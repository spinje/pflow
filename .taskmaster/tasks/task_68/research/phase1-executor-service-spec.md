# Phase 1: WorkflowExecutorService & Metadata Infrastructure

## Overview
Extract workflow execution logic from CLI into a reusable service that can be used by both CLI and repair flows. Add metadata tracking for execution history.

## Goals
1. Create `WorkflowExecutorService` that handles workflow execution with configurable error behavior
2. Add `update_metadata()` method to `WorkflowManager`
3. Extend metadata structure to track execution history
4. Refactor CLI to use the new service (maintaining exact same user experience)
5. Ensure all existing tests pass

## Implementation Tasks

### 1. Create WorkflowExecutorService
**File**: `src/pflow/core/workflow_executor_service.py` (NEW)

```python
from dataclasses import dataclass
from typing import Any, Optional, Union
from datetime import datetime

@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    success: bool
    action_result: str | None = None  # Action string from flow.run() (e.g., "default", "error")
    errors: list[dict] = None
    shared_after: dict = None
    node_count: int = 0
    duration: float = 0.0
    metrics_summary: dict | None = None  # From MetricsCollector

class WorkflowExecutorService:
    """Reusable workflow execution service."""

    def __init__(self,
                 workflow_manager: Optional[WorkflowManager] = None,
                 output_controller: Optional[OutputController] = None,
                 abort_on_first_error: bool = True):
        """
        Initialize executor service.

        Args:
            workflow_manager: For updating metadata (optional)
            output_controller: For progress display (optional)
                             Created as OutputController(print_flag, output_format)
            abort_on_first_error: If True, stop on first error (CLI mode)
                                 If False, collect all errors (repair mode)
        """

    def execute_workflow(self,
                        workflow_ir: dict,
                        execution_params: dict,
                        workflow_name: Optional[str] = None,
                        stdin_data: Optional[Any] = None,
                        output_key: Optional[str] = None,
                        planner_llm_calls: Optional[list] = None,
                        metrics_collector: Optional[Any] = None,
                        trace_collector: Optional[Any] = None) -> ExecutionResult:
        """Execute a workflow and return structured result.

        Must handle:
        - Creating Registry() instance
        - Calling compile_ir_to_flow with all parameters
        - Initializing shared["__llm_calls__"] if metrics_collector provided
        - Adding __progress_callback__ if output_controller.is_interactive()
        - Detecting success: flow.run() returns action string;
          success = not (result and result.startswith("error"))
        - Updating workflow metadata if workflow_manager and workflow_name provided
        """
```

**Key Features**:
- Configurable error behavior via `abort_on_first_error`
- Optional progress display through `OutputController`
- Returns structured `ExecutionResult` with all execution data
- Automatically updates workflow metadata if name provided

**⚠️ CRITICAL LIMITATION**:
PocketFlow's `flow.run()` stops on first error by design. When `abort_on_first_error=False`, we cannot actually collect multiple errors using standard flow execution. For Phase 1, this parameter will be a placeholder - both modes will capture only the first error. Full multi-error collection would require custom node-by-node execution (deferred to Phase 2).

**Critical Implementation Details**:
```python
# Import required modules
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry import Registry
from pflow.core import OutputController, WorkflowManager

# Inside execute_workflow method:

# 1. Create registry
registry = Registry()

# 2. Initialize shared store
shared_storage = {}
if planner_llm_calls:
    shared_storage["__llm_calls__"] = planner_llm_calls
elif metrics_collector:
    shared_storage["__llm_calls__"] = []

# 3. Add progress callback if interactive
if output_controller and output_controller.is_interactive():
    callback = output_controller.create_progress_callback()
    if callback:
        shared_storage["__progress_callback__"] = callback

# 4. Compile workflow
flow = compile_ir_to_flow(
    ir_json=workflow_ir,
    registry=registry,
    initial_params=execution_params,
    validate=True,  # Always validate
    metrics_collector=metrics_collector,
    trace_collector=trace_collector
)

# 5. Execute and check result
action_result = flow.run(shared_storage)

# 6. Determine success
# SUCCESS: action_result is None, "default", or doesn't start with "error"
# FAILURE: action_result starts with "error"
success = not (action_result and isinstance(action_result, str) and action_result.startswith("error"))
```

