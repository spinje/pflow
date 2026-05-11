"""Shared workflow save operations for CLI and MCP.

This module provides unified workflow save functionality used by both
the CLI and MCP server, eliminating code duplication while maintaining
separate interfaces optimized for each use case.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from pflow.core.diagnostic import Severity
from pflow.core.exceptions import MarkdownParseError, WorkflowValidationError
from pflow.core.ir_schema import normalize_ir, validate_ir
from pflow.core.markdown_parser import parse_markdown
from pflow.core.workflow.manager import WorkflowManager

logger = logging.getLogger(__name__)

# Reserved names that could conflict with system functionality
RESERVED_WORKFLOW_NAMES: frozenset[str] = frozenset({
    # CLI commands
    "null",
    "undefined",
    "none",
    "test",
    "list",
    "find",
    "describe",
    "history",
    "save",
    "guide",
    "probe",
    "run",
    "read-fields",
    "mcp",
    "skill",
    "settings",
    "trace",
    "report",
    "visualize",
    "registry",
    "workflow",
    "instructions",
    # Guide topic names (pflow guide <topic>)
    "core",
    "http",
    "llm",
    "code",
    "shell",
    "file",
    "batch",
    "branching",
    "sub-workflows",
    "prompt-caching",
    "caching",
})


def validate_workflow_name(name: str) -> tuple[bool, Optional[str]]:
    """Validate workflow name meets format requirements.

    Unified validation used by both CLI and MCP. Uses CLI rules (50 char max,
    reserved names) as the baseline to avoid breaking existing workflows.

    Rules:
    - Lowercase letters, numbers, and hyphens only
    - Maximum 50 characters
    - Must start and end with alphanumeric (no leading/trailing hyphens)
    - No consecutive hyphens (--) allowed
    - Cannot use reserved system names

    Args:
        name: Workflow name to validate

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if valid
        - (False, error_message) if invalid
    """
    import re

    # Check empty
    if not name:
        return False, "Workflow name cannot be empty"

    # Check reserved names (case-insensitive)
    if name.lower() in RESERVED_WORKFLOW_NAMES:
        reserved_list = ", ".join(sorted(RESERVED_WORKFLOW_NAMES))
        return False, f"'{name}' is a reserved workflow name. Reserved names: {reserved_list}"

    # Check length (CLI limit of 50 chars)
    if len(name) > 50:
        return False, "Workflow name cannot exceed 50 characters"

    # Validate pattern: lowercase, numbers, single hyphens only
    # Must start/end with alphanumeric
    if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", name):
        return (
            False,
            "Name must contain only lowercase letters, numbers, and single hyphens. "
            "Must start and end with alphanumeric (no leading/trailing hyphens). "
            "No consecutive hyphens. Example: 'my-workflow' or 'pr-analyzer-v2'",
        )

    return True, None


def _resolve_for_validation(workflow_ir: dict[str, Any], source_path: Optional[Path]) -> dict[str, Any]:
    """Return an IR copy with file references resolved, for validation only.

    The input IR keeps its literal file path strings (e.g.
    ``params.prompt = './creative-direction.md'``) so
    ``_discover_and_bundle_deps`` can still see them and bundle the files.
    Without this split, save would either skip file-content-aware checks
    (the original gap that motivated Task 159 follow-up) or break bundling
    (file paths get replaced with content before discovery scans the IR).

    Falls through to the original IR if resolution can't run (no
    ``source_path``) or raises (missing files, YAML errors). Downstream
    layers diagnose those failures via ``MarkdownParseError`` /
    ``CompilationError`` — this layer's job is just to expose the file
    content for content-aware validators when resolution succeeds.
    """
    if source_path is None:
        return workflow_ir
    try:
        import copy

        from pflow.core.file_resolver import resolve_file_references

        validation_ir = copy.deepcopy(workflow_ir)
        resolve_file_references(validation_ir, source_path.parent)
        return validation_ir
    except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        logger.debug(
            "Save-path file-reference resolution skipped (%s); missing-file errors surface elsewhere.",
            exc,
        )
    except Exception:
        logger.debug("Save-path file-reference resolution raised; skipping silently", exc_info=True)
    return workflow_ir


def _validate_and_normalize_ir(
    workflow_ir: dict[str, Any],
    auto_normalize: bool,
    source_desc: str,
    source_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Validate and optionally normalize workflow IR.

    Performs comprehensive validation:
    1. IR schema validation (structure, required fields)
    2. WorkflowValidator validation (data flow, output sources, node types)

    Args:
        workflow_ir: Workflow IR to validate
        auto_normalize: Whether to auto-add missing fields
        source_desc: Description of source for error messages
        source_path: Path to the workflow file, for resolving relative
            sub-workflow references during validation

    Returns:
        Validated workflow IR

    Raises:
        ValueError: If IR validation fails
        WorkflowValidationError: If comprehensive validation fails
    """
    if auto_normalize:
        normalize_ir(workflow_ir)

    # Step 1: IR schema validation
    try:
        validate_ir(workflow_ir)
    except Exception as e:
        if "Invalid workflow" in source_desc:
            raise WorkflowValidationError(f"{source_desc}: {e}") from e
        raise ValueError(f"{source_desc}: {e}") from e

    # Step 1.5: build a separate copy with file references resolved, used
    # ONLY for downstream validation. See ``_resolve_for_validation``.
    validation_ir = _resolve_for_validation(workflow_ir, source_path)

    # Step 2: Comprehensive workflow validation (data flow, output sources, node types)
    from pflow.core.validation_utils import generate_dummy_parameters
    from pflow.core.workflow.validator import WorkflowValidator
    from pflow.registry import Registry

    try:
        # Generate dummy parameters for template validation
        # This enables structural validation without requiring real parameter values
        inputs = validation_ir.get("inputs", {})
        dummy_params = generate_dummy_parameters(inputs)

        registry = Registry()
        validator_diagnostics = WorkflowValidator.validate(
            workflow_ir=validation_ir,
            extracted_params=dummy_params,  # Use dummy params for template validation
            registry=registry,
            skip_node_types=False,  # Validate node types
            workflow_file=source_path,
        )
        errors = [diagnostic for diagnostic in validator_diagnostics if diagnostic.severity == Severity.ERROR]

        if errors:
            summary = f"{source_desc} - Validation errors:\n" + "\n".join(
                f"  {i}. {diagnostic.message}" for i, diagnostic in enumerate(errors, 1)
            )
            raise WorkflowValidationError(summary=summary, validation_errors=errors)

        return workflow_ir
    except WorkflowValidationError:
        raise
    except Exception as e:
        if "Invalid workflow" in source_desc:
            raise WorkflowValidationError(f"{source_desc}: Validation failed: {e}") from e
        raise ValueError(f"{source_desc}: Validation failed: {e}") from e


