# PocketFlow Patterns for Task 11: Implement read-file and write-file nodes

## Overview

Basic file I/O nodes are fundamental building blocks for pflow workflows. These nodes demonstrate the core node implementation pattern that all other nodes will follow.

## Relevant Cookbook Examples

- `cookbook/pocketflow-node`: Core node implementation with error handling
- `cookbook/pocketflow-batch-node`: File processing patterns
- `cookbook/pocketflow-communication`: Shared store usage

## Patterns to Adopt

### Pattern: Basic Node Structure
**Source**: `cookbook/pocketflow-node/`
**Compatibility**: ✅ Direct
**Description**: Standard prep/exec/post lifecycle with error handling

**Original PocketFlow Pattern**:
```python
class SummarizeNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=1)

    def prep(self, shared):
        if "text" not in shared:
            raise ValueError("Missing required input: text")
        return shared["text"]

    def exec(self, text):
        # Pure business logic
        return summarize_text(text)

    def post(self, shared, prep_res, exec_res):
        shared["summary"] = exec_res
        return "default"
```

**Adapted for pflow file nodes**:
```python
from pocketflow import Node
import os

class ReadFileNode(Node):
    def __init__(self):
        super().__init__(max_retries=2, wait=0)

    def prep(self, shared):
        # Natural interface: check shared store first, then params
        file_path = shared.get("file_path") or self.params.get("file_path")

        if not file_path:
            raise ValueError("Missing required input: file_path")

        # Optional encoding parameter
        encoding = self.params.get("encoding", "utf-8")

        return {
            "file_path": file_path,
            "encoding": encoding
        }

    def exec(self, prep_res):
        # Pure file reading logic - retryable for transient errors
        file_path = prep_res["file_path"]
        encoding = prep_res["encoding"]

        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read()
        except FileNotFoundError:
            raise ValueError(f"File not found: {file_path}")
        except PermissionError:
            raise ValueError(f"Permission denied: {file_path}")

    def post(self, shared, prep_res, exec_res):
        # Natural output interface
        shared["content"] = exec_res
        shared["file_path"] = prep_res["file_path"]  # Preserve for reference
        return "default"
```

### Pattern: Shared Store Priority
**Source**: `cookbook/pocketflow-communication/` and architectural docs
**Compatibility**: ✅ Direct
**Description**: Always check shared store before params

**Implementation for all file nodes**:
```python
# Consistent pattern across all nodes
file_path = shared.get("file_path") or self.params.get("file_path")

# This enables:
# 1. Dynamic data from previous nodes (shared store)
# 2. Static configuration fallback (params)
# 3. CLI override capability
```

### Pattern: Natural Key Naming
**Source**: Multiple cookbook examples
**Compatibility**: ✅ Direct
**Description**: Use intuitive, self-documenting key names

**File operation conventions**:
```python
# Input keys
"file_path"     # Path to file
"content"       # File content
"source_path"   # For copy/move operations
"dest_path"     # Destination for copy/move

# Output keys
"content"       # Read file content
"written_file"  # Path of written file
"file_size"     # Size information
"file_exists"   # Existence check result
```

### Pattern: Complete File Node Set
**Source**: Simple nodes principle from MVP scope
**Compatibility**: ✅ Direct
**Description**: One node per file operation

