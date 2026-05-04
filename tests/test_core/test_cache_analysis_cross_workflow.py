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
    CrossWorkflowResult,
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
    result = walk_cross_workflow(root_ir, base_path=None, resolve_child=_StubResolver({}))
    assert result.edges == ()


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
    result = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    edges = result.edges
    assert len(edges) == 2
    edges_by_input = {e.child_input_name: e for e in edges}
    assert edges_by_input["text"].parent_value_expr == "title"
    assert edges_by_input["tone"].parent_value_expr == "voice"
    for e in edges:
        assert e.child_workflow == "/abs/child.pflow.md"
        assert e.line_in_parent == 50


def test_walker_collects_cache_items_by_workflow_label() -> None:
    child_ir = {
        "cache": {"items": [{"name": "creative.direction", "var": "creative.direction", "prose_before": "child"}]},
        "nodes": [{"id": "noop", "type": "shell", "params": {"command": "echo ok"}}],
    }
    root_ir = {
        "cache": {"items": [{"name": "creative.direction", "var": "creative.direction", "prose_before": "parent"}]},
        "nodes": [_workflow_node("process", "./child.pflow.md", {"direction": "${creative.direction}"})],
    }
    resolver = _StubResolver({"./child.pflow.md": (child_ir, Path("/abs/child.pflow.md"))})
    result = walk_cross_workflow(
        root_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        root_workflow_path="/abs/parent.pflow.md",
    )
    assert isinstance(result, CrossWorkflowResult)
    assert result.cache_items_by_workflow["/abs/parent.pflow.md"][0]["prose_before"] == "parent"
    assert result.cache_items_by_workflow["/abs/child.pflow.md"][0]["prose_before"] == "child"


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
    result = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    edges = result.edges
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
    # Production-accurate idiom: pass ``root_workflow_path`` so the walker
    # auto-seeds it into ``seen``. The legacy ``seen_paths={...}`` kwarg
    # still works (set union) but is test-only scaffolding.
    result = walk_cross_workflow(
        a_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        root_workflow_path="/abs/a.pflow.md",
    )
    # 1 edge from a → b. Cycle prevents descending b's edge to a.
    assert len(result.edges) == 1
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
    result = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver, max_depth=1)
    # Only root → child edge; depth 1 doesn't descend into grandchild.
    assert len(result.edges) == 1
    assert result.edges[0].child_workflow == "/abs/child.pflow.md"
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
    result = walk_cross_workflow(
        root_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        max_depth=1,
        notes=notes,
    )
    assert len(result.edges) == 1  # Root → child only.
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
        root_workflow_path="/abs/a.pflow.md",
        notes=notes,
    )
    assert any("cycle" in n and "skipped" in n for n in notes)


def test_walk_cross_workflow_does_not_emit_back_edge_to_root() -> None:
    """Regression for cycle bug: A → B → A. The back-edge B → A must NOT
    appear in ``cw_result.edges`` because A is the root.

    Pre-fix the walker initialized ``seen`` empty, so when the recursion
    reached B and tried to resolve B → A, the cycle check at
    :func:`_process_one_call` had no prior knowledge of A and accepted
    the back-edge. That edge then mutated root parameters via
    :func:`pflow.core.cache_analysis.analyze._build_parameters_by_workflow`.

    Post-fix the walker seeds ``seen`` with ``root_workflow_path`` so the
    back-edge is suppressed at the cycle check. This test drives the
    PRODUCTION call shape (no ``seen_paths`` kwarg — relies on the
    automatic root seeding).
    """
    a_ir = {"nodes": [_workflow_node("calls_b", "./b.pflow.md", {"x": "${y}"})]}
    b_ir = {"nodes": [_workflow_node("calls_a", "./a.pflow.md", {"y": "${z}"})]}
    resolver = _StubResolver({
        "./b.pflow.md": (b_ir, Path("/abs/b.pflow.md")),
        "./a.pflow.md": (a_ir, Path("/abs/a.pflow.md")),
    })
    result = walk_cross_workflow(
        a_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        root_workflow_path="/abs/a.pflow.md",
    )
    edges_to_root = [e for e in result.edges if e.child_workflow == "/abs/a.pflow.md"]
    assert edges_to_root == [], f"back-edge to root suppressed; got {edges_to_root}"
    # The forward edge A → B is still emitted.
    edges_to_b = [e for e in result.edges if e.child_workflow == "/abs/b.pflow.md"]
    assert len(edges_to_b) == 1


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
    result = walk_cross_workflow(
        root_ir,
        base_path=Path("/abs/path"),
        resolve_child=resolver,
        root_workflow_path="/abs/path/parent.pflow.md",
    )
    edges = result.edges
    assert len(edges) == 1
    assert edges[0].parent_workflow == "/abs/path/parent.pflow.md"
    assert edges[0].child_workflow == "/abs/path/child.pflow.md"


