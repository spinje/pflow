# Plan to Fix Last 2 Failing Tests

## Root Cause Analysis

Both tests are failing with the same error:
```
RequirementsAnalysisNode: Input too vague - Please specify what needs to be processed
```

### Why This Happens:
1. The tests were written for the OLD flow order
2. They're missing mocks for the NEW nodes (RequirementsAnalysis and Planning)
3. The mock order doesn't match the Task 52 flow

### Current Mock Order in Failing Tests:
```
1. Discovery
2. Browse (WRONG - should be ParameterDiscovery)
3. Param discovery (WRONG - should be RequirementsAnalysis)
4. Generation (WRONG - missing ComponentBrowsing and Planning)
```

### Required Mock Order (Task 52):
```
1. Discovery (not found)
2. ParameterDiscovery (MOVED earlier)
3. RequirementsAnalysis (NEW - this is missing!)
4. ComponentBrowsing
5. Planning (NEW - this is missing!)
6. WorkflowGeneration
7. ParameterMapping
```

## Test 1: test_convergence_at_parameter_mapping

### Current Structure:
- Path A: Tests existing workflow discovery (working)
- Path B: Tests workflow generation (failing)

### Path B Mocks Needed:
```python
responses = [
    # 1. Discovery not found
    discovery_not_found,

    # 2. ParameterDiscovery (was at position 3)
    param_discovery,

    # 3. RequirementsAnalysis (NEW - MISSING!)
    requirements_response,  # Must have is_clear: True

    # 4. ComponentBrowsing (was at position 2)
    browse_response,

    # 5. Planning (NEW - MISSING!)
    planning_response,  # Must return text with Status: FEASIBLE

    # 6. Generation
    generation_response,

    # 7. ParameterMapping (for validation)
    param_mapping,

    # 8. Metadata (after successful validation)
    metadata_response,

    # 9. Final ParameterMapping (convergence point)
    param_mapping_final,
]
```

## Test 2: test_complete_flow_with_stdin_data

### Key Difference:
This test includes stdin data in the shared store, but otherwise needs the same fix.

### Mocks Needed:
Same order as above, but:
- ParameterDiscovery should detect stdin_type
- Requirements should acknowledge stdin processing
- Planning should mention stdin in the plan

## Implementation Strategy

### Step 1: Create Helper Mocks
For both tests, we need to insert:

```python
# After param_discovery, insert:
requirements_response = create_requirements_mock(
    is_clear=True,
    steps=["Process input", "Generate output"],
    capabilities=["llm"]
)

# After (what was) browse, insert:
planning_response = create_planning_mock(
    status="FEASIBLE",
    node_chain="llm"
)
```

### Step 2: Reorder Existing Mocks
1. Move param_discovery to position 2
2. Move browse to position 4
3. Adjust indices in side_effect list

### Step 3: Update side_effect Order
Count total mocks needed:
- Discovery: 1
- ParameterDiscovery: 1
- RequirementsAnalysis: 1 (NEW)
- ComponentBrowsing: 1
- Planning: 1 (NEW)
- Generation: 1-3 (depending on retries)
- ParameterMapping: 1-2 (before and after validation)
- Metadata: 1 (if validation passes)

Total: 9-12 mocks (was 7-10)

## Key Points to Remember

1. **RequirementsAnalysis MUST have `is_clear: True`** or test exits early
2. **Planning returns .text() not .json()** - different mock structure
3. **Order is critical** - must match new flow exactly
4. **ValidatorNode doesn't use LLM** - validates internally now

## Testing Strategy

After fixing:
1. Run each test individually to verify
2. Check for any remaining mock mismatches
3. Ensure convergence point (ParameterMapping) is reached by both paths
4. Verify shared store contains expected keys

## Common Pitfall
Don't forget that ValidatorNode no longer makes LLM calls - it validates internally using the registry. So don't include validation mocks in the side_effect list.