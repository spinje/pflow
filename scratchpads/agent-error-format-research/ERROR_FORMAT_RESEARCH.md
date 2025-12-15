# Pflow Agent Error Format Research

**Research Date**: 2025-12-12
**Research Question**: How does pflow format errors for agent consumption in JSON output mode?

---

## Executive Summary

When workflows fail with `--output-format json`, pflow returns a **rich, structured error response** specifically designed for AI agents to self-diagnose issues. The system implements a **two-layer error enhancement architecture**:

1. **Data Layer** (`executor_service.py`): Extracts rich context from shared store
2. **Display Layer** (`error_formatter.py`): Formats errors with optional sanitization

The result is agents receive detailed execution state, error categories, available fields for template errors, HTTP status codes, MCP error details, and per-node execution tracking.

---

## 1. JSON Error Output Structure

### Top-Level Response Format

```json
{
  "success": false,
  "error": "Workflow failed with action: error",
  "errors": [
    {
      "source": "runtime",
      "category": "api_validation",
      "message": "Field 'title' required",
      "node_id": "create-issue",
      "fixable": true,
      "status_code": 400,
      "raw_response": {...},
      "response_headers": {...},
      "response_time": 1.234,
      "available_fields": ["result", "status", "data"]
    }
  ],
  "checkpoint": {
    "completed_nodes": ["fetch", "analyze"],
    "node_actions": {"fetch": "default", "analyze": "default"},
    "node_hashes": {...},
    "failed_node": "send"
  },
  "execution": {
    "duration_ms": 1234,
    "nodes_executed": 2,
    "nodes_total": 4,
    "steps": [
      {
        "node_id": "fetch",
        "status": "completed",
        "duration_ms": 150,
        "cached": false,
        "repaired": false
      },
      {
        "node_id": "analyze",
        "status": "completed",
        "duration_ms": 200,
        "cached": true,
        "repaired": false
      },
      {
        "node_id": "send",
        "status": "failed",
        "duration_ms": 50,
        "cached": false,
        "repaired": true
      },
      {
        "node_id": "notify",
        "status": "not_executed",
        "duration_ms": null,
        "cached": false
      }
    ]
  },
  "metrics": {
    "duration_ms": 1234,
    "total_cost_usd": 0.05,
    "nodes_executed": 2
  }
}
```

---

## 2. Error Field Breakdown

### Core Error Fields (Always Present)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `source` | string | Where error originated | `"runtime"`, `"validation"` |
| `category` | string | Error classification for repair | `"api_validation"`, `"template_error"`, `"execution_failure"` |
| `message` | string | Human-readable error description | `"Field 'title' required"` |
| `node_id` | string | Which node failed | `"create-issue"` |
| `fixable` | boolean | Whether auto-repair can attempt fix | `true` or `false` |
| `action` | string | Flow action returned | `"error"` |

### Rich Context Fields (Extracted from Shared Store)

**HTTP Node Errors** (`src/pflow/nodes/http/http.py`):
```json
{
  "status_code": 400,
  "raw_response": {"error": "Bad request", "details": "..."},
  "response_headers": {"content-type": "application/json"},
  "response_time": 1.234
}
```

**MCP Node Errors** (`src/pflow/nodes/mcp/node.py`):
```json
{
  "mcp_error_details": {"server": "github", "tool": "create_issue"},
  "mcp_error": {"code": -32603, "message": "Internal error"}
}
```

**Template Errors** (from `runtime/template_validator.py`):
```json
{
  "category": "template_error",
  "available_fields": ["result", "status", "data", "timestamp", "user"],
  "available_fields_total": 47,
  "available_fields_truncated": true,
  "trace_file_hint": "Showing 20 of 47 fields. Full field list saved to ~/.pflow/debug/workflow-trace-*.json"
}
```

### Error Categories for Repair Strategy

