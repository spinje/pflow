# Phase 1: Foundation Refactoring Specification
## Extract Execution Logic and Create Display Abstraction

### Overview

Phase 1 creates the foundational components needed for the unified execution system by extracting execution logic from the CLI into reusable services. This phase produces a working system with the same functionality as today but with clean architectural boundaries.

### Goals

1. Extract workflow execution logic from CLI into WorkflowExecutorService
2. Create display abstraction (OutputInterface) for Click-independence
3. Implement DisplayManager for reusable UX logic
4. Refactor CLI to thin pattern (command parsing only)
5. Add update_metadata() to WorkflowManager

### Component Specifications

## 1. OutputInterface Protocol

**File**: `src/pflow/execution/output_interface.py` (NEW)

```python
from typing import Protocol, Optional, Callable

class OutputInterface(Protocol):
    """Abstract interface for all output display operations."""

    def show_progress(self, message: str, is_error: bool = False) -> None:
        """Display a progress message."""
        ...

    def show_result(self, data: str) -> None:
        """Display result data (always to stdout)."""
        ...

    def show_error(self, title: str, details: Optional[str] = None) -> None:
        """Display an error message."""
        ...

    def show_success(self, message: str) -> None:
        """Display a success message."""
        ...

    def create_node_callback(self) -> Optional[Callable]:
        """Create callback for node execution progress."""
        ...

    def is_interactive(self) -> bool:
        """Check if output is interactive (not piped/JSON)."""
        ...
```

## 2. CLI Output Implementation

**File**: `src/pflow/cli/cli_output.py` (NEW)

```python
from typing import Optional, Callable
import click
from pflow.execution.output_interface import OutputInterface
from pflow.core import OutputController

class CliOutput(OutputInterface):
    """Click-based implementation of OutputInterface."""

    def __init__(self,
                 output_controller: OutputController,
                 verbose: bool = False,
                 output_format: str = "text"):
        self.output_controller = output_controller
        self.verbose = verbose
        self.output_format = output_format

    def show_progress(self, message: str, is_error: bool = False) -> None:
        if self.output_controller.is_interactive():
            click.echo(message, err=is_error)

    def show_result(self, data: str) -> None:
        click.echo(data)  # Always to stdout

    def show_error(self, title: str, details: Optional[str] = None) -> None:
        if self.output_format != "json":
            click.echo(f"❌ {title}", err=True)
            if details and self.verbose:
                click.echo(details, err=True)

    def show_success(self, message: str) -> None:
        if self.output_format != "json":
            click.echo(f"✅ {message}")

    def create_node_callback(self) -> Optional[Callable]:
        return self.output_controller.create_progress_callback()

    def is_interactive(self) -> bool:
        return self.output_controller.is_interactive()
```

## 3. Display Manager

**File**: `src/pflow/execution/display_manager.py` (NEW)

```python
from dataclasses import dataclass
from typing import Optional, Any
from .output_interface import OutputInterface

@dataclass
class DisplayManager:
    """Manages all workflow execution display operations."""

    output: OutputInterface

    def show_execution_start(self, node_count: int, context: str = "") -> None:
        """Show workflow execution starting."""
        if context == "resume":
            message = f"Resuming workflow from checkpoint..."
        elif context == "repair_validation":
            message = f"Validating repair ({node_count} nodes):"
        else:
            message = f"Executing workflow ({node_count} nodes):"

        self.output.show_progress(message)

    def show_node_progress(self, node_id: str, status: str, duration: float = 0) -> None:
        """Show individual node progress."""
        if status == "cached":
            self.output.show_progress(f"  {node_id}... ↻ cached")
        elif status == "success":
            self.output.show_progress(f"  {node_id}... ✓ {duration:.1f}s")
        elif status == "error":
            self.output.show_progress(f"  {node_id}... ✗ Failed", is_error=True)

    def show_execution_result(self, success: bool, data: Optional[str] = None) -> None:
        """Show final execution result."""
        if success:
            self.output.show_success("Workflow executed successfully")
            if data:
                self.output.show_result(data)
        else:
            self.output.show_error("Workflow execution failed")

    def show_repair_start(self) -> None:
        """Show repair process starting."""
        self.output.show_progress("\n🔧 Auto-repairing workflow...")

    def show_repair_issue(self, error_message: str, context: Optional[dict] = None) -> None:
        """Show what issue is being repaired."""
        self.output.show_progress(f"  • Issue detected: {error_message}")

        if context and context.get("available_fields"):
            fields = ", ".join(context["available_fields"])
            self.output.show_progress(f"    Available fields: {fields}")

    def show_repair_result(self, success: bool) -> None:
        """Show repair attempt result."""
        if success:
            self.output.show_progress("  ✅ Workflow repaired successfully!")
        else:
            self.output.show_progress("  ❌ Could not repair automatically")
```

