"""Move file node implementation."""

import logging
import os
import shutil
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node

logger = logging.getLogger(__name__)


class MoveFileNode(Node):
    """
    Move a file to a new location with automatic directory creation.

    This node moves a file from source to destination, creating parent
    directories as needed. Uses atomic moves when possible, with fallback
    to copy-and-delete for cross-filesystem moves.

    Interface:
    - Reads: shared["source_path"] (required), shared["dest_path"] (required),
            shared["overwrite"] (optional, default False)
    - Writes: shared["moved"] on success, shared["error"] on failure,
             shared["warning"] on partial success (copy ok, delete failed)
    - Params: source_path, dest_path, overwrite (as fallbacks if not in shared)
    - Actions: default (success), error (failure)

    Security Note: This node can move ANY accessible file on the system.
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

    def _cross_device_move(self, source_path: str, dest_path: str) -> tuple[str, bool]:
        """Handle cross-filesystem move by copy and delete."""
        try:
            # First copy the file
            shutil.copy2(source_path, dest_path)

            # Then try to delete the source
            try:
                os.remove(source_path)
                return f"Successfully moved {source_path} to {dest_path}", True
            except Exception as e:
                # Copy succeeded but delete failed - partial success
                warning_msg = f"File copied but source deletion failed: {e!s}"
                logger.warning(warning_msg, extra={"phase": "cross_device_move", "file_path": source_path})
                # Store warning but still return success
                return f"Successfully moved {source_path} to {dest_path} (warning: {warning_msg})", True

        except Exception as e:
            # Copy failed
            return f"Error during cross-device move: {e!s}", False

    def exec(self, prep_res: tuple[str, str, bool]) -> tuple[str, bool]:
        """
        Move file from source to destination.

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
            # Try to move the file
            shutil.move(source_path, dest_path)
        except OSError as e:
            # Check if it's a cross-device link error
            if "cross-device link" in str(e).lower():
                # Handle cross-filesystem move
                return self._cross_device_move(source_path, dest_path)
            # Other OS errors are non-retryable
            return f"Error moving file: {e!s}", False
        except PermissionError:
            return "Error moving file: Permission denied", False
        except Exception as e:
            # This will trigger retry logic in Node
            raise RuntimeError(f"Error moving file: {e!s}") from e
        else:
            return f"Successfully moved {source_path} to {dest_path}", True

    def exec_fallback(self, prep_res: tuple[str, str, bool], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        source_path, dest_path, _ = prep_res
        return f"Failed to move {source_path} to {dest_path} after retries: {exc!s}", False

    def post(self, shared: dict, prep_res: tuple[str, str, bool], exec_res: tuple[str, bool]) -> str:
        """Update shared store based on result and return action."""
        message, success = exec_res

        if success:
            shared["moved"] = message
            # Check if there's a warning in the message
            if "warning:" in message.lower():
                # Extract warning part
                warning_start = message.lower().find("warning:")
                shared["warning"] = message[warning_start:]
            return "default"
        else:
            shared["error"] = message
            return "error"
