"""JSON parsing utilities for pflow.

Provides safe, consistent JSON parsing with:
- Quick rejection for non-JSON strings (performance)
- Size limits to prevent memory exhaustion (security)
- Graceful fallback for invalid JSON
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Security: Prevent memory exhaustion from maliciously large JSON
DEFAULT_MAX_JSON_SIZE = 10 * 1024 * 1024  # 10MB

# Max chars to show in debug log previews
_LOG_PREVIEW_LENGTH = 100


def try_parse_json(
    value: str,
    *,
    max_size: int = DEFAULT_MAX_JSON_SIZE,
) -> tuple[bool, Any]:
    """Attempt to parse a string as JSON.

    Returns a tuple of (success, result) where:
    - (True, parsed_value) if parsing succeeded
    - (False, original_value) if parsing failed or was skipped

    The two-value return distinguishes between:
    - "Parsed successfully to None": (True, None)
    - "Failed to parse": (False, original_string)

    Args:
        value: String that may contain JSON
        max_size: Maximum string size to attempt parsing (default 10MB)

    Returns:
        Tuple of (success: bool, result: Any)

    Examples:
        >>> try_parse_json('{"a": 1}')
        (True, {'a': 1})
        >>> try_parse_json('not json')
        (False, 'not json')
        >>> try_parse_json('null')
        (True, None)
    """
    if not isinstance(value, str):
        return (False, value)

    # Strip whitespace - critical for shell output with trailing newlines
    text = value.strip()

    # Quick rejection: empty string
    if not text:
        return (False, value)

    # Security: size limit (check after strip)
    if len(text) > max_size:
        logger.warning(
            f"Skipping JSON parse: string exceeds size limit ({len(text):,} > {max_size:,} bytes)",
        )
        return (False, value)

    # Quick rejection: doesn't look like JSON
    # Valid JSON starts with: { [ " t(rue) f(alse) n(ull) - or digit
    first_char = text[0]
    if first_char not in '{["tfn-0123456789':
        return (False, value)

    # Attempt parse
    try:
        parsed = json.loads(text)
        logger.debug(
            f"Parsed JSON string to {type(parsed).__name__}",
            extra={"preview": text[:_LOG_PREVIEW_LENGTH] if len(text) > _LOG_PREVIEW_LENGTH else text},
        )
        return (True, parsed)
    except (json.JSONDecodeError, ValueError) as e:
        logger.debug(
            f"String is not valid JSON: {type(e).__name__}",
            extra={"preview": text[:_LOG_PREVIEW_LENGTH] if len(text) > _LOG_PREVIEW_LENGTH else text},
        )
        return (False, value)


def parse_json_or_original(
    value: str,
    *,
    max_size: int = DEFAULT_MAX_JSON_SIZE,
) -> Any:
    """Parse JSON string or return original value unchanged.

    Convenience wrapper around try_parse_json() for cases where
    you don't need to know whether parsing succeeded.

    Args:
        value: String that may contain JSON
        max_size: Maximum string size to attempt parsing

    Returns:
        Parsed JSON value or original string
    """
    _success, result = try_parse_json(value, max_size=max_size)
    return result