### 2. Extend WorkflowManager
**File**: `src/pflow/core/workflow_manager.py` (UPDATE)

**Current state**: WorkflowManager has NO update methods - only save(), load(), delete(), exists()

**Add NEW method** (does not exist currently):
```python
def update_metadata(self, workflow_name: str, updates: dict) -> None:
    """
    Update workflow metadata after execution.

    IMPORTANT: This method does NOT exist and must be created from scratch.

    Implementation requirements:
    - Load existing workflow using self.load(workflow_name)
    - Merge updates into rich_metadata (create if doesn't exist)
    - Update the "updated_at" timestamp
    - Use atomic save operation (like save() does with os.link())
    - Handle the temporary file cleanup on failure

    Args:
        workflow_name: Name of the workflow to update
        updates: Dictionary of metadata fields to update

    Raises:
        FileNotFoundError: If workflow doesn't exist
    """
    workflow_path = self._get_workflow_path(workflow_name)

    # Load existing
    workflow_data = self.load(workflow_name)

    # Merge updates into rich_metadata
    if "rich_metadata" not in workflow_data:
        workflow_data["rich_metadata"] = {}
    workflow_data["rich_metadata"].update(updates)
    workflow_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Atomic save (reuse _perform_atomic_save pattern from save() method)
    # ... implement atomic file replacement ...
```

### 3. Extend Metadata Structure
**Location**: Update `rich_metadata` in saved workflows

Add these fields:
```json
{
  "rich_metadata": {
    // ... existing fields ...

    // Execution tracking (NEW)
    "last_execution_timestamp": "ISO-8601 timestamp",
    "last_execution_success": true/false,
    "last_execution_params": {...},
    "last_execution_errors": [...],
    "execution_count": 0
  }
}
```

### 4. Refactor CLI
**File**: `src/pflow/cli/main.py` (UPDATE)

Replace the core of `execute_json_workflow()` (currently lines 1390-1462):

```python
def execute_json_workflow(
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None,
    output_key: str | None,
    params: dict[str, Any] | None,
    planner_llm_calls: list[dict] | None,
    output_format: str,
    metrics_collector: Any | None,
) -> None:
    # Get output controller
    output_controller = _get_output_controller(ctx)

    # Create executor service
    from pflow.core.workflow_executor_service import WorkflowExecutorService

    # Get workflow name if available (for metadata updates)
    workflow_name = ctx.obj.get("workflow_name")

    executor = WorkflowExecutorService(
        workflow_manager=WorkflowManager() if workflow_name else None,
        output_controller=output_controller,
        abort_on_first_error=True  # CLI always aborts on first error
    )

    try:
        # Execute workflow
        result = executor.execute_workflow(
            workflow_ir=ir_data,
            execution_params=params or {},
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            planner_llm_calls=planner_llm_calls,
            metrics_collector=metrics_collector,
            trace_collector=workflow_trace  # If tracing enabled
        )

        # Route based on success (matches existing logic at lines 1275-1281)
        if result.success:
            # Call existing handler with EXACT signature
            _handle_workflow_success(
                ctx=ctx,
                workflow_trace=workflow_trace,
                shared_storage=result.shared_after,
                output_key=output_key,
                ir_data=ir_data,
                output_format=output_format,
                metrics_collector=metrics_collector,
                verbose=verbose
            )
        else:
            # Call existing handler with EXACT signature
            _handle_workflow_error(
                ctx=ctx,
                workflow_trace=workflow_trace,
                output_format=output_format,
                metrics_collector=metrics_collector,
                shared_storage=result.shared_after,
                verbose=verbose
            )

    except Exception as e:
        # Call existing exception handler with EXACT signature
        _handle_workflow_exception(
            ctx=ctx,
            e=e,
            workflow_trace=workflow_trace,
            output_format=output_format,
            metrics_collector=metrics_collector,
            shared_storage=result.shared_after if result else {},
            verbose=verbose
        )
```

**IMPORTANT**: The existing `_handle_workflow_success`, `_handle_workflow_error`, and `_handle_workflow_exception` functions must NOT be changed - they have specific signatures that must be matched exactly.

