"""Shared workflow save operations for CLI and MCP.

This module provides unified workflow save functionality used by both
the CLI and MCP server, eliminating code duplication while maintaining
separate interfaces optimized for each use case.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from pflow.core.exceptions import WorkflowValidationError
from pflow.core.ir_schema import normalize_ir, validate_ir
from pflow.core.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)

# Reserved names that could conflict with system functionality
RESERVED_WORKFLOW_NAMES = {
    "null",
    "undefined",
    "none",
    "test",
    "settings",
    "registry",
    "workflow",
    "mcp",
}


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


def _validate_and_normalize_ir(workflow_ir: dict[str, Any], auto_normalize: bool, source_desc: str) -> dict[str, Any]:
    """Validate and optionally normalize workflow IR.

    Performs comprehensive validation:
    1. IR schema validation (structure, required fields)
    2. WorkflowValidator validation (data flow, output sources, node types)

    Args:
        workflow_ir: Workflow IR to validate
        auto_normalize: Whether to auto-add missing fields
        source_desc: Description of source for error messages

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

    # Step 2: Comprehensive workflow validation (data flow, output sources, node types)
    from pflow.core.validation_utils import generate_dummy_parameters
    from pflow.core.workflow_validator import WorkflowValidator
    from pflow.registry import Registry

    try:
        # Generate dummy parameters for template validation
        # This enables structural validation without requiring real parameter values
        inputs = workflow_ir.get("inputs", {})
        dummy_params = generate_dummy_parameters(inputs)

        registry = Registry()
        errors, _ = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            extracted_params=dummy_params,  # Use dummy params for template validation
            registry=registry,
            skip_node_types=False,  # Validate node types
        )

        if errors:
            error_msg = f"{source_desc} - Validation errors:\n"
            for i, error in enumerate(errors, 1):
                error_msg += f"  {i}. {error}\n"
            raise WorkflowValidationError(error_msg.rstrip())

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
        source: Dict containing workflow IR (or metadata wrapper)
        auto_normalize: Whether to auto-add missing fields

    Returns:
        Validated workflow IR
    """
    # Extract IR if wrapped in metadata
    workflow_ir = source.get("ir", source)
    return _validate_and_normalize_ir(workflow_ir, auto_normalize, "Invalid workflow IR")


def _load_from_file(path: Path, auto_normalize: bool) -> dict[str, Any]:
    """Load workflow from file path.

    Args:
        path: Path to JSON file
        auto_normalize: Whether to auto-add missing fields

    Returns:
        Validated workflow IR

    Raises:
        ValueError: If file cannot be loaded or is invalid
        WorkflowValidationError: If IR validation fails
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # Extract IR if wrapped
        workflow_ir = data.get("ir", data)
        return _validate_and_normalize_ir(workflow_ir, auto_normalize, f"Invalid workflow in {path}")

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e
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
    return _validate_and_normalize_ir(workflow_ir, auto_normalize, f"Invalid workflow '{name}'")


def load_and_validate_workflow(
    source: str | dict[str, Any],
    auto_normalize: bool = True,
) -> dict[str, Any]:
    """Load workflow from any source and validate IR structure.

    Handles three input types:
    1. Dict: Use directly as IR (or extract from metadata wrapper)
    2. File path: Load from JSON file
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


def save_workflow_with_options(
    name: str,
    workflow_ir: dict[str, Any],
    description: str,
    *,
    force: bool = False,
    metadata: Optional[dict[str, Any]] = None,
) -> Path:
    """Save workflow to library with existence checks and overwrite handling.

    Args:
        name: Workflow name (must be validated first using validate_workflow_name)
        workflow_ir: Validated workflow IR
        description: Workflow description
        force: If True, overwrite existing workflow by deleting it first
        metadata: Optional rich metadata dict (keywords, capabilities, use cases)

    Returns:
        Path to saved workflow file

    Raises:
        FileExistsError: If workflow exists and force=False
        WorkflowValidationError: If save fails
    """
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

    # Save workflow
    try:
        saved_path = manager.save(name, workflow_ir, description, metadata)
        logger.info(f"Saved workflow '{name}' to {saved_path}")
        return Path(saved_path)
    except Exception as e:
        raise WorkflowValidationError(f"Failed to save workflow '{name}': {e}") from e


def generate_workflow_metadata(workflow_ir: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Generate rich metadata for workflow using LLM.

    This is an optional CLI-only feature that generates:
    - keywords: Search terms for workflow discovery
    - capabilities: What the workflow can do
    - typical_use_cases: Common scenarios for using this workflow

    Note: This operation takes 10-30 seconds and costs ~$0.01 per workflow.
    MCP server does not use this feature to keep saves fast.

    Args:
        workflow_ir: Validated workflow IR

    Returns:
        Metadata dict with keywords, capabilities, use_cases
        Or None if generation fails
    """
    try:
        # Lazy import to avoid dependency in MCP context
        from pflow.planning.nodes import MetadataGenerationNode

        node = MetadataGenerationNode()
        shared: dict[str, Any] = {
            "generated_workflow": workflow_ir,
            "user_input": "",  # Not needed for metadata generation
            "cache_planner": False,  # Disable caching for metadata
        }

        node.run(shared)

        metadata = shared.get("workflow_metadata")
        if metadata and isinstance(metadata, dict):
            logger.debug(
                f"Generated metadata: {len(metadata.get('keywords', []))} keywords, "
                f"{len(metadata.get('capabilities', []))} capabilities"
            )
            return metadata  # type: ignore[no-any-return]

        logger.warning("MetadataGenerationNode returned no metadata")
        return None

    except Exception as e:
        logger.warning(f"Failed to generate workflow metadata: {e}")
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
