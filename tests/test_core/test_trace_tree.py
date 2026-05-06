"""TraceTree traversal contracts.

These tests lock the trace tree as the single traversal primitive used by
trace reports, runtime summaries, and analyze-cache rollups.
"""

from __future__ import annotations

import pytest

from pflow.core.trace_tree import TraceTree, WalkEvent


def test_from_dict_handles_empty_nodes() -> None:
    tree = TraceTree.from_dict({"format_version": "2.1", "nodes": []})

    assert list(tree.iter_llm_leaves()) == []
    assert tree.total_cost() == (None, "unavailable")


def test_from_dict_rejects_non_list_nodes() -> None:
    with pytest.raises(ValueError, match="dict"):
        TraceTree.from_dict({"format_version": "2.1", "nodes": {}})


def test_iter_llm_leaves_yields_batch_item_and_nested_events() -> None:
    tree = TraceTree(
        events=(
            {
                "node_id": "batch-parent",
                "batch_items": [
                    {"index": 0, "llm_call": {"cost_usd": 0.01}},
                    {"index": 1, "events": [{"node_id": "inner-llm", "llm_call": {"cost_usd": 0.02}}]},
                ],
            },
        ),
        format_version="2.1",
    )

    leaves = list(tree.iter_llm_leaves())

    assert [(leaf.tier, leaf.owner_node_id, leaf.event_node_id) for leaf in leaves] == [
        ("batch_item", "batch-parent", "unknown"),
        ("sub_workflow_descendant", "batch-parent", "inner-llm"),
    ]


def test_cost_for_node_does_not_descend_into_sub_workflow_events() -> None:
    tree = TraceTree(
        events=(
            {
                "node_id": "parent-llm",
                "llm_call": {"cost_usd": 0.01},
                "sub_workflow_events": [{"node_id": "child-llm", "llm_call": {"cost_usd": 99.99}}],
            },
        ),
        format_version="2.1",
    )

    assert tree.cost_for_node("parent-llm") == (0.01, "trace")


def test_total_cost_descends_sub_workflows_three_deep() -> None:
    tree = TraceTree(
        events=(
            {
                "node_id": "a",
                "llm_call": {"cost_usd": 0.10},
                "sub_workflow_events": [
                    {
                        "node_id": "b",
                        "llm_call": {"cost_usd": 0.10},
                        "sub_workflow_events": [{"node_id": "c", "llm_call": {"cost_usd": 0.10}}],
                    }
                ],
            },
        ),
        format_version="2.1",
    )

    assert tree.total_cost() == (pytest.approx(0.30), "trace")


