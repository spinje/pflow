"""Copy file node implementation."""

import os
import shutil
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node


class CopyFileNode(Node):
    """
    Copy a file to a new location with automatic directory creation.

    This node copies a file from source to destination, preserving metadata
    and creating parent directories as needed. Supports overwrite control.

    Interface:
    - Reads: shared["source_path"] (required), shared["dest_path"] (required),
            shared["overwrite"] (optional, default False)
    - Writes: shared["copied"] on success, shared["error"] on failure
    - Params: source_path, dest_path, overwrite (as fallbacks if not in shared)
    - Actions: default (success), error (failure)

    Security Note: This node can copy ANY accessible file on the system.
    Do not expose to untrusted input without proper validation.
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient file access issues."""
        super().__init__(max_retries=3, wait=0.1)

    def prep(self, shared: dict) -> tuple[str, str, bool]:
        """Extract source path, destination path, and overwrite flag from shared store or params."""
        # Source path is required
        source_path = shared.get("source_path") or self.params.get("source_path")
        if not source_path:
            raise ValueError("Missing required 'source_path' in shared store or params")

        # Destination path is required
        dest_path = shared.get("dest_path") or self.params.get("dest_path")
        if not dest_path:
            raise ValueError("Missing required 'dest_path' in shared store or params")

        # Overwrite flag (default False)
        overwrite = shared.get("overwrite", self.params.get("overwrite", False))

        return (str(source_path), str(dest_path), bool(overwrite))

    def exec(self, prep_res: tuple[str, str, bool]) -> tuple[str, bool]:
        """
        Copy file from source to destination.

        Returns:
            Tuple of (result_message, success_bool)
        """
        source_path, dest_path, overwrite = prep_res

        # Check if source exists
        if not os.path.exists(source_path):
            return f"Error: Source file {source_path} does not exist", False

        # Check if source is a file (not directory)
        if not os.path.isfile(source_path):
            return f"Error: Source path {source_path} is not a file", False

        # Check if destination already exists
        if os.path.exists(dest_path) and not overwrite:
            return f"Error: Destination file {dest_path} already exists (set overwrite=True to replace)", False

        # Create parent directories if needed
        parent_dir = os.path.dirname(os.path.abspath(dest_path))
        if parent_dir:
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except PermissionError:
                return f"Error creating directory for {dest_path}: Permission denied", False
            except OSError as e:
                return f"Error creating directory for {dest_path}: {e!s}", False

        try:
            # Copy the file preserving metadata
            shutil.copy2(source_path, dest_path)
        except PermissionError:
            return "Error copying file: Permission denied", False
        except OSError as e:
            # Disk full, path too long, etc.
            return f"Error copying file: {e!s}", False
        except Exception as e:
            # This will trigger retry logic in Node
            raise RuntimeError(f"Error copying file: {e!s}") from e
        else:
            return f"Successfully copied {source_path} to {dest_path}", True

    def exec_fallback(self, prep_res: tuple[str, str, bool], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        source_path, dest_path, _ = prep_res
        return f"Failed to copy {source_path} to {dest_path} after retries: {exc!s}", False

    def post(self, shared: dict, prep_res: tuple[str, str, bool], exec_res: tuple[str, bool]) -> str:
        """Update shared store based on result and return action."""
        message, success = exec_res

        if success:
            shared["copied"] = message
            return "default"
        else:
            shared["error"] = message
            return "error"
