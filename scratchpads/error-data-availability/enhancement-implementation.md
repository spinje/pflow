# Enhancement Implementation Guide

## Summary

**Question**: Is error data available at line 248 in `_build_error_list()`?
**Answer**: YES - All error data is available in `shared[failed_node]` dictionary.

## Current Implementation (Lines 218-249)

```python
def _build_error_list(
    self, success: bool, action_result: Optional[str], shared_store: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build error list if execution failed."""
    if success:
        return []

    # Extract error information
    error_info = self._extract_error_info(action_result, shared_store)

    # Determine error category
    category = self._determine_error_category(error_info["message"] or "")

    return [
        {
            "source": "runtime",
            "category": category,
            "message": error_info["message"],  # ← Basic message only
            "action": action_result,
            "node_id": error_info["failed_node"],
            "fixable": True,
        }
    ]
```

## Proposed Enhancement

### Option 1: Simple Enhancement (HTTP + MCP Details)

```python
def _build_error_list(
    self, success: bool, action_result: Optional[str], shared_store: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build error list if execution failed."""
    if success:
        return []

    # Extract error information
    error_info = self._extract_error_info(action_result, shared_store)

    # ENHANCEMENT: Access node-level data for richer errors
    failed_node = error_info["failed_node"]
    enhanced_message = error_info["message"]

    if failed_node:
        node_output = shared_store.get(failed_node, {})
        if isinstance(node_output, dict):
            # HTTP-specific enhancement
            if "status_code" in node_output:
                status_code = node_output["status_code"]
                response = node_output.get("response", "")
                enhanced_message = self._format_http_error(status_code, response, enhanced_message)

            # MCP-specific enhancement
            elif "error_details" in node_output:
                details = node_output["error_details"]
                enhanced_message = self._format_mcp_error(details, enhanced_message)

    # Determine error category
    category = self._determine_error_category(enhanced_message or "")

    return [
        {
            "source": "runtime",
            "category": category,
            "message": enhanced_message,  # ← Now enhanced!
            "action": action_result,
            "node_id": failed_node,
            "fixable": True,
        }
    ]

def _format_http_error(
    self, status_code: int, response: Any, fallback: str
) -> str:
    """Format HTTP error with status code and response details.

    Args:
        status_code: HTTP status code (e.g., 404, 500)
        response: Response body (dict, str, or other)
        fallback: Original error message to use if formatting fails

    Returns:
        Enhanced error message
    """
    try:
        # Extract error message from response if available
        if isinstance(response, dict):
            # Try common error keys
            error_msg = (
                response.get("error") or
                response.get("message") or
                response.get("error_description")
            )
            if error_msg:
                return f"HTTP {status_code}: {error_msg}"
            # If no error key, show first 200 chars of response
            import json
            response_str = json.dumps(response)[:200]
            return f"HTTP {status_code}: {response_str}"
        elif isinstance(response, str) and response:
            # Show first 200 chars of string response
            return f"HTTP {status_code}: {response[:200]}"
        else:
            # Just status code
            return f"HTTP {status_code}"
    except Exception:
        # If formatting fails, return fallback
        return fallback

def _format_mcp_error(self, details: dict, fallback: str) -> str:
    """Format MCP error with server and tool details.

    Args:
        details: Error details dict with 'server' and 'tool' keys
        fallback: Original error message

    Returns:
        Enhanced error message
    """
    server = details.get("server", "unknown")
    tool = details.get("tool", "unknown")
    timeout = details.get("timeout", False)

    if timeout:
        return f"MCP {server}.{tool} timed out: {fallback}"
    else:
        return f"MCP {server}.{tool} failed: {fallback}"
```

### Option 2: Comprehensive Enhancement (Structured Error Data)