def _load_from_dict(source: dict[str, Any], auto_normalize: bool) -> dict[str, Any]:
    """Load workflow from dict source.

    Args:
        source: Dict containing workflow IR
        auto_normalize: Whether to auto-add missing fields

    Returns:
        Validated workflow IR
    """
    # Extract IR if wrapped (legacy compatibility)
    workflow_ir = source.get("ir", source)
    return _validate_and_normalize_ir(workflow_ir, auto_normalize, "Invalid workflow IR")


def _load_from_file(path: Path, auto_normalize: bool) -> dict[str, Any]:
    """Load workflow from a .pflow.md file path.

    Args:
        path: Path to .pflow.md file
        auto_normalize: Whether to auto-add missing fields

    Returns:
        Validated workflow IR

    Raises:
        ValueError: If file cannot be loaded or is invalid
        WorkflowValidationError: If IR validation fails
    """
    try:
        content = path.read_text(encoding="utf-8")
        result = parse_markdown(content)
        return _validate_and_normalize_ir(result.ir, auto_normalize, f"Invalid workflow in {path}", source_path=path)

    except MarkdownParseError as e:
        raise ValueError(f"Invalid workflow in {path}: {e}") from e
    except (ValueError, WorkflowValidationError):
        raise
    except Exception as e:
        raise ValueError(f"Failed to load workflow from {path}: {e}") from e


def _load_from_workflow_name(name: str, auto_normalize: bool) -> dict[str, Any]:
    """Load workflow from WorkflowManager by name.

    Args:
        name: Workflow name
        auto_normalize: Whether to auto-add missing fields

    Returns:
        Validated workflow IR

    Raises:
        WorkflowValidationError: If IR validation fails
    """
    manager = WorkflowManager()
    workflow_ir = manager.load_ir(name)
    entry_point = Path(manager.get_path(name))
    return _validate_and_normalize_ir(
        workflow_ir, auto_normalize, f"Invalid workflow '{name}'", source_path=entry_point
    )


