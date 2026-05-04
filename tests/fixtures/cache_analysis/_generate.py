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

import json
from pathlib import Path
from typing import Any

from tests.shared.trace_fixture_builder import TraceFixtureBuilder

FIXTURE_DIR = Path(__file__).parent
PARENT_WORKFLOW_PATH = "tests/fixtures/cache_analysis/parent.pflow.md"

# Cost figures encoded here are load-bearing for downstream assertions:
# tests/test_cli/test_analyze_cache.py asserts actually_paid_usd == 0.15;
# tests/test_core/test_cache_analysis_analyze.py asserts == 0.12 for the
# erroring trace (parent $0.05 + child draft $0.07; review didn't execute).
_PARENT_DRAFT_COST = 0.05
_CHILD_DRAFT_COST = 0.07
_CHILD_REVIEW_COST = 0.03


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
    call_child = builder.workflow_event("call-child", [child_draft, child_review])
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
        success=False,
        error="child failed after first LLM",
    )
    return builder.trace(
        PARENT_WORKFLOW_PATH,
        [parent_draft, call_child],
        workflow_name="parent",
        failed_node_ids=["call-child"],
    )


def write_fixtures() -> None:
    """Overwrite the committed JSON fixtures with generator output."""
    _write_json(FIXTURE_DIR / "parent-child-trace.json", build_parent_child_trace())
    _write_json(FIXTURE_DIR / "parent-child-erroring-trace.json", build_parent_child_erroring_trace())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    write_fixtures()
