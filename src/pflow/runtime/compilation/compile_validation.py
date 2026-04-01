"""Pre-compilation validation orchestration.

Consolidates all validation steps that run before IR-to-Flow compilation:
structure validation, input preparation, output validation, and template
validation. Called once from compile_workflow() as a single orchestration point.
"""

import logging
from typing import Any

from pflow.core.exceptions import CompilationError, SchemaValidationError
from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name
from pflow.registry import Registry

from ..template_validation import extract_node_outputs
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


def _validate_data_flow_at_compile_time(ir_dict: dict[str, Any]) -> None:
    """Validate data flow at compile time (cycles, forward refs, non-existent node refs).

    Passes check_inputs=False because the compiler has initial_params containing
    variables not declared in IR inputs — undefined input checking is a semantic
    concern for WorkflowValidator.

    Args:
        ir_dict: The workflow IR dictionary

    Raises:
        CompilationError: If data flow validation finds errors
    """
    from pflow.core.workflow.data_flow import validate_data_flow

    data_flow_errors = validate_data_flow(ir_dict, check_inputs=False)
    if data_flow_errors:
        lines = [f"  - {e}" for e in data_flow_errors[:5]]
        if len(data_flow_errors) > 5:
            lines.append(f"  ... and {len(data_flow_errors) - 5} more errors")
        error_msg = "Data flow validation failed:\n" + "\n".join(lines)
        raise CompilationError(
            message=error_msg,
            phase="data_flow_validation",
        )


def _prepare_compilation(
    ir_dict: dict[str, Any],
    registry: Registry,
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

    # Data flow validation — prevents compiler producing Flows with cycles
    _validate_data_flow_at_compile_time(ir_dict)

    # Template resolution mode (reads IR or settings, writes to initial_params)
    template_resolution_mode = _get_template_resolution_mode(ir_dict)
    initial_params["__template_resolution_mode__"] = template_resolution_mode

    logger.debug(
        f"Template resolution mode: {template_resolution_mode}",
        extra={"phase": "validation", "mode": template_resolution_mode},
    )

    # Input validation and defaults (5-tier resolution, writes defaults to initial_params)
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

    # Output validation (validates output names can trace to node outputs)
    try:
        _validate_outputs(ir_dict, registry)
    except SchemaValidationError:
        logger.debug("Output validation failed", extra={"phase": "output_validation"}, exc_info=True)
        raise

    return initial_params, [], resolved_defaults, resolved_env_param_names


def _validate_outputs(workflow_ir: dict[str, Any], registry: Registry) -> None:
    """Validate declared workflow outputs can be produced by nodes.

    This function validates that declared outputs CAN be produced by nodes in the workflow.
    Since nodes may write dynamic keys at runtime, this only issues warnings, not errors.

    Args:
        workflow_ir: The workflow IR dictionary containing output declarations
        registry: Registry instance for accessing node metadata

    Raises:
        SchemaValidationError: If output names are invalid identifiers
    """
    # Extract output declarations (backward compatible with workflows without outputs)
    outputs = workflow_ir.get("outputs", {})

    # If no outputs declared, nothing to validate
    if not outputs:
        logger.debug("No outputs declared for workflow", extra={"phase": "output_validation"})
        return

    logger.debug(
        "Validating workflow outputs", extra={"phase": "output_validation", "declared_outputs": list(outputs.keys())}
    )

    # First validate all output names are valid Python identifiers
    for output_name, _output_spec in outputs.items():
        if not is_valid_parameter_name(output_name):
            error_msg = get_parameter_validation_error(output_name, "output")
            raise SchemaValidationError(
                message=error_msg,
                path=f"outputs.{output_name}",
                suggestion="Avoid shell special characters like $, |, >, <, &, ;",
            )

    # Get all possible outputs from nodes in the workflow
    all_node_outputs = extract_node_outputs(workflow_ir, registry)

    logger.debug(
        f"Found {len(all_node_outputs)} possible outputs from nodes",
        extra={"phase": "output_validation", "available_outputs": sorted(all_node_outputs.keys())},
    )

    # Validate each declared output can be produced
    for output_name, output_spec in outputs.items():
        # If output has a 'source' field, it will be resolved from that expression
        if isinstance(output_spec, dict) and "source" in output_spec:
            logger.debug(
                f"Output '{output_name}' uses source expression: {output_spec['source']}",
                extra={"phase": "output_validation", "output": output_name},
            )
            continue  # Skip validation for outputs with source field

        # Check if output can be traced to any node
        if output_name not in all_node_outputs:
            # Issue warning, not error, since nodes may write dynamic keys
            logger.warning(
                f"Declared output '{output_name}' cannot be traced to any node in the workflow. "
                f"This may be fine if nodes write dynamic keys.",
                extra={
                    "phase": "output_validation",
                    "output": output_name,
                    "available_outputs": sorted(all_node_outputs.keys()),
                },
            )
        else:
            logger.debug(
                f"Output '{output_name}' can be produced by workflow nodes",
                extra={"phase": "output_validation", "output": output_name},
            )

    logger.debug("Output validation complete", extra={"phase": "output_validation"})
