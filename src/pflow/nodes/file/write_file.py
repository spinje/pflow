"""Write file node implementation."""

import os
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node


class WriteFileNode(Node):
    """
    Write content to a file with automatic directory creation.

    This node writes text content to a file, creating parent directories
    as needed. Supports both write and append modes.

    Interface:
    - Reads: shared["content"] (required), shared["file_path"] (required),
            shared["encoding"] (optional)
    - Writes: shared["written"] on success, shared["error"] on failure
    - Params: content, file_path, encoding, append (as fallbacks if not in shared)
    - Actions: default (success), error (failure)

    Security Note: This node can write to ANY accessible path on the system.
    Do not expose to untrusted input without proper validation.

    Performance Note: Entire content is loaded into memory. Not suitable
    for very large files in MVP.
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient file access issues."""
        super().__init__(max_retries=3, wait=0.1)

    def prep(self, shared: dict) -> tuple[str, str, str, bool]:
        """Extract content, file path, encoding, and mode from shared store or params."""
        # Content is required - check shared first, then params
        if "content" in shared:
            content = shared["content"]
        elif "content" in self.params:
            content = self.params["content"]
        else:
            raise ValueError("Missing required 'content' in shared store or params")

        # File path is required
        file_path = shared.get("file_path") or self.params.get("file_path")
        if not file_path:
            raise ValueError("Missing required 'file_path' in shared store or params")

        # Get encoding with UTF-8 default
        encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")

        # Get append mode (default False)
        append = self.params.get("append", False)

        return (str(content), str(file_path), encoding, append)

    def exec(self, prep_res: tuple[str, str, str, bool]) -> tuple[str, bool]:
        """
        Write content to file.

        Returns:
            Tuple of (result_message, success_bool)
        """
        content, file_path, encoding, append = prep_res

        # Create parent directories if needed
        parent_dir = os.path.dirname(os.path.abspath(file_path))
        if parent_dir:
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except PermissionError:
                return f"Error creating directory for {file_path}: Permission denied", False
            except OSError as e:
                return f"Error creating directory for {file_path}: {e!s}", False

        # Determine write mode
        mode = "a" if append else "w"

        try:
            # Write the file
            with open(file_path, mode, encoding=encoding) as f:
                f.write(content)
        except PermissionError:
            return f"Error writing file {file_path}: Permission denied", False
        except OSError as e:
            # Disk full, path too long, etc.
            return f"Error writing file {file_path}: {e!s}", False
        except Exception as e:
            # This will trigger retry logic in Node
            raise RuntimeError(f"Error writing file {file_path}: {e!s}") from e
        else:
            operation = "appended to" if append else "wrote to"
            return f"Successfully {operation} {file_path}", True

    def exec_fallback(self, prep_res: tuple[str, str, str, bool], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        _, file_path, _, _ = prep_res
        return f"Failed to write file {file_path} after retries: {exc!s}", False

    def post(self, shared: dict, prep_res: tuple[str, str, str, bool], exec_res: tuple[str, bool]) -> str:
        """Update shared store based on result and return action."""
        message, success = exec_res

        if success:
            shared["written"] = message
            return "default"
        else:
            shared["error"] = message
            return "error"
