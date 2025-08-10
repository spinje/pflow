# Validation Redesign Implementation Plan

## Problem Summary
Template validation happens BEFORE parameter extraction, causing workflows with required inputs to fail validation. The validator checks templates against an empty {} dictionary instead of actual parameter values.

## Current Flow (BROKEN)
```
Generate → Validate (❌ with {}) → Metadata → ParameterMapping (extracts values here)
           ↑_______retry (3x)_______↓
```

## Target Flow (FIXED)
```
Generate → ParameterMapping (extract first) → Validate (✅ with params) → Metadata
                    ↓
            params_incomplete → ResultPreparation (skip validation)
```

## Implementation Steps

### Phase 1: Core Flow Reordering

#### 1.1 Update flow.py
Change the node connections to extract parameters before validation:

```python
# FROM (current):
workflow_generator - "validate" >> validator
validator - "retry" >> workflow_generator
validator - "metadata_generation" >> metadata_generation
validator - "failed" >> result_preparation
metadata_generation >> parameter_mapping

# TO (fixed):
workflow_generator - "validate" >> parameter_mapping
parameter_mapping - "params_complete" >> validator
parameter_mapping - "params_incomplete" >> result_preparation
validator - "retry" >> workflow_generator
validator - "metadata_generation" >> metadata_generation
validator - "failed" >> result_preparation
metadata_generation >> parameter_preparation
```

#### 1.2 Update WorkflowGeneratorNode
No changes needed - it already returns "validate"

#### 1.3 Update ParameterMappingNode
Needs to handle both Path A (found_workflow) and Path B (generated_workflow):

```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    # Support both paths
    workflow = shared.get("found_workflow") or {"ir": shared.get("generated_workflow")}
    # Rest remains the same
```

#### 1.4 Update ValidatorNode
Make it use extracted parameters for validation:

```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow": shared.get("generated_workflow"),
        "generation_attempts": shared.get("generation_attempts", 0),
        "extracted_params": shared.get("extracted_params", {}),  # NEW
    }

def _validate_templates(self, workflow: dict[str, Any]) -> list[str]:
    # Use extracted_params instead of empty {}
    params = self.prep_res.get("extracted_params", {})
    template_errors = TemplateValidator.validate_workflow_templates(
        workflow,
        params,  # Now has actual values!
        self.registry,
    )
    return template_errors
```

#### 1.5 Update MetadataGenerationNode
Change its output to go to parameter_preparation instead of parameter_mapping:
- No code change needed in the node itself
- Just the flow wiring change in flow.py

### Phase 2: Handle Edge Cases

#### 2.1 Skip Validation When Parameters Missing
When ParameterMappingNode finds missing parameters, skip validation entirely:
- The flow already handles this with "params_incomplete" → result_preparation

#### 2.2 Ensure Retry Loop Still Works
The retry loop (validator → generator) should still work for actual generation issues:
- Syntax errors in generated workflow
- Invalid node types
- Structural problems

### Phase 3: Test Updates

#### 3.1 Update Mock Sequences
Change the order of mocks in all integration tests:

```python
# FROM:
responses = [
    discovery_response,
    browsing_response,
    param_discovery_response,
    generation_response,  # x3 for retries
    generation_response,
    generation_response,
    metadata_response,
    param_mapping_response,
]

# TO:
responses = [
    discovery_response,
    browsing_response,
    param_discovery_response,
    generation_response,  # Only 1 needed!
    param_mapping_response,  # Moved before validation
    metadata_response,  # After validation passes
]
```

#### 3.2 Use Realistic Workflows
Remove empty inputs workaround:

```python
# FROM:
"inputs": {}  # Workaround

# TO:
"inputs": {
    "input_file": {
        "description": "Input file to process",
        "type": "string",
        "required": True
    }
}
```

#### 3.3 Test Missing Parameters Path
Add tests for when extraction fails:
- ParameterMappingNode → "params_incomplete" → ResultPreparation

## Files to Modify

### Core Implementation
1. `src/pflow/planning/flow.py` - Reorder connections (lines 80-115)
2. `src/pflow/planning/nodes.py` - Update ValidatorNode (lines 1180-1250)
3. `src/pflow/planning/nodes.py` - Update ParameterMappingNode prep (lines 700-720)

### Test Files (Remove Workarounds)
1. `tests/test_planning/integration/test_planner_integration.py`
2. `tests/test_planning/integration/test_planner_simple.py`
3. `tests/test_planning/integration/test_planner_smoke.py`
4. `tests/test_planning/integration/test_flow_structure.py` - Update expected edges

## Validation Points

After implementation, verify:
1. ✅ Workflows with required inputs pass validation
2. ✅ Only 1 generation mock needed (not 3)
3. ✅ Template variables validated with actual values
4. ✅ Missing parameters skip validation gracefully
5. ✅ Retry loop still works for real generation errors
6. ✅ Both Path A and Path B converge correctly

## Risk Assessment

### Low Risk
- Flow reordering is straightforward
- Node changes are minimal
- Tests will immediately show if it works

### Medium Risk
- Retry logic might need adjustment
- Some edge cases in parameter extraction

### Mitigation
- Run all existing tests after each change
- Add new tests for the redesigned flow
- Keep old flow logic commented for rollback

## Success Criteria

1. All integration tests pass without triple generation mocks
2. Workflows with required inputs validate correctly
3. Template validation uses extracted parameter values
4. Missing parameters handled gracefully
5. Performance similar or better than current

## Implementation Order

1. Update flow.py connections
2. Update ValidatorNode to use extracted_params
3. Update ParameterMappingNode to handle both paths
4. Run tests to verify basic flow works
5. Update test mocks and remove workarounds
6. Add new tests for edge cases
7. Update documentation

This plan minimizes risk by making incremental changes that can be tested at each step.