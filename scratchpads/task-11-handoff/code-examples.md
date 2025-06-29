# Task 11 Code Examples

Complete working examples for each file node based on Task 4 discoveries.

## 1. read_file.py - Complete Implementation

```python
"""Read file node for pflow."""
from typing import Any

from pocketflow import BaseNode


class ReadFileNode(BaseNode):
    """Read file contents into shared storage.

    Reads a file from the filesystem and stores its contents in the shared store.
    Supports text files with UTF-8 encoding by default.

    Interface:
        Reads: file_path (str) - Path to the file to read
        Writes: content (str) - Contents of the file
        Actions: default (success), error (file not found or read error)
    """

    name = 'read-file'

    def prep(self, shared_storage: dict[str, Any]) -> Any:
        """Validate that file_path is provided."""
        # Check shared storage first, then params
        file_path = shared_storage.get('file_path') or self.params.get('file_path')

        if not file_path:
            raise ValueError("Missing required input: file_path")

        # Store for exec phase
        return {'file_path': file_path}

    def exec(self, prep_result: Any) -> Any:
        """Read the file contents."""
        file_path = prep_result['file_path']

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {'content': content, 'success': True}
        except FileNotFoundError:
            return {
                'error': f"File not found: {file_path}",
                'success': False
            }
        except Exception as e:
            return {
                'error': f"Error reading file: {e}",
                'success': False
            }

    def post(self, shared_storage: dict[str, Any], prep_result: Any, exec_result: Any) -> str:
        """Store content in shared storage and return appropriate action."""
        if exec_result['success']:
            shared_storage['content'] = exec_result['content']
            return None  # Default action
        else:
            shared_storage['error'] = exec_result['error']
            return 'error'
```

## 2. write_file.py - Complete Implementation

```python
"""Write file node for pflow."""
import os
from typing import Any

from pocketflow import BaseNode


class WriteFileNode(BaseNode):
    """Write content to a file.

    Writes content from shared storage to a file on the filesystem.
    Creates parent directories if they don't exist.

    Interface:
        Reads:
            - content (str) - Content to write to the file
            - file_path (str) - Path where to write the file
            - force (bool, optional) - Skip safety checks if True
        Writes: None
        Actions: default (success), error (write error)
    """

    name = 'write-file'

    def prep(self, shared_storage: dict[str, Any]) -> Any:
        """Validate inputs and perform safety checks."""
        # Get inputs from shared storage or params
        content = shared_storage.get('content')
        file_path = shared_storage.get('file_path') or self.params.get('file_path')
        force = shared_storage.get('force', False)

        # Validate required inputs
        if content is None:
            raise ValueError("Missing required input: content")
        if not file_path:
            raise ValueError("Missing required input: file_path")

        # Safety check - warn about overwriting
        if os.path.exists(file_path) and not force:
            raise ValueError(
                f"File already exists: {file_path}. "
                "Set shared['force'] = True to overwrite."
            )

        return {
            'content': content,
            'file_path': file_path
        }

    def exec(self, prep_result: Any) -> Any:
        """Write the content to file."""
        file_path = prep_result['file_path']
        content = prep_result['content']

        try:
            # Create parent directory if needed
            parent_dir = os.path.dirname(file_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Write the file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return {'success': True}
        except Exception as e:
            return {
                'error': f"Error writing file: {e}",
                'success': False
            }

    def post(self, shared_storage: dict[str, Any], prep_result: Any, exec_result: Any) -> str:
        """Return appropriate action based on result."""
        if exec_result['success']:
            return None  # Default action
        else:
            shared_storage['error'] = exec_result['error']
            return 'error'
```

## 3. copy_file.py - Complete Implementation

