"""Copy file node implementation."""

import logging
import os
import shutil
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


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

    def _validate_source(self, source_path: str) -> tuple[str, bool] | None:
        """Validate source file exists and is a file."""
        if not os.path.exists(source_path):
            logger.error("Source file not found", extra={"source_path": source_path, "phase": "exec"})
            return f"Error: Source file '{source_path}' does not exist. Please check the path.", False

        if not os.path.isfile(source_path):
            logger.error("Source is not a file", extra={"source_path": source_path, "phase": "exec"})
            return (
                f"Error: Source path '{source_path}' is not a file. This node only copies files, not directories.",
                False,
            )
        return None

    def _validate_destination(self, dest_path: str, overwrite: bool, source_path: str) -> tuple[str, bool] | None:
        """Validate destination doesn't exist or can be overwritten."""
        if os.path.exists(dest_path) and not overwrite:
            logger.error(
                "Destination exists, overwrite not allowed",
                extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"},
            )
            return f"Error: Destination file '{dest_path}' already exists. Set overwrite=True to replace it.", False
        return None

    def _check_disk_space(
        self, file_size: int, parent_dir: str | None, source_path: str, dest_path: str
    ) -> tuple[str, bool] | None:
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
                    return (
                        f"Error: Insufficient disk space. Need {file_size} bytes but only {free_bytes} available.",
                        False,
                    )
            except (AttributeError, OSError):
                # statvfs not available on Windows or other error - continue anyway
                pass
        return None

    def exec(self, prep_res: tuple[str, str, bool]) -> tuple[str, bool]:
        """
        Copy file from source to destination with disk space checks.

        Returns:
            Tuple of (result_message, success_bool)
        """
        source_path, dest_path, overwrite = prep_res

        # Validate source
        if error := self._validate_source(source_path):
            return error

        # Validate destination
        if error := self._validate_destination(dest_path, overwrite, source_path):
            return error

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

        # Check disk space
        if disk_error := self._check_disk_space(file_size, parent_dir, source_path, dest_path):
            return disk_error

        # Perform the actual copy
        return self._perform_copy(source_path, dest_path, file_size)

    def _perform_copy(self, source_path: str, dest_path: str, file_size: int) -> tuple[str, bool]:
        """Perform the actual file copy operation."""
        try:
            logger.info("Copying file", extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"})
            # Copy the file preserving metadata
            shutil.copy2(source_path, dest_path)

            logger.info(
                "File copy completed",
                extra={"source_path": source_path, "dest_path": dest_path, "size_bytes": file_size, "phase": "exec"},
            )
        except PermissionError:
            logger.exception(
                "Permission denied during copy",
                extra={"source_path": source_path, "dest_path": dest_path, "phase": "exec"},
            )
            return (
                f"Error: Permission denied when copying '{source_path}' to '{dest_path}'. Check file permissions.",
                False,
            )
        except OSError as e:
            if "No space left" in str(e) or "disk full" in str(e).lower():
                logger.exception(
                    "Disk full during copy",
                    extra={"source_path": source_path, "dest_path": dest_path, "error": str(e), "phase": "exec"},
                )
                return f"Error: No space left on device when copying to '{dest_path}'.", False
            logger.exception(
                "Copy failed",
                extra={"source_path": source_path, "dest_path": dest_path, "error": str(e), "phase": "exec"},
            )
            return f"Error: Failed to copy '{source_path}' to '{dest_path}': {e!s}", False
        except Exception as e:
            logger.warning(
                "Unexpected error, will retry",
                extra={"source_path": source_path, "dest_path": dest_path, "error": str(e), "phase": "exec"},
            )
            # This will trigger retry logic in Node
            raise RuntimeError(f"Error copying from '{source_path}' to '{dest_path}': {e!s}") from e
        else:
            return f"Successfully copied '{source_path}' to '{dest_path}'", True

    def exec_fallback(self, prep_res: tuple[str, str, bool], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        source_path, dest_path, _ = prep_res
        logger.error(
            f"Failed to copy file after {self.max_retries} retries",
            extra={"source_path": source_path, "dest_path": dest_path, "error": str(exc), "phase": "fallback"},
        )
        return (
            f"Error: Could not copy '{source_path}' to '{dest_path}' after {self.max_retries} retries. {exc!s}. Check if files are locked or if there are system issues.",
            False,
        )

    def post(self, shared: dict, prep_res: tuple[str, str, bool], exec_res: tuple[str, bool]) -> str:
        """Update shared store based on result and return action."""
        message, success = exec_res

        if success:
            shared["copied"] = message
            return "default"
        else:
            shared["error"] = message
            return "error"
