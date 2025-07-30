# Task 20: WorkflowExecutor Implementation Review

## Quick Reference Card

**What It Does**: Enables workflows to execute other workflows as sub-components with parameter mapping and storage isolation.

**Node Type**: `"workflow"` or `"pflow.runtime.workflow_executor"`
**Implementation**: `src/pflow/runtime/workflow_executor.py`
**Test Location**: `tests/test_runtime/test_workflow_executor/`
**Examples**: `examples/nested/`

**30-Second Usage**:
```json
{
  "id": "run_sub_workflow",
  "type": "workflow",
  "params": {
    "workflow_ref": "path/to/workflow.json",
    "param_mapping": {"input": "$parent_value"},
    "output_mapping": {"result": "parent_result"}
  }
}
```

## Executive Summary

### What This Enables
- Workflow composition and reusability
- Modular workflow design with proper isolation
- Dynamic workflow loading and execution
- Safe parameter passing between workflow levels

### Critical Architectural Decision
WorkflowExecutor was moved from `nodes/` to `runtime/` because it's infrastructure, not a user-facing computation node. This maintains conceptual clarity: users think of workflows as compositions, not as nodes.

### Critical Integration Points
- **Compiler**: Modified to auto-inject registry for workflow nodes
- **Registry**: Passed via `__registry__` parameter
- **Template Resolver**: Used for parameter mapping
- **Storage System**: Four isolation modes implemented

### Breaking Changes
None. The implementation is purely additive.

### Security Model
- Default "mapped" storage mode prevents data leakage
- Path traversal protection for workflow_ref
- Circular dependency detection
- Maximum nesting depth enforcement

## System Architecture Impact

```
┌─────────────────┐
│   User writes   │
│   workflow.json │
└────────┬────────┘
         │
         v
┌─────────────────┐     ┌──────────────────┐
│    Compiler     │────>│ WorkflowExecutor │
│ (injects reg.)  │     │  (runtime/)      │
└─────────────────┘     └────────┬─────────┘
         │                       │
         │                       v
         │              ┌──────────────────┐
         └─────────────>│  Sub-Workflow    │
                        │   Compilation    │
                        └──────────────────┘

Key: Registry injection happens transparently during compilation
```

## Integration Points Matrix

### 1. Compiler Integration (`src/pflow/runtime/compiler.py`)

**Modification Location**: Line 311-316 in `_instantiate_nodes()`
```python
# Special case: inject registry for workflow executor
if node_type == "workflow" or node_type == "pflow.runtime.workflow_executor":
    params = params.copy()
    params["__registry__"] = registry
```

**Why**: WorkflowExecutor needs registry to compile sub-workflows
**When to use**: Any system node needing access to registry
**Impact**: Transparent to users, no API changes

### 2. Registry Access Pattern

**How WorkflowExecutor Gets Registry**:
```python
# In WorkflowExecutor.exec()
registry = self.params.get("__registry__")
if not isinstance(registry, Registry):
    registry = None

# Pass to sub-workflow compilation
sub_flow = compile_ir_to_flow(
    workflow_ir,
    registry=registry,
    initial_params=child_params,
    validate=True
)
```

### 3. Template Resolution Integration

**Parameter Mapping**:
```python
def _resolve_parameter_mappings(self, param_mapping: dict[str, Any],
                               shared: dict[str, Any]) -> dict[str, Any]:
    resolved = {}
    for child_param, parent_value in param_mapping.items():
        if isinstance(parent_value, str) and TemplateResolver.has_templates(parent_value):
            resolved[child_param] = TemplateResolver.resolve_string(parent_value, context)
        else:
            resolved[child_param] = parent_value
    return resolved
```

### 4. Storage System Integration

**Storage Mode Creation**:
```python
def _create_child_storage(self, parent_shared: dict[str, Any],
                         storage_mode: str, prep_res: dict[str, Any]) -> dict[str, Any]:
    if storage_mode == "mapped":
        child_storage = prep_res["child_params"].copy()
    elif storage_mode == "isolated":
        child_storage = {}
    elif storage_mode == "scoped":
        # Filter parent storage by prefix
    elif storage_mode == "shared":
        child_storage = parent_shared  # Same reference!
```

