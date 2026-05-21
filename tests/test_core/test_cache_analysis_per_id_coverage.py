"""F2.4 — per-warning-ID coverage + golden-shape assertions.

Catches the case where a catalog ID exists but no production code path actually
emits it (dead-code regression). Iterates the catalog at test time so adding
a new ID without a corresponding emission path fails CI.

The full byte-exact text/JSON goldens are deferred to v1.x in favor of these
structural checks: ``EXPECTED_CATALOG_COUNT`` ensures count drift can't hide,
and the per-id round-trip locks the agent-facing JSON contract for every ID.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from pflow.core.prompt_cache_analysis.warning_catalog import (
    CACHE_OPPORTUNITIES_NUDGE_ID,
    CACHE_WARNING_CATALOG,
    EXPECTED_CATALOG_COUNT,
    make_diagnostic,
)

# Minimal context kwargs per ID — copy of test_cache_analysis_warnings.py's
# helper, kept here so this coverage test is self-contained.
_DISCREPANCY_BASE = {
    "workflow_path_short": "workflow",
    "root_cause_summary": "Upstream value changed between predicted run and actual run",
    "suggestion": "Upstream value changed between predicted run and actual run; re-run analyze-cache to refresh the prediction.",
    "predicted_cache_key": None,
    "actual_cache_key": None,
    "affected_workflow": "workflow.pflow.md",
}


_STAGE_ATTR_MODULES: dict[str, tuple[str, ...]] = {
    "estimate_tokens": (
        "pflow.core.prompt_cache_analysis.stages.row_builder",
        "pflow.core.prompt_cache_analysis.stages.suggestions",
        "pflow.core.prompt_cache_analysis.stages.cross_workflow",
    ),
    "get_min_cache_tokens": (
        "pflow.core.prompt_cache_analysis.below_min_tokens_detector",
        "pflow.core.prompt_cache_analysis.analyze",
        "pflow.core.prompt_cache_analysis.stages.row_builder",
        "pflow.core.prompt_cache_analysis.stages.warnings",
        "pflow.core.prompt_cache_analysis.stages.suggestions",
        "pflow.core.prompt_cache_analysis.stages.fragmentation",
        "pflow.core.prompt_cache_analysis.stages.partial_declarations",
        "pflow.core.prompt_cache_analysis.stages.cross_workflow",
    ),
    "_input_rate": (
        "pflow.core.prompt_cache_analysis.stages.suggestions",
        "pflow.core.prompt_cache_analysis.stages.fragmentation",
    ),
    "_estimate_ref_tokens": (
        "pflow.core.prompt_cache_analysis.stages.row_builder",
        "pflow.core.prompt_cache_analysis.stages.suggestions",
        "pflow.core.prompt_cache_analysis.stages.partial_declarations",
    ),
}


def _patch_stage_attr(monkeypatch: pytest.MonkeyPatch, name: str, value: Any) -> None:
    for module_name in _STAGE_ATTR_MODULES[name]:
        monkeypatch.setattr(importlib.import_module(module_name), name, value, raising=False)


def _kwargs_for(warning_id: str) -> tuple[str | None, dict]:
    """Return ``(node_id, context_kwargs)`` for constructing a Diagnostic."""
    samples: dict[str, tuple[str | None, dict]] = {
        "cache.order-mismatch": (
            "X",
            {
                "declared": ["a", "b"],
                "actual": ["b", "a"],
                "declared_str": "[a, b]",
                "actual_str": "[b, a]",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.unused-chunk": (None, {"chunk_name": "topic", "source_line": 12}),
        "cache.shared-context-undeclared": (
            None,
            {"node_count": 3, "shared_chunks": ["concept"], "affected_workflow": "x.pflow.md", "savings_usd": 0.78},
        ),
        "cache.shared-context-undeclared-conditional": (
            None,
            {
                "node_count": 2,
                "shared_chunks": ["concept"],
                "affected_workflow": "x.pflow.md",
                "min_tokens": 2048,
                "affected_nodes": ["draft", "review"],
            },
        ),
        "cache.sub-workflow-cache-undeclared": (
            None,
            {
                "affected_workflow": "child.pflow.md",
                "child_workflow": "child.pflow.md",
                "child_workflow_basename": "child.pflow.md",
                "affected_input_count": 1,
                "inputs": [
                    {
                        "child_input_name": "concept",
                        "parent_value_expr": "concept",
                        "parent_workflow": "parent.pflow.md",
                        "parent_node_id": "call-child",
                        "line_in_parent": 42,
                        "tokens_estimated": 2048,
                        "consumer_node_ids": ["child-llm-a", "child-llm-b"],
                        "consumer_node_ids_csv": "`child-llm-a`, `child-llm-b`",
                    }
                ],
                "body_block": "Template variables to remove:\n  • `concept` ~2,048 tokens — uses `${concept}`",
                "case": "actionable",
                "savings_usd": None,
            },
        ),
        "cache.prompt-cache-incomplete": (
            None,
            {
                "affected_workflow": "x.pflow.md",
                "workflow_basename": "x.pflow.md",
                "affected_node_count": 2,
                "node_findings_block": (
                    "Affected nodes:\n"
                    "- `draft` (model: anthropic/claude-sonnet-4-5):\n"
                    "    1. Remove from prompt body: ${concept}\n"
                    "    2. Set prompt_cache: [concept]"
                ),
                "node_findings": [
                    {
                        "node_id": "draft",
                        "missing_chunks": ["concept"],
                        "missing_chunks_csv": "`concept`",
                        "corrected_prompt_cache": ["concept"],
                        "corrected_prompt_cache_inline": "[concept]",
                        "prompt_body_cleanup": ["concept"],
                        "prompt_body_cleanup_csv": "${concept}",
                        "rep_model": "anthropic/claude-sonnet-4-5",
                        "missing_chunks_tokens": 1500,
                    }
                ],
                "below_threshold_clause": "",
                "savings_usd": None,
            },
        ),
        "cache.batch-prewarm-recommended": (
            "score",
            {
                "batch_size": 34,
                "prefix_tokens_estimated": 2100,
                "savings_pct": 89,
                "savings_usd": 0.12,
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.batch-prewarm-lower-bound-recommended": (
            "score",
            {
                "measurable_tokens": 1200,
                "batch_alias": "item",
                "unresolved_refs": ("a", "b"),
                "savings_lower_bound_usd": 0.02,
                "batch_size": 12,
                "affected_workflow": "x.pflow.md",
            },
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
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.padding-advisory": (
            "review",
            {
                "current_subset": ["a"],
                "suggested_subset": ["a", "b"],
                "savings_usd": 0.04,
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.below-min-predicted": (
            "rewrite",
            {
                "model": "claude-sonnet-4-5",
                "cacheable_tokens": 512,
                "min_tokens": 1024,
                "provider_note": "",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.below-min-observed": (
            "rewrite",
            {
                "model": "claude-sonnet-4-5",
                "cacheable_tokens": 0,
                "min_tokens": 1024,
                "provider_note": "",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.below-min-rendered": (
            "rewrite",
            {
                "model": "claude-sonnet-4-5",
                "cacheable_tokens": 512,
                "min_tokens": 1024,
                "provider_note": "",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.prewarm-disabled-below-min": (
            "rewrite",
            {
                "model": "claude-sonnet-4-5",
                "cacheable_tokens": 512,
                "min_tokens": 1024,
                "provider_note": "",
                "alias": "item",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.conditional-warmup-recommended": (
            "rewrite",
            {
                "model": "claude-sonnet-4-5",
                "below_min_count": 2,
                "total_count": 4,
                "min_tokens": 1024,
                "affected_workflow": "x.pflow.md",
            },
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
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.unsupported-provider-ttl": (
            "X",
            {
                "provider": "anthropic",
                "model": "anthropic/claude-sonnet-4-5",
                "ttl": "11m",
                "ttl_seconds": 660,
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.prewarm-no-prefix": (
            "score",
            {"batch_alias": "item", "first_dynamic_position": 0, "affected_workflow": "x.pflow.md"},
        ),
        "cache.batch-prewarm-below-min": (
            "score",
            {
                "model": "anthropic/claude-sonnet-4-5",
                "prefix_tokens": 27,
                "min_tokens": 1024,
                "batch_alias": "item",
                "provider_note": "cache_control markers will silently no-op at the provider",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.consolidate-to-root-recommended": (
            None,
            {
                "root": "concept",
                "sub_paths": ["concept.core_idea", "concept.title", "concept.angle"],
                "model": "anthropic/claude-sonnet-4-5",
                "min_tokens": 1024,
                "max_subpath_tokens": 200,
                "root_tokens": 1500,
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.heterogeneous-models-fragment-cache": (
            None,
            {
                "model_group_count": 2,
                "models_csv": "anthropic/claude-haiku-4-5, anthropic/claude-sonnet-4-5",
                "model_groups": [
                    {
                        "model": "anthropic/claude-haiku-4-5",
                        "node_paths": ["draft"],
                        "node_count": 1,
                        "cache_creation_cost_usd": 0.001,
                    },
                    {
                        "model": "anthropic/claude-sonnet-4-5",
                        "node_paths": ["review"],
                        "node_count": 1,
                        "cache_creation_cost_usd": 0.002,
                    },
                ],
                "model_groups_lines": (
                    "  - anthropic/claude-haiku-4-5 (1 node): draft\n  - anthropic/claude-sonnet-4-5 (1 node): review"
                ),
                "shared_chunks": ["context"],
                "affected_workflow": "x.pflow.md",
                "savings_usd": 0.001,
            },
        ),
        "cache.system-prompts-fragment-cache": (
            None,
            {
                "system_group_count": 2,
                "system_groups": [
                    {"system_preview": "X", "node_ids": ["a"], "redundant_write_usd": 0.001},
                    {"system_preview": "Y", "node_ids": ["b"], "redundant_write_usd": 0.002},
                ],
                "system_groups_lines": "  - `X` -> 1 node(s): a\n  - `Y` -> 1 node(s): b",
                "shared_chunks": ["context"],
                "affected_workflow": "x.pflow.md",
                "savings_usd": 0.001,
                "node_ids_csv": "a, b",
            },
        ),
        "cache.first-call-write-penalty": (
            "draft",
            {
                "model": "anthropic/claude-haiku-4-5",
                "affected_workflow": "x.pflow.md",
                "savings_usd": 0.0002,
            },
        ),
        "cache.opaque-prompt": (
            "process-items",
            {
                "var_ref": "item.prompt",
                "upstream_node_id": "prepare-items",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.prompt-body-duplicates-cache": (
            "write-lyrics",
            {
                "overlapping_pairs": [{"chunk_name": "concept", "body_ref": "concept"}],
                "overlap_lines": "  - cached `${concept}` AND inline `${concept}`",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.prompt-body-shadows-cache": (
            "write-lyrics",
            {
                "shadowing_pairs": [
                    {"chunk_name": "concept", "body_ref": "concept.title", "direction": "cache_contains_body"}
                ],
                "overlap_lines": "  - cached `${concept}` overlaps inline `${concept.title}` (cache_contains_body)",
                "affected_workflow": "x.pflow.md",
            },
        ),
        "llm.thinking-temperature-mismatch": (
            "score-choruses",
            {
                "model": "anthropic/claude-haiku-4-5",
                "reasoning_effort": "low",
                "temperature": 0.3,
                "affected_workflow": "x.pflow.md",
            },
        ),
        "cache.routed-provider-degraded": (
            "write-lyrics",
            {
                "model": "openrouter/anthropic/claude-sonnet-4-5",
                "n_rendered_chunks": 3,
                "affected_workflow": "x.pflow.md",
            },
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
# Per-ID JSON round-trip — structural floor over a small representative sample.
# Full per-ID coverage is delegated to the production-driven test below
# (``test_emitted_diagnostics_round_trip_for_real_producer_paths``), which
# iterates the diagnostics actual code paths emit rather than constructing
# them locally. The two surfaces are complementary: this one catches
# ``make_diagnostic``-side regressions for the structural variants; the
# production-driven one catches divergence between the catalog template and
# how producers populate context.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "warning_id",
    [
        # Simple flat context (list-of-strings).
        "cache.order-mismatch",
        # Discrepancy diagnostic with nullable cache-key context.
        "cache.discrepancy",
        # V6 combined-diagnostic shape (invalid_fields: list[str]).
        "cache.invalid-on-non-llm",
    ],
)
def test_per_id_diagnostic_json_round_trip(warning_id: str) -> None:
    """For 3 structurally-representative catalog IDs (flat / nested-dispatch /
    multi-field-collapse), the emitted Diagnostic.to_dict() round-trips
    through json.dumps/loads cleanly and carries ``id`` at top level. Catches
    non-JSON-serializable values (Path, set, etc.) leaking into context, and
    the regression where ``id`` gets nested inside ``context`` instead of
    surfacing at the top of the payload (top-10% diagnostic systems —
    mypy/rustc/ruff — surface stable IDs at top level for filtering)."""
    node_id, kwargs = _kwargs_for(warning_id)
    diag = make_diagnostic(warning_id, node_id=node_id, **kwargs)
    payload = diag.to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped == payload
    assert payload["id"] == warning_id


def test_analyze_rehydrates_catalog_warnings_from_trace(tmp_path: Any) -> None:
    """Runtime-only cache warnings recorded in trace JSON remain visible to
    ``analyze-cache --from-trace``.

    The rendered/prewarm-disabled below-min IDs are emitted by runtime code, not
    the static analyzer. Trace replay is therefore the production boundary that
    keeps those IDs observable after the run that produced them.
    """
    from pflow.core.prompt_cache_analysis import analyze
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    workflow_path = str(tmp_path / "trace-replay.pflow.md")
    trace_path = tmp_path / "trace-replay.json"
    workflow_ir: dict[str, Any] = {
        "nodes": [
            {
                "id": "ask",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "hello"},
            }
        ],
        "edges": [],
    }
    rendered = make_diagnostic(
        "cache.below-min-rendered",
        node_id="ask",
        affected_workflow=workflow_path,
        model="anthropic/claude-sonnet-4-5",
        cacheable_tokens=5,
        min_tokens=1024,
        provider_note="cache_control markers will silently no-op at the provider",
    )
    prewarm_disabled = make_diagnostic(
        "cache.prewarm-disabled-below-min",
        node_id="ask",
        affected_workflow=workflow_path,
        model="anthropic/claude-sonnet-4-5",
        cacheable_tokens=5,
        min_tokens=1024,
        provider_note="cache_control markers will silently no-op at the provider",
        alias="item",
    )

    builder = TraceFixtureBuilder()
    trace = builder.trace(workflow_path, [builder.llm_event("ask")])
    trace["format_version"] = "2.3.0"
    trace["warnings"] = [rendered.to_display_dict(), prewarm_disabled.to_display_dict()]
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    analysis = analyze(workflow_ir, workflow_path=workflow_path, trace_path=trace_path)
    warnings_by_id = {warning.id: warning for warning in analysis.warnings}

    assert warnings_by_id["cache.below-min-rendered"].context["cacheable_tokens"] == 5
    assert warnings_by_id["cache.prewarm-disabled-below-min"].context["alias"] == "item"


# ---------------------------------------------------------------------------
# Production-driven round-trip: drives REAL producers (validator, analyzer,
# summarizer) against minimal IR fixtures that fire each catalog id, then
# round-trips the emitted Diagnostic through ``Diagnostic.to_dict() →
# json.dumps → json.loads`` and asserts top-level ``id`` plus content
# fidelity. Catches the regression class where the catalog template and the
# producer's context-population diverge — something the local-construction
# round-trip above can't see (it builds the same kwargs the catalog
# template renders against).
# ---------------------------------------------------------------------------
#
# v1 stubbed warnings — catalog rows exist but no producer fires them yet.
# Documented here for transparency; the production-driven test skips these
# by design (the structural round-trip above provides coverage on the
# ``make_diagnostic``-side until detection wires up in v1.x).
#
# TODO(task-159 recommendations-section-plan): when sub-segments B+C wire
# up producers for the remaining IDs below, this set should empty out and the parallel
# test helpers ``_kwargs_for`` (this file) and ``_minimal_context_kwargs`` +
# ``test_every_id_round_trips_through_make_diagnostic`` (in
# ``tests/test_core/test_cache_analysis_warnings.py``) become dead. Delete
# all four in the same PR that lands sub-segment C; the production-driven test
# ``test_emitted_diagnostics_round_trip_for_real_producer_paths`` will cover
# all 12 IDs once stubs ship. Sub-segment B → ``cache.cross-workflow-*``.
# Sub-segment C → ``cache.discrepancy``.
_STUBBED_PRODUCERS_DEFERRED_TO_V1X = frozenset()


def _round_trip(diag: Any) -> dict:
    """Round-trip a Diagnostic through ``to_dict → json.dumps → json.loads``.
    Asserts ``id`` is at top level and the round-trip is byte-stable."""
    payload = diag.to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped == payload
    assert "id" in payload
    return payload


def test_emitted_diagnostics_round_trip_for_real_producer_paths(tmp_path: Any, monkeypatch: Any) -> None:
    """Drive every NON-STUBBED catalog id through its actual producer and
    round-trip the emitted Diagnostic. Catches the divergence class where
    a producer populates context with a non-JSON-serializable value (Path,
    set, dataclass) — invisible to the structural round-trip above which
    only sees the catalog template's hand-curated kwargs.

    Producers covered:
    - ``validate_data_flow`` → ``cache.order-mismatch``,
      ``cache.unused-chunk``, ``cache.invalid-on-non-llm``,
      ``cache.unsupported-provider-ttl``,
      ``cache.prompt-body-duplicates-cache``,
      ``cache.prompt-body-shadows-cache``
    - ``analyze`` → ``cache.below-min-predicted``, ``cache.prewarm-no-prefix``
    - ``summarize_from_analysis`` → ``cache.opportunities-available``
    """
    from pflow.core.prompt_cache_analysis import analyze, summarize_from_analysis
    from pflow.core.prompt_cache_analysis.cost_estimation import ModelPricing
    from pflow.core.workflow.data_flow import validate_data_flow

    below_min_module = importlib.import_module("pflow.core.prompt_cache_analysis.below_min_tokens_detector")
    token_estimation_module = importlib.import_module("pflow.core.prompt_cache_analysis.token_estimation")
    cost_module = importlib.import_module("pflow.core.prompt_cache_analysis.cost_estimation")
    _patch_stage_attr(
        monkeypatch,
        "estimate_tokens",
        lambda _model, text, **_kwargs: (len((text or "").split()), "heuristic"),
    )
    monkeypatch.setattr(
        token_estimation_module,
        "estimate_tokens",
        lambda _model, text, **_kwargs: (len((text or "").split()), "heuristic"),
    )
    _patch_stage_attr(monkeypatch, "get_min_cache_tokens", lambda _model: 10)
    monkeypatch.setattr(below_min_module, "get_min_cache_tokens", lambda _model: 10)
    _patch_stage_attr(monkeypatch, "_input_rate", lambda _model: 1.0)
    monkeypatch.setattr(
        cost_module,
        "get_model_pricing",
        lambda _model: ModelPricing(input_rate=1.0, output_rate=1.0, cache_creation_rate=1.25, cache_read_rate=0.1),
    )

    seen_ids: set[str] = set()

    # --- validator-emitted ids (data_flow.py) -----------------------------
    # cache.order-mismatch: declare ## Cache items in one order, then a
    # node's prompt_cache lists them in a different order.
    order_mismatch_ir: dict[str, Any] = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                "prompt_cache": ["b", "a"],  # wrong order
                "params": {"prompt": "go"},
            }
        ],
        "edges": [],
    }
    diags = validate_data_flow(order_mismatch_ir, check_inputs=False)
    found = [d for d in diags if d.id == "cache.order-mismatch"]
    assert found, f"validate_data_flow did not emit cache.order-mismatch: ids={[d.id for d in diags]}"
    _round_trip(found[0])
    seen_ids.add("cache.order-mismatch")

    # cache.unused-chunk: a chunk in ## Cache that no node references.
    unused_chunk_ir: dict[str, Any] = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                "prompt_cache": ["a"],  # b is declared but unreferenced
                "params": {"prompt": "go"},
            }
        ],
        "edges": [],
    }
    diags = validate_data_flow(unused_chunk_ir, check_inputs=False)
    found = [d for d in diags if d.id == "cache.unused-chunk"]
    assert found, f"validate_data_flow did not emit cache.unused-chunk: ids={[d.id for d in diags]}"
    _round_trip(found[0])
    seen_ids.add("cache.unused-chunk")

    # cache.invalid-on-non-llm: prompt_cache: declared on a non-LLM node.
    invalid_on_non_llm_ir: dict[str, Any] = {
        "inputs": {"a": {"type": "string"}},
        "cache": {
            "items": [{"name": "a", "var": "a", "prose_before": "A:\n"}],
        },
        "nodes": [
            {
                "id": "echo",
                "type": "shell",
                "prompt_cache": ["a"],  # invalid on shell node
                "params": {"command": "echo hi"},
            }
        ],
        "edges": [],
    }
    diags = validate_data_flow(invalid_on_non_llm_ir, check_inputs=False)
    found = [d for d in diags if d.id == "cache.invalid-on-non-llm"]
    assert found, f"validate_data_flow did not emit cache.invalid-on-non-llm: ids={[d.id for d in diags]}"
    payload = _round_trip(found[0])
    # V6 combined-diagnostic shape: invalid_fields list survives JSON.
    assert payload["context"]["invalid_fields"] == ["prompt_cache"]
    seen_ids.add("cache.invalid-on-non-llm")

    # cache.unsupported-provider-ttl: minute-level TTL on a cached non-Gemini node.
    unsupported_provider_ttl_ir: dict[str, Any] = {
        "inputs": {"a": {"type": "string"}},
        "cache": {
            "ttl": "11m",
            "items": [{"name": "a", "var": "a", "prose_before": "A:\n"}],
        },
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                "prompt_cache": ["a"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "go"},
            }
        ],
        "edges": [],
    }
    diags = validate_data_flow(unsupported_provider_ttl_ir, check_inputs=False)
    found = [d for d in diags if d.id == "cache.unsupported-provider-ttl"]
    assert found, f"validate_data_flow did not emit cache.unsupported-provider-ttl: ids={[d.id for d in diags]}"
    payload = _round_trip(found[0])
    assert payload["context"]["ttl_seconds"] == 660
    seen_ids.add("cache.unsupported-provider-ttl")

    # --- analyzer-emitted ids (analyze.py) -------------------------------
    # cache.below-min-predicted: a node opts into a small declared cache —
    # the rendered content falls below the provider minimum (Anthropic = 1024).
    below_min_tokens_ir: dict[str, Any] = {
        "inputs": {"topic": {"type": "string"}},
        "cache": {
            "items": [{"name": "topic", "var": "topic", "prose_before": "Topic:\n"}],
        },
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["topic"],
                "params": {"prompt": "summarize ${topic}"},
            }
        ],
        "edges": [],
    }
    analysis = analyze(below_min_tokens_ir, parameters={"topic": "hi"})
    found = [d for d in analysis.warnings if d.id == "cache.below-min-predicted"]
    assert found, f"analyze did not emit cache.below-min-predicted: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.below-min-predicted")

    # cache.prewarm-no-prefix: batch llm node with prewarm: true and
    # ${item.X} at position 0 of the prompt template.
    prewarm_no_prefix_ir: dict[str, Any] = {
        "inputs": {"items": {"type": "list"}},
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prewarm": True,
                "batch": {"items": "${items}", "as": "item"},
                "params": {"prompt": "${item.text}"},  # batch ref at position 0
            }
        ],
        "edges": [],
    }
    analysis = analyze(prewarm_no_prefix_ir)
    found = [d for d in analysis.warnings if d.id == "cache.prewarm-no-prefix"]
    assert found, f"analyze did not emit cache.prewarm-no-prefix: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.prewarm-no-prefix")

    # cache.batch-prewarm-below-min: prewarm: true with a short static prefix
    # before ${item.X}. The detector reads the real ``get_min_cache_tokens``
    # from ``llm_capabilities`` (not the analyzer-patched stub at 10), so a
    # ~5-token prefix on Sonnet-4-5 is honestly below the 1024 minimum.
    batch_prewarm_below_min_ir: dict[str, Any] = {
        "inputs": {"items": {"type": "list"}},
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "prewarm": True,
                "batch": {"items": "${items}", "as": "item"},
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Score this: ${item.text}"},
            }
        ],
        "edges": [],
    }
    analysis = analyze(batch_prewarm_below_min_ir)
    found = [d for d in analysis.warnings if d.id == "cache.batch-prewarm-below-min"]
    assert found, f"analyze did not emit cache.batch-prewarm-below-min: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.batch-prewarm-below-min")

    # cache.prewarm-disabled-below-min: runtime pre-flight disables prewarm
    # when the static prefix is below the provider minimum.
    from pflow.registry.registry import Registry
    from pflow.runtime.compilation.compiler import compile_workflow
    from pflow.runtime.engine.engine import build_prompt_cache_dict

    compiled = compile_workflow(batch_prewarm_below_min_ir, Registry(), initial_params={"items": [{"text": "a"}]})
    shared_for_prewarm = {"items": [{"text": "a"}], "_pflow_workflow_file": "x.pflow.md"}
    render_dict = build_prompt_cache_dict(compiled, shared_for_prewarm)
    assert render_dict["score"].prewarm is False
    found = [
        d
        for d in (shared_for_prewarm.get("__warnings__", {}) or {}).values()
        if getattr(d, "id", None) == "cache.prewarm-disabled-below-min"
    ]
    assert found, "build_prompt_cache_dict did not emit cache.prewarm-disabled-below-min"
    _round_trip(found[0])
    seen_ids.add("cache.prewarm-disabled-below-min")

    # cache.below-min-observed / rendered: runtime LLM helpers emit these
    # producer-path diagnostics outside analyze().
    from types import MappingProxyType

    from pflow.core.prompt_cache import CacheRenderContext
    from pflow.nodes.llm.llm import (
        _emit_declared_rendered_below_min_warning,
        _emit_observed_below_min_cache_warning,
    )

    runtime_shared: dict[str, Any] = {
        "__pflow_prompt_cache__": MappingProxyType({
            "ask": CacheRenderContext(
                cache_block=None,
                subset=("topic",),
                prewarm=False,
                unresolved_batch_prompt=None,
                batch_alias=None,
            )
        }),
        "_pflow_workflow_file": "x.pflow.md",
    }
    _emit_observed_below_min_cache_warning(
        shared=runtime_shared,
        node_id="ask",
        model="anthropic/claude-sonnet-4-5",
        llm_usage={
            "has_cache_telemetry": True,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    )
    observed = runtime_shared["__warnings__"]["ask"]
    assert observed.id == "cache.below-min-observed"
    _round_trip(observed)
    seen_ids.add("cache.below-min-observed")

    _emit_declared_rendered_below_min_warning(
        shared=runtime_shared,
        node_id="ask",
        model="anthropic/claude-sonnet-4-5",
        measured_tokens=5,
        min_tokens=10,
    )
    rendered = runtime_shared["__warnings__"]["ask"]
    assert rendered.id == "cache.below-min-rendered"
    _round_trip(rendered)
    seen_ids.add("cache.below-min-rendered")

    # cache.routed-provider-degraded: runtime advisory emitted by
    # _build_system_blocks when the model looks like Anthropic routed
    # through a proxy AND multi-chunk caching would have applied.
    from pflow.nodes.llm.llm import _emit_routed_provider_degraded_advisory

    routed_shared: dict[str, Any] = {"_pflow_workflow_file": "x.pflow.md"}
    _emit_routed_provider_degraded_advisory(
        shared=routed_shared,
        node_id="ask",
        model="openrouter/anthropic/claude-sonnet-4-5",
        n_rendered_chunks=3,
    )
    routed_advisory = routed_shared["__warnings__"]["ask"]
    assert routed_advisory.id == "cache.routed-provider-degraded"
    _round_trip(routed_advisory)
    seen_ids.add("cache.routed-provider-degraded")

    # cache.conditional-warmup-recommended: complete trace shows a mixed
    # cohort, with some provider calls stripped below-min and some not.
    conditional_ir: dict[str, Any] = {
        "inputs": {"items": {"type": "list"}},
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prewarm": True,
                "batch": {"items": "${items}", "as": "item"},
                "params": {"prompt": ("stable " * 2000) + "${item.text}"},
            }
        ],
        "edges": [],
    }
    conditional_path = str(tmp_path / "conditional.pflow.md")
    conditional_trace_path = tmp_path / "conditional-trace.json"
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    conditional_trace_path.write_text(
        json.dumps(
            builder.trace(
                workflow_path=conditional_path,
                nodes=[
                    builder.batch_event(
                        "score",
                        [
                            {
                                "index": index,
                                "success": True,
                                "llm_call": {
                                    "model": "anthropic/claude-sonnet-4-5",
                                    "input_tokens": 200,
                                    "output_tokens": 5,
                                    "total_tokens": 205,
                                    "cost_usd": 0.01,
                                    **({"prewarm_disabled_reason": "below_min"} if index in {0, 1} else {}),
                                },
                            }
                            for index in range(4)
                        ],
                    )
                ],
            )
        ),
        encoding="utf-8",
    )
    analysis = analyze(conditional_ir, workflow_path=conditional_path, trace_path=conditional_trace_path)
    found = [d for d in analysis.warnings if d.id == "cache.conditional-warmup-recommended"]
    assert found, f"analyze did not emit cache.conditional-warmup-recommended: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.conditional-warmup-recommended")

    # cache.batch-prewarm-recommended: batch with large static prefix, no
    # explicit prewarm decision.
    batch_recommended_ir: dict[str, Any] = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "priced/model",
                "batch": {"items": [{"text": str(i)} for i in range(34)], "as": "item"},
                "params": {"prompt": ("stable " * 5_000) + "${item.text}"},
            }
        ],
        "edges": [],
    }
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    batch_recommended_path = str(tmp_path / "batch-recommended.pflow.md")
    batch_recommended_trace_path = tmp_path / "batch-recommended-trace.json"
    builder = TraceFixtureBuilder()
    batch_recommended_trace_path.write_text(
        json.dumps(
            builder.trace(
                workflow_path=batch_recommended_path,
                nodes=[
                    builder.batch_event(
                        "score",
                        [
                            {
                                "index": index,
                                "success": True,
                                "llm_call": {
                                    "model": "priced/model",
                                    "input_tokens": 10_000,
                                    "output_tokens": 5,
                                    "total_tokens": 10_005,
                                    "cost_usd": 0.01,
                                },
                            }
                            for index in range(34)
                        ],
                    )
                ],
            )
        ),
        encoding="utf-8",
    )
    analysis = analyze(
        batch_recommended_ir, workflow_path=batch_recommended_path, trace_path=batch_recommended_trace_path
    )
    found = [d for d in analysis.warnings if d.id == "cache.batch-prewarm-recommended"]
    assert found, f"analyze did not emit cache.batch-prewarm-recommended: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.batch-prewarm-recommended")

    # cache.batch-prewarm-lower-bound-recommended: measurable stable bytes in
    # the prefix clear the analyzer-patched provider minimum, but an unresolved
    # upstream ref prevents confident exact measurement.
    lower_bound_ir: dict[str, Any] = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "priced/model",
                "batch": {"items": [{"text": "a"}, {"text": "b"}], "as": "item"},
                "params": {"prompt": ("stable " * 5_000) + "${missing.upstream}\n${item.text}"},
            }
        ],
        "edges": [],
    }
    analysis = analyze(lower_bound_ir, workflow_path=str(tmp_path / "lower-bound.pflow.md"), auto_load_trace=False)
    found = [d for d in analysis.warnings if d.id == "cache.batch-prewarm-lower-bound-recommended"]
    assert found, (
        f"analyze did not emit cache.batch-prewarm-lower-bound-recommended: ids={[d.id for d in analysis.warnings]}"
    )
    _round_trip(found[0])
    seen_ids.add("cache.batch-prewarm-lower-bound-recommended")

    # cache.consolidate-to-root-recommended: brownfield path. Workflow declares
    # ``## Cache`` with two SUB-PATH chunks (``concept.title``, ``concept.core_idea``)
    # of the same root. Each sub-path is below the (mocked) min-cache threshold;
    # the consolidated ``${concept}`` would cross. Override ``_estimate_ref_tokens``
    # locally so the threshold check fires deterministically without needing
    # real memo data (production-shape estimator math is covered by dedicated
    # unit tests; this test only locks the emission contract).
    _patch_stage_attr(
        monkeypatch,
        "_estimate_ref_tokens",
        lambda ref, **_kw: 100 if ref == "concept" else 5,
    )
    consolidate_ir: dict[str, Any] = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {
            "items": [
                {"name": "concept.title", "var": "concept.title", "prose_before": "T:\n"},
                {"name": "concept.core_idea", "var": "concept.core_idea", "prose_before": "C:\n"},
            ]
        },
        "nodes": [
            {
                "id": "consumer-1",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["concept.title", "concept.core_idea"],
                "params": {"prompt": "${concept.title} ${concept.core_idea}"},
            },
            {
                "id": "consumer-2",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["concept.title", "concept.core_idea"],
                "params": {"prompt": "${concept.title} ${concept.core_idea}"},
            },
        ],
        "edges": [],
    }
    analysis = analyze(consolidate_ir)
    found = [d for d in analysis.warnings if d.id == "cache.consolidate-to-root-recommended"]
    assert found, f"analyze did not emit cache.consolidate-to-root-recommended: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.consolidate-to-root-recommended")

    # cache.heterogeneous-models-fragment-cache: two exact models declare the
    # same chunk, so each provider/model namespace pays a separate cache write.
    # Override ``_estimate_ref_tokens`` locally so the precise per-chunk math
    # (introduced after the initial implementation) runs deterministically
    # without needing memo data to be populated. Production-shape estimator
    # math is covered by dedicated unit tests; this test only locks the
    # emission contract.
    _patch_stage_attr(monkeypatch, "_estimate_ref_tokens", lambda _ref, **_kw: 100)
    fragment_ir: dict[str, Any] = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft from cached context."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review from cached context."},
            },
        ],
        "edges": [],
    }
    analysis = analyze(fragment_ir, parameters={"context": "stable " * 20})
    found = [d for d in analysis.warnings if d.id == "cache.heterogeneous-models-fragment-cache"]
    assert found, (
        f"analyze did not emit cache.heterogeneous-models-fragment-cache: ids={[d.id for d in analysis.warnings]}"
    )
    payload = _round_trip(found[0])
    assert payload["context"]["model_groups"][0]["node_paths"]
    seen_ids.add("cache.heterogeneous-models-fragment-cache")

    # cache.system-prompts-fragment-cache: two nodes share model and chunks but
    # use distinct system prompts, so provider cache prefixes diverge.
    system_fragment_ir: dict[str, Any] = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are a lyricist.", "prompt": "Draft from cached context."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are an emotional reviewer.", "prompt": "Review cached context."},
            },
        ],
        "edges": [],
    }
    analysis = analyze(system_fragment_ir, parameters={"context": "stable " * 20})
    found = [d for d in analysis.warnings if d.id == "cache.system-prompts-fragment-cache"]
    assert found, f"analyze did not emit cache.system-prompts-fragment-cache: ids={[d.id for d in analysis.warnings]}"
    payload = _round_trip(found[0])
    assert payload["context"]["system_group_count"] == 2
    seen_ids.add("cache.system-prompts-fragment-cache")

    # cache.first-call-write-penalty: only one node uses this exact model with
    # prompt_cache declared, so its cache write has no same-model read.
    write_penalty_ir: dict[str, Any] = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft from cached context."},
            }
        ],
        "edges": [],
    }
    analysis = analyze(write_penalty_ir, parameters={"context": "stable " * 20})
    found = [d for d in analysis.warnings if d.id == "cache.first-call-write-penalty"]
    assert found, f"analyze did not emit cache.first-call-write-penalty: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.first-call-write-penalty")

    # cache.dynamic-before-static: full-path declared cache chunk appears after
    # an undeclared dynamic ref.
    dynamic_ir: dict[str, Any] = {
        "cache": {
            "items": [
                {
                    "name": "creative-direction.response",
                    "var": "creative-direction.response",
                    "prose_before": "Direction:\n",
                }
            ]
        },
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "priced/model",
                "prompt_cache": ["creative-direction.response"],
                "params": {"prompt": "Dynamic ${user_input}\n${creative-direction.response}\n" + ("rubric " * 50)},
            }
        ],
        "edges": [],
    }
    from pflow.runtime.cache import MemoizationCache

    dynamic_cache = MemoizationCache(db_path=tmp_path / "dynamic-cache.db")
    dynamic_workflow_path = str(tmp_path / "dynamic.pflow.md")
    dynamic_cache.put(
        cache_key="creative-direction-key",
        node_id="creative-direction",
        workflow_path=dynamic_workflow_path,
        action="default",
        output={"response": "resolved direction " * 5000},
    )
    analysis = analyze(dynamic_ir, workflow_path=dynamic_workflow_path, memo_cache=dynamic_cache)
    found = [d for d in analysis.warnings if d.id == "cache.dynamic-before-static"]
    assert found, f"analyze did not emit cache.dynamic-before-static: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.dynamic-before-static")

    # cache.padding-advisory: dotted-path subset starts after position 1.
    padding_ir: dict[str, Any] = {
        "cache": {
            "items": [
                {"name": "concept", "var": "concept", "prose_before": "concept " * 20},
                {"name": "concept-brief.response", "var": "concept-brief.response", "prose_before": "brief " * 20},
                {"name": "scorer.response", "var": "scorer.response", "prose_before": "score " * 20},
            ]
        },
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "priced/model",
                "prompt_cache": ["scorer.response"],
                "params": {"prompt": "review ${scorer.response}"},
            },
            {
                "id": "rewrite",
                "type": "llm",
                "model": "priced/model",
                "prompt_cache": ["concept-brief.response", "scorer.response"],
                "params": {"prompt": "rewrite ${concept-brief.response}"},
            },
        ],
        "edges": [],
    }
    analysis = analyze(padding_ir)
    found = [d for d in analysis.warnings if d.id == "cache.padding-advisory"]
    assert found, f"analyze did not emit cache.padding-advisory: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.padding-advisory")

    # cache.shared-context-undeclared: two LLM nodes share a dotted-path ref
    # and the workflow has no ## Cache block.
    shared_ir: dict[str, Any] = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "priced/model",
                "params": {"prompt": "Use ${concept-brief.response}."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "priced/model",
                "params": {"prompt": "Review ${concept-brief.response}."},
            },
        ],
        "edges": [],
    }
    analysis = analyze(shared_ir)
    found = [d for d in analysis.warnings if d.id == "cache.shared-context-undeclared"]
    assert found, f"analyze did not emit cache.shared-context-undeclared: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.shared-context-undeclared")

    # cache.shared-context-undeclared-conditional: same structural opportunity,
    # but current resolved values are below the provider minimum. No suggested
    # paste block is emitted; the advisory tells agents to retry with
    # representative runtime values before editing.
    _patch_stage_attr(monkeypatch, "get_min_cache_tokens", lambda _model: 1000)
    conditional_ir: dict[str, Any] = {
        "inputs": {"article": {"type": "string"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "priced/model",
                "params": {"prompt": "Draft ${article}."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "priced/model",
                "params": {"prompt": "Review ${article}."},
            },
        ],
        "edges": [],
    }
    analysis = analyze(conditional_ir, parameters={"article": "hi"}, workflow_path="conditional.pflow.md")
    found = [d for d in analysis.warnings if d.id == "cache.shared-context-undeclared-conditional"]
    assert found, (
        f"analyze did not emit cache.shared-context-undeclared-conditional: ids={[d.id for d in analysis.warnings]}"
    )
    _round_trip(found[0])
    seen_ids.add("cache.shared-context-undeclared-conditional")
    _patch_stage_attr(monkeypatch, "get_min_cache_tokens", lambda _model: 10)

    # cache.prompt-cache-incomplete: workflow already declares ## Cache, but
    # each LLM node's prompt_cache omits a shared chunk it references.
    partial_declaration_ir: dict[str, Any] = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "prompt_cache": ["a"],
                "params": {"model": "priced/model", "prompt": "Use ${a} and ${b}."},
            },
            {
                "id": "review",
                "type": "llm",
                "prompt_cache": ["a"],
                "params": {"model": "priced/model", "prompt": "Review ${a} and ${b}."},
            },
        ],
    }
    analysis = analyze(partial_declaration_ir, parameters={"a": "a " * 20, "b": "b " * 20})
    found = [d for d in analysis.warnings if d.id == "cache.prompt-cache-incomplete"]
    assert found, f"analyze did not emit cache.prompt-cache-incomplete: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.prompt-cache-incomplete")

    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

    cross_module = importlib.import_module("pflow.core.prompt_cache_analysis.cross_workflow")

    # cache.sub-workflow-cache-undeclared: parent passes a value into a child
    # workflow that has repeated LLM consumers but no child-local ## Cache.
    child_cache_ir = {
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_cache_child_ir = {
        "nodes": [
            {"id": "use", "type": "llm", "params": {"prompt": "Use ${concept}"}},
            {"id": "review", "type": "llm", "params": {"prompt": "Review ${concept}"}},
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_cache_child_ir, Path("/abs/child.pflow.md"), ()),
    )
    analysis = analyze(child_cache_ir, workflow_path="parent.pflow.md")
    found = [d for d in analysis.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert found, f"analyze did not emit cache.sub-workflow-cache-undeclared: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.sub-workflow-cache-undeclared")

    # cache.cross-workflow-rename-detected: parent value tail differs from the
    # child input name. Per the evidence-basis suppression (#362), the warning
    # fires only when at least one side declares ## Cache — the parent here
    # has it so the rename has actionable consequences (prose label alignment).
    rename_child_ir = {"nodes": [{"id": "noop", "type": "shell", "params": {"command": "echo ok"}}]}
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(rename_child_ir, None, ()),
    )
    rename_ir: dict[str, Any] = {
        "cache": {"items": [{"name": "concept_brief", "var": "concept_brief", "prose_before": "Brief:\n"}]},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"creative_brief": "${concept_brief}"}},
            }
        ],
    }
    analysis = analyze(rename_ir, workflow_path="parent.pflow.md")
    found = [d for d in analysis.warnings if d.id == "cache.cross-workflow-rename-detected"]
    assert found, f"analyze did not emit cache.cross-workflow-rename-detected: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.cross-workflow-rename-detected")

    # cache.cross-workflow-prose-mismatch: same dotted-path chunk name in both
    # cache blocks, different prose labels, no rename on the edge.
    prose_child_ir = {
        "cache": {
            "items": [{"name": "creative.direction", "var": "creative.direction", "prose_before": "child prose"}]
        },
        "nodes": [{"id": "noop", "type": "shell", "params": {"command": "echo ok"}}],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(prose_child_ir, None, ()),
    )
    prose_ir: dict[str, Any] = {
        "cache": {
            "items": [{"name": "creative.direction", "var": "creative.direction", "prose_before": "parent prose"}]
        },
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"direction": "${creative.direction}"}},
            }
        ],
    }
    analysis = analyze(prose_ir, workflow_path="parent.pflow.md")
    found = [d for d in analysis.warnings if d.id == "cache.cross-workflow-prose-mismatch"]
    assert found, f"analyze did not emit cache.cross-workflow-prose-mismatch: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.cross-workflow-prose-mismatch")

    # cache.discrepancy: 2.1.0 trace event with skipped cache chunk.
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": "parent.pflow.md",
            "nodes": [
                {
                    "node_id": "gen",
                    "llm_call": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 0,
                        "cache_chunks_skipped": ["concept"],
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    analysis = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    found = [d for d in analysis.warnings if d.id == "cache.discrepancy"]
    assert found, f"analyze did not emit cache.discrepancy: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.discrepancy")

    # cache.opaque-prompt: LLM batch consumes ${item.X}; batch.items sources
    # from a type: code node. Static walkers can't see the assembled prompt.
    opaque_prompt_ir: dict[str, Any] = {
        "nodes": [
            {"id": "prepare-items", "type": "code", "params": {}},
            {
                "id": "process-items",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": "${prepare-items.result}", "as": "item"},
                "params": {"prompt": "${item.prompt}"},
            },
        ],
        "edges": [],
    }
    analysis = analyze(opaque_prompt_ir)
    found = [d for d in analysis.warnings if d.id == "cache.opaque-prompt"]
    assert found, f"analyze did not emit cache.opaque-prompt: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.opaque-prompt")

    # cache.prompt-body-duplicates-cache: a chunk listed in prompt_cache: AND
    # referenced verbatim inside the prompt body. Validator-emitted via the
    # save-time data_flow path.
    duplicates_ir: dict[str, Any] = {
        "inputs": {"concept": {"type": "string"}},
        "cache": {
            "items": [{"name": "concept", "var": "concept", "prose_before": "C:\n"}],
        },
        "nodes": [
            {
                "id": "write-lyrics",
                "type": "llm",
                "prompt_cache": ["concept"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Use the concept ${concept} to write a song.",
                },
            }
        ],
        "edges": [],
    }
    diags = validate_data_flow(duplicates_ir, check_inputs=False, workflow_path="x.pflow.md")
    found = [d for d in diags if d.id == "cache.prompt-body-duplicates-cache"]
    assert found, f"validate_data_flow did not emit cache.prompt-body-duplicates-cache: ids={[d.id for d in diags]}"
    _round_trip(found[0])
    seen_ids.add("cache.prompt-body-duplicates-cache")

    # cache.prompt-body-shadows-cache: cache parent + body sub-path → WARNING.
    shadows_ir: dict[str, Any] = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {
            "items": [{"name": "concept", "var": "concept", "prose_before": "C:\n"}],
        },
        "nodes": [
            {
                "id": "write-lyrics",
                "type": "llm",
                "prompt_cache": ["concept"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Use ${concept.title} to write a song.",
                },
            }
        ],
        "edges": [],
    }
    diags = validate_data_flow(shadows_ir, check_inputs=False, workflow_path="x.pflow.md")
    found = [d for d in diags if d.id == "cache.prompt-body-shadows-cache"]
    assert found, f"validate_data_flow did not emit cache.prompt-body-shadows-cache: ids={[d.id for d in diags]}"
    _round_trip(found[0])
    seen_ids.add("cache.prompt-body-shadows-cache")

    # llm.thinking-temperature-mismatch: Anthropic LLM node with reasoning_effort
    # enabled AND temperature != 1.0 (Anthropic's API rejects this composition).
    thinking_temp_ir: dict[str, Any] = {
        "inputs": {"q": {"type": "string"}},
        "nodes": [
            {
                "id": "score-choruses",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-haiku-4-5",
                    "reasoning_effort": "low",
                    "temperature": 0.3,
                    "prompt": "Score: ${q}",
                },
            }
        ],
        "edges": [],
    }
    diags = validate_data_flow(thinking_temp_ir, check_inputs=False, workflow_path="x.pflow.md")
    found = [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]
    assert found, f"validate_data_flow did not emit llm.thinking-temperature-mismatch: ids={[d.id for d in diags]}"
    payload = _round_trip(found[0])
    # Pin numeric temperature survives JSON round-trip without coercion drift.
    assert payload["context"]["temperature"] == 0.3
    seen_ids.add("llm.thinking-temperature-mismatch")

    # --- summarize-emitted id (summarize.py) -----------------------------
    # cache.opportunities-available: the dry-run nudge fires when actionable
    # opportunities exist. Reuse the prewarm-no-prefix IR — it carries one.
    nudge = summarize_from_analysis(analysis)
    assert nudge is not None, "summarize_from_analysis returned None despite actionable opportunities"
    assert nudge.id == "cache.opportunities-available"
    _round_trip(nudge)
    seen_ids.add("cache.opportunities-available")

    # --- coverage assertion: every NON-STUBBED catalog id was driven ----
    expected_covered = (
        set(CACHE_WARNING_CATALOG.keys()) | {CACHE_OPPORTUNITIES_NUDGE_ID}
    ) - _STUBBED_PRODUCERS_DEFERRED_TO_V1X
    missing = expected_covered - seen_ids
    assert not missing, (
        f"production-driven test missed catalog ids that should have producers: {missing}. "
        f"If a stub became a real producer, drive it here and remove from "
        f"_STUBBED_PRODUCERS_DEFERRED_TO_V1X."
    )
