# Task 36: Testing and Validation Guide

## Testing Strategy Overview

Since we're only changing the context builder's presentation format, testing focuses on:
1. Verifying the new format is clear and correct
2. Ensuring no breaking changes to existing functionality
3. Validating the LLM planner can use the new format effectively

## Pre-Implementation Testing

### 1. Capture Current Output

```python
# capture_current_output.py
from pflow.planning.context_builder import build_planning_context
from pflow.registry import Registry
import json

registry = Registry()
metadata = registry.load()

# Test nodes with different characteristics
test_cases = {
    "simple_node": ["echo"],
    "file_nodes": ["read-file", "write-file"],
    "complex_node": ["github-get-issue"],
    "llm_node": ["llm"],
}

outputs = {}
for case_name, node_ids in test_cases.items():
    filtered = {nid: metadata[nid] for nid in node_ids if nid in metadata}
    context = build_planning_context(
        selected_node_ids=node_ids,
        selected_workflow_names=[],
        registry_metadata=filtered
    )
    outputs[case_name] = context

# Save for comparison
with open("before_context.json", "w") as f:
    json.dump(outputs, f, indent=2)

print("Captured current output for comparison")
```

### 2. Identify Problem Patterns

Look for these problematic patterns in current output:
- `**Parameters**: none` when node has inputs
- `**Inputs**:` section that suggests shared store reads
- `"${key}"` unhelpful placeholder text
- Inconsistent format between nodes

## Unit Tests

### Test 1: Parameters Section Always Present

```python
def test_parameters_section_always_present():
    """All nodes should have a Parameters section."""
    context = build_planning_context(
        selected_node_ids=["read-file", "write-file", "llm"],
        selected_workflow_names=[],
        registry_metadata=test_registry
    )

    # Should have Parameters section for each node
    assert context.count("**Parameters** (all go in params field):") == 3

    # Should NOT have old Inputs section
    assert "**Inputs**:" not in context

    # Should NOT have misleading "Parameters: none"
    assert "**Parameters**: none" not in context
```

### Test 2: Output Access Pattern

```python
def test_output_access_pattern_shown():
    """Outputs should show namespaced access pattern."""
    context = build_planning_context(
        selected_node_ids=["read-file"],
        selected_workflow_names=[],
        registry_metadata=test_registry
    )

    assert "**Outputs** (access as ${node_id.output_key}):" in context
    assert "- `content: str`" in context
```

### Test 3: Example Usage Always Present

```python
def test_example_usage_for_all_nodes():
    """Every node should have an example usage section."""
    nodes = ["read-file", "write-file", "llm"]
    context = build_planning_context(
        selected_node_ids=nodes,
        selected_workflow_names=[],
        registry_metadata=test_registry
    )

    # Each node should have example
    assert context.count("**Example usage**:") == len(nodes)
    assert context.count('```json') == len(nodes)
    assert '"params": {' in context
```

### Test 4: All Parameters Shown

```python
def test_all_parameters_shown():
    """Both inputs and exclusive params should be in Parameters."""
    # LLM has both inputs (prompt) and exclusive params (model, temperature)
    context = build_planning_context(
        selected_node_ids=["llm"],
        selected_workflow_names=[],
        registry_metadata=test_registry
    )

    # Should show ALL parameters
    assert "- `prompt: str`" in context
    assert "- `model:" in context or "- `model: str`" in context
    assert "- `temperature:" in context or "- `temperature: float`" in context
```

### Test 5: Complex Structure Still Works

```python
def test_complex_structure_display():
    """Complex nested structures should still show JSON format."""
    context = build_planning_context(
        selected_node_ids=["github-get-issue"],
        selected_workflow_names=[],
        registry_metadata=test_registry
    )

    # Should still have structure display
    assert "Structure (JSON format):" in context
    assert "Available paths:" in context
```

## Integration Tests

### Test 1: Workflow Generation with New Format

```python
def test_workflow_generation_with_new_context():
    """Test that the planner can generate workflows with new format."""
    from pflow.planning.flow import plan_workflow

    # Use a simple request
    result = plan_workflow("read a file and write it to another location")

    # Should generate valid workflow
    assert result["success"]
    workflow = result["workflow_ir"]

    # Nodes should have params
    for node in workflow["nodes"]:
        assert "params" in node

    # Should use template variables
    assert any("${" in str(node["params"]) for node in workflow["nodes"])
```

### Test 2: Multiple Same-Type Nodes

```python
def test_multiple_same_type_nodes():
    """With namespacing, multiple same-type nodes should work."""
    from pflow.planning.flow import plan_workflow

    result = plan_workflow("fetch github issues 123 and 456 and compare them")

    # Should be able to use multiple github-get-issue nodes
    workflow = result["workflow_ir"]
    github_nodes = [n for n in workflow["nodes"] if n["type"] == "github-get-issue"]

    # With namespacing, this should work
    assert len(github_nodes) >= 2  # Might use 2 or more
