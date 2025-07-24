# Task 17 Dependency Changes

## Summary

Task 17's dependencies have been updated to reflect the removal of Task 15.

### Previous Dependencies
- Task 15: LLM API client (REMOVED)
- Task 16: Planning context builder
- Task 18: Prompt templates
- Task 19: Response parser

### Updated Dependencies
- Task 12: General LLM node (REPLACES Task 15)
- Task 16: Planning context builder
- Task 18: Prompt templates
- Task 19: Response parser

## Why This Change?

1. **Task 15 was redundant** - It attempted to create wrapper functions that added no value
2. **Task 12 provides the LLM node** - This is what the planner needs in the registry to generate workflows
3. **Direct usage is better** - The planner should use `llm` library directly, not through wrappers

## What This Means for Implementation

### The Planner Depends on Task 12 Because:
- It needs the LLM node to exist in the registry
- It can include `type: "llm"` nodes in generated workflows
- Users expect to use LLM functionality in their workflows

### The Planner Does NOT Use Task 12's Code:
- It imports `llm` library directly for its own LLM calls
- It doesn't instantiate or call the LLMNode class
- Internal implementation is separate from user-facing nodes

## Example Workflow Generation

When the planner generates a workflow, it might create:

```json
{
    "nodes": [
        {
            "id": "n1",
            "type": "read-file",
            "params": {"path": "document.txt"}
        },
        {
            "id": "n2",
            "type": "llm",  // <-- This requires Task 12 to exist
            "params": {
                "prompt": "Summarize this document: $content",
                "temperature": 0.3
            }
        }
    ],
    "edges": [
        {"from": "n1", "to": "n2", "action": "default"}
    ],
    "start_node": "n1"
}
```

The planner can only generate workflows with `"type": "llm"` if Task 12 has been implemented and registered.

## Implementation Notes

1. **Import Order**: Task 12 must be implemented before Task 17 can generate workflows using it
2. **Registry Check**: The planner should verify available nodes through the registry (Task 7)
3. **Error Handling**: If LLM node isn't available, provide clear error message

## Testing Considerations

```python
# Test that planner can generate workflows with LLM nodes
def test_planner_generates_llm_workflows():
    # Ensure LLM node is in registry
    registry = NodeRegistry()
    assert "llm" in registry.get_all_nodes()

    # Generate workflow
    ir = generate_workflow_ir("Summarize this file", node_context)

    # Verify LLM node is included
    llm_nodes = [n for n in ir["nodes"] if n["type"] == "llm"]
    assert len(llm_nodes) > 0
```

## Conclusion

The dependency change from Task 15 → Task 12 correctly reflects:
- What the planner needs (LLM node in registry)
- How it should be implemented (direct `llm` usage)
- Clear separation of concerns (internal vs user-facing)
