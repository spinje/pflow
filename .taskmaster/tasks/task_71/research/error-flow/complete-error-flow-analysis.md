# Complete Error Flow Analysis - What Agents See

## Executive Summary

When workflows fail with `--no-repair`, agents currently see **minimal error information** - just a generic message. The system has **rich error data** (error category, node ID, detailed messages) but **doesn't expose it** in the output.

## 1. Current Error Display (--no-repair)

### What Gets Printed to stderr

**Location**: `src/pflow/cli/main.py:1034-1060` (`_handle_workflow_error`)

```python
def _handle_workflow_error(...):
    # Only show error messages if not in JSON mode
    if output_format != "json":
        click.echo("cli: Workflow execution failed - Node returned error action", err=True)
        click.echo("cli: Check node output above for details", err=True)

    # Include metrics in error JSON if applicable
    if output_format == "json" and metrics_collector:
        error_output = {"error": "Workflow execution failed", "is_error": True, **metrics_summary}
        _serialize_json_result(error_output, verbose)
```

**Problem**: Generic "Workflow execution failed" message - no specifics!

### What Agents Currently See

**Text mode** (default):
```
cli: Workflow execution failed - Node returned error action
cli: Check node output above for details
```

**JSON mode** (`--output-format json`):
```json
{
  "error": "Workflow execution failed",
  "is_error": true,
  "metrics": {...}
}
```

**Missing**: Node ID, error category, actual error message, available fields for template errors

## 2. What's in ExecutionResult.errors (Available but Hidden)

### ExecutionResult Structure

**Location**: `src/pflow/execution/executor_service.py:16-29`

```python
@dataclass
class ExecutionResult:
    success: bool
    shared_after: dict[str, Any]
    errors: list[dict[str, Any]]          # ← THIS HAS THE DETAILS!
    action_result: Optional[str]
    node_count: int
    duration: float
    output_data: Optional[str]
    metrics_summary: Optional[dict]
    repaired_workflow_ir: Optional[dict]
```

### Error Dict Structure

**Created by**: `src/pflow/execution/executor_service.py:218-249` (`_build_error_list`)

```python
{
    "source": "runtime",              # Where error originated
    "category": "template_error",     # Error classification
    "message": "Template ${fetch.result.title} failed to resolve: 'result' not found in 'fetch' output. Available fields: ['status_code', 'body']",
    "action": "error:template_failed", # Action string that triggered
    "node_id": "process",             # Which node failed
    "fixable": True                   # Whether repair should attempt
}
```

### Error Categories Detected

**Location**: `src/pflow/execution/executor_service.py:368-396` (`_determine_error_category`)

1. **`api_validation`** - API parameter errors
   - Patterns: "input should be", "field required", "validation error", "parameter `"

2. **`template_error`** - Template resolution failures
   - Patterns: Contains `"${"` or word "template"

3. **`execution_failure`** - Everything else
   - Generic runtime failures

## 3. How Template Errors Are Created

### Template Resolution Flow

**Location**: `src/pflow/runtime/node_wrapper.py:186-216`

```python
# When template ${var.field} can't resolve
error_msg = f"Template {template_str} failed to resolve: {str(e)}"
logger.error(
    f"Template resolution failed for node '{self.node_id}': {error_msg}",
    extra={"node_id": self.node_id, "param": key},
)
# Make template errors fatal to trigger repair
raise ValueError(error_msg)  # ← This becomes the error message
```

### Error Message Format

Template errors look like:
```
"Template ${fetch.result.title} failed to resolve: 'result' not found in 'fetch' output. Available fields: ['status_code', 'body']"
```

**What it includes**:
- The template that failed: `${fetch.result.title}`
- What went wrong: `'result' not found`
- **Available fields**: `['status_code', 'body']` ← CRITICAL for repair!

### How Errors Propagate

```
TemplateAwareNodeWrapper (raises ValueError)
    ↓
InstrumentedNodeWrapper (catches, marks failed_node)
    ↓
Flow execution (returns "error" action)
    ↓
WorkflowExecutorService._build_error_list()
    ↓
ExecutionResult.errors list
    ↓
CLI _handle_workflow_error() ← LOSES THE DETAIL!
```

