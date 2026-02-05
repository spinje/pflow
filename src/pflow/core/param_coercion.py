"""Parameter type coercion utilities.

Provides coercion between Python types and declared parameter types.

Two main use cases:
1. Serializing dict/list to JSON strings when declared type is "str" (for MCP tools)
2. Coercing CLI-provided values to match workflow input declarations
   (e.g., int → str when input declares type: string)
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Type aliases for normalization (consistent with type_checker.py)
_TYPE_ALIASES = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
}


def _normalize_type(type_name: str) -> str:
    """Normalize type name to canonical form."""
    lower = type_name.lower()
    return _TYPE_ALIASES.get(lower, lower)


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


# =============================================================================
# Input coercion helpers (extracted to reduce complexity of main function)
# =============================================================================


def _coerce_to_string(value: Any, log_context: dict[str, Any]) -> Any:
    """Coerce non-string values to string."""
    if not isinstance(value, str):
        coerced = str(value)
        logger.debug(
            f"Coerced {type(value).__name__} to string for input",
            extra={"original_type": type(value).__name__, **log_context},
        )
        return coerced
    return value


def _coerce_to_integer(value: Any, log_context: dict[str, Any]) -> Any:
    """Coerce string values to integer."""
    if isinstance(value, str):
        try:
            coerced = int(value)
            logger.debug(
                "Coerced string to integer for input",
                extra={"original_value": value, **log_context},
            )
            return coerced
        except ValueError:
            logger.warning(
                f"Cannot coerce '{value}' to integer",
                extra={"original_value": value, **log_context},
            )
    return value


def _coerce_to_number(value: Any, log_context: dict[str, Any]) -> Any:
    """Coerce string values to float."""
    if isinstance(value, str):
        try:
            coerced = float(value)
            logger.debug(
                "Coerced string to float for input",
                extra={"original_value": value, **log_context},
            )
            return coerced
        except ValueError:
            logger.warning(
                f"Cannot coerce '{value}' to number",
                extra={"original_value": value, **log_context},
            )
    return value


def _coerce_to_boolean(value: Any, log_context: dict[str, Any]) -> Any:
    """Coerce string values to boolean."""
    if isinstance(value, str):
        lower_val = value.lower()
        if lower_val in ("true", "1", "yes"):
            logger.debug(
                "Coerced string to True for input",
                extra={"original_value": value, **log_context},
            )
            return True
        elif lower_val in ("false", "0", "no"):
            logger.debug(
                "Coerced string to False for input",
                extra={"original_value": value, **log_context},
            )
            return False
        else:
            logger.warning(
                f"Cannot coerce '{value}' to boolean",
                extra={"original_value": value, **log_context},
            )
    return value


def _coerce_to_object(value: Any, log_context: dict[str, Any]) -> Any:
    """Coerce JSON string to dict."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                logger.debug(
                    "Coerced JSON string to dict for input",
                    extra={"original_value": value[:50], **log_context},
                )
                return parsed
            logger.warning(
                f"JSON parsed to {type(parsed).__name__}, expected dict",
                extra={"original_value": value[:50], **log_context},
            )
        except json.JSONDecodeError:
            logger.warning(
                "Cannot parse string as JSON object",
                extra={"original_value": value[:50], **log_context},
            )
    return value


def _coerce_to_array(value: Any, log_context: dict[str, Any]) -> Any:
    """Coerce JSON string to list."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                logger.debug(
                    "Coerced JSON string to list for input",
                    extra={"original_value": value[:50], **log_context},
                )
                return parsed
            logger.warning(
                f"JSON parsed to {type(parsed).__name__}, expected list",
                extra={"original_value": value[:50], **log_context},
            )
        except json.JSONDecodeError:
            logger.warning(
                "Cannot parse string as JSON array",
                extra={"original_value": value[:50], **log_context},
            )
    return value


# Dispatch table for type coercion
_COERCION_DISPATCH = {
    "string": _coerce_to_string,
    "integer": _coerce_to_integer,
    "number": _coerce_to_number,
    "boolean": _coerce_to_boolean,
    "object": _coerce_to_object,
    "array": _coerce_to_array,
}


def coerce_input_to_declared_type(
    value: Any,
    declared_type: str | None,
    input_name: str | None = None,
) -> Any:
    """Coerce a CLI-provided value to match the workflow input's declared type.

    This function handles the case where CLI parameter parsing (via infer_type)
    converts numeric strings to int/float before the workflow's declared type
    is consulted. It ensures the final value matches the declared type.

    Args:
        value: The value to potentially coerce (may already be coerced by CLI)
        declared_type: Declared type from workflow input (string, integer, number, etc.)
        input_name: Optional input name for logging context

    Returns:
        Coerced value if conversion needed and successful, otherwise original value

    Coercion rules:
        - string: Convert int/float/bool to str
        - integer: Convert str to int (if valid)
        - number: Convert str to float (if valid)
        - boolean: Convert str to bool ("true"/"false"/"1"/"0"/"yes"/"no")
        - object: Parse str as JSON dict (if valid)
        - array: Parse str as JSON list (if valid)
        - No declared type: Return value unchanged

    Examples:
        >>> coerce_input_to_declared_type(1458059302022549698, "string")
        '1458059302022549698'
        >>> coerce_input_to_declared_type("42", "integer")
        42
        >>> coerce_input_to_declared_type("3.14", "number")
        3.14
        >>> coerce_input_to_declared_type("true", "boolean")
        True
        >>> coerce_input_to_declared_type('{"a": 1}', "object")
        {'a': 1}
    """
    if declared_type is None:
        return value

    normalized_type = _normalize_type(declared_type)
    log_context: dict[str, Any] = {"input": input_name} if input_name else {}

    # Use dispatch table for coercion
    coercer = _COERCION_DISPATCH.get(normalized_type)
    if coercer:
        return coercer(value, log_context)

    # Unknown type - return unchanged
    return value
