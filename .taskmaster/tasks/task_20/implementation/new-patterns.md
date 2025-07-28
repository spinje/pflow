# New Patterns Discovered in Task 20

## 1. System Node Compiler Injection Pattern

**Problem**: System nodes (like WorkflowNode) need access to system resources (like the registry) but shouldn't require users to manually pass them.

**Solution**: Modify the compiler to automatically inject system dependencies for specific node types.

```python
# In compiler.py:_instantiate_nodes()
if node_type == "pflow.nodes.workflow":
    params = params.copy()
    params["__registry__"] = registry
```

**Benefits**:
- Transparent to users
- Ensures system nodes always have required resources
- No breaking changes to workflow format

**When to use**:
- Nodes that need registry access
- Nodes that need runtime context
- Future: MCP nodes, remote execution nodes

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