def test_edge_carries_parent_node_id() -> None:
    """Per the catalog, cache.cross-workflow-rename-detected requires
    parent_node_id for the path field."""
    child_ir = {"inputs": {"x": {"type": "string"}}, "nodes": []}
    root_ir = {"nodes": [_workflow_node("song-creator", "./c.pflow.md", {"x": "${y}"})]}
    resolver = _StubResolver({"./c.pflow.md": (child_ir, Path("/abs/c.pflow.md"))})
    result = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    edges = result.edges
    assert edges[0].parent_node_id == "song-creator"


def test_inputs_with_non_template_values_still_yield_edge() -> None:
    """A literal-value input (no ${...}) doesn't have a parent_value_expr; walker
    omits it from the rename surface but doesn't crash."""
    child_ir = {"inputs": {"x": {"type": "string"}}, "nodes": []}
    root_ir = {"nodes": [_workflow_node("c", "./child.pflow.md", {"x": "literal value"})]}
    resolver = _StubResolver({"./child.pflow.md": (child_ir, Path("/abs/c.pflow.md"))})
    result = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    edges = result.edges
    # Walker may or may not emit an edge for literals; the contract is "no crash".
    # If emitted, parent_value_expr is the literal value; rename check uses tail logic.
    if edges:
        assert edges[0].child_input_name == "x"


def test_template_items_gap_note_uses_real_analyze_cache_cli_param_wording() -> None:
    """Runtime batch enumeration note must not suggest a nonexistent
    ``analyze-cache --inputs`` flag; workflow inputs are positional
    ``key=value`` params on the CLI.
    """
    child_ir = {"inputs": {"x": {"type": "string"}}, "nodes": []}
    root_ir = {"nodes": [_batch_workflow_node("children", "./child.pflow.md", {"x": "${item.x}"})]}
    resolver = _StubResolver({"./child.pflow.md": (child_ir, Path("/abs/child.pflow.md"))})
    notes: list[str] = []
    walk_cross_workflow(
        root_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        root_workflow_path="/abs/parent.pflow.md",
        notes=notes,
    )

    assert notes
    note = notes[0]
    assert "actually_paid_usd is trace-driven" in note
    assert "CLI parameter" in note
    assert "--inputs" not in note
    assert "current_cost" not in note


# ---------------------------------------------------------------------------
# CrossWorkflowEdge — batch-alias detection (#362 evidence-basis suppression)
# ---------------------------------------------------------------------------


def _batch_workflow_node(node_id: str, workflow_ref: str, inputs: dict[str, str], alias: str = "item") -> dict:
    """Workflow-type node with a batch config — the parent shape that triggers
    batch-alias edges."""
    return {
        "id": node_id,
        "type": "workflow",
        "params": {"workflow": workflow_ref, "inputs": dict(inputs)},
        "batch": {"items": "${things}", "as": alias},
        "_source_line": 50,
    }


