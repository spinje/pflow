"""Security utilities for sensitive data handling.

This module provides shared constants and functions for identifying and masking
sensitive parameters across CLI and MCP server contexts.
"""

# Sensitive parameter names to mask/redact
# This set is used to identify parameters that may contain credentials, tokens,
# or other sensitive information that shouldn't be logged or displayed
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "token",
    "api_token",
    "access_token",
    "auth_token",
    "api_key",
    "apikey",
    "api-key",
    "secret",
    "client_secret",
    "private_key",
    "ssh_key",
    "secret_key",
    "credential",
    "credentials",
    "authorization",
    "auth",
}


def is_sensitive_parameter(key: str) -> bool:
    """Check if a parameter name indicates sensitive data.

    Performs case-insensitive matching against known sensitive parameter names.

    Args:
        key: Parameter name to check

    Returns:
        True if the parameter name contains sensitive keywords

    Examples:
        >>> is_sensitive_parameter("password")
        True
        >>> is_sensitive_parameter("API_KEY")
        True
        >>> is_sensitive_parameter("username")
        False
    """
    key_lower = key.lower()
    return any(sensitive in key_lower for sensitive in SENSITIVE_KEYS)


def mask_sensitive_value(key: str, value: str, mask_text: str = "<REDACTED>") -> str:
    """Mask a value if the parameter name is sensitive.

    Args:
        key: Parameter name
        value: Parameter value
        mask_text: Text to use for masking (default: "<REDACTED>")

    Returns:
        Original value if not sensitive, mask_text if sensitive

    Examples:
        >>> mask_sensitive_value("password", "secret123")
        '<REDACTED>'
        >>> mask_sensitive_value("username", "john")
        'john'
    """
    if is_sensitive_parameter(key):
        return mask_text
    return value
