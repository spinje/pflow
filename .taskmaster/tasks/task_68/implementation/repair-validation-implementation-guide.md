# Repair Service Validation Implementation Guide

## Executive Summary

This document provides step-by-step instructions to add static validation to the repair service, creating a validation loop similar to the planner's architecture. The repair service will validate generated repairs before attempting execution, preventing structurally invalid workflows from being executed.

## Current State Analysis

### What Currently Exists

1. **`src/pflow/execution/repair_service.py`**
   - `repair_workflow()` function that uses LLM to fix errors
   - Basic IR validation in `_validate_repaired_workflow()`
   - No static validation of templates or structure

2. **`src/pflow/execution/workflow_execution.py`**
   - `execute_workflow()` function that calls repair once
   - No retry loop for validation failures
   - Skips validation when repair is enabled

3. **`src/pflow/execution/executor_service.py`**
   - Has `validate` parameter (already added)
   - Executes workflows with optional validation

### The Problem

**Current Flow (Broken):**
```
Workflow fails → Generate repair → Execute repaired workflow
                                         ↓
                              If invalid structure → Crash!
```

**What Happens:**
1. LLM generates repair with wrong edge format (`from_node` instead of `from`)
2. No validation catches this
3. Execution fails with "Edge missing from_node or to_node"
4. No retry, just failure

## Solution Architecture (Option A)

### New Flow
```
Workflow fails → Generate repair → Static Validation → Runtime Execution
                        ↑                    ↓                ↓
                        └────── Retry ←───────┴────────────────┘
                              (max 3 attempts)
```

### Key Components

1. **Enhanced repair function** with validation loop
2. **Unified error format** for both validation and runtime errors
3. **Retry logic** in workflow_execution.py
4. **Proper checkpoint preservation** through retries

## Detailed Implementation Steps

### Step 1: Create Enhanced Repair Function

**File:** `src/pflow/execution/repair_service.py`

**Add this new function AFTER the existing `repair_workflow()` function:**

```python
def repair_workflow_with_validation(
    workflow_ir: dict,
    errors: List[Dict[str, Any]],
    original_request: Optional[str] = None,
    shared_store: Optional[Dict[str, Any]] = None,
    execution_params: Optional[Dict[str, Any]] = None,
    max_attempts: int = 3
) -> Tuple[bool, Optional[dict], Optional[List[Dict[str, Any]]]]:
    """
    Repair workflow with static validation loop.

    This function:
    1. Generates repair based on errors
    2. Validates the repair statically
    3. If validation fails, regenerates with validation errors
    4. Returns repaired workflow only if it passes validation

    Args:
        workflow_ir: The workflow that failed
        errors: List of error dictionaries from execution or validation
        original_request: Original user request for context
        shared_store: Execution state for additional context
        execution_params: Parameters for template validation
        max_attempts: Maximum repair generation attempts (default: 3)

    Returns:
        Tuple of:
        - success: True if repair succeeded and validated
        - repaired_workflow_ir: The repaired and validated workflow (or None)
        - validation_errors: Any remaining validation errors (or None)
    """

    attempt = 0
    current_errors = errors
    current_workflow = workflow_ir

    while attempt < max_attempts:
        logger.info(f"Repair attempt {attempt + 1}/{max_attempts}")

        # 1. Generate repair based on current errors
        success, repaired_ir = repair_workflow(
            workflow_ir=current_workflow,
            errors=current_errors,
            original_request=original_request,
            shared_store=shared_store
        )

        if not success or not repaired_ir:
            logger.warning(f"Repair generation failed at attempt {attempt + 1}")
            return False, None, None

        # 2. Static Validation
        from pflow.core.workflow_validator import WorkflowValidator
        from pflow.registry import Registry

        try:
            registry = Registry()
            validation_errors = WorkflowValidator.validate(
                repaired_ir,
                extracted_params=execution_params or {},
                registry=registry,
                skip_node_types=False  # Always validate node types
            )

            if not validation_errors:
                # Validation passed!
                logger.info(f"Repair validated successfully at attempt {attempt + 1}")
                return True, repaired_ir, None

            # Validation failed, prepare for retry
            logger.warning(f"Repair validation failed with {len(validation_errors)} errors")

            # Convert validation errors to repair format
            current_errors = []
            for error in validation_errors[:3]:  # Limit to top 3 errors
                # Try to extract specific context from error message
                error_dict = {
                    "source": "validation",
                    "category": "static_validation",
                    "message": error,
                    "fixable": True
                }

                # Add specific context based on error type
                if "Template" in error:
                    error_dict["category"] = "template_error"
                    # Extract template path if possible
                    import re
                    template_match = re.search(r'\$\{([^}]+)\}', error)
                    if template_match:
                        error_dict["template"] = template_match.group(0)
                elif "Edge" in error or "from" in error:
                    error_dict["category"] = "edge_format"
                    error_dict["hint"] = "Use 'from' and 'to' keys, not 'from_node' and 'to_node'"
                elif "node type" in error.lower():
                    error_dict["category"] = "invalid_node_type"

                current_errors.append(error_dict)

            # Update workflow for next attempt
            current_workflow = repaired_ir
            attempt += 1

        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False, None, [{"source": "validation", "message": str(e)}]

    # Max attempts reached
    logger.warning(f"Max repair attempts ({max_attempts}) reached")
    return False, None, current_errors
```

