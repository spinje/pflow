# Error Information Flow Analysis: --no-repair Mode

## Investigation Summary

This document analyzes what error information is returned when workflow execution fails with `--no-repair` flag, and what additional context is available internally for the repair system.

## Current Error Flow with --no-repair

### 1. Execution Path

When `--no-repair` is used:

```python
# workflow_execution.py:583-604
else:
    # REPAIR DISABLED: Skip all validation, execute directly
    shared_store = resume_state if resume_state else {}

    result = executor.execute_workflow(
        workflow_ir=workflow_ir,
        execution_params=execution_params,
        shared_store=shared_store,
        workflow_name=workflow_name,
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=trace_collector,
        validate=False,  # Skip ALL validation when repair disabled
    )

    return result
```

**Key Characteristics**:
- No validation performed at all
- Direct execution via `WorkflowExecutorService.execute_workflow()`
- Single execution attempt - fail fast
- Returns `ExecutionResult` directly

### 2. Error Information in ExecutionResult

The `ExecutionResult` dataclass contains:

```python
@dataclass
class ExecutionResult:
    success: bool                              # False on failure
    shared_after: dict[str, Any]               # Final shared store state
    errors: list[dict[str, Any]]               # Structured error data
    action_result: Optional[str]               # Flow action (e.g., "error")
    node_count: int                            # Number of nodes executed
    duration: float                            # Total execution time
    output_data: Optional[str]                 # Extracted output (None on failure)
    metrics_summary: Optional[dict]            # LLM usage metrics
    repaired_workflow_ir: Optional[dict]       # None when --no-repair
```

### 3. Error Structure

Each error in `result.errors` is a dict with:

```python
{
    "source": "runtime",              # Where error originated (runtime/validation/api)
    "category": "api_validation",     # Error type (used for repair strategy)
    "message": "Field 'title' required",  # Human-readable description
    "node_id": "create-issue",        # Which node failed
    "node_type": "mcp-github-create_issue",  # Type of node
    "fixable": True,                  # Whether repair could attempt

    # Additional context fields (category-dependent):
    "exception_type": "ValueError",   # Python exception type
    "hint": "Check the API documentation",  # Helpful suggestion
    "attempted": [...],               # What was attempted (for extraction errors)
    "available": [...],               # Available fields/options
    "sample": "...",                  # Sample data for context
}
```

### 4. CLI Display with --no-repair

The CLI displays errors via standard error handlers.

**What the user sees**:
- Error message from `error["message"]`
- Node ID where failure occurred
- Basic error details

**What the user does NOT see**:
- Full error context (attempted operations, available options)
- Checkpoint state (which nodes succeeded)
- Shared store contents at failure
- Detailed error categorization
- Repair suggestions

## Rich Context Available Internally for Repair

### 1. Checkpoint Information (in shared_after)

```python
shared["__execution__"] = {
    "completed_nodes": ["fetch", "analyze"],  # Successfully executed nodes
    "node_actions": {                         # Actions returned by each node
        "fetch": "default",
        "analyze": "default"
    },
    "node_hashes": {                          # MD5 config hashes for cache
        "fetch": "a1b2c3d4...",
        "analyze": "e5f6g7h8..."
    },
    "failed_node": "send"                     # Where failure occurred
}
```

**Location**: `result.shared_after["__execution__"]`

**Contains**:
- Execution progress (what succeeded before failure)
- Failure point (which node caused error)
- Node configuration hashes (for cache validation)
- Action routing (what path was taken)

### 2. Repair Context (_analyze_errors_for_repair)

When repair is enabled, this function extracts rich context:

```python
# repair_service.py:274-299
context = {
    "primary_error": errors[0],           # Main error
    "error_count": len(errors),           # Total errors
    "completed_nodes": [],                # From checkpoint
    "failed_node": None,                  # From checkpoint
    "template_issues": [],                # Unresolved templates
    "is_mcp_tool": False,                 # MCP tool detection
    "mcp_server": None,                   # Server name
    "mcp_tool": None,                     # Tool name
}

# Enhanced with:
_extract_checkpoint_info(context, shared_store)  # Adds checkpoint data
_check_mcp_tool_error(context, shared_store)     # Detects MCP errors
_analyze_template_errors(context, errors)        # Analyzes templates
```

**This context is used to build the repair prompt but NOT exposed to users.**

### 3. Template Issue Details

For template errors, additional context includes:

```python
{
    "template": "${data.user.name}",      # The unresolved template
    "available_fields": ["id", "login"],  # What fields are available
    "node_id": "process",                 # Where template is used
    "source_node": "fetch"                # Where data comes from
}
```

**Status**: Only available in repair prompt, not shown to users

### 4. API Warning Details

For API errors, warnings are tracked:

```python
shared["__warnings__"] = {
    "node-id": "API returned error: 404 Not Found"
}
shared["__non_repairable_error__"] = True
```

**Status**: Internal only, not shown in error output

### 5. Shared Store Mutations

The full shared store state at failure contains:

- All intermediate data from successful nodes
- Template resolution context
- Node outputs and namespaced data
- System flags and metadata

**Status**: Available in `result.shared_after` but not displayed to users

## Summary of Findings

### Current State with --no-repair

**Error Information Returned to CLI**:
1. Basic error message (`error["message"]`)
2. Node ID (`error["node_id"]`)
3. Error category (`error["category"]`)
4. Node type (`error["node_type"]`)

**Rich Context Available But Not Shown**:
1. **Checkpoint data**: Which nodes completed successfully
2. **Execution progress**: Full workflow execution history
3. **Template details**: Available fields, attempted templates
4. **API context**: What was attempted vs. what's valid
5. **Shared store state**: All intermediate data at failure
6. **Repair guidance**: Whether error is fixable, category-specific hints

### Key Insight

**The repair system builds comprehensive error context that would be valuable for debugging, but this context is never exposed to users when --no-repair is used.**

All the information needed for rich error messages exists in:
- `result.errors[*]` - Structured error data with category and context
- `result.shared_after["__execution__"]` - Checkpoint with execution progress
- `result.shared_after["__warnings__"]` - API warnings
- Full shared store - All intermediate data

## Recommendations

The investigation reveals that pflow already captures rich error context internally. The question is: **Should we expose this context to users when --no-repair is used?**

### Option A: No New Flag Needed
Simply enhance error display to show the rich context that already exists in `ExecutionResult`. This would benefit all users regardless of repair settings.

### Option B: Add --verbose-errors Flag
Keep current terse errors, add flag for developers who want full context.

### Option C: New inspect-error Command
Add a separate command to analyze errors from trace files.

**Recommendation**: Start with **Option A** - the data is already there, we just need to format and display it better. This makes error messages more helpful for everyone without requiring new flags or commands.