## 4. WorkflowExecutorService

**File**: `src/pflow/execution/executor_service.py` (NEW)

```python
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List
from datetime import datetime
import time
import logging

logger = logging.getLogger(__name__)

@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    success: bool
    shared_after: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    action_result: Optional[str] = None
    node_count: int = 0
    duration: float = 0.0
    output_data: Optional[str] = None
    metrics_summary: Optional[dict] = None

class WorkflowExecutorService:
    """
    Reusable workflow execution service.
    Extracted from CLI to enable use by repair service and future interfaces.
    """

    def __init__(self,
                 output_interface: Optional[OutputInterface] = None,
                 workflow_manager: Optional['WorkflowManager'] = None):
        """
        Initialize executor service.

        Args:
            output_interface: For progress display (optional)
            workflow_manager: For metadata updates (optional)
        """
        self.output = output_interface
        self.workflow_manager = workflow_manager

    def execute_workflow(self,
                        workflow_ir: dict,
                        execution_params: dict,
                        shared_store: Optional[dict] = None,
                        workflow_name: Optional[str] = None,
                        stdin_data: Optional[Any] = None,
                        output_key: Optional[str] = None,
                        metrics_collector: Optional[Any] = None,
                        trace_collector: Optional[Any] = None) -> ExecutionResult:
        """
        Execute a workflow and return structured result.

        This method encapsulates all the execution logic currently in CLI:
        - Registry creation and validation
        - Workflow compilation
        - Shared store preparation
        - Execution with error handling
        - Result extraction
        - Metadata updates
        """
        from pflow.runtime.compiler import compile_ir_to_flow
        from pflow.registry import Registry
        from pflow.core import populate_shared_store

        start_time = time.time()

        # Initialize shared store
        if shared_store is None:
            shared_store = {}

        # Add execution parameters for template resolution
        if execution_params:
            shared_store.update(execution_params)

        # Add stdin data if provided
        if stdin_data:
            populate_shared_store(shared_store, stdin_data)

        # Initialize metrics tracking
        if metrics_collector:
            shared_store["__llm_calls__"] = []
            metrics_collector.record_workflow_start()

        # Add progress callback if output interface provided
        if self.output and self.output.create_node_callback():
            shared_store["__progress_callback__"] = self.output.create_node_callback()

        # Create registry
        registry = Registry()

        try:
            # Compile workflow
            flow = compile_ir_to_flow(
                ir_json=workflow_ir,
                registry=registry,
                initial_params=execution_params,
                validate=True,
                metrics_collector=metrics_collector,
                trace_collector=trace_collector
            )

            # Execute workflow
            action_result = flow.run(shared_store)

            # Determine success (PocketFlow returns action string)
            success = not (action_result and
                          isinstance(action_result, str) and
                          action_result.startswith("error"))

            # Extract output data if requested
            output_data = None
            if output_key and output_key in shared_store:
                output_data = shared_store[output_key]
            elif success:
                # Try to find output using common patterns
                output_data = self._extract_default_output(shared_store, workflow_ir)

            # Build error list if failed
            errors = []
            if not success:
                errors.append({
                    "source": "runtime",
                    "category": "execution_failure",
                    "message": f"Workflow failed with action: {action_result}",
                    "action": action_result,
                    "fixable": True  # Assume fixable for repair
                })

            # Update workflow metadata if manager provided
            if success and self.workflow_manager and workflow_name:
                self.workflow_manager.update_metadata(workflow_name, {
                    "last_execution_timestamp": datetime.now().isoformat(),
                    "last_execution_success": True,
                    "last_execution_params": execution_params,
                    "execution_count": 1  # Will be incremented by manager
                })

        except Exception as e:
            logger.exception("Workflow execution failed with exception")
            success = False
            errors = [{
                "source": "runtime",
                "category": "exception",
                "message": str(e),
                "exception_type": type(e).__name__,
                "fixable": self._is_fixable_error(e)
            }]
            action_result = "error"
            output_data = None

        finally:
            if metrics_collector:
                metrics_collector.record_workflow_end()

        duration = time.time() - start_time

        return ExecutionResult(
            success=success,
            shared_after=shared_store,
            errors=errors,
            action_result=action_result,
            node_count=len(workflow_ir.get("nodes", [])),
            duration=duration,
            output_data=output_data,
            metrics_summary=metrics_collector.get_summary() if metrics_collector else None
        )

    def _extract_default_output(self, shared: dict, workflow_ir: dict) -> Optional[str]:
        """Extract output using workflow declarations or common patterns."""
        # Check declared outputs
        if "outputs" in workflow_ir:
            for output_name in workflow_ir["outputs"]:
                if output_name in shared:
                    return str(shared[output_name])

        # Common output patterns
        for key in ["result", "output", "response", "data"]:
            if key in shared:
                return str(shared[key])

        # Check last node's output
        nodes = workflow_ir.get("nodes", [])
        if nodes:
            last_node_id = nodes[-1].get("id")
            if last_node_id in shared:
                node_output = shared[last_node_id]
                if isinstance(node_output, dict):
                    for key in ["result", "output", "response"]:
                        if key in node_output:
                            return str(node_output[key])

        return None

    def _is_fixable_error(self, exception: Exception) -> bool:
        """Determine if an error can be fixed by repair."""
        error_msg = str(exception).lower()

        # Non-fixable infrastructure/auth issues
        non_fixable_keywords = [
            "api key", "authentication", "unauthorized", "forbidden",
            "rate limit", "quota", "connection refused", "timeout",
            "permission denied", "out of memory"
        ]

        for keyword in non_fixable_keywords:
            if keyword in error_msg:
                return False

        # Template and field errors are usually fixable
        fixable_keywords = [
            "template", "field", "not found", "missing", "undefined",
            "key error", "attribute", "type error", "value error"
        ]

        for keyword in fixable_keywords:
            if keyword in error_msg:
                return True

        # Default to optimistically fixable
        return True
```

