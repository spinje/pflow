# Error Information Flow Report

**Date**: 2025-10-02
**Context**: Task 71 - Understanding how raw API errors are captured and what repair LLM sees

## Executive Summary

**Finding**: The repair LLM receives **highly summarized error information** with critical details lost. Raw API error responses, HTTP bodies, and detailed MCP tool outputs are **NOT** passed to the repair LLM, severely limiting its ability to fix API validation errors.

**Impact**: When GitHub/Slack/Discord APIs return validation errors (e.g., "field 'title' is required"), the repair LLM only sees generic summaries like "API validation error" without the actual field names, constraints, or available options.

---

## Error Capture: HTTP Node

**Location**: `src/pflow/nodes/http/http.py`

### What Gets Stored in Shared Store

```python
# Line 169-183 in post() method
def post(self, shared, prep_res, exec_res):
    # ALWAYS stores these keys (success or failure):
    shared["response"] = exec_res["response"]           # Full API response (dict or str)
    shared["status_code"] = exec_res["status_code"]     # HTTP status code
    shared["response_headers"] = exec_res["headers"]    # Full headers
    shared["response_time"] = exec_res.get("duration", 0)

    # On HTTP errors (non-2xx):
    if status < 200 or status >= 300:
        shared["error"] = f"HTTP {status}"              # ONLY the status code!
        return "error"
```

**Key Observation**: The HTTP node stores the **full API response** in `shared["response"]`, but only sets `shared["error"]` to a generic status code like `"HTTP 422"` or `"HTTP 400"`.

### Example: GitHub API Validation Error

**Actual API Response** (stored in `shared["response"]`):
```json
{
  "message": "Validation Failed",
  "errors": [
    {
      "resource": "Issue",
      "field": "title",
      "code": "missing_field"
    },
    {
      "resource": "Issue",
      "field": "body",
      "code": "invalid"
    }
  ],
  "documentation_url": "https://docs.github.com/rest/issues/issues#create-an-issue"
}
```

**What gets stored as error** (`shared["error"]`):
```python
"HTTP 422"  # Just the status code!
```

---

## Error Capture: MCP Node

**Location**: `src/pflow/nodes/mcp/node.py`

### What Gets Stored in Shared Store

```python
# Lines 341-422 in post() method
def post(self, shared, prep_res, exec_res):
    # On protocol errors:
    if "error" in exec_res:
        shared["error"] = exec_res["error"]              # Error message string
        shared["error_details"] = {
            "server": prep_res["server"],
            "tool": prep_res["tool"],
            "timeout": exec_res.get("timeout", False)
        }
        return "default"  # Doesn't even return "error"!

    # On tool-level errors (isError flag):
    result = exec_res.get("result")
    if isinstance(result, dict) and result.get("is_tool_error"):
        shared["error"] = result.get("error", "Tool execution failed")
        shared["error_details"] = {
            "server": prep_res["server"],
            "tool": prep_res["tool"],
            "is_tool_error": True
        }
        return "error"

    # On success - stores FULL result:
    shared["result"] = result                            # Full MCP response
    shared[f"{server}_{tool}_result"] = result          # Server-specific key

    # Extract structured fields:
    if isinstance(result, dict) and not result.get("error"):
        for key, value in result.items():
            if not key.startswith("_") and not key.startswith("is_"):
                shared[key] = value  # Individual fields at root level
```

**Key Observation**:
- MCP nodes store the **full result** including nested data structures
- For tool errors, only `shared["error"]` contains the error message
- The full MCP response with validation details is in `shared["result"]` but not extracted for errors

### Example: Slack MCP Validation Error

**Actual MCP Response** (stored in `shared["result"]`):
```json
{
  "successful": true,
  "error": null,
  "data": {
    "ok": false,
    "error": "invalid_blocks",
    "response_metadata": {
      "messages": [
        "blocks[0].text.text: must be present",
        "blocks[1].type: must be 'section', 'divider', or 'image'"
      ]
    }
  }
}
```

**What gets stored as error** (`shared["error"]`):
```python
"invalid_blocks"  # Just the error code!
```

---

## Error Extraction: Executor Service

**Location**: `src/pflow/execution/executor_service.py`

### How Errors are Extracted for Repair

```python
# Lines 251-278 in _extract_error_info()
def _extract_error_info(self, action_result, shared_store):
    """Extract error message and failed node from shared store."""
    error_message = f"Workflow failed with action: {action_result}"
    failed_node = self._get_failed_node_from_execution(shared_store)

    # Priority 1: Check root-level error
    if "error" in shared_store:
        error_message = str(shared_store["error"])  # ONLY uses the generic error!
    else:
        # Priority 2: Check node-level error
        if failed_node in shared_store:
            node_output = shared_store[failed_node]
            if "error" in node_output:
                error_message = str(node_output["error"])  # Still generic!

    return {"message": error_message, "failed_node": failed_node}
```

