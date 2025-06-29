# Testing Strategy for Task 11 File Nodes

Based on the test patterns discovered during Task 4 implementation.

## Test Structure

Create `tests/test_file_nodes.py` with comprehensive coverage for all file operations.

## Key Testing Patterns from Task 4

### 1. Node Execution Simulation

PocketFlow sets `self.shared` before calling `exec()`, so tests must simulate this:

```python
def test_node_execution_pattern():
    node = SomeNode()
    shared = {"input": "value"}

    # Simulate PocketFlow's execution sequence
    prep_result = node.prep(shared)
    node.shared = shared  # CRITICAL: PocketFlow does this
    exec_result = node.exec(prep_result)
    action = node.post(shared, prep_result, exec_result)
```

### 2. Use Temporary Files

Always use `tempfile` for test files to ensure cleanup:

```python
import tempfile
import os

def test_with_temp_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.txt")
        # Test operations...
    # Files automatically cleaned up
```

### 3. Test Missing Inputs

Every node should fail fast in `prep()`:

```python
def test_missing_required_inputs():
    node = ReadFileNode()

    # Test missing file_path
    with pytest.raises(ValueError, match="Missing required input: file_path"):
        node.prep({})

    # Test with params fallback
    node.params = {"file_path": "test.txt"}
    result = node.prep({})  # Should not raise
```

### 4. Test Error Actions

Nodes should return appropriate actions on errors:

```python
def test_error_handling():
    node = ReadFileNode()
    shared = {"file_path": "/nonexistent/file.txt"}

    prep_result = node.prep(shared)
    node.shared = shared
    exec_result = node.exec(prep_result)
    action = node.post(shared, prep_result, exec_result)

    assert action == 'error'
    assert 'error' in shared
    assert "File not found" in shared['error']
```

## Complete Test Suite Structure

