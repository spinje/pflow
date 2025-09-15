# Plan to Fix Remaining 6 Tests

## Analysis of Failures

All 6 tests are failing because they haven't been updated for the new Task 52 flow that includes RequirementsAnalysisNode and PlanningNode.

### Current Flow Order (Task 52)
1. **WorkflowDiscoveryNode** - finds or doesn't find workflow
2. **ParameterDiscoveryNode** - discovers parameters (MOVED earlier)
3. **RequirementsAnalysisNode** - extracts requirements (NEW)
4. **ComponentBrowsingNode** - selects components
5. **PlanningNode** - creates execution plan (NEW)
6. **WorkflowGeneratorNode** - generates workflow
7. **ParameterMappingNode** - maps parameters
8. **ValidatorNode** - validates (may retry to WorkflowGeneratorNode)
9. **MetadataGenerationNode** - generates metadata

### Failing Tests

1. **test_retry_mechanism_with_controlled_failures**
   - Issue: Missing RequirementsAnalysisNode mock → marked as "too vague" → exits early
   - Fix: Add Requirements and Planning mocks

2. **test_missing_parameters_scenario_path_b**
   - Issue: Same - missing new node mocks
   - Fix: Add Requirements and Planning mocks

3. **test_max_retries_exceeded**
   - Issue: Same - missing new node mocks
   - Fix: Add Requirements and Planning mocks, ensure 3+ generation attempts

4. **test_convergence_at_parameter_mapping**
   - Issue: Missing new node mocks for Path B
   - Fix: Add Requirements and Planning mocks

5. **test_complete_flow_with_stdin_data**
   - Issue: Missing new node mocks
   - Fix: Add Requirements and Planning mocks

6. **test_planner_simple.py::test_path_b_generation**
   - Issue: Different file, likely same issue
   - Fix: Add Requirements and Planning mocks

## Common Fix Pattern

For each test, we need to:

### 1. Add RequirementsAnalysisNode Mock
```python
requirements_response = Mock()
requirements_response.json.return_value = {
    "content": [{
        "input": {
            "is_clear": True,  # IMPORTANT: Must be True to continue
            "clarification_needed": None,
            "steps": ["Step 1", "Step 2"],
            "estimated_nodes": 2,
            "required_capabilities": ["llm"],
            "complexity_indicators": {}
        }
    }]
}
```

### 2. Add PlanningNode Mock
```python
planning_response = Mock()
planning_response.text.return_value = """## Execution Plan

Based on requirements, creating workflow.

**Status**: FEASIBLE
**Node Chain**: node1 >> node2"""
```

### 3. Update Mock side_effect Order
```python
mock_model.prompt.side_effect = [
    discovery_response,       # 1. Discovery
    param_discovery,          # 2. ParameterDiscovery (MOVED)
    requirements_response,    # 3. RequirementsAnalysis (NEW)
    browsing_response,        # 4. ComponentBrowsing
    planning_response,        # 5. Planning (NEW)
    generation_response,      # 6. Generation
    param_mapping,           # 7. ParameterMapping
    # ... rest of flow
]
```

## Special Cases

### Retry Tests (3 tests)
For tests with retries, we need:
- Same generation response used multiple times
- OR different responses for each attempt
- Accumulated context handled automatically by WorkflowGeneratorNode

### Stdin Data Test
- Needs to preserve stdin in shared store
- Otherwise same fix pattern

## Implementation Order

1. **Fix simple tests first** (convergence, stdin, simple)
   - These just need the new mocks added

2. **Fix retry tests** (retry_mechanism, max_retries, missing_params)
   - More complex due to multiple generation attempts
   - Need to ensure validation errors trigger retries

## Key Points to Remember

1. **RequirementsAnalysisNode MUST have `is_clear: True`** or it exits with "clarification_needed"
2. **PlanningNode MUST return text (not json)** with Status: FEASIBLE
3. **Mock order is critical** - must match new flow exactly
4. **ParameterDiscovery moved BEFORE Requirements** (not after ComponentBrowsing)