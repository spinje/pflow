# Nested Workflow Error Handling Analysis

## Current Error Handling in PocketFlow

### Node-Level Error Handling

1. **Retry Mechanism**:
   - Nodes have `max_retries` and `wait` parameters
   - `exec()` is retried automatically on exceptions
   - After all retries fail, `exec_fallback()` is called

2. **Graceful Fallback**:
   - `exec_fallback(prep_res, exc)` can return a fallback value instead of raising
   - Default behavior is to re-raise the exception
   - Allows nodes to handle errors gracefully

3. **Action-Based Error Routing**:
   - Nodes can return error actions like "error", "failed", etc.
   - Flows can route to error handling nodes based on these actions
   - Example: `node - "error" >> error_handler`

### Flow-Level Error Handling

1. **Flow Execution**:
   - Flows execute nodes sequentially based on actions
   - If a node raises an exception (after retries/fallback), the flow stops
   - No built-in error aggregation or context preservation

2. **Nested Flow Support**:
   - Flows can act as nodes in other flows
   - Flow's `post()` method receives None for exec_res
   - No special error handling for nested flows currently

## Requirements for Nested Workflow Error Handling

### 1. Error Context Preservation

**Requirement**: Maintain error context through nested workflows

**Implementation Options**:
- Add error context to shared store with hierarchical keys
- Create an error stack that tracks nested flow errors
- Include workflow ID/name in error messages

**Example Structure**:
```python
shared["_errors"] = {
    "parent_workflow": {
        "error": "Child workflow failed",
        "child_errors": {
            "data_processing_workflow": {
                "error": "Node 'validate' failed",
                "node_id": "validate-data",
                "exception": "ValidationError: Missing required field"
            }
        }
    }
}
```

### 2. Error Propagation Strategy

**Decision Point**: Stop on first error vs. collect all errors

**Option A - Fail Fast** (Recommended for MVP):
- Stop execution on first error
- Preserve full error context and stack trace
- Simple to implement and debug
- Matches current PocketFlow behavior

**Option B - Error Collection**:
- Continue execution where possible
- Collect all errors in a list
- More complex state management
- Useful for validation scenarios

### 3. Error Reporting

**Requirements**:
- Clear indication of which nested workflow failed
- Full path from parent to failing node
- Original exception details preserved
- Actionable error messages

**Proposed Error Format**:
```
WorkflowExecutionError: Child workflow 'data-processing' failed
  Path: main-workflow -> data-processing -> validate-node
  Original Error: ValidationError: Missing required field 'email'
  Node ID: validate-data
  Node Type: validate-json
```

### 4. Debugging Features

**Storage Snapshots**:
- Capture shared store state at error time
- Include in error context for debugging
- Optional verbose mode for full dumps

**Execution Trace**:
- Log workflow execution path
- Include timing information
- Show action transitions

### 5. Partial Success Handling

**Requirements**:
- Some workflows may want to continue despite child failures
- Need a way to mark workflows as "optional" or "critical"
- Parent workflow decides how to handle child failures

**Implementation Options**:
```python
# Option 1: Error tolerance parameter
child_flow = Flow(start=node, error_tolerant=True)

# Option 2: Error handling in parent
parent_flow - "child_error" >> handle_child_error

# Option 3: Try-catch pattern with wrapper node
try_wrapper = TryNode(child_flow, fallback_action="continue")
```

### 6. Error Recovery Patterns

**Compensating Transactions**:
- Ability to rollback or compensate for partial completion
- Store compensation actions in workflow metadata

**Checkpoint/Resume**:
- Save workflow state periodically
- Allow resuming from last successful node
- Out of scope for MVP

## Implementation Recommendations for MVP

### 1. Minimal Error Context (Required)

Add error context to CompilationError and runtime errors:
```python
class WorkflowExecutionError(Exception):
    def __init__(self, message, workflow_path=None, node_id=None,
                 node_type=None, original_error=None):
        self.workflow_path = workflow_path or []
        self.node_id = node_id
        self.node_type = node_type
        self.original_error = original_error
        super().__init__(self._format_message(message))
```

### 2. Enhanced Flow Execution

Modify Flow._orch() to track execution path:
```python
def _orch(self, shared, params=None, parent_path=None):
    execution_path = (parent_path or []) + [self.name or "unnamed_flow"]
    try:
        # ... existing orchestration logic ...
    except Exception as e:
        # Wrap with context
        raise WorkflowExecutionError(
            "Workflow execution failed",
            workflow_path=execution_path,
            node_id=current_node_id,
            original_error=e
        )
```

### 3. Error Action Convention

Establish convention for error actions:
- Nodes return "error" action on recoverable errors
- Flows can handle with: `node - "error" >> error_handler`
- Unhandled "error" actions stop execution with clear message

### 4. CLI Error Reporting

Enhanced error reporting in CLI:
```python
except WorkflowExecutionError as e:
    click.echo(f"cli: Workflow execution failed", err=True)
    click.echo(f"  Path: {' -> '.join(e.workflow_path)}", err=True)
    if e.node_id:
        click.echo(f"  Failed at: {e.node_id} ({e.node_type})", err=True)
    if e.original_error:
        click.echo(f"  Error: {e.original_error}", err=True)
    if verbose:
        # Show full traceback and store snapshot
```

## Future Enhancements (Post-MVP)

1. **Error Recovery Workflows**: Special workflows triggered on errors
2. **Retry Policies**: Configurable retry strategies per workflow
3. **Error Metrics**: Track error rates and patterns
4. **Circuit Breakers**: Prevent cascading failures
5. **Async Error Handling**: For parallel execution
6. **Error Webhooks**: Notify external systems of failures

## Summary

For the MVP, implement:
1. Basic error context preservation (workflow path, node info)
2. Fail-fast strategy with clear error messages
3. Convention for error actions ("error" return value)
4. Enhanced CLI error reporting
5. Optional debug information (shared store snapshot)

This provides a solid foundation for error handling in nested workflows while keeping the implementation simple and aligned with PocketFlow's existing patterns.
