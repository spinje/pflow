"""Parameter type coercion utilities.

Provides coercion between Python types and declared parameter types.
The main use case is serializing dict/list to JSON strings when the
declared parameter type is "str" - enabling MCP tools that expect
JSON-formatted string parameters.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def coerce_to_declared_type(
    value: Any,
    expected_type: str | None,
) -> Any:
    """Coerce a value to match its declared parameter type.

    When expected_type is "str" and value is dict/list, serialize to JSON string.
    This enables MCP tools that declare `param: str` but expect JSON content
    to receive properly serialized JSON strings instead of Python dicts.

    Args:
        value: The value to potentially coerce
        expected_type: Declared type from node interface ("str", "dict", etc.)

    Returns:
        Coerced value if conversion needed, otherwise original value

    Examples:
        >>> coerce_to_declared_type({"key": "value"}, "str")
        '{"key": "value"}'
        >>> coerce_to_declared_type([1, 2, 3], "str")
        '[1, 2, 3]'
        >>> coerce_to_declared_type("hello", "str")
        'hello'
        >>> coerce_to_declared_type({"key": "value"}, "dict")
        {'key': 'value'}
    """
    if expected_type is None:
        return value

    # Normalize type aliases
    normalized_type = expected_type.lower()

    # dict/list -> str: Serialize to JSON
    if normalized_type in ("str", "string") and isinstance(value, (dict, list)):
        try:
            serialized = json.dumps(value)
            logger.debug(
                f"Coerced {type(value).__name__} to JSON string for str-typed parameter",
                extra={"original_type": type(value).__name__},
            )
            return serialized
        except (TypeError, ValueError) as e:
            # Non-serializable objects (custom classes, file handles, etc.)
            # Fall back to original value - let downstream handle the type mismatch
            logger.warning(
                f"Cannot serialize {type(value).__name__} to JSON: {e}. Passing original value.",
                extra={"original_type": type(value).__name__, "error": str(e)},
            )
            return value

    return value
