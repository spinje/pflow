# Validation Redesign Implementation Guide

## Current State

All integration tests are passing, but they contain workarounds for a fundamental design flaw in the Natural Language Planner's validation system.

## The Problem

The planner validates template variables (`$input_file`, `$output_file`) **BEFORE** extracting their actual values from user input. This causes validation to fail for any generated workflow with required inputs.

### Current Flow (Path B - Generation)
```
Generate → Validate (❌ fails - no params) → Metadata → ParameterMapping (extracts params here)
           ↑_______retry (3x)_______↓
```

### Why Tests Pass (Workarounds)

1. **Empty inputs**: Generated workflows use `"inputs": {}` to avoid template validation
2. **Triple mocks**: We provide 3 identical generation responses for retry attempts
3. **No required params**: Tests avoid workflows with required parameters

## The Solution

Reorder the flow to extract parameters BEFORE validation:

### Future Flow (Path B - Generation)
```
Generate → ParameterMapping (extract params) → Validate (✅ with params) → Metadata
```

## Implementation Steps

### 1. Update flow.py
```python
# Change from:
workflow_generator - "validate" >> validator
validator - "metadata_generation" >> metadata_generation
metadata_generation >> parameter_mapping

# To:
workflow_generator - "validate" >> parameter_mapping
parameter_mapping - "params_complete" >> validator
validator - "metadata_generation" >> metadata_generation
parameter_mapping - "params_incomplete" >> result_preparation
```

### 2. Update ValidatorNode
```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow": shared.get("generated_workflow"),
        "extracted_params": shared.get("extracted_params", {}),  # NEW
    }

def _validate_templates(self, workflow: dict, params: dict) -> list[str]:
    # Use params instead of empty {}
    template_errors = TemplateValidator.validate_workflow_templates(
        workflow,
        params,  # Actual extracted parameters
        self.registry,
    )
```

### 3. Update Tests

After implementing the redesign:

1. **Remove triple generation mocks** - Only need 1 generation response
2. **Use realistic workflows** - Can have required inputs with template variables
3. **Update mock sequences** - ParameterMapping comes before Validation
4. **Test missing params path** - When extraction fails, skip validation

### Example Test Update

```python
# BEFORE (with workaround):
responses = [
    discovery_response,
    browsing_response,
    param_discovery_response,
    generation_response,  # attempt 1
    generation_response,  # attempt 2 (retry)
    generation_response,  # attempt 3 (retry)
    metadata_response,
    param_mapping_response,
]

# AFTER (with fix):
responses = [
    discovery_response,
    browsing_response,
    param_discovery_response,
    generation_response,  # only 1 needed
    param_mapping_response,  # moved before validation
    # validation happens here (no mock needed)
    metadata_response,
]
```

## Files to Update

### Core Implementation
- `src/pflow/planning/flow.py` - Reorder node connections
- `src/pflow/planning/nodes.py` - Update ValidatorNode to use extracted_params
- `src/pflow/planning/nodes.py` - Update WorkflowGeneratorNode routing

### Tests (Remove Workarounds)
- `tests/test_planning/integration/test_planner_integration.py`
- `tests/test_planning/integration/test_planner_simple.py`
- `tests/test_planning/integration/test_planner_smoke.py`

### Documentation
- Update architecture diagrams
- Document new flow order
- Add interactive parameter collection docs

## Benefits After Redesign

1. **Validation works correctly** - Templates validated with real values
2. **No futile retries** - Retry only for actual generation problems
3. **Simpler tests** - No complex mock workarounds needed
4. **Better UX** - Can handle missing parameters gracefully
5. **Logical flow** - Extract first, then validate with extracted values

## Interactive Parameter Collection (Phase 2)

After fixing the flow order, consider adding interactive parameter collection:

```python
# When parameters are missing:
if planner_output.get("needs_user_input"):
    for param in planner_output["missing_params"]:
        value = click.prompt(f"Enter value for {param}")
        # Resume flow with provided parameters
```

## References

- Full redesign document: `scratchpads/task-17-validation-fix/planner-validation-redesign.md`
- Current workarounds are marked with: `⚠️ VALIDATION REDESIGN`
- Search for these markers to find all code that needs updating
- Note: Not all places are marked with this marker, you need to find them all. And you will probably find out that some of the tests are not working as expected.

## **Workflow for fixing the problem** (follow this workflow)

Alot has happened since the last time we worked on this. This is what you need to do to get up to speed:

1. Read `.taskmaster/tasks/task_17/implementation/progress-log.md` (everything below line 1267 is important)
2. Read `scratchpads/task-17-validation-fix/planner-validation-redesign.md` to understand the problem fully
3. Gather context using subagents to verify that you understand the problem, the current codebase and the problem completely
4. Make a detailed plan of what you need to do to fix the problem
5. Make the codefixes yourself (do NOT delegate to subagents)
6. verify the redesign works by following the "Testing the Fix" section below
7. Document your updates in a new document called `scratchpads/task-17-validation-fix/validation-redesign-implementation-log.md`
8. Assign test-writer-fixer subagent to fix the tests (make sure to give comprehensive instructions AND context, prefereably reference any created documents like the `scratchpads/task-17-validation-fix/validation-redesign-implementation-log.md`)
9. Verify that the tests are working as expected

> Important: *Follow the workflow above this is critical.*

## Testing the Fix

To verify the redesign works:

1. Create a test with a workflow that has required inputs
2. Provide only 1 generation mock (not 3)
3. Ensure the workflow uses template variables
4. Verify validation passes with extracted parameters
5. Test the missing parameters path (skip validation)

## Your task

Follow the workflow above to get to the bottom and fix the problem throughly. Think hard!