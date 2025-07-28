# Shared Store Analysis: PocketFlow vs pflow Nested Workflows

## PocketFlow's Native Behavior

In pure PocketFlow, the shared store works like this:

1. **Single Shared Instance**: There is ONE shared store dictionary that is passed by reference to all nodes and flows
   ```python
   shared = {}  # Created once
   flow.run(shared)  # Same dict passed through entire execution
   ```

2. **No Isolation**: When you use a Flow as a node, it receives the SAME shared store:
   ```python
   inner_flow = Flow(start=some_node)
   outer_flow = Flow(start=inner_flow)
   outer_flow.run(shared)  # inner_flow sees the same 'shared' dict
   ```

3. **Direct Mutation**: All nodes directly read/write to the same dictionary:
   ```python
   # From test_flow_composition.py:
   class NumberNode(Node):
       def prep(self, shared_storage):
           shared_storage['current'] = self.number  # Direct write

   class AddNode(Node):
       def prep(self, shared_storage):
           shared_storage['current'] += self.number  # Direct mutation
   ```

## The Problem for pflow

This creates several issues for pflow's use case:

1. **Key Collisions**: If parent and child workflows both use `shared["data"]`, they overwrite each other
2. **No Encapsulation**: Child workflows can read/modify ANY parent data
3. **Template Variables**: Child workflows need different initial parameters but share the same storage
4. **Debugging Nightmare**: Hard to track which workflow modified what data

## pflow's Proposed Solution

The WorkflowNode adapter provides **configurable storage isolation**:

### Storage Modes

1. **"mapped" (default)** - Most controlled:
   ```python
   # Child gets a NEW dict with only mapped inputs
   child_shared = {"__workflow_context__": [...]}
   child_shared.update(resolved_params)  # Only what's explicitly mapped
   ```
   - Child workflow gets a **new dictionary instance**
   - Only contains values explicitly mapped via `param_mapping`
   - Complete isolation from parent

2. **"isolated"** - Complete isolation:
   ```python
   # Child gets empty storage
   child_shared = {"__workflow_context__": [...]}
   ```
   - Child gets a **new, empty dictionary**
   - No access to parent data at all

3. **"scoped"** - Namespace isolation:
   ```python
   # Child sees filtered view of parent storage
   child_shared = {}
   for key, value in parent_shared.items():
       if key.startswith(prefix):
           child_shared[key.removeprefix(prefix)] = value
   ```
   - Child gets a **new dictionary** with filtered parent data
   - Only keys with specific prefix are visible

4. **"shared"** - PocketFlow native behavior:
   ```python
   # Direct reference - same as PocketFlow
   child_shared = parent_shared
   ```
   - Child uses **same dictionary instance** as parent
   - Full PocketFlow compatibility but no isolation

## Key Differences Summary

| Aspect | PocketFlow | pflow (mapped/isolated/scoped) | pflow (shared mode) |
|--------|------------|--------------------------------|-------------------|
| Dictionary Instance | Same for all | New per child workflow | Same for all |
| Parent Data Access | Full access | Controlled/None | Full access |
| Key Collision Risk | High | None | High |
| Parameter Passing | Via shared store | Via param_mapping | Via shared store |
| Output Extraction | Manual | Via output_mapping | Manual |
| Debugging | Hard | Easy (isolated contexts) | Hard |

## Example Comparison

### PocketFlow Native:
```python
# Parent and child share same storage
shared = {"user_id": 123, "data": "parent data"}
inner_flow = Flow(start=ProcessNode())  # Can read/write ALL of shared
outer_flow = Flow(start=inner_flow)
outer_flow.run(shared)
# shared might now be {"user_id": 123, "data": "child overwrote this", "new_key": "child added"}
```

### pflow with Isolation:
```python
# Parent workflow
shared = {"user_id": 123, "data": "parent data"}

# Child workflow via WorkflowNode
workflow_node = WorkflowNode()
workflow_node.set_params({
    "workflow_ref": "child.json",
    "param_mapping": {
        "user": "$user_id"  # Child sees this as shared["user"], not shared["user_id"]
    },
    "output_mapping": {
        "result": "child_result"  # Child's shared["result"] -> parent's shared["child_result"]
    },
    "storage_mode": "mapped"
})

# After execution:
# Parent shared: {"user_id": 123, "data": "parent data", "child_result": "..."}
# Child had its own shared: {"user": 123, "result": "..."}
```

## Why This Matters

1. **Workflow Reusability**: Child workflows don't need to know parent's key structure
2. **Composition Safety**: Can't accidentally break parent by overwriting keys
3. **Clear Data Flow**: Explicit input/output mappings document data dependencies
4. **Testing**: Can test workflows in isolation with known inputs
5. **Debugging**: Each workflow's data is separate and traceable

## Conclusion

PocketFlow's shared store design is perfect for single-level workflows where all nodes cooperate on the same data structure. However, for nested workflows in pflow, we need isolation to:
- Prevent key collisions
- Enable workflow reuse with different parameters
- Maintain clear data flow boundaries
- Support the "Plan Once, Run Forever" philosophy

The WorkflowNode adapter provides this isolation while still allowing full PocketFlow compatibility via "shared" mode when needed.