```

## Validation Tests

### Before/After Comparison

```python
# compare_outputs.py
import json
import difflib

# Load before output (captured earlier)
with open("before_context.json") as f:
    before = json.load(f)

# Generate after output
from pflow.planning.context_builder import build_planning_context
from pflow.registry import Registry

registry = Registry()
metadata = registry.load()

after = {}
for case_name, node_ids in test_cases.items():
    filtered = {nid: metadata[nid] for nid in node_ids if nid in metadata}
    context = build_planning_context(
        selected_node_ids=node_ids,
        selected_workflow_names=[],
        registry_metadata=filtered
    )
    after[case_name] = context

# Compare each case
for case_name in before:
    print(f"\n{'='*60}")
    print(f"Case: {case_name}")
    print("="*60)

    before_lines = before[case_name].split("\n")
    after_lines = after[case_name].split("\n")

    diff = difflib.unified_diff(
        before_lines, after_lines,
        fromfile="before", tofile="after",
        lineterm=""
    )

    for line in diff:
        if line.startswith("+"):
            print(f"✅ {line}")
        elif line.startswith("-"):
            print(f"❌ {line}")
```

### Key Validation Points

Check that:
1. ❌ `**Inputs**:` is gone
2. ✅ `**Parameters** (all go in params field):` is present
3. ❌ `**Parameters**: none` is gone
4. ✅ `**Example usage**:` is present
5. ✅ Real example values, not `"${key}"`
6. ✅ `**Outputs** (access as ${node_id.output_key}):` shows access pattern

## Performance Testing

### Memory/Speed Impact

```python
import time
import tracemalloc

# Test performance impact
tracemalloc.start()
start_time = time.time()

for _ in range(100):
    context = build_planning_context(
        selected_node_ids=["read-file", "write-file", "llm"],
        selected_workflow_names=[],
        registry_metadata=test_registry
    )

elapsed = time.time() - start_time
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

print(f"Time for 100 generations: {elapsed:.2f}s")
print(f"Memory usage: {current / 1024 / 1024:.2f} MB")

# Should be negligible difference from before
```

## Manual Testing Checklist

### Visual Inspection
- [ ] Parameters section is clear and complete
- [ ] Output access pattern is obvious
- [ ] Examples use realistic values
- [ ] Format is consistent across all nodes
- [ ] No confusing "none" messages

### LLM Planner Testing
- [ ] Generate workflow with file operations
- [ ] Generate workflow with multiple API calls
- [ ] Generate workflow with LLM processing
- [ ] Verify all params are properly set
- [ ] Verify template variables are used correctly

### Edge Cases
- [ ] Node with no parameters
- [ ] Node with only exclusive params
- [ ] Node with complex nested structure
- [ ] Node with many parameters
- [ ] Workflow section unchanged

## Success Criteria

### Must Pass
- [x] All existing tests pass (with updates for new format)
- [x] No breaking changes to other systems
- [x] Context is clearer than before
- [x] Examples are valid JSON
- [x] Format is consistent

### Should Pass
- [x] LLM generates better workflows
- [x] Reduced confusion about parameters
- [x] No performance degradation
- [ ] Documentation examples still valid

### Nice to Have
- [ ] Improved example value generation
- [ ] Better handling of optional params
- [ ] Clearer type information

## Rollback Testing

If issues occur:
1. Revert context_builder.py
2. Run test suite - should pass immediately
3. No data migration needed
4. No user workflows affected

## Test Output Archive

Save test outputs for future reference:
```bash
# Before implementation
python capture_current_output.py > before_output.txt

# After implementation
python validate_format.py > after_output.txt

# Diff for documentation
diff -u before_output.txt after_output.txt > format_changes.diff
```

## Continuous Validation

Add to CI/CD:
```python
# test_context_format.py
def test_context_format_requirements():
    """Ensure context format meets requirements."""
    context = build_planning_context(...)

    # Required format elements
    assert "**Parameters** (all go in params field):" in context
    assert "**Outputs** (access as" in context
    assert "**Example usage**:" in context

    # Forbidden old format elements
    assert "**Inputs**:" not in context
    assert "**Parameters**: none" not in context
    assert '"${key}"' not in context  # No unhelpful placeholders
```

## Summary

Testing focuses on validating that the new format:
1. Eliminates confusion about parameters vs inputs
2. Shows clear examples for every node
3. Makes namespaced access patterns obvious
4. Maintains backward compatibility
5. Improves LLM workflow generation

The changes are isolated to presentation only, making testing straightforward and rollback simple.