## Success Criteria

1. **No User-Visible Changes**: The CLI works exactly as before
2. **All Tests Pass**: No regression in existing functionality
3. **Metadata Updates Work**: After execution, workflows have updated metadata
4. **Error Collection Mode Works**: When `abort_on_first_error=False`, all errors collected
5. **Progress Display Works**: OutputController integration maintained

## Testing Plan

### Unit Tests
1. Test `WorkflowExecutorService` with both error modes
2. Test `WorkflowManager.update_metadata()`
3. Test metadata structure updates

### Integration Tests
1. Execute workflow via CLI - verify same behavior
2. Execute workflow with errors - verify metadata updated
3. Execute with `abort_on_first_error=False` - verify all errors collected

## Interface for Phase 2

Phase 2 will use these components:

```python
# Import and use
from pflow.core.workflow_executor_service import WorkflowExecutorService, ExecutionResult

# Create executor for repair mode
executor = WorkflowExecutorService(
    workflow_manager=workflow_manager,
    output_controller=output_controller,
    abort_on_first_error=False  # Collect all errors for repair
)

# Execute and get all errors
result = executor.execute_workflow(workflow_ir, params)
if not result.success:
    errors = result.errors  # All collected errors
    shared = result.shared_after  # Final state
```

## Files to Create/Modify

**New Files**:
- `src/pflow/core/workflow_executor_service.py`
- `tests/test_core/test_workflow_executor_service.py`

**Modified Files**:
- `src/pflow/core/workflow_manager.py` (add update_metadata)
- `src/pflow/cli/main.py` (refactor execute_json_workflow)
- `tests/test_core/test_workflow_manager.py` (test update_metadata)

## Critical Implementation Clarifications

### Error Collection Mode (`abort_on_first_error=False`)

When `abort_on_first_error=False`, the service needs to continue execution after errors. This is complex because:

1. **PocketFlow's flow.run() stops on first error** - When a node returns "error" action, the flow terminates
2. **Need custom execution logic** - Can't just call `flow.run()` once

**Suggested Implementation Approach**:
```python
if abort_on_first_error:
    # Normal execution - let flow handle everything
    action_result = flow.run(shared_storage)
else:
    # Error collection mode - execute nodes individually
    # This is similar to what RuntimeValidationNode currently does
    # Look at src/pflow/planning/nodes.py lines 2795-2830 for reference

    # Option 1: Execute the flow and capture whatever we can
    try:
        action_result = flow.run(shared_storage)
    except Exception as e:
        errors_collected.append(format_error(e))
        # Continue to collect more errors from shared state

    # Option 2: Future enhancement - execute nodes one by one
    # This would require deeper integration with PocketFlow
```

**For Phase 1**: Implement Option 1 - just capture the first error even when `abort_on_first_error=False`. Full error collection can be enhanced in Phase 2.

### Node Counting

Use `len(workflow_ir.get("nodes", []))` to count nodes in the workflow.

### MetricsCollector Timing

```python
if metrics_collector:
    metrics_collector.record_workflow_start()
try:
    # ... execution ...
finally:
    if metrics_collector:
        metrics_collector.record_workflow_end()
        llm_calls = shared_storage.get("__llm_calls__", [])
        summary = metrics_collector.get_summary(llm_calls)
        # Include in ExecutionResult
```

## Notes for Implementation

1. **Preserve ALL existing behavior** - This is a refactor, not a feature change
2. **Handle backwards compatibility** - Old workflows without execution metadata should still work
3. **Use existing error formats** - Don't change how errors are structured
4. **Maintain progress callback pattern** - Keep `__progress_callback__` in shared store
5. **Keep metrics collection** - MetricsCollector integration must continue working
6. **Flow returns action strings** - Not result objects; check `action_result.startswith("error")`
7. **Registry created fresh** - `Registry()` is instantiated for each execution
8. **Validate always True** - When calling `compile_ir_to_flow`

## Deliverables

1. Working `WorkflowExecutorService` class
2. Updated `WorkflowManager` with metadata tracking
3. Refactored CLI using the service
4. All tests passing
5. Documentation of the new service API

---

This phase can be implemented independently and provides the foundation for Phase 2's repair service.