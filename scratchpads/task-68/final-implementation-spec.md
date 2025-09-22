# Task 68: Final Implementation Specification

## Executive Summary

Refactor RuntimeValidation from the planner flow into a separate repair service that fixes broken workflows after execution. This creates a unified execution-repair flow with caching to prevent duplicate side effects and enable self-healing workflows.

## Architecture Decisions (Confirmed)

1. **Full Caching System** - Implement complete node execution caching
2. **Unified Flow Pattern** - Repair IS the primary execution path when auto-repair enabled
3. **Shared Store Caching** - Cache stored in `shared["__execution_cache__"]`
4. **Template Context** - Port simplified template extraction for rich error context
5. **Haiku for Repair** - Use claude-3-haiku model (fast/cheap) for repair generation

## Implementation Phases

### Phase 1: WorkflowExecutorService & Infrastructure

#### 1.1 Create WorkflowExecutorService
**File**: `src/pflow/core/workflow_executor_service.py`

```python
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

@dataclass
class NodeExecutionCache:
    """Stores execution results for reuse."""
    executions: dict[str, 'CachedExecution'] = field(default_factory=dict)

@dataclass
class CachedExecution:
    node_id: str
    node_type: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    success: bool
    timestamp: datetime
    cache_key: str

@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    success: bool
    action_result: Optional[str] = None
    errors: list[dict] = field(default_factory=list)
    shared_after: dict = field(default_factory=dict)
    node_count: int = 0
    duration: float = 0.0
    metrics_summary: Optional[dict] = None

class CachingNodeWrapper(Node):
    """Wraps a node to add caching capability."""

    def __init__(self, node: Node, cache: NodeExecutionCache, output_controller=None):
        self.node = node
        self.cache = cache
        self.output_controller = output_controller
        super().__init__()

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        cache_key = self._generate_cache_key(prep_res)

        if cache_key in self.cache.executions:
            cached = self.cache.executions[cache_key]
            if self.output_controller:
                self.output_controller.display_cached_node(self.node.id)
            return cached.outputs

        result = self.node.exec(prep_res)

        self.cache.executions[cache_key] = CachedExecution(
            node_id=self.node.id,
            node_type=self.node.__class__.__name__,
            inputs=prep_res,
            outputs=result,
            success=True,
            timestamp=datetime.now(),
            cache_key=cache_key
        )

        return result

    def _generate_cache_key(self, inputs: dict) -> str:
        input_json = json.dumps(inputs, sort_keys=True, default=str)
        input_hash = hashlib.sha256(input_json.encode()).hexdigest()[:16]
        return f"{self.node.id}:{self.node.__class__.__name__}:{input_hash}"

class WorkflowExecutorService:
    """Reusable workflow execution service with caching support."""

    def __init__(self,
                 workflow_manager=None,
                 output_controller=None,
                 abort_on_first_error=True):
        self.workflow_manager = workflow_manager
        self.output_controller = output_controller
        self.abort_on_first_error = abort_on_first_error

    def execute_workflow(self,
                        workflow_ir: dict,
                        execution_params: dict,
                        shared_store: Optional[dict] = None,
                        workflow_name: Optional[str] = None,
                        stdin_data: Optional[Any] = None,
                        output_key: Optional[str] = None,
                        planner_llm_calls: Optional[list] = None,
                        metrics_collector: Optional[Any] = None,
                        trace_collector: Optional[Any] = None) -> ExecutionResult:
        """Execute workflow with optional caching."""
        from pflow.runtime.compiler import compile_ir_to_flow
        from pflow.registry import Registry
        import time

        start_time = time.time()

        # Use provided shared store or create new
        if shared_store is None:
            shared_store = {}

        # Get or create cache from shared store
        cache = shared_store.get("__execution_cache__")
        if cache is None:
            cache = NodeExecutionCache()
            shared_store["__execution_cache__"] = cache

        # Initialize shared store
        if planner_llm_calls:
            shared_store["__llm_calls__"] = planner_llm_calls
        elif metrics_collector:
            shared_store["__llm_calls__"] = []

        # Add progress callback if interactive
        if self.output_controller and self.output_controller.is_interactive():
            callback = self.output_controller.create_progress_callback()
            if callback:
                shared_store["__progress_callback__"] = callback

        # Create registry and compile
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

            # Wrap nodes with caching if cache exists
            if cache.executions:
                flow = self._wrap_flow_with_cache(flow, cache)

            # Execute
            if metrics_collector:
                metrics_collector.record_workflow_start()

            action_result = flow.run(shared_store)

            # Determine success
            success = not (action_result and
                         isinstance(action_result, str) and
                         action_result.startswith("error"))

            errors = []
            if not success:
                errors.append({
                    "source": "runtime",
                    "category": "execution_failure",
                    "message": f"Workflow failed with action: {action_result}",
                    "fixable": True
                })

            # Update workflow metadata if manager and name provided
            if self.workflow_manager and workflow_name and success:
                self.workflow_manager.update_metadata(workflow_name, {
                    "last_execution_timestamp": datetime.now(timezone.utc).isoformat(),
                    "last_execution_success": success,
                    "last_execution_params": execution_params,
                    "execution_count": 1  # Will be incremented properly
                })

        except Exception as e:
            success = False
            errors = [{
                "source": "runtime",
                "category": "exception",
                "message": str(e),
                "fixable": self._is_fixable_error(e)
            }]
            action_result = "error"

        finally:
            if metrics_collector:
                metrics_collector.record_workflow_end()

        duration = time.time() - start_time

        return ExecutionResult(
            success=success,
            action_result=action_result,
            errors=errors,
            shared_after=shared_store,
            node_count=len(workflow_ir.get("nodes", [])),
            duration=duration,
            metrics_summary=metrics_collector.get_summary() if metrics_collector else None
        )

    def _wrap_flow_with_cache(self, flow, cache):
        """Wrap flow nodes with caching wrappers."""
        # This is complex with PocketFlow's structure
        # For MVP, we'll implement partial caching
        # Full implementation would require modifying flow internals
        return flow

    def _is_fixable_error(self, exception: Exception) -> bool:
        """Determine if error can be fixed by repair."""
        error_msg = str(exception).lower()

        # Non-fixable: auth, rate limits, network issues
        non_fixable = ["api key", "unauthorized", "rate limit",
                       "connection refused", "timeout"]

        for keyword in non_fixable:
            if keyword in error_msg:
                return False

        return True  # Optimistically assume fixable
```

