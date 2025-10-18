"""Error handling utilities for MCP server.

This module provides sanitization functions to ensure LLM-friendly
output without leaking sensitive data.
"""

from typing import Any

from pflow.core.security_utils import SENSITIVE_KEYS


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
        {"api_key": "<REDACTED>", "name": "test"}

        >>> params = {"safe_name": "secret", "channel": "C09"}
        >>> sanitize_parameters(params, always_redact_keys={"safe_name"})
        {"safe_name": "<REDACTED>", "channel": "C09"}
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
            # Recursively sanitize nested dicts (don't pass always_redact_keys - only applies to top level)
            sanitized[key] = sanitize_parameters(value, always_redact_keys=None)
        elif isinstance(value, list):
            # Sanitize lists (may contain dicts with sensitive data)
            sanitized[key] = [
                sanitize_parameters(item, always_redact_keys=None) if isinstance(item, dict) else item for item in value
            ]
        elif isinstance(value, str) and len(value) > 100:
            # Truncate very long strings (potential keys/tokens)
            sanitized[key] = value[:20] + "...<truncated>"
        else:
            sanitized[key] = value

    return sanitized
