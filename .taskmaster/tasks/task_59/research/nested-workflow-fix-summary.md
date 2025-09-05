# Critical Fix: Disabled Workflow-as-Node Confusion Until Task 59

## The Problem We Discovered

The LLM was generating **invalid workflows that would fail at runtime** by trying to use workflows as if they were nodes:

```json
{
  "type": "generate-changelog",  // ❌ This is a WORKFLOW name, not a NODE type!
  "params": {"limit": "20"}
}
```

When tested:
```
❌ FAILED: compiler: Node type 'generate-changelog' not found in registry
Available node types: git-checkout, github-list-issues, llm, write-file, etc.
```

## Root Cause

The ComponentBrowsingNode was including saved workflows in the planning context sent to WorkflowGeneratorNode. The LLM saw these workflows and incorrectly assumed it could use them as building blocks (nodes), but pflow doesn't support nested workflow execution yet.

## The Fix Applied

### 1. ComponentBrowsingNode Changes (`src/pflow/planning/nodes.py`)

**Before**: Passed workflows to the planning context
```python
planning_context = build_planning_context(
    selected_node_ids=exec_res["node_ids"],
    selected_workflow_names=exec_res["workflow_names"],  # ❌ Workflows included
    ...
)
```

**After**: Disabled workflow inclusion
```python
planning_context = build_planning_context(
    selected_node_ids=exec_res["node_ids"],
    selected_workflow_names=[],  # ✅ Disabled until nested workflows supported
    ...
)
```

### 2. Clear Workflows from Results

Added code to actively clear any workflows the LLM might select:
```python
if result.get("workflow_names"):
    logger.info(
        f"ComponentBrowsingNode: Ignoring {len(result['workflow_names'])} workflows "
        "(nested workflows not supported yet)",
        extra={"phase": "exec", "ignored_workflows": result["workflow_names"]},
    )
    result["workflow_names"] = []  # Clear workflows
```

## Why This Matters

1. **Prevents Runtime Failures**: The LLM will no longer generate workflows that would crash at compilation
2. **Clear Feature Boundary**: Until Task 59 implements nested workflow execution, workflows cannot be used as nodes
3. **Test Accuracy**: Tests now validate that generated workflows use only valid node types

## Impact on Tests

### Before Fix
- Test expected 3 nodes (including invalid `generate-changelog` workflow-as-node)
- Workflow would pass initial validation but FAIL at runtime compilation

### After Fix
- LLM must generate workflows using only registered node types
- Test expectations need updating to expect 5+ primitive nodes instead of 3
- Generated workflows will actually run successfully

## Future: Task 59 - Nested Workflow Support

When Task 59 is implemented, it will:
1. Allow workflows to be executed as nodes within other workflows
2. Enable powerful workflow composition
3. Re-enable the workflow context in ComponentBrowsingNode

Until then, the system correctly prevents the LLM from generating invalid workflows.

## Test Updates Needed

1. **test_changelog_verbose_complete_pipeline**: Update to expect 5+ nodes (not 3)
2. **Any tests checking browsed_components**: Expect empty `workflow_names` array
3. **Generator tests**: Ensure only valid node types are used

## Verification

To verify the fix works:
```python
# This should now FAIL to compile (as it should):
workflow = {
    "nodes": [{"type": "generate-changelog", "params": {}}]
}
# Error: Node type 'generate-changelog' not found

# This should SUCCEED:
workflow = {
    "nodes": [
        {"type": "github-list-issues", "params": {"limit": "20"}},
        {"type": "llm", "params": {"prompt": "Generate changelog"}},
        {"type": "write-file", "params": {"file_path": "CHANGELOG.md"}}
    ]
}
```

## Summary

This fix prevents a critical issue where the LLM was hallucinating a feature (workflow composition) that doesn't exist yet. The system now correctly constrains the LLM to use only valid node types, ensuring generated workflows will actually run.