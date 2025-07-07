"""Move file node implementation."""

import errno
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

        # Normalize paths
        source_path = os.path.expanduser(source_path)
        source_path = os.path.abspath(source_path)
        source_path = os.path.normpath(source_path)

        dest_path = os.path.expanduser(dest_path)
        dest_path = os.path.abspath(dest_path)
        dest_path = os.path.normpath(dest_path)

        # Overwrite flag (default False)
        overwrite = shared.get("overwrite", self.params.get("overwrite", False))

        logger.debug(
            "Preparing to move file",
            extra={"source_path": source_path, "dest_path": dest_path, "overwrite": overwrite, "phase": "prep"},
        )
        return (str(source_path), str(dest_path), bool(overwrite))

    def _cross_device_move(self, source_path: str, dest_path: str) -> tuple[str, bool]:
        """Handle cross-filesystem move by copy and delete."""
        logger.info(
            "Performing cross-device move",
            extra={"source_path": source_path, "dest_path": dest_path, "phase": "cross_device_move"},
        )

        try:
            # First copy the file
            shutil.copy2(source_path, dest_path)
            logger.debug(
                "Cross-device copy completed",
                extra={"source_path": source_path, "dest_path": dest_path, "phase": "cross_device_move"},
            )

            # Then try to delete the source
            try:
                os.remove(source_path)
                logger.info(
                    "Cross-device move completed",
                    extra={"source_path": source_path, "dest_path": dest_path, "phase": "cross_device_move"},
                )
            except Exception as e:
                # Copy succeeded but delete failed - partial success
                warning_msg = f"File copied but source deletion failed: {e!s}"
                logger.warning(
                    warning_msg, extra={"source_path": source_path, "error": str(e), "phase": "cross_device_move"}
                )
                # Store warning but still return success
                return f"Successfully moved '{source_path}' to '{dest_path}' (warning: {warning_msg})", True
            else:
                return f"Successfully moved '{source_path}' to '{dest_path}' (cross-device)", True

        except Exception as e:
            # Copy failed
            logger.exception(
                "Cross-device move failed during copy",
                extra={
                    "source_path": source_path,
                    "dest_path": dest_path,
                    "error": str(e),
                    "phase": "cross_device_move",
                },
            )
            return f"Error: Failed to copy '{source_path}' to '{dest_path}' during cross-device move: {e!s}", False

    def _validate_move(self, source_path: str, dest_path: str, overwrite: bool) -> tuple[str, bool] | None:
        """Validate source and destination for move operation."""
        # Check if source exists
        if not os.path.exists(source_path):
            logger.error("Source file not found", extra={"source_path": source_path, "phase": "exec"})
            return f"Error: Source file '{source_path}' does not exist. Please check the path.", False

        # Check if source is a file (not directory)
        if not os.path.isfile(source_path):
            logger.error("Source is not a file", extra={"source_path": source_path, "phase": "exec"})
            return (
                f"Error: Source path '{source_path}' is not a file. This node only moves files, not directories.",
                False,
            )

        # Check if destination already exists
        if os.path.exists(dest_path) and not overwrite:
            logger.error(
                "Destination exists, overwrite not allowed",
                extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"},
            )
            return f"Error: Destination file '{dest_path}' already exists. Set overwrite=True to replace it.", False

        return None

    def _ensure_parent_directory(self, dest_path: str) -> tuple[str, bool] | None:
        """Create parent directories if needed."""
        parent_dir = os.path.dirname(dest_path)
        if parent_dir:
            try:
                logger.debug("Creating parent directories", extra={"dir_path": parent_dir, "phase": "exec"})
                os.makedirs(parent_dir, exist_ok=True)
            except PermissionError:
                logger.exception(
                    "Permission denied creating directory", extra={"dir_path": parent_dir, "phase": "exec"}
                )
                return f"Error: Permission denied when creating directory '{parent_dir}'. Check permissions.", False
            except OSError as e:
                logger.exception(
                    "Failed to create directory", extra={"dir_path": parent_dir, "error": str(e), "phase": "exec"}
                )
                return f"Error: Cannot create directory '{parent_dir}': {e!s}", False
        return None

    def exec(self, prep_res: tuple[str, str, bool]) -> tuple[str, bool]:
        """
        Move file from source to destination.

        Returns:
            Tuple of (result_message, success_bool)
        """
        source_path, dest_path, overwrite = prep_res

        # Validate the move operation
        if error := self._validate_move(source_path, dest_path, overwrite):
            return error

        # Get file size for logging
        try:
            file_size = os.path.getsize(source_path)
            if file_size > 1024 * 1024:  # 1MB
                logger.info(
                    "Moving large file",
                    extra={
                        "source_path": source_path,
                        "dest_path": dest_path,
                        "size_mb": round(file_size / (1024 * 1024), 2),
                        "phase": "exec",
                    },
                )
        except OSError:
            file_size = 0

        # Create parent directories if needed
        if error := self._ensure_parent_directory(dest_path):
            return error

        try:
            logger.info("Moving file", extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"})
            # Try to move the file
            shutil.move(source_path, dest_path)
            logger.info(
                "File moved successfully",
                extra={"source_path": source_path, "dest_path": dest_path, "size_bytes": file_size, "phase": "exec"},
            )
        except OSError as e:
            # Check if it's a cross-device link error
            if "cross-device link" in str(e).lower() or e.errno == errno.EXDEV if hasattr(e, "errno") else False:
                logger.debug(
                    "Cross-device link detected",
                    extra={"source_path": source_path, "dest_path": dest_path, "error": str(e), "phase": "exec"},
                )
                # Handle cross-filesystem move
                return self._cross_device_move(source_path, dest_path)
            # Other OS errors are non-retryable
            logger.exception(
                "Move failed",
                extra={"source_path": source_path, "dest_path": dest_path, "error": str(e), "phase": "exec"},
            )
            return f"Error: Failed to move '{source_path}' to '{dest_path}': {e!s}", False
        except PermissionError:
            logger.exception(
                "Permission denied during move",
                extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"},
            )
            return (
                f"Error: Permission denied when moving '{source_path}' to '{dest_path}'. Check file permissions.",
                False,
            )
        except Exception as e:
            logger.warning(
                "Unexpected error, will retry",
                extra={"source_path": source_path, "dest_path": dest_path, "error": str(e), "phase": "exec"},
            )
            # This will trigger retry logic in Node
            raise RuntimeError(f"Error moving '{source_path}' to '{dest_path}': {e!s}") from e
        else:
            return f"Successfully moved '{source_path}' to '{dest_path}'", True

    def exec_fallback(self, prep_res: tuple[str, str, bool], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        source_path, dest_path, _ = prep_res
        logger.error(
            f"Failed to move file after {self.max_retries} retries",
            extra={"source_path": source_path, "dest_path": dest_path, "error": str(exc), "phase": "fallback"},
        )
        return (
            f"Error: Could not move '{source_path}' to '{dest_path}' after {self.max_retries} retries. {exc!s}. Check if files are locked or if there are system issues.",
            False,
        )

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