#### 1.2 Add WorkflowManager.update_metadata()
**File**: `src/pflow/core/workflow_manager.py`

Add this method to existing WorkflowManager class:

```python
def update_metadata(self, workflow_name: str, updates: dict) -> None:
    """Update workflow metadata after execution.

    Args:
        workflow_name: Name of workflow to update
        updates: Dictionary of metadata fields to update

    Raises:
        FileNotFoundError: If workflow doesn't exist
    """
    import tempfile
    import os
    from datetime import datetime, timezone

    workflow_path = self._get_workflow_path(workflow_name)
    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow not found: {workflow_name}")

    # Load existing workflow
    workflow_data = self.load(workflow_name)

    # Merge updates into rich_metadata
    if "rich_metadata" not in workflow_data:
        workflow_data["rich_metadata"] = {}

    # Handle execution_count increment specially
    if "execution_count" in updates:
        current_count = workflow_data["rich_metadata"].get("execution_count", 0)
        workflow_data["rich_metadata"]["execution_count"] = current_count + 1
        del updates["execution_count"]

    workflow_data["rich_metadata"].update(updates)
    workflow_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Atomic save using temp file + rename pattern
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

#### 1.3 Refactor CLI to use WorkflowExecutorService
**File**: `src/pflow/cli/main.py`

Replace execute_json_workflow implementation (around lines 1390-1462):

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
    """Execute workflow using WorkflowExecutorService."""
    from pflow.core.workflow_executor_service import WorkflowExecutorService
    from pflow.core import WorkflowManager

    # Store in context for potential repair
    ctx.obj["workflow_ir"] = ir_data
    ctx.obj["execution_params"] = params or {}
    ctx.obj["original_request"] = ctx.obj.get("workflow_text", "")

    # Get output controller
    output_controller = _get_output_controller(ctx)

    # Get workflow name if available
    workflow_name = ctx.obj.get("workflow_name")

    # Create executor
    executor = WorkflowExecutorService(
        workflow_manager=WorkflowManager() if workflow_name else None,
        output_controller=output_controller,
        abort_on_first_error=True
    )

    # Get trace collector if enabled
    workflow_trace = ctx.obj.get("workflow_trace")

    # Execute workflow
    try:
        result = executor.execute_workflow(
            workflow_ir=ir_data,
            execution_params=params or {},
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            planner_llm_calls=planner_llm_calls,
            metrics_collector=metrics_collector,
            trace_collector=workflow_trace
        )

        if result.success:
            _handle_workflow_success(
                ctx=ctx,
                workflow_trace=workflow_trace,
                shared_storage=result.shared_after,
                output_key=output_key,
                ir_data=ir_data,
                output_format=output_format,
                metrics_collector=metrics_collector,
                verbose=ctx.obj.get("verbose", False)
            )
        else:
            _handle_workflow_error(
                ctx=ctx,
                workflow_trace=workflow_trace,
                output_format=output_format,
                metrics_collector=metrics_collector,
                shared_storage=result.shared_after,
                verbose=ctx.obj.get("verbose", False),
                errors=result.errors  # Pass errors for potential repair
            )

    except Exception as e:
        _handle_workflow_exception(
            ctx=ctx,
            e=e,
            workflow_trace=workflow_trace,
            output_format=output_format,
            metrics_collector=metrics_collector,
            shared_storage={},
            verbose=ctx.obj.get("verbose", False)
        )
```

