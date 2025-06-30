"""Delete file node implementation."""

import logging
import os
import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node

logger = logging.getLogger(__name__)


class DeleteFileNode(Node):
    """
    Delete a file from the filesystem with safety confirmation.

    This node deletes a file only when explicitly confirmed via the shared store.
    Treats non-existent files as success for idempotent behavior.

    Interface:
    - Reads: shared["file_path"] (required), shared["confirm_delete"] (required)
    - Writes: shared["deleted"] on success, shared["error"] on failure
    - Params: file_path (as fallback if not in shared)
    - Actions: default (success), error (failure)

    Security Note: This node can delete ANY accessible file on the system.
    Do not expose to untrusted input without proper validation.
    WARNING: Deletion is permanent and cannot be undone.

    Safety Note: The confirm_delete flag MUST be set in shared store.
    It cannot be provided via params to prevent accidental deletions.
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient file access issues."""
        super().__init__(max_retries=3, wait=0.1)

    def prep(self, shared: dict) -> tuple[str, bool]:
        """Extract file path and confirmation flag from shared store."""
        # File path is required
        file_path = shared.get("file_path") or self.params.get("file_path")
        if not file_path:
            raise ValueError("Missing required 'file_path' in shared store or params")

        # Normalize the path
        file_path = os.path.expanduser(file_path)
        file_path = os.path.abspath(file_path)
        file_path = os.path.normpath(file_path)

        # Confirmation flag MUST come from shared store only (not params)
        if "confirm_delete" not in shared:
            raise ValueError(
                "Missing required 'confirm_delete' in shared store. "
                "This safety flag must be explicitly set in shared store."
            )

        confirm_delete = shared["confirm_delete"]

        logger.debug(
            "Preparing to delete file",
            extra={"file_path": file_path, "confirm_delete": confirm_delete, "phase": "prep"},
        )

        return (str(file_path), bool(confirm_delete))

    def exec(self, prep_res: tuple[str, bool]) -> tuple[str, bool]:
        """
        Delete file if confirmed.

        Returns:
            Tuple of (result_message, success_bool)
        """
        file_path, confirm_delete = prep_res

        # Check confirmation
        if not confirm_delete:
            logger.error(
                "Delete not confirmed",
                extra={"file_path": file_path, "confirm_delete": confirm_delete, "phase": "exec"},
            )
            return (
                f"Error: Deletion of '{file_path}' not confirmed. Set shared['confirm_delete'] = True to confirm.",
                False,
            )

        # Check if file exists
        if not os.path.exists(file_path):
            # Idempotent behavior - already deleted is success
            logger.info("File does not exist (idempotent success)", extra={"file_path": file_path, "phase": "exec"})
            return f"Successfully deleted '{file_path}' (file did not exist)", True

        # Check if it's actually a file (not directory)
        if not os.path.isfile(file_path):
            logger.error("Path is not a file", extra={"file_path": file_path, "phase": "exec"})
            return f"Error: Path '{file_path}' is not a file. This node only deletes files, not directories.", False

        # Get file info for logging
        try:
            file_size = os.path.getsize(file_path)
            logger.info("Deleting file", extra={"file_path": file_path, "size_bytes": file_size, "phase": "exec"})
        except OSError:
            file_size = 0

        try:
            # Delete the file
            os.remove(file_path)
            # Log the deletion for audit trail
            logger.info(
                "File deleted successfully",
                extra={"file_path": file_path, "size_bytes": file_size, "action": "deleted", "phase": "exec"},
            )
        except PermissionError:
            logger.error("Permission denied", extra={"file_path": file_path, "phase": "exec"})
            return (
                f"Error: Permission denied when deleting '{file_path}'. Check file permissions or run with appropriate privileges.",
                False,
            )
        except OSError as e:
            # Handle race condition where file was deleted between check and delete
            if not os.path.exists(file_path):
                logger.info(
                    "File deleted by another process (race condition)", extra={"file_path": file_path, "phase": "exec"}
                )
                return f"Successfully deleted '{file_path}' (deleted by another process)", True
            logger.error("Delete failed", extra={"file_path": file_path, "error": str(e), "phase": "exec"})
            return f"Error: Failed to delete '{file_path}': {e!s}", False
        except Exception as e:
            logger.warning(
                "Unexpected error, will retry", extra={"file_path": file_path, "error": str(e), "phase": "exec"}
            )
            # This will trigger retry logic in Node
            raise RuntimeError(f"Error deleting file '{file_path}': {e!s}") from e
        else:
            return f"Successfully deleted '{file_path}'", True

    def exec_fallback(self, prep_res: tuple[str, bool], exc: Exception) -> tuple[str, bool]:
        """Handle final failure after all retries."""
        file_path, _ = prep_res
        logger.error(
            f"Failed to delete file after {self.max_retries} retries",
            extra={"file_path": file_path, "error": str(exc), "phase": "fallback"},
        )
        return (
            f"Error: Could not delete '{file_path}' after {self.max_retries} retries. {exc!s}. Check if the file is locked or if there are system issues.",
            False,
        )

    def post(self, shared: dict, prep_res: tuple[str, bool], exec_res: tuple[str, bool]) -> str:
        """Update shared store based on result and return action."""
        message, success = exec_res

        if success:
            shared["deleted"] = message
            return "default"
        else:
            shared["error"] = message
            return "error"
