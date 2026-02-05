"""Workflow lifecycle management.

Workflows are stored as .pflow.md files with YAML frontmatter for system
metadata (timestamps, execution stats). The markdown body is preserved
exactly as the author wrote it — save/load never modifies content.

Frontmatter is additive: prepended on save, split on load/update.
The parser extracts the IR dict and description from the markdown body.
"""

import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from pflow.core.exceptions import WorkflowExistsError, WorkflowNotFoundError, WorkflowValidationError
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown

logger = logging.getLogger(__name__)


class WorkflowManager:
    """Manages workflow lifecycle: save, load, list, delete.

    Workflows are stored in ~/.pflow/workflows/ as .pflow.md files
    with YAML frontmatter for system metadata.
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

    @staticmethod
    def _name_from_path(file_path: Path) -> str:
        """Derive workflow name from file path, handling .pflow.md double extension.

        Args:
            file_path: Path to a .pflow.md workflow file

        Returns:
            Workflow name (e.g. "my-workflow" from "my-workflow.pflow.md")
        """
        name = file_path.stem
        if name.endswith(".pflow"):
            name = name[:-6]
        return name

    def _validate_workflow_name(self, name: str) -> None:
        """Validate workflow name format.

        Enforces: lowercase letters, numbers, hyphens only, max 50 chars.
        Must start/end with alphanumeric. No consecutive hyphens. No reserved names.

        Args:
            name: Workflow name to validate

        Raises:
            WorkflowValidationError: If name is invalid
        """
        import re

        # Reserved names that could conflict with system functionality
        RESERVED_NAMES = {"null", "undefined", "none", "test", "settings", "registry", "workflow", "mcp", "skill"}

        if not name:
            raise WorkflowValidationError("Workflow name cannot be empty")

        if name.lower() in RESERVED_NAMES:
            reserved_list = ", ".join(sorted(RESERVED_NAMES))
            raise WorkflowValidationError(f"'{name}' is a reserved workflow name. Reserved names: {reserved_list}")

        if len(name) > 50:
            raise WorkflowValidationError("Workflow name cannot exceed 50 characters")

        # Stronger regex: must start/end with alphanumeric, single hyphens only
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", name):
            raise WorkflowValidationError(
                f"Invalid workflow name '{name}'. "
                "Must be lowercase letters, numbers, and single hyphens only. "
                "Must start and end with alphanumeric (no leading/trailing hyphens). "
                "No consecutive hyphens. Example: 'my-workflow' or 'pr-analyzer-v2'"
            )

    def _build_frontmatter(self, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Build frontmatter dict for a new save.

        Args:
            metadata: Optional additional metadata fields (flat, no nesting)

        Returns:
            Frontmatter dict with timestamps, version, and any extra fields
        """
        now = datetime.now(timezone.utc).isoformat()
        frontmatter: dict[str, Any] = {
            "created_at": now,
            "updated_at": now,
            "version": "1.0.0",
        }
        if metadata:
            frontmatter.update(metadata)
        return frontmatter

    def _serialize_with_frontmatter(self, frontmatter: dict[str, Any], markdown_body: str) -> str:
        """Serialize frontmatter and markdown body into a single string.

        Args:
            frontmatter: Frontmatter dict
            markdown_body: Raw markdown content (author's original)

        Returns:
            Complete file content with ---frontmatter--- and body
        """
        fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        return f"---\n{fm_str}---\n\n{markdown_body}"

    def _split_frontmatter_and_body(self, content: str) -> tuple[dict[str, Any], str]:
        """Split a saved workflow file into frontmatter dict and markdown body.

        Args:
            content: Full file content

        Returns:
            (frontmatter_dict, markdown_body) tuple.
            If no frontmatter, returns ({}, full_content).
        """
        lines = content.splitlines(keepends=True)
        if not lines or lines[0].rstrip() != "---":
            return {}, content

        # Find closing ---
        for i in range(1, len(lines)):
            if lines[i].rstrip() == "---":
                fm_text = "".join(lines[1:i])
                body = "".join(lines[i + 1 :])
                # Strip leading newlines from body (we add \n\n on serialize)
                body = body.lstrip("\n")
                try:
                    fm_data = yaml.safe_load(fm_text)
                except yaml.YAMLError:
                    logger.warning("Failed to parse frontmatter YAML, treating as body")
                    return {}, content
                if isinstance(fm_data, dict):
                    return fm_data, body
                return {}, content

        # No closing --- found
        return {}, content

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
            raise WorkflowExistsError(f"Workflow '{self._name_from_path(file_path)}' already exists") from None
        except OSError:
            # Handle other OS errors (disk full, permission denied, etc.)
            # Clean up temp file and re-raise
            Path(temp_path).unlink(missing_ok=True)
            raise

    def save(
        self,
        name: str,
        markdown_content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Save a workflow as .pflow.md with frontmatter.

        The caller must have already validated the markdown content.
        This method prepends frontmatter and writes atomically.

        Args:
            name: Workflow name (kebab-case, max 50 chars)
            markdown_content: Raw markdown workflow content (no frontmatter)
            metadata: Optional flat metadata fields (keywords, capabilities, etc.)

        Returns:
            Absolute path of saved file

        Raises:
            WorkflowExistsError: If workflow already exists
            WorkflowValidationError: If name is invalid
        """
        self._validate_workflow_name(name)

        frontmatter = self._build_frontmatter(metadata)
        file_content = self._serialize_with_frontmatter(frontmatter, markdown_content)

        file_path = self.workflows_dir / f"{name}.pflow.md"
        temp_fd, temp_path = tempfile.mkstemp(dir=self.workflows_dir, prefix=f".{name}.", suffix=".tmp")

        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                f.write(file_content)

            self._perform_atomic_save(file_path, temp_path)

            logger.info(f"Saved workflow '{name}' to {file_path}")
            return str(file_path)

        except WorkflowExistsError:
            raise
        except Exception as e:
            Path(temp_path).unlink(missing_ok=True)
            raise WorkflowValidationError(f"Failed to save workflow: {e}") from e

    def load(self, name: str) -> dict[str, Any]:
        """Load workflow with flat metadata structure.

        Parses the .pflow.md file, extracts frontmatter metadata and IR.
        Returns a flat dict — no rich_metadata wrapper.

        Args:
            name: Workflow name

        Returns:
            Flat metadata dict with fields:
                name, description, ir, created_at, updated_at, version,
                execution_count, last_execution_timestamp, last_execution_success,
                last_execution_duration_seconds, average_execution_duration_seconds,
                last_execution_params, search_keywords, capabilities, typical_use_cases

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        file_path = self.workflows_dir / f"{name}.pflow.md"

        if not file_path.exists():
            raise WorkflowNotFoundError(f"Workflow '{name}' not found")

        try:
            content = file_path.read_text(encoding="utf-8")
            result = parse_markdown(content)

            # Build flat metadata structure from frontmatter
            fm = result.metadata or {}
            loaded: dict[str, Any] = {
                "name": fm.get("name", name),
                "description": result.description or "",
                "ir": result.ir,
                "created_at": fm.get("created_at"),
                "updated_at": fm.get("updated_at"),
                "version": fm.get("version"),
                # Execution tracking (was in rich_metadata, now flat)
                "execution_count": fm.get("execution_count", 0),
                "last_execution_timestamp": fm.get("last_execution_timestamp"),
                "last_execution_success": fm.get("last_execution_success"),
                "last_execution_duration_seconds": fm.get("last_execution_duration_seconds"),
                "average_execution_duration_seconds": fm.get("average_execution_duration_seconds"),
                "last_execution_params": fm.get("last_execution_params"),
                # Discovery metadata (was in rich_metadata, now flat)
                "search_keywords": fm.get("search_keywords"),
                "capabilities": fm.get("capabilities"),
                "typical_use_cases": fm.get("typical_use_cases"),
            }

            logger.debug(f"Loaded workflow '{name}' from {file_path}")
            return loaded

        except MarkdownParseError as e:
            raise WorkflowValidationError(f"Invalid workflow '{name}': {e}") from e
        except Exception as e:
            if isinstance(e, WorkflowValidationError):
                raise
            raise WorkflowValidationError(f"Failed to load workflow '{name}': {e}") from e

    def load_ir(self, name: str) -> dict[str, Any]:
        """Load just the IR dict from a workflow.

        Args:
            name: Workflow name

        Returns:
            The IR dict (for WorkflowExecutor)

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
        return str((self.workflows_dir / f"{name}.pflow.md").resolve())

    def list_all(self) -> list[dict[str, Any]]:
        """List all workflows in the directory.

        Returns:
            List of workflow metadata dicts (flat structure)
        """
        workflows = []

        for file_path in self.workflows_dir.glob("*.pflow.md"):
            try:
                name = self._name_from_path(file_path)
                content = file_path.read_text(encoding="utf-8")
                result = parse_markdown(content)
                fm = result.metadata or {}

                workflow_meta: dict[str, Any] = {
                    "name": fm.get("name", name),
                    "description": result.description or "",
                    "ir": result.ir,
                    "created_at": fm.get("created_at"),
                    "updated_at": fm.get("updated_at"),
                    "version": fm.get("version"),
                    "execution_count": fm.get("execution_count", 0),
                    "last_execution_timestamp": fm.get("last_execution_timestamp"),
                    "last_execution_success": fm.get("last_execution_success"),
                    "last_execution_duration_seconds": fm.get("last_execution_duration_seconds"),
                    "average_execution_duration_seconds": fm.get("average_execution_duration_seconds"),
                    "last_execution_params": fm.get("last_execution_params"),
                    "search_keywords": fm.get("search_keywords"),
                    "capabilities": fm.get("capabilities"),
                    "typical_use_cases": fm.get("typical_use_cases"),
                }
                workflows.append(workflow_meta)
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
        file_path = self.workflows_dir / f"{name}.pflow.md"
        return file_path.exists()

    def delete(self, name: str) -> None:
        """Delete a workflow.

        Args:
            name: Workflow name

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        file_path = self.workflows_dir / f"{name}.pflow.md"

        if not file_path.exists():
            raise WorkflowNotFoundError(f"Workflow '{name}' not found")

        try:
            file_path.unlink()
            logger.info(f"Deleted workflow '{name}'")
        except Exception as e:
            raise WorkflowValidationError(f"Failed to delete workflow '{name}': {e}") from e

    def update_metadata(self, name: str, updates: dict[str, Any]) -> None:
        """Update workflow frontmatter metadata after execution.

        Reads the file, splits frontmatter from body, updates fields,
        reassembles, and writes atomically. The markdown body is NEVER modified.

        Args:
            name: Workflow name
            updates: Dictionary of metadata fields to update
                - execution_count: Will be incremented from current value
                - last_execution_timestamp: Timestamp will be updated
                - Any other metadata fields

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
            WorkflowValidationError: If update fails
        """
        file_path = self.workflows_dir / f"{name}.pflow.md"

        if not file_path.exists():
            raise WorkflowNotFoundError(f"Workflow '{name}' not found")

        try:
            content = file_path.read_text(encoding="utf-8")
            frontmatter, body = self._split_frontmatter_and_body(content)

            # Handle execution_count increment specially
            if "execution_count" in updates:
                current_count = frontmatter.get("execution_count", 0)
                new_count = current_count + 1
                frontmatter["execution_count"] = new_count
                del updates["execution_count"]

                # Update average duration if duration is provided
                if "last_execution_duration_seconds" in updates:
                    new_duration = updates["last_execution_duration_seconds"]
                    current_avg = frontmatter.get("average_execution_duration_seconds")

                    if current_avg is None or current_count == 0:
                        # First execution, average equals the duration
                        frontmatter["average_execution_duration_seconds"] = new_duration
                    else:
                        # Running average formula: new_avg = old_avg + (new_value - old_avg) / new_count
                        new_avg = current_avg + (new_duration - current_avg) / new_count
                        frontmatter["average_execution_duration_seconds"] = round(new_avg, 2)

            # Apply other updates
            frontmatter.update(updates)
            frontmatter["updated_at"] = datetime.now(timezone.utc).isoformat()

            # Reassemble and write atomically
            new_content = self._serialize_with_frontmatter(frontmatter, body)

            temp_fd, temp_path = tempfile.mkstemp(dir=self.workflows_dir, prefix=f".{name}.", suffix=".tmp")

            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    f.write(new_content)

                os.replace(temp_path, file_path)
                logger.debug(f"Updated metadata for workflow '{name}'")

            except Exception:
                Path(temp_path).unlink(missing_ok=True)
                raise

        except WorkflowNotFoundError:
            raise
        except Exception as e:
            if isinstance(e, WorkflowNotFoundError):
                raise
            raise WorkflowValidationError(f"Failed to update workflow metadata: {e}") from e

    def update_ir(self, name: str, new_ir: dict[str, Any]) -> None:
        """Update just the IR of an existing workflow, preserving metadata.

        DEPRECATED: Only caller was the repair save handler, which is gated
        pending markdown format migration (Task 107). Preserved for backwards
        compatibility but unreachable from production code.

        Args:
            name: Workflow name
            new_ir: New workflow IR to replace the existing one

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
            WorkflowValidationError: If update fails
        """
        if not self.exists(name):
            raise WorkflowNotFoundError(f"Workflow '{name}' does not exist")

        try:
            # Load existing workflow
            workflow_data = self.load(name)

            # update_ir is gated — repair system is the only caller and it's disabled.
            # This method is preserved but should not be called in production.
            logger.warning(f"update_ir called for '{name}' — this method is deprecated (Task 107)")
            _ = workflow_data  # Acknowledge loaded data
            _ = new_ir  # Acknowledge new IR

        except WorkflowNotFoundError:
            raise
        except Exception as e:
            raise WorkflowValidationError(f"Failed to update workflow IR: {e}") from e
