# Phase 2: Repair Service Implementation Specification
## Resume-Based Repair with Checkpoint Tracking

### Overview

Phase 2 implements the repair service using a resume-based approach with checkpoint tracking through InstrumentedNodeWrapper. This eliminates duplicate execution and enables self-healing workflows.

### Prerequisites

- Phase 1 completed (WorkflowExecutorService, DisplayManager, thin CLI)
- All Phase 1 tests passing
- Clean architectural boundaries established

### Goals

1. Remove RuntimeValidationNode from planner (12 → 11 nodes)
2. Extend InstrumentedNodeWrapper with checkpoint tracking
3. Implement unified execute_workflow() function
4. Create repair service with LLM-based correction
5. Update CLI to use unified execution
6. Ensure resume from checkpoint works correctly

### Component Specifications

## 1. Extended InstrumentedNodeWrapper

**File**: `src/pflow/runtime/instrumented_wrapper.py` (UPDATE)

Add checkpoint tracking to the existing wrapper:

```python
# Add to imports
from typing import Dict, Any, Optional

class InstrumentedNodeWrapper(BaseNode):
    """Extended with checkpoint tracking for resume capability."""

    def _run(self, shared: Dict[str, Any]) -> str:
        """Execute node with instrumentation and checkpoint tracking."""

        # Initialize checkpoint structure if not present
        if "__execution__" not in shared:
            shared["__execution__"] = {
                "completed_nodes": [],
                "node_actions": {},
                "failed_node": None
            }

        # Check if this node already completed (resume case)
        if self.node_id in shared["__execution__"]["completed_nodes"]:
            # Node already executed - return cached action
            cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")

            # Show cached indicator in progress
            callback = shared.get("__progress_callback__")
            if callable(callback):
                depth = shared.get("_pflow_depth", 0)
                with contextlib.suppress(Exception):
                    # Special event for cached nodes
                    callback(self.node_id, "node_cached", 0, depth)

            logger.info(f"Resuming {self.node_id} with cached action: {cached_action}")
            return cached_action

        # ... existing instrumentation code ...

        try:
            # Execute the wrapped node
            action = self.node._run(shared)

            # Track successful completion
            shared["__execution__"]["completed_nodes"].append(self.node_id)
            shared["__execution__"]["node_actions"][self.node_id] = action

            # ... existing success handling ...

            return action

        except Exception as e:
            # Track failed node for debugging
            shared["__execution__"]["failed_node"] = self.node_id

            # ... existing error handling ...

            raise
```

## 2. Extended OutputController

**File**: `src/pflow/core/output_controller.py` (UPDATE)

Add support for cached node display:

```python
def create_progress_callback(self) -> Optional[Callable]:
    """Create a callback for workflow progress updates."""
    if not self.is_interactive():
        return None

    def progress_callback(
        node_id: str,
        event: str,
        duration_ms: Optional[float] = None,
        depth: int = 0,
    ) -> None:
        indent = "  " * (depth + 1)

        if event == "node_start":
            click.echo(f"{indent}{node_id}...", nl=False, err=True)

        elif event == "node_complete":
            if duration_ms is not None:
                duration_s = duration_ms / 1000.0
                click.echo(f" ✓ {duration_s:.1f}s", err=True)
            else:
                click.echo(" ✓", err=True)

        elif event == "node_cached":  # NEW: Cached node indicator
            click.echo(f"{indent}{node_id}... ↻ cached", err=True)

        elif event == "node_error":
            click.echo(f" ✗ Failed", err=True)

        elif event == "workflow_start":
            if duration_ms:  # duration_ms contains node count
                click.echo(f"Executing workflow ({int(duration_ms)} nodes):", err=True)

    return progress_callback
```

## 3. Unified Execution Function

**File**: `src/pflow/execution/workflow_execution.py` (NEW)

