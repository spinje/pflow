# Task 11 Implementation Guide - File Nodes

This guide contains critical discoveries from Task 4 (IR Compiler) implementation that are essential for implementing Task 11 (file nodes).

## Critical Discoveries for Node Implementation

### 1. Node Class Structure Pattern

From our mock nodes in the integration tests, we discovered the minimal working pattern for PocketFlow nodes:

```python
from typing import Any
from pocketflow import BaseNode  # CRITICAL: Use BaseNode, not Node!

class ReadFileNode(BaseNode):
    """Read file contents into shared storage.

    Interface:
        Reads: file_path (str) - Path to file to read
        Writes: content (str) - File contents
    """

    name = 'read-file'  # Explicit name attribute (recommended)

    def __init__(self):
        super().__init__()
        # No need to initialize params - PocketFlow handles this

    def prep(self, shared_storage: dict[str, Any]) -> Any:
        """Validate inputs and prepare for execution."""
        # This is where you validate required inputs
        if "file_path" not in shared_storage:
            raise ValueError("Missing required input: file_path")
        return None  # Can return data for exec phase

    def exec(self, prep_result: Any) -> Any:
        """Execute main logic."""
        # Access shared_storage through self.shared
        file_path = self.shared["file_path"]

        # Perform the actual work
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            return content
        except FileNotFoundError:
            raise ValueError(f"File not found: {file_path}")

    def post(self, shared_storage: dict[str, Any], prep_result: Any, exec_result: Any) -> str:
        """Store results and return transition action."""
        # Store the result in shared storage
        shared_storage["content"] = exec_result
        return None  # Default transition (can return "error", "success", etc.)
```

### 2. Critical Import and Inheritance

**MUST USE**: `from pocketflow import BaseNode`
- ❌ DO NOT USE: `from pocketflow import Node`
- The registry scanner (Task 5) specifically looks for `BaseNode` inheritance
- This was a critical discovery that caused test failures initially

### 3. Node Naming Convention

Task 5's scanner expects one of these approaches:

**Option A - Explicit name attribute (RECOMMENDED):**
```python
class ReadFileNode(BaseNode):
    name = 'read-file'  # Explicit name
```

**Option B - Automatic kebab-case conversion:**
```python
class ReadFileNode(BaseNode):
    # No name attribute - scanner converts to 'read-file'
    pass
```

### 4. Shared Storage Access Pattern

PocketFlow provides different interfaces in different methods:

```python
def prep(self, shared_storage: dict[str, Any]) -> Any:
    # Use parameter 'shared_storage' here
    value = shared_storage.get("key")

def exec(self, prep_result: Any) -> Any:
    # Use 'self.shared' here (set by PocketFlow)
    value = self.shared["key"]

def post(self, shared_storage: dict[str, Any], prep_result: Any, exec_result: Any) -> str:
    # Use parameter 'shared_storage' here
    shared_storage["result"] = exec_result
```

### 5. Error Handling Pattern

Implement "fail fast on missing required inputs" in the `prep()` method:

```python
def prep(self, shared_storage: dict[str, Any]) -> Any:
    """Validate all required inputs are present."""
    required_keys = ["file_path"]  # List all required inputs
    missing = [k for k in required_keys if k not in shared_storage]

    if missing:
        raise ValueError(f"Missing required inputs: {', '.join(missing)}")

    # Optional: validate types or values
    file_path = shared_storage["file_path"]
    if not isinstance(file_path, str):
        raise TypeError(f"file_path must be a string, got {type(file_path).__name__}")

    return None
```

### 6. Parameter Handling Priority

Nodes should check shared storage first, then fall back to params:

```python
def prep(self, shared_storage: dict[str, Any]) -> Any:
    # Priority: shared storage > node params
    file_path = shared_storage.get("file_path") or self.params.get("file_path")

    if not file_path:
        raise ValueError("file_path must be provided in shared storage or params")
```

Note: The compiler passes template variables (like `$file_path`) through unchanged.

### 7. Module Structure

The compiler expects this exact structure:

```
src/pflow/nodes/file/
├── __init__.py          # Can be empty
├── read_file.py         # Contains ReadFileNode class
├── write_file.py        # Contains WriteFileNode class
├── copy_file.py         # Contains CopyFileNode class
├── move_file.py         # Contains MoveFileNode class
└── delete_file.py       # Contains DeleteFileNode class
```