| Category | Meaning | Repair Strategy |
|----------|---------|-----------------|
| `api_validation` | API parameter format issues | Fix field names/types |
| `template_error` | Unresolved `${variable}` templates | Update template paths |
| `execution_failure` | Runtime failures | General error handling |
| `exception` | Python exceptions | Depends on exception type |
| `static_validation` | Workflow structure issues | Fix workflow IR |

---

## 3. Execution State Tracking

### Per-Node Status (`execution.steps`)

Each node in the workflow gets a status entry:

```json
{
  "node_id": "fetch",
  "status": "completed",      // "completed", "failed", "not_executed"
  "duration_ms": 150,         // Execution time (null for not_executed)
  "cached": true,             // Whether cache was used
  "repaired": false           // Whether this node was auto-repaired
}
```

**Status Values**:
- `"completed"` - Node executed successfully
- `"failed"` - Node execution failed
- `"not_executed"` - Node never ran (workflow stopped before reaching it)

**Task 71 Enhancement**: Added `cached` tracking to show which nodes used cached results (from `runtime/instrumented_wrapper.py` lines 598-601).

### Checkpoint Data (`checkpoint`)

Resume data for retry after repair:

```json
{
  "completed_nodes": ["fetch", "analyze"],
  "node_actions": {
    "fetch": "default",
    "analyze": "default"
  },
  "node_hashes": {
    "fetch": "a1b2c3d4...",
    "analyze": "e5f6g7h8..."
  },
  "failed_node": "send"
}
```

**Purpose**: Enables resume from failure point after auto-repair, avoiding duplicate execution.

---

## 4. Implementation Architecture

### Two-Layer Error Enhancement (Task 71)

**Layer 1: Data Extraction** (`executor_service.py` lines 270-346)

```python
# Extract rich context from node's namespaced output
failed_node = error_info.get("failed_node")
if failed_node:
    node_output = shared_store.get(failed_node, {})
    if isinstance(node_output, dict):
        # HTTP node data
        if "status_code" in node_output:
            error["status_code"] = node_output["status_code"]
            error["raw_response"] = node_output.get("response")
            error["response_headers"] = node_output.get("response_headers")

        # MCP node data
        if "error_details" in node_output:
            error["mcp_error_details"] = node_output["error_details"]

        # Template errors: show available fields
        if category == "template_error":
            all_fields = list(node_output.keys())
            error["available_fields"] = all_fields[:20]  # MAX_DISPLAYED_FIELDS
            if len(all_fields) > 20:
                error["available_fields_total"] = len(all_fields)
                error["available_fields_truncated"] = True
```

**Layer 2: Formatting & Sanitization** (`error_formatter.py`)

```python
def format_execution_errors(
    result: ExecutionResult,
    shared_storage: dict | None = None,
    ir_data: dict | None = None,
    metrics_collector: Any | None = None,
    sanitize: bool = True,  # ALWAYS True for JSON output
) -> dict:
    """Format errors with optional sanitization."""

    formatted_errors = []
    for error in result.errors:
        formatted_error = error.copy()

        if sanitize:
            # Remove sensitive data (API keys, tokens)
            if "raw_response" in formatted_error:
                formatted_error["raw_response"] = sanitize_parameters(formatted_error["raw_response"])
            if "response_headers" in formatted_error:
                formatted_error["response_headers"] = sanitize_parameters(formatted_error["response_headers"])

        formatted_errors.append(formatted_error)

    return {
        "errors": formatted_errors,
        "checkpoint": result.shared_after.get("__execution__", {}),
        "execution": {...},  # Per-node status
        "metrics": {...}     # Timing and costs
    }
```

### Where JSON Output is Built

**Entry Point**: `src/pflow/cli/main.py` (around line 476)

```python
if output_format == "json":
    # Format errors using shared formatter
    formatted = format_execution_errors(
        result,
        shared_storage=result.shared_after,
        ir_data=workflow_ir,
        metrics_collector=metrics_collector,
        sanitize=True  # Always sanitize for JSON output
    )

    output_json = {
        "success": False,
        "error": str(result.errors[0].get("message")) if result.errors else "Workflow failed",
        **formatted  # Merge in errors, checkpoint, execution, metrics
    }

    click.echo(json.dumps(output_json, indent=2, default=str))
```

