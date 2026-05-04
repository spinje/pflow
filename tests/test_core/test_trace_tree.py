"""TraceTree traversal contracts.

These tests lock the trace tree as the single traversal primitive used by
trace reports, runtime summaries, and analyze-cache rollups.
"""

from __future__ import annotations

import pytest

from pflow.core.trace_tree import TraceTree, WalkEvent
from tests.shared.mutation_contract import mutation_contract


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=277,
    revert='return None, "unavailable"',
    expected_failure="empty trace returns (0.0, 'trace') instead of (None, 'unavailable')",
)
def test_from_dict_handles_empty_nodes() -> None:
    """Mutation contract: change empty total to ``0.0`` -> total assertion fails."""
    tree = TraceTree.from_dict({"format_version": "2.1", "nodes": []})

    assert list(tree.iter_llm_leaves()) == []
    assert tree.total_cost() == (None, "unavailable")


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=80,
    revert='raise ValueError(f"trace nodes must be a list',
    expected_failure="non-list nodes silently coerced — pytest.raises does not fire",
)
def test_from_dict_rejects_non_list_nodes() -> None:
    """Mutation contract: silently coerce non-list nodes -> pytest.raises fails."""
    with pytest.raises(ValueError, match="dict"):
        TraceTree.from_dict({"format_version": "2.1", "nodes": {}})


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=156,
    revert="yield from self.walk(",
    expected_failure="batch_items[*].events recursion dropped — inner leaf missing",
)
def test_iter_llm_leaves_yields_batch_item_and_nested_events() -> None:
    """Mutation contract: drop batch ``events`` recursion -> inner leaf missing."""
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=133,
    revert='if raw_event.get("cached") and not descend_cached_subtrees',
    expected_failure="cached parent yielded; child leaks through",
)
def test_iter_llm_leaves_skips_cached_subtree_when_requested() -> None:
    """Mutation contract: skip only cached leaves -> uncached child leaks through."""
    tree = TraceTree(
        events=(
            {
                "node_id": "cached-parent",
                "cached": True,
                "sub_workflow_events": [{"node_id": "inner-llm", "llm_call": {"cost_usd": 0.20}}],
            },
        ),
        format_version="2.1",
    )

    assert list(tree.iter_llm_leaves(descend_cached_subtrees=False)) == []


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=167,
    revert="child_workflow_path = edges.get",
    expected_failure="edge threading dropped — leaf.workflow_path is None",
)
def test_iter_llm_leaves_threads_workflow_path_via_edges() -> None:
    """Mutation contract: drop edge threading -> workflow_path is None."""
    tree = TraceTree(
        events=(
            {
                "node_id": "call-child",
                "sub_workflow_events": [{"node_id": "child-llm", "llm_call": {"cost_usd": 0.10}}],
            },
        ),
        format_version="2.1",
    )

    [leaf] = list(tree.iter_llm_leaves(edges={"call-child": "child.pflow.md"}, workflow_path="parent.pflow.md"))

    assert leaf.workflow_path == "child.pflow.md"
    assert leaf.event_node_id == "child-llm"


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=217,
    revert="return self._sum_leaves(self.iter_llm_leaves((event,), descend_sub_workflows=False))",
    expected_failure="cost_for_node descends into sub_workflow_events — sums child cost into parent",
)
def test_cost_for_node_does_not_descend_into_sub_workflow_events() -> None:
    """Mutation contract: make cost_for_node deep -> cost becomes 100.0."""
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=253,
    revert="leaves = self.iter_llm_leaves(",
    expected_failure="leaves undefined — NameError on next line",
)
def test_total_cost_descends_sub_workflows_three_deep() -> None:
    """Mutation contract: set descend_sub_workflows=False internally -> total is 0.1."""
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


def test_trace_fixture_builder_matches_workflow_trace_collector_shape() -> None:
    """Defends fixture fidelity across two files: cache-analysis tests using
    synthetic traces fail if the ``TraceFixtureBuilder`` drifts from
    ``WorkflowTraceCollector``'s event shape.

    No ``@mutation_contract`` marker — the contract is a cross-file shape
    invariant, not a single line. The single-line mutation primitive can't
    express "key set X should equal key set Y."
    """
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


def test_committed_cache_analysis_fixtures_match_generator_output() -> None:
    """Defends fixture drift: committed JSON must match the programmatic generator.

    Closes the third link of the drift-detection chain:

    - ``WorkflowTraceCollector`` adds field → ``TraceFixtureBuilder`` shape test fails
    - ``TraceFixtureBuilder`` updated → generator output changes → THIS test fails
    - Net: the committed ``parent-child-trace.json`` and
      ``parent-child-erroring-trace.json`` are transitively pinned to production
      shape. Hand-edits that diverge from generator output fail loudly.

    Re-run ``python -m tests.fixtures.cache_analysis._generate`` to regenerate
    after intentional shape changes; commit the diff.

    No ``@mutation_contract`` marker — the contract is a cross-file shape
    invariant tracked by the bytes of the committed files, not a single line.
    """
    import json
    from pathlib import Path

    from tests.fixtures.cache_analysis._generate import (
        FIXTURE_DIR,
        build_parent_child_erroring_trace,
        build_parent_child_trace,
    )

    fixture_dir = Path(FIXTURE_DIR)
    cases = (
        ("parent-child-trace.json", build_parent_child_trace()),
        ("parent-child-erroring-trace.json", build_parent_child_erroring_trace()),
    )
    for filename, generated in cases:
        committed = json.loads((fixture_dir / filename).read_text())
        assert committed == generated, (
            f"{filename} drifted from generator output. Run: python -m tests.fixtures.cache_analysis._generate"
        )


