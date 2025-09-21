# Phase 2: Repair Service Implementation (REVISED - NO AMBIGUITY)

## Overview
Remove RuntimeValidationNode from the planner flow and implement a separate repair service that uses Phase 1's WorkflowExecutorService to diagnose and fix broken workflows.

## Prerequisites
- Phase 1 completed: `WorkflowExecutorService` available and working
- Phase 1 completed: `WorkflowManager.update_metadata()` available
- Phase 1 completed: CLI uses `WorkflowExecutorService`

## Goals
1. Remove `RuntimeValidationNode` from planner flow
2. Create new `repair` module with repair flow
3. Implement repair nodes using `WorkflowExecutorService`
4. Add CLI integration for repair after execution failure
5. Update all affected tests

## Implementation Tasks

### 1. Remove RuntimeValidationNode from Planner

**EXACT Changes Required:**

#### File: `src/pflow/planning/flow.py`
Remove these exact lines:
- Line 27: `RuntimeValidationNode,` (from imports)
- Line 70: `runtime_validation: Node = RuntimeValidationNode()  # NEW: Runtime validation node`
- Line 89: `runtime_validation = DebugWrapper(runtime_validation, debug_context)  # type: ignore[assignment]`
- Line 173: `metadata_generation >> runtime_validation`
- Line 177: `runtime_validation >> parameter_preparation`
- Line 179: `runtime_validation - "runtime_fix" >> workflow_generator`
- Line 181: `runtime_validation - "failed_runtime" >> result_preparation`

Replace line 173 with:
```python
metadata_generation >> parameter_preparation
```

Update node counts:
- Line 57: Change `"Creating planner flow with 12 nodes"` to `"Creating planner flow with 11 nodes"`
- Line 209: Change `"12 nodes"` to `"11 nodes"`

#### File: `src/pflow/planning/nodes.py`
Remove the entire `RuntimeValidationNode` class (lines 2745-3201)

#### File: `src/pflow/core/__init__.py`
Keep `RuntimeValidationError` class but remove from exports if it's exported

#### Files to DELETE completely:
- `tests/test_runtime_validation.py`
- `tests/test_runtime_validation_simple.py`
- `tests/test_runtime/test_runtime_validation_core.py`
- `tests/test_planning/integration/test_runtime_validation_flow.py`
- `examples/runtime_feedback_demo.py`

#### Files to CHECK for minor updates:
- `tests/test_planning/integration/test_parameter_runtime_flow.py` - Remove comment on line 35
- `tests/test_planning/integration/test_planner_integration.py` - Check for RuntimeValidationNode references

### 2. Create Repair Module Structure
**New Directory**: `src/pflow/repair/`

```
src/pflow/repair/
├── __init__.py
├── repair_flow.py          # Main repair flow orchestration
├── nodes.py                # Repair-specific nodes
└── repair_service.py       # High-level repair API
```

### 3. Implement Repair Nodes

**⚠️ CRITICAL CLARIFICATION: Error Collection Behavior**

We do NOT implement multi-error collection (continuing execution after a node fails). However, we DO collect multiple types of errors from what DID execute:

1. **Execution stops at first node failure** (PocketFlow design)
2. **From partial execution, we can detect**:
   - The primary execution error (where it stopped)
   - Template mismatches in nodes that executed before failure
   - Missing fields in API responses that were returned
   - Type mismatches in data that was produced

**Example**: If node 1 returns `{login: "user"}` but node 2 expects `${node1.username}`, we detect:
- Primary error: Node 2 failed (template reference error)
- Additional info: `node1.username` doesn't exist, available fields: `login`

This gives the repair service rich context without implementing complex multi-node error collection.

**File**: `src/pflow/repair/nodes.py`