## 4. The Information Gap

### What We Have (in ExecutionResult.errors)

```python
result.errors = [
    {
        "source": "runtime",
        "category": "template_error",
        "message": "Template ${fetch.result.title} failed to resolve: 'result' not found in 'fetch' output. Available fields: ['status_code', 'body']",
        "action": "error:template_failed",
        "node_id": "process",
        "fixable": True
    }
]
```

### What We Show

**Text mode**:
```
cli: Workflow execution failed - Node returned error action
cli: Check node output above for details
```

**JSON mode**:
```json
{
  "error": "Workflow execution failed",
  "is_error": true
}
```

### The Gap

**Missing in output**:
1. ✗ Which node failed (`node_id: "process"`)
2. ✗ Error category (`category: "template_error"`)
3. ✗ Actual error message (the helpful message with available fields!)
4. ✗ Whether error is fixable (`fixable: True`)
5. ✗ Action that triggered error (`action: "error:template_failed"`)

## 5. Error Extraction Logic

### Where Error Messages Come From

**Location**: `src/pflow/execution/executor_service.py:251-278` (`_extract_error_info`)

```python
def _extract_error_info(action_result, shared_store):
    # Try multiple sources for error message

    # 1. Root level error
    if "error" in shared_store:
        error_message = str(shared_store["error"])

    # 2. Node-level error (in namespaced output)
    elif failed_node in shared_store:
        node_output = shared_store[failed_node]
        if "error" in node_output:
            error_message = str(node_output["error"])

    # 3. Fallback
    else:
        error_message = f"Workflow failed with action: {action_result}"

    return {"message": error_message, "failed_node": failed_node}
```

**Key Insight**: Error messages ARE extracted from shared store correctly, they're just not displayed!

### Failed Node Detection

**Location**: `src/pflow/execution/executor_service.py:280-293` (`_get_failed_node_from_execution`)

```python
if "__execution__" in shared_store:
    execution_data = shared_store.get("__execution__", {})
    failed_node = execution_data.get("failed_node")  # ← Set by InstrumentedNodeWrapper
```

## 6. What Needs to Change

### Current Flow (--no-repair)

```
execute_workflow(enable_repair=False)
    ↓
ExecutionResult(success=False, errors=[{detailed info}])
    ↓
_handle_workflow_error()  ← DISCARDS result.errors!
    ↓
Generic message to stderr
```

### Proposed Flow

```
execute_workflow(enable_repair=False)
    ↓
ExecutionResult(success=False, errors=[{detailed info}])
    ↓
_handle_workflow_error(result)  ← ACCEPT result parameter
    ↓
Format and display result.errors[0]
    ↓
Detailed error to stderr with node ID, category, message
```

### Implementation Changes Needed

**File**: `src/pflow/cli/main.py`

1. **Update _handle_workflow_error signature** (line 1034):
```python
def _handle_workflow_error(
    ctx: click.Context,
    result: ExecutionResult,  # ← ADD THIS
    workflow_trace: Any | None,
    output_format: str,
    # ... other params
):
```

2. **Format and display errors** (line 1044):
```python
if output_format != "json":
    if result.errors:
        error = result.errors[0]
        click.echo(f"❌ Workflow failed at node '{error['node_id']}'", err=True)
        click.echo(f"   Category: {error['category']}", err=True)
        click.echo(f"   Error: {error['message']}", err=True)
    else:
        click.echo("cli: Workflow execution failed - Node returned error action", err=True)
```

3. **Update JSON mode** (line 1054):
```python
if output_format == "json" and metrics_collector:
    error_detail = result.errors[0] if result.errors else {}
    error_output = {
        "error": error_detail.get("message", "Workflow execution failed"),
        "node_id": error_detail.get("node_id"),
        "category": error_detail.get("category"),
        "is_error": True,
        **metrics_summary
    }
```

4. **Update call site** (line 1205):
```python
_handle_workflow_error(
    ctx=ctx,
    result=result,  # ← ADD THIS
    workflow_trace=workflow_trace,
    # ... other params
)
```