```python
"""Comprehensive tests for file nodes."""
import os
import tempfile
import pytest
from unittest.mock import patch, mock_open

from pflow.nodes.file.read_file import ReadFileNode
from pflow.nodes.file.write_file import WriteFileNode
from pflow.nodes.file.copy_file import CopyFileNode
from pflow.nodes.file.move_file import MoveFileNode
from pflow.nodes.file.delete_file import DeleteFileNode


class TestReadFileNode:
    """Test ReadFileNode functionality."""

    def test_read_existing_file(self):
        """Test reading an existing file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            node = ReadFileNode()
            shared = {"file_path": temp_path}

            prep_result = node.prep(shared)
            node.shared = shared
            exec_result = node.exec(prep_result)
            action = node.post(shared, prep_result, exec_result)

            assert action is None  # Success
            assert shared["content"] == "test content"
        finally:
            os.unlink(temp_path)

    def test_read_nonexistent_file(self):
        """Test error handling for missing files."""
        node = ReadFileNode()
        shared = {"file_path": "/nonexistent/file.txt"}

        prep_result = node.prep(shared)
        node.shared = shared
        exec_result = node.exec(prep_result)
        action = node.post(shared, prep_result, exec_result)

        assert action == 'error'
        assert 'error' in shared
        assert "File not found" in shared['error']

    def test_params_fallback(self):
        """Test using params when shared storage empty."""
        node = ReadFileNode()
        node.params = {"file_path": "test.txt"}

        # Should not raise
        prep_result = node.prep({})
        assert prep_result['file_path'] == "test.txt"

    def test_missing_file_path(self):
        """Test error on missing file_path."""
        node = ReadFileNode()

        with pytest.raises(ValueError, match="Missing required input: file_path"):
            node.prep({})


class TestWriteFileNode:
    """Test WriteFileNode functionality."""

    def test_write_new_file(self):
        """Test writing to a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "output.txt")

            node = WriteFileNode()
            shared = {
                "content": "Hello, world!",
                "file_path": output_path,
                "force": True
            }

            prep_result = node.prep(shared)
            node.shared = shared
            exec_result = node.exec(prep_result)
            action = node.post(shared, prep_result, exec_result)

            assert action is None  # Success

            # Verify file contents
            with open(output_path, 'r') as f:
                assert f.read() == "Hello, world!"

    def test_overwrite_protection(self):
        """Test that overwriting requires force flag."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            node = WriteFileNode()
            shared = {
                "content": "new content",
                "file_path": temp_path
                # No force flag
            }

            with pytest.raises(ValueError, match="File already exists"):
                node.prep(shared)
        finally:
            os.unlink(temp_path)

    def test_create_parent_directories(self):
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "a", "b", "c", "file.txt")

            node = WriteFileNode()
            shared = {
                "content": "nested file",
                "file_path": nested_path,
                "force": True
            }

            prep_result = node.prep(shared)
            node.shared = shared
            exec_result = node.exec(prep_result)
            action = node.post(shared, prep_result, exec_result)

            assert action is None
            assert os.path.exists(nested_path)


class TestCopyFileNode:
    """Test CopyFileNode functionality."""

    def test_copy_file(self):
        """Test copying a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source file
            source = os.path.join(tmpdir, "source.txt")
            with open(source, 'w') as f:
                f.write("source content")

            dest = os.path.join(tmpdir, "dest.txt")

            node = CopyFileNode()
            shared = {
                "source_path": source,
                "dest_path": dest,
                "force": True
            }

            prep_result = node.prep(shared)
            node.shared = shared
            exec_result = node.exec(prep_result)
            action = node.post(shared, prep_result, exec_result)

            assert action is None
            assert os.path.exists(source)  # Source still exists
            assert os.path.exists(dest)    # Dest created

            with open(dest, 'r') as f:
                assert f.read() == "source content"

    def test_copy_missing_source(self):
        """Test error when source doesn't exist."""
        node = CopyFileNode()
        shared = {
            "source_path": "/nonexistent/source.txt",
            "dest_path": "/tmp/dest.txt"
        }

        with pytest.raises(ValueError, match="Source file not found"):
            node.prep(shared)


class TestMoveFileNode:
    """Test MoveFileNode functionality."""

    def test_move_file(self):
        """Test moving a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source file
            source = os.path.join(tmpdir, "source.txt")
            with open(source, 'w') as f:
                f.write("content to move")

            dest = os.path.join(tmpdir, "moved.txt")

            node = MoveFileNode()
            shared = {
                "source_path": source,
                "dest_path": dest,
                "force": True  # Required for destructive op
            }

            prep_result = node.prep(shared)
            node.shared = shared
            exec_result = node.exec(prep_result)
            action = node.post(shared, prep_result, exec_result)

            assert action is None
            assert not os.path.exists(source)  # Source removed
            assert os.path.exists(dest)        # Dest created

            with open(dest, 'r') as f:
                assert f.read() == "content to move"

    def test_move_requires_force(self):
        """Test that move requires force flag."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            node = MoveFileNode()
            shared = {
                "source_path": temp_path,
                "dest_path": "/tmp/moved.txt"
                # No force flag
            }

            with pytest.raises(ValueError, match="destructive operation"):
                node.prep(shared)
        finally:
            os.unlink(temp_path)


class TestDeleteFileNode:
    """Test DeleteFileNode functionality."""

    def test_delete_file(self):
        """Test deleting a file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        node = DeleteFileNode()
        shared = {
            "file_path": temp_path,
            "force": True  # Required
        }

        prep_result = node.prep(shared)
        node.shared = shared
        exec_result = node.exec(prep_result)
        action = node.post(shared, prep_result, exec_result)

        assert action is None
        assert not os.path.exists(temp_path)

    def test_delete_requires_force(self):
        """Test that delete requires force flag."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            node = DeleteFileNode()
            shared = {"file_path": temp_path}

            with pytest.raises(ValueError, match="destructive operation"):
                node.prep(shared)
        finally:
            os.unlink(temp_path)

    def test_delete_system_file_protection(self):
        """Test that system files cannot be deleted."""
        node = DeleteFileNode()

        for path in ["/etc/passwd", "/usr/bin/python", "/sys/kernel"]:
            shared = {"file_path": path, "force": True}

            with pytest.raises(ValueError, match="Cannot delete system file"):
                node.prep(shared)

    def test_delete_already_absent(self):
        """Test deleting non-existent file succeeds."""
        node = DeleteFileNode()
        shared = {
            "file_path": "/nonexistent/file.txt",
            "force": True
        }

        prep_result = node.prep(shared)
        node.shared = shared
        exec_result = node.exec(prep_result)
        action = node.post(shared, prep_result, exec_result)

        assert action is None
        assert shared.get('message') == 'File already absent'


class TestIntegration:
    """Test nodes working together."""

    def test_read_copy_write_flow(self):
        """Test a complete file processing flow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source file
            source = os.path.join(tmpdir, "input.txt")
            with open(source, 'w') as f:
                f.write("Original content")

            # Simulate workflow: read -> copy -> write
            shared = {"file_path": source}

            # Read
            read_node = ReadFileNode()
            prep = read_node.prep(shared)
            read_node.shared = shared
            exec_result = read_node.exec(prep)
            read_node.post(shared, prep, exec_result)

            assert shared["content"] == "Original content"

            # Copy
            backup = os.path.join(tmpdir, "backup.txt")
            shared["source_path"] = source
            shared["dest_path"] = backup
            shared["force"] = True

            copy_node = CopyFileNode()
            prep = copy_node.prep(shared)
            copy_node.shared = shared
            exec_result = copy_node.exec(prep)
            copy_node.post(shared, prep, exec_result)

            # Modify and write
            shared["content"] = shared["content"].upper()
            shared["file_path"] = source

            write_node = WriteFileNode()
            prep = write_node.prep(shared)
            write_node.shared = shared
            exec_result = write_node.exec(prep)
            write_node.post(shared, prep, exec_result)

            # Verify
            with open(source, 'r') as f:
                assert f.read() == "ORIGINAL CONTENT"
            with open(backup, 'r') as f:
                assert f.read() == "Original content"


# Performance tests
class TestPerformance:
    """Test performance characteristics."""

    def test_large_file_handling(self):
        """Test reading/writing large files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 10MB file
            large_file = os.path.join(tmpdir, "large.txt")
            content = "x" * (10 * 1024 * 1024)  # 10MB

            # Write
            write_node = WriteFileNode()
            shared = {
                "content": content,
                "file_path": large_file,
                "force": True
            }

            import time
            start = time.time()

            prep = write_node.prep(shared)
            write_node.shared = shared
            exec_result = write_node.exec(prep)
            write_node.post(shared, prep, exec_result)

            write_time = time.time() - start

            # Read
            read_node = ReadFileNode()
            shared = {"file_path": large_file}

            start = time.time()

            prep = read_node.prep(shared)
            read_node.shared = shared
            exec_result = read_node.exec(prep)
            read_node.post(shared, prep, exec_result)

            read_time = time.time() - start

            # Should complete reasonably fast
            assert write_time < 1.0  # Less than 1 second
            assert read_time < 1.0   # Less than 1 second
            assert len(shared["content"]) == 10 * 1024 * 1024
```

## Test Checklist

- [ ] All nodes have basic functionality tests
- [ ] Missing input validation tested for each node
- [ ] Error paths tested (file not found, permissions, etc.)
- [ ] Safety features tested (force flags, system file protection)
- [ ] Parameter fallback tested (shared storage -> params)
- [ ] Integration tests show nodes working together
- [ ] Performance tests for large files
- [ ] All tests use temporary files for isolation
- [ ] Tests simulate PocketFlow execution correctly
- [ ] Edge cases covered (empty files, special characters, etc.)

## Running Tests

```bash
# Run all file node tests
pytest tests/test_file_nodes.py -v

# Run with coverage
pytest tests/test_file_nodes.py --cov=pflow.nodes.file --cov-report=html

# Run specific test class
pytest tests/test_file_nodes.py::TestReadFileNode -v
```

## Expected Coverage

Based on Task 4 experience, aim for:
- 100% line coverage
- 100% branch coverage
- All error paths tested
- All safety checks validated

Remember: Tests are part of the implementation task, not a separate subtask!