```python
import sys
from typing import Any, Optional
from pocketflow import Node
from pflow.core.workflow_executor_service import WorkflowExecutorService, ExecutionResult
from pflow.core.workflow_manager import WorkflowManager
from pflow.core.output_controller import OutputController  # Direct import, not from __init__
import logging

logger = logging.getLogger(__name__)

class ErrorCheckerNode(Node):
    """Check if workflow has existing errors or needs diagnosis."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "execution_errors": shared.get("execution_errors", []),
            "workflow_ir": shared.get("workflow_ir"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        return {"has_errors": bool(prep_res["execution_errors"])}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        if exec_res["has_errors"]:
            return "has_errors"  # Go to repair generator
        else:
            return "find_errors"  # Go to executor to find errors

class WorkflowExecutorNode(Node):
    """Execute workflow to find runtime errors (was RuntimeValidationNode).

    Collects both the primary error (where execution stopped) and additional
    context from partial execution (template mismatches, missing fields).
    """

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_ir": shared.get("workflow_ir"),
            "execution_params": shared.get("execution_params"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        # Create OutputController to show progress during repair
        # This reuses the existing node execution display format:
        # "Executing workflow (N nodes):" followed by node progress
        output_controller = OutputController(print_flag=True, output_format='text')

        # Use Phase 1's WorkflowExecutorService
        executor = WorkflowExecutorService(
            workflow_manager=None,  # Don't update metadata during repair
            output_controller=output_controller  # Shows progress during repair
        )

        result = executor.execute_workflow(
            workflow_ir=prep_res["workflow_ir"],
            execution_params=prep_res["execution_params"],
        )

        # ExecutionResult structure from Phase 1:
        # success: bool
        # errors: list[dict] - Primary execution error
        # shared_after: dict - Contains outputs from nodes that DID run
        # action_result: str | None

        errors = result.errors or []

        # ENHANCEMENT: Analyze partial execution for additional context
        # This is simpler than RuntimeValidationNode's full multi-error collection
        # but still provides valuable information about what went wrong
        if not result.success and result.shared_after:
            # Check for template mismatches in the partial execution
            additional_context = self._analyze_partial_execution(
                prep_res["workflow_ir"],
                result.shared_after
            )
            if additional_context:
                # Add as supplementary information to the primary error
                if errors:
                    errors[0]["additional_context"] = additional_context

        return {
            "success": result.success,
            "errors": errors,
            "shared_after": result.shared_after or {},
        }

    def _analyze_partial_execution(self, workflow_ir: dict, shared_after: dict) -> Optional[dict]:
        """Analyze partial execution results for additional error context.

        NOTE: This is a simplified version. A full implementation would:
        1. Check template references against actual data
        2. Identify missing fields in API responses
        3. Detect type mismatches

        For the MVP, this is a placeholder that can be enhanced later.
        Future enhancement could port logic from RuntimeValidationNode's
        _collect_missing_template_errors method.
        """
        # Placeholder - real implementation would analyze templates vs actual data
        return None

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        if exec_res["success"]:
            shared["repaired_workflow"] = prep_res["workflow_ir"]
            shared["repair_success"] = True
            return "success"
        else:
            # Store errors with any additional context from partial execution
            shared["execution_errors"] = exec_res["errors"]
            shared["repair_attempts"] = shared.get("repair_attempts", 0) + 1

            if shared["repair_attempts"] >= 3:
                logger.warning(f"Max repair attempts reached (3)")
                return "max_attempts"
            else:
                return "errors_found"

class RepairGeneratorNode(Node):
    """Generate fixed version of workflow based on errors.

    This is similar to WorkflowGeneratorNode but focuses on fixing specific errors
    rather than generating from scratch. Receives primary error plus any
    additional context from partial execution analysis.
    """

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_ir": shared.get("workflow_ir"),
            "execution_errors": shared.get("execution_errors", []),
            "original_request": shared.get("original_request", ""),
            "repair_attempts": shared.get("repair_attempts", 0),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement LLM-based repair logic
        # For now, return a placeholder
        logger.info(f"RepairGeneratorNode: Would fix {len(prep_res['execution_errors'])} error(s)")

        # This would use LLM to:
        # 1. Analyze the primary error (where execution stopped)
        # 2. Use additional_context if available (template mismatches, missing fields)
        # 3. Generate a corrected workflow that fixes the issues

        # Example error structure with additional context:
        # {
        #     "message": "Template ${node1.username} not found",
        #     "node_id": "node2",
        #     "additional_context": {
        #         "missing_paths": ["node1.username"],
        #         "available_fields": ["node1.login", "node1.bio"]
        #     }
        # }

        # For MVP, just return the original workflow
        # Real implementation would call LLM here
        return {
            "repaired_workflow": prep_res["workflow_ir"]  # Placeholder
        }

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        shared["workflow_ir"] = exec_res["repaired_workflow"]
        # Clear errors since we've attempted a fix
        shared["execution_errors"] = []
        return "default"  # Continue to validator

# Import and use ValidatorNode from planner with key mapping
class RepairValidatorNode(Node):
    """Wrapper around ValidatorNode for repair flow compatibility."""

    def __init__(self):
        super().__init__()
        from pflow.planning.nodes import ValidatorNode
        self.validator = ValidatorNode()

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        # Map repair keys to validator expectations
        shared["generated_workflow"] = shared.get("workflow_ir")
        shared["generation_attempts"] = shared.get("repair_attempts", 0)
        # Pass through to validator
        return self.validator.prep(shared)

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        return self.validator.exec(prep_res)

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        # ValidatorNode returns: "metadata_generation", "retry", or "failed"
        # Map to repair flow actions
        validator_action = self.validator.post(shared, prep_res, exec_res)

        if validator_action == "metadata_generation":
            # Validation passed
            return "valid"
        elif validator_action == "retry":
            # Validation failed but can retry
            return "retry"
        else:  # "failed"
            # Max attempts reached
            return "failed"
```