## 5. WorkflowManager Update

**File**: `src/pflow/core/workflow_manager.py` (UPDATE)

Add this method to the existing WorkflowManager class:

```python
def update_metadata(self, workflow_name: str, updates: dict) -> None:
    """
    Update workflow metadata after execution.

    Args:
        workflow_name: Name of the workflow to update
        updates: Dictionary of metadata fields to update

    Raises:
        FileNotFoundError: If workflow doesn't exist
    """
    import json
    import tempfile
    import os
    from datetime import datetime, timezone
    from pathlib import Path

    workflow_path = self._get_workflow_path(workflow_name)

    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow not found: {workflow_name}")

    # Load existing workflow data
    workflow_data = self.load(workflow_name)

    # Initialize rich_metadata if not present
    if "rich_metadata" not in workflow_data:
        workflow_data["rich_metadata"] = {}

    # Handle execution_count increment specially
    if "execution_count" in updates:
        current_count = workflow_data["rich_metadata"].get("execution_count", 0)
        workflow_data["rich_metadata"]["execution_count"] = current_count + 1
        del updates["execution_count"]  # Remove from updates dict

    # Merge remaining updates
    workflow_data["rich_metadata"].update(updates)

    # Update timestamp
    workflow_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Atomic save using temporary file + rename
    with tempfile.NamedTemporaryFile(
        mode='w',
        dir=workflow_path.parent,
        delete=False,
        suffix='.tmp'
    ) as tmp_file:
        json.dump(workflow_data, tmp_file, indent=2)
        tmp_path = tmp_file.name

    try:
        # Atomic replace
        os.replace(tmp_path, workflow_path)
    except Exception:
        # Clean up temp file on failure
        Path(tmp_path).unlink(missing_ok=True)
        raise
```