```python
from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

from .executor_service import WorkflowExecutorService, ExecutionResult
from .display_manager import DisplayManager
from .output_interface import OutputInterface

logger = logging.getLogger(__name__)

def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    enable_repair: bool = True,
    max_repair_attempts: int = 3,
    resume_state: Optional[dict] = None,
    original_request: Optional[str] = None,
    output: Optional[OutputInterface] = None,
    workflow_manager: Optional[Any] = None,
    workflow_name: Optional[str] = None,
    stdin_data: Optional[Any] = None,
    output_key: Optional[str] = None,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None
) -> ExecutionResult:
    """
    Unified workflow execution function with automatic repair capability.

    This is THE primary execution function for all workflows. Repair is just
    a feature flag, not a separate code path.

    Args:
        workflow_ir: The workflow IR to execute
        execution_params: Parameters for template resolution
        enable_repair: Whether to attempt repair on failure (default: True)
        max_repair_attempts: Maximum repair attempts (default: 3)
        resume_state: Shared store from previous execution for resume
        original_request: Original user request for repair context
        output: Output interface for display
        workflow_manager: For metadata updates
        workflow_name: Name of workflow being executed
        stdin_data: Data from stdin
        output_key: Key to extract from shared store
        metrics_collector: For metrics tracking
        trace_collector: For execution tracing

    Returns:
        ExecutionResult with success status and execution details
    """
    from .null_output import NullOutput

    # Default output if not provided
    if output is None:
        output = NullOutput()

    # Create display manager
    display = DisplayManager(output=output)

    # Prepare shared store
    if resume_state:
        # Resume from checkpoint
        shared_store = resume_state
        display.show_execution_start(
            node_count=len(workflow_ir.get("nodes", [])),
            context="resume"
        )
    else:
        # Fresh execution
        shared_store = {}
        display.show_execution_start(
            node_count=len(workflow_ir.get("nodes", []))
        )

    # Create executor service
    executor = WorkflowExecutorService(
        output_interface=output,
        workflow_manager=workflow_manager
    )

    # Execute workflow
    result = executor.execute_workflow(
        workflow_ir=workflow_ir,
        execution_params=execution_params,
        shared_store=shared_store,  # Contains checkpoint if resuming
        workflow_name=workflow_name,
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=trace_collector
    )

    if result.success:
        display.show_execution_result(True, result.output_data)
        return result

    # Execution failed
    if not enable_repair or not result.errors:
        display.show_execution_result(False)
        return result

    # Attempt repair
    display.show_repair_start()

    # Extract error context
    if result.errors:
        first_error = result.errors[0]
        display.show_repair_issue(
            first_error.get("message", "Unknown error"),
            first_error.get("additional_context")
        )

    # Repair workflow
    from .repair_service import repair_workflow

    success, repaired_ir = repair_workflow(
        workflow_ir=workflow_ir,
        errors=result.errors,
        original_request=original_request,
        shared_store=result.shared_after  # Pass for context
    )

    if not success:
        display.show_repair_result(False)
        display.show_execution_result(False)
        return result

    display.show_repair_result(True)

    # Resume execution with repaired workflow
    # The checkpoint data in shared_store allows resume from failure point
    return execute_workflow(
        workflow_ir=repaired_ir,
        execution_params=execution_params,
        enable_repair=False,  # Don't repair the repair
        resume_state=result.shared_after,  # RESUME WITH CHECKPOINT!
        original_request=original_request,
        output=output,
        workflow_manager=workflow_manager,
        workflow_name=workflow_name,
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=trace_collector
    )
```

## 4. Repair Service

**File**: `src/pflow/execution/repair_service.py` (NEW)

