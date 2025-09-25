# Task 68 Phase 2: Detailed Implementation Plan

## Overview
Phase 2 adds checkpoint/resume capability and automatic repair to workflow execution. This plan addresses all ambiguities and assumptions before implementation begins.

## Critical Clarifications

### What We're Building
- **Checkpoint/Resume System**: NOT a cache. Nodes that already executed are skipped on resume.
- **Auto-Repair**: Single repair attempt on failure (not 3 as spec suggests - simpler for MVP)
- **Progress Display**: Only adds "↻ cached" indicator, no error indicators (✗)

### What We're NOT Building
- Error indicators in progress display
- Multiple repair attempts with backoff
- Complex cache invalidation
- Detailed error messages in UI

## Implementation Steps

### Step 1: Extend InstrumentedNodeWrapper (15 min)
**File**: `src/pflow/runtime/instrumented_wrapper.py`

**Changes**:
1. Add checkpoint checking before line 308 (before `self.inner_node._run(shared)`)
2. Add success recording after line 308 (after successful execution)
3. Add failure recording in except block (line 341)

**Exact Implementation**:
```python
# Before line 308, add:
# Initialize checkpoint structure if not present
if "__execution__" not in shared:
    shared["__execution__"] = {
        "completed_nodes": [],
        "node_actions": {},
        "failed_node": None
    }

# Check if node already completed (resume case)
if self.node_id in shared["__execution__"]["completed_nodes"]:
    cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")

    # Call progress callback for cached node
    if callable(callback):
        with contextlib.suppress(Exception):
            callback(self.node_id, "node_cached", None, depth)

    logger.debug(f"Node {self.node_id} skipped (already completed), returning cached action: {cached_action}")
    return cached_action

# After line 308 (successful execution), add:
# Record successful completion
shared["__execution__"]["completed_nodes"].append(self.node_id)
shared["__execution__"]["node_actions"][self.node_id] = result

# In except block after line 341, add:
# Record failure
shared["__execution__"]["failed_node"] = self.node_id
```

**Testing**: Run existing instrumented_wrapper tests to ensure no breakage

### Step 2: Extend OutputController (10 min)
**File**: `src/pflow/core/output_controller.py`

**Changes**:
Add new event handling in `create_progress_callback()` method (around line 205)

**Exact Implementation**:
```python
# After the elif for "node_complete" (around line 211), add:
elif event == "node_cached":
    # Display cached indicator for resumed nodes
    click.echo(" ↻ cached", err=True)
```

**Testing**: Manually verify output shows "↻ cached" for resumed nodes

### Step 3: Create RepairService (45 min)
**File**: `src/pflow/execution/repair_service.py` (NEW)

**Implementation Structure**:
```python
import logging
import json
import re
from typing import Tuple, Optional, Dict, Any, List
import llm

logger = logging.getLogger(__name__)

def repair_workflow(
    workflow_ir: dict,
    errors: List[Dict[str, Any]],
    original_request: Optional[str] = None,
    shared_store: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[dict]]:
    """Main repair function."""
    # 1. Check if errors are repairable
    # 2. Extract error context (simplified from RuntimeValidationNode)
    # 3. Build repair prompt
    # 4. Call LLM (claude-3-haiku)
    # 5. Parse response
    # 6. Return repaired workflow or failure

def _analyze_errors_for_repair(errors: List[Dict[str, Any]], shared_store: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract useful context from errors."""
    # Port simplified logic from RuntimeValidationNode
    # Focus on template errors and field suggestions

def _build_repair_prompt(workflow_ir: dict, errors: List[Dict[str, Any]], context: Dict[str, Any]) -> str:
    """Create LLM prompt for repair."""
    # Simple, focused prompt for Haiku
    # Include workflow, errors, and suggestions

def _extract_workflow_from_response(response_text: str) -> Optional[dict]:
    """Extract JSON workflow from LLM response."""
    # Use regex to find JSON block (like planner does)
    # Fallback to full response parsing
```

