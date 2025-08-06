# Task 17 - Subtask 2 Implementation Plan

## Context Gathering Complete

### Critical Discovery from Subtask 1
⚠️ **IMPORTANT**: The Pydantic models `WorkflowDecision` and `ComponentSelection` do NOT exist in `ir_models.py`. They need to be created directly in `nodes.py` as shown in the spec.

### Dependencies Verified

#### From Previous Subtasks (Subtask 1)
- ✅ `workflow_loader.py` provides `load_workflow()` and `list_all_workflows()`
- ✅ `registry_helper.py` provides `get_node_interface()`, `get_node_outputs()`, `get_node_inputs()`
- ✅ `ir_models.py` has `NodeIR`, `EdgeIR`, `FlowIR` (but NOT WorkflowDecision/ComponentSelection)
- ✅ Test fixtures include `mock_llm_with_schema` and `test_registry_data`
- ✅ LLM configured with anthropic plugin (`llm-anthropic` installed)

#### Context Builder Integration
- ✅ `build_discovery_context(node_ids, workflow_names, registry_metadata)` → returns markdown string
- ✅ `build_planning_context(selected_node_ids, selected_workflow_names, registry_metadata, saved_workflows)` → returns str or error dict
- ⚠️ `build_planning_context()` can return error dict with "error" key - must handle!

### For Next Subtasks
- Must provide `discovery_result` dict for parameter extraction
- Must provide `browsed_components` dict for workflow generation
- Must provide `registry_metadata` dict for downstream validation

## Shared Store Contract

### Reads
- `user_input: str` - Natural language input from CLI
- `stdin_data: Any` - Optional data from stdin pipe
- `current_date: str` - ISO timestamp for context

### Writes

#### WorkflowDiscoveryNode
- `discovery_context: str` - Markdown from build_discovery_context()
- `discovery_result: dict` - LLM decision with found/workflow_name/confidence/reasoning
- `found_workflow: dict` - Full workflow metadata from WorkflowManager.load() (Path A only)

#### ComponentBrowsingNode
- `browsed_components: dict` - Dict with node_ids and workflow_names lists
- `planning_context: str | dict` - Detailed markdown OR empty string on error
- `registry_metadata: dict` - Full registry metadata for downstream nodes

## Implementation Steps

### Phase 1: Core Components (1 hour)
1. Create `src/pflow/planning/nodes.py` with module-level imports and logging
2. Define Pydantic models: `WorkflowDecision` and `ComponentSelection`
3. Implement `WorkflowDiscoveryNode` class:
   - `__init__` with LLM model setup
   - `prep()` method loading discovery context
   - `exec()` method with semantic matching via LLM
   - `post()` method routing "found_existing" or "not_found"
   - `exec_fallback()` for error recovery
4. Implement `ComponentBrowsingNode` class:
   - `__init__` with LLM model setup
   - `prep()` method with Registry instantiation and discovery context
   - `exec()` method with over-inclusive selection
   - `post()` method with planning context and always routing "generate"
   - `exec_fallback()` for error recovery

### Phase 2: Integration (30 mins)
1. Verify context_builder imports work correctly
2. Test WorkflowManager integration for loading workflows
3. Handle planning_context error dict case (check for "error" key)
4. Test Registry instantiation and loading
5. ⚠️ **CRITICAL**: Implement nested response extraction: `response_data['content'][0]['input']`

### Phase 3: Testing (1 hour)
1. Create `tests/test_planning/test_discovery.py`
2. Test Path A routing (found_existing) with exact workflow match
3. Test Path B routing (not_found) with no/partial matches
4. Test ComponentBrowsingNode always returns "generate"
5. Test exec_fallback on both nodes
6. Test planning_context error dict handling
7. Test nested response extraction pattern
8. Use `mock_llm_with_schema` fixture for structured output testing

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| Wrong action strings | Breaks flow routing | Follow spec exactly: "found_existing", "not_found", "generate" |
| Missing registry_metadata | Breaks validation in Subtask 5 | Always store in shared after Registry.load() |
| Planning context errors | Breaks generation in Subtask 4 | Check isinstance(dict) and "error" key |
| Nested response extraction | Mysterious failures | ALWAYS use `response_data['content'][0]['input']` |
| Missing Pydantic models | Can't use structured output | Create WorkflowDecision and ComponentSelection in nodes.py |

## Validation Strategy

### Must Verify
1. Routing strings match spec exactly ("found_existing" / "not_found" / "generate")
2. All shared store keys are written per contract
3. Nested response extraction works: `response_data['content'][0]['input']`
4. Registry metadata propagates for Path B
5. Planning context error dict handled (empty string on error)
6. Both nodes implement exec_fallback
7. Logging provides visibility into decisions

### Integration Points to Test
1. Context builder functions import and work
2. WorkflowManager loads workflows correctly
3. Registry instantiates and loads metadata
4. LLM structured output with Pydantic schemas
5. PocketFlow Node lifecycle (prep/exec/post)

## Critical Implementation Notes

### 1. Nested LLM Response Pattern (MUST FOLLOW)
```python
response = self.model.prompt(prompt, schema=WorkflowDecision, temperature=0)
response_data = response.json()
# ⚠️ CRITICAL: Extract from nested structure
return response_data['content'][0]['input']  # NOT response_data directly!
```

### 2. Planning Context Error Handling
```python
planning_context = build_planning_context(...)
if isinstance(planning_context, dict) and "error" in planning_context:
    logger.warning(f"Planning context error: {planning_context['error']}")
    shared["planning_context"] = ""  # Empty string on error
else:
    shared["planning_context"] = planning_context
```

### 3. Direct Instantiation Pattern
```python
# In ComponentBrowsingNode.prep()
from pflow.registry import Registry
registry = Registry()  # Direct instantiation, NOT singleton
registry_metadata = registry.load()
```

### 4. Action Strings (EXACT)
- WorkflowDiscoveryNode: "found_existing" OR "not_found"
- ComponentBrowsingNode: ALWAYS "generate" (never "found")

## Success Criteria

✅ Checklist before marking complete:
- [ ] Both node classes in single `nodes.py` file
- [ ] WorkflowDecision and ComponentSelection models defined
- [ ] WorkflowDiscoveryNode routes correctly based on semantic match
- [ ] ComponentBrowsingNode always returns "generate"
- [ ] Nested response extraction implemented correctly
- [ ] Registry metadata stored for Path B
- [ ] Planning context error dict handled
- [ ] exec_fallback implemented on both nodes
- [ ] All shared store keys written per contract
- [ ] Tests cover both paths and edge cases
- [ ] make test passes for discovery tests
- [ ] make check passes
- [ ] Progress log updated with insights

## Time Estimate

- Phase 1 (Core): 1 hour
- Phase 2 (Integration): 30 minutes
- Phase 3 (Testing): 1 hour
- Total: ~2.5 hours

## Next Steps

1. Implement nodes.py with both classes
2. Run local tests to verify routing
3. Create comprehensive test suite
4. Document discoveries in shared progress log
5. Hand off to Subtask 3 with clear documentation