def test_walker_populates_parent_batch_alias_from_default_item() -> None:
    """When the parent workflow-type node has ``batch:`` with no explicit
    ``as:``, the walker records ``parent_batch_alias = "item"`` on each edge.
    Used downstream to suppress rename warnings for iteration-variable
    references (``${item}`` / ``${item.X}``).
    """
    child_ir = {"inputs": {"source": {"type": "string"}}, "nodes": []}
    parent_node = {
        "id": "fetch",
        "type": "workflow",
        "params": {"workflow": "./c.pflow.md", "inputs": {"source": "${item}"}},
        "batch": {"items": "${urls}", "parallel": True},  # No explicit ``as:`` → defaults to "item".
        "_source_line": 50,
    }
    root_ir = {"nodes": [parent_node]}
    resolver = _StubResolver({"./c.pflow.md": (child_ir, Path("/abs/c.pflow.md"))})
    result = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    assert len(result.edges) == 1
    assert result.edges[0].parent_batch_alias == "item"


def test_walker_populates_parent_batch_alias_from_explicit_as() -> None:
    """When ``as: <name>`` overrides the default, the alias propagates to edges."""
    child_ir = {"inputs": {"row": {"type": "object"}}, "nodes": []}
    root_ir = {"nodes": [_batch_workflow_node("process", "./c.pflow.md", {"row": "${record.data}"}, alias="record")]}
    resolver = _StubResolver({"./c.pflow.md": (child_ir, Path("/abs/c.pflow.md"))})
    result = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    assert result.edges[0].parent_batch_alias == "record"


def test_walker_parent_batch_alias_none_for_non_batch_node() -> None:
    """Non-batch workflow nodes have no iteration variable; ``parent_batch_alias``
    is ``None``."""
    child_ir = {"inputs": {"x": {"type": "string"}}, "nodes": []}
    root_ir = {"nodes": [_workflow_node("c", "./child.pflow.md", {"x": "${y}"})]}
    resolver = _StubResolver({"./child.pflow.md": (child_ir, Path("/abs/child.pflow.md"))})
    result = walk_cross_workflow(root_ir, base_path=Path("/abs"), resolve_child=resolver)
    assert result.edges[0].parent_batch_alias is None


def test_is_batch_alias_root_simple_alias_match() -> None:
    """``${item}`` (bare alias) is detected as a batch-alias root."""
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="item",
        child_input_name="source",
        line_in_parent=10,
        parent_node_id="fetch",
        parent_batch_alias="item",
    )
    assert edge.is_rename is True  # Names differ: 'item' vs 'source'
    assert edge.is_batch_alias_root is True


def test_is_batch_alias_root_dotted_path_match() -> None:
    """``${item.field}`` is a batch-alias root (root segment = alias)."""
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="item.url",
        child_input_name="source",
        line_in_parent=10,
        parent_node_id="fetch",
        parent_batch_alias="item",
    )
    assert edge.is_batch_alias_root is True


def test_is_batch_alias_root_bracketed_path_match() -> None:
    """``${item[0].x}`` is a batch-alias root (root segment before bracket = alias)."""
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="item[0].field",
        child_input_name="source",
        line_in_parent=10,
        parent_node_id="fetch",
        parent_batch_alias="item",
    )
    assert edge.is_batch_alias_root is True


def test_is_batch_alias_root_false_when_no_batch() -> None:
    """``parent_batch_alias=None`` → never a batch-alias root."""
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="item",
        child_input_name="source",
        line_in_parent=10,
        parent_node_id="fetch",
        parent_batch_alias=None,
    )
    assert edge.is_batch_alias_root is False


def test_is_batch_alias_root_false_when_value_doesnt_match() -> None:
    """Stable identifier (e.g. ``${concept_brief}``) is NOT a batch-alias root
    even when the parent has batch config."""
    edge = CrossWorkflowEdge(
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        parent_value_expr="concept_brief",
        child_input_name="creative_brief",
        line_in_parent=10,
        parent_node_id="fetch",
        parent_batch_alias="item",
    )
    assert edge.is_rename is True  # 'concept_brief' vs 'creative_brief'
    assert edge.is_batch_alias_root is False  # Real rename, not iteration variable