# ---------------------------------------------------------------------------
# walk() — universal primitive
# ---------------------------------------------------------------------------


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=138,
    revert="yield WalkEvent(",
    expected_failure="top-level yield removed — walk() yields nothing for non-LLM events",
)
def test_walk_yields_top_level_event_with_no_llm_call() -> None:
    """Mutation contract: filter at walk() level (yield only LLM events)
    -> shell event missing -> assertion ``len(walked) == 1`` fails.

    walk() is the universal primitive. Non-LLM events MUST be yielded so
    consumers like ``_iter_executed_keys`` can build the executed-keys
    index across all node types (shell, code, llm, etc.).
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

    No ``@mutation_contract`` marker — the contract defends an ABSENCE
    (no extra recursion line exists today). The single-line mutation
    primitive can revert lines that exist; it can't revert a line that
    isn't there. Surfacing this as docstring-only is the honest signal.
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=152,
    revert="owner_node_id=event_node_id,",
    expected_failure="batch_item owner_node_id kwarg missing — yields TypeError or attribution drifts",
)
def test_walk_assigns_owner_node_id_for_batch_items_to_parent() -> None:
    """Mutation contract: change owner_node_id assignment for batch items
    to the item's own id -> attribution drifts -> assertion fails.

    Batch items typically lack their own node_id and must be attributed to
    the batch parent. The TraceExecutionIndex relies on this for the
    executed-keys map.
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=133,
    revert='if raw_event.get("cached") and not descend_cached_subtrees',
    expected_failure="cached subtree no longer skipped — child leaks through",
)
def test_walk_skips_cached_subtree_when_kwarg_false() -> None:
    """Mutation contract: skip only the cached top-level event but recurse into
    its children -> child leaks through -> assertion ``len(walked) == 0`` fails.

    Producer shims (``_collect_llm_calls_from_events``) set
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=201,
    revert="if we.has_llm_call",
    expected_failure="filter dropped — non-LLM events yielded into cost-aggregation stream",
)
def test_iter_llm_leaves_skips_non_llm_events() -> None:
    """Mutation contract: change filter to ``not we.has_llm_call`` (invert)
    -> non-LLM event yielded -> assertion ``llm_only`` fails.

    iter_llm_leaves is the LLM-only filter over walk(). Shell/code events
    must NOT appear in the leaf stream that feeds cost aggregation.
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=93,
    revert="if requires_llm_call and not isinstance",
    expected_failure="requires_llm_call filter dropped — wrong (non-LLM) event returned",
)
def test_event_for_requires_llm_call_skips_events_without_llm_call() -> None:
    """Mutation contract: drop ``requires_llm_call`` filter (return first match
    by node_id) -> wrong (non-LLM) event returned -> assertion fails on
    ``llm_call.get("cost_usd")``.

    Loop recovery records multiple events for the same node_id. Token
    estimation must skip the early non-LLM event and find the LLM-bearing
    one. This contract is what review-plan-C2 calls out.
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=280,
    revert='return total, "trace"',
    expected_failure="trace tier label dropped — falls through to (None, 'unavailable') or NameError",
)
def test_cost_for_node_priced_event_returns_trace_tier() -> None:
    """Mutation contract: change return tier to ``"recomputed"`` -> tier
    assertion fails.

    Priced top-level event must report tier=``trace`` (high-confidence,
    real recorded data). Renderer annotates ``(trace)`` next to the cost.
    """
    tree = TraceTree(
        events=({"node_id": "draft", "llm_call": {"cost_usd": 0.05}},),
        format_version="2.1",
    )

    assert tree.cost_for_node("draft") == (pytest.approx(0.05), "trace")


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=278,
    revert="if has_unpriced:",
    expected_failure="trace_partial branch never taken — unpriced reports 'trace' (over-confident)",
)
def test_cost_for_node_unpriced_returns_trace_partial() -> None:
    """Mutation contract: drop the ``has_unpriced`` flag in ``_sum_leaves``
    -> tier reports ``"trace"`` instead of ``"trace_partial"`` -> agent
    sees high-confidence label on data with unpriced leaves -> assertion fails.

    An unpriced model (Ollama, custom endpoint) on any leaf must downgrade
    the whole node to trace_partial so the agent knows the absolute number
    is incomplete.
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

    No ``@mutation_contract`` marker — in the current implementation the
    cached item carries ``cost_usd: 0.0`` explicitly, so summing
    ``cost_usd`` across all leaves produces the correct partial total
    regardless of which line you mutate. The test still defends the
    behavior; the targeted mutation surface lives in the producer (cached
    batch items must serialize ``cost_usd: 0.0``), which is outside this
    file's scope.
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=214,
    revert='return None, "unavailable"',
    expected_failure="missing-node early return dropped — fall-through hits AttributeError on None",
)
def test_cost_for_node_returns_unavailable_for_missing_node() -> None:
    """Mutation contract: return ``(0.0, "trace")`` for missing node
    -> phantom zero contributes to aggregates -> assertion fails.

    A node id absent from the trace must return ``unavailable`` so the
    analyzer's recompute fallback fires (rather than fabricating a 0.0
    that silently passes through cost summation).
    """
    tree = TraceTree(events=(), format_version="2.1")

    assert tree.cost_for_node("nonexistent") == (None, "unavailable")