### 4. Create Repair Flow
**File**: `src/pflow/repair/repair_flow.py`

```python
from pocketflow import Flow
from .nodes import (
    ErrorCheckerNode,
    WorkflowExecutorNode,
    RepairGeneratorNode,
    RepairValidatorNode
)

def create_repair_flow() -> Flow:
    """Create flow for repairing broken workflows."""

    # Create nodes
    error_checker = ErrorCheckerNode()
    executor = WorkflowExecutorNode()
    generator = RepairGeneratorNode()
    validator = RepairValidatorNode()  # Wrapper around ValidatorNode

    # Wire the flow
    flow = Flow(start=error_checker)

    # Initial routing
    error_checker - "has_errors" >> generator
    error_checker - "find_errors" >> executor

    # Executor routing
    executor - "success" >> Flow.end()
    executor - "errors_found" >> generator
    executor - "max_attempts" >> Flow.end()

    # Generator always goes to validator
    generator >> validator

    # Validator routing
    validator - "valid" >> executor  # Try executing the fix
    validator - "retry" >> generator  # Fix validation errors
    validator - "failed" >> Flow.end()  # Too many attempts

    return flow
```

### 5. Create Repair Service API
**File**: `src/pflow/repair/repair_service.py`

```python
from typing import Optional, Tuple
from pflow.core.workflow_manager import WorkflowManager
from .repair_flow import create_repair_flow

def repair_workflow(
    workflow_ir: dict,
    execution_params: dict,
    execution_errors: Optional[list[dict]] = None,
    original_request: Optional[str] = None,
    workflow_name: Optional[str] = None
) -> Tuple[bool, dict]:
    """
    Attempt to repair a broken workflow.

    Args:
        workflow_ir: The workflow IR to repair
        execution_params: Parameters for workflow execution
        execution_errors: List of error dicts with structure:
            {
                "source": str,  # "runtime", "node", "template", etc.
                "category": str,  # "exception", "missing_template_path", etc.
                "message": str,
                "fixable": bool,
                "node_id": Optional[str],
                "attempted": Optional[str | list],
                "available": Optional[list[str]]
            }
        original_request: Original user request text
        workflow_name: Name of workflow (for metadata updates)

    Returns:
        (success, repaired_workflow_ir)
    """
    shared = {
        "workflow_ir": workflow_ir,
        "execution_params": execution_params,
        "execution_errors": execution_errors or [],
        "original_request": original_request,
        "workflow_manager": WorkflowManager(),
        "repair_attempts": 0,
    }

    flow = create_repair_flow()
    flow.run(shared)

    success = shared.get("repair_success", False)
    repaired_workflow = shared.get("repaired_workflow", workflow_ir)

    return success, repaired_workflow
```

### 6. CLI Integration

**File**: `src/pflow/cli/main.py`

