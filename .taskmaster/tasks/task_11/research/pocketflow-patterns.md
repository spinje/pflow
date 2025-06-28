# PocketFlow Patterns for Task 11: Implement read-file and write-file nodes

## Task Context

- **Goal**: Create basic file I/O nodes following single-purpose design
- **Dependencies**: Task 9 (natural key patterns)
- **Constraints**: Simple operations only - streaming deferred to v2.0

## Overview

Basic file I/O nodes are fundamental building blocks for pflow workflows. These nodes demonstrate the core node implementation pattern that all other nodes will follow.

## Core Patterns from Advanced Analysis

### Pattern: Content Truncation for Performance
**Found in**: YouTube summarizer, Codebase Knowledge
**Why It Applies**: Prevent memory issues with large files

```python
def truncate_content(content: str, max_length: int = 50000) -> str:
    """Truncate content for downstream processing"""
    if len(content) <= max_length:
        return content

    # Smart truncation - try to break at paragraph
    truncated = content[:max_length]
    last_newline = truncated.rfind('\n')
    if last_newline > max_length * 0.8:  # If we have a good break point
        truncated = truncated[:last_newline]

    return truncated + "\n\n[Content truncated...]"

# In ReadFileNode
def post(self, shared, prep_res, exec_res):
    # Option to truncate for performance
    if self.params.get("truncate", False):
        max_length = self.params.get("max_length", 50000)
        shared["content"] = truncate_content(exec_res, max_length)
        shared["content_truncated"] = True
    else:
        shared["content"] = exec_res

    shared["file_path"] = prep_res["file_path"]
    shared["file_size"] = len(exec_res)  # Original size
    return "default"
```

### Pattern: Selective File Loading
**Found in**: Codebase Knowledge (filters by extension)
**Why It Applies**: Don't load files that won't be processed

```python
def should_read_file(file_path: str, filters: dict) -> bool:
    """Determine if file should be read based on filters"""
    # Extension filter
    allowed_extensions = filters.get("extensions", [])
    if allowed_extensions:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in allowed_extensions:
            return False

    # Size filter
    max_size = filters.get("max_size", float('inf'))
    if os.path.getsize(file_path) > max_size:
        return False

    # Binary detection
    if filters.get("text_only", True):
        with open(file_path, 'rb') as f:
            chunk = f.read(512)
            if b'\0' in chunk:  # Likely binary
                return False

    return True
```

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

### Anti-Pattern: Generic Key Names
**Found in**: Early implementations
**Issue**: Causes collisions and confusion
**Alternative**: Always use descriptive keys like "file_content", "config_file_path"

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

## Integration Points

### Connection to Task 8 (Shell Pipes)
File nodes can read from stdin instead:
```python
# In ReadFileNode.prep()
if "stdin" in shared and not shared.get("file_path"):
    # Use stdin as content source
    return {"content": shared["stdin"], "from_stdin": True}
```

### Connection to Task 9 (Natural Keys)
All keys follow natural naming:
```python
# Good: Descriptive, specific
shared["config_file_path"] = "/etc/config.json"
shared["config_content"] = "{...}"
shared["readme_content"] = "# Project\n..."

# Bad: Generic, collision-prone
shared["path"] = "/etc/config.json"  # Which path?
shared["content"] = "{...}"         # Content of what?
```

### Connection to Task 23 (Tracing)
File operations add trace metadata:
```python
def post(self, shared, prep_res, exec_res):
    shared["content"] = exec_res
    # Trace-friendly metadata
    shared["_file_metadata"] = {
        "path": prep_res["file_path"],
        "size": len(exec_res),
        "truncated": self.params.get("truncate", False)
    }
```

## Minimal Test Case

```python
# Save as test_file_patterns.py
import tempfile
import os
from pocketflow import Node

class MinimalReadFileNode(Node):
    """Read file following all patterns"""

    def prep(self, shared):
        # Natural key, shared store priority
        file_path = shared.get("file_path") or self.params.get("file_path")

        if not file_path and "stdin" in shared:
            # Shell pipe support
            return {"use_stdin": True}

        if not file_path:
            raise ValueError("Missing required input: file_path")

        return {"file_path": file_path}

    def exec(self, prep_res):
        if prep_res.get("use_stdin"):
            return None  # Content already in shared["stdin"]

        with open(prep_res["file_path"], 'r') as f:
            content = f.read()

        # Performance: truncate if requested
        if self.params.get("truncate"):
            max_len = self.params.get("max_length", 50000)
            if len(content) > max_len:
                content = content[:max_len] + "\n[Truncated]"

        return content

    def post(self, shared, prep_res, exec_res):
        if prep_res.get("use_stdin"):
            # Already have content
            shared["file_content"] = shared["stdin"]
            shared["from_stdin"] = True
        else:
            # Natural, specific key
            shared["file_content"] = exec_res
            shared["source_file"] = prep_res["file_path"]

        return "default"

def test_natural_keys_and_performance():
    # Create test file
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("A" * 100000)  # 100KB file
        test_file = f.name

    # Test 1: Natural keys
    node = MinimalReadFileNode()
    shared = {"file_path": test_file}
    node.run(shared)

    assert "file_content" in shared  # Natural key
    assert "source_file" in shared   # Descriptive
    assert len(shared["file_content"]) == 100000

    # Test 2: Performance truncation
    node_truncate = MinimalReadFileNode()
    node_truncate.set_params({"truncate": True, "max_length": 1000})
    shared2 = {"file_path": test_file}
    node_truncate.run(shared2)

    assert len(shared2["file_content"]) < 1100  # Truncated
    assert "[Truncated]" in shared2["file_content"]

    # Test 3: stdin support
    node_stdin = MinimalReadFileNode()
    shared3 = {"stdin": "From pipe!"}
    node_stdin.run(shared3)

    assert shared3["file_content"] == "From pipe!"
    assert shared3["from_stdin"] == True

    # Cleanup
    os.unlink(test_file)
    print("✓ File patterns validated")

if __name__ == "__main__":
    test_natural_keys_and_performance()
```

## Summary

Task 11's file nodes demonstrate all core pflow patterns:

1. **Natural Key Naming** - "file_content" not "content"
2. **Performance Awareness** - Truncation and filtering options
3. **Shell Integration** - stdin as alternative to file reading
4. **Single Purpose** - Each node does ONE file operation
5. **Fail Fast** - Clear validation in prep()

These patterns ensure file operations are efficient, debuggable, and composable.
