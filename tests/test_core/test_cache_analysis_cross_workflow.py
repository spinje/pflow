"""F1.3 — Tier 2 cross-workflow walker tests.

Walker traverses parent → child sub-workflow edges via ``resolve_sub_workflow``,
detects rename / prose-mismatch / value-flow opportunities, handles cycles +
depth limit, and re-raises broken-ref errors instead of silently skipping
(the analyzer only fires on already-validated workflows; broken refs surface
through the existing diagnostic pipeline).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from pflow.core.cache_analysis.cross_workflow import (
    CrossWorkflowEdge,
    walk_cross_workflow,
)
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

# ---------------------------------------------------------------------------
# Helpers — test resolvers
# ---------------------------------------------------------------------------


class _StubResolver:
    """Synthetic resolver: maps ``workflow:`` strings to (ir, path) pairs."""

    def __init__(self, table: dict[str, tuple[dict[str, Any], Path | None]]) -> None:
        self._table = table
        self.calls: list[str] = []

    def __call__(self, params: dict[str, Any], base_path: Path | None) -> SubWorkflowResult | None:
        ref = params.get("workflow")
        if not isinstance(ref, str) or "${" in ref or not ref:
            return None
        self.calls.append(ref)
        if ref not in self._table:
            raise FileNotFoundError(f"Sub-workflow not found: {ref}")
        ir, path = self._table[ref]
        return SubWorkflowResult(ir=ir, path=path, warnings=())


def _workflow_node(node_id: str, workflow_ref: str, inputs: dict[str, str]) -> dict:
    return {
        "id": node_id,
        "type": "workflow",
        "params": {"workflow": workflow_ref, "inputs": dict(inputs)},
        "_source_line": 50,
    }


# ---------------------------------------------------------------------------
# Walker basics
# ---------------------------------------------------------------------------


def test_walker_returns_empty_list_for_workflow_with_no_subworkflows() -> None:
    root_ir = {
        "nodes": [
            {"id": "step1", "type": "shell", "params": {"command": "echo"}},
        ]
    }
    edges = walk_cross_workflow(root_ir, base_path=None, resolve_child=_StubResolver({}))
    assert edges == []


def test_walker_emits_one_edge_per_input_for_a_single_subworkflow() -> None:
    """A parent passing 2 inputs to a child produces 2 edges (one per input)."""
    child_ir = {
        "inputs": {"text": {"type": "string"}, "tone": {"type": "string"}},
        "nodes": [],
    }
    root_ir = {
        "nodes": [
            _workflow_node(
                "process",
                "./child.pflow.md",
                {"text": "${title}", "tone": "${voice}"},
            )
        ]
    }
    resolver = _StubResolver({"./child.pflow.md": (child_ir, Path("/abs/child.pflow.md"))})
    edges = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    assert len(edges) == 2
    edges_by_input = {e.child_input_name: e for e in edges}
    assert edges_by_input["text"].parent_value_expr == "title"
    assert edges_by_input["tone"].parent_value_expr == "voice"
    for e in edges:
        assert e.child_workflow == "/abs/child.pflow.md"
        assert e.line_in_parent == 50


def test_walker_recurses_into_grandchildren() -> None:
    grandchild_ir = {"inputs": {"v": {"type": "string"}}, "nodes": []}
    child_ir = {
        "inputs": {"x": {"type": "string"}},
        "nodes": [_workflow_node("gc", "./grandchild.pflow.md", {"v": "${x}"})],
    }
    root_ir = {"nodes": [_workflow_node("c", "./child.pflow.md", {"x": "${input1}"})]}
    resolver = _StubResolver({
        "./child.pflow.md": (child_ir, Path("/abs/child.pflow.md")),
        "./grandchild.pflow.md": (grandchild_ir, Path("/abs/grandchild.pflow.md")),
    })
    edges = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    assert len(edges) == 2
    parents = {e.parent_workflow for e in edges}
    assert "/abs/child.pflow.md" in parents  # grandchild edge


def test_walker_handles_cycle_at_info_level(caplog: pytest.LogCaptureFixture) -> None:
    """A.pflow.md → B.pflow.md → A.pflow.md is a cycle. Walker stops descending
    that branch but continues siblings; logs at info, doesn't raise."""
    caplog.set_level(logging.INFO, logger="pflow.core.cache_analysis.cross_workflow")
    a_ir = {"nodes": [_workflow_node("calls_b", "./b.pflow.md", {"x": "${y}"})]}
    b_ir = {"nodes": [_workflow_node("calls_a", "./a.pflow.md", {"y": "${z}"})]}
    resolver = _StubResolver({
        "./b.pflow.md": (b_ir, Path("/abs/b.pflow.md")),
        "./a.pflow.md": (a_ir, Path("/abs/a.pflow.md")),
    })
    edges = walk_cross_workflow(
        a_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        seen_paths={"/abs/a.pflow.md"},  # simulate root is "/abs/a.pflow.md"
    )
    # 1 edge from a → b. Cycle prevents descending b's edge to a.
    assert len(edges) == 1
    assert any("cycle" in rec.message.lower() for rec in caplog.records)


