"""Error handling utilities for MCP server.

This module provides sanitization functions to ensure LLM-friendly
output without leaking sensitive data.
"""

from typing import Any

from pflow.core.security_utils import SENSITIVE_KEYS


def sanitize_parameters(params: dict[str, Any]) -> dict[str, Any]:
    """Sanitize parameters to redact sensitive values.

    Recursively sanitizes dictionaries to remove:
    - Sensitive values (API keys, tokens, passwords)
    - Very long strings (potential keys/tokens)

    Args:
        params: Parameters dictionary to sanitize

    Returns:
        Sanitized parameters with sensitive values redacted

    Example:
        >>> params = {"api_key": "sk-1234", "name": "test"}
        >>> sanitize_parameters(params)
        {"api_key": "<REDACTED>", "name": "test"}
    """
    sanitized: dict[str, Any] = {}

    for key, value in params.items():
        key_lower = key.lower()

        # Check if key contains sensitive words
        is_sensitive = any(sensitive in key_lower for sensitive in SENSITIVE_KEYS)

        if is_sensitive:
            sanitized[key] = "<REDACTED>"
        elif isinstance(value, dict):
            # Recursively sanitize nested dicts
            sanitized[key] = sanitize_parameters(value)
        elif isinstance(value, str) and len(value) > 100:
            # Truncate very long strings (potential keys/tokens)
            sanitized[key] = value[:20] + "...<truncated>"
        else:
            sanitized[key] = value

    return sanitized
