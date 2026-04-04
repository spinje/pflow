"""Unified workflow resolution for CLI and MCP entry points.

Merges CLI (cli/workflow_resolution.py) and MCP (mcp_server/utils/resolver.py)
resolvers into a single function that returns ResolvedWorkflow.
"""

import logging
import os
from pathlib import Path
from typing import Any

from pflow.core.diagnostic import Diagnostic
from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.suggestion_utils import find_similar_items
from pflow.core.workflow.manager import WorkflowManager

from .result import ResolvedWorkflow

logger = logging.getLogger(__name__)


def resolve_workflow(
    identifier: str | dict[str, Any],
    wm: WorkflowManager | None = None,
) -> ResolvedWorkflow:
    """Resolve a workflow identifier to IR + metadata.

    Args:
        identifier: File path, saved name, raw markdown string, or IR dict.
        wm: WorkflowManager instance. Created internally if None.

    Returns:
        ResolvedWorkflow with ir, source, and file_path.

    Raises:
        WorkflowNotFoundError: Workflow not found (with similar_names for suggestions).
        MarkdownParseError: Invalid markdown content.
        PermissionError: File access denied.
        ValueError: Inline workflow contains file references.
    """
    # Dict input — passthrough (MCP sends pre-parsed IR)
    if isinstance(identifier, dict):
        _check_inline_file_references(identifier, "direct")
        return ResolvedWorkflow(ir=identifier, source="direct", file_path=None)

    if not isinstance(identifier, str):
        raise WorkflowNotFoundError(
            workflow_name=str(identifier),
            similar_names=[],
            hint="Workflow must be a file path, saved name, markdown string, or IR dict.",
        )

    # Raw markdown content — contains newlines (MCP sends inline workflows)
    if "\n" in identifier:
        ir, diagnostics = _parse_markdown_content(identifier)
        _check_inline_file_references(ir, "content")
        return ResolvedWorkflow(ir=ir, source="content", file_path=None, diagnostics=diagnostics)

    # File path — contains path separator or ends with known extension
    if _is_path_like(identifier):
        result = _try_load_from_file(identifier)
        if result is not None:
            return result
        # Fall through to name-based resolution

    # Name-based resolution — try saved workflow library
    if wm is None:
        wm = WorkflowManager()

    result = _try_load_from_library(identifier, wm)
    if result is not None:
        return result

    # Not found — build suggestions and raise
    similar = _find_suggestions(identifier, wm)
    raise WorkflowNotFoundError(
        workflow_name=identifier,
        similar_names=similar,
    )


def _is_path_like(identifier: str) -> bool:
    """Check if identifier looks like a file path."""
    return (
        os.sep in identifier
        or (os.altsep is not None and os.altsep in identifier)
        or identifier.endswith(".pflow.md")
        or identifier.endswith(".json")
        or identifier.endswith(".md")
    )


def _try_load_from_file(identifier: str) -> ResolvedWorkflow | None:
    """Try to load workflow from file path. Returns None if file doesn't exist."""
    from pflow.core import normalize_ir
    from pflow.core.markdown_parser import parse_markdown

    path = Path(identifier).expanduser().resolve()

    # Reject .json files with migration hint
    if path.suffix == ".json":
        raise WorkflowNotFoundError(
            workflow_name=identifier,
            similar_names=[],
            hint="JSON workflow format is no longer supported. Convert to .pflow.md format.",
        )

    # Reject .md files that aren't .pflow.md with rename suggestion
    if path.suffix == ".md" and not str(path).endswith(".pflow.md"):
        pflow_path = path.with_suffix(".pflow.md")
        if pflow_path.exists():
            raise WorkflowNotFoundError(
                workflow_name=identifier,
                similar_names=[str(pflow_path)],
                hint=f"Did you mean '{pflow_path}'? Workflow files use the .pflow.md extension.",
            )
        raise WorkflowNotFoundError(
            workflow_name=identifier,
            similar_names=[],
            hint="Workflow files use the .pflow.md extension, not .md.",
        )

    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    result = parse_markdown(content)
    normalize_ir(result.ir)
    return ResolvedWorkflow(
        ir=result.ir,
        source="file",
        file_path=str(path),
        diagnostics=tuple(result.warnings),
    )


def _try_load_from_library(identifier: str, wm: WorkflowManager) -> ResolvedWorkflow | None:
    """Try to load workflow from saved library."""
    name = identifier
    if not wm.exists(name):
        # Strip .pflow.md extension and retry
        if identifier.endswith(".pflow.md"):
            name = identifier[:-9]  # len(".pflow.md") == 9
            if not wm.exists(name):
                return None
        else:
            return None

    return _load_library_workflow(name, wm)


def _load_library_workflow(name: str, wm: WorkflowManager) -> ResolvedWorkflow:
    """Load a saved workflow, preserving parser diagnostics when possible.

    Parses the entry-point file directly so parser warnings survive.
    Falls back to ``load_ir()`` when the file isn't readable (e.g. mocked
    WorkflowManager in tests with fake paths).
    """
    from pflow.core import normalize_ir
    from pflow.core.markdown_parser import parse_markdown

    file_path = wm.get_path(name)
    diagnostics: tuple[Diagnostic, ...] = ()
    path = Path(file_path)
    if path.exists():
        content = path.read_text(encoding="utf-8")
        result = parse_markdown(content)
        ir = result.ir
        diagnostics = tuple(result.warnings)
    else:
        ir = wm.load_ir(name)
    normalize_ir(ir)
    return ResolvedWorkflow(
        ir=ir,
        source="library",
        file_path=file_path,
        diagnostics=diagnostics,
    )


def _parse_markdown_content(content: str) -> tuple[dict[str, Any], tuple[Diagnostic, ...]]:
    """Parse raw markdown string into IR dict and parser diagnostics."""
    from pflow.core import normalize_ir
    from pflow.core.markdown_parser import parse_markdown

    result = parse_markdown(content)
    normalize_ir(result.ir)
    return result.ir, tuple(result.warnings)


def _check_inline_file_references(workflow_ir: dict[str, Any], source: str) -> None:
    """Raise ValueError if inline workflow contains file references."""
    if source not in ("content", "direct"):
        return
    from pflow.core.file_resolver import has_file_references

    file_refs = has_file_references(workflow_ir)
    if file_refs:
        examples = ", ".join(file_refs[:3])
        raise ValueError(
            f"Workflow contains file references ({examples}) but was provided as inline content. "
            f"File references require a workflow file path to resolve relative paths from. "
            f"Save the workflow to a file and reference it by path or saved name."
        )


def _find_suggestions(query: str, wm: WorkflowManager) -> list[str]:
    """Find similar workflow names for error suggestions."""
    all_workflows = wm.list_all()
    all_names = [w.get("name", "") for w in all_workflows if w.get("name")]
    if not all_names:
        return []
    return find_similar_items(query, all_names, max_results=5, method="substring", sort_by_length=True)
