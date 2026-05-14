"""Parameter type coercion utilities.

Two functions for two pipeline stages:
- coerce_param_for_node: Serializes dict/list → JSON string for nodes expecting "str"
- coerce_workflow_input: Full bidirectional coercion for CLI/env values entering a workflow
"""

import json
import logging
from typing import Any

from pflow.core.validation_utils import VALIDATION_PLACEHOLDER

logger = logging.getLogger(__name__)


def coerce_param_for_node(
    value: Any,
    expected_type: str | None,
) -> Any:
    """Coerce a resolved parameter value for node execution.

    Intentionally narrow: only serializes dict/list → JSON string when the
    node declares the parameter as type "str". All other values pass through
    unchanged. This handles the MCP tool case where a tool declares `param: str`
    but the upstream produced a dict/list.

    This function does NOT perform general type coercion (e.g., str→int).
    At this pipeline stage, values are already in their intended form from
    template resolution or the shared store.

    Note on vocabulary: ``expected_type`` here is the S3 node-Interface type
    (Python-aliased — ``"str"``, ``"dict"``), NOT the S1 workflow-IR vocabulary.
    This is why ``"str"``/``"string"`` are both accepted below, even though
    ``coerce_workflow_input`` (the S1 entry point) rejects Python aliases. See
    ``src/pflow/core/types.py`` module docstring for the surface split.

    Args:
        value: The resolved value to potentially coerce
        expected_type: Declared type from node interface ("str", "dict", etc.)

    Returns:
        Coerced value if conversion needed, otherwise original value

    Examples:
        >>> coerce_param_for_node({"key": "value"}, "str")
        '{"key": "value"}'
        >>> coerce_param_for_node([1, 2, 3], "str")
        '[1, 2, 3]'
        >>> coerce_param_for_node("hello", "str")
        'hello'
        >>> coerce_param_for_node({"key": "value"}, "dict")
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
    """Coerce non-string values to string.

    For dict/list, uses json.dumps() to produce valid JSON strings.
    This is consistent with coerce_param_for_node() and ensures
    nodes expecting JSON strings receive proper JSON, not Python repr.
    """
    if isinstance(value, str):
        return value
    # Use JSON serialization for containers to produce valid JSON strings
    # (e.g., {"a": 1} instead of {'a': 1})
    coerced = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    logger.debug(
        f"Coerced {type(value).__name__} to string for input",
        extra={"original_type": type(value).__name__, **log_context},
    )
    return coerced


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


def _coerce_to_any(value: Any, log_context: dict[str, Any]) -> Any:
    """Passthrough coercion for `type: any`."""
    return value


# Dispatch table for type coercion
_COERCION_DISPATCH = {
    "string": _coerce_to_string,
    "integer": _coerce_to_integer,
    "number": _coerce_to_number,
    "boolean": _coerce_to_boolean,
    "object": _coerce_to_object,
    "array": _coerce_to_array,
    "any": _coerce_to_any,
}


def coerce_workflow_input(
    value: Any,
    declared_type: str | None,
    input_name: str | None = None,
) -> Any:
    """Coerce a CLI/env-provided value to match the workflow input's declared type.

    This function handles the case where CLI parameter parsing (via infer_type)
    converts numeric strings to int/float before the workflow's declared type
    is consulted. It ensures the final value matches the declared type.

    Args:
        value: The value to potentially coerce (may already be coerced by CLI)
        declared_type: Declared type from workflow input (string, integer, number, etc.)
        input_name: Optional input name for logging context

    Returns:
        Coerced value if conversion needed and successful, otherwise original value.

    Note:
        This function uses **lenient coercion** - if conversion fails (e.g., "maybe"
        cannot be converted to boolean), the original value is returned unchanged
        with a warning logged. This allows downstream validation (e.g., code node
        type checking) to catch the error with full context, rather than failing
        early with a generic coercion error. This design choice trades immediate
        error detection for better error messages at the point of use.

    Coercion rules:
        - string: Convert int/float/bool to str
        - integer: Convert str to int (if valid)
        - number: Convert str to float (if valid)
        - boolean: Convert str to bool ("true"/"false"/"1"/"0"/"yes"/"no")
        - object: Parse str as JSON dict (if valid)
        - array: Parse str as JSON list (if valid)
        - No declared type: Return value unchanged

    Examples:
        >>> coerce_workflow_input(1458059302022549698, "string")
        '1458059302022549698'
        >>> coerce_workflow_input("42", "integer")
        42
        >>> coerce_workflow_input("3.14", "number")
        3.14
        >>> coerce_workflow_input("true", "boolean")
        True
        >>> coerce_workflow_input('{"a": 1}', "object")
        {'a': 1}
    """
    if declared_type is None:
        return value

    # Pass through the validation sentinel without trying to coerce it.
    # generate_dummy_parameters() injects this string in place of unresolved
    # declared inputs during structural validation, cache-key prediction, and
    # cross-workflow walker compile passes; treating it as a real value
    # produces stderr warnings like
    # ``Cannot coerce '__validation_placeholder__' to integer``.
    if value == VALIDATION_PLACEHOLDER:
        return value

    log_context: dict[str, Any] = {"input": input_name} if input_name else {}

    # Use dispatch table for coercion
    coercer = _COERCION_DISPATCH.get(declared_type)
    if coercer:
        return coercer(value, log_context)

    # Unknown type - return unchanged
    return value
