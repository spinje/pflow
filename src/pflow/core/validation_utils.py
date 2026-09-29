"""Shared validation utilities for pflow."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from pflow.core.diagnostic import Diagnostic

VALIDATION_PLACEHOLDER: Final[str] = "__validation_placeholder__"
"""Sentinel value substituted for unresolved declared inputs during
structural validation, cache-key prediction, and cross-workflow walker
compile passes. Consumers that handle real workflow values must short-
circuit when they see this string — it is never a meaningful payload."""


def generate_dummy_parameters(inputs: dict[str, Any]) -> dict[str, Any]:
    """Generate dummy parameters for workflow validation.

    Creates placeholder values for all declared inputs to enable
    structural validation without real values.

    Args:
        inputs: Declared workflow inputs

    Returns:
        Dictionary of dummy parameter values

    Example:
        >>> inputs = {"api_key": {"type": "string"}, "repo": {"type": "string"}}
        >>> generate_dummy_parameters(inputs)
        {'api_key': '__validation_placeholder__', 'repo': '__validation_placeholder__'}
    """
    return dict.fromkeys(inputs, VALIDATION_PLACEHOLDER)


def validate_with_placeholder_inputs(workflow_ir: dict[str, Any], *, workflow_file: Path | None) -> list["Diagnostic"]:
    """Validate a workflow without real input values -- the shared call behind
    ``--validate-only``, ``pflow save``, and ``analyze-cache``.

    Declared inputs get placeholder values. ``workflow_file`` reaches the
    validator on both channels it reads -- the ``workflow_file`` argument and
    ``_pflow_workflow_file`` in the params -- so relative sub-workflow paths
    resolve against the workflow's directory, never the current directory.
    Callers pass the path once here instead of assembling those params by hand.
    """
    from pflow.core.workflow.validator import WorkflowValidator
    from pflow.registry import Registry

    params = generate_dummy_parameters(workflow_ir.get("inputs") or {})
    if workflow_file is not None:
        params["_pflow_workflow_file"] = str(workflow_file)
    return WorkflowValidator.validate(
        workflow_ir=workflow_ir,
        extracted_params=params,
        registry=Registry(),
        skip_node_types=False,
        workflow_file=workflow_file,
    )


def is_valid_parameter_name(name: str) -> bool:
    """Check if a parameter name is valid.

    Allows most strings except:
    - Empty strings
    - Strings with shell special characters that could cause security issues

    This is more permissive than Python's isidentifier(), allowing:
    - Hyphens: api-key, user-name
    - Dots: file.path, data.field
    - Numbers at start: 123-start, 2fa-token

    Args:
        name: The parameter name to validate

    Returns:
        True if the name is valid, False otherwise
    """
    if not name or not name.strip():
        return False

    # Reject reserved framework keys — __*__ bypasses NamespacedSharedStore
    # and writes directly to root store, corrupting execution state
    if name.startswith("__") and name.endswith("__"):
        return False

    # Disallow shell special characters and whitespace that could cause issues
    # - Shell special chars: dangerous in commands or template expansion
    # - Spaces/tabs: break CLI parsing, incompatible with template regex
    dangerous_chars = ["$", "|", ">", "<", "&", ";", "`", "\n", "\r", "\0", '"', "'", "\\", " ", "\t"]
    return not any(char in name for char in dangerous_chars)


def get_parameter_validation_error(name: str, param_type: str = "parameter") -> str:
    """Get a descriptive error message for invalid parameter names.

    Args:
        name: The invalid parameter name
        param_type: Type of parameter (e.g., "input", "output", "parameter")

    Returns:
        Error message describing why the name is invalid
    """
    if not name or not name.strip():
        return f"Invalid {param_type} name - cannot be empty"

    if name.startswith("__") and name.endswith("__"):
        return f"Invalid {param_type} name '{name}' - names wrapped in double underscores are reserved for internal use"

    # Check for specific dangerous characters and provide helpful messages
    if " " in name:
        return f"Invalid {param_type} name '{name}' - cannot contain spaces (use hyphens or underscores instead)"
    elif "\t" in name:
        return f"Invalid {param_type} name '{name}' - cannot contain tabs"
    elif "$" in name:
        return f"Invalid {param_type} name '{name}' - cannot contain '$' (conflicts with template syntax)"
    elif any(char in name for char in ["|", ">", "<", "&", ";", "`"]):
        return f"Invalid {param_type} name '{name}' - cannot contain shell special characters"
    elif any(char in name for char in ["\n", "\r", "\0"]):
        return f"Invalid {param_type} name '{name}' - cannot contain control characters"
    elif any(char in name for char in ['"', "'"]):
        return f"Invalid {param_type} name '{name}' - cannot contain quotes"
    elif "\\" in name:
        return f"Invalid {param_type} name '{name}' - cannot contain backslashes"

    # Generic fallback
    return f"Invalid {param_type} name '{name}' - contains invalid characters"