---

## 5. Security: Sanitization

**Critical**: `--output-format json` ALWAYS sanitizes sensitive data before returning to agents.

**What Gets Redacted** (`mcp_server/utils/errors.py`):

```python
SENSITIVE_PATTERNS = [
    "api_key", "apikey", "api-key",
    "secret", "token", "password", "passwd",
    "authorization", "auth",
    "bearer", "credentials"
]

# Example sanitization:
{
    "api_key": "sk-secret123456",      # REDACTED
    "data": "normal value",            # PRESERVED
    "Authorization": "Bearer token",   # REDACTED
    "Content-Type": "application/json" # PRESERVED
}
```

**Tests**: `tests/test_execution/formatters/test_error_formatter.py` (lines 21-108)

---

## 6. Real-World Examples

### Example 1: Template Error

**Workflow**:
```json
{
  "nodes": [
    {"id": "fetch", "type": "http", "params": {"url": "https://api.example.com"}},
    {"id": "process", "type": "shell", "params": {"command": "echo ${fetch.wrong_field}"}}
  ]
}
```

**JSON Error Output**:
```json
{
  "success": false,
  "error": "Template ${fetch.wrong_field} not found",
  "errors": [{
    "source": "runtime",
    "category": "template_error",
    "message": "Template ${fetch.wrong_field} not found",
    "node_id": "process",
    "fixable": true,
    "available_fields": ["result", "status", "response", "headers"]
  }],
  "execution": {
    "steps": [
      {"node_id": "fetch", "status": "completed", "cached": false},
      {"node_id": "process", "status": "failed", "cached": false}
    ]
  }
}
```

**Agent Can**:
- See `available_fields` to know correct field name is `result` not `wrong_field`
- Understand which node failed (`process`)
- Know the error is fixable
- See that `fetch` completed successfully

### Example 2: HTTP 400 Error

**JSON Error Output**:
```json
{
  "success": false,
  "errors": [{
    "source": "runtime",
    "category": "api_validation",
    "message": "Field 'title' is required",
    "node_id": "create-issue",
    "fixable": true,
    "status_code": 400,
    "raw_response": {
      "error": "Validation failed",
      "fields": {"title": "Required field missing"}
    },
    "response_headers": {"content-type": "application/json"},
    "response_time": 0.234
  }],
  "checkpoint": {
    "completed_nodes": ["fetch-repo", "analyze-issues"],
    "failed_node": "create-issue"
  }
}
```

**Agent Can**:
- See HTTP 400 status code
- Read full API error response
- Know which field (`title`) is missing
- See previous nodes succeeded
- Resume from checkpoint after fix

---

## 7. Test Coverage

### Integration Tests

**File**: `tests/test_cli/test_enhanced_error_output.py`

Key test scenarios:
1. **Execution state visibility** (lines 23-83)
   - Per-node status tracking
   - Completed/failed/not_executed states

2. **Cache hit tracking** (lines 113-146)
   - Verify `cached` field in execution steps

3. **JSON error structure** (lines 172-211)
   - Required fields: `success`, `error`, `errors`, `checkpoint`, `execution`
   - Error structure: `category`, `message`, `node_id`

4. **Template error context** (lines 212-245)
   - Available fields shown
   - Actionable feedback

### Unit Tests

**File**: `tests/test_execution/formatters/test_error_formatter.py`

**Security guardrails** (lines 21-108):
- API keys redacted in `raw_response`
- Auth tokens redacted in `response_headers`
- Nested secrets sanitized recursively

**Data integrity** (lines 110-155):
- Original errors never modified
- All errors processed (not just first)

**Execution state** (lines 157-223):
- Completed nodes show correct status
- Cache hits tracked accurately
- Repaired nodes marked

**Robustness** (lines 225-308):
- Handles empty errors
- Handles missing optional fields
- Handles None metrics_collector

---

## 8. Key Implementation Files