## 6. CLI Refactoring

**File**: `src/pflow/cli/main.py` (UPDATE)

**IMPORTANT**: The current CLI uses an intermediate function `_execute_workflow_and_handle_result` that must be preserved. The call chain is:
```
execute_json_workflow()
  → _execute_workflow_and_handle_result()
    → _handle_workflow_success/error/exception()
```

Replace `execute_json_workflow` function with thin version:

```python
def execute_json_workflow(
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    planner_llm_calls: list[dict[str, Any]] | None = None,
    output_format: str = "text",
    metrics_collector: Any | None = None,
) -> None:
    """
    Thin CLI wrapper for workflow execution.
    All logic delegated to WorkflowExecutorService.
    """
    from pflow.execution import WorkflowExecutorService
    from pflow.execution import DisplayManager
    from pflow.cli.cli_output import CliOutput
    from pflow.core import WorkflowManager

    # Create output interface
    cli_output = CliOutput(
        output_controller=ctx.obj["output_controller"],
        verbose=ctx.obj.get("verbose", False),
        output_format=output_format
    )

    # Create display manager
    display = DisplayManager(output=cli_output)

    # Get workflow name if available
    workflow_name = ctx.obj.get("workflow_name")

    # Create executor service
    executor = WorkflowExecutorService(
        output_interface=cli_output,
        workflow_manager=WorkflowManager() if workflow_name else None
    )

    # Show execution starting
    node_count = len(ir_data.get("nodes", []))
    display.show_execution_start(node_count)

    # Get workflow trace
    workflow_trace = ctx.obj.get("workflow_trace")

    # Execute workflow
    result = executor.execute_workflow(
        workflow_ir=ir_data,
        execution_params=execution_params or {},
        shared_store=None,  # Fresh execution
        workflow_name=workflow_name,
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=workflow_trace
    )

    # Delegate to intermediate function (preserves existing structure)
    _execute_workflow_and_handle_result(
        ctx=ctx,
        result=result,
        shared_storage=result.shared_after,
        workflow_trace=workflow_trace,
        output_key=output_key,
        ir_data=ir_data,
        output_format=output_format,
        metrics_collector=metrics_collector,
        verbose=ctx.obj.get("verbose", False),
        display=display
    )

def _execute_workflow_and_handle_result(
    ctx: click.Context,
    result: ExecutionResult,
    shared_storage: dict[str, Any],
    workflow_trace: Any | None,
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
    display: DisplayManager
) -> None:
    """
    Intermediate function that routes to appropriate handlers.
    This MUST be preserved for compatibility.
    """
    # Display result
    display.show_execution_result(result.success, result.output_data)

    # Route based on result
    if result.success:
        _handle_workflow_success(
            ctx=ctx,
            workflow_trace=workflow_trace,
            shared_storage=shared_storage,
            output_key=output_key,
            ir_data=ir_data,
            output_format=output_format,
            metrics_collector=metrics_collector,
            verbose=verbose
        )
    else:
        _handle_workflow_error(
            ctx=ctx,
            workflow_trace=workflow_trace,
            output_format=output_format,
            metrics_collector=metrics_collector,
            shared_storage=shared_storage,
            verbose=verbose
        )

# IMPORTANT: These handler signatures have INCONSISTENT parameter ordering
# that must be preserved exactly for compatibility

def _handle_workflow_success(
    ctx: click.Context,
    workflow_trace: Any | None,
    shared_storage: dict[str, Any],
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
) -> None:
    """Success handler - parameter order must be preserved exactly."""
    # Handle JSON output mode
    if output_format == "json":
        # ... existing JSON handling ...
        pass

    # Save trace if enabled
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        if verbose:
            click.echo(f"📊 Workflow trace saved: {trace_file}", err=True)

    ctx.exit(0)

def _handle_workflow_error(
    ctx: click.Context,
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
) -> None:
    """Error handler - note different parameter order from success handler."""
    # Handle JSON output mode
    if output_format == "json":
        # ... existing JSON error handling ...
        pass

    # Save trace if enabled
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        if verbose:
            click.echo(f"📊 Workflow trace saved: {trace_file}", err=True)

    ctx.exit(1)

def _handle_workflow_exception(
    ctx: click.Context,
    e: Exception,
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
) -> None:
    """Exception handler - includes exception parameter."""
    # Handle JSON output mode
    if output_format == "json":
        # ... existing JSON exception handling ...
        pass

    # Save trace if enabled
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        if verbose:
            click.echo(f"📊 Workflow trace saved: {trace_file}", err=True)

    ctx.exit(1)
```

