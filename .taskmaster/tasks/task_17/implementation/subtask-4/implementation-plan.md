# Subtask 4: Generation System - Implementation Plan

## Context Verification

### ✅ Previous Subtask Outputs Confirmed

From the shared progress log and code inspection:

1. **_parse_structured_response() helper exists** - Available in all nodes (lines 153-178, 377-402, etc.)
2. **FlowIR model ready** - Has `inputs` field (Optional[dict[str, Any]]) in ir_models.py
3. **ParameterDiscoveryNode outputs** - Writes `discovered_params` dict to shared store
4. **ParameterMappingNode expects** - Reads `generated_workflow` with `inputs` field
5. **Test fixtures available** - mock_llm_with_schema, Anthropic response patterns
6. **Lazy loading pattern established** - Model loaded in exec(), not __init__()

### ✅ Interface Contract Verified

**Input Keys (from shared store):**
- `user_input`: str
- `discovered_params`: dict[str, str] (optional, from ParameterDiscoveryNode)
- `browsed_components`: dict with node_ids and workflow_names lists
- `planning_context`: str (required, markdown about components)
- `validation_errors`: list[str] (optional, on retry)
- `generation_attempts`: int (optional, default 0)

**Output Keys (to shared store):**
- `generated_workflow`: Complete IR dict with inputs field
- `generation_attempts`: Updated count

**Routing:**
- Always returns "validate" action string

## Component Breakdown

### 1. WorkflowGeneratorNode Class Structure

```python
class WorkflowGeneratorNode(Node):
    name = "generator"  # Class attribute for registry

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared): ...
    def exec(self, prep_res): ...
    def post(self, shared, prep_res, exec_res): ...
    def exec_fallback(self, prep_res, exc): ...
    def _parse_structured_response(self, response, expected_type): ...
    def _build_prompt(self, prep_res): ...
```

### 2. Prompt Building Strategy

The prompt must emphasize:
- Template variables ($var) for ALL dynamic values
- NEVER hardcode values like "1234"
- LINEAR workflow only (no branching)
- Template paths supported ($data.field.subfield)
- Fix specific errors on retry (not simplify)

### 3. Workflow Generation Logic

Key decisions from clarifications:
- Rename parameters for clarity (filename → input_file)
- Use universal defaults only (100, not 20 from request)
- Avoid multiple nodes of same type (shared store collision)
- Include workflow_name for saved workflows
- Generate descriptive node IDs (read_data, not n1)

## Integration Points

### Upstream Dependencies
- **ComponentBrowsingNode**: Provides `browsed_components` and `planning_context`
- **ParameterDiscoveryNode**: Provides `discovered_params` as hints
- **Context builder**: Creates planning_context markdown

### Downstream Consumers
- **ValidatorNode**: Validates generated workflow structure and templates
- **ParameterMappingNode**: Extracts parameters based on inputs field

## Risk Identification

### Technical Risks
1. **Empty planning_context** - Must raise ValueError immediately
2. **Anthropic response parsing** - Must use content[0]['input'] pattern
3. **Template variable preservation** - Never replace with actual values
4. **Linear workflow constraint** - No branching edges allowed

### Mitigation Strategies
1. Check planning_context first thing in exec()
2. Use existing _parse_structured_response() helper
3. Strong prompt emphasis on template variables
4. No action field in edges (linear only)

## Testing Approach

### Unit Tests (tests/test_planning/unit/)
- Test empty planning_context handling
- Test prompt building with/without errors
- Test template variable generation
- Test parameter renaming logic
- Test linear workflow constraint

### Integration Tests (tests/test_planning/integration/)
- Test with ParameterDiscoveryNode output
- Test convergence with ParameterMappingNode
- Test retry with validation errors
- Test North Star workflow generation

### LLM Tests (tests/test_planning/llm/)
- Real API test for workflow generation
- Template variable preservation test
- Progressive enhancement on retry

## Implementation Sequence

### Phase 1: Core Structure (15 min)
1. Add WorkflowGeneratorNode class after ParameterPreparationNode (line ~1000)
2. Import FlowIR from ir_models
3. Set name = "generator" attribute
4. Implement __init__ with super() call

### Phase 2: Main Logic (30 min)
1. Implement prep() to gather all inputs
2. Implement _build_prompt() with template emphasis
3. Implement exec() with:
   - Planning context validation
   - Lazy model loading
   - LLM call with FlowIR schema
   - Response parsing
4. Copy _parse_structured_response() if not inherited

### Phase 3: Integration (20 min)
1. Implement post() to store workflow and route
2. Implement exec_fallback() for error handling
3. Add logging statements
4. Test basic functionality

### Phase 4: Testing (30 min)
1. Create tests/test_planning/unit/test_generator.py
2. Add basic unit tests
3. Create integration test with ParameterMappingNode
4. Verify template variable generation

## Success Metrics

✅ Checklist for completion:
- [ ] WorkflowGeneratorNode class exists with name = "generator"
- [ ] Empty planning_context raises ValueError
- [ ] Lazy model loading in exec()
- [ ] Anthropic response parsing works
- [ ] Generated workflows use template variables
- [ ] Inputs field properly structured
- [ ] Linear workflows only (no branching)
- [ ] Routes to "validate" correctly
- [ ] exec_fallback handles errors
- [ ] Integration with ParameterMappingNode verified
- [ ] Tests passing with make test
- [ ] Code quality passing with make check
- [ ] Progress log updated with insights

## Critical Code Patterns to Follow

### From existing nodes:
```python
# Lazy loading pattern
def exec(self, prep_res):
    model = llm.get_model(prep_res["model_name"])

# Nested response parsing
result = dict(content[0]["input"])

# Planning context check
if not prep_res["planning_context"]:
    raise ValueError("Planning context is required but was empty")

# Template emphasis in prompt
"CRITICAL Requirements:\n1. Use template variables ($variable) for ALL dynamic values"
```

## North Star Examples to Use

For consistency with other subtasks:
- generate-changelog: repo, since_date parameters
- issue-triage-report: repo, labels, state, limit
- create-release-notes: version, repo, include_contributors
- summarize-github-issue: issue_number, repo

## Notes and Discoveries

From progress log analysis:
1. All nodes use identical _parse_structured_response() implementation
2. Anthropic nests data at content[0]['input'] - CRITICAL
3. Test fixtures support schema-based mocking
4. Planning context can be error dict - check isinstance
5. Set name attribute at class level, not in __init__

This plan provides clear implementation guidance while respecting the established patterns from previous subtasks.
