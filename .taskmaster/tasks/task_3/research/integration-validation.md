# Integration Validation Guide

## Overview

Task 3 validates that all core components work together. This document details what to verify and how.

## Component Integration Map

```
CLI (main.py)
    ↓ --file flag
JSON File (hello_workflow.json)
    ↓ json.loads()
IR Schema (ir_schema.py)
    ↓ validate_ir()
Registry (registry.json)
    ↓ load()
Compiler (compiler.py)
    ↓ compile_ir_to_flow()
    ├── Dynamic Import (importlib)
    ├── Node Instantiation
    └── Flow Construction (>>)
Shared Store (dict)
    ↓
Node Execution (prep/exec/post)
    ↓
Success Output
```

## Integration Points to Validate

### 1. CLI → File Reading
```python
# Verify in main.py
def read_workflow_from_file(file_path: str) -> str:
    """Should handle all file reading errors gracefully."""
    # Test: Non-existent file
    # Test: Permission denied
    # Test: Non-UTF8 file
    # Test: Empty file
```

### 2. JSON Parsing → Schema Validation
```python
# The flow from raw JSON to validated IR
raw_json = '{"nodes": [...]}'
    ↓
ir_dict = json.loads(raw_json)  # Can throw JSONDecodeError
    ↓
validate_ir(ir_dict)  # Can throw ValidationError
    ↓
# ir_dict is now trusted
```

### 3. Registry → Compiler Integration
```python
# Registry provides metadata
registry_entry = {
    "module": "pflow.nodes.file.read_file",
    "class_name": "ReadFileNode"
}

# Compiler uses metadata for dynamic import
module = importlib.import_module(registry_entry["module"])
node_class = getattr(module, registry_entry["class_name"])
```

### 4. Compiler → PocketFlow Integration
```python
# Compiler builds native pocketflow objects
node_instances = {
    "read": ReadFileNode(),
    "write": WriteFileNode()
}

# Use pocketflow's >> operator
flow = node_instances["read"] >> node_instances["write"]
```

### 5. Shared Store Flow
```python
# Trace data through the workflow
shared = {}  # Empty initially

# After read-file executes
shared = {"content": "Hello, pflow!"}

# write-file reads this
content = shared["content"]  # Must exist!
```

## Validation Tests

### 1. Component Availability Test
```python
def test_all_components_available():
    """Ensure all required components exist."""
    # Can import all modules
    from pflow.cli import main
    from pflow.core import validate_ir
    from pflow.registry import Registry
    from pflow.runtime import compile_ir_to_flow

    # Registry exists
    assert Registry().registry_path.parent.exists()

    # Test nodes exist
    from pflow.nodes.file.read_file import ReadFileNode
    from pflow.nodes.file.write_file import WriteFileNode
```

### 2. Round-Trip Test
```python
def test_ir_round_trip():
    """Verify IR can go through full pipeline."""
    # Create IR
    ir = {
        "ir_version": "1.0",
        "nodes": [...],
        "edges": [...],
        "start_node": "read"
    }

    # Validate
    validate_ir(ir)

    # Compile
    registry = Registry()
    flow = compile_ir_to_flow(ir, registry)

    # Execute
    shared = {}
    flow.run(shared)

    # Verify shared store has data
    assert "content" in shared
```

### 3. Error Propagation Test
```python
def test_error_propagation():
    """Errors should bubble up with context."""

    # Test each layer catches and re-throws appropriately
    with pytest.raises(click.ClickException) as e:
        # Missing file
        result = runner.invoke(main, ["--file", "nonexistent.json"])
    assert "File not found" in str(e.value)

    with pytest.raises(click.ClickException) as e:
        # Invalid JSON
        result = runner.invoke(main, ["--file", "invalid.json"])
    assert "Invalid JSON" in str(e.value)
```

### 4. Registry Integration Test
```python
def test_registry_compiler_integration():
    """Registry and compiler must work together."""
    registry = Registry()

    # Registry has read-file
    assert "read-file" in registry.load()

    # Compiler can use registry metadata
    ir = {
        "nodes": [{"id": "r", "type": "read-file", "params": {}}]
    }

    # Should not throw
    flow = compile_ir_to_flow(ir, registry)
```

### 5. Shared Store Isolation Test
```python
def test_shared_store_isolation():
    """Each execution gets fresh shared store."""
    workflow = create_test_workflow()

    # First execution
    shared1 = {}
    flow.run(shared1)

    # Second execution
    shared2 = {}
    flow.run(shared2)

    # Stores are independent
    shared1["test"] = "modified"
    assert "test" not in shared2
```

## Integration Debugging Guide

### When CLI Can't Find Workflow File
```python
# Check: Is path absolute or relative?
# Debug: Print resolved path
file_path = Path(file).resolve()
click.echo(f"Looking for file at: {file_path}")
```

### When Registry Can't Find Node
```python
# Check: Is node registered?
registry = Registry()
all_nodes = registry.load()
click.echo(f"Available nodes: {list(all_nodes.keys())}")

# Check: Name mismatch?
# "read-file" vs "read_file" vs "ReadFile"
```

### When Import Fails
```python
# Check: Module path correct?
try:
    module = importlib.import_module(module_path)
except ImportError as e:
    click.echo(f"Failed to import {module_path}")
    click.echo(f"Python path: {sys.path}")
    click.echo(f"Error: {e}")
```

### When Shared Store Communication Fails
```python
# Add debug logging to nodes
class DebugNode(BaseNode):
    def prep(self, shared):
        click.echo(f"Prep: shared keys = {list(shared.keys())}")

    def post(self, shared, prep_res, exec_res):
        click.echo(f"Post: writing {exec_res} to shared")
```

## Performance Validation

### Measure Each Step
```python
import time

start = time.time()

# Load file
t1 = time.time()
workflow_json = read_file(file)

# Parse JSON
t2 = time.time()
ir = json.loads(workflow_json)

# Validate
t3 = time.time()
validate_ir(ir)

# Compile
t4 = time.time()
flow = compile_ir_to_flow(ir, registry)

# Execute
t5 = time.time()
flow.run(shared)

end = time.time()

# Report
print(f"File read: {t1-start:.3f}s")
print(f"JSON parse: {t2-t1:.3f}s")
print(f"Validation: {t3-t2:.3f}s")
print(f"Compilation: {t4-t3:.3f}s")
print(f"Execution: {t5-t4:.3f}s")
print(f"Total: {end-start:.3f}s")
```

Target: < 100ms for hello world

## Security Validation

### Dynamic Import Safety
```python
# Compiler should only import from allowed packages
ALLOWED_PACKAGES = ["pflow.nodes"]

def is_safe_import(module_path: str) -> bool:
    return any(module_path.startswith(pkg) for pkg in ALLOWED_PACKAGES)
```

### File Access Safety
```python
# Nodes should validate file paths
def validate_file_path(path: str) -> Path:
    resolved = Path(path).resolve()

    # Prevent directory traversal
    if ".." in path:
        raise ValueError("Path traversal not allowed")

    return resolved
```

## Success Metrics

Integration is validated when:

1. ✅ All components load without import errors
2. ✅ Hello workflow executes end-to-end
3. ✅ Errors at each layer provide clear context
4. ✅ Performance is acceptable (<100ms)
5. ✅ Security constraints are enforced
6. ✅ Tests cover all integration points

## Remember

Task 3 is about proving the architecture works. Every integration point is a potential failure point in production, so validate thoroughly now to save debugging time later.
