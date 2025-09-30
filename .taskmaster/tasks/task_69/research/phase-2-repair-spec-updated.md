# Phase 2: Repair Flow Implementation Specification (Updated)
## PocketFlow-Based Repair System with Checkpoint Tracking

### Overview

Phase 2 implements a proper PocketFlow-based repair system using the supervisor pattern with checkpoint tracking through InstrumentedNodeWrapper. This follows pflow's architecture where complex orchestration uses flows, not simple functions.

### Architecture Pattern

Following the planner's architecture, the repair system should be:

```
src/pflow/repair/
├── __init__.py
├── flow.py           # Repair flow orchestration
├── nodes.py          # Repair-specific nodes
└── prompts/          # Repair prompt templates
    └── repair_workflow.md
```

## Component Specifications

## 1. Repair Flow (`src/pflow/repair/flow.py`)

**Following the Supervisor Pattern from PocketFlow:**

```python
from pocketflow import Flow, Node
from .nodes import (
    ErrorAnalyzerNode,
    RepairGeneratorNode,
    StaticValidatorNode,
    RuntimeExecutorNode,
    ResultPreparationNode
)

def create_repair_flow(max_attempts: int = 3) -> Flow:
    """Create repair flow using supervisor pattern.

    Flow structure:
    1. Analyze errors from failed execution
    2. Generate repair using LLM
    3. Validate repaired workflow (static)
    4. Execute repaired workflow (runtime)
    5. Loop or return based on results
    """

    # Initialize nodes
    error_analyzer = ErrorAnalyzerNode()
    repair_generator = RepairGeneratorNode(wait=1)
    static_validator = StaticValidatorNode()
    runtime_executor = RuntimeExecutorNode()
    result_preparation = ResultPreparationNode()

    # Create flow with error analyzer as start
    flow = Flow(start=error_analyzer)

    # Define routing
    error_analyzer >> repair_generator

    # Generator outputs
    repair_generator - "generated" >> static_validator
    repair_generator - "unrepairable" >> result_preparation

    # Validator outputs (similar to planner's ValidatorNode)
    static_validator - "valid" >> runtime_executor
    static_validator - "invalid" >> repair_generator  # Retry with validation errors
    static_validator - "max_attempts" >> result_preparation

    # Runtime executor outputs
    runtime_executor - "success" >> result_preparation
    runtime_executor - "failed" >> error_analyzer  # Loop back with new errors
    runtime_executor - "max_attempts" >> result_preparation

    return flow
```

## 2. Repair Nodes (`src/pflow/repair/nodes.py`)

### ErrorAnalyzerNode

```python
class ErrorAnalyzerNode(Node):
    """Analyzes execution errors to determine repair strategy."""

    name = "error-analyzer"

    def prep(self, shared: dict) -> dict:
        return {
            "errors": shared.get("execution_errors", []),
            "shared_after": shared.get("shared_after", {}),
            "failed_node": shared.get("failed_node"),
            "repair_attempts": shared.get("repair_attempts", 0)
        }

    def exec(self, prep_res: dict) -> dict:
        """Analyze errors for repairability."""
        errors = prep_res["errors"]

        # Classify errors
        fixable = []
        unfixable = []

        for error in errors:
            if self._is_fixable(error):
                fixable.append(self._extract_repair_context(error))
            else:
                unfixable.append(error)

        return {
            "fixable_errors": fixable,
            "unfixable_errors": unfixable,
            "repair_context": self._build_repair_context(fixable, prep_res["shared_after"])
        }

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        if exec_res["unfixable_errors"]:
            shared["repair_failed"] = True
            shared["unfixable_errors"] = exec_res["unfixable_errors"]
            return "unrepairable"

        shared["repair_context"] = exec_res["repair_context"]
        shared["fixable_errors"] = exec_res["fixable_errors"]
        return "default"  # Continue to repair generator
```

### RepairGeneratorNode

```python
class RepairGeneratorNode(Node):
    """Generates repaired workflow using LLM."""

    name = "repair-generator"

    def __init__(self, wait: int = 1):
        super().__init__(max_retries=2, wait=wait)

    def prep(self, shared: dict) -> dict:
        return {
            "workflow_ir": shared["original_workflow"],
            "errors": shared.get("fixable_errors", []),
            "validation_errors": shared.get("validation_errors", []),
            "repair_context": shared.get("repair_context", {}),
            "original_request": shared.get("original_request"),
            "repair_attempts": shared.get("repair_attempts", 0)
        }

    def exec(self, prep_res: dict) -> dict:
        """Generate repair using Claude Haiku."""
        import llm

        # Build comprehensive prompt
        prompt = self._build_repair_prompt(
            workflow_ir=prep_res["workflow_ir"],
            errors=prep_res["errors"],
            validation_errors=prep_res["validation_errors"],
            context=prep_res["repair_context"],
            original_request=prep_res["original_request"]
        )

        # Use Haiku for fast, cheap repairs
        model = llm.get_model("anthropic/claude-3-haiku-20240307")
        response = model.prompt(prompt, temperature=0.0)

        # Extract and validate JSON
        repaired_ir = self._extract_workflow_json(response.text())

        return {
            "success": repaired_ir is not None,
            "repaired_ir": repaired_ir
        }

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        attempts = prep_res["repair_attempts"]

        if not exec_res["success"]:
            if attempts >= 3:
                return "unrepairable"
            # Store error for retry
            shared["repair_generation_failed"] = True
            return "unrepairable"

        shared["repaired_workflow"] = exec_res["repaired_ir"]
        shared["repair_attempts"] = attempts + 1
        return "generated"
```

### StaticValidatorNode

