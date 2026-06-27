"""Security utilities for sensitive data handling.

This module provides shared constants and functions for identifying and masking
sensitive parameters across CLI and MCP server contexts.
"""

import re
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


# Split a parameter name into words on snake_case / kebab-case / dotted / camelCase boundaries.
_WORD_BOUNDARY = re.compile(r"[_\-.\s]+|(?<=[a-z0-9])(?=[A-Z])")


def _word_signature(key: str) -> str:
    """Normalize a parameter name to a sentinel-bounded ``_word_word_`` form (lowercased words), so a plain
    substring test matches WHOLE words only: ``api_key`` / ``X-API-Key`` / ``apiKey`` all become
    ``_api_key_``, while ``author`` becomes ``_author_`` and so never matches the sensitive word ``auth``."""
    return "_" + "_".join(word.lower() for word in _WORD_BOUNDARY.split(key) if word) + "_"


_SENSITIVE_SIGNATURES = tuple(_word_signature(name) for name in SENSITIVE_KEYS)


def is_sensitive_parameter(key: str) -> bool:
    """Check whether a parameter NAME denotes sensitive data (credentials, tokens, ...).

    Word-aware and case-insensitive: a sensitive name must appear as WHOLE words in ``key`` (across
    snake_case / kebab-case / dotted / camelCase), so ``api_key`` / ``X-API-Key`` / ``apiKey`` match while
    ``author`` / ``secretary`` / ``tokens`` do NOT — the earlier raw-substring check redacted those by
    mistake. A name with no word delimiter (e.g. ``myapikey``) is one word and won't match an embedded
    ``apikey``; that trade buys the false-positive fix and is the accepted boundary (real secret params are
    delimited). The single source of truth — ``sanitize_parameters`` / ``mask_sensitive_value`` / the rerun
    display / the run-detail panel all defer here.

    Examples:
        >>> is_sensitive_parameter("api_key")
        True
        >>> is_sensitive_parameter("API_KEY")
        True
        >>> is_sensitive_parameter("author")
        False
        >>> is_sensitive_parameter("username")
        False
    """
    signature = _word_signature(key)
    return any(sig in signature for sig in _SENSITIVE_SIGNATURES)


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

        # Redact env-derived keys (always_redact_keys) and sensitive-NAMED keys (the shared word-aware rule)
        if key in always_redact_keys or is_sensitive_parameter(key):
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