## API Specification

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `workflow_ref` | str | None | Path to workflow JSON file |
| `workflow_ir` | dict | None | Inline workflow definition |
| `param_mapping` | dict | {} | Maps parent values to child params |
| `output_mapping` | dict | {} | Maps child outputs to parent |
| `storage_mode` | str | "mapped" | Storage isolation strategy |
| `max_depth` | int | 10 | Maximum nesting depth |
| `error_action` | str | "error" | Action to return on error |

### Storage Modes Behavior

| Mode | Child Sees | Parent Sees | Use When |
|------|------------|-------------|----------|
| `mapped` | Only mapped params | No changes | Default - safe isolation |
| `isolated` | Empty storage | No changes | Running untrusted workflows |
| `scoped` | Filtered by prefix | No changes | Namespace organization |
| `shared` | Everything | All changes | Parent-child cooperation |

### Error Types

```python
# Validation Errors
ValueError("Either 'workflow_ref' or 'workflow_ir' must be provided")
ValueError("Circular workflow reference detected: A -> B -> A")

# Execution Errors
RecursionError("Maximum workflow nesting depth (10) exceeded")
FileNotFoundError("Workflow file not found: /path/to/workflow.json")
TypeError("Workflow must be a JSON object")

# Context-Aware Errors
WorkflowExecutionError(
    message="Sub-workflow execution failed",
    workflow_path=["main.json", "sub.json"],
    original_error=original_exception
)
```

## Implementation Patterns

### Pattern 1: System Node Compiler Injection

**Problem**: System nodes need access to runtime resources (registry, config, etc.)

**Solution**: Compiler injects dependencies transparently
```python
# In compiler
if is_system_node(node_type):
    params["__registry__"] = registry
    params["__config__"] = config
```

**Applicable To**: MCP nodes, remote execution nodes, monitoring nodes

### Pattern 2: Reserved Namespace Pattern

**Problem**: System metadata conflicts with user data

**Solution**: Reserve namespace prefix
```python
RESERVED_KEY_PREFIX = "_pflow_"

# System keys
shared["_pflow_depth"] = current_depth
shared["_pflow_stack"] = execution_stack
shared["_pflow_workflow_file"] = workflow_path
```

**Applicable To**: Any feature needing metadata in shared storage

### Pattern 3: Test Node Self-Reference

**Problem**: Integration tests need custom nodes but imports fail

**Solution**: Define nodes in test file, reference test module
```python
# In test file
class TestNode(BaseNode):
    def exec(self, prep_res):
        return "test"

# In test registry
registry_data = {
    "test_node": {
        "module": "tests.test_integration",  # THIS FILE
        "class_name": "TestNode",
        "file_path": __file__
    }
}
```

## DO NOT Section - Critical Warnings

### DO NOT Place WorkflowExecutor in nodes/
- **Why**: It's infrastructure, not a user computation
- **Impact**: Would appear in planner, confusing users
- **Exception**: None

### DO NOT Use "shared" Storage Mode Without Justification
- **Why**: Child can modify ALL parent data
- **Risk**: Data corruption, security issues
- **When OK**: Parent-child designed together, trust established

### DO NOT Skip Registry Injection
- **Why**: Sub-workflow compilation will fail
- **How to verify**: Check params["__registry__"] exists
- **Fix**: Ensure compiler modification is present

### DO NOT Allow Unrestricted Nesting
- **Why**: Stack overflow, resource exhaustion
- **Default**: max_depth=10
- **Monitor**: Check _pflow_depth in shared storage

## Testing Guide

### How to Test Nodes Using WorkflowExecutor

1. **Create Test Registry**:
```python
@pytest.fixture
def test_registry(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry = Registry(registry_path)

    # Define test nodes IN THIS FILE
    registry_data = {
        "my_test_node": {
            "module": __name__,
            "class_name": "MyTestNode",
            "file_path": __file__
        }
    }
    registry.save(registry_data)
    return registry
```