```python
"""Copy file node for pflow."""
import os
import shutil
from typing import Any

from pocketflow import BaseNode


class CopyFileNode(BaseNode):
    """Copy a file from source to destination.

    Copies a file while preserving metadata. Creates parent directories
    for the destination if they don't exist.

    Interface:
        Reads:
            - source_path (str) - Path to the source file
            - dest_path (str) - Path where to copy the file
            - force (bool, optional) - Overwrite destination if it exists
        Writes: None
        Actions: default (success), error (copy error)
    """

    name = 'copy-file'

    def prep(self, shared_storage: dict[str, Any]) -> Any:
        """Validate inputs and check paths."""
        source_path = shared_storage.get('source_path') or self.params.get('source_path')
        dest_path = shared_storage.get('dest_path') or self.params.get('dest_path')
        force = shared_storage.get('force', False)

        if not source_path:
            raise ValueError("Missing required input: source_path")
        if not dest_path:
            raise ValueError("Missing required input: dest_path")

        # Check source exists
        if not os.path.exists(source_path):
            raise ValueError(f"Source file not found: {source_path}")

        # Check if destination exists
        if os.path.exists(dest_path) and not force:
            raise ValueError(
                f"Destination already exists: {dest_path}. "
                "Set shared['force'] = True to overwrite."
            )

        return {
            'source_path': source_path,
            'dest_path': dest_path
        }

    def exec(self, prep_result: Any) -> Any:
        """Copy the file."""
        source = prep_result['source_path']
        dest = prep_result['dest_path']

        try:
            # Create parent directory if needed
            parent_dir = os.path.dirname(dest)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Copy file with metadata
            shutil.copy2(source, dest)

            return {'success': True}
        except Exception as e:
            return {
                'error': f"Error copying file: {e}",
                'success': False
            }

    def post(self, shared_storage: dict[str, Any], prep_result: Any, exec_result: Any) -> str:
        """Return appropriate action based on result."""
        if exec_result['success']:
            return None
        else:
            shared_storage['error'] = exec_result['error']
            return 'error'
```

## 4. move_file.py - Complete Implementation

```python
"""Move file node for pflow."""
import os
import shutil
from typing import Any

from pocketflow import BaseNode


class MoveFileNode(BaseNode):
    """Move a file from source to destination.

    Moves a file to a new location. This is a destructive operation
    that removes the source file.

    Interface:
        Reads:
            - source_path (str) - Path to the source file
            - dest_path (str) - Path where to move the file
            - force (bool, optional) - Required for destructive operation
        Writes: None
        Actions: default (success), error (move error)
    """

    name = 'move-file'

    def prep(self, shared_storage: dict[str, Any]) -> Any:
        """Validate inputs and require confirmation."""
        source_path = shared_storage.get('source_path') or self.params.get('source_path')
        dest_path = shared_storage.get('dest_path') or self.params.get('dest_path')
        force = shared_storage.get('force', False)

        if not source_path:
            raise ValueError("Missing required input: source_path")
        if not dest_path:
            raise ValueError("Missing required input: dest_path")

        # Check source exists
        if not os.path.exists(source_path):
            raise ValueError(f"Source file not found: {source_path}")

        # Require force flag for destructive operation
        if not force:
            raise ValueError(
                f"Moving {source_path} is a destructive operation. "
                "Set shared['force'] = True to proceed."
            )

        # Check if destination exists
        if os.path.exists(dest_path):
            raise ValueError(
                f"Destination already exists: {dest_path}. "
                "Cannot move to existing location."
            )

        return {
            'source_path': source_path,
            'dest_path': dest_path
        }

    def exec(self, prep_result: Any) -> Any:
        """Move the file."""
        source = prep_result['source_path']
        dest = prep_result['dest_path']

        try:
            # Create parent directory if needed
            parent_dir = os.path.dirname(dest)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Move the file
            shutil.move(source, dest)

            return {'success': True}
        except Exception as e:
            return {
                'error': f"Error moving file: {e}",
                'success': False
            }

    def post(self, shared_storage: dict[str, Any], prep_result: Any, exec_result: Any) -> str:
        """Return appropriate action based on result."""
        if exec_result['success']:
            return None
        else:
            shared_storage['error'] = exec_result['error']
            return 'error'
```

## 5. delete_file.py - Complete Implementation

