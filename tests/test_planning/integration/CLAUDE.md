# Integration Test Guide for Natural Language Planner

## ⚠️ Critical: Read This First

This guide contains ESSENTIAL information for fixing/writing planner integration tests. Tests in this folder include:
- **Full flow tests** (`test_planner_*.py`): Complete planner execution
- **Partial flow tests** (`test_*_integration.py`): Specific node sequences
- **Discovery tests** (`test_*discovery*.py`, `test_happy_path*.py`): Path A/B routing
- **Structure tests** (`test_flow_structure.py`): Flow wiring without execution

## 🎯 Quick Fix Checklist

1. **Wrong mock structure?** → See "Correct Mock Structures" below
2. **Test hanging/failing on retry?** → Provide 3 generation mocks
3. **Wrong error message?** → Check "Failure Modes" section
4. **Action string mismatch?** → See "Exact Action Strings"

## Correct Mock Structures (Copy These!)

### WorkflowDiscoveryNode (Path A or B entry)
```python
Mock(json=lambda: {"content": [{"input": {
    "found": True,  # or False for Path B
    "workflow_name": "test-workflow",  # or None
    "confidence": 0.95,
    "reasoning": "Match found"
}}]})
```

### ParameterMappingNode (Both paths converge here)
```python
Mock(json=lambda: {"content": [{"input": {
    "extracted": {"param1": "value1"},  # NOT "parameters"!
    "missing": [],  # or ["param1", "param2"]
    "confidence": 0.9,
    "reasoning": "Extracted all parameters"
}}]})
```

### ComponentBrowsingNode (Path B only)
```python
Mock(json=lambda: {"content": [{"input": {
    "node_ids": ["llm", "read-file"],  # NOT "selected_components"!
    "workflow_names": [],
    "reasoning": "Selected relevant components"
}}]})
```

### ParameterDiscoveryNode (Path B only)
```python
Mock(json=lambda: {"content": [{"input": {
    "parameters": {"key": "value"},  # This one IS "parameters"!
    "stdin_type": None,
    "reasoning": "Found parameters"
}}]})
```

### WorkflowGeneratorNode (Path B only)
```python
Mock(json=lambda: {"content": [{"input": {
    "ir_version": "0.1.0",
    "nodes": [...],
    "edges": [...],
    "start_node": "node1",
    "inputs": {...},
    "outputs": {}
}}]})
```

### MetadataGenerationNode (Path B only)
```python
Mock(json=lambda: {"content": [{"input": {
    "suggested_name": "workflow-name",
    "description": "Description",
    "search_keywords": ["key1", "key2"],
    "capabilities": ["capability1"],
    "typical_use_cases": ["use case"],
    "declared_inputs": ["input1"],
    "declared_outputs": []
}}]})
```

## ⚠️ Retry Mechanism (Path B - Full Flow Only)

**For full flow tests**: When validation fails, ValidatorNode returns "retry" → WorkflowGeneratorNode (max 3 attempts)

```python
responses = [
    discovery_response,      # 1
    browsing_response,       # 2
    param_discovery_response,# 3
    generation_response,     # 4 - Attempt 1
    generation_response,     # 5 - Attempt 2 (if validation fails)
    generation_response,     # 6 - Attempt 3 (if validation fails again)
    metadata_response,       # 7 - Only if validation eventually passes
    param_mapping_response   # 8
]
```

**If you only provide ONE generation mock, the test will fail when retry occurs!**

## Exact Action Strings (Must Match!)

```python
# Nodes return these EXACT strings:
WorkflowDiscoveryNode:    "found_existing" | "not_found"
ComponentBrowsingNode:    "generate"  # NOT "default"!
ParameterDiscoveryNode:   ""  # Empty string
ParameterMappingNode:     "params_complete" | "params_incomplete"
ParameterPreparationNode: ""  # Empty string
WorkflowGeneratorNode:    "validate"  # NOT "default"!
ValidatorNode:           "metadata_generation" | "retry" | "failed"
MetadataGenerationNode:   ""  # Empty string
ResultPreparationNode:    None  # Terminates flow
```

## Failure Modes (Different Errors)

1. **Validation Errors** (during generation):
   - Error: `"Validation errors: ..."`
   - Happens when generated workflow fails validation
   - Causes retry loop (up to 3 attempts)

2. **Missing Parameters** (at execution):
   - Error: `"Missing required parameters: param1, param2"`
   - Happens when ParameterMappingNode can't extract required params
   - No retry, goes straight to ResultPreparationNode

## Registry Mock Pattern

```python
with patch("pflow.planning.nodes.Registry") as MockRegistry:
    mock_registry = Mock()
    mock_registry.load.return_value = {
        'llm': {'interface': {'inputs': [], 'outputs': [], 'params': []},
                'description': 'LLM node'}
    }
    # MUST handle node_types parameter:
    mock_registry.get_nodes_metadata.side_effect = lambda node_types: {
        nt: {} for nt in node_types if nt in ['llm', 'read-file', 'write-file']
    }
    MockRegistry.return_value = mock_registry
```

## WorkflowManager Test Pattern

```python
test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))
test_manager.save(
    name="test-workflow",
    workflow_ir={"ir_version": "0.1.0", ...},  # NOT "workflow"!
    description="Test workflow"  # NOT "metadata"!
)
shared = {
    "user_input": "...",
    "workflow_manager": test_manager  # Pass via shared store
}
```

## Common Assertion Patterns

```python
# Order-independent list comparison:
assert set(output["missing_params"]) == {"param1", "param2"}

# Check error type:
assert "Validation errors" in output["error"] or "Missing required parameters" in output["error"]

# Verify path taken:
if "found_workflow" in shared:
    # Path A was taken
    assert "generated_workflow" not in shared
else:
    # Path B was taken
    assert "generated_workflow" in shared
```

## 🔴 CRITICAL: Template Validation Trap

**Generated workflows with required inputs WILL FAIL validation!**

The validator checks if template variables have values AT GENERATION TIME, which they never do:
```python
# ❌ THIS WILL ALWAYS FAIL VALIDATION:
"inputs": {
    "file_path": {"required": True, ...}  # Validator checks: is $file_path provided? NO!
}
"params": {"path": "$file_path"}  # Template variable has no value yet

# ✅ WORKAROUND - Use empty inputs for generated workflows:
"inputs": {}  # No required inputs = no validation failures
```

**Why this matters**: If your Path B test generates a workflow with required inputs, validation will fail, trigger 3 retries, then fail the entire flow. Either:
1. Generate workflows with `"inputs": {}` (recommended)
2. Provide 3+ generation mocks and expect validation failure
3. Mock validation to always pass

## 🔴 CRITICAL: Always Provide 3 Generation Mocks

**Even if you expect validation to pass**, ALWAYS provide 3 generation responses for Path B:

```python
# ❌ FRAGILE - Will break if validation unexpectedly fails:
responses = [
    discovery, browsing, param_discovery,
    generation_response,  # Only 1 copy
    metadata, param_mapping
]

# ✅ ROBUST - Handles unexpected validation failures:
responses = [
    discovery, browsing, param_discovery,
    generation_response,  # Attempt 1
    generation_response,  # Attempt 2 (if validation fails)
    generation_response,  # Attempt 3 (if validation fails again)
    metadata, param_mapping
]
```

**Why**: Template validation is unpredictable. Having 3 mocks prevents mysterious test failures when validation unexpectedly triggers retries.

## ✅ Working Examples

See `test_planner_working.py` for 2 complete working tests with correct mock structures.