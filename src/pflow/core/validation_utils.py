"""Shared validation utilities for pflow."""

from typing import Any


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
        {"api_key": "__validation_placeholder__", "repo": "__validation_placeholder__"}
    """
    dummy_params = {}

    for key, _input_spec in inputs.items():
        # Use validation placeholder
        dummy_params[key] = "__validation_placeholder__"

    return dummy_params


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


def generate_validation_suggestions(errors: list[dict[str, str]]) -> list[str]:
    """Generate actionable suggestions for fixing validation errors.

    Args:
        errors: List of error dicts with 'message' and 'type' keys

    Returns:
        List of unique suggestions for fixing the errors

    Example:
        >>> errors = [{"message": "Unknown node type: 'foo'", "type": "validation"}]
        >>> generate_validation_suggestions(errors)
        ["Use 'registry list' to see available nodes"]
    """
    suggestions = []

    for error in errors:
        message = error.get("message", "").lower()

        if "template" in message or "${" in message:
            suggestions.append("Check template syntax: ${node.output}")
        elif "node type" in message or "unknown node" in message:
            suggestions.append("Use 'registry list' to see available nodes")
        elif "cycle" in message or "circular" in message:
            suggestions.append("Remove circular dependencies between nodes")
        elif "unused" in message and "input" in message:
            suggestions.append("Remove unused inputs or use them in node parameters")

    # De-duplicate suggestions
    return list(set(suggestions))