## 7. Template Error Example (Real World)

### What Actually Happens

**Workflow IR**:
```json
{
  "nodes": [
    {"id": "fetch", "type": "http", "params": {"url": "https://api.github.com/repos/pflow"}},
    {"id": "process", "type": "llm", "params": {"prompt": "Analyze: ${fetch.result.title}"}}
  ]
}
```

**Execution**:
1. `fetch` node runs, returns: `{"status_code": 200, "body": "{...}"}`
2. `process` tries to resolve `${fetch.result.title}`
3. Template resolver looks for `fetch.result.title` in shared store
4. Finds: `shared["fetch"] = {"status_code": 200, "body": "{...}"}`
5. Error: `"result" not found, available: ['status_code', 'body']`

### What Gets Created

**ExecutionResult.errors**:
```python
[{
    "source": "runtime",
    "category": "template_error",
    "message": "Template ${fetch.result.title} failed to resolve: 'result' not found in 'fetch' output. Available fields: ['status_code', 'body']",
    "node_id": "process",
    "fixable": True
}]
```

### What Agent Currently Sees

**stderr**:
```
cli: Workflow execution failed - Node returned error action
cli: Check node output above for details
```

**HUGE PROBLEM**: Agent has NO IDEA:
- Which node failed
- What template failed
- What fields are available
- That it's a template error (could try different approach)

## 8. Recommendations

### Immediate Fix (Minimal)

**Show the error message from result.errors[0]**:
```python
if result.errors:
    click.echo(f"❌ {result.errors[0]['message']}", err=True)
```

This alone would give agents:
- The failed template
- What went wrong
- Available fields

### Better Fix (Structured)

**Format errors properly**:
```python
error = result.errors[0]
click.echo(f"❌ Workflow failed at node '{error['node_id']}'", err=True)
click.echo(f"   {error['message']}", err=True)
if error['category'] == 'template_error':
    click.echo(f"   💡 Check template variable paths", err=True)
```

### Best Fix (Complete)

**Provide JSON mode for agents**:
```json
{
  "success": false,
  "error": {
    "node_id": "process",
    "category": "template_error",
    "message": "Template ${fetch.result.title} failed...",
    "available_fields": ["status_code", "body"],
    "suggestion": "Use ${fetch.body} instead"
  }
}
```

## 9. Why This Matters for Agents

### Current Situation

Agent runs workflow with `--no-repair`, gets:
```
cli: Workflow execution failed - Node returned error action
```

**Agent's perspective**:
- "Something went wrong but I don't know what"
- Can't determine if it's worth retrying
- Can't suggest fixes
- Can't learn from the error

### With Full Error Info

Agent gets:
```json
{
  "error": {
    "node_id": "process",
    "category": "template_error",
    "message": "Template ${fetch.result.title} failed to resolve: 'result' not found in 'fetch' output. Available fields: ['status_code', 'body']"
  }
}
```

**Agent's perspective**:
- "Ah, template error in process node"
- "Available fields are status_code and body"
- "Should use ${fetch.body} instead of ${fetch.result.title}"
- Can suggest fix or retry with correction

## 10. Code Locations Summary

### Key Files

1. **Error Creation**: `src/pflow/execution/executor_service.py`
   - Line 218-249: `_build_error_list()` - Creates error dicts
   - Line 251-278: `_extract_error_info()` - Extracts messages
   - Line 368-396: `_determine_error_category()` - Categorizes errors

2. **Error Storage**: `src/pflow/execution/executor_service.py`
   - Line 16-29: `ExecutionResult` dataclass
   - Line 485-494: `_build_execution_result()` - Packs errors

3. **Error Display**: `src/pflow/cli/main.py`
   - Line 1034-1060: `_handle_workflow_error()` - LOSES ERROR DETAILS
   - Line 1205: Call site that needs to pass result

4. **Template Errors**: `src/pflow/runtime/node_wrapper.py`
   - Line 186-216: Template resolution with detailed error messages

### The Fix is Simple

**Just pass ExecutionResult to _handle_workflow_error()** and display `result.errors[0]`!

The data is there, we're just not using it.
