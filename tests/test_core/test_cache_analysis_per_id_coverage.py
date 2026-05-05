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
from typing import Any

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
    "predicted_label": "hit",
    "actual_pct": 20,
    "root_cause_summary": "auto",
    "cache_age_sec": None,
    "predicted_cache_key": None,
    "actual_cache_key": None,
    "affected_workflow": "x.pflow.md",
}


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
        "cache.below-min-tokens": (
            "rewrite",
            {
                "model": "claude-sonnet-4-5",
                "cacheable_tokens": 512,
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
        "cache.prewarm-no-prefix": (
            "score",
            {"batch_alias": "item", "first_dynamic_position": 0, "affected_workflow": "x.pflow.md"},
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
        # Nested dispatch payload — highest complexity in the catalog.
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


# ---------------------------------------------------------------------------
# JSON format_version contract
# ---------------------------------------------------------------------------


def test_json_format_version_consumer_rule_holds() -> None:
    """Consumer rule: ``format_version.startswith(JSON_FORMAT_VERSION_MAJOR + ".")``
    accepts current ``"4.x"`` AND any future ``"4.x"`` minor bump. Lock both.

    Phase 5 (Task 159 cleanup) bumped 3.x → 4.0 — breaking field rename:
    the three overloaded summary cost fields (``current_cost_per_run_usd``,
    ``cost_without_caching_usd``, ``rerun_cost_per_run_usd``) were replaced
    with five atomic primitives, each carrying one meaning regardless of
    greenfield/trace context.
    """
    assert JSON_FORMAT_VERSION.startswith("4.")
    assert JSON_FORMAT_VERSION.startswith(JSON_FORMAT_VERSION_MAJOR + ".")


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
      ``cache.prompt-body-duplicates-cache``,
      ``cache.prompt-body-shadows-cache``
    - ``analyze`` → ``cache.below-min-tokens``, ``cache.prewarm-no-prefix``
    - ``summarize_from_analysis`` → ``cache.opportunities-available``
    """
    from pflow.core.cache_analysis import analyze, summarize_from_analysis
    from pflow.core.workflow.data_flow import validate_data_flow

    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(
        analyze_module,
        "estimate_tokens",
        lambda _model, text, **_kwargs: (len((text or "").split()), "heuristic"),
    )
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

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

    # --- analyzer-emitted ids (analyze.py) -------------------------------
    # cache.below-min-tokens: a node opts into a small declared cache —
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
    found = [d for d in analysis.warnings if d.id == "cache.below-min-tokens"]
    assert found, f"analyze did not emit cache.below-min-tokens: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.below-min-tokens")

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

    # cache.batch-prewarm-recommended: batch with large static prefix, no
    # explicit prewarm decision.
    batch_recommended_ir: dict[str, Any] = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "priced/model",
                "batch": {"items": [{"text": str(i)} for i in range(34)], "as": "item"},
                "params": {"prompt": ("stable " * 100) + "${item.text}"},
            }
        ],
        "edges": [],
    }
    analysis = analyze(batch_recommended_ir)
    found = [d for d in analysis.warnings if d.id == "cache.batch-prewarm-recommended"]
    assert found, f"analyze did not emit cache.batch-prewarm-recommended: ids={[d.id for d in analysis.warnings]}"
    _round_trip(found[0])
    seen_ids.add("cache.batch-prewarm-recommended")

    # cache.consolidate-to-root-recommended: brownfield path. Workflow declares
    # ``## Cache`` with two SUB-PATH chunks (``concept.title``, ``concept.core_idea``)
    # of the same root. Each sub-path is below the (mocked) min-cache threshold;
    # the consolidated ``${concept}`` would cross. Override ``_estimate_ref_tokens``
    # locally so the threshold check fires deterministically without needing
    # real memo data (production-shape estimator math is covered by dedicated
    # unit tests; this test only locks the emission contract).
    monkeypatch.setattr(
        analyze_module,
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
    analysis = analyze(dynamic_ir)
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

    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")

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

    # cache.discrepancy: 2.1.0 trace event with observable TTL-expiry fields.
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
                        "cache_age_sec": 301,
                        "cache_chunks_skipped": [],
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
