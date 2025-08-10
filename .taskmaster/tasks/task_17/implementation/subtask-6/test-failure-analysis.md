# Task 17 Subtask 6: Integration Test Failure Analysis & Solution

## Executive Summary

The integration tests were failing because of incorrect mock response structures, not because the flow implementation was broken. The flow works perfectly when given correctly structured mocks.

## Root Cause Analysis

### The Good News ✅
- **The flow implementation is correct and working**
- All nodes execute in the right order
- Both Path A and Path B routing works correctly
- The shared store contract is properly maintained
- The convergence at ParameterMappingNode works

### The Issues with Tests ❌

#### Issue 1: Wrong Mock Response Structure
Tests were mocking with incorrect field names:

**WRONG:**
```python
"input": {
    "parameters": {  # ❌ Wrong field name
        "repo": {
            "value": "...",
            "source": "...",
            "confidence": 0.95
        }
    }
}
```

**CORRECT:**
```python
"input": {
    "extracted": {  # ✅ Correct field name per ParameterExtraction model
        "repo": "anthropics/pflow",  # Direct values, not nested objects
        "since_date": "2024-01-01",
        "limit": "50"
    },
    "missing": [],
    "confidence": 0.95,
    "reasoning": "..."
}
```

#### Issue 2: Registry Mock Missing Interface Field
ComponentBrowsingNode expects Registry nodes to have an "interface" field:

**WRONG:**
```python
{'llm': {'description': 'Process with LLM'}}  # ❌ Missing interface
```

**CORRECT:**
```python
{'llm': {
    'interface': {
        'inputs': [...],
        'outputs': [...]
    },
    'description': 'Process with LLM'
}}  # ✅ Has interface field
```

#### Issue 3: Wrong Workflow IR Structure in Assertions
Tests expected workflow wrapper with name:

**WRONG:**
```python
assert output["workflow_ir"]["name"] == "generate-changelog"  # ❌
```

**CORRECT:**
```python
assert output["workflow_ir"]["start_node"] == "fetch"  # ✅ IR structure
```

## The Solution

### 1. Fix Mock Response Structures
Each node expects specific Pydantic model structures:

- **WorkflowDiscoveryNode** expects `WorkflowDecision`:
  ```python
  {"found": bool, "workflow_name": str, "confidence": float, "reasoning": str}
  ```

- **ParameterMappingNode** expects `ParameterExtraction`:
  ```python
  {"extracted": dict, "missing": list, "confidence": float, "reasoning": str}
  ```

- **ComponentBrowsingNode** expects `ComponentSelection`:
  ```python
  {"node_ids": list, "workflow_names": list, "reasoning": str}
  ```

### 2. Provide Mocks in Correct Sequence
Each path requires different number of LLM calls:

- **Path A**: 2 calls (Discovery → ParameterMapping)
- **Path B**: 7+ calls (Discovery → Browse → ParamDiscovery → Generate → Validate → Metadata → ParameterMapping)

### 3. Use Test WorkflowManager for Isolation
As discovered in the learnings document:
```python
test_manager = WorkflowManager(tmp_path / "workflows")
shared = {"workflow_manager": test_manager}
```

## Working Test Example

See `tests/test_planning/integration/test_planner_working.py` for two fully working integration tests that demonstrate:
- Correct mock structures
- Proper test isolation with WorkflowManager
- Accurate assertions for shared store state
- Both success and failure scenarios

## How to Fix Remaining Tests

1. **Update mock response structures** to match Pydantic models
2. **Mock Registry.load()** properly when testing Path B
3. **Provide correct number of mock responses** for each path
4. **Fix assertions** to match actual data structures
5. **Use test WorkflowManager** for isolation

## Key Learnings

1. **Always check Pydantic model definitions** when mocking structured responses
2. **The parse_structured_response utility** expects Anthropic's nested format and returns the entire "input" object
3. **Each node documents its expected structures** in its class definition
4. **Integration tests ARE feasible** with proper mock setup
5. **The flow implementation is solid** - test failures were due to incorrect test setup, not bugs in the flow

## Files to Update

- `tests/test_planning/integration/test_planner_integration.py` - Apply fixes to all 9 tests
- `tests/test_planning/integration/test_planner_smoke.py` - Apply fixes to 3 tests

Use the patterns from `test_planner_working.py` as the template.