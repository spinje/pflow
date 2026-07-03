"""API warning detection for node execution results.

Detects API errors in node output that should surface as warnings rather than
clean successes. Uses a provenance-aware priority system:
1. Explicit failure flags (status:error, ok:false, success:false, etc.)
2. Error codes
3. Validation patterns (defer to normal error handling)
4. Resource patterns (surface as API warning)

When an error matches both validation and resource patterns, validation wins.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ErrorSignal:
    message: str
    from_explicit_failure_flag: bool


def detect_api_warning(node_id: str, shared: dict[str, Any], *, node_type_name: str | None = None) -> str | None:
    """Detect API errors that should surface as warnings.

    Explicit failure flags are trusted as self-reported API failures. For
    message-only signals, returns None for validation-style errors so normal
    error handling can proceed.

    Strategy:
    1. Check explicit failure flags first
    2. Check error codes
    3. Check for validation patterns (defer to normal execution errors)
    4. Check for resource patterns (surface warning)
    5. Default to no API warning

    Args:
        node_id: The node identifier to check in shared store
        shared: The shared store containing node outputs
        node_type_name: Optional runtime node type. When provided, canonical
            result-wrapper unwrapping is limited to MCP nodes.

    Returns:
        Warning message string if API warning detected, None otherwise
    """
    # Get node output
    if node_id not in shared:
        logger.debug(f"Node {node_id} not in shared store for API warning check")
        return None

    output = shared.get(node_id)
    logger.debug(
        f"Checking {node_id} output for API warning. Type: {type(output).__name__}, Keys: {list(output.keys()) if isinstance(output, dict) else 'N/A'}"
    )

    # Handle MCP nested responses
    output = unwrap_mcp_response(output, inspect_result=node_type_name in (None, "MCPNode"))
    if not output:
        return None

    # Type guard: API warnings only make sense for dict responses
    # Binary data, strings, and primitive types cannot have API error fields
    if not isinstance(output, dict):
        logger.debug(f"Node {node_id} output is not a dict ({type(output).__name__}), skipping API warning check")
        return None

    # Extract error information
    error_code = extract_error_code(output)
    error_signal = _extract_error_signal(output)

    if not error_signal:
        return None  # No error detected

    error_msg = error_signal.message

    # Explicit top-level failure flags are a self-report from the tool/API. Do
    # not discard them just because the free-text message is novel.
    if error_signal.from_explicit_failure_flag:
        return _format_explicit_failure_warning(error_msg, error_code)

    # PRIORITY 1: Check error codes (most reliable signal)
    code_handled, code_warning = _warning_from_error_code(error_code, error_msg)
    if code_handled:
        return code_warning

    return _warning_from_message(error_msg)


def _format_explicit_failure_warning(error_msg: str, error_code: str | None) -> str:
    if error_code:
        logger.info(f"Explicit API failure detected: {error_code} - {error_msg}")
        return f"API error ({error_code}): {error_msg}"
    logger.info(f"Explicit API failure detected: {error_msg}")
    return f"API error: {error_msg}"


def _warning_from_error_code(error_code: str | None, error_msg: str) -> tuple[bool, str | None]:
    if not error_code:
        return False, None

    error_category = _categorize_by_error_code(error_code)
    if error_category == "validation":
        # Validation error - leave it to normal execution handling
        logger.debug(f"Validation error detected: {error_code} - {error_msg}")
        return True, None

    if error_category == "resource":
        # Resource error - surface as API warning
        logger.info(f"Resource error detected: {error_code} - {error_msg}")
        return True, f"API error ({error_code}): {error_msg}"

    # Unknown error code - continue to message analysis.
    return False, None


def _warning_from_message(error_msg: str) -> str | None:
    # PRIORITY 2: Check if it's a validation error
    if _is_validation_error(error_msg):
        logger.debug(f"Validation error detected: {error_msg}")
        return None

    # PRIORITY 3: Check if it's a resource error
    if _is_resource_error(error_msg):
        logger.info(f"Resource error detected: {error_msg}")
        return f"API error: {error_msg}"

    # DEFAULT: When in doubt, do not convert to an API warning.
    logger.debug(f"Unknown error type, skipping API warning conversion: {error_msg}")
    return None


def unwrap_mcp_response(output: Any, *, inspect_result: bool = True) -> dict | None:
    """Unwrap MCP nested responses to get actual API response."""
    if not isinstance(output, dict):
        return None

    # Canonical MCP ``result`` wrapper — JSON-string or dict form. Both are
    # gated on ``inspect_result`` so this unwrapping stays limited to MCP nodes
    # (a non-MCP node's ``result`` is payload data, not an API response).
    if inspect_result:
        parsed = _parse_mcp_json_result(output)
        if parsed is not None:
            return parsed

        if isinstance(output.get("result"), dict):
            result = output["result"]
            return _unwrap_successful_data(result) or result

    # Handle MCP dict with nested data
    data = _unwrap_successful_data(output)
    if data is not None:
        return data

    # Handle HTTP node with response field
    if "response" in output and "status_code" in output:
        status_code = output.get("status_code", 200)
        # Only check 2xx responses for API errors
        if 200 <= status_code < 300:
            return output.get("response")
        # For 4xx/5xx, HTTP node already handles it
        return None

    return output


def _parse_mcp_json_result(output: dict) -> dict | None:
    """Parse MCP JSON result field if present."""
    if "result" not in output or not isinstance(output["result"], str):
        return None

    try:
        parsed = json.loads(output["result"])
        if isinstance(parsed, dict):
            # Check for nested data in successful MCP response
            if parsed.get("successful") and "data" in parsed:
                data = parsed["data"]
                # Ensure data is a dict before returning
                if isinstance(data, dict):
                    return data
                return None
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def _unwrap_successful_data(output: dict) -> dict | None:
    """Return nested MCP data from successful wrapper payloads."""
    if output.get("successful") is True and "data" in output:
        data = output["data"]
        if isinstance(data, dict):
            return data
        return None
    return None


def extract_error_code(output: dict) -> str | None:
    """Extract error code from various API response formats."""
    # Defensive type check
    if not isinstance(output, dict):
        return None

    # Try different common locations for error codes
    candidates = [
        output.get("error_code"),
        output.get("errorCode"),
        output.get("code"),
        output.get("error", {}).get("code") if isinstance(output.get("error"), dict) else None,
        output.get("statusCode"),
        output.get("status_code"),
    ]

    for code in candidates:
        if code:
            return str(code)
    return None


def _check_boolean_error_flags(output: dict) -> str | None:
    """Check boolean error flags in API response.

    Args:
        output: API response dictionary

    Returns:
        Error message if found, None otherwise
    """
    # Defensive type check
    if not isinstance(output, dict):
        return None

    # Check various boolean error indicators
    if output.get("ok") is False:
        return _first_error_message(output.get("error"), default="API request failed")

    if output.get("success") is False:
        return _first_error_message(output.get("error"), output.get("message"), default="API request failed")

    if output.get("successful") is False or output.get("successfull") is False:  # MCP typo
        return _first_error_message(output.get("error"), output.get("message"), default="API request failed")

    if output.get("succeeded") is False:
        return _first_error_message(output.get("error"), output.get("message"), default="API request failed")

    if output.get("isError") is True:
        error_info = output.get("error", {})
        return _first_error_message(error_info, output.get("message"), default="API request failed")

    return None


def _check_status_field(output: dict) -> str | None:
    """Check status field for error indicators.

    Args:
        output: API response dictionary

    Returns:
        Error message if found, None otherwise
    """
    # Defensive type check
    if not isinstance(output, dict):
        return None

    status = str(output.get("status", "")).lower()
    if status in ["error", "failed", "failure"]:
        return _first_error_message(output.get("message"), output.get("error"), default="API request failed")
    return None


def _check_graphql_errors(output: dict) -> str | None:
    """Check for GraphQL errors in API response.

    Args:
        output: API response dictionary

    Returns:
        Error message if found, None otherwise
    """
    # Defensive type check
    if not isinstance(output, dict):
        return None

    if "errors" in output and output.get("errors"):
        errors = output["errors"]
        if isinstance(errors, list) and len(errors) > 0:
            first_error = errors[0]
            if isinstance(first_error, dict):
                message = first_error.get("message", "GraphQL error")
                # Ensure message is a string
                return str(message)
            else:
                return str(first_error)
    return None


def extract_error_message(output: dict) -> str | None:
    """Extract error message from API response.

    Args:
        output: API response dictionary

    Returns:
        Error message if found, None otherwise
    """
    # Defensive type check
    if not isinstance(output, dict):
        return None

    signal = _extract_error_signal(output)
    if signal is None:
        return None
    return signal.message


def _extract_error_signal(output: dict) -> _ErrorSignal | None:
    """Extract error text and whether it came from an explicit failure flag."""
    # Defensive type check
    if not isinstance(output, dict):
        return None

    # Check boolean error flags
    error_msg = _check_boolean_error_flags(output)
    if error_msg:
        return _ErrorSignal(error_msg, from_explicit_failure_flag=True)

    # Check status field
    error_msg = _check_status_field(output)
    if error_msg:
        return _ErrorSignal(error_msg, from_explicit_failure_flag=True)

    # Check for GraphQL errors
    error_msg = _check_graphql_errors(output)
    if error_msg:
        return _ErrorSignal(error_msg, from_explicit_failure_flag=False)

    # Check if there's an error field with content
    if output.get("error"):
        error_text = _coerce_error_message(output.get("error"))
        if error_text:
            return _ErrorSignal(error_text, from_explicit_failure_flag=False)

    return None


def _first_error_message(*values: Any, default: str) -> str:
    for value in values:
        message = _coerce_error_message(value)
        if message:
            return message
    return default


def _coerce_error_message(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            message = _coerce_error_message(item)
            if message:
                return message
        return None
    if isinstance(value, dict):
        for key in ("message", "error", "reason"):
            message = _coerce_error_message(value.get(key))
            if message:
                return message
        return None
    return str(value)


def _categorize_by_error_code(code: str) -> str:
    """Categorize error by error code."""
    code_upper = str(code).upper()

    # Validation error codes
    VALIDATION_CODES = [
        "VALIDATION_ERROR",
        "INVALID_PARAMETER",
        "INVALID_REQUEST",
        "BAD_REQUEST",
        "MALFORMED",
        "TYPE_ERROR",
        "FORMAT_ERROR",
        "MISSING_PARAMETER",
        "MISSING_FIELD",
        "INVALID_FORMAT",
        "SCHEMA_ERROR",
        "INVALID_INPUT",
        "PARAMETER_ERROR",
        "400",  # Bad Request usually means fixable
    ]

    # Resource error codes
    RESOURCE_CODES = [
        "NOT_FOUND",
        "RESOURCE_NOT_FOUND",
        "CHANNEL_NOT_FOUND",
        "USER_NOT_FOUND",
        "FILE_NOT_FOUND",
        "ITEM_NOT_FOUND",
        "PERMISSION_DENIED",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "RATE_LIMITED",
        "RATE_LIMIT",
        "QUOTA_EXCEEDED",
        "401",  # Unauthorized
        "403",  # Forbidden
        "404",  # Not Found
        "429",  # Rate Limited
    ]

    for vc in VALIDATION_CODES:
        if vc in code_upper:
            return "validation"

    for rc in RESOURCE_CODES:
        if rc in code_upper:
            return "resource"

    return "unknown"


def _is_validation_error(error_msg: str) -> bool:
    """Check if error message indicates a validation/parameter error."""
    if not error_msg:
        return False

    msg_lower = error_msg.lower()

    # Validation error indicators
    VALIDATION_PATTERNS = [
        # Format/type errors
        "should be a",
        "must be a",
        "expected a",
        "expecting",
        "invalid format",
        "wrong format",
        "incorrect format",
        "type mismatch",
        "wrong type",
        "invalid type",
        # Validation errors
        "validation error",
        "validation failed",
        "invalid input",
        "invalid request",
        "invalid parameter",
        "invalid value",
        "invalid data",
        "malformed",
        "badly formed",
        # Missing/required errors
        "missing required",
        "required field",
        "required parameter",
        "must provide",
        "must include",
        "must specify",
        # Structure errors
        "should be valid",
        "must be valid",
        "not a valid",
        "does not match",
        "does not conform",
        "schema error",
        # Specific format errors
        "invalid date",
        "invalid email",
        "invalid url",
        "invalid json",
        "parse error",
        "syntax error",
        # Type-specific errors
        "input should be",
        "parameter should be",
        "value should be",
    ]

    return any(pattern in msg_lower for pattern in VALIDATION_PATTERNS)


def _is_resource_error(error_msg: str) -> bool:
    """Check if error message indicates a resource/permission error."""
    if not error_msg:
        return False

    msg_lower = error_msg.lower()

    # Resource error indicators
    RESOURCE_PATTERNS = [
        # Not found errors
        "not found",
        "not_found",
        "does not exist",
        "doesn't exist",
        "no such",
        "cannot find",
        "could not find",
        "unable to find",
        "404",
        "missing",
        "unavailable",
        # Permission errors
        "permission denied",
        "access denied",
        "unauthorized",
        "forbidden",
        "not authorized",
        "no access",
        "restricted",
        "403",
        "401",
        # Rate limiting
        "rate limit",
        "quota exceeded",
        "too many requests",
        "throttled",
        "429",
        # Authentication
        "authentication failed",
        "invalid token",
        "expired token",
        "invalid api key",
        "bad credentials",
    ]

    # Only return True if we're confident it's a resource error
    # AND it doesn't also look like a validation error
    is_resource = any(pattern in msg_lower for pattern in RESOURCE_PATTERNS)
    is_validation = _is_validation_error(error_msg)

    # If it looks like both, prefer the validation classification
    return is_resource and not is_validation