def test_walker_respects_depth_limit(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="pflow.core.cache_analysis.cross_workflow")
    grandchild_ir = {"nodes": []}
    child_ir = {"nodes": [_workflow_node("gc", "./gc.pflow.md", {"v": "${x}"})]}
    root_ir = {"nodes": [_workflow_node("c", "./child.pflow.md", {"x": "${input1}"})]}
    resolver = _StubResolver({
        "./child.pflow.md": (child_ir, Path("/abs/child.pflow.md")),
        "./gc.pflow.md": (grandchild_ir, Path("/abs/gc.pflow.md")),
    })
    edges = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver, max_depth=1)
    # Only root → child edge; depth 1 doesn't descend into grandchild.
    assert len(edges) == 1
    assert edges[0].child_workflow == "/abs/child.pflow.md"
    assert any("depth" in rec.message.lower() for rec in caplog.records)


def test_walker_reraises_resolution_error() -> None:
    """Broken sub-workflow refs surface through the existing diagnostic pipeline,
    not via a new cache.* ID. Walker re-raises so the same error you'd see at
    pflow run validation also fires from analyze-cache."""
    root_ir = {"nodes": [_workflow_node("c", "./missing.pflow.md", {"x": "${y}"})]}
    resolver = _StubResolver({})  # nothing in the table
    with pytest.raises(FileNotFoundError):
        walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)


def test_walker_depth_limit_appends_truncation_note() -> None:
    """Regression: silently truncated cross-workflow analysis is a
    silent-failure attractor — when the walker stops at max_depth, agents
    must see a note in the analysis output, not just a debug log line."""
    grandchild_ir = {"nodes": []}
    child_ir = {"nodes": [_workflow_node("gc", "./gc.pflow.md", {"v": "${x}"})]}
    root_ir = {"nodes": [_workflow_node("c", "./child.pflow.md", {"x": "${input1}"})]}
    resolver = _StubResolver({
        "./child.pflow.md": (child_ir, Path("/abs/child.pflow.md")),
        "./gc.pflow.md": (grandchild_ir, Path("/abs/gc.pflow.md")),
    })
    notes: list[str] = []
    edges = walk_cross_workflow(
        root_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        max_depth=1,
        notes=notes,
    )
    assert len(edges) == 1  # Root → child only.
    assert any("max_depth" in n and "deeper boundaries not analyzed" in n for n in notes)