**Key Decisions**:
- Use `anthropic/claude-3-haiku-20240307` for speed/cost
- Single repair attempt (no retry loop)
- Focus on template errors (most common)
- Reuse JSON parsing from LLMNode

### Step 4: Create Unified Execution Function (30 min)
**File**: `src/pflow/execution/workflow_execution.py` (NEW)

**Critical Design Decision**:
- This function orchestrates ExecutorService + RepairService
- It does NOT replace ExecutorService, it uses it

**Implementation Structure**:
```python
from .executor_service import WorkflowExecutorService, ExecutionResult
from .repair_service import repair_workflow
from .display_manager import DisplayManager

def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    enable_repair: bool = True,
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
    Unified execution with optional repair.

    Key Logic:
    1. Use ExecutorService to execute
    2. If success, return
    3. If failure and repair enabled:
       a. Show repair message via DisplayManager
       b. Call repair_workflow()
       c. Recursively call self with repaired IR and resume_state
    4. Return final result
    """

    # Initialize display
    display = DisplayManager(output=output or NullOutput())

    # Prepare shared store (with checkpoint if resuming)
    if resume_state:
        shared_store = resume_state
        # Display resume message using existing method
        display.show_execution_start(
            node_count=len(workflow_ir.get("nodes", [])),
            context="resume"
        )
    else:
        shared_store = {}

    # Execute using ExecutorService
    executor = WorkflowExecutorService(
        output_interface=output,
        workflow_manager=workflow_manager
    )

    result = executor.execute_workflow(
        workflow_ir=workflow_ir,
        execution_params=execution_params,
        shared_store=shared_store,  # Pass checkpoint data if resuming
        workflow_name=workflow_name,
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=trace_collector
    )

    # Handle repair if needed
    if not result.success and enable_repair and result.errors:
        display.show_repair_start()  # Uses existing method

        success, repaired_ir = repair_workflow(
            workflow_ir=workflow_ir,
            errors=result.errors,
            original_request=original_request,
            shared_store=result.shared_after  # Pass final state for context
        )

        if success and repaired_ir:
            # Recursive call with resume state
            return execute_workflow(
                workflow_ir=repaired_ir,
                execution_params=execution_params,
                enable_repair=False,  # Don't repair the repair
                resume_state=result.shared_after,  # CRITICAL: Resume with checkpoint!
                original_request=original_request,
                output=output,
                workflow_manager=workflow_manager,
                workflow_name=workflow_name,
                stdin_data=stdin_data,
                output_key=output_key,
                metrics_collector=metrics_collector,
                trace_collector=trace_collector
            )

    return result
```

**Also Need**: `src/pflow/execution/null_output.py` for non-interactive execution

### Step 5: Update CLI Integration (20 min)
**File**: `src/pflow/cli/main.py`

**Changes**:
1. Add `--no-repair` flag to command definition (line ~2700)
2. Modify `execute_json_workflow()` to use unified execution (already uses ExecutorService)

**Exact Changes**:
```python
# 1. Add flag (around line 2700)
@click.option("--no-repair", is_flag=True, help="Disable automatic workflow repair on failure")

# 2. Update execute_json_workflow() to:
def execute_json_workflow(...):
    """Execute workflow using unified execution."""
    from pflow.execution.workflow_execution import execute_workflow
    from pflow.cli.cli_output import CliOutput

    # Create output interface (already exists from Phase 1)
    cli_output = CliOutput(
        output_controller=ctx.obj["output_controller"],
        verbose=ctx.obj.get("verbose", False),
        output_format=output_format
    )

    # Get repair preference
    enable_repair = not ctx.obj.get("no_repair", False)

    # Execute with unified function
    result = execute_workflow(
        workflow_ir=ir_data,
        execution_params=execution_params or {},
        enable_repair=enable_repair,
        original_request=ctx.obj.get("workflow_text"),  # From planner
        output=cli_output,
        workflow_manager=ctx.obj.get("workflow_manager"),
        workflow_name=ctx.obj.get("workflow_name"),
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=ctx.obj.get("workflow_trace")
    )

    # Use existing handlers for result processing
    if result.success:
        _handle_workflow_success(...)
    else:
        _handle_workflow_error(...)
```