| File | Responsibility | Lines |
|------|---------------|-------|
| `src/pflow/execution/executor_service.py` | Extract rich error context from shared store | 270-346 |
| `src/pflow/execution/formatters/error_formatter.py` | Format errors with sanitization | 16-120 |
| `src/pflow/execution/execution_state.py` | Build per-node execution steps | Full file |
| `src/pflow/cli/main.py` | JSON output construction | ~476 |
| `src/pflow/runtime/instrumented_wrapper.py` | Checkpoint tracking, cache hits | 542-601 |
| `src/pflow/mcp_server/utils/errors.py` | Sanitization logic | Full file |

---

## 9. Agent Benefits (Task 71 Impact)

### Before Task 71
```json
{
  "success": false,
  "error": "Node failed",
  "errors": [{"message": "Node failed"}]
}
```

**Problems**:
- No context about what went wrong
- No visibility into execution state
- No cache information
- Generic error messages

### After Task 71
```json
{
  "success": false,
  "errors": [{
    "category": "template_error",
    "node_id": "process",
    "available_fields": ["result", "status", "data"],
    "status_code": 400,
    "raw_response": {...}
  }],
  "execution": {
    "steps": [
      {"node_id": "fetch", "status": "completed", "cached": true},
      {"node_id": "process", "status": "failed", "cached": false}
    ]
  },
  "checkpoint": {...}
}
```

**Agent Can Now**:
1. **Self-diagnose**: See available fields, HTTP codes, full responses
2. **Understand execution**: Know what ran, what cached, what failed
3. **Resume efficiently**: Use checkpoint to retry from failure point
4. **Optimize**: See cache hits to understand performance

---

## 10. MCP Server Parity

The MCP server (`src/pflow/mcp_server/`) uses the **same error formatter** for parity:

**File**: `mcp_server/services/execution_service.py` (around line 143)

```python
# MCP also uses format_execution_errors with sanitize=True
formatted = format_execution_errors(
    result,
    shared_storage=result.shared_after,
    ir_data=workflow_ir,
    metrics_collector=metrics_collector,
    sanitize=True  # Same as CLI JSON mode
)
```

**Result**: CLI `--output-format json` and MCP server return identical error structures.

---

## 11. Key Takeaways for Agent Development

### What Agents Receive on Failure

1. **Error categorization** - Know repair strategy to use
2. **Execution visibility** - See exactly what happened (completed/cached/failed)
3. **Rich context** - HTTP codes, response bodies, available fields
4. **Checkpoint data** - Resume from failure point
5. **Security** - Sensitive data sanitized

### What This Enables

- **Intelligent repair**: Full context helps LLM fix issues
- **Efficient retry**: Resume from checkpoint, no duplicate work
- **Performance analysis**: Cache metrics show optimization opportunities
- **Better debugging**: Complete state for troubleshooting

### Design Philosophy

> "Give agents structured, actionable data—not just error messages. Include everything needed for self-diagnosis and repair."

---

## Appendix: Quick Reference

### Error Categories

| Category | When Used | Example |
|----------|-----------|---------|
| `api_validation` | API parameter issues | Missing required field |
| `template_error` | Unresolved templates | `${node.bad_field}` |
| `execution_failure` | Runtime errors | Command failed |
| `exception` | Python exceptions | ValueError, TypeError |

### Status Values

| Status | Meaning |
|--------|---------|
| `completed` | Node executed successfully |
| `failed` | Node execution failed |
| `not_executed` | Workflow stopped before node |

### Key Shared Store Fields

| Field | Purpose |
|-------|---------|
| `__execution__` | Checkpoint for resume |
| `__cache_hits__` | Nodes that used cache |
| `__modified_nodes__` | Nodes auto-repaired |
| `__warnings__` | Non-repairable API warnings |

---

## References

- **Task 71**: Rich error context extraction and agent enablement
- **Task 72**: Shared formatters for CLI/MCP parity
- **Task 85**: Runtime template resolution hardening
- Architecture docs: `src/pflow/execution/CLAUDE.md`
- Test docs: `tests/CLAUDE.md`
