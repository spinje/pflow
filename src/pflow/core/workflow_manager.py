"""Workflow lifecycle management."""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pflow.core.exceptions import WorkflowExistsError, WorkflowNotFoundError, WorkflowValidationError

logger = logging.getLogger(__name__)


class WorkflowManager:
    """Manages workflow lifecycle: save, load, list, delete.

    Workflows are stored in ~/.pflow/workflows/ as JSON files with metadata wrapper.
    """

    def __init__(self, workflows_dir: Optional[Path] = None):
        """Initialize WorkflowManager.

        Args:
            workflows_dir: Directory to store workflows. Defaults to ~/.pflow/workflows/
        """
        if workflows_dir is None:
            workflows_dir = Path("~/.pflow/workflows")

        self.workflows_dir = Path(workflows_dir).expanduser().resolve()

        # Create directory if it doesn't exist
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"WorkflowManager initialized with directory: {self.workflows_dir}")

    def _validate_workflow_name(self, name: str) -> None:
        """Validate workflow name.

        Args:
            name: Workflow name to validate

        Raises:
            WorkflowValidationError: If name is invalid
        """
        if not name:
            raise WorkflowValidationError("Workflow name cannot be empty")
        if len(name) > 50:
            raise WorkflowValidationError("Workflow name cannot exceed 50 characters")
        if "/" in name or "\\" in name:
            raise WorkflowValidationError("Workflow name cannot contain path separators")

        # Check for invalid characters (allow alphanumeric, hyphens, underscores, dots)
        import re

        if not re.match(r"^[a-zA-Z0-9._-]+$", name):
            raise WorkflowValidationError(
                "Workflow name can only contain letters, numbers, dots, hyphens, and underscores"
            )

    def _create_metadata_wrapper(
        self, name: str, workflow_ir: dict[str, Any], description: str, metadata: Optional[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create metadata wrapper for workflow.

        Args:
            name: Workflow name
            workflow_ir: The workflow IR dictionary
            description: Workflow description
            metadata: Optional rich metadata (keywords, capabilities, use cases)

        Returns:
            Metadata wrapper dictionary
        """
        now = datetime.now(timezone.utc).isoformat()

        wrapper = {
            "name": name,
            "description": description,
            "ir": workflow_ir,
            "created_at": now,
            "updated_at": now,
            "version": "1.0.0",
        }

        # Store rich metadata for discovery if available
        if metadata:
            wrapper["rich_metadata"] = metadata

        return wrapper

    def _perform_atomic_save(self, file_path: Path, temp_path: str) -> None:
        """Perform atomic file save operation.

        Args:
            file_path: Target file path
            temp_path: Temporary file path

        Raises:
            WorkflowExistsError: If workflow already exists
            OSError: For other OS-level errors
        """
        try:
            # Create hard link to temp file with target name
            # This will fail with EEXIST if target already exists
            os.link(temp_path, file_path)
            # If successful, remove the temp file
            os.unlink(temp_path)
        except FileExistsError:
            # Clean up temp file and raise our custom error
            os.unlink(temp_path)
            raise WorkflowExistsError(f"Workflow '{file_path.stem}' already exists") from None
        except OSError:
            # Handle other OS errors (disk full, permission denied, etc.)
            # Clean up temp file and re-raise
            Path(temp_path).unlink(missing_ok=True)
            raise

    def save(
        self,
        name: str,
        workflow_ir: dict[str, Any],
        description: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Save a workflow with metadata wrapper.

        Args:
            name: Workflow name (kebab-case, max 50 chars)
            workflow_ir: The workflow IR dictionary
            description: Optional workflow description
            metadata: Optional rich metadata (keywords, capabilities, use cases)

        Returns:
            Absolute path of saved file

        Raises:
            WorkflowExistsError: If workflow already exists
            WorkflowValidationError: If name is invalid
        """
        # Validate name
        self._validate_workflow_name(name)

        # Use provided description or empty string
        final_description = description or ""

        # Create metadata wrapper
        wrapper = self._create_metadata_wrapper(name, workflow_ir, final_description, metadata)

        # Atomic write: write to temp file first, then rename
        file_path = self.workflows_dir / f"{name}.json"
        temp_fd, temp_path = tempfile.mkstemp(dir=self.workflows_dir, prefix=f".{name}.", suffix=".tmp")

        try:
            # Write to temp file
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(wrapper, f, indent=2)

            # Attempt atomic save
            self._perform_atomic_save(file_path, temp_path)

            logger.info(f"Saved workflow '{name}' to {file_path}")
            return str(file_path)

        except WorkflowExistsError:
            # Re-raise workflow exists error
            raise
        except Exception as e:
            # Clean up temp file if it still exists
            Path(temp_path).unlink(missing_ok=True)
            raise WorkflowValidationError(f"Failed to save workflow: {e}") from e

    def load(self, name: str) -> dict[str, Any]:
        """Load workflow with full metadata wrapper.

        Args:
            name: Workflow name

        Returns:
            Full metadata wrapper dict (for Context Builder)

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        file_path = self.workflows_dir / f"{name}.json"

        if not file_path.exists():
            raise WorkflowNotFoundError(f"Workflow '{name}' not found")

        try:
            with open(file_path, encoding="utf-8") as f:
                metadata = json.load(f)

            logger.debug(f"Loaded workflow '{name}' from {file_path}")
            return metadata  # type: ignore[no-any-return]

        except json.JSONDecodeError as e:
            raise WorkflowValidationError(f"Invalid JSON in workflow '{name}': {e}") from e
        except Exception as e:
            raise WorkflowValidationError(f"Failed to load workflow '{name}': {e}") from e

    def load_ir(self, name: str) -> dict[str, Any]:
        """Load just the IR field from a workflow.

        Args:
            name: Workflow name

        Returns:
            Just the IR dict (for WorkflowExecutor)

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        metadata = self.load(name)
        return metadata["ir"]  # type: ignore[no-any-return]

    def get_path(self, name: str) -> str:
        """Get absolute path for a workflow file.

        Args:
            name: Workflow name

        Returns:
            Absolute expanded path for workflow file
        """
        return str((self.workflows_dir / f"{name}.json").resolve())

    def list_all(self) -> list[dict[str, Any]]:
        """List all workflows in the directory.

        Returns:
            List of workflow metadata dicts
        """
        workflows = []

        for file_path in self.workflows_dir.glob("*.json"):
            try:
                with open(file_path, encoding="utf-8") as f:
                    metadata = json.load(f)
                workflows.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to load workflow from {file_path}: {e}")
                continue

        # Sort by name for consistent ordering
        workflows.sort(key=lambda w: w.get("name", ""))

        return workflows

    def exists(self, name: str) -> bool:
        """Check if a workflow exists.

        Args:
            name: Workflow name

        Returns:
            True if workflow exists, False otherwise
        """
        file_path = self.workflows_dir / f"{name}.json"
        return file_path.exists()

    def delete(self, name: str) -> None:
        """Delete a workflow.

        Args:
            name: Workflow name

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        file_path = self.workflows_dir / f"{name}.json"

        if not file_path.exists():
            raise WorkflowNotFoundError(f"Workflow '{name}' not found")

        try:
            file_path.unlink()
            logger.info(f"Deleted workflow '{name}'")
        except Exception as e:
            raise WorkflowValidationError(f"Failed to delete workflow '{name}': {e}") from e

    def update_metadata(self, name: str, updates: dict[str, Any]) -> None:
        """Update workflow metadata after execution.

        Args:
            name: Workflow name
            updates: Dictionary of metadata fields to update
                - execution_count: Will be incremented from current value
                - last_execution_timestamp: Timestamp will be updated
                - Any other rich_metadata fields

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
            WorkflowValidationError: If update fails
        """
        file_path = self.workflows_dir / f"{name}.json"

        if not file_path.exists():
            raise WorkflowNotFoundError(f"Workflow '{name}' not found")

        try:
            # Load existing workflow
            workflow_data = self.load(name)

            # Ensure rich_metadata exists
            if "rich_metadata" not in workflow_data:
                workflow_data["rich_metadata"] = {}

            # Handle execution_count increment specially
            if "execution_count" in updates:
                current_count = workflow_data["rich_metadata"].get("execution_count", 0)
                workflow_data["rich_metadata"]["execution_count"] = current_count + 1
                del updates["execution_count"]  # Remove from updates dict

            # Apply other updates
            workflow_data["rich_metadata"].update(updates)
            workflow_data["updated_at"] = datetime.now(timezone.utc).isoformat()

            # Atomic save using temp file + replace pattern
            temp_fd, temp_path = tempfile.mkstemp(dir=self.workflows_dir, prefix=f".{name}.", suffix=".tmp")

            try:
                # Write to temp file
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(workflow_data, f, indent=2)

                # Atomic replace (unlike save(), this replaces existing file)
                os.replace(temp_path, file_path)

                logger.debug(f"Updated metadata for workflow '{name}'")

            except Exception:
                # Clean up temp file on failure
                Path(temp_path).unlink(missing_ok=True)
                raise

        except WorkflowNotFoundError:
            # Re-raise workflow not found
            raise
        except Exception as e:
            raise WorkflowValidationError(f"Failed to update workflow metadata: {e}") from e