```python
from typing import Tuple, Optional, Dict, Any, List
import logging
import json
import llm

logger = logging.getLogger(__name__)

def repair_workflow(
    workflow_ir: dict,
    errors: List[Dict[str, Any]],
    original_request: Optional[str] = None,
    shared_store: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[dict]]:
    """
    Attempt to repair a broken workflow using LLM.

    Args:
        workflow_ir: The workflow that failed
        errors: List of error dictionaries from execution
        original_request: Original user request for context
        shared_store: Execution state for additional context

    Returns:
        (success, repaired_workflow_ir or None)
    """
    if not errors:
        return False, None

    # Analyze errors for repair context
    repair_context = _analyze_errors_for_repair(errors, shared_store)

    # Generate repair prompt
    prompt = _create_repair_prompt(
        workflow_ir=workflow_ir,
        errors=errors,
        repair_context=repair_context,
        original_request=original_request
    )

    try:
        # Use Haiku for fast, cheap repairs
        model = llm.get_model("anthropic/claude-3-haiku-20240307")

        # Generate repair
        response = model.prompt(prompt)

        # Extract repaired workflow from response
        repaired_ir = _extract_workflow_from_response(response.text())

        # Basic validation
        if not _validate_repaired_workflow(repaired_ir):
            logger.warning("Repaired workflow failed validation")
            return False, None

        logger.info("Successfully generated workflow repair")
        return True, repaired_ir

    except Exception as e:
        logger.error(f"Repair generation failed: {e}")
        return False, None

def _analyze_errors_for_repair(
    errors: List[Dict[str, Any]],
    shared_store: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Extract repair context from errors and execution state.

    Pattern inspired by RuntimeValidationNode's error analysis.
    """
    context = {
        "primary_error": errors[0] if errors else {},
        "error_count": len(errors),
        "completed_nodes": [],
        "failed_node": None
    }

    # Extract checkpoint information if available
    if shared_store and "__execution__" in shared_store:
        execution_data = shared_store["__execution__"]
        context["completed_nodes"] = execution_data.get("completed_nodes", [])
        context["failed_node"] = execution_data.get("failed_node")

    # Analyze template errors (simplified from RuntimeValidationNode)
    primary_error = context["primary_error"]
    if "template" in primary_error.get("message", "").lower():
        # Extract template context
        if primary_error.get("additional_context"):
            context["template_issues"] = primary_error["additional_context"]

    return context

def _create_repair_prompt(
    workflow_ir: dict,
    errors: List[Dict[str, Any]],
    repair_context: Dict[str, Any],
    original_request: Optional[str]
) -> str:
    """Create prompt for LLM repair."""

    # Format errors for prompt
    error_text = _format_errors_for_prompt(errors, repair_context)

    prompt = f"""Fix this workflow that failed during execution.

## Original Request
{original_request or "Not available"}

## Failed Workflow
```json
{json.dumps(workflow_ir, indent=2)}
```

## Execution Errors
{error_text}

## Repair Context
- Completed nodes: {', '.join(repair_context.get('completed_nodes', []))}
- Failed at node: {repair_context.get('failed_node', 'unknown')}

## Your Task
Analyze the errors and generate a corrected workflow that fixes the issues.

Common fixes needed:
1. Template variable corrections (e.g., ${data.username} → ${data.login})
2. Missing parameters in node configs
3. Incorrect field references
4. Shell command syntax errors
5. API response structure changes

Return ONLY the corrected workflow JSON. Do not include explanations.

## Corrected Workflow
```json
"""

    return prompt

def _format_errors_for_prompt(
    errors: List[Dict[str, Any]],
    repair_context: Dict[str, Any]
) -> str:
    """Format errors for LLM consumption."""
    lines = []

    for i, error in enumerate(errors, 1):
        message = error.get("message", "Unknown error")
        lines.append(f"{i}. {message}")

        # Add template context if available
        if repair_context.get("template_issues"):
            for issue in repair_context["template_issues"].get("missing_templates", []):
                template = issue.get("template", "unknown")
                available = issue.get("available_fields", [])
                lines.append(f"   - Template {template} not found")
                if available:
                    lines.append(f"     Available fields: {', '.join(available)}")

    return "\n".join(lines)

def _extract_workflow_from_response(response: str) -> Optional[dict]:
    """Extract JSON workflow from LLM response."""
    import re

    # Find JSON block in response
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to parse entire response as JSON
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in response
    json_start = response.find('{')
    json_end = response.rfind('}') + 1
    if json_start >= 0 and json_end > json_start:
        try:
            return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass

    return None

def _validate_repaired_workflow(workflow_ir: Optional[dict]) -> bool:
    """Basic validation of repaired workflow."""
    if not workflow_ir:
        return False

    # Check required fields
    if "ir_version" not in workflow_ir:
        return False
    if "nodes" not in workflow_ir or not workflow_ir["nodes"]:
        return False

    # Check node structure
    for node in workflow_ir["nodes"]:
        if "id" not in node or "type" not in node:
            return False

    return True
```

## 5. Null Output Implementation

**File**: `src/pflow/execution/null_output.py` (NEW)

```python
from typing import Optional, Callable
from .output_interface import OutputInterface

class NullOutput(OutputInterface):
    """Silent output implementation for non-interactive execution."""

    def show_progress(self, message: str, is_error: bool = False) -> None:
        pass  # Silent

    def show_result(self, data: str) -> None:
        pass  # Silent

    def show_error(self, title: str, details: Optional[str] = None) -> None:
        pass  # Silent

    def show_success(self, message: str) -> None:
        pass  # Silent

    def create_node_callback(self) -> Optional[Callable]:
        return None  # No progress tracking

    def is_interactive(self) -> bool:
        return False
```

## 6. Updated CLI Integration

**File**: `src/pflow/cli/main.py` (UPDATE)

Add `--no-repair` flag and update execution:

```python
@click.command(...)
@click.option('--no-repair', is_flag=True, help='Disable automatic repair on failure')
def workflow_command(..., no_repair: bool):
    """Main CLI command with repair option."""

    # ... existing setup ...

    # Store repair preference
    ctx.obj['enable_repair'] = not no_repair

    # ... rest of command ...

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
    Execute workflow using unified execution with repair capability.
    """
    from pflow.execution import execute_workflow
    from pflow.cli.cli_output import CliOutput
    from pflow.core import WorkflowManager

    # Create output interface
    cli_output = CliOutput(
        output_controller=ctx.obj["output_controller"],
        verbose=ctx.obj.get("verbose", False),
        output_format=output_format
    )

    # Get workflow context
    workflow_name = ctx.obj.get("workflow_name")
    original_request = ctx.obj.get("workflow_text", "")

    # Execute with unified function (includes repair capability)
    result = execute_workflow(
        workflow_ir=ir_data,
        execution_params=execution_params or {},
        enable_repair=ctx.obj.get('enable_repair', True),  # Default: repair enabled
        original_request=original_request,
        output=cli_output,
        workflow_manager=WorkflowManager() if workflow_name else None,
        workflow_name=workflow_name,
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=ctx.obj.get("workflow_trace")
    )

    # Handle JSON output mode
    if output_format == "json":
        output_data = {
            "success": result.success,
            "result": result.output_data,
            "errors": result.errors if not result.success else None,
            "metrics": result.metrics_summary
        }
        click.echo(json.dumps(output_data))

    # Save trace if enabled
    if ctx.obj.get("workflow_trace"):
        trace_file = ctx.obj["workflow_trace"].save_to_file()
        if ctx.obj.get("verbose"):
            click.echo(f"📊 Workflow trace saved: {trace_file}", err=True)

    # Exit with appropriate code
    ctx.exit(0 if result.success else 1)
