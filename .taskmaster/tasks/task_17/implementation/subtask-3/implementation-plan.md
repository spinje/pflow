# Task 17 - Subtask 3 Implementation Plan

## Dependencies Verified

### From Previous Subtasks
- ✅ WorkflowDiscoveryNode routes "found_existing" (Path A) or "not_found" (Path B)
- ✅ ComponentBrowsingNode provides browsed_components and planning_context
- ✅ `_parse_structured_response()` helper method available at line 153 in nodes.py
- ✅ Test fixtures (mock_llm_with_schema, etc.) available in conftest.py
- ✅ Lazy loading pattern established (models loaded in exec(), not __init__)
- ✅ Nested LLM response pattern documented and helper available

### For Next Subtasks (What They'll Need From Us)
- discovered_params for GeneratorNode context (Path B)
- execution_params for final workflow execution
- Convergence point established for both paths
- "params_complete" or "params_incomplete" routing actions

## Shared Store Contract

### Keys We Read
- `user_input` (str) - Natural language request
- `stdin` (Optional[str]) - Text data piped from stdin
- `stdin_binary` (Optional[bytes]) - Binary stdin data
- `stdin_path` (Optional[str]) - Temp file path for large stdin
- `browsed_components` (dict) - From ComponentBrowsingNode (Path B)
- `planning_context` (str or empty) - From ComponentBrowsingNode (Path B)
- `registry_metadata` (dict) - From ComponentBrowsingNode (Path B)
- `found_workflow` (dict) - From WorkflowDiscoveryNode (Path A)
- `generated_workflow` (dict) - From GeneratorNode (Path B, future)
- `workflow_metadata` (dict) - From MetadataGenerationNode (Path B, future)

### Keys We Write
- `discovered_params` (dict) - Parameter hints for generation
- `extracted_params` (dict) - Actual parameter values found
- `execution_params` (dict) - Final parameters ready for execution
- `missing_params` (List[str]) - List of missing required parameters

## Implementation Steps

### Phase 1: Core Components (2-3 hours)
1. Create Pydantic models for parameter structures
   - `ParameterDiscovery` model for discovered params
   - `ParameterExtraction` model for mapped params
2. Implement ParameterDiscoveryNode with LLM extraction
   - Lazy model loading in exec()
   - Use `_parse_structured_response()` helper
   - Handle empty planning_context gracefully
3. Implement ParameterMappingNode with independent extraction
   - MUST NOT use discovered_params
   - Extract fresh from user_input and stdin
   - Validate against workflow_ir["inputs"]
   - Route "params_complete" or "params_incomplete"
4. Implement ParameterPreparationNode as pass-through
   - Simple copy of extracted_params to execution_params
   - Prepare for future transformations

### Phase 2: Integration (1-2 hours)
1. Connect to discovery node routing
   - Path A: found_existing → parameter_mapping
   - Path B: generate → parameter_discovery → (future) → parameter_mapping
2. Establish convergence point logic
   - Handle both found_workflow["ir"] and generated_workflow
3. Verify action strings match spec
   - "params_complete" when all required found
   - "params_incomplete" when missing required

### Phase 3: Testing (2-3 hours)
1. Create unit tests (mocked LLM)
   - Test Path A scenarios (found_workflow)
   - Test Path B scenarios (generated_workflow placeholder)
   - Test convergence behavior
   - Test parameter extraction independence
2. Create LLM tests (real API)
   - Test parameter discovery with real language
   - Test extraction accuracy
3. Integration tests
   - Test flow from discovery nodes
   - Test routing to future nodes

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| Wrong routing action | Breaks flow orchestration | Test action strings thoroughly, use exact strings from spec |
| Dependent extraction | Invalid verification, security risk | Ensure ParameterMappingNode does fresh extraction |
| Missing stdin check | Incomplete params when piped data | Always check shared["stdin"] as fallback |
| Nested response handling | Crashes on LLM response | Use existing `_parse_structured_response()` helper |
| Model loading in __init__ | Resource waste, test failures | Always lazy-load in exec() |
| Planning context empty | Node failure | Check for empty string, not just existence |

## Critical Implementation Notes

### 1. Nested LLM Response Pattern (CRITICAL)
```python
# Use the helper method from line 153
structured_data = self._parse_structured_response(response, ExpectedModel)
```

### 2. Lazy Model Loading (CRITICAL)
```python
def exec(self, prep_res):
    model = llm.get_model(prep_res["model_name"])  # NOT in __init__
    temperature = prep_res.get("temperature", 0.0)
```

### 3. Independent Extraction in ParameterMappingNode
```python
# DO NOT use discovered_params here!
# Extract fresh from user_input for verification
```

### 4. Workflow IR Access Pattern
```python
# Path A
workflow_ir = shared["found_workflow"]["ir"]

# Path B (future)
workflow_ir = shared["generated_workflow"]
```

### 5. Template Variable Preservation
- NEVER replace $var with actual values in workflows
- Extract values for parameters, preserve templates

## Validation Strategy

### Unit Tests (Always Run)
- Verify routing from discovery nodes works
- Ensure both paths converge correctly
- Test parameter extraction independence
- Test stdin fallback logic
- Test missing required params detection

### LLM Tests (Run with RUN_LLM_TESTS=1)
- Test real parameter extraction accuracy
- Test complex natural language patterns
- Test confidence scoring

### Integration Tests
- Full Path A flow: discovery → mapping → preparation
- Partial Path B flow: browsing → discovery → mapping
- Verify shared store contracts

## Expected Challenges

1. **Handling both Path A and Path B workflows**
   - Solution: Check for both found_workflow["ir"] and generated_workflow

2. **Template path resolution ($data.field)**
   - Solution: Simple dot notation parsing, no complex expressions

3. **Parameter name matching**
   - Solution: Preserve exact case from workflow inputs field

4. **Stdin as fallback source**
   - Solution: Always check shared["stdin"] when user_input lacks params

## Success Criteria

✅ All three nodes added to existing nodes.py file
✅ ParameterDiscoveryNode extracts named parameters from natural language
✅ ParameterMappingNode does independent extraction and validation
✅ ParameterPreparationNode formats parameters for execution
✅ Correct routing: "params_complete" when all required params found
✅ Correct routing: "params_incomplete" when missing required params
✅ Template syntax ($var and $data.field) properly supported
✅ Stdin checked as fallback parameter source
✅ Both Path A and Path B scenarios tested
✅ Integration with discovery nodes verified
✅ make test passes (for parameter tests)
✅ make check passes
✅ Progress log documents implementation journey

## Next Steps

1. ✅ Create this implementation plan
2. Start with Pydantic models
3. Implement ParameterDiscoveryNode (simplest)
4. Implement ParameterMappingNode (most critical - convergence point)
5. Implement ParameterPreparationNode (pass-through)
6. Write comprehensive tests
7. Update shared progress log throughout
8. Run make test and make check
9. Document insights for future subtasks

---

*This plan ensures the Parameter Management System creates a robust convergence point for Task 17's two-path architecture.*
