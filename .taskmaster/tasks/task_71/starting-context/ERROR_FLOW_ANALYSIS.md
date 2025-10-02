# Error Flow Analysis for Task 71

## The Critical Problem

Agents using `--no-repair` get almost no error context, making it impossible to fix issues autonomously. This document details the complete error flow and what needs to be exposed.

## Error Information Flow

### 1. Node Level - Rich Error Capture

#### HTTP Node (`src/pflow/nodes/http/http.py`)

**What's captured**:
```python
# Line 89-95: Full response stored
shared["response"] = response_json  # Full API response with details
shared["status_code"] = response.status_code
shared["headers"] = dict(response.headers)

# But only generic error set:
if not response.ok:
    shared["error"] = f"HTTP {response.status_code}"  # Just status!
```

**Example GitHub API error response** (in `shared["response"]`):
```json
{
  "message": "Validation Failed",
  "errors": [
    {
      "resource": "Issue",
      "field": "assignees",
      "code": "invalid",
      "message": "assignees should be a list"
    },
    {
      "resource": "Issue",
      "field": "body",
      "code": "invalid",
      "message": "body is too short (minimum is 30 characters)"
    }
  ],
  "documentation_url": "https://docs.github.com/rest/issues"
}
```

#### MCP Node (`src/pflow/nodes/mcp/node.py`)

**What's captured**:
```python
# Line 339: Full result stored
shared[self.store_result_as] = result  # Complete MCP response

# Line 354-365: Error extraction
if error_info := result.get("error"):
    if isinstance(error_info, dict):
        error_msg = error_info.get("message", "Unknown error")
    shared["error"] = error_msg  # Just message!
```

**Example MCP error** (in `shared["result"]`):
```json
{
  "error": {
    "code": "invalid_blocks",
    "message": "Field 'assignee' expects array",
    "details": {
      "field": "assignee",
      "expected": "array",
      "received": "string",
      "value": "alice"
    }
  }
}
```

### 2. Executor Service - Error Extraction

**Location**: `src/pflow/execution/executor_service.py:251-366`

**Current extraction** (simplified):
```python
def _extract_error_from_shared(shared: dict, failed_node: str) -> dict:
    # Only looks at shared["error"] or shared[node]["error"]
    error_msg = shared.get("error", "Unknown error")

    return {
        "source": "runtime",
        "category": _detect_error_category(shared),
        "message": error_msg,  # Generic message only!
        "node_id": failed_node,
        "fixable": True
    }
    # NOT extracting shared["response"] or shared["result"]!
```

### 3. CLI Display - Information Loss

**Location**: `src/pflow/cli/main.py:1034-1060`

**Current `_handle_workflow_error()`**:
```python
def _handle_workflow_error(ctx, workflow_trace, output_format, ...):
    # NO ExecutionResult parameter!
    # Can't access result.errors

    if output_format == "json":
        output = {"error": "Workflow execution failed", "is_error": True}
    else:
        click.echo("cli: Workflow execution failed - Node returned error action")
```

**The gap**: ExecutionResult.errors has everything but isn't passed to the error handler!

### 4. What Repair LLM Sees

**Location**: `src/pflow/execution/repair_service.py:274-299`

**Repair context**:
```python
# Only gets extracted error message
errors = [{
    "message": "HTTP 422",  # No details!
    "category": "api_validation",
    "node_id": "create-issue"
}]

# Formats as:
"1. HTTP 422
   Category: api_validation
   Node: create-issue"
```

**Repair can't see**:
- Which fields failed validation
- What format was expected
- The actual API response
- Available fields in shared store

## What Agents Need to See

### Current State (Useless)
```
cli: Workflow execution failed - Node returned error action
```

### Required State (Actionable)

#### For API Validation Errors:
```
❌ Workflow failed at node: 'create-issue'
   Category: api_validation
   Message: HTTP 422 - Validation Failed

   API Response Details:
   - Field 'assignees' should be a list (got: string "alice")
   - Field 'body' too short (minimum: 30 chars, got: 5)

   Documentation: https://docs.github.com/rest/issues

   Your request:
   {
     "title": "Bug Report",
     "body": "Short",
     "assignees": "alice"
   }
```

#### For Template Errors:
```
❌ Workflow failed at node: 'process-data'
   Category: template_error
   Template: ${fetch.result.issues[0].title}
   Problem: 'result' not found in 'fetch' output

   Available in 'fetch':
   - ${fetch.issues} (array of 42 items)
   - ${fetch.issues[0].title} = "First issue"
   - ${fetch.issues[0].number} = 123
   - ${fetch.total_count} = 42
```

