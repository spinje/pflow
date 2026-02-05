# Error Handling Patterns for Nested Workflows

This document captures error handling patterns to consider when implementing Task 59 (Nested Workflows).

## Background

During a dead code cleanup (Feb 2026), we removed several exception classes that were designed but never used:
- `WorkflowExecutionError` - designed for nested workflow error tracking
- `CircularWorkflowReferenceError` - designed for circular dependency detection
- `RuntimeValidationError` - designed for LLM repair feedback loop

These were removed because the codebase uses a simpler, more pragmatic pattern:
- **Validation phase**: Returns error strings (never raises)
- **Runtime phase**: Catches everything, converts to error dicts
- **Display phase**: CLI formats based on output mode

## Current Error Pattern

The current pattern works well and is flexible:

```python
# executor_service.py
def _handle_execution_exception(self, exception):
    return {
        "success": False,
        "errors": [{
            "source": "runtime",
            "node_id": node_id,
            "message": str(exception),
            "exception_type": type(exception).__name__,
            "category": "exception",
        }]
    }
```

## Patterns to Consider for Task 59

### 1. Workflow Path Tracking

When a nested workflow fails, users need to see the execution path. Instead of a custom exception, consider enriching the error dict:

```python
# In nested workflow executor
def execute_nested_workflow(self, workflow_ref, parent_path):
    current_path = parent_path + [workflow_ref]
    try:
        result = self._execute(workflow_ir)
        return result
    except Exception as e:
        return {
            "success": False,
            "errors": [{
                "source": "nested_workflow",
                "workflow_path": current_path,  # ["main.pflow.md", "sub.pflow.md", "failing.pflow.md"]
                "message": str(e),
                "node_id": failing_node_id,
            }]
        }
```

Display example:
```
Error: Node execution failed
Workflow path: main.pflow.md → processor.pflow.md → analyzer.pflow.md
Node: sentiment-analysis
Message: API rate limit exceeded
```

### 2. Circular Dependency Detection

Detect cycles before execution, return as validation error:

```python
# In nested workflow validation
def validate_nested_workflow(workflow_ir, execution_stack):
    workflow_ref = workflow_ir.get("params", {}).get("workflow_ref")

    if workflow_ref in execution_stack:
        return [f"Circular workflow reference: {' → '.join(execution_stack + [workflow_ref])}"]

    # Continue validation with updated stack
    return validate_children(workflow_ir, execution_stack + [workflow_ref])
```

### 3. Error Context Propagation

Nested errors should include context from parent:

```python
error = {
    "source": "nested_workflow",
    "workflow_ref": "validators/api_response.pflow.md",
    "workflow_path": ["main.pflow.md", "validators/api_response.pflow.md"],
    "node_id": "validate-response",
    "message": "Schema validation failed",
    "child_errors": [  # Preserve child workflow errors
        {"node_id": "check-format", "message": "Invalid JSON structure"}
    ],
    "parent_context": {
        "input_mapping": {"response": "${api_data}"},
        "storage_mode": "mapped"
    }
}
```

### 4. Max Depth Protection

Prevent stack exhaustion with depth limiting:

```python
MAX_WORKFLOW_DEPTH = 10  # Configurable

def execute_nested_workflow(workflow_ir, current_depth=0):
    if current_depth >= MAX_WORKFLOW_DEPTH:
        return {
            "success": False,
            "errors": [{
                "source": "nested_workflow",
                "category": "depth_exceeded",
                "message": f"Maximum workflow nesting depth ({MAX_WORKFLOW_DEPTH}) exceeded",
                "suggestion": "Reduce nesting levels or increase max_depth parameter"
            }]
        }
```

## Why Error Dicts Over Custom Exceptions

1. **Flexibility**: Easy to add new fields without changing exception hierarchy
2. **Serialization**: Error dicts serialize to JSON naturally for CLI output
3. **Accumulation**: Multiple errors can be collected without try/except chains
4. **LLM-friendly**: Structured data is easier for LLMs to parse and suggest fixes
5. **Consistency**: Same pattern used everywhere (validation, runtime, display)

## Implementation Recommendation

When implementing Task 59:

1. **Don't create custom exception classes** - use error dicts with standardized fields
2. **Add `workflow_path` field** to track execution hierarchy
3. **Detect cycles in validation phase** - return as validation errors
4. **Preserve child errors** - include in parent error for full context
5. **Add depth limiting** - prevent infinite recursion
6. **Document error format** - so CLI/MCP can display consistently

## Related Files

- `src/pflow/execution/executor_service.py` - Current error handling
- `src/pflow/core/workflow_validator.py` - Validation error pattern
- `src/pflow/cli/main.py` - Error display logic
- `.taskmaster/tasks/task_59/research/nested-workflows-spec.md` - Full spec
