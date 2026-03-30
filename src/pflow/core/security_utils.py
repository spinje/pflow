"""Security utilities for sensitive data handling.

This module provides shared constants and functions for identifying and masking
sensitive parameters across CLI and MCP server contexts.
"""

from typing import Any

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


def sanitize_parameters(params: dict[str, Any], always_redact_keys: set[str] | None = None) -> dict[str, Any]:
    """Sanitize parameters to redact sensitive values.

    Recursively sanitizes dictionaries to remove:
    - Parameters specified in always_redact_keys (e.g., from settings.env)
    - Sensitive values (API keys, tokens, passwords)
    - Very long strings (potential keys/tokens)

    Args:
        params: Parameters dictionary to sanitize
        always_redact_keys: Set of param names to always redact (regardless of name pattern)

    Returns:
        Sanitized parameters with sensitive values redacted

    Example:
        >>> params = {"api_key": "sk-1234", "name": "test"}
        >>> sanitize_parameters(params)
        {'api_key': '<REDACTED>', 'name': 'test'}

        >>> params = {"safe_name": "secret", "channel": "C09"}
        >>> sanitize_parameters(params, always_redact_keys={"safe_name"})
        {'safe_name': '<REDACTED>', 'channel': 'C09'}
    """
    always_redact_keys = always_redact_keys or set()
    sanitized: dict[str, Any] = {}

    for key, value in params.items():
        # Skip internal params (start with __)
        if key.startswith("__"):
            continue

        key_lower = key.lower()

        # Check if key should always be redacted (e.g., from env)
        if key in always_redact_keys or any(sensitive in key_lower for sensitive in SENSITIVE_KEYS):
            sanitized[key] = "<REDACTED>"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_parameters(value, always_redact_keys=None)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_parameters(item, always_redact_keys=None) if isinstance(item, dict) else item for item in value
            ]
        elif isinstance(value, str) and len(value) > 100:
            sanitized[key] = value[:20] + "...<truncated>"
        else:
            sanitized[key] = value

    return sanitized
