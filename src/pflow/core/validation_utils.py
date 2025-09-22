"""Shared validation utilities for pflow."""


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

    # Disallow shell special characters that could cause security issues
    # These could be dangerous in shell commands or template expansion
    dangerous_chars = ["$", "|", ">", "<", "&", ";", "`", "\n", "\r", "\0", '"', "'", "\\"]
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
    if "$" in name:
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
