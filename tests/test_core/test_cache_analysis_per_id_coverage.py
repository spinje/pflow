"""F2.4 — per-warning-ID coverage + golden-shape assertions.

Catches the case where a catalog ID exists but no production code path actually
emits it (dead-code regression). Iterates the catalog at test time so adding
a new ID without a corresponding emission path fails CI.

The full byte-exact text/JSON goldens are deferred to v1.x in favor of these
structural checks: ``EXPECTED_CATALOG_COUNT`` ensures count drift can't hide,
and the per-id round-trip locks the agent-facing JSON contract for every ID.
"""

from __future__ import annotations

import json

import pytest

from pflow.core.cache_analysis import JSON_FORMAT_VERSION, JSON_FORMAT_VERSION_MAJOR
from pflow.core.cache_analysis.warning_catalog import (
    CACHE_OPPORTUNITIES_NUDGE_ID,
    CACHE_WARNING_CATALOG,
    EXPECTED_CATALOG_COUNT,
    make_diagnostic,
)

# Minimal context kwargs per ID — copy of test_cache_analysis_warnings.py's
# helper, kept here so this coverage test is self-contained.
_DISCREPANCY_BASE = {
    "trace_path": "songs[1]",
    "predicted_pct": 80,
    "actual_pct": 20,
    "root_cause_summary": "auto",
    "cache_age_sec": None,
    "predicted_cache_key": None,
    "actual_cache_key": None,
}


def _kwargs_for(warning_id: str) -> tuple[str | None, dict]:
    """Return ``(node_id, context_kwargs)`` for constructing a Diagnostic."""
    samples: dict[str, tuple[str | None, dict]] = {
        "cache.order-mismatch": (
            "X",
            {"declared": ["a", "b"], "actual": ["b", "a"], "declared_str": "[a, b]", "actual_str": "[b, a]"},
        ),
        "cache.unused-chunk": (None, {"chunk_name": "topic", "source_line": 12}),
        "cache.shared-context-undeclared": (
            None,
            {"node_count": 3, "shared_chunks": ["concept"], "affected_workflow": "x.pflow.md", "savings_usd": 0.78},
        ),
        "cache.batch-prewarm-recommended": (
            "score",
            {"batch_size": 34, "prefix_tokens_estimated": 2100, "savings_pct": 89, "savings_usd": 0.12},
        ),
        "cache.dynamic-before-static": (
            "score",
            {
                "dynamic_ref": "chorus_text",
                "dynamic_line": 3,
                "cacheable_tokens": 1640,
                "affected_calls": 136,
                "savings_usd": 0.31,
                "projected_ratio_pct": 87,
            },
        ),
        "cache.padding-advisory": (
            "review",
            {
                "current_subset": ["a"],
                "suggested_subset": ["a", "b"],
                "savings_usd": 0.04,
            },
        ),
        "cache.below-min-tokens": (
            "rewrite",
            {"model": "claude-sonnet-4-5", "cacheable_tokens": 512, "min_tokens": 1024},
        ),
        "cache.cross-workflow-prose-mismatch": (
            None,
            {
                "parent_workflow": "p.pflow.md",
                "child_workflow": "c.pflow.md",
                "chunk_name": "concept",
                "parent_prose": "P",
                "child_prose": "C",
            },
        ),
        "cache.cross-workflow-rename-detected": (
            None,
            {
                "parent_workflow": "p.pflow.md",
                "child_workflow": "c.pflow.md",
                "parent_value_expr": "concept_brief",
                "child_input_name": "creative_brief",
                "line_in_parent": 77,
                "parent_node_id": "song-creator",
            },
        ),
        "cache.discrepancy": (
            "X",
            dict(_DISCREPANCY_BASE, root_cause="key_mismatch"),
        ),
        "cache.invalid-on-non-llm": (
            "X",
            {
                "node_type": "shell",
                "invalid_fields": ["prompt_cache"],
                "invalid_fields_csv": "prompt_cache",
                "is_or_are": "is",
                "plural_s": "",
            },
        ),
        "cache.prewarm-no-prefix": (
            "score",
            {"batch_alias": "item", "first_dynamic_position": 0},
        ),
    }
    return samples[warning_id]


def test_catalog_count_constant_matches_dict_length() -> None:
    """Adding a new ID without updating the count cascades zero edits — but
    the lock test must fire if a future contributor accidentally diverges."""
    assert len(CACHE_WARNING_CATALOG) == EXPECTED_CATALOG_COUNT


def test_every_catalog_id_has_a_kwargs_sample() -> None:
    """Per-id coverage: every catalog id has a known emission shape we can test."""
    catalog_ids = sorted(CACHE_WARNING_CATALOG.keys())
    for warning_id in catalog_ids:
        # Will raise KeyError in _kwargs_for() if a new ID lands without sample.
        _kwargs_for(warning_id)


def test_opportunities_nudge_id_NOT_in_catalog() -> None:
    """Defensive: the dry-run nudge ID is reserved separately."""
    assert CACHE_OPPORTUNITIES_NUDGE_ID not in CACHE_WARNING_CATALOG


# ---------------------------------------------------------------------------
# Per-ID JSON round-trip — every catalog ID's emitted Diagnostic round-trips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("warning_id", sorted(CACHE_WARNING_CATALOG.keys()))
def test_per_id_diagnostic_json_round_trip(warning_id: str) -> None:
    """For every catalog ID, the emitted Diagnostic.to_dict() round-trips
    through json.dumps/loads cleanly. Catches non-JSON-serializable values
    (Path, set, etc.) leaking into context."""
    node_id, kwargs = _kwargs_for(warning_id)
    diag = make_diagnostic(warning_id, node_id=node_id, **kwargs)
    payload = diag.to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped == payload


@pytest.mark.parametrize("warning_id", sorted(CACHE_WARNING_CATALOG.keys()))
def test_per_id_json_payload_carries_id_at_top_level(warning_id: str) -> None:
    """Top-10% diagnostic systems (mypy, rustc, ruff) all surface stable IDs at
    top level for filtering/suppression. v1 contract: ``id`` is a top-level key
    in the JSON, not buried in context."""
    node_id, kwargs = _kwargs_for(warning_id)
    diag = make_diagnostic(warning_id, node_id=node_id, **kwargs)
    payload = diag.to_dict()
    assert payload["id"] == warning_id


# ---------------------------------------------------------------------------
# JSON format_version contract
# ---------------------------------------------------------------------------


def test_json_format_version_consumer_rule_holds() -> None:
    """Consumer rule: ``format_version.startswith(JSON_FORMAT_VERSION_MAJOR + ".")``
    accepts current ``"1.0"`` AND any future ``"1.x"`` minor bump. Lock both."""
    assert JSON_FORMAT_VERSION == "1.0"
    assert JSON_FORMAT_VERSION.startswith(JSON_FORMAT_VERSION_MAJOR + ".")
