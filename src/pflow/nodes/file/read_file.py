"""Read file node implementation."""

import base64
import logging
import os
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pflow.pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


class ReadFileNode(Node):
    """
    Read content from a file and add line numbers for display.

    This node reads a text file and formats it with 1-indexed line numbers,
    following the Tutorial-Cursor pattern for file display.

    Interface:
    - Params: file_path: str  # Path to the file to read
    - Params: encoding: str  # File encoding (optional, default: utf-8)
    - Writes: shared["content"]: str  # File contents (with line numbers for text, base64-encoded for binary)
    - Writes: shared["content_is_binary"]: bool  # True if content is binary data
    - Writes: shared["file_path"]: str  # Path that was read
    - Writes: shared["error"]: str  # Error message if operation failed
    - Actions: default (success), error (failure)

    Security Note: This node can read ANY accessible file on the system.
    Do not expose to untrusted input without proper validation.
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient file access issues."""
        super().__init__(max_retries=3, wait=0.1)

    def prep(self, shared: dict) -> tuple[str, str]:
        """Extract file path and encoding from shared store or params."""
        # Get file path from params
        file_path = self.params.get("file_path")
        if not file_path:
            raise ValueError("Missing required 'file_path' parameter")

        # Normalize the path
        file_path = os.path.expanduser(file_path)  # Expand ~
        file_path = os.path.abspath(file_path)  # Resolve .. and make absolute
        file_path = os.path.normpath(file_path)  # Clean up separators

        # Get encoding with UTF-8 default
        encoding = self.params.get("encoding", "utf-8")

        logger.debug("Preparing to read file", extra={"file_path": file_path, "encoding": encoding, "phase": "prep"})
        return (str(file_path), encoding)

    def exec(self, prep_res: tuple[str, str]) -> str | bytes:
        """
        Read file content and add line numbers for text files, or read as binary.

        Returns:
            File content with line numbers (text) or raw bytes (binary)

        Raises:
            FileNotFoundError: If file doesn't exist
            PermissionError: If file cannot be read due to permissions
            OSError: For other file system errors
        """
        file_path, encoding = prep_res

        # Check if file exists
        if not os.path.exists(file_path):
            logger.error("File not found", extra={"file_path": file_path, "phase": "exec"})
            raise FileNotFoundError(f"File '{file_path}' does not exist")

        # Binary extension detection
        BINARY_EXTENSIONS = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".ico",
            ".webp",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".7z",
            ".rar",
            ".mp3",
            ".mp4",
            ".wav",
            ".avi",
            ".mov",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".woff",
            ".woff2",
            ".ttf",
            ".bin",
            ".dat",
        }

        path = Path(file_path)
        file_ext = path.suffix.lower()
        is_binary_ext = file_ext in BINARY_EXTENSIONS

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

        # Read file based on detection
        if is_binary_ext:
            # Known binary extension - read as binary directly
            logger.info("Reading binary file", extra={"file_path": file_path, "phase": "exec"})
            binary_content = path.read_bytes()
            self._is_binary = True

            logger.info(
                "Binary file read successfully",
                extra={"file_path": file_path, "size_bytes": len(binary_content), "phase": "exec"},
            )
            return binary_content
        else:
            # Try text read first
            try:
                logger.info("Reading text file", extra={"file_path": file_path, "encoding": encoding, "phase": "exec"})

                with open(file_path, encoding=encoding) as f:
                    lines = f.readlines()

                # Add 1-indexed line numbers
                numbered_lines = [f"{i + 1}: {line}" for i, line in enumerate(lines)]
                text_content = "".join(numbered_lines)
                self._is_binary = False

                logger.info(
                    "Text file read successfully",
                    extra={
                        "file_path": file_path,
                        "size_bytes": len(text_content),
                        "line_count": len(lines),
                        "phase": "exec",
                    },
                )
                return text_content

            except UnicodeDecodeError:
                # Binary file with text extension - fallback to binary
                logger.info(
                    "Text decode failed, reading as binary",
                    extra={"file_path": file_path, "encoding": encoding, "phase": "exec"},
                )
                binary_content = path.read_bytes()
                self._is_binary = True

                logger.info(
                    "Binary file read successfully (after decode error)",
                    extra={"file_path": file_path, "size_bytes": len(binary_content), "phase": "exec"},
                )
                return binary_content

    def exec_fallback(self, prep_res: tuple[str, str], exc: Exception) -> str:
        """Handle final failure after all retries with user-friendly messages."""
        file_path, encoding = prep_res

        logger.error(
            f"Failed to read file after {self.max_retries} retries",
            extra={"file_path": file_path, "error": str(exc), "phase": "fallback"},
        )

        # Provide specific error messages based on exception type
        if isinstance(exc, FileNotFoundError):
            error_msg = f"Error: File '{file_path}' does not exist. Please check the path and try again."
        elif isinstance(exc, UnicodeDecodeError):
            error_msg = f"Error: Cannot read '{file_path}' with {encoding} encoding. Try a different encoding or check the file format."
        elif isinstance(exc, PermissionError):
            error_msg = f"Error: Permission denied when reading '{file_path}'. Check file permissions or run with appropriate privileges."
        elif isinstance(exc, IsADirectoryError):
            error_msg = f"Error: '{file_path}' is a directory, not a file."
        else:
            error_msg = f"Error: Could not read '{file_path}' after {self.max_retries} retries. {exc!s}. Please check if the file is locked or if there are system issues."

        # Return error message that will be stored in shared["error"]
        return error_msg

    def post(self, shared: dict, prep_res: tuple[str, str], exec_res: str | bytes) -> str:
        """Update shared store based on result and return action."""
        # Check if exec_res is an error message from exec_fallback
        if isinstance(exec_res, str) and exec_res.startswith("Error:"):
            shared["error"] = exec_res
            return "error"

        # Handle binary encoding
        if hasattr(self, "_is_binary") and self._is_binary:
            # Binary content - base64 encode
            assert isinstance(exec_res, bytes), "Binary content must be bytes"  # Type narrowing for mypy  # noqa: S101
            encoded = base64.b64encode(exec_res).decode("ascii")
            shared["content"] = encoded
            shared["content_is_binary"] = True
        else:
            # Text content - store as-is
            assert isinstance(exec_res, str), "Text content must be str"  # Type narrowing for mypy  # noqa: S101
            shared["content"] = exec_res
            shared["content_is_binary"] = False

        # Store file path
        shared["file_path"] = prep_res[0]

        return "default"