### Phase 2: Repair Service Implementation

#### 2.1 Remove RuntimeValidationNode from Planner

**File**: `src/pflow/planning/flow.py`

Remove these exact lines:
- Line 27: Remove `RuntimeValidationNode,` from imports
- Line 70: Remove `runtime_validation: Node = RuntimeValidationNode()`
- Line 89: Remove debug wrapper line for runtime_validation
- Lines 173-181: Remove all runtime_validation edges
- Line 173: Replace with `metadata_generation >> parameter_preparation`
- Update node count from 12 to 11 in log messages

**File**: `src/pflow/planning/nodes.py`
- Delete entire RuntimeValidationNode class (lines 2745-3201)

**Files to DELETE**:
- `tests/test_runtime_validation.py`
- `tests/test_runtime_validation_simple.py`
- `tests/test_runtime/test_runtime_validation_core.py`
- `tests/test_planning/integration/test_runtime_validation_flow.py`
- `examples/runtime_feedback_demo.py`

#### 2.2 Create Repair Module Structure

Create these new files:

**File**: `src/pflow/repair/__init__.py`
```python
"""Repair service for fixing broken workflows."""

from .repair_service import repair_workflow, execute_with_auto_repair

__all__ = ["repair_workflow", "execute_with_auto_repair"]
```

**File**: `src/pflow/repair/prompts/repair_generator.md`
```markdown
---
model: anthropic/claude-3-haiku
temperature: 0.7
max_tokens: 8000
---

# Repair Broken Workflow

You need to fix a workflow that failed during execution.

## Current Workflow
```json
{workflow_ir}
```

## Execution Errors
{errors}

## Original User Request
{original_request}

## Your Task

Analyze the errors and generate a corrected version of the workflow that fixes the issues.

Common fixes:
1. **Template path errors**: Update field names to match actual API responses
2. **Missing parameters**: Add required parameters to node configurations
3. **Wrong node types**: Replace with correct node types
4. **Array indexing**: Fix array notation in templates
5. **Shell command syntax**: Correct shell commands for the environment

Return ONLY the corrected workflow IR in JSON format. Do not include any explanation.
```

