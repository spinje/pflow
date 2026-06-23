"""Programmatic generators for the committed cache-analysis trace fixtures.

Why this module exists: hand-crafted JSON fixtures drift silently from the
production ``WorkflowTraceCollector`` shape — a new field on the runtime side
isn't reflected in the fixture, but every test that consumes the fixture keeps
passing because nothing checks the shape contract. This module makes the
fixtures generator output instead, so:

- ``WorkflowTraceCollector`` adds a field → ``TraceFixtureBuilder`` fails its
  shape test (``test_trace_fixture_builder_matches_workflow_trace_collector_shape``)
- ``TraceFixtureBuilder`` updated → committed JSON drifts → drift test fails
- Drift detection chain: production shape → builder → committed fixture

Run as a script (``python -m tests.fixtures.cache_analysis._generate``) to
regenerate the JSON files when the builder shape changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.shared.trace_fixture_builder import TraceFixtureBuilder
from tests.shared.trace_jsonl import write_trace_jsonl

FIXTURE_DIR = Path(__file__).parent
PARENT_WORKFLOW_PATH = "tests/fixtures/cache_analysis/parent.pflow.md"
CHILD_WORKFLOW_PATH = "tests/fixtures/cache_analysis/child.pflow.md"
PARENT_3DEEP_WORKFLOW_PATH = "tests/fixtures/cache_analysis/parent-3deep.pflow.md"
CHILD_3DEEP_WORKFLOW_PATH = "tests/fixtures/cache_analysis/child-3deep.pflow.md"
GRANDCHILD_WORKFLOW_PATH = "tests/fixtures/cache_analysis/grandchild.pflow.md"

# Cost figures encoded here are load-bearing for downstream assertions:
# tests/test_cli/test_analyze_cache.py asserts actually_paid_usd == 0.15;
# tests/test_core/test_cache_analysis_analyze.py asserts == 0.12 for the
# erroring trace (parent $0.05 + child draft $0.07; review didn't execute).
_PARENT_DRAFT_COST = 0.05
_CHILD_DRAFT_COST = 0.07
_CHILD_REVIEW_COST = 0.03
_GRANDCHILD_DRAFT_COST = 0.03


def build_parent_child_trace() -> dict[str, Any]:
    """Successful run: parent draft + child draft + child review."""
    builder = TraceFixtureBuilder()
    parent_draft = builder.llm_event(
        "draft",
        cost_usd=_PARENT_DRAFT_COST,
        input_tokens=1000,
        output_tokens=100,
        cache_creation_input_tokens=200,
    )
    child_draft = builder.llm_event(
        "draft",
        cost_usd=_CHILD_DRAFT_COST,
        input_tokens=900,
        output_tokens=90,
        cache_creation_input_tokens=300,
    )
    child_review = builder.llm_event(
        "review",
        cost_usd=_CHILD_REVIEW_COST,
        input_tokens=800,
        output_tokens=80,
        cache_read_input_tokens=300,
    )
    call_child = builder.workflow_event(
        "call-child",
        [child_draft, child_review],
        workflow_path=CHILD_WORKFLOW_PATH,
    )
    return builder.trace(
        PARENT_WORKFLOW_PATH,
        [parent_draft, call_child],
        workflow_name="parent",
    )


def build_parent_child_erroring_trace() -> dict[str, Any]:
    """Erroring run: parent succeeded; child errored after the draft LLM.

    Defends phantom-cost suppression — the static IR enumerates a ``review``
    node in the child workflow that never ran. ``actually_paid_usd`` must
    reflect what fired ($0.05 + $0.07 = $0.12), not the IR's recompute.
    """
    builder = TraceFixtureBuilder()
    parent_draft = builder.llm_event(
        "draft",
        cost_usd=_PARENT_DRAFT_COST,
        input_tokens=1000,
        output_tokens=100,
        cache_creation_input_tokens=200,
    )
    child_draft = builder.llm_event(
        "draft",
        cost_usd=_CHILD_DRAFT_COST,
        input_tokens=900,
        output_tokens=90,
        cache_creation_input_tokens=300,
    )
    call_child = builder.workflow_event(
        "call-child",
        [child_draft],
        workflow_path=CHILD_WORKFLOW_PATH,
        success=False,
        error="child failed after first LLM",
    )
    return builder.trace(
        PARENT_WORKFLOW_PATH,
        [parent_draft, call_child],
        workflow_name="parent",
        failed_node_ids=["call-child"],
    )


def build_parent_child_memo_hit_trace() -> dict[str, Any]:
    """3-LLM-node trace: parent's draft costs $0.05; child has 2 memo-hit LLMs.

    Memo-hit LLMs carry ``cached: true`` AND ``llm_call.cost_usd > 0`` —
    the production shape that triggers Bug #1 if cached events aren't
    filtered out of the rollup's ``actually_paid_usd``.
    """
    builder = TraceFixtureBuilder()
    parent_draft = builder.llm_event(
        "draft",
        cost_usd=_PARENT_DRAFT_COST,
        input_tokens=1000,
        output_tokens=100,
        cache_creation_input_tokens=200,
    )
    child_draft = builder.cached_llm_event_with_call(
        "draft",
        cost_usd=_CHILD_DRAFT_COST,
    )
    child_review = builder.cached_llm_event_with_call(
        "review",
        cost_usd=_CHILD_REVIEW_COST,
    )
    call_child = builder.workflow_event(
        "call-child",
        [child_draft, child_review],
        workflow_path=CHILD_WORKFLOW_PATH,
    )
    return builder.trace(
        PARENT_WORKFLOW_PATH,
        [parent_draft, call_child],
        workflow_name="parent",
    )


def build_parent_child_grandchild_trace() -> dict[str, Any]:
    """3-deep trace: parent-3deep → child-3deep → grandchild, each with one priced LLM call.

    Uses dedicated parent-3deep / child-3deep .pflow.md files so the
    cross-workflow walker discovers all three workflows without disturbing
    the parent.pflow.md / child.pflow.md fixtures used by other tests.
    """
    builder = TraceFixtureBuilder()
    parent_draft = builder.llm_event(
        "draft",
        cost_usd=_PARENT_DRAFT_COST,
        input_tokens=1000,
        output_tokens=100,
    )
    grandchild_draft = builder.llm_event(
        "draft",
        cost_usd=_GRANDCHILD_DRAFT_COST,
        input_tokens=600,
        output_tokens=60,
    )
    call_grandchild = builder.workflow_event(
        "call-grandchild",
        [grandchild_draft],
        workflow_path=GRANDCHILD_WORKFLOW_PATH,
    )
    child_draft = builder.llm_event(
        "draft",
        cost_usd=_CHILD_DRAFT_COST,
        input_tokens=900,
        output_tokens=90,
    )
    call_child = builder.workflow_event(
        "call-child",
        [child_draft, call_grandchild],
        workflow_path=CHILD_3DEEP_WORKFLOW_PATH,
    )
    return builder.trace(
        PARENT_3DEEP_WORKFLOW_PATH,
        [parent_draft, call_child],
        workflow_name="parent-3deep",
    )


def write_fixtures() -> None:
    """Overwrite the committed JSONL fixtures with generator output."""
    _write_jsonl(FIXTURE_DIR / "parent-child-trace.json", build_parent_child_trace())
    _write_jsonl(FIXTURE_DIR / "parent-child-erroring-trace.json", build_parent_child_erroring_trace())
    _write_jsonl(FIXTURE_DIR / "parent-child-memo-hit-trace.json", build_parent_child_memo_hit_trace())
    _write_jsonl(FIXTURE_DIR / "parent-child-grandchild-trace.json", build_parent_child_grandchild_trace())


def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Write a committed fixture as Task-172 JSONL (the only format ``load_trace_file`` reads). The
    ``.json`` filename is kept — loaders content-detect via the ``pflow_trace`` marker line, not the
    extension."""
    write_trace_jsonl(path, payload)


if __name__ == "__main__":
    write_fixtures()