```python
"""Delete file node for pflow."""
import os
from typing import Any

from pocketflow import BaseNode


class DeleteFileNode(BaseNode):
    """Delete a file from the filesystem.

    Permanently removes a file. This is a destructive operation that
    cannot be undone. Includes safety checks to prevent accidental deletion.

    Interface:
        Reads:
            - file_path (str) - Path to the file to delete
            - force (bool) - Required confirmation for deletion
        Writes: None
        Actions: default (success), error (delete error)
    """

    name = 'delete-file'

    def prep(self, shared_storage: dict[str, Any]) -> Any:
        """Validate inputs and enforce safety checks."""
        file_path = shared_storage.get('file_path') or self.params.get('file_path')
        force = shared_storage.get('force', False)

        if not file_path:
            raise ValueError("Missing required input: file_path")

        # Safety check - prevent deleting system files
        dangerous_paths = ['/sys', '/etc', '/usr', '/bin', '/sbin', '/boot']
        abs_path = os.path.abspath(file_path)

        for dangerous in dangerous_paths:
            if abs_path.startswith(dangerous):
                raise ValueError(
                    f"Cannot delete system file: {file_path}. "
                    "This operation is blocked for safety."
                )

        # Check if file exists
        if not os.path.exists(file_path):
            # Not an error - file already doesn't exist
            return {'file_path': file_path, 'already_gone': True}

        # Require force flag for destructive operation
        if not force:
            raise ValueError(
                f"Deleting {file_path} is a destructive operation. "
                "Set shared['force'] = True to proceed."
            )

        return {'file_path': file_path, 'already_gone': False}

    def exec(self, prep_result: Any) -> Any:
        """Delete the file."""
        if prep_result['already_gone']:
            return {'success': True, 'message': 'File already absent'}

        file_path = prep_result['file_path']

        try:
            os.remove(file_path)
            return {'success': True}
        except Exception as e:
            return {
                'error': f"Error deleting file: {e}",
                'success': False
            }

    def post(self, shared_storage: dict[str, Any], prep_result: Any, exec_result: Any) -> str:
        """Return appropriate action based on result."""
        if exec_result['success']:
            if 'message' in exec_result:
                shared_storage['message'] = exec_result['message']
            return None
        else:
            shared_storage['error'] = exec_result['error']
            return 'error'
```

## Test Example

```python
"""Test file nodes implementation."""
import os
import tempfile
import pytest

from pflow.nodes.file.read_file import ReadFileNode
from pflow.nodes.file.write_file import WriteFileNode


def test_read_write_integration():
    """Test reading and writing files through nodes."""
    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.txt")
        test_content = "Hello, pflow!"

        # Write test file
        with open(test_file, 'w') as f:
            f.write(test_content)

        # Test read node
        read_node = ReadFileNode()
        shared = {'file_path': test_file}

        prep_result = read_node.prep(shared)
        read_node.shared = shared  # Simulate PocketFlow
        exec_result = read_node.exec(prep_result)
        action = read_node.post(shared, prep_result, exec_result)

        assert action is None  # Success
        assert shared['content'] == test_content

        # Test write node
        write_node = WriteFileNode()
        output_file = os.path.join(tmpdir, "output.txt")
        shared['file_path'] = output_file
        shared['force'] = True

        prep_result = write_node.prep(shared)
        write_node.shared = shared
        exec_result = write_node.exec(prep_result)
        action = write_node.post(shared, prep_result, exec_result)

        assert action is None  # Success

        # Verify file was written
        with open(output_file, 'r') as f:
            assert f.read() == test_content


def test_missing_inputs():
    """Test that nodes fail fast on missing inputs."""
    node = ReadFileNode()
    shared = {}  # Missing file_path

    with pytest.raises(ValueError, match="Missing required input: file_path"):
        node.prep(shared)
```

## __init__.py for the file module

```python
"""File operation nodes for pflow."""
from .copy_file import CopyFileNode
from .delete_file import DeleteFileNode
from .move_file import MoveFileNode
from .read_file import ReadFileNode
from .write_file import WriteFileNode

__all__ = [
    "ReadFileNode",
    "WriteFileNode",
    "CopyFileNode",
    "MoveFileNode",
    "DeleteFileNode",
]
```