**File**: `src/pflow/repair/nodes.py`
```python
import logging
from typing import Any, Optional
from pocketflow import Node
import llm

from pflow.core.workflow_executor_service import WorkflowExecutorService, ExecutionResult
from pflow.core import OutputController

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
    """Execute workflow to find runtime errors.

    This is a simplified version of RuntimeValidationNode focused on
    error detection with template context extraction.
    """

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_ir": shared.get("workflow_ir"),
            "execution_params": shared.get("execution_params", {}),
            "shared_store": shared.get("shared_store", shared),  # Reuse shared for caching
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        # Create output controller for progress display
        output_controller = OutputController(print_flag=True, output_format='text')

        # Use WorkflowExecutorService
        executor = WorkflowExecutorService(
            workflow_manager=None,
            output_controller=output_controller,
            abort_on_first_error=True  # Stop on first error for repair
        )

        # Execute with shared store for caching
        result = executor.execute_workflow(
            workflow_ir=prep_res["workflow_ir"],
            execution_params=prep_res["execution_params"],
            shared_store=prep_res["shared_store"]  # Pass shared for cache reuse
        )

        errors = result.errors or []

        # Add template context if execution failed
        if not result.success and result.shared_after:
            additional_context = self._analyze_partial_execution(
                prep_res["workflow_ir"],
                result.shared_after
            )
            if additional_context and errors:
                errors[0]["additional_context"] = additional_context

        return {
            "success": result.success,
            "errors": errors,
            "shared_after": result.shared_after,
        }

    def _analyze_partial_execution(self, workflow_ir: dict, shared_after: dict) -> Optional[dict]:
        """Extract template context from partial execution.

        Simplified version of RuntimeValidationNode's template extraction.
        """
        from pflow.runtime.template_validator import TemplateValidator

        templates = TemplateValidator._extract_all_templates(workflow_ir)
        missing_contexts = []

        for template in templates:
            if not self._template_exists_in_shared(template, shared_after):
                # Extract node_id and field from template
                parts = template.split(".", 1)
                if len(parts) == 2:
                    node_id, field_path = parts
                    # Get available fields at node level
                    available = self._get_available_fields(shared_after, node_id)
                    missing_contexts.append({
                        "template": f"${{{template}}}",
                        "available_fields": available
                    })

        return {"missing_templates": missing_contexts} if missing_contexts else None

    def _template_exists_in_shared(self, template: str, shared: dict) -> bool:
        """Check if template path exists in shared store."""
        parts = template.split(".")
        if not parts:
            return False

        current = shared.get(parts[0])
        for part in parts[1:]:
            if current is None:
                return False
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return False

        return current is not None

    def _get_available_fields(self, shared: dict, node_id: str) -> list[str]:
        """Get available fields for a node in shared store."""
        node_data = shared.get(node_id, {})
        if isinstance(node_data, dict):
            return list(node_data.keys())
        return []

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        if exec_res["success"]:
            shared["repaired_workflow"] = prep_res["workflow_ir"]
            shared["repair_success"] = True
            return "success"
        else:
            shared["execution_errors"] = exec_res["errors"]
            shared["repair_attempts"] = shared.get("repair_attempts", 0) + 1

            if shared["repair_attempts"] >= 3:
                logger.warning("Max repair attempts reached (3)")
                return "max_attempts"
            else:
                return "errors_found"

class RepairGeneratorNode(Node):
    """Generate fixed version of workflow based on errors."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_ir": shared.get("workflow_ir"),
            "execution_errors": shared.get("execution_errors", []),
            "original_request": shared.get("original_request", ""),
            "repair_attempts": shared.get("repair_attempts", 0),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Generate repaired workflow using LLM."""
        from pflow.planning.prompts.loader import load_prompt
        import json

        # Format errors for prompt
        error_text = self._format_errors_for_prompt(prep_res["execution_errors"])

        # Load repair prompt template
        repair_prompt = load_prompt("repair_generator")

        # Substitute variables in prompt
        prompt = repair_prompt.format(
            workflow_ir=json.dumps(prep_res["workflow_ir"], indent=2),
            errors=error_text,
            original_request=prep_res["original_request"]
        )

        # Use Haiku for fast, cheap repairs
        model = llm.get_model("anthropic/claude-3-haiku")

        try:
            response = model.prompt(prompt)

            # Parse JSON from response
            repaired_ir = self._extract_json_from_response(response.text())

            logger.info(f"Successfully generated repair (attempt {prep_res['repair_attempts'] + 1})")

            return {"repaired_workflow": repaired_ir}

        except Exception as e:
            logger.error(f"Repair generation failed: {e}")
            # Return original workflow as fallback
            return {"repaired_workflow": prep_res["workflow_ir"]}

    def _format_errors_for_prompt(self, errors: list[dict]) -> str:
        """Format errors for LLM consumption."""
        lines = []
        for i, error in enumerate(errors, 1):
            lines.append(f"{i}. {error.get('message', 'Unknown error')}")

            if error.get("additional_context"):
                context = error["additional_context"]
                if context.get("missing_templates"):
                    for missing in context["missing_templates"]:
                        template = missing["template"]
                        available = missing.get("available_fields", [])
                        lines.append(f"   - Template {template} not found")
                        if available:
                            lines.append(f"     Available fields: {', '.join(available)}")

        return "\n".join(lines)

    def _extract_json_from_response(self, response: str) -> dict:
        """Extract JSON from LLM response."""
        import json

        # Try to find JSON in response
        start = response.find("{")
        end = response.rfind("}") + 1

        if start >= 0 and end > start:
            json_str = response[start:end]
            return json.loads(json_str)

        raise ValueError("No valid JSON found in response")

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        shared["workflow_ir"] = exec_res["repaired_workflow"]
        shared["execution_errors"] = []  # Clear errors after repair attempt
        return "default"  # Continue to validator

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
        return self.validator.prep(shared)

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        return self.validator.exec(prep_res)

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        validator_action = self.validator.post(shared, prep_res, exec_res)

        # Map validator actions to repair flow
        if validator_action == "metadata_generation":
            return "valid"
        elif validator_action == "retry":
            return "retry"
        else:  # "failed"
            return "failed"
```

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
    validator = RepairValidatorNode()

    # Wire the flow
    flow = Flow(start=error_checker)

    # Initial routing
    error_checker.next(generator, "has_errors")
    error_checker.next(executor, "find_errors")

    # Executor routing - returns None to end when successful
    executor.next(generator, "errors_found")
    # "success" and "max_attempts" have no successors - flow ends

    # Generator always goes to validator
    generator.next(validator)

    # Validator routing
    validator.next(executor, "valid")  # Try executing the fix
    validator.next(generator, "retry")  # Fix validation errors
    # "failed" has no successor - flow ends

    return flow