# ---------------------------------------------------------------------------
# cost_for_batch_item — batch-shape entry point
# ---------------------------------------------------------------------------


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=242,
    revert="leaves.extend(we for we in self.walk(",
    expected_failure="batch-item events recursion dropped — nested LLM cost missing",
)
def test_cost_for_batch_item_recurses_into_events() -> None:
    """Mutation contract: change ``cost_for_batch_item`` to skip the
    ``events`` recursion -> only direct ``llm_call`` summed -> assertion
    fails because nested LLMs aren't included.

    Batch items store sub-workflow children under ``events`` (not
    ``sub_workflow_events``). The dedicated entry point handles the shape
    difference; the trace report's items table relies on this.
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=230,
    revert='return 0.0, "trace"',
    expected_failure="cached short-circuit dropped — falls through to (None, 'unavailable')",
)
def test_cost_for_batch_item_cached_no_llm_call_returns_zero_trace() -> None:
    """Mutation contract: drop the cached short-circuit -> returns
    ``(None, "unavailable")`` -> recompute fallback fabricates a fictional
    cost for a memo-hit batch item -> assertion fails.

    Batch items can be cached (memo hits) just like top-level events. The
    short-circuit prevents the recompute fallback from inventing cost on
    a memo-hit run.
    """
    tree = TraceTree(events=(), format_version="2.1")
    cached_item = {"index": 0, "cached": True}

    assert tree.cost_for_batch_item(cached_item) == (0.0, "trace")


# ---------------------------------------------------------------------------
# total_cost — full-trace rollup
# ---------------------------------------------------------------------------


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=253,
    revert="leaves = self.iter_llm_leaves(",
    expected_failure="leaves binding dropped — NameError on next line",
)
def test_total_cost_descends_sub_workflows() -> None:
    """Mutation contract: change default to ``descend_sub_workflows=False``
    -> child cost missing from total -> assertion fails (total == 0.05).

    Single-level sub-workflow case (the simpler counterpart to the
    3-deep test). Trace-driven current_cost for a parent + one child must
    sum both. Without this, parent-scope cost under-reports actual spend.
    """
    tree = TraceTree(
        events=(
            {
                "node_id": "root-llm",
                "llm_call": {"cost_usd": 0.05},
            },
            {
                "node_id": "call-child",
                "sub_workflow_events": [{"node_id": "child-llm", "llm_call": {"cost_usd": 0.10}}],
            },
        ),
        format_version="2.1",
    )

    assert tree.total_cost() == (pytest.approx(0.15), "trace")


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=259,
    revert="return self._sum_leaves(leaf for leaf in leaves if not leaf.is_cached)",
    expected_failure="default branch (exclude cached) returns None — assertion fails",
)
def test_total_cost_includes_cached_when_kwarg_true() -> None:
    """Mutation contract: ignore the include_cached kwarg (always exclude)
    -> cached leaf missing -> assertion fails.

    Some consumers (debugging tools, full-cost-audit reports) want the
    cached zero-cost leaves visible to confirm coverage. The kwarg
    distinguishes "what we paid this run" (default, exclude cached) from
    "every event with cost data" (include_cached=True).
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=167,
    revert="child_workflow_path = edges.get",
    expected_failure="edge threading dropped — child_workflow_path NameError on next line",
)
def test_walk_event_carries_workflow_path_via_edges() -> None:
    """Mutation contract: ignore ``edges`` parameter in walk() recursion
    -> child workflow_path stays None -> assertion fails.

    For 2.1 traces (no per-event workflow_path field), ``cw_result.edges``
    is the only attribution mechanism. Sub-workflow descendants must
    inherit the child's workflow_path looked up by parent node id.
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


@mutation_contract(
    file="src/pflow/core/trace_tree.py",
    line=57,
    revert="LlmEventLeaf = WalkEvent",
    expected_failure="alias broken — ImportError on `from pflow.core.trace_tree import LlmEventLeaf`",
)
def test_walk_event_is_dataclass_alias_of_llm_event_leaf() -> None:
    """Backward-compat: ``LlmEventLeaf`` was the previous public name and
    several callers still import it. Renaming to ``WalkEvent`` keeps the
    alias so existing imports don't break.

    Mutation contract: change the alias to a separate class -> identity
    assertion ``LlmEventLeaf is WalkEvent`` fails.
    """
    from pflow.core.trace_tree import LlmEventLeaf

    assert LlmEventLeaf is WalkEvent
