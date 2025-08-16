# Task 9: Automatic Namespacing - Task Review

## Executive Summary

**Problem**: Multiple nodes of the same type writing to the same shared store keys caused data collisions and overwrites.

**Solution**: Implemented automatic namespacing that isolates each node's outputs under `shared[node_id][key]` while maintaining backward compatibility through proxy patterns.

**Impact Level**: 🔴 **CRITICAL** - Fundamentally changes how data flows between nodes

**Status**: ✅ Complete and enabled by default in MVP

**Implementation Size**: ~200 lines of new code

## Quick Impact Assessment

If your task involves any of these, you MUST understand this change:
- ✅ Creating workflows or nodes
- ✅ Template variable resolution
- ✅ Shared store access patterns
- ✅ Node testing strategies
- ✅ Workflow compilation
- ✅ Planner/generator systems

## The Paradigm Shift

### Before (Flat Shared Store)
```python
# Node1 writes
shared["response"] = "data1"
# Node2 writes
shared["response"] = "data2"  # OVERWRITES data1!
# Node3 reads
data = shared["response"]  # Only sees data2
```

### After (Namespaced Store)
```python
# Node1 writes (appears to write to "response")
shared["node1"]["response"] = "data1"  # Actually namespaced
# Node2 writes
shared["node2"]["response"] = "data2"  # No collision!
# Node3 reads via template
data = "$node1.response"  # Explicitly references node1's data
```

## System-Wide Changes Matrix

| Component | File(s) | Change Type | Impact |
|-----------|---------|-------------|---------|
| **Runtime** | `src/pflow/runtime/namespaced_store.py` | NEW | Core proxy implementation |
| **Runtime** | `src/pflow/runtime/namespaced_wrapper.py` | NEW | Node wrapper for namespacing |
| **Compiler** | `src/pflow/runtime/compiler.py` | MODIFIED | Applies namespace wrapping |
| **IR Schema** | `src/pflow/core/ir_schema.py` | MODIFIED | Added `enable_namespacing` field |
| **Templates** | `src/pflow/runtime/template_resolver.py` | UNCHANGED* | Already supported paths |
| **Node Wrapper** | `src/pflow/runtime/node_wrapper.py` | MODIFIED | Logging improvements |
| **CLI** | `src/pflow/cli/main.py` | MINOR | Linting fixes only |
| **Tests** | Multiple test files | MODIFIED | Updated for namespaced outputs |

*Template resolver already supported `$node.key` syntax, no changes needed

## Core Implementation Components

### 1. NamespacedSharedStore (`namespaced_store.py`)
```python
class NamespacedSharedStore:
    """Transparent proxy that namespaces all writes"""

    def __setitem__(self, key, value):
        # Writes go to namespace
        self._parent[self._namespace][key] = value

    def __getitem__(self, key):
        # Reads check namespace first, then root
        if key in self._parent[self._namespace]:
            return self._parent[self._namespace][key]
        if key in self._parent:
            return self._parent[key]
        raise KeyError(...)
```

**Key Design Decisions:**
- Writes ALWAYS go to namespace (isolation)
- Reads check namespace THEN root (backward compatibility)
- CLI inputs remain at root level (accessible to all)
- Full dict protocol support (iteration, keys, values)

### 2. NamespacedNodeWrapper (`namespaced_wrapper.py`)
```python
class NamespacedNodeWrapper:
    """Wraps nodes to provide namespaced shared store"""

    def _run(self, shared):
        namespaced_shared = NamespacedSharedStore(shared, self._node_id)
        return self._inner_node._run(namespaced_shared)
```

**Integration Pattern:**
- Wraps AFTER TemplateAwareNodeWrapper
- Transparent to nodes (no code changes needed)
- Preserves all PocketFlow operators (>>, -)

### 3. Compiler Integration
```python
# In _instantiate_nodes() around line 274
if enable_namespacing:  # Defaults to True
    node_instance = NamespacedNodeWrapper(node_instance, node_id)
```

**Wrapper Order (Critical):**
1. Base Node
2. TemplateAwareNodeWrapper (if templates)
3. NamespacedNodeWrapper (if enabled)