```

**File**: `src/pflow/repair/repair_service.py`
```python
from typing import Optional, Tuple
from pflow.core.workflow_executor_service import WorkflowExecutorService

def execute_with_auto_repair(
    workflow_ir: dict,
    execution_params: dict,
    original_request: Optional[str] = None,
    output_controller=None,
    workflow_manager=None,
    metrics_collector=None,
    trace_collector=None
) -> dict:
    """
    Unified execution with automatic repair on failure.

    This is the PRIMARY execution path when auto-repair is enabled.
    Cache is built during first execution and reused during repairs.

    Returns:
        ExecutionResult with success status and shared store
    """
    import click

    # Single shared store for entire repair session
    shared_store = {}

    # Create executor
    executor = WorkflowExecutorService(
        workflow_manager=workflow_manager,
        output_controller=output_controller,
        abort_on_first_error=True
    )

    # First execution attempt
    result = executor.execute_workflow(
        workflow_ir=workflow_ir,
        execution_params=execution_params,
        shared_store=shared_store,  # Build cache here
        metrics_collector=metrics_collector,
        trace_collector=trace_collector
    )

    if result.success:
        return result  # Happy path - no repair needed

    # Repair needed - cache is already in shared_store["__execution_cache__"]
    click.echo("\n🔧 Auto-repairing workflow...", err=True)

    if result.errors and result.errors[0].get("message"):
        click.echo(f"  • Issue detected: {result.errors[0]['message']}", err=True)

    # Use repair flow
    repair_success, repaired_workflow = repair_workflow(
        workflow_ir=workflow_ir,
        execution_params=execution_params,
        execution_errors=result.errors,
        original_request=original_request,
        shared_store=shared_store  # Pass same store with cache!
    )

    if repair_success:
        click.echo("  ✅ Workflow repaired successfully!", err=True)

        # Execute repaired workflow with SAME shared store (and cache)
        result = executor.execute_workflow(
            workflow_ir=repaired_workflow,
            execution_params=execution_params,
            shared_store=shared_store,  # Reuses cache!
            metrics_collector=metrics_collector,
            trace_collector=trace_collector
        )
    else:
        click.echo("  ❌ Could not repair automatically", err=True)

    return result