```python
class StaticValidatorNode(Node):
    """Validates repaired workflow structure and templates."""

    name = "static-validator"

    def prep(self, shared: dict) -> dict:
        from pflow.registry import Registry

        return {
            "workflow_ir": shared["repaired_workflow"],
            "execution_params": shared.get("execution_params", {}),
            "registry": Registry(),
            "repair_attempts": shared.get("repair_attempts", 0)
        }

    def exec(self, prep_res: dict) -> dict:
        """Validate using existing infrastructure."""
        from pflow.core.workflow_validator import WorkflowValidator

        errors = WorkflowValidator.validate(
            prep_res["workflow_ir"],
            extracted_params=prep_res["execution_params"],
            registry=prep_res["registry"]
        )

        return {"errors": errors}

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        attempts = prep_res["repair_attempts"]
        errors = exec_res["errors"]

        if not errors:
            return "valid"  # Proceed to runtime execution

        if attempts >= 3:
            shared["validation_failed"] = True
            return "max_attempts"

        # Store errors for repair generator
        shared["validation_errors"] = errors
        return "invalid"  # Back to repair generator
```

### RuntimeExecutorNode

```python
class RuntimeExecutorNode(Node):
    """Executes repaired workflow with checkpoint resume."""

    name = "runtime-executor"

    def prep(self, shared: dict) -> dict:
        return {
            "workflow_ir": shared["repaired_workflow"],
            "execution_params": shared.get("execution_params", {}),
            "resume_state": shared.get("checkpoint_state"),  # Critical for resume!
            "repair_attempts": shared.get("repair_attempts", 0)
        }

    def exec(self, prep_res: dict) -> dict:
        """Execute with checkpoint resume."""
        from pflow.execution.executor_service import WorkflowExecutorService

        executor = WorkflowExecutorService()
        result = executor.execute_workflow(
            workflow_ir=prep_res["workflow_ir"],
            execution_params=prep_res["execution_params"],
            shared_store=prep_res["resume_state"],  # Resume from checkpoint!
            validate=False  # Already validated
        )

        return {
            "success": result.success,
            "errors": result.errors,
            "shared_after": result.shared_after,
            "output_data": result.output_data
        }

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        attempts = prep_res["repair_attempts"]

        if exec_res["success"]:
            shared["final_result"] = exec_res
            return "success"

        if attempts >= 3:
            return "max_attempts"

        # Store new errors for analysis
        shared["execution_errors"] = exec_res["errors"]
        shared["shared_after"] = exec_res["shared_after"]
        shared["checkpoint_state"] = exec_res["shared_after"]  # Update checkpoint
        return "failed"  # Back to error analyzer
```

## 3. Integration with Execution System

**Update `workflow_execution.py`:**

```python
def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    enable_repair: bool = True,
    # ... other params
) -> ExecutionResult:
    """Execute workflow with optional repair flow."""

    # First execution attempt
    executor = WorkflowExecutorService(output_interface=output)
    result = executor.execute_workflow(
        workflow_ir=workflow_ir,
        execution_params=execution_params,
        validate=not enable_repair  # Skip validation if repair enabled
    )

    if result.success or not enable_repair:
        return result

    # Trigger repair flow
    if output.is_interactive():
        display.show_repair_start()

    # Create and run repair flow
    from pflow.repair import create_repair_flow

    repair_flow = create_repair_flow(max_attempts=3)
    repair_shared = {
        "original_workflow": workflow_ir,
        "execution_errors": result.errors,
        "shared_after": result.shared_after,
        "checkpoint_state": result.shared_after,  # For resume!
        "failed_node": result.shared_after.get("__execution__", {}).get("failed_node"),
        "execution_params": execution_params,
        "original_request": original_request
    }

    # Run repair flow
    repair_flow.run(repair_shared)

    # Check repair result
    if repair_shared.get("final_result"):
        final = repair_shared["final_result"]
        return ExecutionResult(
            success=final["success"],
            shared_after=final["shared_after"],
            output_data=final["output_data"]
        )
    else:
        # Repair failed, return original error
        return result
```

## 4. Key Differences from Simple Service

### Flow Benefits:
1. **Proper retry loops** with validation at each step
2. **Separation of concerns** - each node has one job
3. **Action-based routing** - clear flow control
4. **Testability** - each node can be tested independently
5. **Extensibility** - easy to add new repair strategies

### Checkpoint/Resume:
- InstrumentedNodeWrapper tracking remains unchanged
- Checkpoint passed through `resume_state` parameter
- Nodes check `shared["__execution__"]["completed_nodes"]` to skip

### Validation Strategy:
1. **Static validation** after each repair attempt
2. **Runtime execution** to catch dynamic errors
3. **Loop back** to repair with specific error context
4. **Max attempts** to prevent infinite loops

## Migration Path

### Phase 1 (Current):
Keep simple `repair_service.py` but extract logic into node classes

### Phase 2 (Next):
Create flow structure while maintaining backward compatibility

### Phase 3 (Future):
Full migration to flow-based repair with extended capabilities

## Success Criteria

1. **Template errors trigger repair** (not just warnings)
2. **Static validation prevents invalid repairs**
3. **Resume from checkpoint** (no re-execution)
4. **Display shows "↻ cached"** for resumed nodes
5. **Max 3 repair attempts** before giving up
6. **Non-repairable errors fail fast**

## Testing Strategy

1. **Unit tests** for each node
2. **Flow integration tests** with mocked LLM
3. **End-to-end tests** with real template errors
4. **Checkpoint verification** - no duplicate side effects

This architecture follows PocketFlow patterns and provides a robust, extensible repair system that can evolve beyond simple template fixes to handle complex runtime errors.