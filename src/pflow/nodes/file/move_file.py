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

from .exceptions import NonRetriableError

logger = logging.getLogger(__name__)


class MoveFileNode(Node):
    """
    Move a file to a new location with automatic directory creation.

    This node moves a file from source to destination, creating parent
    directories as needed. Uses atomic moves when possible, with fallback
    to copy-and-delete for cross-filesystem moves.

    Interface:
    - Params: source_path: str  # Source file path
    - Params: dest_path: str  # Destination file path
    - Params: overwrite: bool  # Whether to overwrite existing files (optional, default: false)
    - Writes: shared["moved"]: bool  # True if move succeeded
    - Writes: shared["error"]: str  # Error message if operation failed
    - Writes: shared["warning"]: str  # Warning message on partial success (copy ok but delete failed)
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
        source_path = self.params.get("source_path")
        if not source_path:
            raise ValueError("Missing required 'source_path' parameter")

        # Destination path is required
        dest_path = self.params.get("dest_path")
        if not dest_path:
            raise ValueError("Missing required 'dest_path' parameter")

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

    def _cross_device_move(self, source_path: str, dest_path: str) -> str:
        """Handle cross-filesystem move by copy and delete."""
        logger.info(
            "Performing cross-device move",
            extra={"source_path": source_path, "dest_path": dest_path, "phase": "cross_device_move"},
        )

        # First copy the file - let exceptions bubble up
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
            return f"Successfully moved '{source_path}' to '{dest_path}' (cross-device)"
        except Exception as e:
            # Copy succeeded but delete failed - partial success
            warning_msg = f"File copied but source deletion failed: {e!s}"
            logger.warning(
                warning_msg, extra={"source_path": source_path, "error": str(e), "phase": "cross_device_move"}
            )
            # Store warning but still return success
            return f"Successfully moved '{source_path}' to '{dest_path}' (warning: {warning_msg})"

    def _validate_move(self, source_path: str, dest_path: str, overwrite: bool) -> None:
        """Validate source and destination for move operation."""
        # Check if source exists
        if not os.path.exists(source_path):
            logger.error("Source file not found", extra={"source_path": source_path, "phase": "exec"})
            raise FileNotFoundError(f"Source file '{source_path}' does not exist")

        # Check if source is a file (not directory)
        if not os.path.isfile(source_path):
            logger.error("Source is not a file", extra={"source_path": source_path, "phase": "exec"})
            # This is a validation error that won't change with retries
            raise NonRetriableError(
                f"Source path '{source_path}' is not a file. This node only moves files, not directories."
            )

        # Check if destination already exists
        if os.path.exists(dest_path) and not overwrite:
            logger.error(
                "Destination exists, overwrite not allowed",
                extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"},
            )
            # This is a validation error that won't change with retries
            raise NonRetriableError(f"Destination file '{dest_path}' already exists. Set overwrite=True to replace it.")

    def _ensure_parent_directory(self, dest_path: str) -> None:
        """Create parent directories if needed."""
        parent_dir = os.path.dirname(dest_path)
        if parent_dir:
            logger.debug("Creating parent directories", extra={"dir_path": parent_dir, "phase": "exec"})
            # Let exceptions bubble up for retry mechanism
            os.makedirs(parent_dir, exist_ok=True)

    def exec(self, prep_res: tuple[str, str, bool]) -> str:
        """
        Move file from source to destination.

        Returns:
            Success message (may include warnings)

        Raises:
            FileNotFoundError: If source file doesn't exist
            NonRetriableError: For validation errors that won't change
            PermissionError: If unable to move file or create directories
            OSError: For other file system errors
        """
        source_path, dest_path, overwrite = prep_res

        # Validate the move operation
        self._validate_move(source_path, dest_path, overwrite)

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
        self._ensure_parent_directory(dest_path)

        logger.info("Moving file", extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"})

        try:
            # Try to move the file
            shutil.move(source_path, dest_path)
            logger.info(
                "File moved successfully",
                extra={"source_path": source_path, "dest_path": dest_path, "size_bytes": file_size, "phase": "exec"},
            )
            return f"Successfully moved '{source_path}' to '{dest_path}'"
        except OSError as e:
            # Check if it's a cross-device link error
            if "cross-device link" in str(e).lower() or (hasattr(e, "errno") and e.errno == errno.EXDEV):
                logger.debug(
                    "Cross-device link detected",
                    extra={"source_path": source_path, "dest_path": dest_path, "error": str(e), "phase": "exec"},
                )
                # Handle cross-filesystem move
                return self._cross_device_move(source_path, dest_path)
            else:
                # Other OS errors should be retried
                raise

    def exec_fallback(self, prep_res: tuple[str, str, bool], exc: Exception) -> str:
        """Handle final failure after all retries with user-friendly messages."""
        source_path, dest_path, _ = prep_res

        logger.error(
            f"Failed to move file after {self.max_retries} retries",
            extra={"source_path": source_path, "dest_path": dest_path, "error": str(exc), "phase": "fallback"},
        )

        # Provide specific error messages based on exception type
        if isinstance(exc, NonRetriableError):
            # Pass through non-retriable error messages as-is
            error_msg = f"Error: {exc!s}"
        elif isinstance(exc, FileNotFoundError):
            error_msg = f"Error: Source file '{source_path}' does not exist. Please check the path."
        elif isinstance(exc, PermissionError):
            error_msg = (
                f"Error: Permission denied when moving '{source_path}' to '{dest_path}'. Check file permissions."
            )
        elif isinstance(exc, OSError) and ("No space left" in str(exc) or "disk full" in str(exc).lower()):
            error_msg = f"Error: No space left on device when moving to '{dest_path}'."
        else:
            error_msg = f"Error: Could not move '{source_path}' to '{dest_path}' after {self.max_retries} retries. {exc!s}. Check if files are locked or if there are system issues."

        return error_msg

    def post(self, shared: dict, prep_res: tuple[str, str, bool], exec_res: str) -> str:
        """Update shared store based on result and return action."""
        # Check if exec_res is an error message from exec_fallback
        if exec_res.startswith("Error:"):
            shared["error"] = exec_res
            return "error"
        else:
            shared["moved"] = exec_res
            # Check if there's a warning in the message
            if "warning:" in exec_res.lower():
                # Extract warning part
                warning_start = exec_res.lower().find("warning:")
                shared["warning"] = exec_res[warning_start:]
            return "default"