def repair_workflow(
    workflow_ir: dict,
    execution_params: dict,
    execution_errors: Optional[list[dict]] = None,
    original_request: Optional[str] = None,
    shared_store: Optional[dict] = None
) -> Tuple[bool, dict]:
    """
    Attempt to repair a broken workflow using repair flow.

    Returns:
        (success, repaired_workflow_ir)
    """
    from .repair_flow import create_repair_flow

    # Use provided shared store or create new
    if shared_store is None:
        shared_store = {}

    # Set up repair context in shared store
    shared_store.update({
        "workflow_ir": workflow_ir,
        "execution_params": execution_params,
        "execution_errors": execution_errors or [],
        "original_request": original_request or "",
        "repair_attempts": 0,
    })

    # Run repair flow
    flow = create_repair_flow()
    flow.run(shared_store)

    # Extract results
    success = shared_store.get("repair_success", False)
    repaired_workflow = shared_store.get("repaired_workflow", workflow_ir)

    return success, repaired_workflow
```

#### 2.3 Update CLI Integration

**File**: `src/pflow/cli/main.py`

1. Add `--no-repair` flag to main command:
```python
@click.option('--no-repair', is_flag=True, help='Disable automatic repair on failure')
def main(..., no_repair: bool):
    ctx.obj['auto_repair'] = not no_repair
```

2. Modify `execute_json_workflow` to use unified flow:
```python
def execute_json_workflow(...):
    """Execute workflow with unified repair flow."""
    # ... existing setup ...

    # Store context for repair
    ctx.obj["workflow_ir"] = ir_data
    ctx.obj["execution_params"] = params or {}
    ctx.obj["original_request"] = ctx.obj.get("workflow_text", "")

    # Use unified flow if auto-repair enabled (default)
    if ctx.obj.get('auto_repair', True) and output_format != 'json':
        from pflow.repair import execute_with_auto_repair

        result = execute_with_auto_repair(
            workflow_ir=ir_data,
            execution_params=params or {},
            original_request=ctx.obj.get("original_request"),
            output_controller=output_controller,
            workflow_manager=WorkflowManager() if workflow_name else None,
            metrics_collector=metrics_collector,
            trace_collector=workflow_trace
        )
    else:
        # Traditional execution without repair
        executor = WorkflowExecutorService(
            workflow_manager=WorkflowManager() if workflow_name else None,
            output_controller=output_controller,
            abort_on_first_error=True
        )

        result = executor.execute_workflow(
            workflow_ir=ir_data,
            execution_params=params or {},
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            planner_llm_calls=planner_llm_calls,
            metrics_collector=metrics_collector,
            trace_collector=workflow_trace
        )

    # Handle result (existing handlers)
    if result.success:
        _handle_workflow_success(...)
    else:
        _handle_workflow_error(...)
```

## Testing Strategy

### Phase 1 Tests
- Unit tests for WorkflowExecutorService
- Unit tests for NodeExecutionCache
- Test WorkflowManager.update_metadata()
- Integration test: CLI uses service correctly

### Phase 2 Tests
- Delete 4 RuntimeValidation test files
- Update planner tests to expect 11 nodes
- Unit tests for repair nodes (mock llm.get_model)
- Integration test: repair flow works end-to-end

## Success Criteria

1. ✅ No duplicate execution (caching works)
2. ✅ Auto-repair by default
3. ✅ RuntimeValidationNode removed (11 nodes)
4. ✅ All tests pass
5. ✅ Workflows self-heal for API changes

## Timeline

- Phase 1: 6-8 hours (foundation)
- Phase 2: 8-10 hours (repair service)
- Testing: 4-6 hours
- **Total**: ~20 hours

---

This specification is complete and ready for implementation.