# Deep Analysis of Remaining Test Failures

## The Two Failing Tests

1. `test_mixed_node_types` - Integration test checking category grouping
2. `test_discovery_context_large_registry_performance` - Performance test with 1000 nodes

## Root Cause Analysis

### The Data Flow Problem

The tests mock `_process_nodes` to return nodes with explicit "category" fields:
```python
{
    "file-reader": {
        "category": "File Operations",  # ← Test expects this to be used
        "description": "...",
        "inputs": [...],
        # BUT NO registry_info field!
    }
}
```

But `_group_nodes_by_category` expects this structure:
```python
{
    "file-reader": {
        "description": "...",
        "registry_info": {  # ← Function looks here
            "module": "test.file",
            "file_path": "..."
        }
    }
}
```

### The Design Disconnect

The tests reveal a design assumption mismatch:
- **Tests assume**: If a node has a "category" field, it will be used
- **Implementation does**: Infers category from module path/node name, ignores "category" field

## Why These Tests Are Valuable

1. **Integration Testing**: They verify the full context building flow works correctly
2. **Category Organization**: They ensure nodes are properly grouped for the planner
3. **Performance**: They ensure the system scales to large registries
4. **Flexibility**: They test that different node sources can provide categories

## The Solution Options

### Option 1: Fix the Tests (Not Recommended)
Make tests provide proper `registry_info` structure:
- ❌ Makes tests more complex
- ❌ Doesn't address the underlying design issue
- ❌ Tests become tightly coupled to implementation details

### Option 2: Respect Explicit Categories (Recommended) ✅
Enhance `_group_nodes_by_category` to use "category" field if present:
- ✅ Makes system more flexible
- ✅ Allows explicit category assignment
- ✅ Backward compatible
- ✅ Simplifies testing
- ✅ Future-proof for nodes that know their category

## Implementation Plan

1. **Enhance _group_nodes_by_category**:
   - Check if node has explicit "category" field first
   - Fall back to inference if not present
   - This is a simple 3-line change

2. **Benefits**:
   - Tests will pass without modification
   - System becomes more flexible
   - MCP nodes could declare categories explicitly
   - Future node types can self-categorize

## Code Change

```python
def _group_nodes_by_category(nodes: dict[str, dict]) -> dict[str, list[str]]:
    for node_type, node_data in nodes.items():
        # NEW: Check for explicit category first
        if "category" in node_data:
            category = node_data["category"]
        else:
            # EXISTING: Infer from registry info
            registry_info = node_data.get("registry_info", node_data)
            # ... rest of inference logic
```

This is the cleanest solution that respects both explicit categories and inference.