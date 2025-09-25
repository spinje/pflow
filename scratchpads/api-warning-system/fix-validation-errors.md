# API Warning System Fix: Validation vs Resource Errors

## Date: 2025-01-24

## Executive Summary

The current API warning system incorrectly prevents repair of validation errors (e.g., wrong data format) by treating them the same as resource errors (e.g., channel not found). This document provides a precise implementation plan to fix this critical issue.

## The Problem

### Current Behavior (BROKEN)
```
User sends: {"values": {"A1": "data"}}  # Wrong format
API returns: "Input should be a valid list"
System: Marks as non-repairable ❌
Result: Repair never runs, user stuck
```

### Desired Behavior (FIXED)
```
User sends: {"values": {"A1": "data"}}  # Wrong format
API returns: "Input should be a valid list"
System: Recognizes as validation error ✓
Result: Repair fixes to [["data"]], workflow succeeds
```

## Core Insight

API errors fall into THREE categories, not two:

1. **Workflow Errors** (Repairable by workflow repair)
   - Template errors: `${node.wrong_field}`
   - Missing node parameters
   - Wrong connections

2. **Validation Errors** (Repairable by workflow repair) ← WE MISSED THIS
   - Wrong data format (dict vs list)
   - Missing required fields
   - Type mismatches
   - Invalid date formats

3. **Resource Errors** (NOT repairable by workflow repair)
   - Channel/user/file not found
   - Permission denied
   - Rate limits
   - Authentication failures

## Implementation Specification

### File to Modify
`src/pflow/runtime/instrumented_wrapper.py`

### Replace Current `_detect_api_warning` Method

```python
def _detect_api_warning(self, shared: dict) -> Optional[str]:
    """
    Detect non-repairable API errors (resource/permission issues).

    Returns None for validation errors to allow repair attempts.

    Strategy:
    1. Check error codes first (most reliable)
    2. Check for validation patterns (let repair handle)
    3. Check for resource patterns (prevent repair)
    4. Default to repairable (loop detection is safety net)
    """
    # Get node output
    if self.node_id not in shared:
        return None

    output = shared.get(self.node_id)

    # Handle MCP nested responses
    output = self._unwrap_mcp_response(output)
    if not output:
        return None

    # Extract error information
    error_code = self._extract_error_code(output)
    error_msg = self._extract_error_message(output)

    if not error_msg:
        return None  # No error detected

    # PRIORITY 1: Check error codes (most reliable signal)
    if error_code:
        error_category = self._categorize_by_error_code(error_code)

        if error_category == "validation":
            # Validation error - let repair handle it
            logger.debug(f"Validation error detected (repairable): {error_code} - {error_msg}")
            return None

        elif error_category == "resource":
            # Resource error - prevent repair
            logger.info(f"Resource error detected (non-repairable): {error_code} - {error_msg}")
            return f"API error ({error_code}): {error_msg}"

        # Unknown error code - continue to message analysis

    # PRIORITY 2: Check if it's a validation error (repairable)
    if self._is_validation_error(error_msg):
        logger.debug(f"Validation error detected (repairable): {error_msg}")
        return None  # Let repair handle it

    # PRIORITY 3: Check if it's a resource error (not repairable)
    if self._is_resource_error(error_msg):
        logger.info(f"Resource error detected (non-repairable): {error_msg}")
        return f"API error: {error_msg}"

    # DEFAULT: When in doubt, let repair try
    # Loop detection will prevent infinite attempts
    logger.debug(f"Unknown error type, allowing repair attempt: {error_msg}")
    return None
```

### Add Helper Methods