**ADD CLI flag** to main command (optional):
```python
@click.option('--no-repair', is_flag=True, help='Disable automatic repair on failure')
def main(..., no_repair: bool):
    # Store in context for later use
    ctx.obj['auto_repair'] = not no_repair
```

**ADD after line 1381** (after error display, before trace save):

```python
def _handle_workflow_exception(
    ctx: click.Context,
    e: Exception,
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
) -> None:
    # ... existing error handling code ...

    # Line 1381: Error has been displayed
    else:
        # Format error based on type
        if isinstance(e, UserFriendlyError):
            error_message = e.format_for_cli(verbose=verbose)
            click.echo(error_message, err=True)
        else:
            click.echo(f"cli: Workflow execution failed - {e}", err=True)
            click.echo("cli: This may indicate a bug in the workflow or nodes", err=True)

    # NEW CODE STARTS HERE (after line 1381)
    # Auto-repair by default (unless --no-repair flag is set or JSON output mode)
    if output_format != "json" and ctx.obj.get("workflow_ir") and ctx.obj.get("execution_params"):
        # Build error structure for repair service
        error_info = {
            "source": "runtime",
            "category": "exception",
            "message": str(e),
            "fixable": True  # Assume fixable for now
        }

        # Check if auto-repair is disabled (could be set via --no-repair flag)
        auto_repair = ctx.obj.get("auto_repair", True)  # Default to True

        if auto_repair:
            # Automatically attempt repair without prompting
            click.echo("\n🔧 Auto-repairing workflow...", err=True)
            _attempt_repair(
                ctx,
                ctx.obj["workflow_ir"],
                ctx.obj["execution_params"],
                [error_info],
                ctx.obj.get("original_request")
            )
            # If repair succeeds, it will execute and exit
            # If it fails, continue to normal error exit
        else:
            # Manual mode: offer choices
            try:
                repair_choice = click.prompt(
                    "\nWorkflow failed. What would you like to do?\n"
                    "1. Try to repair automatically\n"
                    "2. Save anyway\n"
                    "3. Abort",
                    type=click.Choice(["1", "2", "3"]),
                    default="1"  # Default to repair
                )

                if repair_choice == "1":
                    _attempt_repair(
                        ctx,
                        ctx.obj["workflow_ir"],
                        ctx.obj["execution_params"],
                        [error_info],
                        ctx.obj.get("original_request")
                    )
                elif repair_choice == "2":
                    # Save workflow despite errors
                    workflow_name = ctx.obj.get("workflow_name")
                    if workflow_name:
                        workflow_manager = WorkflowManager()
                        workflow_manager.update_metadata(
                            workflow_name,
                            {"last_execution_errors": [error_info]}
                        )
                        click.echo(f"Workflow saved with errors: {workflow_name}")
            except (KeyboardInterrupt, EOFError):
                # User cancelled prompt
                pass
    # NEW CODE ENDS HERE

    # Existing trace saving code continues (line 1383+)
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")

    ctx.exit(1)

def _attempt_repair(
    ctx: click.Context,
    workflow_ir: dict,
    execution_params: dict,
    errors: list[dict],
    original_request: Optional[str]
) -> None:
    """Attempt to repair workflow using repair service."""
    # Show the specific error we're fixing
    if errors and errors[0].get("message"):
        click.echo(f"  • Issue detected: {errors[0]['message']}", err=True)
    click.echo("  • Analyzing workflow structure...", err=True)

    try:
        from pflow.repair import repair_workflow

        # The repair service will show progress via OutputController
        # Users will see node execution progress during validation
        success, repaired_workflow = repair_workflow(
            workflow_ir=workflow_ir,
            execution_params=execution_params,
            execution_errors=errors,
            original_request=original_request
        )

        if success:
            click.echo("  ✅ Workflow repaired successfully!", err=True)
            # Update context with repaired workflow
            ctx.obj["workflow_ir"] = repaired_workflow
            # Re-execute using existing machinery
            from pflow.cli.main import execute_json_workflow
            execute_json_workflow(
                ctx,
                repaired_workflow,
                ctx.obj.get("stdin_data"),
                ctx.obj.get("output_key"),
                execution_params,
                ctx.obj.get("planner_llm_calls"),
                ctx.obj.get("output_format", "text"),
                ctx.obj.get("metrics_collector")
            )
            # Exit successfully if execution works
            ctx.exit(0)
        else:
            click.echo("❌ Could not repair automatically", err=True)
            # Continue to normal error exit

    except ImportError:
        # Repair module not available
        click.echo("Repair service not available", err=True)
    except Exception as repair_error:
        click.echo(f"Repair failed: {repair_error}", err=True)
        # Continue to normal error exit
```