def load_and_validate_workflow(
    source: str | dict[str, Any],
    auto_normalize: bool = True,
) -> dict[str, Any]:
    """Load workflow from any source and validate IR structure.

    Handles three input types:
    1. Dict: Use directly as IR (or extract from metadata wrapper)
    2. File path: Load from .pflow.md file
    3. Workflow name: Load from WorkflowManager

    Args:
        source: File path (str), workflow name (str), or IR dict
        auto_normalize: Whether to auto-add missing fields (ir_version, edges)

    Returns:
        Validated workflow IR dict

    Raises:
        TypeError: If source is not str or dict
        ValueError: If workflow cannot be loaded or is invalid
        FileNotFoundError: If file doesn't exist
        WorkflowValidationError: If IR validation fails
    """
    # Case 1: Dict input
    if isinstance(source, dict):
        return _load_from_dict(source, auto_normalize)

    # Case 2 & 3: String input (file path or workflow name)
    if not isinstance(source, str):
        raise TypeError(f"Source must be str or dict, got {type(source)}")

    # Try as file path first
    path = Path(source)
    if path.exists():
        return _load_from_file(path, auto_normalize)

    # Try as workflow name
    manager = WorkflowManager()
    if manager.exists(source):
        return _load_from_workflow_name(source, auto_normalize)

    # Not found anywhere
    raise ValueError(f"Workflow not found: {source} (not a file or saved workflow)")


def _discover_and_bundle_deps(
    name: str, workflow_ir: dict[str, Any], source_path: Path
) -> tuple[Optional[list[tuple[str, Path]]], list[str]]:
    """Discover file dependencies and compute bundle-relative paths.

    Args:
        name: Workflow name (for error messages)
        workflow_ir: Parsed and validated workflow IR
        source_path: Path to the source workflow file

    Returns:
        Tuple of (dependencies_for_save, bundled_file_display_list)

    Raises:
        WorkflowValidationError: If dependency discovery fails on missing files
    """
    from pflow.core.workflow.dependency_discovery import discover_dependencies

    try:
        parent_base = source_path.parent.resolve()
        deps = discover_dependencies(workflow_ir, parent_base)
        if not deps:
            return None, []

        # Compute bundle-relative paths from the parent workflow's directory,
        # not from whichever sub-workflow discovered the dependency.
        # This ensures files from nested sub-workflows land at the correct
        # relative position so all references resolve from the bundle root.
        dep_tuples: list[tuple[str, Path]] = []
        for dep in deps:
            try:
                rel = str(dep.absolute_path.relative_to(parent_base))
            except ValueError:
                raise WorkflowValidationError(
                    f"Cannot bundle dependency '{dep.relative_path}' "
                    f"(node '{dep.source_node_id}', param '{dep.source_param}'): "
                    f"file is outside the workflow's directory.\n"
                    f"  Resolved to: {dep.absolute_path}\n"
                    f"  Workflow dir: {parent_base}\n"
                    f"Move the file into the workflow's directory tree, "
                    f"or use an absolute path (which won't be bundled)."
                ) from None
            dep_tuples.append((rel, dep.absolute_path))
        return dep_tuples, [rel for rel, _ in dep_tuples]

    except WorkflowValidationError:
        raise
    except (FileNotFoundError, ValueError) as e:
        raise WorkflowValidationError(f"Dependency discovery failed for '{name}': {e}") from e
    except Exception as e:
        raise WorkflowValidationError(
            f"Unexpected error during dependency discovery for '{name}': {e}\n"
            "If this is a bug, please report it. "
            "To save without bundling, remove file references from the workflow."
        ) from e


def _reject_unbundleable_file_refs(name: str, workflow_ir: dict[str, Any]) -> None:
    """Reject saves of workflows with file references when no source path is available.

    Without a source path, file references can't be bundled, producing a broken
    saved workflow. Fail early with an actionable error message.
    """
    from pflow.core.file_resolver import has_file_references, is_workflow_file_reference

    try:
        file_refs = has_file_references(workflow_ir)
        # Also check for sub-workflow file refs (not in FILE_RESOLVABLE_PARAMS)
        for node in workflow_ir.get("nodes", []):
            wf_ref = node.get("params", {}).get("workflow", "")
            if isinstance(wf_ref, str) and is_workflow_file_reference(wf_ref):
                file_refs.append(wf_ref)
        if file_refs:
            refs_display = ", ".join(file_refs[:3])
            raise WorkflowValidationError(
                f"Workflow '{name}' contains file references ({refs_display}) "
                f"but no source file path was provided for dependency bundling.\n"
                f"Save from a file path instead of raw content, "
                f"or inline the referenced content directly in the workflow."
            )
    except WorkflowValidationError:
        raise
    except Exception as e:
        logger.debug(f"File reference check skipped for '{name}': {e}")