#### For MCP Tool Errors:
```
❌ Workflow failed at node: 'mcp-github-create_issue'
   Category: api_validation
   Tool: github-create_issue

   Error Details:
   - Field: assignee
   - Expected: array
   - Received: string "alice"
   - Fix: Use ["alice"] instead
```

## Implementation Requirements

### 1. Enhance Error Extraction

**File**: `src/pflow/execution/executor_service.py`

**Add to `_extract_error_from_shared()`**:
```python
# Line ~260, after basic extraction:
error = {
    "source": "runtime",
    "category": category,
    "message": error_msg,
    "node_id": failed_node,
    "fixable": True
}

# ADD: Capture raw responses
if "response" in shared:
    error["raw_response"] = shared["response"]
    error["status_code"] = shared.get("status_code")

# ADD: Capture MCP results
if "result" in shared:
    result = shared["result"]
    if isinstance(result, dict) and "error" in result:
        error["mcp_error"] = result["error"]

# ADD: For template errors, capture available data
if category == "template_error":
    # Extract what IS available in the node
    node_data = shared.get(failed_node, {})
    if isinstance(node_data, dict):
        error["available_fields"] = list(node_data.keys())

return error
```

### 2. Update CLI Error Display

**File**: `src/pflow/cli/main.py`

**Fix function signature** (line ~1034):
```python
def _handle_workflow_error(
    ctx: click.Context,
    result: ExecutionResult,  # ADD THIS
    workflow_trace: Any | None,
    output_format: str,
    # ...
):
```

**Update display logic**:
```python
if result and result.errors:
    for error in result.errors:
        # Basic error info
        click.echo(f"❌ Workflow failed at node: '{error.get('node_id')}'", err=True)
        click.echo(f"   Category: {error.get('category')}", err=True)
        click.echo(f"   Message: {error.get('message')}", err=True)

        # API Response details
        if raw := error.get('raw_response'):
            click.echo("\n   API Response Details:", err=True)
            if isinstance(raw, dict):
                if errors := raw.get('errors'):
                    for e in errors:
                        field = e.get('field', 'unknown')
                        msg = e.get('message', e.get('code', 'error'))
                        click.echo(f"   - Field '{field}': {msg}", err=True)
                elif msg := raw.get('message'):
                    click.echo(f"   - {msg}", err=True)

                if doc_url := raw.get('documentation_url'):
                    click.echo(f"\n   Documentation: {doc_url}", err=True)

        # MCP error details
        if mcp := error.get('mcp_error'):
            if details := mcp.get('details'):
                click.echo(f"   - Field: {details.get('field')}", err=True)
                click.echo(f"   - Expected: {details.get('expected')}", err=True)
                click.echo(f"   - Received: {details.get('received')}", err=True)

        # Available fields for template errors
        if available := error.get('available_fields'):
            click.echo(f"\n   Available fields in node:", err=True)
            for field in available[:10]:  # Show first 10
                click.echo(f"   - {field}", err=True)

        # Fixable hint
        if error.get('fixable') and no_repair:
            click.echo("\n   💡 This error may be fixable - remove --no-repair flag", err=True)
```

**Update call site** (line ~1205):
```python
_handle_workflow_error(
    ctx=ctx,
    result=result,  # ADD THIS
    workflow_trace=workflow_trace,
    # ...
)
```

### 3. JSON Mode Enhancement

**For `--output-format json`**:
```python
if output_format == "json":
    output = {
        "success": False,
        "errors": result.errors if result else [],
        "checkpoint": {
            "completed_nodes": checkpoint_info.get("completed_nodes", []),
            "failed_node": checkpoint_info.get("failed_node")
        } if checkpoint_info else None
    }
    click.echo(json.dumps(output, indent=2))
```

## Testing Requirements

### Test Scenarios

1. **HTTP API Error**:
   - Trigger GitHub 422 validation error
   - Verify full error details shown
   - Check field-level errors displayed

2. **Template Resolution Error**:
   - Use invalid template path
   - Verify available fields shown
   - Check correct path suggested

3. **MCP Tool Error**:
   - Send invalid params to MCP tool
   - Verify schema details shown
   - Check expected vs received displayed

4. **JSON Output Mode**:
   - Run with `--output-format json`
   - Verify structured error array
   - Check all error fields present

### Expected Outputs

See examples above for each error type.

## Summary

The key finding is that **all the error information we need is already captured** - it's just not being displayed. By passing ExecutionResult to the error handler and extracting the raw responses, we can give agents the same detailed error context that a human developer would need to debug issues.

This is critical for Task 71 because without this error visibility, agents can't effectively use the discovery commands to understand and fix workflow problems.