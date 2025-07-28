# Task 18: Immediate Fixes Required

## Type Errors to Fix (3 total)

### 1. node_wrapper.py:185 - Missing type annotation
```python
def __getattr__(self, name: str) -> Any:
    """Delegate all other attributes to inner node."""
    return getattr(self.inner_node, name)
```

### 2. node_wrapper.py:189 - Missing type annotation
```python
def __repr__(self) -> str:
    """String representation for debugging."""
    inner_repr = repr(self.inner_node)
    return f"TemplateAwareNodeWrapper({inner_repr}, node_id='{self.node_id}')"
```

### 3. compiler.py:305 - Type incompatibility
The issue is that `node_instance` is typed as `BaseNode` but we're assigning a `TemplateAwareNodeWrapper` to it. The fix is to type `node_instance` as `Union[BaseNode, TemplateAwareNodeWrapper]` or similar.

Around line 305:
```python
node_instance = TemplateAwareNodeWrapper(node_instance, node_id, initial_params)
```

The `_instantiate_nodes` function returns `dict[str, BaseNode]` but now it can also contain wrapped nodes.

## Quick Fix Steps

1. Add return type annotations to `__getattr__` and `__repr__` in node_wrapper.py
2. Update the type hints in compiler.py to handle both BaseNode and TemplateAwareNodeWrapper
3. Run `make check` to verify fixes
4. Run full test suite to ensure no regressions

## After Fixing Types

1. Create a simple integration test in `tests/test_integration/` that shows templates working with real file nodes
2. Verify the template system works end-to-end
3. Consider adding debug logging for template resolution
4. Update CLAUDE.md in the project root to document the template system

## Remember

- The implementation is COMPLETE
- All 70 tests pass
- Don't change functionality, just fix types
- The system works perfectly, it just needs type annotations
