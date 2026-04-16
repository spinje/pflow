"""Shared sub-workflow resolution.

Resolves sub-workflow references (file path or saved name) to their IR dict.
Used by validator, executor, and visualizer.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubWorkflowResult:
    """Result of resolving a sub-workflow reference."""

    ir: dict[str, Any]
    path: Optional[Path]
    warnings: tuple[Diagnostic, ...]


def resolve_sub_workflow(
    params: dict[str, Any],
    base_path: Optional[Path] = None,
) -> Optional[SubWorkflowResult]:
    """Resolve a sub-workflow reference from node params.

    Handles two resolution modes:
    1. File reference (``workflow`` param containing path indicators)
    2. Saved workflow name (``workflow`` param as plain name)

    Returns None for template references (``${...}``) that can't be
    resolved statically, or when no workflow reference is present.

    Raises on failure (FileNotFoundError, MarkdownParseError, ValueError, etc.).
    Callers wrap in their own error handling.

    Args:
        params: Node params dict (must contain ``workflow``)
        base_path: Directory to resolve relative file paths from.
                   For validator: ``workflow_file.parent``
                   For executor: parent workflow dir or CWD
                   For visualizer: source file parent dir
    """
    from pflow.core.file_resolver import is_workflow_file_reference

    workflow_ref = params.get("workflow")

    # No workflow reference
    if not isinstance(workflow_ref, str) or not workflow_ref:
        return None

    # Template references can't be resolved statically
    if "${" in workflow_ref:
        return None

    # Mode 1: File reference
    if is_workflow_file_reference(workflow_ref):
        return _resolve_from_file(workflow_ref, base_path)

    # Mode 2: Saved workflow name
    return _resolve_from_saved(workflow_ref)


def _resolve_from_file(
    workflow_ref: str,
    base_path: Optional[Path],
) -> SubWorkflowResult:
    """Resolve a file reference to a sub-workflow IR.

    Raises:
        FileNotFoundError: File doesn't exist
        ValueError: Relative path with no base_path
        MarkdownParseError: Parse failure
    """
    from pflow.core.markdown_parser import parse_markdown

    path = Path(workflow_ref)
    if not path.is_absolute():
        if base_path is not None:
            path = base_path / path
        else:
            raise ValueError(
                f"Cannot resolve relative sub-workflow '{workflow_ref}' "
                f"-- use an absolute path or load the workflow from a file "
                f"so relative paths can be resolved"
            )
    resolved = path.resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Sub-workflow file not found: '{workflow_ref}' (resolved to: {resolved})")

    content = resolved.read_text(encoding="utf-8")
    result = parse_markdown(content)
    if "nodes" not in result.ir:
        raise ValueError(f"Sub-workflow file {resolved} must contain a '## Steps' section with at least one node")
    return SubWorkflowResult(ir=result.ir, path=resolved, warnings=tuple(result.warnings))


def _resolve_from_saved(workflow_ref: str) -> SubWorkflowResult:
    """Resolve a saved workflow name to its IR.

    Re-parses the source file if available on disk (same behavior as
    both the validator and executor — ensures latest version is used).

    Raises:
        Exception: WorkflowNotFoundError or other load failures
    """
    from pflow.core.markdown_parser import parse_markdown
    from pflow.core.workflow.manager import WorkflowManager

    wm = WorkflowManager()
    child_ir = wm.load_ir(workflow_ref)
    child_path_value = wm.get_path(workflow_ref)
    child_path = Path(child_path_value) if isinstance(child_path_value, str) else None
    warnings: tuple[Diagnostic, ...] = ()

    # Re-parse from disk if file exists (get latest version + parser warnings)
    if child_path and child_path.exists():
        content = child_path.read_text(encoding="utf-8")
        result = parse_markdown(content)
        child_ir = result.ir
        warnings = tuple(result.warnings)

    return SubWorkflowResult(ir=child_ir, path=child_path, warnings=warnings)