def save_workflow_with_options(
    name: str,
    markdown_content: str,
    *,
    force: bool = False,
    metadata: Optional[dict[str, Any]] = None,
    source_path: Optional[Path] = None,
) -> tuple[Path, list[str], dict[str, Any]]:
    """Parse, validate, and save a workflow with dependency bundling and overwrite handling.

    When source_path is provided, discovers file dependencies (sub-workflows,
    prompts, scripts) and bundles them into the saved workflow folder.

    Content validation (parse + full WorkflowValidator) is handled internally.
    Name validation is the caller's responsibility (use validate_workflow_name).

    Args:
        name: Workflow name (caller must validate via validate_workflow_name first)
        markdown_content: Original .pflow.md content string
        force: If True, overwrite existing workflow by deleting it first
        metadata: Optional metadata dict (keywords, capabilities, use cases)
        source_path: Optional path to the source workflow file. When provided,
            dependency discovery runs and files are bundled into the saved folder.

    Returns:
        Tuple of (path_to_saved_entry_point, list_of_bundled_relative_paths, validated_ir)

    Raises:
        MarkdownParseError: If markdown_content cannot be parsed
        FileExistsError: If workflow exists and force=False
        WorkflowValidationError: If validation or save fails
    """
    result = parse_markdown(markdown_content)
    validated_ir = _validate_and_normalize_ir(
        result.ir,
        auto_normalize=True,
        source_desc=f"Invalid workflow '{name}'",
        source_path=source_path,
    )

    manager = WorkflowManager()

    # Check existence
    if manager.exists(name):
        if not force:
            raise FileExistsError(
                f"Workflow '{name}' already exists. Use force=True to overwrite or choose a different name."
            )

        # Delete existing workflow before saving
        try:
            manager.delete(name)
            logger.info(f"Deleted existing workflow '{name}' (force=True)")
        except Exception as e:
            raise WorkflowValidationError(f"Failed to delete existing workflow '{name}': {e}") from e

    # Discover dependencies if source path is provided
    dependencies: Optional[list[tuple[str, Path]]] = None
    bundled_files: list[str] = []

    if source_path is not None:
        dependencies, bundled_files = _discover_and_bundle_deps(name, validated_ir, source_path)
    else:
        _reject_unbundleable_file_refs(name, validated_ir)

    # Save workflow
    try:
        saved_path = manager.save(name, markdown_content, metadata, dependencies)
        logger.info(f"Saved workflow '{name}' to {saved_path}")
    except Exception as e:
        raise WorkflowValidationError(f"Failed to save workflow '{name}': {e}") from e

    # Re-enrich if this workflow is published as a Claude Code skill (Task 119)
    try:
        from pflow.core.workflow.skill_service import re_enrich_if_skill

        re_enrich_if_skill(name)
    except Exception:
        logger.warning(f"Failed to re-enrich skill for '{name}'", exc_info=True)

    return Path(saved_path), bundled_files, validated_ir


def generate_workflow_metadata(
    workflow_ir: dict[str, Any], model_name: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Generate rich metadata for workflow using LLM.

    Stub — rich metadata generation is currently disabled.
    Returns None unconditionally.
    """
    return None


def delete_draft_safely(file_path: str) -> bool:
    """Delete draft workflow file with security checks.

    Only deletes files in .pflow/workflows/ directories (home or cwd) for safety.
    Refuses to delete symlinks to prevent accidental damage.

    Security features:
    - Path traversal prevention via is_relative_to()
    - Symlink detection and refusal
    - Whitelist of allowed directories only

    Args:
        file_path: Path to draft file to delete

    Returns:
        True if deleted successfully, False if unsafe or failed
    """
    try:
        file_path_obj = Path(file_path).resolve()  # Resolves symlinks

        # Define safe base directories for auto-deletion (also resolve them)
        home_pflow = (Path.home() / ".pflow" / "workflows").resolve()
        cwd_pflow = (Path.cwd() / ".pflow" / "workflows").resolve()

        # Check if file is within safe directories using is_relative_to()
        # This prevents path traversal attacks (e.g., ../../etc/passwd)
        try:
            is_safe = file_path_obj.is_relative_to(home_pflow) or file_path_obj.is_relative_to(cwd_pflow)
        except (ValueError, TypeError):
            # is_relative_to() may raise on invalid paths
            logger.warning(f"Invalid path for draft deletion: {file_path}")
            return False

        # Additional security: refuse to delete symlinks (defense in depth)
        if Path(file_path).is_symlink():
            logger.warning(f"Refusing to delete symlink: {file_path}")
            return False

        # Only delete if in safe directory and not a symlink
        if is_safe:
            try:
                file_path_obj.unlink()
                logger.info(f"Deleted draft: {file_path}")
                return True
            except Exception as e:
                logger.warning(f"Could not delete draft {file_path}: {e}")
                return False
        else:
            logger.warning(f"Not deleting {file_path} - only files in .pflow/workflows/ can be auto-deleted")
            return False

    except Exception:
        logger.exception("Error during draft deletion")
        return False