### Step 6: Remove RuntimeValidationNode (15 min)
**File**: `src/pflow/planning/flow.py`

**Exact Line Changes**:
- Line 27: Remove `RuntimeValidationNode` from imports
- Line 57: Change "12 nodes" to "11 nodes" in debug message
- Line 70: Remove `runtime_validation: Node = RuntimeValidationNode()` line
- Line 89: Remove debug wrapper line for runtime_validation
- Line 159: Change `validator - "runtime_validation" >> runtime_validation` to `validator - "metadata_generation" >> metadata_generation`
- Line 173: Remove `runtime_validation >> metadata_generation`
- Line 177: Remove `runtime_validation - "runtime_fix" >> workflow_generator`
- Line 179: Remove `runtime_validation - "failed_runtime" >> result_preparation`
- Line 214: Update docstring from "12 nodes" to "11 nodes"

**File**: `src/pflow/planning/nodes.py`
- Lines 2882-3387: Delete entire RuntimeValidationNode class

### Step 7: Delete Test Files (5 min)
**Files to Delete**:
- `tests/test_runtime_validation.py`
- `tests/test_runtime_validation_simple.py`
- `tests/test_runtime/test_runtime_validation_core.py`
- `tests/test_planning/integration/test_runtime_validation_flow.py`

### Step 8: Run Tests and Fix Issues (30 min)
- Run `make test`
- Fix any test failures
- Verify checkpoint/resume works manually

## Testing Strategy

### Manual Testing Scenarios
1. **Basic Repair**: Break a workflow with template error, verify repair and resume
2. **No Side Effects**: Add logging to a node, verify it only executes once
3. **Disable Repair**: Use --no-repair flag, verify workflow just fails
4. **Complex Workflow**: Test with multi-node workflow, fail at different points

### Automated Testing
- Existing tests should pass (except deleted RuntimeValidation tests)
- Consider adding integration test for repair flow (if time permits)

## Risk Mitigation

### Potential Issues and Solutions

1. **Checkpoint Corruption**
   - Solution: Validate checkpoint structure before trusting
   - Fallback: If invalid, treat as fresh execution

2. **Infinite Repair Loop**
   - Solution: Only one repair attempt (enable_repair=False on recursive call)
   - No repair of repairs

3. **LLM Failure**
   - Solution: Catch exception in repair_workflow, return (False, None)
   - Workflow fails normally if repair fails

4. **Test Breakage**
   - Solution: Preserve all interfaces exactly
   - InstrumentedNodeWrapper changes are additive only

## Success Criteria

Implementation is complete when:
1. ✅ Workflow fails → repairs → resumes from checkpoint
2. ✅ "↻ cached" shown for skipped nodes
3. ✅ No duplicate execution (verified with logging)
4. ✅ --no-repair flag disables repair
5. ✅ Planner has 11 nodes (not 12)
6. ✅ All tests pass (except deleted RuntimeValidation tests)

## Verified Adjustments (Phase 2 Research)

After parallel verification of all critical assumptions:

1. **DisplayManager methods** - Use `show_repair_start()`, `show_repair_issue()`, `show_repair_result()` (already implemented in Phase 1)
2. **ExecutorService interface** - Confirmed accepts `shared_store` parameter, perfect for resume
3. **InstrumentedNodeWrapper order** - Confirmed always outermost at line 571
4. **RuntimeValidationNode location** - Confirmed at lines 2882-3387
5. **CLI already refactored** - `execute_json_workflow()` already uses ExecutorService
6. **JSON parsing** - Write own extraction logic like planner does (NOT using LLMNode)

## Order of Implementation

1. InstrumentedNodeWrapper - Foundation for checkpoint
2. OutputController - Visual feedback
3. RepairService - Core repair logic
4. Unified execution - Orchestration
5. CLI integration - User interface
6. RuntimeValidation removal - Cleanup
7. Test deletion - Final cleanup
8. Testing - Verification

This order ensures each component builds on the previous one with no forward dependencies.