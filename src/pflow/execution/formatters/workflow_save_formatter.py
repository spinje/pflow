"""Shared formatters for workflow save operations.

This module provides formatting functions for displaying workflow save success
messages across CLI and MCP interfaces. All formatters return strings that can
be displayed directly or incorporated into structured responses.

Usage:
    >>> from pflow.execution.formatters.workflow_save_formatter import format_save_success
    >>> message = format_save_success(
    ...     name="my-workflow",
    ...     saved_path="/path/to/workflow.pflow.md",
    ...     workflow_ir={"inputs": {"param": {"required": True, "type": "string"}}},
    ... )
    >>> print(message)
    ✓ Saved workflow 'my-workflow' to library
    ...
"""

from typing import Any


def format_save_success(
    name: str,
    saved_path: str,
    workflow_ir: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Format workflow save success message.

    Creates a comprehensive success message showing:
    - Save confirmation with location
    - Execution hint with parameter placeholders
    - Optional parameters list
    - Discovery keywords (if metadata provided)
    - Tip for complex types (array/object/untyped)

    Args:
        name: Workflow name
        saved_path: Path where workflow was saved
        workflow_ir: Workflow IR dict with inputs/outputs
        metadata: Optional metadata dict with keywords

    Returns:
        Formatted success message string

    Example:
        >>> result = format_save_success(
        ...     name="test-workflow",
        ...     saved_path="/path/to/workflow.pflow.md",
        ...     workflow_ir={
        ...         "inputs": {
        ...             "msg": {"required": True, "type": "string"},
        ...             "count": {"required": False, "type": "number"}
        ...         }
        ...     },
        ...     metadata={"keywords": ["test", "example"]}
        ... )
        >>> "Execute with: pflow test-workflow msg=<value>" in result
        True
        >>> "Optional params: count" in result
        True
    """
    lines = [
        f"✓ Saved workflow '{name}' to library",
        f"  Location: {saved_path}",
    ]

    # Add execution hint with parameter information
    execution_hint = format_execution_hint(name, workflow_ir)
    lines.append(f"  ✨ Execute with: {execution_hint}")

    # Add note about optional parameters if there are any
    inputs = workflow_ir.get("inputs", {})
    optional_params = [param_name for param_name, spec in inputs.items() if not spec.get("required", True)]
    if optional_params:
        lines.append(f"  Optional params: {', '.join(optional_params)}")

    # Add tip if workflow has complex parameter types
    if _has_complex_types(workflow_ir):
        lines.append(f"  💡 For parameter details: pflow workflow describe {name}")

    # Add keywords if metadata provided
    if metadata:
        keywords = metadata.get("keywords", [])
        if keywords:
            # Show first 3 keywords with ellipsis
            keywords_str = ", ".join(keywords[:3])
            if len(keywords) > 3:
                keywords_str += "..."
            lines.append(f"  Discoverable by: {keywords_str}")

    return "\n".join(lines)


def format_execution_hint(name: str, workflow_ir: dict[str, Any]) -> str:
    """Format execution hint with parameter type placeholders.

    Generates a command example showing how to execute the workflow with
    type-appropriate placeholders for each parameter.

    Args:
        name: Workflow name
        workflow_ir: Workflow IR with inputs declaration

    Returns:
        Formatted execution command string

    Examples:
        >>> format_execution_hint("my-workflow", {"inputs": {}})
        'pflow my-workflow'

        >>> format_execution_hint("my-workflow", {
        ...     "inputs": {
        ...         "topic": {"required": True, "type": "string"},
        ...         "verbose": {"required": False, "type": "boolean"}
        ...     }
        ... })
        'pflow my-workflow topic=<value> verbose=<true/false>'

        >>> format_execution_hint("analyzer", {
        ...     "inputs": {
        ...         "count": {"required": True, "type": "number"},
        ...         "data": {"required": True, "type": "array"}
        ...     }
        ... })
        'pflow analyzer count=<number> data=<array>'
    """
    base_command = f"pflow {name}"

    # Get inputs from IR
    inputs = workflow_ir.get("inputs", {})
    if not inputs:
        return base_command

    # Separate required and optional parameters
    required_params = []
    optional_params = []

    for param_name, param_spec in inputs.items():
        is_required = param_spec.get("required", True)
        param_type = param_spec.get("type", "string")

        # Create hint based on type - use consistent <type> format
        type_hint = _get_type_hint(param_type)
        hint = f"{param_name}={type_hint}"

        if is_required:
            required_params.append(hint)
        else:
            optional_params.append(hint)

    # Construct full command (required first, then optional)
    all_params = required_params + optional_params
    if all_params:
        return f"{base_command} {' '.join(all_params)}"
    else:
        return base_command


def _get_type_hint(param_type: str) -> str:
    """Get type-appropriate placeholder hint.

    Uses JSON format for arrays and objects to show exact syntax needed.

    Args:
        param_type: Parameter type from workflow IR

    Returns:
        Placeholder string for the type

    Examples:
        >>> _get_type_hint("boolean")
        '<true/false>'
        >>> _get_type_hint("number")
        '<number>'
        >>> _get_type_hint("array")
        "'[...]'"
        >>> _get_type_hint("object")
        "'{...}'"
        >>> _get_type_hint("string")
        '<value>'
    """
    type_hints = {
        "boolean": "<true/false>",
        "number": "<number>",
        "array": "'[...]'",  # Show JSON array format with shell quotes
        "object": "'{...}'",  # Show JSON object format with shell quotes
    }
    return type_hints.get(param_type, "<value>")


def _has_complex_types(workflow_ir: dict[str, Any]) -> bool:
    """Check if workflow has complex parameter types that need explanation.

    Complex types are: array, object, or untyped (generic "value").

    Args:
        workflow_ir: Workflow IR dict with inputs

    Returns:
        True if workflow has any complex parameter types

    Examples:
        >>> _has_complex_types({"inputs": {"name": {"type": "string"}}})
        False
        >>> _has_complex_types({"inputs": {"data": {"type": "array"}}})
        True
        >>> _has_complex_types({"inputs": {"config": {"type": "object"}}})
        True
        >>> _has_complex_types({"inputs": {"value": {"type": "any"}}})
        True
    """
    inputs = workflow_ir.get("inputs", {})

    for param_spec in inputs.values():
        param_type = param_spec.get("type", "string").lower()

        # Check if it's a complex type
        if param_type in ("array", "object", "any", ""):
            return True

    return False
