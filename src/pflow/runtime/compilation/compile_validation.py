"""Pre-compilation validation orchestration.

Consolidates all validation steps that run before IR-to-Flow compilation:
structure validation, input preparation, output validation, and template
validation. Called once from compile_ir_to_flow() as a single orchestration point.
"""

import logging
import sys
from typing import Any

from pflow.core.ir_schema import ValidationError
from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name
from pflow.registry import Registry

from ..template_validation import ValidationWarning, extract_node_outputs, validate_workflow_templates
from .ir_preparation import prepare_inputs, validate_ir_structure

logger = logging.getLogger(__name__)

# Display limits for warning output
MAX_DISPLAYED_WARNINGS_PER_NODE = 10  # Limit to avoid overwhelming terminal output


def display_validation_warnings(warnings: list[ValidationWarning]) -> None:
    """Display validation warnings in a user-friendly format.

    Warnings are grouped by node for cleaner output and displayed to stderr
    so they don't interfere with JSON output mode.

    Args:
        warnings: List of validation warnings to display
    """
    # Group warnings by node for cleaner output
    by_node: dict[str, list[ValidationWarning]] = {}
    for w in warnings:
        if w.node_id not in by_node:
            by_node[w.node_id] = []
        by_node[w.node_id].append(w)

    # Display grouped warnings
    print(file=sys.stderr)  # Blank line for separation
    print(f"Note: {len(warnings)} template(s) use runtime validation:", file=sys.stderr)
    print(file=sys.stderr)

    for node_id, node_warnings in by_node.items():
        # Show node context once
        first = node_warnings[0]

        # Format node type (shorten MCP types)
        node_type_display = first.node_type
        if node_type_display.startswith("mcp-"):
            # Remove 'mcp-' prefix and replace first '-composio-' with '/'
            node_type_display = node_type_display[4:]  # Remove 'mcp-'
            if "-composio-" in node_type_display:
                node_type_display = node_type_display.replace("-composio-", "/", 1)

        print(f"  Node '{node_id}' ({node_type_display}):", file=sys.stderr)
        print(f"    Output type: {first.output_type} (structure unknown at validation time)", file=sys.stderr)
        print(file=sys.stderr)

        # Show each template (limit to avoid overwhelming)
        display_count = min(len(node_warnings), MAX_DISPLAYED_WARNINGS_PER_NODE)
        for w in node_warnings[:display_count]:
            print(f"    \u2022 {w.template}", file=sys.stderr)
            print(f"      Accessing: {w.output_key}.{w.nested_path}", file=sys.stderr)
            print(file=sys.stderr)

        if len(node_warnings) > MAX_DISPLAYED_WARNINGS_PER_NODE:
            remaining = len(node_warnings) - MAX_DISPLAYED_WARNINGS_PER_NODE
            print(f"    ... and {remaining} more template(s)", file=sys.stderr)
            print(file=sys.stderr)

    print("  These templates will be validated during workflow execution.", file=sys.stderr)
    print("  If the nested paths don't exist, the workflow will fail at runtime.", file=sys.stderr)
    print(file=sys.stderr)


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
    """Raise ValidationError with formatted input error messages.

    Args:
        errors: List of (message, path, suggestion) tuples from prepare_inputs

    Raises:
        ValidationError: Always raises with formatted error message
    """
    if len(errors) == 1:
        # Single error - keep current behavior for backward compatibility
        message, path, suggestion = errors[0]
        raise ValidationError(message, path=path, suggestion=suggestion)

    # Multiple errors - aggregate them for better UX
    error_lines = []
    for msg, path, _ in errors:  # Ignore individual suggestions
        # Extract just the input name from path like "inputs.api_key"
        input_name = path.split(".")[-1] if "." in path else path
        error_lines.append(f"  \u2022 '{input_name}' - {msg}")

    combined_message = f"Found {len(errors)} input validation errors:\n" + "\n".join(error_lines)
    raise ValidationError(
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
    from .compiler import CompilationError

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


def _validate_workflow(
    ir_dict: dict[str, Any], registry: Registry, initial_params: dict[str, Any], validate_templates: bool
) -> dict[str, Any]:
    """Validate workflow IR and prepare parameters.

    This function consolidates all validation steps to reduce complexity
    in the main compile_ir_to_flow function.

    Args:
        ir_dict: The workflow IR dictionary
        registry: Registry instance for node metadata lookup
        initial_params: Initial parameters for the workflow
        validate_templates: Whether to validate template variables

    Returns:
        Updated initial_params with defaults applied

    Raises:
        CompilationError: If structure validation fails
        ValidationError: If input/output validation fails
        ValueError: If template validation fails
    """
    from .compiler import CompilationError

    # Step 2: Validate structure
    try:
        validate_ir_structure(ir_dict)
    except CompilationError:
        logger.debug("IR validation failed", extra={"phase": "validation"}, exc_info=True)
        raise

    # Step 2.5: Get and validate template resolution mode
    template_resolution_mode = _get_template_resolution_mode(ir_dict)

    # Store in initial_params for access during node creation
    initial_params["__template_resolution_mode__"] = template_resolution_mode

    logger.debug(
        f"Template resolution mode: {template_resolution_mode}",
        extra={"phase": "validation", "mode": template_resolution_mode},
    )

    # Step 3: Validate inputs and apply defaults
    try:
        # Load settings.env once per compilation
        settings_env = _load_settings_env()

        # Pass settings_env to prepare_inputs
        errors, defaults, env_param_names = prepare_inputs(ir_dict, initial_params, settings_env=settings_env)
        if errors:
            _raise_input_validation_errors(errors)
        initial_params.update(defaults)  # Explicit mutation

        # Store env param names as internal param (for sanitization at metadata storage time)
        if env_param_names:
            initial_params["__env_param_names__"] = list(env_param_names)
    except ValidationError:
        logger.debug("Input validation failed", extra={"phase": "input_validation"}, exc_info=True)
        raise

    # Step 4: Validate outputs
    try:
        _validate_outputs(ir_dict, registry)
    except ValidationError:
        logger.debug("Output validation failed", extra={"phase": "output_validation"}, exc_info=True)
        raise

    # Step 5: Validate templates if requested
    if validate_templates:
        logger.debug("Validating template variables", extra={"phase": "template_validation"})
        template_errors, template_warnings = validate_workflow_templates(ir_dict, initial_params, registry)

        # Display warnings if present (non-blocking)
        if template_warnings:
            display_validation_warnings(template_warnings)

        # Fail only on errors
        if template_errors:
            error_msg = "Template validation failed:\n" + "\n".join(f"  - {e}" for e in template_errors)
            logger.error(
                "Template validation failed",
                extra={"phase": "template_validation", "error_count": len(template_errors), "errors": template_errors},
            )
            raise ValueError(error_msg)

    return initial_params


def _validate_outputs(workflow_ir: dict[str, Any], registry: Registry) -> None:
    """Validate declared workflow outputs can be produced by nodes.

    This function validates that declared outputs CAN be produced by nodes in the workflow.
    Since nodes may write dynamic keys at runtime, this only issues warnings, not errors.

    Args:
        workflow_ir: The workflow IR dictionary containing output declarations
        registry: Registry instance for accessing node metadata

    Raises:
        ValidationError: If output names are invalid identifiers
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
            raise ValidationError(
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