## Integration Requirements for Other Tasks

### For Tasks Creating Nodes
- Nodes require NO changes - namespacing is transparent
- Fallback pattern still works: `shared.get("key") or self.params.get("key")`
- Nodes are unaware they're namespaced

### For Tasks Creating Workflows
Workflows MUST use explicit template references:
```json
{
  "nodes": [
    {"id": "fetch1", "type": "github-get-issue", "params": {"issue": "123"}},
    {"id": "analyze", "type": "llm", "params": {
      "prompt": "Analyze: $fetch1.issue_data.title"  // MUST use node_id prefix
    }}
  ]
}
```

### For Tasks Modifying Compiler
- Check if wrapping order matters for your feature
- Namespace wrapping happens AFTER template wrapping
- Access pattern: `shared[node_id][key]` not `shared[key]`

### For Tasks Writing Tests
```python
# Old test pattern (BROKEN with namespacing)
assert shared["output"] == "expected"

# New test pattern (REQUIRED)
assert shared["node_id"]["output"] == "expected"
```

### For Planner/Generator Tasks
The planner MUST:
1. Generate unique node IDs (already does)
2. Use `$node_id.output` pattern for references
3. Set `"enable_namespacing": true` (or omit, it's default)

## Workflow Migration Patterns

### Simple Pipeline (No Changes Needed)
If nodes don't share output keys, no changes required:
```json
// Still works - different output keys
{"id": "read", "type": "read-file"},
{"id": "process", "type": "transform"}
```

### Multiple Same Type (MUST Update)
```json
// BEFORE (broken - collision)
{
  "nodes": [
    {"id": "api1", "type": "api-call"},
    {"id": "api2", "type": "api-call"},
    {"id": "combine", "type": "combine"}  // Which response?
  ]
}

// AFTER (working - explicit references)
{
  "nodes": [
    {"id": "api1", "type": "api-call"},
    {"id": "api2", "type": "api-call"},
    {"id": "combine", "type": "combine", "params": {
      "data1": "$api1.response",
      "data2": "$api2.response"
    }}
  ]
}
```

## Testing Strategies

### Unit Testing Nodes
```python
def test_node_with_namespacing():
    node = MyNode()
    # Create namespaced store for testing
    shared = {}
    namespaced = NamespacedSharedStore(shared, "test_node")

    # Run node with namespaced store
    node._run(namespaced)

    # Verify output is namespaced
    assert shared["test_node"]["output_key"] == expected
```

### Integration Testing Workflows
```python
def test_workflow():
    workflow = {
        "ir_version": "0.1.0",
        "enable_namespacing": true,  # Explicit (though default)
        "nodes": [...],
    }

    flow = compile_ir_to_flow(workflow, registry)
    shared = {}
    flow.run(shared)

    # Check namespaced structure
    assert "node1" in shared
    assert "node2" in shared
```

## Performance Implications

- **Memory**: One additional dict level per node (~negligible)
- **CPU**: One additional dict lookup per read/write (~O(1))
- **Overall**: No measurable performance impact

## Known Limitations and Edge Cases

### Limitations
1. No array indexing in templates (e.g., `$node.items[0]` not supported)
2. Namespace names are fixed to node IDs (not configurable)
3. Cannot read across namespaces without templates

### Edge Cases Handled
- Self-reading nodes work (check own namespace first)
- CLI inputs remain at root (backward compatible)
- Empty workflows don't crash
- Missing template variables show warnings but continue

## Debugging Guide

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Inspect Shared Store Structure
```python
# After workflow execution
import json
print(json.dumps(shared, indent=2))
# Shows namespace structure
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Missing required 'content'" | Node expects flat key | Add param: `"content": "$source_node.content"` |
| Template not resolved | Wrong node ID | Check exact node ID in workflow |
| Data not found | Looking at root instead of namespace | Use `$node_id.key` pattern |

## Relationship to Other Tasks

### Dependencies (Tasks We Depend On)
- **Task 18**: Template Variable System (path support for `$node.key`)
- **Task 4**: IR-to-PocketFlow Compiler (base compilation)
- **Task 6**: JSON IR Schema (structure for enable_namespacing)

### Dependents (Tasks That Depend on Us)
- **Task 17**: Natural Language Planner (must generate namespaced references)
- **Task 11**: File nodes (tests updated for namespacing)
- **Task 20**: Nested workflows (inherit namespacing behavior)
- **Future**: Any task creating workflows or nodes

### Potential Conflicts
- Tasks assuming flat shared store structure
- Tests checking `shared["key"]` directly
- Workflow generators not using node ID prefixes

## Configuration and Control

### Enable/Disable Namespacing
```json
{
  "ir_version": "0.1.0",
  "enable_namespacing": false,  // Explicitly disable (not recommended)
  "nodes": [...]
}
```

### Default Behavior
- MVP: Enabled by default (`true`)
- Can be disabled per workflow if needed
- No global configuration (per-workflow only)

## Impact on System Architecture

### Philosophical Shift
- **Before**: Shared blackboard model - implicit connections
- **After**: Explicit dataflow model - declared connections
- **Result**: More powerful, debuggable, and collision-free workflows

### Enables New Patterns
1. Multiple API aggregation
2. Parallel processing of same node type
3. Complex workflow composition
4. Clear data lineage tracking

### Future Extensibility
- Could add namespace aliasing
- Could add cross-namespace search
- Could add namespace visualization
- Foundation for distributed execution

## Implementation Checklist

### Completed ✅
- [x] Core proxy implementation (NamespacedSharedStore)
- [x] Node wrapper implementation (NamespacedNodeWrapper)
- [x] Compiler integration
- [x] IR schema update
- [x] Test updates for namespacing
- [x] Documentation
- [x] Integration tests
- [x] Make check fixes

### Not Implemented (Future)
- [ ] Namespace aliasing/renaming
- [ ] Cross-namespace search patterns
- [ ] Visualization tools
- [ ] Performance optimizations

## Code Examples for Common Patterns

### Pattern 1: Multiple Data Sources
```json
{
  "nodes": [
    {"id": "source1", "type": "fetch-data", "params": {"url": "$url1"}},
    {"id": "source2", "type": "fetch-data", "params": {"url": "$url2"}},
    {"id": "source3", "type": "fetch-data", "params": {"url": "$url3"}},
    {"id": "aggregate", "type": "combine", "params": {
      "data": ["$source1.data", "$source2.data", "$source3.data"]
    }}
  ]
}
```

### Pattern 2: Pipeline with Preservation
```json
{
  "nodes": [
    {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
    {"id": "backup", "type": "write-file", "params": {
      "file_path": "backup.txt",
      "content": "$read.content"
    }},
    {"id": "process", "type": "transform", "params": {
      "input": "$read.content"
    }}
  ]
}
```

### Pattern 3: Conditional Processing
```json
{
  "nodes": [
    {"id": "check", "type": "validate", "params": {"data": "$input"}},
    {"id": "process_valid", "type": "process", "params": {
      "data": "$check.valid_data"
    }},
    {"id": "process_invalid", "type": "error-handler", "params": {
      "error": "$check.error"
    }}
  ]
}
```

## Critical Warnings for Implementers

⚠️ **DO NOT** assume flat shared store structure
⚠️ **DO NOT** write tests with `shared["key"]` access
⚠️ **DO NOT** generate workflows without node ID prefixes
⚠️ **ALWAYS** use `$node_id.key` for inter-node references
⚠️ **ALWAYS** test with multiple instances of same node type
⚠️ **ALWAYS** check namespace structure when debugging

## Summary for AI Agents

When implementing your task:

1. **If creating nodes**: No changes needed, namespacing is transparent
2. **If creating workflows**: Use `$node_id.output` pattern for all references
3. **If modifying compiler**: Respect wrapper order, namespace wrapping is last
4. **If writing tests**: Expect `shared[node_id][key]` structure
5. **If generating workflows**: Always use explicit node ID references

This change is fundamental to pflow's architecture and enables powerful multi-node workflows that were previously impossible. Embrace the explicit dataflow model - it's more powerful and debuggable than implicit connections.

---
*Task 9 implementation complete. This change is enabled by default in the MVP.*