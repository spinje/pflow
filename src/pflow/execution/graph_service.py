"""Resolve → validate → build a workflow reference into a :class:`GraphModel`.

The single entry point every graph *renderer's* caller reaches for. ``pflow ui``
(React Flow) needs "a workflow reference turned into a validated graph"; so does
``pflow mermaid`` (Mermaid). Owning the three-step pipeline once keeps ``ui``
from being the third literal copy of it (Task 168 plan, H11). ``mermaid``
adopting this helper is a deliberate later follow-up — not done here, to avoid
perturbing the Mermaid goldens.

Two failure regimes, kept distinct on purpose:

* **Resolution or validation failure** → :class:`WorkflowGraphValidationError`,
  carrying the structured diagnostics. The caller renders them (CLI diagnostic
  stream, exit 1) or serializes them (server → HTTP 422). The user's workflow
  is at fault; the error is *expected*.
* **A build failure on already-validated IR propagates unchanged.** That is a
  producer bug in the graph builder, not a user error — it must surface loudly
  (CLI traceback / HTTP 500), never be swallowed into an empty graph.
"""

from __future__ import annotations

from pathlib import Path

from pflow.core.diagnostic import Diagnostic, exception_to_diagnostics
from pflow.core.exceptions import PflowError
from pflow.core.workflow.graph import GraphModel, build_graph
from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
from pflow.execution.runner import WorkflowRunner
from pflow.execution.workflow_resolver import resolve_workflow


class WorkflowGraphValidationError(PflowError):
    """A workflow could not be resolved or validated into a graph.

    Carries the structured :class:`Diagnostic` list so callers can render it
    (CLI) or serialize it (server 422) without re-deriving anything.
    """

    retriable = False

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("Workflow validation failed")

    def to_diagnostics(self) -> list[Diagnostic]:
        return self.diagnostics


def resolve_validate_build(workflow: str, *, max_depth: int = 5) -> GraphModel:
    """Resolve a workflow reference, validate it, and build its ``GraphModel``.

    Args:
        workflow: A saved workflow name or a path to a ``.pflow.md`` file.
        max_depth: Sub-workflow expansion depth (``0`` = no expansion).

    Returns:
        The fully built :class:`GraphModel`.

    Raises:
        WorkflowGraphValidationError: Resolution or validation failed; the
            carried diagnostics describe why. A build failure on already-valid
            IR is NOT wrapped — it propagates so a producer bug surfaces loudly.
    """
    try:
        resolved = resolve_workflow(workflow)
    except Exception as e:
        raise WorkflowGraphValidationError(list(exception_to_diagnostics(e))) from e

    try:
        vresult = WorkflowRunner().validate(
            resolved,
            params={},
            source_file_path=resolved.file_path,
        )
    except Exception as e:
        # A programming bug inside validation propagates out of validate()
        # (runner.py only swallows expected validation-phase errors). Mirror
        # `mermaid`: render it as a diagnostic, not a raw traceback — same
        # regime as "the workflow is invalid."
        raise WorkflowGraphValidationError(list(exception_to_diagnostics(e))) from e

    if not vresult.valid:
        raise WorkflowGraphValidationError(vresult.errors)

    base_path = Path(resolved.file_path).parent if resolved.file_path else None
    source_file = Path(resolved.file_path) if resolved.file_path else None
    return build_graph(
        resolved.ir,
        resolve_child=resolve_sub_workflow,
        base_path=base_path,
        source_file=source_file,
        max_depth=max_depth,
    )


__all__ = ["WorkflowGraphValidationError", "resolve_validate_build"]
