"""Direct unit coverage for ``execution/graph_service.resolve_validate_build``.

The seam every graph *renderer's* caller (``pflow ui``, ``pflow mermaid``)
reaches for. Until now it was exercised only TRANSITIVELY via ``test_ui.py`` (the
HTTP status arms); these tests pin the helper itself and, crucially, its two
deliberately-distinct failure regimes (graph_service.py docstring):

* resolution OR validation failure → ``WorkflowGraphValidationError`` carrying
  the structured ``Diagnostic`` list (callers render it / serialize it to 422);
* a build failure on already-validated IR is NOT wrapped — it propagates so a
  producer bug surfaces loudly (covered as the 500 arm in ``test_ui.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pflow.core.workflow.graph import GraphModel
from pflow.execution.graph_service import WorkflowGraphValidationError, resolve_validate_build
from tests.shared.markdown_utils import write_workflow_file

_VALID_IR = {
    "nodes": [
        {"id": "greet", "type": "shell", "params": {"command": "echo hello"}},
        {"id": "done", "type": "shell", "params": {"command": "echo done"}},
    ],
    "edges": [{"from": "greet", "to": "done"}],
}


def test_valid_workflow_builds_a_graph_model(tmp_path: Path) -> None:
    """A valid ``.pflow.md`` resolves → validates → builds into a GraphModel
    carrying its body nodes."""
    workflow_path = tmp_path / "wf.pflow.md"
    write_workflow_file(_VALID_IR, workflow_path)

    graph = resolve_validate_build(str(workflow_path))

    assert isinstance(graph, GraphModel)
    assert {"greet", "done"} <= {n.id.node_id for n in graph.nodes}


def test_validation_failure_raises_typed_error_with_diagnostics(tmp_path: Path) -> None:
    """A workflow that fails validation (unknown node type) raises
    ``WorkflowGraphValidationError`` carrying the diagnostics — never a bare
    build crash or an empty graph."""
    bad_ir = {"nodes": [{"id": "bad", "type": "nonexistent_type_xyz", "params": {}}], "edges": []}
    workflow_path = tmp_path / "invalid.pflow.md"
    write_workflow_file(bad_ir, workflow_path)

    with pytest.raises(WorkflowGraphValidationError) as exc:
        resolve_validate_build(str(workflow_path))

    # The structured diagnostics ride the exception (callers render/serialize
    # them without re-deriving), and to_diagnostics() returns the same list.
    assert exc.value.diagnostics
    assert exc.value.to_diagnostics() == exc.value.diagnostics


def test_unresolvable_reference_raises_typed_error() -> None:
    """An unresolvable workflow name fails at the resolution step and is wrapped
    in the same typed error (the resolution arm of the first failure regime)."""
    with pytest.raises(WorkflowGraphValidationError) as exc:
        resolve_validate_build("no-such-workflow-xyz")

    assert exc.value.diagnostics