**Also update the `_build_repair_prompt()` function to handle validation errors better:**

```python
def _build_repair_prompt(
    workflow_ir: dict,
    errors: List[Dict[str, Any]],
    repair_context: Dict[str, Any],
    original_request: Optional[str]
) -> str:
    """Create prompt for LLM repair."""

    # Check if these are validation errors
    has_validation_errors = any(e.get("source") == "validation" for e in errors)

    # Format errors for prompt
    error_text = _format_errors_for_prompt(errors, repair_context)

    # Build appropriate prompt based on error type
    if has_validation_errors:
        prompt = f"""Fix this workflow that has validation errors.

## Original Request
{original_request or "Not available"}

## Workflow with Validation Issues
```json
{json.dumps(workflow_ir, indent=2)}
```

## Validation Errors to Fix
{error_text}

## Important Requirements
1. Edges must use "from" and "to" keys (NOT "from_node" or "to_node")
2. All template variables must reference actual node outputs
3. Node types must exist in the registry
4. JSON must be valid and properly formatted

## Common Validation Fixes
- Change edge format: {{"from_node": "a", "to_node": "b"}} → {{"from": "a", "to": "b"}}
- Fix template paths: ${{node.wrong_field}} → ${{node.correct_field}}
- Use valid node types from registry

Return ONLY the corrected workflow JSON. Do not include explanations.

## Corrected Workflow
```json
"""
    else:
        # Use existing runtime error prompt
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
- Completed nodes: {', '.join(repair_context.get('completed_nodes', [])) or 'none'}
- Failed at node: {repair_context.get('failed_node', 'unknown')}

## Your Task
Analyze the errors and generate a corrected workflow that fixes the issues.

Common fixes needed:
1. Template variable corrections (e.g., ${{data.username}} → ${{data.login}})
2. Missing parameters in node configs
3. Incorrect field references
4. Shell command syntax errors
5. API response structure changes

Return ONLY the corrected workflow JSON. Do not include explanations.

## Corrected Workflow
```json
"""

    return prompt
```

### Step 2: Update Workflow Execution

**File:** `src/pflow/execution/workflow_execution.py`

**Replace the entire `execute_workflow()` function with:**

```python
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
    trace_collector: Optional[Any] = None,
) -> ExecutionResult:
    """
    Unified workflow execution function with automatic repair capability.

    When repair is enabled:
    1. Skip initial validation to allow runtime errors
    2. On failure, generate repair with static validation
    3. Execute repaired workflow (runtime validation)
    4. Loop if runtime fails, up to max attempts

    When repair is disabled:
    1. Validate at compile time
    2. Fail fast on any errors
    """
    # Default output if not provided
    if output is None:
        output = NullOutput()

    # Create display manager for UI messages
    display = DisplayManager(output=output)

    # Prepare shared store (with checkpoint if resuming)
    if resume_state:
        shared_store = resume_state
        if output.is_interactive():
            display.show_execution_start(len(workflow_ir.get("nodes", [])), context="resume")
    else:
        shared_store = {}

    # Create executor service
    executor = WorkflowExecutorService(output_interface=output, workflow_manager=workflow_manager)

    # Initial execution attempt
    result = executor.execute_workflow(
        workflow_ir=workflow_ir,
        execution_params=execution_params,
        shared_store=shared_store,
        workflow_name=workflow_name,
        stdin_data=stdin_data,
        output_key=output_key,
        metrics_collector=metrics_collector,
        trace_collector=trace_collector,
        validate=not enable_repair,  # Skip validation if repair enabled
    )

    # If successful or repair disabled, return immediately
    if result.success or not enable_repair:
        return result

    # Store original error for fallback
    original_result = result

    # Enter repair loop
    repair_attempts = 0
    max_repair_attempts = 3
    current_checkpoint = result.shared_after

    while repair_attempts < max_repair_attempts:
        if output.is_interactive():
            if repair_attempts == 0:
                display.show_repair_start()
            else:
                display.show_progress(f"Repair attempt {repair_attempts + 1}/{max_repair_attempts}...")

        # 1. Generate repair with static validation loop
        from .repair_service import repair_workflow_with_validation

        success, repaired_ir, validation_errors = repair_workflow_with_validation(
            workflow_ir=workflow_ir,
            errors=result.errors,
            original_request=original_request,
            shared_store=current_checkpoint,
            execution_params=execution_params,
            max_attempts=3  # Inner validation retry loop
        )

        if not success:
            logger.warning(f"Repair generation/validation failed at attempt {repair_attempts + 1}")
            if validation_errors:
                # Show validation errors to user
                for error in validation_errors[:3]:
                    logger.error(f"Validation error: {error.get('message', 'Unknown')}")
            break  # Exit repair loop

        # 2. Execute repaired workflow (runtime validation)
        if output.is_interactive():
            display.show_progress("Executing repaired workflow...")

        result = executor.execute_workflow(
            workflow_ir=repaired_ir,
            execution_params=execution_params,
            shared_store=current_checkpoint,  # Resume from checkpoint!
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            metrics_collector=metrics_collector,
            trace_collector=trace_collector,
            validate=False,  # Already validated in repair function
        )

        if result.success:
            # Success!
            if output.is_interactive():
                display.show_progress("✅ Workflow repaired and executed successfully!")
            return result

        # Runtime execution failed, prepare for next repair attempt
        repair_attempts += 1
        current_checkpoint = result.shared_after  # Update checkpoint
        workflow_ir = repaired_ir  # Use repaired version for next attempt

    # Max attempts reached or repair failed
    logger.warning("Repair failed after maximum attempts")
    return original_result  # Return original error
