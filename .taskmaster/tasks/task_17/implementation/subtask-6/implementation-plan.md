# Task 17 - Subtask 6 Implementation Plan

## Node Inventory

### Existing Nodes (from previous subtasks)
- [x] WorkflowDiscoveryNode (lines 48-231) - Returns: "found_existing" | "not_found"
- [x] ComponentBrowsingNode (lines 233-447) - Returns: "generate"
- [x] ParameterDiscoveryNode (lines 467-634) - Returns: ""
- [x] ParameterMappingNode (lines 636-851) - Returns: "params_complete" | "params_incomplete"
- [x] ParameterPreparationNode (lines 853-934) - Returns: ""
- [x] WorkflowGeneratorNode (lines 936-1118) - Returns: "validate"
- [x] ValidatorNode (lines 1120-1311) - Returns: "metadata_generation" | "retry" | "failed"
- [x] MetadataGenerationNode (lines 1313-1536) - Returns: ""

### To Create
- [ ] ResultPreparationNode - Returns: None (flow termination)

## Flow Wiring Diagram

```
START
  ↓
WorkflowDiscoveryNode
  ├─["found_existing"]→ ParameterMappingNode -------- Path A (Reuse)
  │                       ├─["params_complete"]→ ParameterPreparationNode
  │                       │                         └─[""]→ ResultPreparationNode → END
  │                       └─["params_incomplete"]→ ResultPreparationNode → END
  │
  └─["not_found"]→ ComponentBrowsingNode ------------- Path B (Generate)
                    └─["generate"]→ ParameterDiscoveryNode
                                    └─[""]→ WorkflowGeneratorNode
                                           └─["validate"]→ ValidatorNode
                                                           ├─["retry"]→ WorkflowGeneratorNode [MAX 3x]
                                                           ├─["failed"]→ ResultPreparationNode → END
                                                           └─["metadata_generation"]→ MetadataGenerationNode
                                                                                      └─[""]→ ParameterMappingNode
                                                                                              ├─["params_complete"]→ ParameterPreparationNode
                                                                                              │                       └─[""]→ ResultPreparationNode → END
                                                                                              └─["params_incomplete"]→ ResultPreparationNode → END
```

## Implementation Steps

### Phase 1: ResultPreparationNode (30 minutes)
1. Add ResultPreparationNode class to nodes.py (after MetadataGenerationNode)
2. Implement prep() to gather all potential inputs:
   - workflow_ir (from found_workflow or generated_workflow)
   - execution_params
   - missing_params
   - validation_errors
   - generation_attempts
   - workflow_metadata
3. Implement exec() to determine success/failure:
   - Success = workflow_ir exists AND execution_params exists AND no missing_params AND no validation_errors
   - Package all data into structured output
4. Implement post() to return None (standard final node pattern)
5. Create unit tests in test_result_preparation.py:
   - Test all 3 entry scenarios (success, missing params, failed generation)
   - Test success determination logic
   - Test output format

### Phase 2: Flow Creation (45 minutes)
1. Create src/pflow/planning/flow.py
2. Import all nodes from nodes.py:
   ```python
   from pflow.planning.nodes import (
       WorkflowDiscoveryNode, ComponentBrowsingNode, ParameterDiscoveryNode,
       ParameterMappingNode, ParameterPreparationNode, WorkflowGeneratorNode,
       ValidatorNode, MetadataGenerationNode, ResultPreparationNode
   )
   ```
3. Create create_planner_flow() function:
   ```python
   def create_planner_flow():
       # Create all nodes
       discovery_node = WorkflowDiscoveryNode()
       # ... create all 9 nodes

       # Create flow with start node
       flow = Flow(start=discovery_node)

       # Wire Path A edges
       discovery_node - "found_existing" >> parameter_mapping
       parameter_mapping - "params_complete" >> parameter_preparation
       parameter_mapping - "params_incomplete" >> result_preparation
       parameter_preparation >> result_preparation  # "" action

       # Wire Path B edges
       discovery_node - "not_found" >> component_browsing
       component_browsing >> parameter_discovery  # "generate" -> default
       parameter_discovery >> workflow_generator  # "" -> default
       workflow_generator >> validator  # "validate" -> default

       # Wire retry loop
       validator - "retry" >> workflow_generator
       validator - "failed" >> result_preparation
       validator - "metadata_generation" >> metadata_generation

       # Wire convergence
       metadata_generation >> parameter_mapping  # "" -> default

       return flow
   ```