**Critical Issue**: The error extraction **ONLY** looks at:
1. `shared["error"]` - Contains generic summaries like `"HTTP 422"` or `"invalid_blocks"`
2. `shared[node_id]["error"]` - Same generic summary

It **NEVER** looks at:
- `shared["response"]` (HTTP full response)
- `shared["result"]` (MCP full result)
- `shared[node_id]` nested data structures

### Example: What Repair Sees

**For GitHub HTTP validation error**:
```python
{
    "source": "runtime",
    "category": "api_validation",  # Detected by pattern matching
    "message": "HTTP 422",         # ❌ NO field names, NO constraints!
    "node_id": "create-issue",
    "fixable": True
}
```

**For Slack MCP validation error**:
```python
{
    "source": "runtime",
    "category": "execution_failure",  # ❌ Wrong category!
    "message": "invalid_blocks",       # ❌ NO field details!
    "node_id": "send_message",
    "fixable": True
}
```

---

## What Repair LLM Sees

**Location**: `src/pflow/execution/repair_service.py`

### Repair Prompt Construction

```python
# Lines 519-551 in _format_errors_for_prompt()
def _format_errors_for_prompt(errors, repair_context):
    """Format errors for LLM consumption."""
    lines = []

    for i, error in enumerate(errors, 1):
        message = error.get("message", "Unknown error")  # ❌ Generic message!
        lines.append(f"{i}. {message}")

        # Add metadata:
        if error.get("category"):
            lines.append(f"   Category: {error['category']}")
        if error.get("hint"):
            lines.append(f"   Hint: {error['hint']}")
        if error.get("node_id"):
            lines.append(f"   Node: {error['node_id']}")

    return "\n".join(lines)
```

### Example: Actual Repair Prompt for GitHub Error

```markdown
## Errors to Fix
1. HTTP 422
   Category: api_validation
   Node: create-issue

## Repair Context
- Completed nodes:
- Failed at node: create-issue

## Guidance for Error Categories Present
### API Parameter Validation Errors
- External API/tool rejecting the parameter format
- Error message usually shows expected format (e.g., 'should be a list')
- Check how the data is prepared in upstream nodes
- Solution: Match the exact format the API expects
```

**What's Missing**:
- ❌ No field names (`title`, `body`)
- ❌ No validation rules (required, format)
- ❌ No API documentation links
- ❌ No example of correct format
- ❌ No error details from the actual response

---

## API Warning Detection

**Location**: `src/pflow/runtime/instrumented_wrapper.py` (lines 737-900)

### How Raw Errors are Accessed (But Not Passed to Repair!)

```python
# Lines 737-800 in _detect_api_warning()
def _detect_api_warning(self, shared):
    """Detect non-repairable API errors."""
    # Get node output
    output = shared.get(self.node_id)

    # Unwrap MCP responses:
    output = self._unwrap_mcp_response(output)  # ✅ Accesses full response!

    # Extract error code and message:
    error_code = self._extract_error_code(output)      # ✅ Checks multiple fields
    error_msg = self._extract_error_message(output)     # ✅ Gets detailed message

    # Categorize by code:
    if error_code:
        if error_code == "422":
            return None  # ❌ Validation error - should be repairable!
        elif error_code in ["404", "403", "401"]:
            return f"API error ({error_code}): {error_msg}"  # Non-repairable
```

**Critical Insight**: The `_detect_api_warning()` method **CAN** access:
- Full HTTP response via `shared[node_id]["response"]`
- Full MCP result via `shared[node_id]["result"]`
- Nested error details in API responses

**But**: This data is **ONLY** used for warning detection (repairable vs non-repairable), **NOT** passed to repair!

---

## The Gap: What Gets Lost

### Information Flow Summary

```
┌─────────────────────────────────────────────┐
│  API Returns Detailed Validation Error      │
│  {                                          │
│    "errors": [{                             │
│      "field": "title",                      │
│      "code": "missing_field"                │
│    }]                                       │
│  }                                          │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  Node Stores Full Response                  │
│  shared["response"] = full_api_response     │
│  shared["error"] = "HTTP 422"  ❌           │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  Executor Extracts Generic Error            │
│  error_info["message"] = "HTTP 422"  ❌     │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  Repair Service Formats for LLM             │
│  "1. HTTP 422"  ❌                          │
│  "   Category: api_validation"              │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  Repair LLM Tries to Fix Without Data       │
│  - Guesses which field is wrong             │
│  - Guesses the validation rule              │
│  - Often fails or makes wrong changes       │
└─────────────────────────────────────────────┘
```

---

## Recommendations for Agents

### 1. Access Full Error Details

