"""Copy file node implementation."""

import logging
import os
import shutil
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node

from .exceptions import NonRetriableError

# Set up logging
logger = logging.getLogger(__name__)


class CopyFileNode(Node):
    """
    Copy a file to a new location with automatic directory creation.

    This node copies a file from source to destination, preserving metadata
    and creating parent directories as needed. Supports overwrite control.

    Interface:
    - Reads: shared["source_path"]: str  # Source file path
    - Reads: shared["dest_path"]: str  # Destination file path
    - Reads: shared["overwrite"]: bool  # Whether to overwrite existing files (optional, default: false)
    - Writes: shared["copied"]: bool  # True if copy succeeded
    - Writes: shared["error"]: str  # Error message if operation failed
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
            "Preparing to copy file",
            extra={"source_path": source_path, "dest_path": dest_path, "overwrite": overwrite, "phase": "prep"},
        )
        return (str(source_path), str(dest_path), bool(overwrite))

    def _validate_source(self, source_path: str) -> None:
        """Validate source file exists and is a file."""
        if not os.path.exists(source_path):
            logger.error("Source file not found", extra={"source_path": source_path, "phase": "exec"})
            raise FileNotFoundError(f"Source file '{source_path}' does not exist")

        if not os.path.isfile(source_path):
            logger.error("Source is not a file", extra={"source_path": source_path, "phase": "exec"})
            # This is a validation error that won't change with retries
            raise NonRetriableError(
                f"Source path '{source_path}' is not a file. This node only copies files, not directories."
            )

    def _validate_destination(self, dest_path: str, overwrite: bool, source_path: str) -> None:
        """Validate destination doesn't exist or can be overwritten."""
        if os.path.exists(dest_path) and not overwrite:
            logger.error(
                "Destination exists, overwrite not allowed",
                extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"},
            )
            # This is a validation error that won't change with retries
            raise NonRetriableError(f"Destination file '{dest_path}' already exists. Set overwrite=True to replace it.")

    def _check_disk_space(self, file_size: int, parent_dir: str | None, source_path: str, dest_path: str) -> None:
        """Check if there's enough disk space for the copy."""
        if file_size > 0:
            try:
                stat = os.statvfs(parent_dir or ".")
                free_bytes = stat.f_bavail * stat.f_frsize
                if free_bytes < file_size * 1.5:  # Want at least 1.5x file size
                    logger.error(
                        "Insufficient disk space",
                        extra={
                            "source_path": source_path,
                            "dest_path": dest_path,
                            "required_bytes": file_size,
                            "free_bytes": free_bytes,
                            "phase": "exec",
                        },
                    )
                    # Raise OSError for disk space issues
                    raise OSError(f"No space left on device. Need {file_size} bytes but only {free_bytes} available")
            except (AttributeError, OSError) as e:
                if "No space left" in str(e):
                    raise  # Re-raise disk space errors
                # statvfs not available on Windows or other error - continue anyway
                pass

    def exec(self, prep_res: tuple[str, str, bool]) -> str:
        """
        Copy file from source to destination with disk space checks.

        Returns:
            Success message

        Raises:
            FileNotFoundError: If source file doesn't exist
            NonRetriableError: For validation errors that won't change
            PermissionError: If unable to read source or write destination
            OSError: For disk space or other file system errors
        """
        source_path, dest_path, overwrite = prep_res

        # Validate source
        self._validate_source(source_path)

        # Validate destination
        self._validate_destination(dest_path, overwrite, source_path)

        # Get source file size
        try:
            file_size = os.path.getsize(source_path)

            # Log for large files
            if file_size > 1024 * 1024:  # 1MB
                logger.info(
                    "Starting large file copy",
                    extra={
                        "source_path": source_path,
                        "dest_path": dest_path,
                        "size_mb": round(file_size / (1024 * 1024), 2),
                        "phase": "exec",
                    },
                )
        except OSError as e:
            logger.warning(
                "Could not get file size", extra={"source_path": source_path, "error": str(e), "phase": "exec"}
            )
            file_size = 0

        # Create parent directories if needed
        parent_dir = os.path.dirname(dest_path)
        if parent_dir:
            logger.debug("Creating parent directories", extra={"dir_path": parent_dir, "phase": "exec"})
            # Let exceptions bubble up for retry mechanism
            os.makedirs(parent_dir, exist_ok=True)

        # Check disk space
        self._check_disk_space(file_size, parent_dir, source_path, dest_path)

        # Perform the actual copy
        return self._perform_copy(source_path, dest_path, file_size)

    def _perform_copy(self, source_path: str, dest_path: str, file_size: int) -> str:
        """Perform the actual file copy operation."""
        logger.info("Copying file", extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"})

        # Copy the file preserving metadata - let exceptions bubble up
        shutil.copy2(source_path, dest_path)

        logger.info(
            "File copy completed",
            extra={"source_path": source_path, "dest_path": dest_path, "size_bytes": file_size, "phase": "exec"},
        )

        return f"Successfully copied '{source_path}' to '{dest_path}'"

    def exec_fallback(self, prep_res: tuple[str, str, bool], exc: Exception) -> str:
        """Handle final failure after all retries with user-friendly messages."""
        source_path, dest_path, _ = prep_res

        logger.error(
            f"Failed to copy file after {self.max_retries} retries",
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
                f"Error: Permission denied when copying '{source_path}' to '{dest_path}'. Check file permissions."
            )
        elif isinstance(exc, OSError) and ("No space left" in str(exc) or "disk full" in str(exc).lower()):
            error_msg = f"Error: No space left on device when copying to '{dest_path}'."
        else:
            error_msg = f"Error: Could not copy '{source_path}' to '{dest_path}' after {self.max_retries} retries. {exc!s}. Check if files are locked or if there are system issues."

        return error_msg

    def post(self, shared: dict, prep_res: tuple[str, str, bool], exec_res: str) -> str:
        """Update shared store based on result and return action."""
        # Check if exec_res is an error message from exec_fallback
        if exec_res.startswith("Error:"):
            shared["error"] = exec_res
            return "error"
        else:
            shared["copied"] = exec_res
            return "default"
