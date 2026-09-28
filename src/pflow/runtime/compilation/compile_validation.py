"""Pre-compilation validation orchestration.

Consolidates all validation steps that run before IR-to-Flow compilation:
structure validation, input preparation, output validation, and template
validation. Called once from compile_workflow() as a single orchestration point.
"""

import logging
from typing import Any

from pflow.core.exceptions import CompilationError, SchemaValidationError
from pflow.core.ir_schema import missing_output_source_suggestion
from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name

from .ir_preparation import prepare_inputs, validate_ir_structure

logger = logging.getLogger(__name__)


def _load_settings_env() -> dict[str, str]:
    """Load settings.env for workflow input population.

    Returns empty dict on any error (non-fatal).

    Returns:
        Dictionary of environment variables from settings.env
    """
    try:
        from pflow.core.settings import SettingsManager

        manager = SettingsManager()
        settings = manager.load()
        return settings.env
    except Exception as e:
        logger.warning(f"Failed to load settings.env: {e}")
        return {}


def _raise_input_validation_errors(errors: list[tuple[str, str, str]]) -> None:
    """Raise SchemaValidationError with formatted input error messages.

    Args:
        errors: List of (message, path, suggestion) tuples from prepare_inputs

    Raises:
        SchemaValidationError: Always raises with formatted error message
    """
    if len(errors) == 1:
        # Single error - keep current behavior for backward compatibility
        message, path, suggestion = errors[0]
        raise SchemaValidationError(message, path=path, suggestion=suggestion)

    # Multiple errors - aggregate them for better UX
    error_lines = []
    for msg, path, _ in errors:  # Ignore individual suggestions
        # Extract just the input name from path like "inputs.api_key"
        input_name = path.split(".")[-1] if "." in path else path
        error_lines.append(f"  \u2022 '{input_name}' - {msg}")

    combined_message = f"Found {len(errors)} input validation errors:\n" + "\n".join(error_lines)
    raise SchemaValidationError(
        message=combined_message,
        path="inputs",
        suggestion="Fix all validation errors above before compiling the workflow",
    )


def _get_template_resolution_mode(ir_dict: dict[str, Any]) -> str:
    """Get and validate template resolution mode from IR or settings.

    Args:
        ir_dict: The workflow IR dictionary

    Returns:
        Validated template resolution mode ('strict' or 'permissive')

    Raises:
        CompilationError: If mode value is invalid
    """
    template_resolution_mode = ir_dict.get("template_resolution_mode")
    if template_resolution_mode is None:
        # Load from global settings if not specified in workflow
        from pflow.core.settings import SettingsManager

        settings = SettingsManager().load()
        template_resolution_mode = settings.runtime.template_resolution_mode

    # Validate mode value
    if template_resolution_mode not in ["strict", "permissive"]:
        raise CompilationError(
            message=f"Invalid template_resolution_mode: {template_resolution_mode}",
            phase="validation",
            details={"valid_modes": ["strict", "permissive"], "provided": template_resolution_mode},
        )

    return template_resolution_mode


def _validate_data_flow_at_compile_time(ir_dict: dict[str, Any], workflow_path: str | None = None) -> None:
    """Validate data flow at compile time (cycles, forward refs, non-existent node refs).

    Passes check_inputs=False because the compiler has initial_params containing
    variables not declared in IR inputs — undefined input checking is a semantic
    concern for WorkflowValidator.

    The structured diagnostics produced by ``validate_data_flow`` are attached
    to ``CompilationError.wrapped_diagnostics`` so the compile-time path carries
    the same rich structure (paths, suggestions, similar_names, available_fields)
    that the pre-execution validator produces — instead of flattening them into
    a single bullet-list message.

    ``workflow_path`` is threaded through so cache-namespaced findings emitted
    via ``make_diagnostic`` (cache.invalid-on-non-llm, cache.prompt-body-*,
    llm.thinking-temperature-mismatch) carry the real path in
    ``context["affected_workflow"]`` rather than the ``"<unknown>"`` placeholder.
    Mirrors the threading convention at every other validation call site
    (validator.py:278, analyze.py:_run_full_validation through the full
    ``WorkflowValidator.validate`` pipeline).

    Args:
        ir_dict: The workflow IR dictionary
        workflow_path: Resolved workflow path for diagnostic attribution; ``None``
            when unavailable (e.g., inline-IR test paths) — diagnostics fall
            back to the ``"<unknown>"`` placeholder.

    Raises:
        CompilationError: If data flow validation finds errors
    """
    from pflow.core.diagnostic import Severity
    from pflow.core.workflow.data_flow import validate_data_flow

    data_flow_diagnostics = validate_data_flow(ir_dict, check_inputs=False, workflow_path=workflow_path)
    errors = [diagnostic for diagnostic in data_flow_diagnostics if diagnostic.severity == Severity.ERROR]
    if errors:
        summary = f"Data flow validation failed ({len(errors)} error{'s' if len(errors) != 1 else ''})"
        raise CompilationError(
            message=summary,
            phase="data_flow_validation",
            wrapped_diagnostics=errors,
        )


