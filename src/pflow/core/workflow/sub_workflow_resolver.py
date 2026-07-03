"""Shared sub-workflow resolution.

Resolves sub-workflow references (file path or saved name) to their IR dict.
Used by validator, executor, visualizer, dry-run planner, and the cache
analyzer's cross-workflow walker.

## Boundary contract

``SubWorkflowResult.ir`` is fully **file-resolved by contract** — every
``FILE_RESOLVABLE_PARAMS`` value (``prompt``, ``code``, ``command``, etc.)
that was a ``./*.md`` file reference at parse time has its content inlined
before this resolver returns. This mirrors :class:`pflow.execution.result.ResolvedWorkflow`'s
contract for the ROOT workflow (Path 1, commit a3044f42) and extends the
"resolve at the boundary, not at every consumer" pattern to the sub-workflow
load primitive.

**Why:** without this, every consumer that walks child IR for analysis
(cross-workflow value-flow detection, future graph-based features) has to
remember to apply file resolution. That's the "consumer applies X" anti-pattern
Path 1 named explicitly. Resolution at the primitive guarantees no consumer
can forget.

**Idempotency:** ``resolve_file_references`` re-walks already-resolved IR
without effect — ``is_file_reference`` returns False on multi-line content,
spaces, etc. So the existing explicit calls in ``compiler.py`` and
``validator.py`` continue to work; they're now defense-in-depth on top of
the boundary call.

**Mocked-WorkflowManager test isolation:** the saved-name path
(``_resolve_from_saved``) skips file resolution when the resolved path
doesn't exist on disk — same pattern Path 1 applied at the library load
site in ``workflow_resolver.py``.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pflow.core.diagnostic import Diagnostic

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubWorkflowResult:
    """Result of resolving a sub-workflow reference.

    The ``ir`` field is fully file-resolved per the boundary contract
    documented in this module's top-level docstring.
    """

    ir: dict[str, Any]
    path: Path | None
    warnings: tuple[Diagnostic, ...]


def resolve_sub_workflow(
    params: dict[str, Any],
    base_path: Path | None = None,
) -> SubWorkflowResult | None:
    """Resolve a sub-workflow reference from node params.

    Handles two resolution modes:
    1. File reference (``workflow`` param containing path indicators)
    2. Saved workflow name (``workflow`` param as plain name)

    Returns None for template references (``${...}``) that can't be
    resolved statically, or when no workflow reference is present.

    The returned ``SubWorkflowResult.ir`` is fully file-resolved — see
    module-level docstring for the boundary contract.

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


def _resolve_file_refs_at_boundary(ir: dict[str, Any], path: Path | None) -> dict[str, Any]:
    """Apply file resolution per the boundary contract.

    Mirrors the ROOT-workflow boundary in ``execution/workflow_resolver.py``:
    inline ``./*.md`` file refs in ``FILE_RESOLVABLE_PARAMS`` so downstream
    consumers (template walkers, cache analyzer's cross-workflow walker,
    etc.) operate on a single canonical IR shape.

    Idempotent on already-resolved IR (``is_file_reference`` returns False
    on multi-line content). The ``path.exists()`` guard handles the
    mocked-``WorkflowManager`` test pattern where ``wm.load_ir(name)``
    returns IR without a real file on disk.

    Returns ``ir`` unchanged if no file resolution can be applied; otherwise
    returns the same dict (modified in place by ``resolve_file_references``).
    """
    if path is None or not path.exists():
        return ir
    from pflow.core.file_resolver import resolve_file_references

    resolve_file_references(ir, path.parent)
    return ir


def _resolve_from_file(
    workflow_ref: str,
    base_path: Path | None,
) -> SubWorkflowResult:
    """Resolve a file reference to a sub-workflow IR.

    The returned IR is fully file-resolved per the boundary contract
    (see module-level docstring).

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
    ir = _resolve_file_refs_at_boundary(result.ir, resolved)
    return SubWorkflowResult(ir=ir, path=resolved, warnings=tuple(result.warnings))


def _resolve_from_saved(workflow_ref: str) -> SubWorkflowResult:
    """Resolve a saved workflow name to its IR.

    Re-parses the source file if available on disk (same behavior as
    both the validator and executor — ensures latest version is used).
    Applies file resolution per the boundary contract when a real file
    exists; mocked-WorkflowManager paths (no on-disk file) skip resolution
    via the ``_resolve_file_refs_at_boundary`` guard.

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

    child_ir = _resolve_file_refs_at_boundary(child_ir, child_path)
    return SubWorkflowResult(ir=child_ir, path=child_path, warnings=warnings)
