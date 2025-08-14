# Task 9: Implement Shared Store Collision Detection and Proxy Mapping

## ID
9

## Title
Implement Shared Store Collision Detection and Proxy Mapping

## Description
Implement automatic namespacing to prevent output collisions when multiple nodes of the same type write to the shared store. This feature isolates each node's outputs in its own namespace, enabling workflows to use multiple instances of the same node type without data being overwritten. Originally planned as manual proxy mappings, the implementation evolved to automatic namespacing after discovering it was simpler and more powerful.

## Status
done

## Dependencies
- Task 18: Template Variable System - Namespacing leverages the existing template path resolution (`$node.key`) for accessing namespaced outputs
- Task 6: Define JSON IR Schema - Extended schema to include `enable_namespacing` field

## Priority
high

## Details
The shared store collision problem was a fundamental limitation preventing workflows from using multiple instances of the same node type. This task evolved from the original proxy mapping approach to automatic namespacing after deep architectural analysis.

### Core Problem Being Solved
When multiple nodes of the same type write to the same shared store key, data gets overwritten:
```json
{
  "nodes": [
    {"id": "fetch1", "type": "github-get-issue", "params": {"issue": "123"}},
    {"id": "fetch2", "type": "github-get-issue", "params": {"issue": "456"}}
  ]
}
// Result: fetch2 overwrites fetch1's issue_data
```

### Evolution of the Solution
1. **Original Plan**: Manual proxy mappings requiring explicit configuration
2. **Enhancement**: Automatic proxy mapping with collision detection
3. **Final Solution**: Automatic namespacing - simpler and more powerful

### Why Automatic Namespacing Won
After extensive analysis comparing three approaches (manual proxy, automatic proxy, automatic namespacing), we determined automatic namespacing was superior because:
- **Simplicity**: ~200 lines vs ~500 for proxy mappings
- **LLM-friendly**: One consistent pattern (`$node_id.output`)
- **No magic**: Explicit data flow, easy to debug
- **Complete solution**: Prevents all collisions automatically

### Architectural Insight
This implementation fundamentally changes pflow's data model:
- **Before**: Shared blackboard where nodes communicate implicitly (PocketFlow model)
- **After**: Isolated namespaces with explicit routing through template variables
- **Trade-off**: Lost implicit connections, gained explicit collision-free data flow

This is a conscious architectural decision that makes pflow diverge from PocketFlow's philosophy but better suited for LLM workflow generation.

## Implementation Requirements

### Core Components
1. **NamespacedSharedStore** (`src/pflow/runtime/namespaced_store.py`)
   - Proxy dictionary that redirects writes to `shared[node_id][key]`
   - Reads check namespace first, then fall back to root level
   - Full dict protocol support for template resolution context

2. **NamespacedNodeWrapper** (`src/pflow/runtime/namespaced_wrapper.py`)
   - Wraps nodes to provide namespaced shared store view
   - Transparent delegation of all node operations
   - Proper handling of PocketFlow operators (`>>`, `-`)

3. **Compiler Integration** (`src/pflow/runtime/compiler.py`)
   - Detect `enable_namespacing` flag in workflow IR
   - Apply namespace wrapper after template wrapper
   - Wrapper composition: Node → TemplateAwareNodeWrapper → NamespacedNodeWrapper

4. **Schema Update** (`src/pflow/core/ir_schema.py`)
   - Add `enable_namespacing` boolean field
   - Default to `true` for MVP (breaking change accepted)

### Storage Structure
With namespacing enabled:
```python
shared = {
  "node1": {
    "output": "data1"    # node1's isolated outputs
  },
  "node2": {
    "output": "data2"    # node2's isolated outputs
  },
  "stdin": "user input"  # CLI inputs remain at root
}
```

### Template Variable Usage
Reference namespaced outputs using node ID prefix:
```json
{
  "params": {
    "content": "$node1.output",     // Access node1's output
    "comparison": "$node2.output"   // Access node2's output
  }
}
```

## Key Design Decisions

### 1. Default-On for MVP
Made the controversial but correct decision to enable namespacing by default:
- No backward compatibility concerns (no production users)
- Forces explicit data flow from the start
- Eliminates entire class of collision bugs
- Simplifies planner logic (no collision avoidance needed)

### 2. Wrapper Composition Order
NamespacedNodeWrapper wraps TemplateAwareNodeWrapper:
- Ensures namespace isolation happens first
- Template resolution sees namespaced view
- Clean separation of concerns

### 3. Root Level Fallback
Reads check namespace first, then root:
- CLI inputs remain accessible at root level
- Provides migration path for future
- Maintains some implicit behavior for special cases

### 4. Full Dict Protocol
Implemented complete dictionary interface on NamespacedSharedStore:
- Required for `dict(shared)` in template resolution
- Enables transparent proxying
- Prevents breaking existing code patterns

### 5. Full Parameterization Reality
Accepted that with namespacing, all inter-node communication goes through params:
- Shared store reads always miss (wrong namespace)
- Forces use of template variables
- Makes data flow explicit and traceable

## Test Strategy

### Unit Tests (`tests/test_runtime/test_namespacing.py`)
- **test_namespacing_prevents_collisions**: Verify multiple same-type nodes don't collide
- **test_namespacing_disabled_by_default**: Test opt-out flag works (though default is on)
- **test_namespacing_with_cli_inputs**: Ensure root-level CLI data remains accessible

### Integration Test Updates
- Updated workflows to use explicit template references (`$node.output`)
- Fixed assumptions about flat shared store structure
- Added namespacing-aware assertions

### Edge Cases Tested
- Dictionary protocol operations (iteration, keys, values)
- Copy operations (prevented infinite recursion)
- Template resolution with namespaced context
- Mixed namespaced and root-level data access

### Performance Validation
- Minimal overhead: O(1) for get/set operations
- One additional dictionary level per node
- ~50-100 lines of wrapper code per node execution

## Impact and Benefits

### Immediate Benefits
1. **No More Collisions**: Multiple instances of same node type work perfectly
2. **Clear Data Lineage**: Easy to trace which node produced which data
3. **Powerful Workflows**: No artificial limitations on node usage
4. **Better Debugging**: Clear visualization of data flow in shared store

### Planner Improvements
- Can use multiple instances of same node type freely
- No collision avoidance logic needed
- Simpler workflow generation with consistent pattern
- Natural node ID usage for namespacing

### Developer Experience
- Explicit data flow easier to understand
- No surprising overwrites
- Clear error messages when connections missing
- Simplified mental model (despite more configuration)

## Future Considerations
- Visualization tools could show namespace structure
- Migration tools for old workflows (if needed)
- Performance optimizations for large namespaces
- Namespace-aware debugging output
- Potential for namespace inheritance in nested workflows

## Lessons Learned
1. **Simple solutions often win**: Namespacing was simpler than proxy mappings
2. **Explicit is better than implicit**: For LLM generation especially
3. **Breaking changes can be good**: Default-on forced better architecture
4. **Full analysis pays off**: Comparing three approaches led to best solution
5. **Architecture evolves**: OK to diverge from PocketFlow when it makes sense