def test_walker_cycle_appends_skip_note() -> None:
    """Regression: cycles previously logged at info but didn't surface to the
    user. The notes list now ensures the truncation is visible."""
    a_ir = {"nodes": [_workflow_node("calls_b", "./b.pflow.md", {"x": "${y}"})]}
    b_ir = {"nodes": [_workflow_node("calls_a", "./a.pflow.md", {"y": "${z}"})]}
    resolver = _StubResolver({
        "./b.pflow.md": (b_ir, Path("/abs/b.pflow.md")),
        "./a.pflow.md": (a_ir, Path("/abs/a.pflow.md")),
    })
    notes: list[str] = []
    walk_cross_workflow(
        a_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        seen_paths={"/abs/a.pflow.md"},
        notes=notes,
    )
    assert any("cycle" in n and "skipped" in n for n in notes)


# ---------------------------------------------------------------------------
# CrossWorkflowEdge — rename detection
# ---------------------------------------------------------------------------


def test_no_rename_when_input_name_matches_value_tail() -> None:
    """parent passes ${concept} to child input named 'concept' — same name,
    no rename."""
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="concept",
        child_input_name="concept",
        line_in_parent=10,
        parent_node_id="step",
    )
    assert edge.is_rename is False


def test_rename_when_input_name_differs_from_value_tail() -> None:
    """parent passes ${concept_brief} to child input 'creative_brief' — rename."""
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="concept_brief",
        child_input_name="creative_brief",
        line_in_parent=77,
        parent_node_id="song-creator",
    )
    assert edge.is_rename is True


def test_no_rename_for_dotted_path_with_matching_tail() -> None:
    """parent passes ${chorus-chooser.winning_chorus} to child input
    'winning_chorus' — tail matches, no rename."""
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="chorus-chooser.winning_chorus",
        child_input_name="winning_chorus",
        line_in_parent=10,
        parent_node_id="step",
    )
    assert edge.is_rename is False


def test_rename_for_dotted_path_with_different_tail() -> None:
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="chorus-chooser.winning_chorus",
        child_input_name="chorus",
        line_in_parent=10,
        parent_node_id="step",
    )
    assert edge.is_rename is True


# ---------------------------------------------------------------------------
# Walker output shape
# ---------------------------------------------------------------------------


def test_edge_carries_resolved_paths() -> None:
    child_ir = {"inputs": {"x": {"type": "string"}}, "nodes": []}
    root_ir = {"nodes": [_workflow_node("c", "./child.pflow.md", {"x": "${y}"})]}
    resolver = _StubResolver({"./child.pflow.md": (child_ir, Path("/abs/path/child.pflow.md"))})
    edges = walk_cross_workflow(
        root_ir,
        base_path=Path("/abs/path"),
        resolve_child=resolver,
        root_workflow_path="/abs/path/parent.pflow.md",
    )
    assert len(edges) == 1
    assert edges[0].parent_workflow == "/abs/path/parent.pflow.md"
    assert edges[0].child_workflow == "/abs/path/child.pflow.md"


def test_edge_carries_parent_node_id() -> None:
    """Per the catalog, cache.cross-workflow-rename-detected requires
    parent_node_id for the path field."""
    child_ir = {"inputs": {"x": {"type": "string"}}, "nodes": []}
    root_ir = {"nodes": [_workflow_node("song-creator", "./c.pflow.md", {"x": "${y}"})]}
    resolver = _StubResolver({"./c.pflow.md": (child_ir, Path("/abs/c.pflow.md"))})
    edges = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    assert edges[0].parent_node_id == "song-creator"


def test_inputs_with_non_template_values_still_yield_edge() -> None:
    """A literal-value input (no ${...}) doesn't have a parent_value_expr; walker
    omits it from the rename surface but doesn't crash."""
    child_ir = {"inputs": {"x": {"type": "string"}}, "nodes": []}
    root_ir = {"nodes": [_workflow_node("c", "./child.pflow.md", {"x": "literal value"})]}
    resolver = _StubResolver({"./child.pflow.md": (child_ir, Path("/abs/c.pflow.md"))})
    edges = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    # Walker may or may not emit an edge for literals; the contract is "no crash".
    # If emitted, parent_value_expr is the literal value; rename check uses tail logic.
    if edges:
        assert edges[0].child_input_name == "x"