4. Export function in __init__.py
5. Document retry mechanism with clear comments

### Phase 3: Integration Testing (1 hour)
1. Create tests/test_planning/test_planner_integration.py
2. Test Path A complete flow:
   ```python
   def test_path_a_complete():
       test_manager = WorkflowManager(tmp_path / "workflows")
       test_manager.save("test-workflow", test_workflow, metadata)

       flow = create_planner_flow()
       shared = {
           "user_input": "generate changelog",
           "workflow_manager": test_manager
       }
       flow.run(shared)

       assert shared["planner_output"]["success"]
       assert shared["planner_output"]["workflow_ir"] is not None
   ```
3. Test Path B complete flow with mocked LLM
4. Test retry mechanism with controlled failures:
   - Mock first 2 attempts to fail, 3rd to succeed
   - Verify generation_attempts = 3
   - Verify final success
5. Test missing parameters scenario (both paths)
6. Test max retries exceeded (Path B)
7. Create tests/test_planning/test_flow_structure.py:
   - Verify all nodes are connected
   - Check all action strings have edges
   - Validate convergence points

## Risk Mitigation

| Risk | Impact | Mitigation Strategy |
|------|--------|-------------------|
| Wrong action string | Flow breaks | Double-check from actual code |
| Missing edge | Path incomplete | Test both full paths |
| Empty string handling | Flow stops | Use >> for default transitions |
| Retry loop infinite | Tests hang | Rely on 3-attempt limit |
| WorkflowManager mismatch | Path A fails | Use shared["workflow_manager"] pattern |

## Testing Strategy

### Unit Tests
- ResultPreparationNode logic
- Action string returns

### Integration Tests (FEASIBLE per learnings)
- Full Path A execution with test WorkflowManager
- Full Path B execution with mocked LLM
- Retry mechanism with controlled failures
- Missing parameters handling
- Error scenarios

### Test Isolation Pattern
```python
# Create isolated test environment
test_manager = WorkflowManager(tmp_path / "test_workflows")
test_manager.save(...)  # Add controlled test workflows

# Run planner with test manager
flow = create_planner_flow()
shared = {"user_input": "...", "workflow_manager": test_manager}
flow.run(shared)
```

## Key Validation Points

1. **Action strings are EXACT**:
   - "metadata_generation" NOT "valid"
   - "retry" NOT "invalid"
   - "" (empty) NOT "default" or "continue"

2. **Empty string transitions**: Need explicit wiring with >>

3. **ResultPreparationNode returns None**: NOT "complete"

4. **WorkflowManager in shared store**: Enables test isolation

5. **Retry loop works**: 3-attempt limit prevents infinite loops

## Implementation Order

1. ResultPreparationNode implementation
2. Unit tests for ResultPreparationNode
3. create_planner_flow() in flow.py
4. Export in __init__.py
5. Integration tests for Path A
6. Integration tests for Path B
7. Retry mechanism tests
8. Flow structure tests
9. Final validation and cleanup

## Success Criteria

- [ ] ResultPreparationNode handles all 3 entry points
- [ ] create_planner_flow() wires all nodes correctly
- [ ] Path A executes end-to-end successfully
- [ ] Path B executes end-to-end successfully
- [ ] Retry mechanism works with 3-attempt limit
- [ ] Convergence at ParameterMappingNode verified
- [ ] Full integration tests pass with test WorkflowManager
- [ ] Flow structure tests verify all edges
- [ ] make test passes for all new tests
- [ ] Progress log updated with learnings