2. **Test Storage Isolation**:
```python
def test_storage_isolation(test_registry):
    workflow_ir = {
        "nodes": [{
            "id": "sub",
            "type": "workflow",
            "params": {
                "workflow_ir": sub_workflow,
                "storage_mode": "isolated"
            }
        }]
    }

    flow = compile_ir_to_flow(workflow_ir, registry=test_registry)
    shared = {"secret": "should_not_leak"}
    flow.run(shared)

    # Verify secret didn't leak to child
```

3. **Test Error Propagation**:
```python
def test_error_context(test_registry):
    # Create failing sub-workflow
    # Verify error includes full path
    # Check original exception preserved
```

## Common Integration Scenarios

### Scenario 1: Planner Generating Nested Workflows
```python
# Planner can now generate:
{
    "nodes": [{
        "id": "reuse_analyzer",
        "type": "workflow",
        "params": {
            "workflow_ref": "~/.pflow/workflows/analyze.json",
            "param_mapping": {"data": "$input"}
        }
    }]
}
```

### Scenario 2: Conditional Sub-Workflow Execution
```python
{
    "edges": [
        {"from": "check", "to": "complex_workflow", "action": "complex"},
        {"from": "check", "to": "simple_workflow", "action": "simple"}
    ]
}
```

### Scenario 3: Error Recovery
```python
{
    "params": {
        "error_action": "fallback"
    },
    "edges": [
        {"from": "workflow_node", "to": "success", "action": "default"},
        {"from": "workflow_node", "to": "error_handler", "action": "fallback"}
    ]
}
```

## Files Modified

### Core Implementation
- `src/pflow/runtime/workflow_executor.py` - Main implementation (NEW)
- `src/pflow/runtime/compiler.py` - Registry injection (lines 311-316)
- `src/pflow/core/exceptions.py` - WorkflowExecutionError class (NEW)

### Tests
- `tests/test_runtime/test_workflow_executor/` - All tests (NEW)
  - `test_workflow_executor.py` - Basic tests
  - `test_workflow_executor_comprehensive.py` - 26 spec criteria
  - `test_integration.py` - Full execution tests

### Documentation
- `docs/reference/node-reference.md` - Removed WorkflowNode section
- `docs/features/nested-workflows.md` - Usage guide (NEW)
- `examples/nested/` - Example workflows (NEW)

### No Changes To
- Registry system
- Template resolver
- Node discovery
- CLI interface
- Existing nodes

## Performance Considerations

### Memory Usage
- Each nested workflow creates new storage dictionary
- "shared" mode has zero overhead
- "mapped" mode copies only specified keys

### Compilation Overhead
- Sub-workflows compiled on each execution
- No caching in current implementation
- Future: Consider workflow compilation cache

### Recursion Limits
- Default max_depth=10 prevents stack issues
- Each level adds ~3 entries to shared storage
- Python recursion limit still applies

## Future Enhancements

### Planned (v2.0)
1. Workflow compilation caching
2. Async workflow execution
3. Progress reporting for nested workflows
4. Workflow registry integration

### Possible Extensions
1. Parallel sub-workflow execution
2. Conditional workflow loading
3. Remote workflow execution
4. Workflow versioning support

## Troubleshooting Playbook

### "Module not found" in Tests
**Symptom**: `ModuleNotFoundError: No module named 'test.module'`
**Cause**: Registry points to non-existent module
**Fix**: Define test nodes in test file, use `__name__` as module

### "No registry available"
**Symptom**: `TypeError: 'NoneType' object has no attribute 'load'`
**Cause**: Registry not injected by compiler
**Fix**: Verify node type matches in compiler check

### "Circular reference detected"
**Symptom**: `ValueError: Circular workflow reference detected`
**Debug**: Check `_pflow_stack` in shared storage
**Fix**: Redesign workflow dependencies

### "Maximum depth exceeded"
**Symptom**: `RecursionError: Maximum workflow nesting depth exceeded`
**Debug**: Check `_pflow_depth` value
**Fix**: Increase max_depth or flatten workflow structure

## Conclusion

WorkflowExecutor successfully enables workflow composition while maintaining architectural clarity through its placement in runtime/. The implementation prioritizes safety (default "mapped" storage), usability (transparent registry injection), and debuggability (comprehensive error context).

Key achievement: Workflows can now be building blocks without becoming conceptual nodes, preserving the user's mental model while enabling powerful composition patterns.
