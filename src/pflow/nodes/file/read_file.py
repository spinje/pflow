"""Read file node implementation."""

import logging
import os
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


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

        # Normalize the path
        file_path = os.path.expanduser(file_path)  # Expand ~
        file_path = os.path.abspath(file_path)  # Resolve .. and make absolute
        file_path = os.path.normpath(file_path)  # Clean up separators

        # Get encoding with UTF-8 default
        encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")

        logger.debug("Preparing to read file", extra={"file_path": file_path, "encoding": encoding, "phase": "prep"})
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
            logger.error("File not found", extra={"file_path": file_path, "phase": "exec"})
            return f"Error: File '{file_path}' does not exist. Please check the path and try again.", False

        # Log file size for large files
        try:
            file_size = os.path.getsize(file_path)
            if file_size > 1024 * 1024:  # 1MB
                logger.info(
                    "Reading large file",
                    extra={"file_path": file_path, "size_mb": round(file_size / (1024 * 1024), 2), "phase": "exec"},
                )
        except OSError:
            pass  # Continue with read attempt

        try:
            logger.info("Reading file", extra={"file_path": file_path, "encoding": encoding, "phase": "exec"})
            # Read file content
            with open(file_path, encoding=encoding) as f:
                lines = f.readlines()
        except UnicodeDecodeError as e:
            logger.exception(
                "Encoding error", extra={"file_path": file_path, "encoding": encoding, "error": str(e), "phase": "exec"}
            )
            return (
                f"Error: Cannot read '{file_path}' with {encoding} encoding. Try a different encoding or check the file format.",
                False,
            )
        except PermissionError:
            logger.exception("Permission denied", extra={"file_path": file_path, "phase": "exec"})
            return (
                f"Error: Permission denied when reading '{file_path}'. Check file permissions or run with appropriate privileges.",
                False,
            )
        except Exception as e:
            logger.warning(
                "Unexpected error, will retry", extra={"file_path": file_path, "error": str(e), "phase": "exec"}
            )
            # This will trigger retry logic in Node
            raise RuntimeError(f"Error reading file {file_path}: {e!s}") from e
        else:
            # Add 1-indexed line numbers
            numbered_lines = [f"{i + 1}: {line}" for i, line in enumerate(lines)]
            content = "".join(numbered_lines)
            logger.info(
                "File read successfully",
                extra={"file_path": file_path, "size_bytes": len(content), "line_count": len(lines), "phase": "exec"},
            )
            return content, True

    def exec_fallback(self, prep_res: tuple[str, str], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        file_path, _ = prep_res
        logger.error(
            f"Failed to read file after {self.max_retries} retries",
            extra={"file_path": file_path, "error": str(exc), "phase": "fallback"},
        )
        return (
            f"Error: Could not read '{file_path}' after {self.max_retries} retries. {exc!s}. Please check if the file is locked or if there are system issues.",
            False,
        )

    def post(self, shared: dict, prep_res: tuple[str, str], exec_res: tuple[str, bool]) -> str:
        """Update shared store based on result and return action."""
        content_or_error, success = exec_res

        if success:
            shared["content"] = content_or_error
            return "default"
        else:
            shared["error"] = content_or_error
            return "error"