```

### Step 3: Fix Template Resolution Errors

**File:** `src/pflow/runtime/node_wrapper.py`

**Find the template resolution warning (around line 211) and make it fatal when needed:**

```python
# Around line 208-214, REPLACE:
elif "${" in str(template):
    logger.warning(
        f"Template in param '{key}' could not be fully resolved: '{template}'",
        extra={"node_id": self.node_id, "param": key},
    )

# WITH:
elif "${" in str(template):
    error_msg = f"Template in param '{key}' could not be fully resolved: '{template}'"
    logger.error(error_msg, extra={"node_id": self.node_id, "param": key})

    # Make template errors fatal to trigger repair
    raise ValueError(error_msg)
```

## Testing Strategy

### Test 1: Basic Template Error Repair

Create `test-repair-template.json`:
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "data",
      "type": "shell",
      "params": {
        "command": "echo '{\"name\": \"John\", \"age\": 30}'"
      }
    },
    {
      "id": "use",
      "type": "shell",
      "params": {
        "command": "echo ${data.stdout.username}"
      }
    }
  ],
  "edges": [{"from": "data", "to": "use"}]
}
```

**Expected Behavior:**
1. Execution fails: "Template ${data.stdout.username} not found"
2. Repair generates: Changes to `${data.stdout.name}`
3. Validation passes
4. Execution succeeds with repaired template

### Test 2: Edge Format Repair

Create `test-repair-edges.json`:
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "a", "type": "shell", "params": {"command": "echo A"}},
    {"id": "b", "type": "shell", "params": {"command": "echo B"}}
  ],
  "edges": [{"from_node": "a", "to_node": "b"}]
}
```

**Expected Behavior:**
1. Validation fails: "Edge missing 'from'"
2. Repair fixes edge format
3. Validation passes
4. Execution succeeds

### Test 3: Checkpoint Resume

Test that repaired workflows resume from checkpoint:
1. Create workflow that writes file then fails
2. Verify file written once
3. Repair fixes error
4. Verify file NOT written again (cached)

### Test Commands

```bash
# Test with repair (default)
uv run pflow test-repair-template.json

# Test without repair (should fail)
uv run pflow --no-repair test-repair-template.json

# Test with trace for debugging
uv run pflow --trace test-repair-edges.json
```

## Success Criteria

### Must Work:
1. ✅ Template errors trigger repair (not just warnings)
2. ✅ Validation errors trigger re-generation
3. ✅ Edge format errors are caught and fixed
4. ✅ Maximum 3 repair attempts before giving up
5. ✅ Checkpoint preserved through repair attempts
6. ✅ "↻ cached" shown for already-executed nodes

### Must NOT Happen:
1. ❌ Invalid workflows executed (validation must catch)
2. ❌ Infinite repair loops
3. ❌ Duplicate execution of successful nodes
4. ❌ Silent failures without error messages

## Edge Cases to Handle

1. **LLM returns invalid JSON**: `_extract_workflow_from_response()` handles
2. **Non-repairable errors**: Max attempts prevents infinite loops
3. **Partial checkpoint corruption**: Validate checkpoint structure
4. **Empty error lists**: Check for empty errors before repair

## Implementation Order

1. **First**: Add `repair_workflow_with_validation()` to repair_service.py
2. **Second**: Update `execute_workflow()` in workflow_execution.py
3. **Third**: Make template errors fatal in node_wrapper.py
4. **Test**: Run test workflows to verify behavior

## Rollback Plan

If issues arise:
1. Keep original `repair_workflow()` function unchanged
2. Can revert `execute_workflow()` to single repair attempt
3. Can make template errors non-fatal again

## Important Notes for Implementer

1. **DO NOT** modify the original `repair_workflow()` function - we're adding a new one
2. **DO NOT** change ExecutorService interface - only use existing parameters
3. **ENSURE** checkpoint is passed through all repair attempts
4. **TEST** with actual workflows before considering complete
5. **LOG** all repair attempts for debugging

## Definition of Done

- [ ] `repair_workflow_with_validation()` implemented
- [ ] `execute_workflow()` uses validation loop
- [ ] Template errors are fatal
- [ ] Test workflows pass with repair
- [ ] Test workflows fail with --no-repair
- [ ] No duplicate node execution on resume
- [ ] Documentation updated

This implementation brings the repair service to parity with the planner's validation approach while maintaining the simpler service-based architecture.