```python
def _build_error_list(
    self, success: bool, action_result: Optional[str], shared_store: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build error list if execution failed."""
    if success:
        return []

    # Extract error information
    error_info = self._extract_error_info(action_result, shared_store)

    # ENHANCEMENT: Extract all available error context
    failed_node = error_info["failed_node"]
    error_context = self._extract_error_context(failed_node, shared_store)

    # Build enhanced message
    enhanced_message = self._build_enhanced_message(
        error_info["message"],
        error_context
    )

    # Determine error category
    category = self._determine_error_category(enhanced_message or "")

    return [
        {
            "source": "runtime",
            "category": category,
            "message": enhanced_message,
            "action": action_result,
            "node_id": failed_node,
            "fixable": True,
            # EXTRA: Include structured context for advanced error handling
            "context": error_context,
        }
    ]

def _extract_error_context(
    self, failed_node: Optional[str], shared_store: dict[str, Any]
) -> dict[str, Any]:
    """Extract all available error context from node output.

    Args:
        failed_node: Node ID that failed
        shared_store: Shared store with namespaced node data

    Returns:
        Dictionary with error context (empty if no context available)
    """
    if not failed_node:
        return {}

    node_output = shared_store.get(failed_node, {})
    if not isinstance(node_output, dict):
        return {}

    context = {}

    # HTTP-specific context
    if "status_code" in node_output:
        context["type"] = "http"
        context["status_code"] = node_output["status_code"]
        context["response"] = node_output.get("response")
        context["response_headers"] = node_output.get("response_headers", {})

    # MCP-specific context
    elif "error_details" in node_output:
        context["type"] = "mcp"
        context["server"] = node_output["error_details"].get("server")
        context["tool"] = node_output["error_details"].get("tool")
        context["timeout"] = node_output["error_details"].get("timeout", False)
        if "result" in node_output:
            context["result"] = node_output["result"]

    # Generic error context
    if "error" in node_output:
        context["error"] = node_output["error"]

    return context

def _build_enhanced_message(
    self, base_message: str, context: dict[str, Any]
) -> str:
    """Build enhanced error message using available context.

    Args:
        base_message: Original error message
        context: Error context from _extract_error_context()

    Returns:
        Enhanced error message
    """
    if not context:
        return base_message

    error_type = context.get("type")

    if error_type == "http":
        return self._format_http_error(
            context.get("status_code"),
            context.get("response"),
            base_message
        )
    elif error_type == "mcp":
        return self._format_mcp_error(context, base_message)
    else:
        return base_message
```

## Testing the Enhancement

```python
# Test case 1: HTTP 404 error
shared_store = {
    "http-fetch": {
        "error": "HTTP 404",
        "status_code": 404,
        "response": {"error": "Resource not found"}
    },
    "__execution__": {
        "failed_node": "http-fetch"
    }
}

errors = service._build_error_list(False, "error", shared_store)
assert "HTTP 404: Resource not found" in errors[0]["message"]

# Test case 2: MCP timeout error
shared_store = {
    "mcp-github-create-issue": {
        "error": "MCP tool timed out after 30 seconds",
        "error_details": {
            "server": "github",
            "tool": "create-issue",
            "timeout": True
        }
    },
    "__execution__": {
        "failed_node": "mcp-github-create-issue"
    }
}

errors = service._build_error_list(False, "error", shared_store)
assert "MCP github.create-issue timed out" in errors[0]["message"]

# Test case 3: Generic error (no special handling)
shared_store = {
    "some-node": "not a dict",
    "__execution__": {
        "failed_node": "some-node"
    }
}

errors = service._build_error_list(False, "error", shared_store)
# Should handle gracefully without crashing
assert len(errors) == 1
```

## Recommendation

**Use Option 1** (Simple Enhancement) for immediate value:
- Minimal code changes
- Clear benefit (HTTP status codes, MCP server/tool names)
- Easy to test
- No breaking changes

**Consider Option 2** (Comprehensive Enhancement) for future:
- Structured error context for advanced error handling
- Enables richer error display in UI
- Supports error analytics
- More complex but more extensible

## Implementation Steps

1. Add helper methods (`_format_http_error`, `_format_mcp_error`)
2. Modify `_build_error_list()` to call helpers
3. Add test cases for HTTP and MCP errors
4. Verify enhanced messages in integration tests
5. Update error display to show enhanced messages

## No Breaking Changes

- Existing error extraction continues to work
- Only the message content changes (becomes more detailed)
- All error structure fields remain the same
- Backward compatible with existing error handling code
