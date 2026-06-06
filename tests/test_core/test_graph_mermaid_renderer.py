"""Tests for rendering GraphModel to Mermaid."""

from __future__ import annotations

from pathlib import Path

import pytest

from pflow.core.workflow.graph import LoopSpec, build_graph, render_mermaid
from pflow.core.workflow.graph.renderers.mermaid import _get_item_label, _loop_label
from pflow.core.workflow.mermaid import generate_mermaid
from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
from pflow.execution.workflow_resolver import resolve_workflow

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


def _render_graph(workflow_path: Path, *, direction: str) -> str:
    resolved = resolve_workflow(str(workflow_path))
    base_path = Path(resolved.file_path).parent if resolved.file_path else None
    graph = build_graph(
        resolved.ir,
        resolve_child=resolve_sub_workflow,
        base_path=base_path,
        source_file=Path(resolved.file_path) if resolved.file_path else None,
        max_depth=5,
    )
    return render_mermaid(graph, direction=direction)


def _render_shim(workflow_path: Path, *, direction: str) -> str:
    resolved = resolve_workflow(str(workflow_path))
    base_path = Path(resolved.file_path).parent if resolved.file_path else None
    return generate_mermaid(
        resolved.ir,
        resolve_child=resolve_sub_workflow,
        base_path=base_path,
        source_file=Path(resolved.file_path) if resolved.file_path else None,
        max_depth=5,
        direction=direction,
    )


@pytest.mark.parametrize(
    "workflow_rel,direction",
    [
        ("core/conditional-branching.pflow.md", "LR"),
        ("nested/document-processor.pflow.md", "LR"),
        ("batch-test-parallel.pflow.md", "LR"),
        ("core/error-handling.pflow.md", "LR"),
        ("real-workflows/generate-changelog/workflow.pflow.md", "LR"),
        ("nested/deep-research/deep-research.pflow.md", "TD"),
        ("nested/deep-research/deep-research.pflow.md", "LR"),
        ("core/stateful-loop-tournament.pflow.md", "LR"),
    ],
)
def test_generate_mermaid_shim_matches_graph_renderer_for_golden_subjects(workflow_rel: str, direction: str) -> None:
    workflow_path = EXAMPLES_DIR / workflow_rel

    assert _render_graph(workflow_path, direction=direction) == _render_shim(workflow_path, direction=direction)


def test_item_label_extraction() -> None:
    assert _get_item_label({"focus": "emotional"}, 0) == "emotional"
    assert _get_item_label({"lens": "heart"}, 0) == "heart"
    assert _get_item_label({"name": "test"}, 0) == "test"
    assert _get_item_label({"label": "my-label"}, 0) == "my-label"
    assert _get_item_label({"workflow": "./foo.pflow.md", "role": "critic"}, 0) == "critic"
    assert _get_item_label("plain-string", 0) == "#1"
    assert _get_item_label(42, 2) == "#3"


def test_loop_label_formats_loop_spec() -> None:
    assert _loop_label(LoopSpec("while", "${run-rounds.more}", 10, {}), "run-rounds") == "<br/>⟳ while more · ≤ 10"
    assert _loop_label(LoopSpec("until", "${check.done}", None, {}), "check") == "<br/>⟳ until done"
    assert (
        _loop_label(
            LoopSpec(
                "while",
                "${review-round.result.continue}",
                "${max_review_rounds}",
                {},
            ),
            "review-round",
        )
        == "<br/>⟳ while result.continue · ≤ max_review_rounds"
    )
    assert (
        _loop_label(
            LoopSpec("while", "${r.more}", 10, {"contenders": "${r.survivors}"}),
            "r",
        )
        == "<br/>⟳ while more · ≤ 10 · carry contenders"
    )
    assert _loop_label(LoopSpec("while", "${r.go}", None, {}), "r") == "<br/>⟳ while go"
    assert _loop_label(LoopSpec("while", "${other.flag}", None, {}), "r") == "<br/>⟳ while other.flag"
    assert _loop_label(LoopSpec("while", "${r.go}", True, {}), "r") == "<br/>⟳ while go"


def test_loop_label_escapes_special_chars() -> None:
    label = _loop_label(LoopSpec("while", "${r.go}", None, {"a|b": "${r.x}"}), "r")

    assert "|" not in label.split("<br/>")[1]
    assert "&#124;" in label
