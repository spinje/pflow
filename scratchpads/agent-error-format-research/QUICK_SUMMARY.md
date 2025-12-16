# Quick Summary: Pflow Agent Error Format

## What Agents Get on Workflow Failure

When executing workflows with `--output-format json`, agents receive:

```json
{
  "success": false,
  "error": "Human-readable summary",
  "errors": [
    {
      "category": "api_validation",           // Error type for repair strategy
      "node_id": "create-issue",              // Which node failed
      "message": "Field 'title' required",    // What went wrong
      "fixable": true,                        // Can auto-repair attempt?

      // Rich context (extracted from shared store):
      "status_code": 400,                     // HTTP nodes
      "raw_response": {...},                  // Full API response
      "available_fields": ["result", "status"] // Template errors
    }
  ],
  "execution": {
    "steps": [
      {"node_id": "fetch", "status": "completed", "cached": true},
      {"node_id": "process", "status": "failed", "cached": false}
    ]
  },
  "checkpoint": {
    "completed_nodes": ["fetch"],
    "failed_node": "process"
  }
}
```

## Key Features

### 1. Error Categorization
- `api_validation` - API parameter issues
- `template_error` - Unresolved `${variable}` templates
- `execution_failure` - Runtime failures
- Tells agents which repair strategy to use

### 2. Execution Visibility
Per-node status tracking:
- **completed** - Ran successfully
- **failed** - Execution failed
- **not_executed** - Workflow stopped before reaching
- **cached** - Used cached result (Task 71)

### 3. Rich Error Context (Task 71)
Extracted from node output in shared store:

**HTTP Nodes**:
```json
{
  "status_code": 400,
  "raw_response": {...},
  "response_headers": {...},
  "response_time": 1.234
}
```

**Template Errors**:
```json
{
  "available_fields": ["result", "status", "data"],
  "available_fields_total": 47,
  "available_fields_truncated": true
}
```

**MCP Nodes**:
```json
{
  "mcp_error_details": {...},
  "mcp_error": {...}
}
```

### 4. Checkpoint for Resume
```json
{
  "completed_nodes": ["node1", "node2"],
  "failed_node": "node3"
}
```
Enables resume from failure point after repair (no duplicate execution).

### 5. Security: Always Sanitized
- API keys → `<REDACTED>`
- Tokens → `<REDACTED>`
- Passwords → `<REDACTED>`
- Normal data → Preserved

## Implementation

**Data Extraction**: `src/pflow/execution/executor_service.py` lines 270-346
```python
# Extract from shared_store[node_id]
if "status_code" in node_output:
    error["status_code"] = node_output["status_code"]
    error["raw_response"] = node_output.get("response")
```

**Formatting**: `src/pflow/execution/formatters/error_formatter.py`
```python
def format_execution_errors(
    result: ExecutionResult,
    sanitize: bool = True  # Always True for JSON output
) -> dict:
    # Sanitize sensitive fields
    # Build execution steps
    # Return structured error data
```

**JSON Output**: `src/pflow/cli/main.py` ~line 476
```python
if output_format == "json":
    formatted = format_execution_errors(result, sanitize=True)
    output_json = {"success": False, **formatted}
    click.echo(json.dumps(output_json))
```

## Agent Benefits

### Before Task 71
```json
{
  "success": false,
  "error": "Node failed"
}
```
**Problem**: No context, no visibility, generic errors.

### After Task 71
```json
{
  "success": false,
  "errors": [{
    "category": "template_error",
    "available_fields": ["result", "status"],
    "status_code": 400
  }],
  "execution": {
    "steps": [
      {"node_id": "fetch", "status": "completed", "cached": true},
      {"node_id": "process", "status": "failed"}
    ]
  }
}
```
**Result**: Self-diagnosis, intelligent repair, execution visibility.

## Testing

**Integration**: `tests/test_cli/test_enhanced_error_output.py`
- Execution state visibility
- Cache hit tracking
- JSON structure validation

**Unit**: `tests/test_execution/formatters/test_error_formatter.py`
- Security (sanitization)
- Data integrity
- Robustness

## Key Files

| File | Purpose |
|------|---------|
| `executor_service.py` | Extract rich context from shared store |
| `error_formatter.py` | Format + sanitize errors |
| `execution_state.py` | Build per-node status |
| `instrumented_wrapper.py` | Track checkpoints & cache hits |
| `cli/main.py` | Construct JSON output |

## MCP Parity

MCP server uses **same formatter** → CLI JSON and MCP return identical structures.

## Design Philosophy

> "Give agents structured, actionable data—not just error messages. Include everything needed for self-diagnosis and repair."

---

For complete details, see: `ERROR_FORMAT_RESEARCH.md`
