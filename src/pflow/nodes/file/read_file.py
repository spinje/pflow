"""Read file node implementation."""

import os
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node


class ReadFileNode(Node):
    """
    Read content from a file and add line numbers for display.

    This node reads a text file and formats it with 1-indexed line numbers,
    following the Tutorial-Cursor pattern for file display.

    Interface:
    - Reads: shared["file_path"] (required), shared["encoding"] (optional)
    - Writes: shared["content"] on success, shared["error"] on failure
    - Params: file_path, encoding (as fallbacks if not in shared)
    - Actions: default (success), error (failure)

    Security Note: This node can read ANY accessible file on the system.
    Do not expose to untrusted input without proper validation.
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient file access issues."""
        super().__init__(max_retries=3, wait=0.1)

    def prep(self, shared: dict) -> tuple[str, str]:
        """Extract file path and encoding from shared store or params."""
        # Check shared store first, then params
        file_path = shared.get("file_path") or self.params.get("file_path")
        if not file_path:
            raise ValueError("Missing required 'file_path' in shared store or params")

        # Get encoding with UTF-8 default
        encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")

        return (str(file_path), encoding)

    def exec(self, prep_res: tuple[str, str]) -> tuple[str, bool]:
        """
        Read file content and add line numbers.

        Returns:
            Tuple of (content_or_error, success_bool)
        """
        file_path, encoding = prep_res

        # Check if file exists
        if not os.path.exists(file_path):
            return f"Error: File {file_path} does not exist", False

        try:
            # Read file content
            with open(file_path, encoding=encoding) as f:
                lines = f.readlines()
        except UnicodeDecodeError as e:
            return f"Error reading file {file_path}: Encoding error - {e!s}", False
        except PermissionError:
            return f"Error reading file {file_path}: Permission denied", False
        except Exception as e:
            # This will trigger retry logic in Node
            raise RuntimeError(f"Error reading file {file_path}: {e!s}") from e
        else:
            # Add 1-indexed line numbers
            numbered_lines = [f"{i + 1}: {line}" for i, line in enumerate(lines)]
            content = "".join(numbered_lines)
            return content, True

    def exec_fallback(self, prep_res: tuple[str, str], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        file_path, _ = prep_res
        return f"Failed to read file {file_path} after retries: {exc!s}", False

    def post(self, shared: dict, prep_res: tuple[str, str], exec_res: tuple[str, bool]) -> str:
        """Update shared store based on result and return action."""
        content_or_error, success = exec_res

        if success:
            shared["content"] = content_or_error
            return "default"
        else:
            shared["error"] = content_or_error
            return "error"
