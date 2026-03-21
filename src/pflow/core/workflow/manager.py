"""Workflow lifecycle management.

Workflows are stored as folders in ~/.pflow/workflows/{name}/ with the
entry point at {name}/{name}.pflow.md. This folder-based structure allows
bundling file dependencies (sub-workflows, prompts, scripts) alongside the
workflow so it remains self-contained when saved.

YAML frontmatter stores system metadata (timestamps, execution stats).
The markdown body is preserved exactly as the author wrote it.

Frontmatter is additive: prepended on save, split on load/update.
The parser extracts the IR dict and description from the markdown body.
"""

import logging
import os
import shutil
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

    Workflows are stored in ~/.pflow/workflows/ as folders, each containing
    an entry point .pflow.md file and any bundled dependencies.
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

    def _workflow_dir(self, name: str) -> Path:
        """Return the directory for a workflow: workflows_dir / name."""
        return self.workflows_dir / name

    def _entry_point(self, name: str) -> Path:
        """Return the entry point file: workflows_dir / name / {name}.pflow.md."""
        return self.workflows_dir / name / f"{name}.pflow.md"

    def _copy_dependencies(self, temp_dir: str, dependencies: Optional[list[tuple[str, Path]]]) -> None:
        """Copy dependency files into the temp bundle directory."""
        if not dependencies:
            return
        temp_dir_resolved = Path(temp_dir).resolve()
        for rel_path, source_path in dependencies:
            dest_path = (Path(temp_dir) / rel_path).resolve()
            if not dest_path.is_relative_to(temp_dir_resolved):
                raise WorkflowValidationError(f"Dependency path '{rel_path}' would escape the bundle directory")
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)

    @staticmethod
    def _build_metadata_dict(name: str, result: Any, fm: dict[str, Any]) -> dict[str, Any]:
        """Build flat metadata dict from parse result and frontmatter."""
        return {
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

    def _atomic_rename(self, name: str, temp_dir: str, target_dir: Path) -> None:
        """Atomically move temp dir to target, cleaning up ghost directories."""
        if target_dir.exists():
            if self._entry_point(name).exists():
                raise WorkflowExistsError(f"Workflow '{name}' already exists")
            # Ghost directory (no entry point) — clean up
            logger.warning(f"Removing ghost directory for '{name}' (no entry point found)")
            shutil.rmtree(target_dir)
        try:
            os.rename(temp_dir, target_dir)
        except OSError:
            if target_dir.exists():
                raise WorkflowExistsError(f"Workflow '{name}' already exists") from None
            raise

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

    def save(
        self,
        name: str,
        markdown_content: str,
        metadata: Optional[dict[str, Any]] = None,
        dependencies: Optional[list[tuple[str, Path]]] = None,
    ) -> str:
        """Save a workflow as a folder with entry point and dependencies.

        Creates workflows_dir/{name}/{name}.pflow.md with frontmatter prepended.
        Optionally copies dependency files into the folder preserving relative paths.
        The entire operation is atomic via temp dir + os.rename().

        Args:
            name: Workflow name (kebab-case, max 50 chars)
            markdown_content: Raw markdown workflow content (no frontmatter)
            metadata: Optional flat metadata fields (keywords, capabilities, etc.)
            dependencies: Optional list of (relative_path_in_bundle, source_absolute_path)
                tuples. Each file is copied into the workflow folder.

        Returns:
            Absolute path of saved entry point file

        Raises:
            WorkflowExistsError: If workflow already exists
            WorkflowValidationError: If name is invalid
        """
        self._validate_workflow_name(name)

        frontmatter = self._build_frontmatter(metadata)
        file_content = self._serialize_with_frontmatter(frontmatter, markdown_content)

        target_dir = self._workflow_dir(name)
        temp_dir = tempfile.mkdtemp(dir=self.workflows_dir, prefix=f".{name}.", suffix=".tmp")

        try:
            # Write entry point file
            entry_point = Path(temp_dir) / f"{name}.pflow.md"
            entry_point.write_text(file_content, encoding="utf-8")

            self._copy_dependencies(temp_dir, dependencies)
            self._atomic_rename(name, temp_dir, target_dir)

            logger.info(f"Saved workflow '{name}' to {target_dir}")
            return str(self._entry_point(name))

        except WorkflowExistsError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            if isinstance(e, WorkflowValidationError):
                raise
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
        file_path = self._entry_point(name)

        if not file_path.exists():
            raise WorkflowNotFoundError(f"Workflow '{name}' not found")

        try:
            content = file_path.read_text(encoding="utf-8")
            result = parse_markdown(content)
            fm = result.metadata or {}
            loaded = self._build_metadata_dict(name, result, fm)
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
        """Get absolute path for a workflow's entry point file.

        Args:
            name: Workflow name

        Returns:
            Absolute path to the entry point file inside the workflow folder
        """
        return str(self._entry_point(name).resolve())

    def list_all(self) -> list[dict[str, Any]]:
        """List all workflows in the directory.

        Returns:
            List of workflow metadata dicts (flat structure), sorted by name
        """
        workflows: list[dict[str, Any]] = []

        if not self.workflows_dir.exists():
            return workflows

        for workflow_dir in sorted(self.workflows_dir.iterdir()):
            if not workflow_dir.is_dir() or workflow_dir.name.startswith("."):
                continue

            name = workflow_dir.name
            entry_point = workflow_dir / f"{name}.pflow.md"
            if not entry_point.exists():
                logger.warning(f"Workflow dir '{name}' missing entry point {name}.pflow.md, skipping")
                continue

            try:
                content = entry_point.read_text(encoding="utf-8")
                result = parse_markdown(content)
                fm = result.metadata or {}
                workflows.append(self._build_metadata_dict(name, result, fm))
            except Exception as e:
                logger.warning(f"Failed to load workflow from {entry_point}: {e}")
                continue

        return workflows

    def exists(self, name: str) -> bool:
        """Check if a workflow exists (directory with valid entry point).

        Args:
            name: Workflow name

        Returns:
            True if workflow exists, False otherwise
        """
        return self._entry_point(name).exists()

    def delete(self, name: str) -> None:
        """Delete a workflow and its entire folder.

        Args:
            name: Workflow name

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        workflow_dir = self._workflow_dir(name)

        if not workflow_dir.is_dir():
            raise WorkflowNotFoundError(f"Workflow '{name}' not found")

        try:
            shutil.rmtree(workflow_dir)
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
        file_path = self._entry_point(name)

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

            # Use workflow dir for temp file so os.replace stays on same filesystem
            temp_fd, temp_path = tempfile.mkstemp(dir=self._workflow_dir(name), prefix=f".{name}.", suffix=".tmp")

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
            raise WorkflowValidationError(f"Failed to update workflow metadata: {e}") from e
