"""Write file node implementation."""

import contextlib
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


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

        # Normalize the path
        file_path = os.path.expanduser(file_path)  # Expand ~
        file_path = os.path.abspath(file_path)  # Resolve .. and make absolute
        file_path = os.path.normpath(file_path)  # Clean up separators

        # Get encoding with UTF-8 default
        encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")

        # Get append mode (default False)
        append = self.params.get("append", False)

        logger.debug(
            "Preparing to write file",
            extra={
                "file_path": file_path,
                "encoding": encoding,
                "append": append,
                "content_size": len(str(content)),
                "phase": "prep",
            },
        )
        return (str(content), str(file_path), encoding, append)

    def _ensure_parent_directory(self, file_path: str) -> None:
        """Create parent directories if needed."""
        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            logger.debug("Creating parent directories", extra={"dir_path": parent_dir, "phase": "exec"})
            # Let exceptions bubble up - they will be caught by retry mechanism
            os.makedirs(parent_dir, exist_ok=True)

    def _check_disk_space(self, content: str, encoding: str, file_path: str) -> None:
        """Check if there's enough disk space for writing."""
        parent_dir = os.path.dirname(file_path)
        try:
            stat = os.statvfs(parent_dir or ".")
            free_bytes = stat.f_bavail * stat.f_frsize
            content_bytes = len(content.encode(encoding))
            if free_bytes < content_bytes * 2:  # Want at least 2x content size
                logger.error(
                    "Insufficient disk space",
                    extra={
                        "file_path": file_path,
                        "required_bytes": content_bytes,
                        "free_bytes": free_bytes,
                        "phase": "exec",
                    },
                )
                # Raise OSError for disk space issues
                raise OSError(f"No space left on device. Need {content_bytes} bytes but only {free_bytes} available")
        except (AttributeError, OSError) as e:
            if "No space left" in str(e):
                raise  # Re-raise disk space errors
            # statvfs not available on Windows or other error - continue anyway
            pass

    def exec(self, prep_res: tuple[str, str, str, bool]) -> str:
        """
        Write content to file atomically.

        Returns:
            Success message

        Raises:
            PermissionError: If unable to write to file or create directories
            OSError: For disk space or other file system errors
        """
        content, file_path, encoding, append = prep_res

        # Create parent directories if needed
        self._ensure_parent_directory(file_path)

        # Check disk space
        self._check_disk_space(content, encoding, file_path)

        # Log operation start for large content
        if len(content) > 1024 * 1024:  # 1MB
            logger.info(
                "Writing large file",
                extra={"file_path": file_path, "size_mb": round(len(content) / (1024 * 1024), 2), "phase": "exec"},
            )

        if append:
            # For append mode, use direct write (atomic append is complex)
            logger.info("Appending to file", extra={"file_path": file_path, "phase": "exec"})
            # Let exceptions bubble up for retry mechanism
            with open(file_path, "a", encoding=encoding) as f:
                f.write(content)
            logger.info(
                "File append successful",
                extra={"file_path": file_path, "bytes_written": len(content), "phase": "exec"},
            )
            return f"Successfully appended to '{file_path}'"
        else:
            # For write mode, use atomic write with temp file
            return self._atomic_write(file_path, content, encoding)

    def _atomic_write(self, file_path: str, content: str, encoding: str) -> str:
        """Write file atomically using temp file + rename."""
        dir_path = os.path.dirname(file_path) or "."

        # Create temp file in same directory for atomic rename
        temp_fd = None
        temp_path = None

        try:
            temp_fd, temp_path = tempfile.mkstemp(dir=dir_path, text=True)
            logger.debug(
                "Created temp file for atomic write",
                extra={"file_path": file_path, "temp_path": temp_path, "phase": "exec"},
            )

            # Write to temp file
            with os.fdopen(temp_fd, "w", encoding=encoding) as f:
                f.write(content)
                temp_fd = None  # fdopen takes ownership

            # Atomic rename (on same filesystem)
            shutil.move(temp_path, file_path)
            logger.info(
                "File written atomically",
                extra={"file_path": file_path, "temp_path": temp_path, "bytes_written": len(content), "phase": "exec"},
            )

            return f"Successfully wrote to '{file_path}'"

        except Exception:
            # Clean up temp file on error before re-raising
            if temp_fd is not None:
                with contextlib.suppress(Exception):
                    os.close(temp_fd)
            if temp_path and os.path.exists(temp_path):
                with contextlib.suppress(Exception):
                    os.unlink(temp_path)
                    logger.debug("Cleaned up temp file after error", extra={"temp_path": temp_path, "phase": "exec"})
            raise  # Re-raise the exception for retry mechanism

    def exec_fallback(self, prep_res: tuple[str, str, str, bool], exc: Exception) -> str:
        """Handle final failure after all retries with user-friendly messages."""
        _, file_path, _, append = prep_res

        logger.error(
            f"Failed to write file after {self.max_retries} retries",
            extra={"file_path": file_path, "error": str(exc), "phase": "fallback"},
        )

        # Provide specific error messages based on exception type
        if isinstance(exc, PermissionError):
            error_msg = f"Error: Permission denied when writing to '{file_path}'. Check file and directory permissions."
        elif isinstance(exc, OSError) and ("No space left" in str(exc) or "disk full" in str(exc).lower()):
            error_msg = f"Error: No space left on device when writing to '{file_path}'."
        elif isinstance(exc, IsADirectoryError):
            error_msg = f"Error: '{file_path}' is a directory, not a file."
        elif isinstance(exc, FileNotFoundError):
            error_msg = f"Error: Parent directory for '{file_path}' does not exist and could not be created."
        else:
            error_msg = f"Error: Could not write to '{file_path}' after {self.max_retries} retries. {exc!s}. Check if the directory is writable or if there are system issues."

        return error_msg

    def post(self, shared: dict, prep_res: tuple[str, str, str, bool], exec_res: str) -> str:
        """Update shared store based on result and return action."""
        # Check if exec_res is an error message from exec_fallback
        if exec_res.startswith("Error:"):
            shared["error"] = exec_res
            return "error"
        else:
            shared["written"] = exec_res
            return "default"
