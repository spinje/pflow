"""API warning detection for node execution results.

Detects API errors in node output that should surface as warnings rather than
failures. Uses a 3-tier priority system:
1. Error codes (most reliable signal)
2. Validation patterns (defer to normal error handling)
3. Resource patterns (surface as API warning)

When an error matches both validation and resource patterns, validation wins.
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def detect_api_warning(node_id: str, shared: dict[str, Any]) -> Optional[str]:
    """Detect API errors that should surface as warnings.

    Returns None for validation-style errors so normal error handling can proceed.

    Strategy:
    1. Check error codes first (most reliable)
    2. Check for validation patterns (defer to normal execution errors)
    3. Check for resource patterns (surface warning)
    4. Default to no API warning

    Args:
        node_id: The node identifier to check in shared store
        shared: The shared store containing node outputs

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
    output = unwrap_mcp_response(output)
    if not output:
        return None

    # Type guard: API warnings only make sense for dict responses
    # Binary data, strings, and primitive types cannot have API error fields
    if not isinstance(output, dict):
        logger.debug(f"Node {node_id} output is not a dict ({type(output).__name__}), skipping API warning check")
        return None

    # Extract error information
    error_code = extract_error_code(output)
    error_msg = extract_error_message(output)

    if not error_msg:
        return None  # No error detected

    # PRIORITY 1: Check error codes (most reliable signal)
    if error_code:
        error_category = _categorize_by_error_code(error_code)

        if error_category == "validation":
            # Validation error - leave it to normal execution handling
            logger.debug(f"Validation error detected: {error_code} - {error_msg}")
            return None

        elif error_category == "resource":
            # Resource error - surface as API warning
            logger.info(f"Resource error detected: {error_code} - {error_msg}")
            return f"API error ({error_code}): {error_msg}"

        # Unknown error code - continue to message analysis

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


def unwrap_mcp_response(output: Any) -> Optional[dict]:
    """Unwrap MCP nested responses to get actual API response."""
    if not isinstance(output, dict):
        return None

    # Try to unwrap MCP JSON string result
    parsed = _parse_mcp_json_result(output)
    if parsed is not None:
        return parsed

    # Handle MCP dict with nested data
    if output.get("successful") is True and "data" in output:
        data = output["data"]
        # Ensure data is a dict before returning
        if isinstance(data, dict):
            return data
        return None

    # Handle HTTP node with response field
    if "response" in output and "status_code" in output:
        status_code = output.get("status_code", 200)
        # Only check 2xx responses for API errors
        if 200 <= status_code < 300:
            return output.get("response")
        # For 4xx/5xx, HTTP node already handles it
        return None

    return output


def _parse_mcp_json_result(output: dict) -> Optional[dict]:
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


def extract_error_code(output: dict) -> Optional[str]:
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


def _check_boolean_error_flags(output: dict) -> Optional[str]:
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
        return output.get("error") or "API request failed"

    if output.get("success") is False:
        return output.get("error") or output.get("message") or "API request failed"

    if output.get("successful") is False or output.get("successfull") is False:  # MCP typo
        return output.get("error") or output.get("message") or "API request failed"

    if output.get("succeeded") is False:
        return output.get("error") or output.get("message") or "API request failed"

    if output.get("isError") is True:
        error_info = output.get("error", {})
        if isinstance(error_info, dict):
            return error_info.get("message") or "API request failed"
        return str(error_info) if error_info else "API request failed"

    return None


def _check_status_field(output: dict) -> Optional[str]:
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
        return output.get("message") or output.get("error") or "API request failed"
    return None


def _check_graphql_errors(output: dict) -> Optional[str]:
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


def extract_error_message(output: dict) -> Optional[str]:
    """Extract error message from API response.

    Args:
        output: API response dictionary

    Returns:
        Error message if found, None otherwise
    """
    # Defensive type check
    if not isinstance(output, dict):
        return None

    # Check boolean error flags
    error_msg = _check_boolean_error_flags(output)
    if error_msg:
        return error_msg

    # Check status field
    error_msg = _check_status_field(output)
    if error_msg:
        return error_msg

    # Check for GraphQL errors
    error_msg = _check_graphql_errors(output)
    if error_msg:
        return error_msg

    # Check if there's an error field with content
    if output.get("error"):
        return output.get("error")

    return None


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