```

## 7. Remove RuntimeValidationNode

**File**: `src/pflow/planning/flow.py` (UPDATE)

Remove RuntimeValidationNode from planner flow with these EXACT line numbers:

```python
# Line 27: Remove from imports
# Remove: RuntimeValidationNode,

# Line 70: Remove node creation
# Remove: runtime_validation: Node = RuntimeValidationNode()  # NEW: Runtime validation node

# Line 89: Remove debug wrapper
# Remove: runtime_validation = DebugWrapper(runtime_validation, debug_context)  # type: ignore[assignment]

# Line 159: CRITICAL - Redirect validator output
# Change FROM:
#   validator - "runtime_validation" >> runtime_validation
# Change TO:
#   validator - "metadata_generation" >> metadata_generation

# Line 173: Remove flow wiring
# Remove: runtime_validation >> metadata_generation

# Line 177: Remove flow wiring
# Remove: runtime_validation - "runtime_fix" >> workflow_generator

# Line 179: Remove flow wiring
# Remove: runtime_validation - "failed_runtime" >> result_preparation

# Line 57: Update node count in log
# Change: logger.debug("Creating planner flow with 12 nodes")
# To: logger.debug("Creating planner flow with 11 nodes")

# Line 214: Update node count in docstring
# Change: "Planner flow created with 12 nodes: 2-path architecture with Requirements/Planning enhancement and Runtime Validation"
# To: "Planner flow created with 11 nodes: 2-path architecture with Requirements/Planning enhancement"
```

**File**: `src/pflow/planning/nodes.py` (UPDATE)

```python
# Lines 2882-3387: Delete entire RuntimeValidationNode class
# IMPORTANT: Line numbers are 2882-3387, NOT 2745-3201