Agents should be able to query:
```python
# Get full API response for a failed node
GET /workflow/nodes/{node_id}/full-output

# Response:
{
  "node_id": "create-issue",
  "status": "error",
  "error_summary": "HTTP 422",
  "full_response": {
    "message": "Validation Failed",
    "errors": [
      {"field": "title", "code": "missing_field"},
      {"field": "body", "code": "invalid"}
    ]
  },
  "response_headers": {...},
  "request_params": {...}
}
```

### 2. Enhanced Error Context

Repair should receive:
```python
{
  "source": "runtime",
  "category": "api_validation",
  "message": "HTTP 422",
  "node_id": "create-issue",
  "fixable": True,

  # NEW: Full context
  "raw_response": {
    "message": "Validation Failed",
    "errors": [...]
  },
  "request_sent": {
    "method": "POST",
    "url": "https://api.github.com/repos/...",
    "body": {...}
  },
  "extracted_fields": {
    "missing_fields": ["title"],
    "invalid_fields": ["body"],
    "validation_rules": [...]
  }
}
```

### 3. Expose via CLI Commands

```bash
# Get detailed error for last failure
pflow debug errors --node create-issue --format json

# Get full response/request for a node
pflow debug node-io --node create-issue --show-request --show-response

# Compare expected vs actual for validation errors
pflow debug validation-diff --node create-issue
```

### 4. Enhanced Repair Context

The repair prompt should include:
```markdown
## Errors to Fix

### Error 1: API Validation Failed
**Node**: create-issue
**Action**: POST https://api.github.com/repos/owner/repo/issues
**Status**: HTTP 422 Unprocessable Entity

**API Error Response**:
```json
{
  "message": "Validation Failed",
  "errors": [
    {
      "resource": "Issue",
      "field": "title",
      "code": "missing_field"
    },
    {
      "resource": "Issue",
      "field": "body",
      "code": "invalid",
      "message": "body is too short (minimum is 30 characters)"
    }
  ]
}
```

**Request Sent**:
```json
{
  "title": "",  // ❌ Empty - missing required field
  "body": "Fix bug",  // ❌ Too short - needs 30+ chars
  "labels": ["bug"]
}
```

**Required Fixes**:
- Field 'title' is required and cannot be empty
- Field 'body' must be at least 30 characters

**Upstream Data Source**:
- 'title' comes from: ${issue.title}
- 'body' comes from: ${issue.description}
```

---

## Implementation Path

### Phase 1: CLI Discovery Commands (Task 71)

Add commands to expose error details:
```bash
pflow errors list                    # List all workflow errors
pflow errors show <node-id>          # Show full error for node
pflow node inspect <node-id>         # Show node inputs/outputs
pflow workflow debug                 # Interactive error exploration
```

### Phase 2: Enhanced Error Extraction

Modify `executor_service.py`:
```python
def _extract_error_info(self, action_result, shared_store):
    """Extract FULL error information including raw responses."""
    error_message = ...

    # NEW: Extract full context
    if failed_node in shared_store:
        node_output = shared_store[failed_node]

        # Extract full HTTP response
        if "response" in node_output:
            raw_response = node_output["response"]

        # Extract full MCP result
        if "result" in node_output:
            raw_result = node_output["result"]

        # Parse validation errors
        validation_errors = self._parse_validation_errors(
            raw_response or raw_result
        )

    return {
        "message": error_message,
        "failed_node": failed_node,
        "raw_response": raw_response,      # NEW
        "validation_errors": validation_errors,  # NEW
        "request_params": prep_res          # NEW
    }
```

### Phase 3: Repair Enhancement

Modify `repair_service.py`:
```python
def _format_errors_for_prompt(errors, repair_context):
    """Format errors with FULL context for LLM."""
    lines = []

    for error in errors:
        # Add basic info
        lines.append(f"Error: {error['message']}")

        # NEW: Add full API response
        if "raw_response" in error:
            lines.append("\n**API Response**:")
            lines.append(json.dumps(error["raw_response"], indent=2))

        # NEW: Add validation details
        if "validation_errors" in error:
            lines.append("\n**Validation Errors**:")
            for val_error in error["validation_errors"]:
                lines.append(f"- {val_error['field']}: {val_error['message']}")

    return "\n".join(lines)
```

---

## Conclusion

**Current State**: The repair system has access to full error details in the shared store, but only extracts and passes generic summaries to the LLM.

**Root Cause**:
1. Nodes store full responses but only set generic `shared["error"]` strings
2. Executor only extracts from `shared["error"]`, ignoring `shared["response"]`/`shared["result"]`
3. Repair formats only the generic error message for the LLM

**Solution**: Create a "full error context" extraction pipeline that:
1. Accesses `shared[node_id]` complete output (not just `shared["error"]`)
2. Parses API responses to extract validation rules, field names, constraints
3. Includes request parameters to show what was sent
4. Formats this as structured context for the repair LLM
5. Exposes this to agents via CLI commands

**Impact**: This would dramatically improve repair success rates for API validation errors, which are currently the most common repair failures.