**Implementation set**:
```python
class WriteFileNode(Node):
    def __init__(self):
        super().__init__(max_retries=2, wait=0)

    def prep(self, shared):
        content = shared.get("content")
        file_path = shared.get("file_path") or self.params.get("file_path")

        if content is None:
            raise ValueError("Missing required input: content")
        if not file_path:
            raise ValueError("Missing required input: file_path")

        mode = self.params.get("mode", "w")
        encoding = self.params.get("encoding", "utf-8")

        return {
            "content": content,
            "file_path": file_path,
            "mode": mode,
            "encoding": encoding
        }

    def exec(self, prep_res):
        # Create directory if needed
        dir_path = os.path.dirname(prep_res["file_path"])
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        # Write file
        with open(
            prep_res["file_path"],
            prep_res["mode"],
            encoding=prep_res["encoding"]
        ) as f:
            f.write(prep_res["content"])

        return prep_res["file_path"]

    def post(self, shared, prep_res, exec_res):
        shared["written_file"] = exec_res
        return "default"

class CopyFileNode(Node):
    def prep(self, shared):
        source = shared.get("source_path") or self.params.get("source_path")
        dest = shared.get("dest_path") or self.params.get("dest_path")

        if not source or not dest:
            raise ValueError("Missing required inputs: source_path and dest_path")

        return {"source": source, "dest": dest}

    def exec(self, prep_res):
        import shutil
        os.makedirs(os.path.dirname(prep_res["dest"]), exist_ok=True)
        shutil.copy2(prep_res["source"], prep_res["dest"])
        return prep_res["dest"]

    def post(self, shared, prep_res, exec_res):
        shared["copied_file"] = exec_res
        return "default"

class MoveFileNode(Node):
    # Similar to copy but using shutil.move

class DeleteFileNode(Node):
    def prep(self, shared):
        file_path = shared.get("file_path") or self.params.get("file_path")
        if not file_path:
            raise ValueError("Missing required input: file_path")

        # Safety check from params
        confirm = self.params.get("confirm_delete", True)
        return {"file_path": file_path, "confirm": confirm}

    def exec(self, prep_res):
        if prep_res["confirm"] and os.path.exists(prep_res["file_path"]):
            os.remove(prep_res["file_path"])
            return True
        return False

    def post(self, shared, prep_res, exec_res):
        shared["deleted"] = exec_res
        return "default"
```

### Pattern: Error Handling
**Source**: `cookbook/pocketflow-node/`
**Compatibility**: ✅ Direct
**Description**: Use built-in retry mechanism appropriately

**Best practices**:
```python
# Retryable errors (transient)
- Network timeouts
- Temporary file locks
- Resource temporarily unavailable

# Non-retryable errors (permanent)
- File not found
- Permission denied
- Invalid file path

# Implementation
def exec(self, prep_res):
    try:
        # File operation
    except FileNotFoundError:
        # Don't retry - file won't appear
        raise ValueError(f"File not found: {file_path}")
    except OSError as e:
        # Let pocketflow retry for transient OS errors
        raise
```

## Patterns to Avoid

### Pattern: Complex State Management
**Source**: Advanced examples
**Issue**: File nodes should be stateless
**Alternative**: Each execution is independent

### Pattern: Streaming/Chunking
**Source**: `pocketflow-batch-node`
**Issue**: Overcomplication for MVP
**Alternative**: Simple full-file operations, add streaming in v2.0

### Pattern: Async File Operations
**Source**: Async examples
**Issue**: Not in MVP scope
**Alternative**: Synchronous I/O is sufficient

## Implementation Guidelines

1. **Consistent interface**: All file nodes follow same pattern
2. **Clear error messages**: Help users debug file issues
3. **Safety first**: Confirm destructive operations
4. **Natural naming**: Use obvious key names
5. **Fail fast**: Validate inputs in prep()

## Testing Approach

```python
import tempfile
import pytest
from pflow.nodes.file import ReadFileNode, WriteFileNode

def test_read_write_flow():
    # Create temporary test file
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("Test content")
        test_file = f.name

    # Test read node
    read_node = ReadFileNode()
    shared = {"file_path": test_file}
    read_node.run(shared)

    assert shared["content"] == "Test content"
    assert shared["file_path"] == test_file

    # Test write node
    write_node = WriteFileNode()
    shared["file_path"] = "output.txt"
    write_node.run(shared)

    assert os.path.exists("output.txt")
    with open("output.txt") as f:
        assert f.read() == "Test content"

def test_missing_input():
    node = ReadFileNode()
    shared = {}  # No file_path

    with pytest.raises(ValueError, match="Missing required input"):
        node.run(shared)

def test_file_not_found():
    node = ReadFileNode()
    shared = {"file_path": "nonexistent.txt"}

    with pytest.raises(ValueError, match="File not found"):
        node.run(shared)
```

These file nodes establish the pattern for all pflow platform nodes: simple, focused, with natural interfaces.