```python
def _unwrap_mcp_response(self, output: Any) -> Optional[dict]:
    """Unwrap MCP nested responses to get actual API response."""
    if not isinstance(output, dict):
        return None

    # Handle MCP JSON string result
    if "result" in output and isinstance(output["result"], str):
        try:
            import json
            parsed = json.loads(output["result"])
            if isinstance(parsed, dict):
                # Check for nested data in successful MCP response
                if parsed.get("successful") and "data" in parsed:
                    return parsed["data"]
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Handle MCP dict with nested data
    if output.get("successful") is True and "data" in output:
        return output["data"]

    return output

def _extract_error_code(self, output: dict) -> Optional[str]:
    """Extract error code from various API response formats."""
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

def _extract_error_message(self, output: dict) -> Optional[str]:
    """Extract error message from API response."""
    # Check various error indicators
    if output.get("ok") is False:
        return output.get("error", "API request failed")

    if output.get("success") is False:
        return output.get("error") or output.get("message", "API request failed")

    if output.get("succeeded") is False:
        return output.get("error") or output.get("message", "API request failed")

    if output.get("isError") is True:
        error_info = output.get("error", {})
        if isinstance(error_info, dict):
            return error_info.get("message", "API request failed")
        return str(error_info)

    # Check status field
    status = str(output.get("status", "")).lower()
    if status in ["error", "failed", "failure"]:
        return output.get("message") or output.get("error", "API request failed")

    return None

def _categorize_by_error_code(self, code: str) -> str:
    """Categorize error by error code."""
    code_upper = str(code).upper()

    # Validation error codes (REPAIRABLE)
    VALIDATION_CODES = [
        "VALIDATION_ERROR", "INVALID_PARAMETER", "INVALID_REQUEST",
        "BAD_REQUEST", "MALFORMED", "TYPE_ERROR", "FORMAT_ERROR",
        "MISSING_PARAMETER", "MISSING_FIELD", "INVALID_FORMAT",
        "SCHEMA_ERROR", "INVALID_INPUT", "PARAMETER_ERROR",
        "400",  # Bad Request usually means fixable
    ]

    # Resource error codes (NOT REPAIRABLE)
    RESOURCE_CODES = [
        "NOT_FOUND", "RESOURCE_NOT_FOUND", "CHANNEL_NOT_FOUND",
        "USER_NOT_FOUND", "FILE_NOT_FOUND", "ITEM_NOT_FOUND",
        "PERMISSION_DENIED", "UNAUTHORIZED", "FORBIDDEN",
        "RATE_LIMITED", "RATE_LIMIT", "QUOTA_EXCEEDED",
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

def _is_validation_error(self, error_msg: str) -> bool:
    """Check if error message indicates a validation/parameter error."""
    if not error_msg:
        return False

    msg_lower = error_msg.lower()

    # Validation error indicators
    VALIDATION_PATTERNS = [
        # Format/type errors
        "should be a", "must be a", "expected a", "expecting",
        "invalid format", "wrong format", "incorrect format",
        "type mismatch", "wrong type", "invalid type",

        # Validation errors
        "validation error", "validation failed", "invalid input",
        "invalid request", "invalid parameter", "invalid value",
        "invalid data", "malformed", "badly formed",

        # Missing/required errors
        "missing required", "required field", "required parameter",
        "must provide", "must include", "must specify",

        # Structure errors
        "should be valid", "must be valid", "not a valid",
        "does not match", "does not conform", "schema error",

        # Specific format errors
        "invalid date", "invalid email", "invalid url",
        "invalid json", "parse error", "syntax error",
    ]

    return any(pattern in msg_lower for pattern in VALIDATION_PATTERNS)

def _is_resource_error(self, error_msg: str) -> bool:
    """Check if error message indicates a resource/permission error."""
    if not error_msg:
        return False

    msg_lower = error_msg.lower()

    # Resource error indicators
    RESOURCE_PATTERNS = [
        # Not found errors
        "not found", "not_found", "does not exist", "doesn't exist",
        "no such", "cannot find", "could not find", "unable to find",
        "404", "missing", "unavailable",

        # Permission errors
        "permission denied", "access denied", "unauthorized",
        "forbidden", "not authorized", "no access", "restricted",
        "403", "401",

        # Rate limiting
        "rate limit", "quota exceeded", "too many requests",
        "throttled", "429",

        # Authentication
        "authentication failed", "invalid token", "expired token",
        "invalid api key", "bad credentials",
    ]

    # Only return True if we're confident it's a resource error
    # AND it doesn't also look like a validation error
    is_resource = any(pattern in msg_lower for pattern in RESOURCE_PATTERNS)
    is_validation = self._is_validation_error(error_msg)

    # If it looks like both, prefer validation (repairable)
    return is_resource and not is_validation
```

## Testing Plan

### Test Case 1: Google Sheets Validation Error
```python
# Input
output = {
    "successful": False,
    "error": "Invalid request data provided\n- Input should be a valid list"
}

# Expected
assert _detect_api_warning(output) is None  # Should allow repair
```

### Test Case 2: Slack Channel Not Found
```python
# Input
output = {
    "ok": False,
    "error": "channel_not_found"
}

# Expected
assert _detect_api_warning(output) == "API error: channel_not_found"  # Prevent repair
```

### Test Case 3: Error Code Priority
```python
# Input (has both code and message)
output = {
    "error_code": "VALIDATION_ERROR",
    "message": "not found"  # Message suggests resource error
}

# Expected
assert _detect_api_warning(output) is None  # Code takes priority, validation = repairable
```

## Implementation Steps

1. **Backup current implementation**
   ```bash
   cp src/pflow/runtime/instrumented_wrapper.py src/pflow/runtime/instrumented_wrapper.py.backup
   ```

2. **Replace `_detect_api_warning` method** with the new implementation above

3. **Add the helper methods** to the InstrumentedNodeWrapper class

4. **Test with Google Sheets case**
   - Verify validation error goes to repair
   - Verify repair can fix the data structure
   - Verify workflow succeeds after repair

5. **Test with Slack case**
   - Verify channel_not_found prevents repair
   - Verify loop detection isn't needed

6. **Run test suite**
   ```bash
   make test
   ```

## Key Principles

1. **Error codes are truth** - Most reliable signal of error type
2. **Explicit validation detection** - Actively identify repairable errors
3. **Conservative resource detection** - Only block obvious non-repairable
4. **Default to repairable** - Let loop detection handle edge cases
5. **Validation > Resource** - If ambiguous, assume repairable

## Success Criteria

- ✅ Google Sheets "Input should be valid list" → Goes to repair
- ✅ Slack "channel_not_found" → Skips repair
- ✅ Unknown errors → Go to repair (loop detection prevents waste)
- ✅ Error codes respected when present
- ✅ No breaking changes to existing behavior

## Rollback Plan

If issues arise:
```bash
mv src/pflow/runtime/instrumented_wrapper.py.backup src/pflow/runtime/instrumented_wrapper.py
```

## Future Improvements

1. **Learning system** - Track which errors repair successfully fixes
2. **Configuration** - Allow users to customize repairable patterns
3. **Metrics** - Track repair success rate by error type
4. **Caching** - Remember error classifications within session

## Conclusion

This fix properly distinguishes validation errors (repairable) from resource errors (not repairable), allowing the repair system to fix format/parameter issues while still preventing futile attempts on missing resources. The implementation prioritizes error codes when available and uses conservative pattern matching as fallback, with loop detection as the ultimate safety net.