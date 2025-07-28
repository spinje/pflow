# Implementation Changes Summary

Based on the architectural decision to move WorkflowNode to the runtime layer, here are the exact changes needed:

## Changes Required

### 1. File Structure Changes

**Delete**:
- `src/pflow/nodes/workflow/` (entire directory)
- `tests/test_nodes/test_workflow/` (entire directory)

**Create**:
- `src/pflow/runtime/workflow_executor.py`
- `tests/test_runtime/test_workflow_executor.py`

### 2. Code Changes

#### A. Rename Class
In the moved file, change:
```python
class WorkflowNode(BaseNode):
```
To:
```python
class WorkflowExecutor(BaseNode):
```

#### B. Update Compiler (`src/pflow/runtime/compiler.py`)

In the `import_node_class()` function, add at the beginning:
```python
def import_node_class(node_type: str, registry: Registry) -> type:
    """Import a node class by type from the registry.

    Args:
        node_type: The type identifier for the node
        registry: The registry containing node metadata

    Returns:
        The node class

    Raises:
        ValueError: If node type not found in registry
        ImportError: If module import fails
        AttributeError: If class not found in module
        TypeError: If class doesn't inherit from BaseNode
    """
    # Special handling for workflow execution
    if node_type == "workflow":
        from pflow.runtime.workflow_executor import WorkflowExecutor
        return WorkflowExecutor

    # Normal node lookup continues below...
    nodes = registry.load()
    # ... rest of existing implementation unchanged
```

### 3. Test Updates

#### A. Move and Update Tests
- Move test files from `tests/test_nodes/test_workflow/` to `tests/test_runtime/`
- Update imports to use `pflow.runtime.workflow_executor`
- Remove any registry-related tests (WorkflowExecutor won't be in registry)

#### B. Add Compiler Test
In `tests/test_runtime/test_compiler.py`, add:
```python
def test_workflow_type_special_handling():
    """Test that 'workflow' type returns WorkflowExecutor directly."""
    from pflow.runtime.workflow_executor import WorkflowExecutor

    # Don't need registry for workflow type
    result = import_node_class("workflow", None)
    assert result is WorkflowExecutor
```

### 4. Documentation Updates

#### A. Update `docs/reference/node-reference.md`
Remove the WorkflowNode section entirely (it's no longer a user-facing node).

#### B. Create `docs/reference/workflow-execution.md`
New document explaining how workflows can execute other workflows using `type: "workflow"` in IR.

#### C. Update Task 20 Spec
Add note that WorkflowExecutor is a runtime component, not a discoverable node.

### 5. What DOESN'T Change

- The IR format remains the same - still use `type: "workflow"`
- All parameters remain the same
- The functionality remains identical
- The WorkflowExecutor implementation stays the same (just moved and renamed)

## Verification Steps

After making changes:

1. **Run scanner**: `python -m pflow registry update`
2. **Check registry**: Verify "workflow" doesn't appear in `~/.pflow/registry.json`
3. **Test planner**: Ensure workflow doesn't show in node discovery
4. **Run tests**: All workflow execution tests should still pass
5. **Test execution**: Workflows with `type: "workflow"` should still work

## Summary

This is primarily a reorganization - the core functionality doesn't change. We're just moving WorkflowNode to a more appropriate location (runtime/) and adding a small special case in the compiler to handle it. This preserves the conceptual model where workflows are compositions, not building blocks.