def _prepare_compilation(
    ir_dict: dict[str, Any],
    initial_params: dict[str, Any],
) -> tuple[dict[str, Any], list[Any], dict[str, Any], set[str]]:
    """Prepare IR for compilation: validate structure, check data flow, resolve inputs.

    Structure and data flow validation are compiler prerequisites — without them
    the compiler crashes (KeyError on missing 'nodes') or produces broken Flows
    (cycles that hang at runtime). These are NOT pre-execution checks.

    Template validation is handled by WorkflowValidator in the Runner and is
    not duplicated here. The display_validation_warnings() call that previously
    printed directly to stderr is removed — warnings route through the Runner.

    Returns:
        (mutated initial_params, validation_warnings)
        Warnings are currently always [] — template warnings come from
        WorkflowValidator, not the compiler.
    """
    # Structure validation — compiler prerequisite (prevents KeyError on ir_dict["nodes"])
    try:
        validate_ir_structure(ir_dict)
    except CompilationError:
        logger.debug("IR validation failed", extra={"phase": "validation"}, exc_info=True)
        raise

    # Data flow validation — prevents compiler producing Flows with cycles.
    # ``_pflow_workflow_file`` is set by Runner / WorkflowExecutor before the
    # compiler runs; threaded through so cache-namespaced findings carry the
    # real path rather than the ``"<unknown>"`` placeholder.
    workflow_path = initial_params.get("_pflow_workflow_file")
    _validate_data_flow_at_compile_time(ir_dict, workflow_path=str(workflow_path) if workflow_path else None)

    # Template resolution mode (reads IR or settings, writes to initial_params)
    template_resolution_mode = _get_template_resolution_mode(ir_dict)
    initial_params["__template_resolution_mode__"] = template_resolution_mode

    logger.debug(
        f"Template resolution mode: {template_resolution_mode}",
        extra={"phase": "validation", "mode": template_resolution_mode},
    )

    # Input validation and preparation (5-tier resolution plus coerced replacements in initial_params)
    resolved_defaults: dict[str, Any] = {}
    resolved_env_param_names: set[str] = set()
    try:
        settings_env = _load_settings_env()
        errors, defaults, env_param_names = prepare_inputs(ir_dict, initial_params, settings_env=settings_env)
        if errors:
            _raise_input_validation_errors(errors)
        initial_params.update(defaults)
        resolved_defaults = defaults
        resolved_env_param_names = env_param_names

        if env_param_names:
            initial_params["__env_param_names__"] = list(env_param_names)
    except SchemaValidationError:
        logger.debug("Input validation failed", extra={"phase": "input_validation"}, exc_info=True)
        raise

    # Output validation (valid names, every output names a source)
    try:
        _validate_outputs(ir_dict)
    except SchemaValidationError:
        logger.debug("Output validation failed", extra={"phase": "output_validation"}, exc_info=True)
        raise

    return initial_params, [], resolved_defaults, resolved_env_param_names


def _validate_outputs(workflow_ir: dict[str, Any]) -> None:
    """Validate declared workflow outputs: valid names, and every output names a source.

    The IR schema also requires ``source``, but compile-only callers (web UI
    pre-flight, cache-key prediction, programmatic ``compile_workflow``) never run
    the schema, so the rule is enforced here too with the same fix hint.

    Args:
        workflow_ir: The workflow IR dictionary containing output declarations

    Raises:
        SchemaValidationError: If an output name is invalid or an output has no source
    """
    for output_name, output_spec in workflow_ir.get("outputs", {}).items():
        if not is_valid_parameter_name(output_name):
            raise SchemaValidationError(
                message=get_parameter_validation_error(output_name, "output"),
                path=f"outputs.{output_name}",
                suggestion="Avoid shell special characters like $, |, >, <, &, ;",
            )
        if not isinstance(output_spec, dict) or output_spec.get("source") is None:
            raise SchemaValidationError(
                message=f"Output '{output_name}' has no source",
                path=f"outputs.{output_name}",
                suggestion=missing_output_source_suggestion(output_name),
            )
