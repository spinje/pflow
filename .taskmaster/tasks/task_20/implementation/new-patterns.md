# New Patterns Discovered in Task 20

## 1. Runtime Component with Compiler Special Handling Pattern (UPDATED)

**Problem**: Some functionality (like workflow execution) is infrastructure, not a user-facing node, but needs to be invoked via IR.

**Solution**: Place the component in `runtime/` and add special handling in the compiler.

```python
# In compiler.py:import_node_class()
# Special handling for workflow execution
if node_type == "workflow" or node_type == "pflow.runtime.workflow_executor":
    from pflow.runtime.workflow_executor import WorkflowExecutor
    return WorkflowExecutor

# Also in _instantiate_nodes() for registry injection
if node_type == "workflow" or node_type == "pflow.runtime.workflow_executor":
    params = params.copy()
    params["__registry__"] = registry
```

**Note**: This pattern was refined during implementation. Originally WorkflowNode was in `nodes/workflow/`, but was refactored to `runtime/workflow_executor.py` to maintain architectural clarity.

**Benefits**:
- Keeps infrastructure separate from user features
- Prevents confusion in planner/registry
- Maintains clean conceptual model
- Transparent to users (they just use `type: "workflow"`)
- Infrastructure doesn't appear as selectable nodes

**When to use**:
- Infrastructure that executes via IR but isn't a user-facing node
- Future: Batch processors, async executors, remote runners

## 2. Storage Isolation Modes Pattern

**Problem**: Sub-workflows need controlled access to parent data for security and clarity.

**Solution**: Implement multiple storage modes with clear semantics:

```python
storage_modes = {
    "mapped": "Only explicitly mapped parameters",
    "isolated": "Completely empty storage",
    "scoped": "Filtered view with prefix",
    "shared": "Direct reference (dangerous)"
}
```

**Benefits**:
- Explicit data flow control
- Security by default (mapped mode)
- Flexibility when needed

**When to use**:
- Any node that executes untrusted code
- Nodes that spawn sub-processes
- Multi-tenant scenarios

## 3. Test Node Self-Reference Pattern

**Problem**: Integration tests fail when registry points to non-existent modules.

**Solution**: Define test nodes in the test file and reference the test module:

```python
# In test file
class TestNode(BaseNode):
    def exec(self, prep_res):
        return "test"

@pytest.fixture
def mock_registry():
    return {
        "test-node": {
            "module": "tests.test_module",  # THIS file
            "class_name": "TestNode",        # Defined above
            "file_path": __file__
        }
    }
```

**Benefits**:
- Self-contained tests
- No external dependencies
- Actually importable by compiler

**When to use**: All integration tests that need custom node behavior

## 4. Execution Context Tracking Pattern

**Problem**: Nested execution needs debugging context and cycle detection.

**Solution**: Use reserved namespace for execution metadata:

```python
RESERVED_PREFIX = "_pflow_"
context_keys = {
    f"{RESERVED_PREFIX}depth": current_depth,
    f"{RESERVED_PREFIX}stack": execution_stack,
    f"{RESERVED_PREFIX}workflow_file": current_file
}
```

**Benefits**:
- No collision with user data
- Available throughout execution
- Enables powerful debugging

**When to use**:
- Any recursive/nested execution
- Debugging and tracing features
- Audit trails

## 5. Architectural Separation Pattern (NEW)

**Problem**: Not all components that execute via IR should be user-visible nodes.

**Solution**: Maintain clear separation between user features and infrastructure:
- `nodes/` = User-facing features (appear in planner)
- `runtime/` = Internal infrastructure (hidden from users)

**Example**: WorkflowExecutor lives in `runtime/` because it's infrastructure for executing workflows, not a building block users combine.

**Conceptual Model**:
- **Nodes** = Building blocks (ingredients like flour, eggs)
- **Workflows** = Compositions (recipes like cake)
- **Runtime Components** = Infrastructure (oven that bakes)

**Benefits**:
- Clean conceptual model for users
- Planner output remains focused
- Infrastructure can evolve independently
- Prevents user confusion

**When to use**:
- Any component that's internal machinery
- Features that shouldn't appear in planner
- Infrastructure that supports user features

**Implementation Note**: This pattern was applied retroactively to WorkflowNode, moving it from `nodes/workflow/` to `runtime/workflow_executor.py` after recognizing it was infrastructure, not a user-facing building block.
