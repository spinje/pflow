# Task 17 Natural Language Planner: Validation & Parameter Flow Redesign

## Executive Summary

The Natural Language Planner has a critical design flaw where workflow validation fails because it attempts to validate template variables without first extracting their values from user input. This document proposes a two-part solution: reordering the flow to extract parameters before validation, and adding interactive parameter collection for missing values.

## Problem Statement

### Current Failure Mode
When a user says "analyze data.csv and save to report.txt", the planner:
1. Generates a workflow with template variables `$input_file` and `$output_file`
2. Immediately validates these templates against an **empty parameter dictionary**
3. Fails validation because `$input_file` has no value
4. Retries generation 3 times (which doesn't help - still no values!)
5. Gives up with "validation failed"

The user input contains the actual values ("data.csv", "report.txt"), but they're never extracted before validation.

## Current Architecture Analysis

### The Two-Path System

The planner has two paths that converge at ParameterMappingNode:

**Path A (Workflow Reuse):**
```
Discovery (finds existing) → ParameterMapping → Preparation → Result
```

**Path B (Workflow Generation):**
```
Discovery (not found) → Browse → ParamDiscovery → Generate → Validate → Metadata → ParameterMapping → Preparation → Result
```

### Key Nodes and Their Roles

1. **ParameterDiscoveryNode**: Extracts *hints* for generation (e.g., "format": "CSV")
   - NOT actual parameter values
   - Just context to help the generator

2. **WorkflowGeneratorNode**: Creates workflow with template variables
   - Produces: `{"params": {"file_path": "$input_file"}}`
   - These are placeholders, not values

3. **ValidatorNode**: Validates the generated workflow
   - Structural validation (JSON schema)
   - Template validation ← **THE PROBLEM**
   - Node type validation

4. **ParameterMappingNode**: Extracts actual values from user input
   - Uses LLM to map user input to workflow parameters
   - Produces: `{"input_file": "data.csv", "output_file": "report.txt"}`
   - **This happens AFTER validation in Path B!**

## Root Cause Analysis

### The Fundamental Flaw

ValidatorNode validates templates with an empty parameter dictionary:

```python
def _validate_templates(self, workflow: dict[str, Any]) -> list[str]:
    template_errors = TemplateValidator.validate_workflow_templates(
        workflow,
        {},  # ← Empty! No parameters provided
        self.registry,
    )
```

Meanwhile, the user input is sitting right there in `shared["user_input"]` with the values we need!

### Why This Design Exists

The original design philosophy was:
1. Validate that the generated workflow is structurally sound
2. Only if valid, try to extract parameters
3. If parameters are missing, ask the user

But this conflates two different types of validation:
- **Structural validation**: Is the workflow syntactically correct?
- **Execution validation**: Are all required parameters available?

### The Retry Loop Futility

When validation fails, ValidatorNode returns "retry" → WorkflowGeneratorNode. But:
- The generator creates the same template variables again
- Validation fails again (still no values!)
- This repeats 3 times, then gives up

This retry mechanism assumes validation failures are due to malformed workflows, not missing parameter values.

## Proposed Solutions

### Solution 1: Reorder the Flow (Immediate Fix)

Change Path B to extract parameters BEFORE validation:

**Current Order:**
```
Generate → Validate (❌ fails) → Metadata → ParameterMapping
```

**New Order:**
```
Generate → ParameterMapping → Validate (✅ with params) → Metadata
```

#### Implementation Changes

1. **Modify flow.py** to reorder nodes:
```python
# Current (BROKEN)
workflow_generator - "validate" >> validator
validator - "metadata_generation" >> metadata_generation
metadata_generation >> parameter_mapping

# New (FIXED)
workflow_generator - "validate" >> parameter_mapping
parameter_mapping - "params_complete" >> validator
validator - "metadata_generation" >> metadata_generation
parameter_mapping - "params_incomplete" >> result_preparation  # Skip validation if params missing
```

2. **Update ValidatorNode** to read extracted parameters:
```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow": shared.get("generated_workflow"),
        "generation_attempts": shared.get("generation_attempts", 0),
        "extracted_params": shared.get("extracted_params", {}),  # NEW
    }

def _validate_templates(self, workflow: dict[str, Any], params: dict[str, Any]) -> list[str]:
    template_errors = TemplateValidator.validate_workflow_templates(
        workflow,
        params,  # Use actual extracted parameters
        self.registry,
    )
```

### Solution 2: Interactive Parameter Collection (User Experience Fix)

When ParameterMappingNode can't extract all required parameters, enable interactive collection:

#### Current Behavior
```
Missing params → "params_incomplete" → ResultPreparation → Return error
```

#### New Behavior
```
Missing params → "params_incomplete" → ResultPreparation → Return "needs_input" status
CLI detects "needs_input" → Prompts user → Resume with new params
```

#### Implementation Changes

1. **Extend ResultPreparationNode** to return special status:
```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    if prep_res["missing_params"] and not prep_res["validation_errors"]:
        return {
            "success": False,
            "needs_user_input": True,  # NEW
            "missing_params": prep_res["missing_params"],
            "workflow_ir": prep_res["workflow_ir"],
            "partial_params": prep_res["execution_params"],
            "prompt": f"Please provide values for: {', '.join(prep_res['missing_params'])}"
        }
```

2. **Update CLI** to handle interactive parameter collection:
```python
# In cli/main.py
result = planner_flow.run(shared)
planner_output = shared.get("planner_output")

if planner_output.get("needs_user_input"):
    # Prompt for missing parameters
    for param in planner_output["missing_params"]:
        value = click.prompt(f"Enter value for {param}")
        shared[f"user_provided_{param}"] = value

    # Resume from ParameterMappingNode with additional input
    shared["resume_from"] = "parameter_mapping"
    shared["additional_params"] = collected_params
    result = planner_flow.run(shared)
```

3. **Add Resume Capability** to planner flow:
```python
def create_planner_flow(resume_from: Optional[str] = None):
    if resume_from == "parameter_mapping":
        # Start directly from parameter mapping with additional params
        flow = Flow(start=parameter_mapping)
    else:
        # Normal flow
        flow = Flow(start=discovery_node)
```

## Benefits of This Redesign

### Immediate Benefits (Flow Reordering)
1. **Validation actually works** - templates validated with real parameter values
2. **No more futile retries** - retry only for actual generation issues
3. **Tests pass** - no need for complex mock workarounds
4. **Logical flow** - extract parameters, then validate with them

### User Experience Benefits (Interactive Collection)
1. **Graceful degradation** - partial input still produces results
2. **User control** - explicitly ask for what's needed
3. **No guessing** - system tells user exactly what's missing
4. **Workflow reuse** - can save partially parameterized workflows

## Implementation Priority

### Phase 1: Flow Reordering (High Priority)
- Fixes immediate validation failures
- Makes tests pass
- Minimal code changes
- Can be done immediately

### Phase 2: Interactive Collection (Medium Priority)
- Requires CLI integration
- Needs flow resume capability
- More complex but better UX
- Can be added incrementally

## Testing Considerations

### Current Test Failures
Tests fail because they mock workflows with required input parameters, which fail validation when checked against empty `{}`.

### After Flow Reordering
Tests will pass naturally because:
1. ParameterMapping happens before validation
2. Validation receives extracted parameters
3. Template validation succeeds with actual values

### Test Updates Needed
1. Adjust mock response order (ParameterMapping before Validation)
2. Remove retry workarounds (3x generation mocks)
3. Test both success and missing parameter paths

## Migration Path

### Step 1: Document Current Behavior
- Add comments explaining why validation currently fails
- Document the workaround (providing 3x generation mocks)

### Step 2: Implement Flow Reordering
- Update flow.py with new node ordering
- Modify ValidatorNode to use extracted_params
- Update WorkflowGeneratorNode to route to parameter_mapping

### Step 3: Update Tests
- Fix mock response sequences
- Remove retry workarounds
- Add tests for new flow order

### Step 4: Implement Interactive Collection
- Extend ResultPreparationNode
- Add CLI integration
- Implement flow resume capability

### Step 5: Documentation
- Update architecture docs
- Add user guide for interactive mode
- Document parameter extraction flow

## Conclusion

The current validation approach is fundamentally flawed because it validates template variables before extracting their values from user input. By reordering the flow to extract parameters before validation and adding interactive collection for missing parameters, we can create a system that:

1. **Actually works** - validates with real values, not empty dictionaries
2. **Helps users** - asks for missing information instead of failing
3. **Makes sense** - logical flow from generation → extraction → validation
4. **Tests properly** - no complex workarounds needed

This redesign aligns the implementation with the original vision while fixing the critical flaw that makes Path B fail for any workflow with input parameters.