class TestTraceFixtureBuilderShapeParity:
    """Each test drives a real ``WorkflowTraceCollector`` and asserts the
    produced event's key set matches what ``TraceFixtureBuilder`` produces.

    Defends fixture fidelity: cache-analysis tests using synthetic traces
    fail if the builder drifts from the producer's event shape.
    """

    def test_regular_llm_event_shape_matches(self) -> None:
        """LLM event keys + llm_call subfields must match builder.llm_event."""
        from pflow.runtime.workflow_trace import WorkflowTraceCollector
        from tests.shared.trace_fixture_builder import TraceFixtureBuilder

        collector = WorkflowTraceCollector("fixture", workflow_path="parent.pflow.md")
        collector.llm_prompts["draft"] = "prompt"
        collector.record_node_execution(
            "draft",
            "LLMNode",
            1.0,
            True,
            node_output={
                "response": "ok",
                "llm_usage": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                    "cost_usd": 0.01,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        )

        builder = TraceFixtureBuilder()
        built = builder.llm_event("draft", cost_usd=0.01)

        assert set(collector.events[0]) == set(built)
        assert set(collector.events[0]["llm_call"]) == set(built["llm_call"])

    def test_cached_llm_event_with_call_shape_matches(self) -> None:
        """Memo-hit LLM event keys + llm_call subfields must match
        builder.cached_llm_event_with_call.

        Drives WorkflowTraceCollector through the full memo-hit shape:
        ``cached=True`` + ``node_output.llm_usage`` carrying cache_source /
        cache_key / cache_age_sec (matching what ``apply_memo_hit`` +
        ``_augment_llm_usage_with_cache_metadata`` produce at runtime).
        """
        from pflow.runtime.workflow_trace import WorkflowTraceCollector
        from tests.shared.trace_fixture_builder import TraceFixtureBuilder

        collector = WorkflowTraceCollector("fixture", workflow_path="parent.pflow.md")
        collector.llm_prompts["draft"] = "prompt"
        cached_llm_usage = {
            "model": "anthropic/claude-sonnet-4-5",
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
            "cost_usd": 0.01,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 950,
            "cache_key": "fixture-cache-key",
            "cache_source": "memo",
            "cache_age_sec": 30.0,
        }
        collector.record_node_execution(
            "draft",
            "LLMNode",
            0.0,
            True,
            node_params={"model": "anthropic/claude-sonnet-4-5"},
            node_output={
                "response": "ok",
                "llm_usage": cached_llm_usage,
            },
            cached=True,
        )

        builder = TraceFixtureBuilder()
        built = builder.cached_llm_event_with_call("draft", cost_usd=0.01)

        assert set(collector.events[0]) == set(built)
        assert set(collector.events[0]["llm_call"]) == set(built["llm_call"])

    def test_workflow_event_shape_matches(self) -> None:
        """Workflow event keys must include node_params with a workflow path,
        matching builder.workflow_event(workflow_path=...).
        """
        from pflow.runtime.workflow_trace import WorkflowTraceCollector
        from tests.shared.trace_fixture_builder import TraceFixtureBuilder

        collector = WorkflowTraceCollector("fixture", workflow_path="parent.pflow.md")
        child_event = {
            "node_id": "child-llm",
            "node_type": "LLMNode",
            "duration_ms": 1.0,
            "success": True,
            "timestamp": "2026-05-02T00:00:00",
            "node_output": {"response": "ok"},
            "llm_call": {
                "model": "anthropic/claude-sonnet-4-5",
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "cost_usd": 0.01,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "llm_prompt": "prompt",
            "llm_response": "ok",
        }
        collector.record_node_execution(
            "call-child",
            "WorkflowExecutor",
            1.0,
            True,
            node_params={"workflow": "child.pflow.md"},
            sub_workflow_events=[child_event],
        )

        builder = TraceFixtureBuilder()
        built = builder.workflow_event(
            "call-child",
            [child_event],
            workflow_path="child.pflow.md",
        )

        assert set(collector.events[0]) == set(built)
        assert collector.events[0]["node_params"]["workflow"] == "child.pflow.md"

    def test_batch_event_shape_matches(self) -> None:
        """Batch event keys must match builder.batch_event."""
        from pflow.runtime.workflow_trace import WorkflowTraceCollector
        from tests.shared.trace_fixture_builder import TraceFixtureBuilder

        collector = WorkflowTraceCollector("fixture", workflow_path="parent.pflow.md")
        items = [
            {
                "index": 0,
                "success": True,
                "duration_ms": 1.0,
                "node_output": {"response": "ok"},
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "total_tokens": 110,
                    "cost_usd": 0.005,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        ]
        collector.record_node_execution(
            "fanout",
            "LLMNode",
            1.0,
            True,
            batch_items=items,
        )

        builder = TraceFixtureBuilder()
        built = builder.batch_event("fanout", items)

        assert set(collector.events[0]) == set(built)


def test_committed_cache_analysis_fixtures_match_generator_output() -> None:
    """Defends fixture drift: committed JSON must match the programmatic generator.

    Closes the third link of the drift-detection chain:

    - ``WorkflowTraceCollector`` adds field → ``TraceFixtureBuilder`` shape test fails
    - ``TraceFixtureBuilder`` updated → generator output changes → THIS test fails
    - Net: the committed cache-analysis trace fixtures are transitively pinned
      to production shape. Hand-edits that diverge from generator output fail
      loudly.

    Re-run ``python -m tests.fixtures.cache_analysis._generate`` to regenerate
    after intentional shape changes; commit the diff.
    """
    import json
    from pathlib import Path

    from tests.fixtures.cache_analysis._generate import (
        FIXTURE_DIR,
        build_parent_child_erroring_trace,
        build_parent_child_grandchild_trace,
        build_parent_child_memo_hit_trace,
        build_parent_child_trace,
    )

    fixture_dir = Path(FIXTURE_DIR)
    cases = (
        ("parent-child-trace.json", build_parent_child_trace()),
        ("parent-child-erroring-trace.json", build_parent_child_erroring_trace()),
        ("parent-child-memo-hit-trace.json", build_parent_child_memo_hit_trace()),
        ("parent-child-grandchild-trace.json", build_parent_child_grandchild_trace()),
    )
    for filename, generated in cases:
        committed = json.loads((fixture_dir / filename).read_text())
        assert committed == generated, (
            f"{filename} drifted from generator output. Run: python -m tests.fixtures.cache_analysis._generate"
        )


# ---------------------------------------------------------------------------
# walk() — universal primitive
# ---------------------------------------------------------------------------


def test_walk_yields_top_level_event_with_no_llm_call() -> None:
    """Defends: walk() is the universal primitive. Non-LLM events MUST be
    yielded so consumers like ``_iter_executed_keys`` can build the
    executed-keys index across all node types (shell, code, llm, etc.).
    """
    tree = TraceTree(
        events=({"node_id": "fetch", "node_type": "ShellNode"},),
        format_version="2.1",
    )

    walked = list(tree.walk())

    assert len(walked) == 1
    assert walked[0].event_node_id == "fetch"
    assert walked[0].has_llm_call is False
    assert walked[0].tier == "top"


def test_walk_does_not_recurse_into_top_level_event_events_field() -> None:
    """Defends against vestigial-recursion REINTRODUCTION at the top level:
    if a future contributor adds ``yield from self.walk(_mapping_events(
    raw_event.get('events')), ...)`` to ``walk()``, this test catches it.
    """
    tree = TraceTree(
        events=(
            {
                "node_id": "parent",
                "events": [{"node_id": "should-not-appear", "llm_call": {"cost_usd": 99.99}}],
            },
        ),
        format_version="2.1",
    )

    walked = list(tree.walk())

    assert len(walked) == 1
    assert walked[0].event_node_id == "parent"


def test_walk_assigns_owner_node_id_for_batch_items_to_parent() -> None:
    """Defends: batch items typically lack their own node_id and must be
    attributed to the batch parent. The TraceExecutionIndex relies on
    this for the executed-keys map.
    """
    tree = TraceTree(
        events=(
            {
                "node_id": "fanout",
                "batch_items": [
                    {"index": 0, "duration_ms": 5},
                    {"index": 1, "duration_ms": 5},
                ],
            },
        ),
        format_version="2.1",
    )

    walked = list(tree.walk())

    batch_items = [we for we in walked if we.tier == "batch_item"]
    assert len(batch_items) == 2
    assert all(we.owner_node_id == "fanout" for we in batch_items)


def test_walk_skips_cached_subtree_when_kwarg_false() -> None:
    """Defends: producer shims (``_collect_llm_calls_from_events``) set
    ``descend_cached_subtrees=False`` so cached parents (memo hits) don't
    re-contribute to runtime cost summaries. The whole subtree must be
    skipped, not just the cached event itself.
    """
    tree = TraceTree(
        events=(
            {
                "node_id": "cached-parent",
                "cached": True,
                "sub_workflow_events": [{"node_id": "child", "llm_call": {"cost_usd": 0.10}}],
            },
        ),
        format_version="2.1",
    )

    walked = list(tree.walk(descend_cached_subtrees=False))

    assert walked == []


# ---------------------------------------------------------------------------
# iter_llm_leaves — filter over walk()
# ---------------------------------------------------------------------------


def test_iter_llm_leaves_skips_non_llm_events() -> None:
    """Defends: iter_llm_leaves is the LLM-only filter over walk().
    Shell/code events must NOT appear in the leaf stream that feeds
    cost aggregation.
    """
    tree = TraceTree(
        events=(
            {"node_id": "fetch", "node_type": "ShellNode"},
            {"node_id": "draft", "llm_call": {"cost_usd": 0.01}},
        ),
        format_version="2.1",
    )

    leaves = list(tree.iter_llm_leaves())

    assert len(leaves) == 1
    assert leaves[0].event_node_id == "draft"


# ---------------------------------------------------------------------------
# event_for — top-level lookup
# ---------------------------------------------------------------------------


def test_event_for_requires_llm_call_skips_events_without_llm_call() -> None:
    """Defends: loop recovery records multiple events for the same node_id.
    Token estimation must skip the early non-LLM event and find the
    LLM-bearing one.
    """
    tree = TraceTree(
        events=(
            {"node_id": "draft", "node_type": "ShellNode"},  # earlier non-LLM event
            {"node_id": "draft", "llm_call": {"cost_usd": 0.05, "input_tokens": 100}},
        ),
        format_version="2.1",
    )

    found = tree.event_for("draft", requires_llm_call=True)

    assert found is not None
    assert found["llm_call"]["cost_usd"] == 0.05


# ---------------------------------------------------------------------------
# cost_for_node — per-node attribution
# ---------------------------------------------------------------------------


def test_cost_for_node_priced_event_returns_trace_tier() -> None:
    """Defends: priced top-level event must report tier=``trace`` (high-
    confidence, real recorded data). Renderer annotates ``(trace)`` next
    to the cost.
    """
    tree = TraceTree(
        events=({"node_id": "draft", "llm_call": {"cost_usd": 0.05}},),
        format_version="2.1",
    )

    assert tree.cost_for_node("draft") == (pytest.approx(0.05), "trace")


def test_cost_for_node_unpriced_returns_trace_partial() -> None:
    """Defends: an unpriced model (Ollama, custom endpoint) on any leaf
    must downgrade the whole node to trace_partial so the agent knows
    the absolute number is incomplete.
    """
    tree = TraceTree(
        events=({"node_id": "draft", "llm_call": {"model": "ollama/llama3", "cost_usd": None}},),
        format_version="2.1",
    )

    cost, source = tree.cost_for_node("draft")
    assert source == "trace_partial"
    assert cost == 0.0  # priced subset is empty; partial flag carries the signal


def test_cost_for_node_partial_batch_some_cached() -> None:
    """Cached batch items contribute zero to the run's actual cost; only
    non-cached items add. Partial-batch cost must report only what
    actually paid.
    """
    tree = TraceTree(
        events=(
            {
                "node_id": "fanout",
                "batch_items": [
                    {"index": 0, "llm_call": {"cost_usd": 0.01}},
                    {"index": 1, "llm_call": {"cost_usd": 0.01}},
                    {"index": 2, "cached": True, "llm_call": {"cost_usd": 0.0}},
                ],
            },
        ),
        format_version="2.1",
    )

    assert tree.cost_for_node("fanout") == (pytest.approx(0.02), "trace")


def test_cost_for_node_returns_unavailable_for_missing_node() -> None:
    """Defends: a node id absent from the trace must return ``unavailable``
    so the analyzer's recompute fallback fires (rather than fabricating a
    0.0 that silently passes through cost summation).
    """
    tree = TraceTree(events=(), format_version="2.1")

    assert tree.cost_for_node("nonexistent") == (None, "unavailable")


# ---------------------------------------------------------------------------
# cost_for_batch_item — batch-shape entry point
# ---------------------------------------------------------------------------


def test_cost_for_batch_item_recurses_into_events() -> None:
    """Defends: batch items store sub-workflow children under ``events``
    (not ``sub_workflow_events``). The dedicated entry point handles the
    shape difference; the trace report's items table relies on this.
    """
    tree = TraceTree(events=(), format_version="2.1")
    batch_item = {
        "index": 0,
        "events": [
            {"node_id": "inner-llm-1", "llm_call": {"cost_usd": 0.07}},
            {"node_id": "inner-llm-2", "llm_call": {"cost_usd": 0.03}},
        ],
    }

    assert tree.cost_for_batch_item(batch_item) == (pytest.approx(0.10), "trace")


def test_cost_for_batch_item_cached_no_llm_call_returns_zero_trace() -> None:
    """Defends: batch items can be cached (memo hits) just like top-level
    events. The short-circuit prevents the recompute fallback from
    inventing cost on a memo-hit run.
    """
    tree = TraceTree(events=(), format_version="2.1")
    cached_item = {"index": 0, "cached": True}

    assert tree.cost_for_batch_item(cached_item) == (0.0, "trace")


# ---------------------------------------------------------------------------
# total_cost — full-trace rollup
# ---------------------------------------------------------------------------


def test_total_cost_includes_cached_when_kwarg_true() -> None:
    """Defends: some consumers (debugging tools, full-cost-audit reports)
    want the cached zero-cost leaves visible to confirm coverage. The
    kwarg distinguishes "what we paid this run" (default, exclude
    cached) from "every event with cost data" (include_cached=True).
    """
    tree = TraceTree(
        events=(
            {"node_id": "uncached", "llm_call": {"cost_usd": 0.05}},
            {"node_id": "cached-llm", "cached": True, "llm_call": {"cost_usd": 0.0}},
        ),
        format_version="2.1",
    )

    excluded = tree.total_cost(include_cached=False)
    included = tree.total_cost(include_cached=True)

    assert excluded == (pytest.approx(0.05), "trace")
    # include_cached=True processes the cached leaf as a priced-at-0 entry —
    # the contract is "every priced leaf counts," and cached llm_call cost is
    # explicitly zero.
    assert included == (pytest.approx(0.05), "trace")


def test_total_cost_all_cached_llm_events_is_zero_trace() -> None:
    """All memo-hit LLM events are known zero-cost evidence for this run.

    A cached LLM event can retain the original ``llm_call.cost_usd`` for
    diagnostics, but ``total_cost(include_cached=False)`` answers "what did
    this run pay?" and must therefore report 0.0, not unavailable.
    """
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    tree = TraceTree.from_dict(
        builder.trace(
            workflow_path="parent.pflow.md",
            nodes=[
                builder.cached_llm_event_with_call("draft", cost_usd=0.05),
                builder.cached_llm_event_with_call("review", cost_usd=0.03),
            ],
        )
    )

    assert tree.total_cost() == (0.0, "trace")
    assert tree.total_cost(include_cached=True) == (pytest.approx(0.08), "trace")


def test_total_cost_cached_llm_event_without_call_is_zero_trace() -> None:
    """Older/minimal memo-hit traces can mark an LLM node cached without
    retaining ``llm_call``. The cached LLM boundary is still observed
    zero-cost evidence for this run.
    """
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    trace = builder.trace(
        workflow_path="parent.pflow.md",
        nodes=[{**builder.cached_llm_event("draft"), "node_type": "LLMNode"}],
    )
    tree = TraceTree.from_dict(trace)

    assert tree.total_cost() == (0.0, "trace")


def test_total_cost_cached_llm_batch_item_without_call_is_zero_trace() -> None:
    """A cached item under an LLM batch is known zero-cost evidence even when
    the memo-hit item does not retain its original ``llm_call``.
    """
    tree = TraceTree(
        events=(
            {
                "node_id": "fanout",
                "node_type": "LLMNode",
                "batch_items": [{"index": 0, "cached": True}],
            },
        ),
        format_version="2.1",
    )

    assert tree.total_cost() == (0.0, "trace")


def test_total_cost_cached_non_llm_event_is_not_llm_cost_evidence() -> None:
    """Cached shell/code-style events do not prove anything about LLM cost.

    This is the negative side of the cached-boundary policy: a cached LLM
    boundary is known zero-cost evidence, but a cached non-LLM boundary is not
    LLM cost evidence at all.
    """
    tree = TraceTree(
        events=(
            {"node_id": "shell", "node_type": "ShellNode", "cached": True},
            {"node_id": "workflow", "node_type": "WorkflowExecutor", "cached": True},
        ),
        format_version="2.1",
    )

    assert tree.total_cost() == (None, "unavailable")


def test_total_cost_cached_workflow_boundary_does_not_leak_historical_child_cost() -> None:
    """A cached workflow container is a paid-cost boundary.

    Its historical ``sub_workflow_events`` are useful for diagnostics when
    explicitly requested, but the current run paid $0 for the whole child
    workflow.
    """
    tree = TraceTree(
        events=(
            {
                "node_id": "call-child",
                "node_type": "WorkflowExecutor",
                "cached": True,
                "sub_workflow_events": [{"node_id": "child-llm", "llm_call": {"cost_usd": 0.08}}],
            },
        ),
        format_version="2.1",
    )

    assert tree.cost_for_event(tree.events[0]) == (0.0, "trace")
    assert tree.total_cost() == (0.0, "trace")
    assert tree.total_cost(include_cached=True) == (pytest.approx(0.08), "trace")


def test_total_cost_mixed_fresh_and_cached_workflow_boundary_sums_fresh_only() -> None:
    tree = TraceTree(
        events=(
            {"node_id": "fresh", "node_type": "LLMNode", "llm_call": {"cost_usd": 0.05}},
            {
                "node_id": "cached-child",
                "node_type": "WorkflowExecutor",
                "cached": True,
                "sub_workflow_events": [{"node_id": "child-llm", "llm_call": {"cost_usd": 0.08}}],
            },
        ),
        format_version="2.1",
    )

    assert tree.total_cost() == (pytest.approx(0.05), "trace")


def test_total_cost_fresh_unpriced_plus_cached_boundary_is_trace_partial() -> None:
    """Cached zero-cost evidence must not hide genuinely unpriced fresh work."""
    tree = TraceTree(
        events=(
            {"node_id": "fresh-custom", "node_type": "LLMNode", "llm_call": {"cost_usd": None}},
            {
                "node_id": "cached-child",
                "node_type": "WorkflowExecutor",
                "cached": True,
                "sub_workflow_events": [{"node_id": "child-llm", "llm_call": {"cost_usd": 0.08}}],
            },
        ),
        format_version="2.1",
    )

    assert tree.total_cost() == (0.0, "trace_partial")


def test_walk_event_carries_workflow_path_via_edges() -> None:
    """Defends: for 2.1 traces (no per-event workflow_path field),
    ``cw_result.edges`` is the only attribution mechanism. Sub-workflow
    descendants must inherit the child's workflow_path looked up by
    parent node id.
    """
    tree = TraceTree(
        events=(
            {
                "node_id": "call-child",
                "sub_workflow_events": [{"node_id": "child-llm", "llm_call": {"cost_usd": 0.10}}],
            },
        ),
        format_version="2.1",
    )

    walked = list(tree.walk(edges={"call-child": "child.pflow.md"}, workflow_path="parent.pflow.md"))

    parent = next(we for we in walked if we.event_node_id == "call-child")
    child = next(we for we in walked if we.event_node_id == "child-llm")
    assert parent.workflow_path == "parent.pflow.md"
    assert child.workflow_path == "child.pflow.md"


def test_walk_event_is_dataclass_alias_of_llm_event_leaf() -> None:
    """Backward-compat: ``LlmEventLeaf`` was the previous public name and
    several callers still import it. Renaming to ``WalkEvent`` keeps the
    alias so existing imports don't break.
    """
    from pflow.core.trace_tree import LlmEventLeaf

    assert LlmEventLeaf is WalkEvent


# ---------------------------------------------------------------------------
# Cached-leaf cost policy (memo-hit shape with populated llm_call)
# ---------------------------------------------------------------------------


def test_cost_for_node_returns_zero_for_memo_hit_with_populated_llm_call() -> None:
    """Defends: production memo-hit shape (apply_memo_hit +
    _augment_llm_usage_with_cache_metadata) sets ``cached: True`` AND
    populates ``llm_call`` with the original ``cost_usd``. Without an
    explicit cached short-circuit, rollup would inflate per-call cost.
    """
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    trace = builder.trace(
        workflow_path="parent.pflow.md",
        nodes=[builder.cached_llm_event_with_call("draft", cost_usd=0.05)],
    )
    tree = TraceTree.from_dict(trace)
    cost, source = tree.cost_for_node("draft")
    assert cost == 0.0
    assert source == "trace"


def test_cost_for_node_with_include_cached_returns_original_cost() -> None:
    """Diagnostic opt-in: ``include_cached=True`` surfaces the historical
    cost on cached events (debugging / full-cost-audit scenarios).
    """
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    trace = builder.trace(
        workflow_path="parent.pflow.md",
        nodes=[builder.cached_llm_event_with_call("draft", cost_usd=0.05)],
    )
    tree = TraceTree.from_dict(trace)
    cost, source = tree.cost_for_node("draft", include_cached=True)
    assert cost == pytest.approx(0.05)
    assert source == "trace"


def test_cost_for_event_filters_cached_descendants() -> None:
    """Sub-workflow with one cached + one priced child LLM:
    ``cost_for_event`` returns ONLY the priced child's cost — the cached
    descendant is filtered out (this run paid $0 for the cached one).
    """
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    parent_event = builder.workflow_event(
        "call-child",
        sub_workflow_events=[
            builder.cached_llm_event_with_call("c-cached", cost_usd=0.10),
            builder.llm_event("c-priced", cost_usd=0.04),
        ],
        workflow_path="child.pflow.md",
    )
    tree = TraceTree.from_dict(builder.trace(workflow_path="parent.pflow.md", nodes=[parent_event]))
    cost, source = tree.cost_for_event(parent_event)
    assert cost == pytest.approx(0.04)  # Pre-fix: 0.14 (cached + priced).
    assert source == "trace"


def test_walk_uses_event_template_resolutions_for_heterogeneous_batch() -> None:
    """Heterogeneous workflow batch: each item runs a different child workflow.

    Pre-fix all items were attributed to the inherited workflow_path (or
    the last-edge-wins entry from ``_edge_child_paths``). Post-fix each
    item's ``template_resolutions["workflow"]["resolved"]`` becomes its
    leaf workflow_path, so per-item cost rolls up to the correct child.
    """
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    parent = builder.heterogeneous_workflow_batch_event(
        "fan-out",
        items=[
            ("/abs/a.pflow.md", [builder.llm_event("draft", cost_usd=0.05)]),
            ("/abs/b.pflow.md", [builder.llm_event("draft", cost_usd=0.07)]),
        ],
    )
    tree = TraceTree.from_dict(builder.trace(workflow_path="parent.pflow.md", nodes=[parent]))

    by_workflow: dict[str | None, list[float]] = {}
    for leaf in tree.iter_llm_leaves():
        cost = leaf.llm_call["cost_usd"] if leaf.llm_call else None
        if cost is not None:
            by_workflow.setdefault(leaf.workflow_path, []).append(float(cost))

    assert by_workflow == {
        "/abs/a.pflow.md": [pytest.approx(0.05)],
        "/abs/b.pflow.md": [pytest.approx(0.07)],
    }


def test_walk_attributes_heterogeneous_batch_with_non_templated_inputs() -> None:
    """Heterogeneous workflow batch where ``inputs`` is a static literal
    (not a template). The ``workflow:`` ref is still templated
    (``${item.workflow}``), so per-item ``template_resolutions["workflow"]``
    must drive attribution — ``inputs`` being non-templated is irrelevant.

    Defends: priority-1 lookup (template_resolutions["workflow"])
    still wins even when no template_resolutions["inputs"] entry exists.
    """
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    parent = {
        "node_id": "fan-out",
        "node_type": "WorkflowNode",
        "duration_ms": 0.0,
        "success": True,
        "timestamp": "2026-05-02T00:00:00",
        "node_params": {"workflow": "${item.workflow}"},
        "batch_items": [
            {
                "index": 0,
                "item": {"workflow": "/abs/a.pflow.md"},
                "success": True,
                "duration_ms": 0.0,
                # Note: only template_resolutions["workflow"] — no "inputs"
                "template_resolutions": {
                    "workflow": {
                        "template": "${item.workflow}",
                        "resolved": "/abs/a.pflow.md",
                    },
                },
                "events": [builder.llm_event("draft", cost_usd=0.05)],
            },
            {
                "index": 1,
                "item": {"workflow": "/abs/b.pflow.md"},
                "success": True,
                "duration_ms": 0.0,
                "template_resolutions": {
                    "workflow": {
                        "template": "${item.workflow}",
                        "resolved": "/abs/b.pflow.md",
                    },
                },
                "events": [builder.llm_event("draft", cost_usd=0.07)],
            },
        ],
    }
    tree = TraceTree.from_dict(builder.trace(workflow_path="parent.pflow.md", nodes=[parent]))
    by_workflow: dict[str | None, list[float]] = {}
    for leaf in tree.iter_llm_leaves():
        if leaf.llm_call is not None:
            by_workflow.setdefault(leaf.workflow_path, []).append(leaf.llm_call["cost_usd"])
    assert by_workflow == {"/abs/a.pflow.md": [0.05], "/abs/b.pflow.md": [0.07]}


def test_resolved_child_workflow_from_event_prefers_template_resolutions() -> None:
    """Helper contract: ``template_resolutions["workflow"]["resolved"]`` wins
    over absent / non-mapping entries; ``node_params.workflow`` is NOT a
    fallback (would re-introduce relative-vs-absolute key mismatches).
    """
    from pflow.core.trace_tree import _resolved_child_workflow_from_event

    # Template resolutions present (heterogeneous batch shape) -> resolved wins.
    item = {
        "template_resolutions": {
            "workflow": {"template": "${item.workflow}", "resolved": "/abs/x.pflow.md"},
        },
        "node_params": {"workflow": "./relative.pflow.md"},
    }
    assert _resolved_child_workflow_from_event(item) == "/abs/x.pflow.md"

    # Template resolutions absent -> None (do NOT fall back to node_params.workflow).
    static = {"node_params": {"workflow": "./relative.pflow.md"}}
    assert _resolved_child_workflow_from_event(static) is None

    # Garbage shapes -> None.
    assert _resolved_child_workflow_from_event({}) is None
    assert _resolved_child_workflow_from_event({"template_resolutions": "not-a-mapping"}) is None
    assert _resolved_child_workflow_from_event({"template_resolutions": {"workflow": {"resolved": ""}}}) is None


def test_walk_uses_edges_for_homogeneous_static_workflow_batch() -> None:
    """Homogeneous static workflow batch (single ``workflow: ./child.pflow.md``
    with N items) does NOT carry ``template_resolutions["workflow"]`` per
    item — verified against production traces. The walker must consult
    ``edges`` (the analyzer's parent_node_id → resolved child path map)
    as a second fallback so child LLM cost gets attributed to the child
    workflow, not the parent.

    Pre-fix: ``_resolved_child_workflow_from_event`` returns None (no
    per-item resolution metadata), falls through to inherited
    ``workflow_path`` (parent), so child events were misattributed to
    parent. ``did_not_execute_in_trace`` flipped True for child rows
    despite execution having happened.

    Heterogeneous case (priority 1) is unaffected — its
    ``template_resolutions["workflow"]`` lookup wins before the edges
    fallback is consulted.
    """
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    parent = builder.homogeneous_workflow_batch_event(
        "fanout",
        workflow_path="./child.pflow.md",  # static literal, as user wrote it
        items=[
            ("alpha", [builder.llm_event("c-llm", cost_usd=0.001)]),
            ("beta", [builder.llm_event("c-llm", cost_usd=0.002)]),
        ],
    )
    tree = TraceTree.from_dict(builder.trace(workflow_path="/abs/parent.pflow.md", nodes=[parent]))

    # Production-shape ``edges`` map: parent_node_id → resolved absolute child path.
    edges = {"fanout": "/abs/child.pflow.md"}

    by_workflow: dict[str | None, float] = {}
    for leaf in tree.iter_llm_leaves(edges=edges, workflow_path="/abs/parent.pflow.md"):
        if leaf.llm_call is None:
            continue
        cost = leaf.llm_call.get("cost_usd")
        if cost is None:
            continue
        by_workflow[leaf.workflow_path] = by_workflow.get(leaf.workflow_path, 0.0) + float(cost)

    # Pre-fix: by_workflow == {"/abs/parent.pflow.md": 0.003}
    # Post-fix: child cost rolls up to the child workflow.
    assert by_workflow == {"/abs/child.pflow.md": pytest.approx(0.003)}