**File**: `src/pflow/repair/__init__.py`

```python
"""Repair service for fixing broken workflows."""

from .repair_service import repair_workflow

__all__ = ["repair_workflow"]
```

## User Experience During Repair

When a workflow fails and auto-repair kicks in, users will see output similar to the current format:

```
Executing workflow (6 nodes):
  fetch_messages... ✓ 1.8s
  analyze_questions... ✓ 0.9s
  send_answers... ✓ 1.9s
  get_timestamp... ✗ Command failed

❌ Workflow execution failed

🔧 Auto-repairing workflow...
  • Issue detected: Template ${get_time.stdout} not found
  • Analyzing workflow structure...
Executing workflow (4 nodes):
  fetch_messages... ✓ 0.1s (cached)
  analyze_questions... ✓ 0.1s (cached)
  send_answers... ✓ 0.1s (cached)
  get_timestamp... ✗ Validation stopped
  ✅ Workflow repaired successfully!

Executing workflow (6 nodes):
  fetch_messages... ✓ 0.1s (cached)
  analyze_questions... ✓ 0.1s (cached)
  send_answers... ✓ 0.1s (cached)
  get_timestamp... ✓ 0.0s
  format_sheet_data... ✓ 0.6s
  update_sheets... ✓ 3.4s
```

The repair process reuses the existing progress display format that users are already familiar with. During repair validation, nodes that were already executed may show as cached/faster since their results can be reused.

## Success Criteria

1. **Planner works without RuntimeValidationNode**: Workflows generate and execute normally
2. **No duplicate execution**: Success path runs workflow only once
3. **Auto-repair by default**: Failed workflows automatically attempt repair without prompting
4. **Progress visible during repair**: OutputController shows execution progress during repair validation
5. **All tests updated and passing**: No test failures from removed RuntimeValidationNode
6. **Simple implementation**: No multi-error collection complexity (deferred to future enhancement)
7. **Self-healing workflows**: Workflows can adapt to environment changes without re-planning

## Testing Plan

### Files that MUST have tests removed/updated:
1. Delete: `tests/test_runtime_validation.py`
2. Delete: `tests/test_runtime_validation_simple.py`
3. Delete: `tests/test_runtime/test_runtime_validation_core.py`
4. Delete: `tests/test_planning/integration/test_runtime_validation_flow.py`
5. Update: Flow structure tests to expect 11 nodes instead of 12

### New test files to create:
1. `tests/test_repair/test_repair_nodes.py` - Unit tests for repair nodes
2. `tests/test_repair/test_repair_flow.py` - Test repair flow
3. `tests/test_repair/test_repair_service.py` - Test repair API

## IMPORTANT NOTES

1. **OutputController provides user-friendly output** - Shows progress during repair execution
2. **ValidatorNode needs key mapping** - Use RepairValidatorNode wrapper
3. **Single error per execution** - PocketFlow stops on first error (no multi-error collection in MVP)
4. **RepairGeneratorNode needs LLM implementation** - Placeholder provided
5. **CLI needs to store workflow_ir and execution_params in ctx.obj** - For repair access
6. **Future enhancement**: Multi-error collection could be added by porting RuntimeValidationNode's
   custom node-by-node execution logic to WorkflowExecutorNode, but this is intentionally
   deferred to keep the initial implementation simple and focused

## Deliverables

1. Planner without RuntimeValidationNode (working)
2. Complete repair module implementation
3. CLI integration with repair prompt
4. All tests passing (with 4 test files deleted)
5. Documentation of repair service API

---

This specification is now completely unambiguous with exact line numbers, file paths, and implementation details based on verified codebase analysis.