Each file should contain one node class.

### 8. Testing Pattern

From our integration tests, here's the pattern for testing nodes:

```python
def test_read_file_node():
    """Test ReadFileNode functionality."""
    from pflow.nodes.file.read_file import ReadFileNode

    # Create node instance
    node = ReadFileNode()

    # Prepare shared storage
    shared = {"file_path": "test.txt"}

    # Create test file
    with open("test.txt", "w") as f:
        f.write("test content")

    try:
        # Simulate PocketFlow execution
        prep_result = node.prep(shared)
        node.shared = shared  # PocketFlow sets this before exec()
        exec_result = node.exec(prep_result)
        node.post(shared, prep_result, exec_result)

        # Verify results
        assert "content" in shared
        assert shared["content"] == "test content"
    finally:
        # Cleanup
        import os
        os.remove("test.txt")
```

### 9. Safety Checks for Destructive Operations

For write/move/delete operations, implement safety checks:

```python
class DeleteFileNode(BaseNode):
    name = 'delete-file'

    def prep(self, shared_storage: dict[str, Any]) -> Any:
        """Validate inputs and check safety."""
        if "file_path" not in shared_storage:
            raise ValueError("Missing required input: file_path")

        file_path = shared_storage["file_path"]

        # Safety check - don't delete system files
        if file_path.startswith("/sys") or file_path.startswith("/etc"):
            raise ValueError(f"Cannot delete system file: {file_path}")

        # In interactive mode, could prompt for confirmation
        # For MVP, we can check for a 'force' flag
        if not shared_storage.get("force", False):
            # Check if file exists and would be deleted
            import os
            if os.path.exists(file_path):
                raise ValueError(
                    f"Deleting {file_path} requires confirmation. "
                    "Set shared['force'] = True to proceed."
                )

        return file_path  # Pass to exec
```

### 10. Natural Interface Pattern

Follow the "natural interface" pattern specified in the task:

```python
# read-file node
# Input: shared['file_path']
# Output: shared['content']

# write-file node
# Input: shared['content'] + shared['file_path']
# Output: None (side effect: file written)

# copy-file node
# Input: shared['source_path'] + shared['dest_path']
# Output: None (side effect: file copied)

# move-file node
# Input: shared['source_path'] + shared['dest_path']
# Output: None (side effect: file moved)

# delete-file node
# Input: shared['file_path']
# Output: None (side effect: file deleted)
```

## Common Pitfalls to Avoid

1. **Wrong Base Class**: Using `Node` instead of `BaseNode` - this will break registry discovery
2. **Missing name attribute**: Forgetting to set explicit name or ensure class name converts properly
3. **Wrong shared storage access**: Using `shared_storage` in exec() or `self.shared` in prep()/post()
4. **Not failing fast**: Doing validation in exec() instead of prep()
5. **Ignoring template variables**: Trying to resolve `$variables` instead of passing them through

## Integration Points

### Registry Discovery
Your nodes will be automatically discovered if they:
- Are in .py files under `src/pflow/nodes/`
- Inherit from `pocketflow.BaseNode`
- Have proper docstrings with Interface section

### Compiler Integration
The compiler will:
- Import your module dynamically using `importlib`
- Verify BaseNode inheritance
- Call `set_params()` if params exist in IR
- Wire nodes using PocketFlow's `>>` operator

### Example IR that will use your nodes:
```json
{
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {"file_path": "input.txt"}
    },
    {
      "id": "write",
      "type": "write-file",
      "params": {"file_path": "output.txt"}
    }
  ],
  "edges": [
    {"from": "read", "to": "write"}
  ]
}
```

## Quick Implementation Checklist

- [ ] Create `src/pflow/nodes/file/` directory
- [ ] Implement each node class inheriting from `BaseNode`
- [ ] Add explicit `name` attribute to each class
- [ ] Implement prep() with input validation
- [ ] Implement exec() with main logic
- [ ] Implement post() to store results
- [ ] Add safety checks for destructive operations
- [ ] Write comprehensive docstrings with Interface section
- [ ] Create tests following the testing pattern
- [ ] Verify nodes are discovered by registry scanner

## Final Notes

Remember: These nodes are part of the MVP's "Simple Platform Nodes" - keep them focused on single operations, use natural interfaces, and fail fast on missing inputs. The goal is to have reliable, composable building blocks for workflows.