# Line 1988: Update comment that references RuntimeValidationNode
# Change: "runtime_errors": shared.get("runtime_errors", []),  # NEW: Runtime errors from RuntimeValidationNode
# To: "runtime_errors": shared.get("runtime_errors", []),  # Legacy: Was used by RuntimeValidationNode
```

**Files to DELETE completely**:
- `tests/test_runtime_validation.py`
- `tests/test_runtime_validation_simple.py`
- `tests/test_runtime/test_runtime_validation_core.py`
- `tests/test_planning/integration/test_runtime_validation_flow.py`
- `examples/runtime_feedback_demo.py`

**File to UPDATE comment only**:
- `tests/test_planning/integration/test_parameter_runtime_flow.py` (line 35 - update comment)

## Testing Strategy

### Unit Tests

1. **Test checkpoint tracking in InstrumentedNodeWrapper**
   - Verify nodes marked as completed
   - Test resume behavior (cached action returned)
   - Verify no re-execution of completed nodes

2. **Test execute_workflow()**
   - Fresh execution path
   - Resume from checkpoint
   - Repair triggering and retry
   - Max repair attempts

3. **Test repair_service**
   - Error analysis
   - Prompt generation
   - Response parsing
   - Workflow validation

### Integration Tests

1. **End-to-end repair flow**
   - Workflow fails → repair → resume → success
   - Multiple repair attempts
   - Non-fixable errors

2. **Resume correctness**
   - Verify no duplicate side effects
   - Check data flow preservation
   - Validate checkpoint integrity

## Success Criteria

1. **No duplicate execution** - Nodes run exactly once
2. **Transparent repair** - Clear progress messages
3. **Planner tests pass** with 11 nodes instead of 12
4. **All existing workflows** continue to work
5. **Resume from checkpoint** works correctly
6. **Repair success rate** > 80% for fixable errors

## Implementation Order

1. Extend InstrumentedNodeWrapper with checkpoint tracking
2. Extend OutputController with cached display
3. Create repair_service.py with LLM integration
4. Create execute_workflow() unified function
5. Update CLI to use unified execution
6. Remove RuntimeValidationNode from planner
7. Delete RuntimeValidation tests
8. Create new tests for repair flow
9. Integration testing

## Migration Notes

### Breaking Changes
- Planner now has 11 nodes instead of 12
- RuntimeValidationNode no longer exists

### New Features
- `--no-repair` flag disables automatic repair
- Workflows auto-repair by default
- Resume from checkpoint capability

### Performance Impact
- Faster execution due to resume (no re-execution)
- Slight overhead for checkpoint tracking (~1ms per node)
- Repair adds time only on failure (not success path)

This phase completes the vision of self-healing workflows with transparent repair and zero duplicate execution.