## Testing Strategy

### Unit Tests

1. **Test OutputInterface implementations**
   - Mock CliOutput methods
   - Verify correct delegation to Click/OutputController

2. **Test DisplayManager**
   - Various contexts (execution, resume, repair)
   - Different output formats
   - Error conditions

3. **Test WorkflowExecutorService**
   - Successful execution
   - Failure scenarios
   - Metrics collection
   - Output extraction logic

4. **Test WorkflowManager.update_metadata()**
   - Metadata merging
   - Execution count increment
   - Atomic file operations
   - Error handling

### Integration Tests

1. **CLI Integration**
   - Verify same behavior as before refactoring
   - Test all output modes (text, json, verbose)
   - Verify exit codes

2. **End-to-End Execution**
   - Real workflows execute correctly
   - Progress display works
   - Errors handled properly

## Migration Notes

### Breaking Changes
- None for external users
- Internal CLI functions reorganized

### Deprecations
- Old CLI helper functions can be removed after migration

### Compatibility
- All existing workflows continue to work
- All CLI flags and options unchanged
- Output format identical to current

## Success Criteria

1. **All existing tests pass** without modification
2. **Same user experience** - identical output
3. **Clean separation** - CLI under 200 lines
4. **Reusable components** - Can be used outside CLI
5. **Performance neutral** - No slowdown

## Deliverables

### New Files
- `src/pflow/execution/__init__.py`
- `src/pflow/execution/output_interface.py`
- `src/pflow/execution/display_manager.py`
- `src/pflow/execution/executor_service.py`
- `src/pflow/cli/cli_output.py`

### Modified Files
- `src/pflow/cli/main.py` - Thin wrapper
- `src/pflow/core/workflow_manager.py` - Add update_metadata()

### Test Files
- `tests/test_execution/test_executor_service.py`
- `tests/test_execution/test_display_manager.py`
- `tests/test_cli/test_thin_cli.py`

## Implementation Order

1. Create output_interface.py
2. Create cli_output.py
3. Create display_manager.py
4. Create executor_service.py
5. Add update_metadata() to WorkflowManager
6. Refactor execute_json_workflow()
7. Run tests and fix issues
8. Clean up deprecated code

This phase creates a solid foundation for Phase 2's repair service while maintaining 100% compatibility with existing functionality.