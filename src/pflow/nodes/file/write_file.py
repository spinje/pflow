"""Write file node implementation."""

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

    def exec(self, prep_res: tuple[str, str, str, bool]) -> tuple[str, bool]:
        """
        Write content to file atomically.

        Returns:
            Tuple of (result_message, success_bool)
        """
        content, file_path, encoding, append = prep_res

        # Create parent directories if needed
        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            try:
                logger.debug("Creating parent directories", extra={"dir_path": parent_dir, "phase": "exec"})
                os.makedirs(parent_dir, exist_ok=True)
            except PermissionError:
                logger.error("Permission denied creating directory", extra={"dir_path": parent_dir, "phase": "exec"})
                return (
                    f"Error: Permission denied when creating directory '{parent_dir}'. Check permissions or run with appropriate privileges.",
                    False,
                )
            except OSError as e:
                logger.error(
                    "Failed to create directory", extra={"dir_path": parent_dir, "error": str(e), "phase": "exec"}
                )
                return f"Error: Cannot create directory '{parent_dir}': {e!s}", False

        # Check disk space (basic check)
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
                return (
                    f"Error: Insufficient disk space. Need {content_bytes} bytes but only {free_bytes} available.",
                    False,
                )
        except (AttributeError, OSError):
            # statvfs not available on Windows or other error - continue anyway
            pass

        # Log operation start for large content
        if len(content) > 1024 * 1024:  # 1MB
            logger.info(
                "Writing large file",
                extra={"file_path": file_path, "size_mb": round(len(content) / (1024 * 1024), 2), "phase": "exec"},
            )

        if append:
            # For append mode, use direct write (atomic append is complex)
            try:
                logger.info("Appending to file", extra={"file_path": file_path, "phase": "exec"})
                with open(file_path, "a", encoding=encoding) as f:
                    f.write(content)
                logger.info(
                    "File append successful",
                    extra={"file_path": file_path, "bytes_written": len(content), "phase": "exec"},
                )
                return f"Successfully appended to '{file_path}'", True
            except PermissionError:
                logger.error("Permission denied", extra={"file_path": file_path, "phase": "exec"})
                return f"Error: Permission denied when writing to '{file_path}'. Check file permissions.", False
            except OSError as e:
                if "No space left" in str(e) or "disk full" in str(e).lower():
                    logger.error("Disk full", extra={"file_path": file_path, "error": str(e), "phase": "exec"})
                    return f"Error: No space left on device when writing to '{file_path}'.", False
                logger.error("Write failed", extra={"file_path": file_path, "error": str(e), "phase": "exec"})
                return f"Error: Failed to write to '{file_path}': {e!s}", False
            except Exception as e:
                logger.warning(
                    "Unexpected error, will retry", extra={"file_path": file_path, "error": str(e), "phase": "exec"}
                )
                raise RuntimeError(f"Error writing file {file_path}: {e!s}") from e
        else:
            # For write mode, use atomic write with temp file
            return self._atomic_write(file_path, content, encoding)

    def _atomic_write(self, file_path: str, content: str, encoding: str) -> tuple[str, bool]:
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
            return f"Successfully wrote to '{file_path}'", True

        except PermissionError:
            logger.error(
                "Permission denied during atomic write",
                extra={"file_path": file_path, "temp_path": temp_path, "phase": "exec"},
            )
            return f"Error: Permission denied when writing to '{file_path}'. Check directory permissions.", False
        except OSError as e:
            if "No space left" in str(e) or "disk full" in str(e).lower():
                logger.error(
                    "Disk full during atomic write",
                    extra={"file_path": file_path, "temp_path": temp_path, "error": str(e), "phase": "exec"},
                )
                return f"Error: No space left on device when writing to '{file_path}'.", False
            logger.error(
                "Atomic write failed",
                extra={"file_path": file_path, "temp_path": temp_path, "error": str(e), "phase": "exec"},
            )
            return f"Error: Failed to write to '{file_path}': {e!s}", False
        except Exception as e:
            logger.warning(
                "Unexpected error during atomic write, will retry",
                extra={"file_path": file_path, "temp_path": temp_path, "error": str(e), "phase": "exec"},
            )
            raise RuntimeError(f"Error during atomic write to {file_path}: {e!s}") from e
        finally:
            # Clean up temp file if still exists
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except:
                    pass
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                    logger.debug("Cleaned up temp file", extra={"temp_path": temp_path, "phase": "exec"})
                except:
                    pass

    def exec_fallback(self, prep_res: tuple[str, str, str, bool], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        _, file_path, _, _ = prep_res
        logger.error(
            f"Failed to write file after {self.max_retries} retries",
            extra={"file_path": file_path, "error": str(exc), "phase": "fallback"},
        )
        return (
            f"Error: Could not write to '{file_path}' after {self.max_retries} retries. {exc!s}. Check if the directory is writable or if there are system issues.",
            False,
        )

    def post(self, shared: dict, prep_res: tuple[str, str, str, bool], exec_res: tuple[str, bool]) -> str:
        """Update shared store based on result and return action."""
        message, success = exec_res

        if success:
            shared["written"] = message
            return "default"
        else:
            shared["error"] = message
            return "error"
