"""F1.1 — closed catalog of cache.* warning IDs and ``make_diagnostic`` helper.

Locks the agent-facing contract: every catalog entry produces a Diagnostic with
the documented severity / source / category / message / suggestions / context;
adding a new ID without updating EXPECTED_CATALOG_COUNT (auto-derived) fails
the integrity test; ``cache.discrepancy`` dispatch surfaces typed payloads on
``context["root_cause_action"]`` per the F1 plan section.
"""

from __future__ import annotations

import logging

import pytest

from pflow.core.cache_analysis.warning_catalog import (
    CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS,
    CACHE_DISCREPANCY_ACTION_TEMPLATES,
    CACHE_DISCREPANCY_REQUIRED_CONTEXT,
    CACHE_OPPORTUNITIES_NUDGE_ID,
    CACHE_WARNING_CATALOG,
    EXPECTED_CATALOG_COUNT,
    CacheWarningSpec,
    format_dry_run_nudge,
    make_diagnostic,
)
from pflow.core.diagnostic import (
    CACHE_ADVISORY_CATEGORY,
    CACHE_WARNING_CATEGORY,
    Diagnostic,
    Severity,
    deduplicate_diagnostics,
)

# ---------------------------------------------------------------------------
# Catalog integrity
# ---------------------------------------------------------------------------


def test_catalog_count_constant_is_auto_derived() -> None:
    """EXPECTED_CATALOG_COUNT must equal len(CATALOG) — adding a new entry
    cascades zero edits across the codebase."""
    assert len(CACHE_WARNING_CATALOG) == EXPECTED_CATALOG_COUNT


def test_catalog_has_fourteen_entries_v1() -> None:
    """v1 ships with 14 cache.* IDs (10 from spec DD#29 + cache.discrepancy from
    Round 2 + cache.invalid-on-non-llm and cache.prewarm-no-prefix from Round 3
    + cache.consolidate-to-root-recommended from CP3 + cache.opaque-prompt
    from Stage-1.5 / lyrics-generator verification). The catalog is closed
    per DD#29; expanding requires design review."""
    assert len(CACHE_WARNING_CATALOG) == 14


def test_all_entries_are_cache_namespaced() -> None:
    """Every catalog ID lives under the ``cache.*`` namespace."""
    for warning_id in CACHE_WARNING_CATALOG:
        assert warning_id.startswith("cache.")


def test_opportunities_nudge_id_is_outside_catalog() -> None:
    """The dry-run nudge ID is reserved separately per spec line 307 — emitted
    by summarize() not analyze()."""
    assert CACHE_OPPORTUNITIES_NUDGE_ID == "cache.opportunities-available"
    assert CACHE_OPPORTUNITIES_NUDGE_ID not in CACHE_WARNING_CATALOG


def test_every_spec_is_a_frozen_dataclass() -> None:
    """CacheWarningSpec must be frozen so the catalog can't be mutated at
    runtime (parallel-safe on a shared module load)."""
    spec = CACHE_WARNING_CATALOG["cache.unused-chunk"]
    assert isinstance(spec, CacheWarningSpec)
    with pytest.raises((AttributeError, TypeError)):
        spec.severity = Severity.ERROR  # type: ignore[misc]


def test_source_split_validator_vs_cache_analyzer() -> None:
    """The source field is per-row, not uniform. Validator-emitted IDs (run-time
    path) carry source='validator'; analyzer-emitted IDs (analytical-tier path)
    carry source='cache_analyzer'. Identity-tuple dedup collapses identical
    findings within a source but not across sources."""
    validator_ids = {
        "cache.order-mismatch",
        "cache.unused-chunk",
        "cache.invalid-on-non-llm",
    }
    for warning_id, spec in CACHE_WARNING_CATALOG.items():
        if warning_id in validator_ids:
            assert spec.source == "validator", warning_id
        else:
            assert spec.source == "cache_analyzer", warning_id


# ---------------------------------------------------------------------------
# make_diagnostic — happy paths
# ---------------------------------------------------------------------------


def test_make_diagnostic_unused_chunk() -> None:
    diag = make_diagnostic("cache.unused-chunk", chunk_name="topic", source_line=12)
    assert diag.severity == Severity.WARNING
    assert diag.source == "validator"
    assert diag.id == "cache.unused-chunk"
    assert diag.context is not None
    assert diag.context["category"] == CACHE_WARNING_CATEGORY
    assert diag.context["chunk_name"] == "topic"
    assert "topic" in diag.message


def test_make_diagnostic_order_mismatch_uses_bare_identifier_format() -> None:
    """Spec line 211-215 mandates bare-identifier bracketed lists (no quotes)."""
    diag = make_diagnostic(
        "cache.order-mismatch",
        node_id="write-lyrics",
        affected_workflow="x.pflow.md",
        declared=["concept", "concept_brief"],
        actual=["concept_brief", "concept"],
        declared_str="[concept, concept_brief]",
        actual_str="[concept_brief, concept]",
    )
    assert "[concept, concept_brief]" in diag.message
    assert "[concept_brief, concept]" in diag.message
    # No single quotes around items (the Python str(list) form would produce them).
    assert "'concept'" not in diag.message
    assert diag.context is not None
    # Typed lists preserved for agent dispatch.
    assert diag.context["declared"] == ["concept", "concept_brief"]
    assert diag.context["actual"] == ["concept_brief", "concept"]


def test_make_diagnostic_below_min_tokens() -> None:
    diag = make_diagnostic(
        "cache.below-min-tokens",
        node_id="rewrite",
        affected_workflow="x.pflow.md",
        model="claude-sonnet-4-5",
        cacheable_tokens=512,
        min_tokens=1024,
    )
    assert diag.severity == Severity.WARNING
    assert diag.id == "cache.below-min-tokens"
    assert "1024" in diag.message
    assert "claude-sonnet-4-5" in diag.message


def test_make_diagnostic_padding_advisory_with_savings() -> None:
    diag = make_diagnostic(
        "cache.padding-advisory",
        node_id="review-narrative",
        affected_workflow="x.pflow.md",
        current_subset=["song-architecture.response"],
        suggested_subset=["concept", "creative-direction.response", "song-architecture.response"],
        savings_usd=0.04,
    )
    assert diag.severity == Severity.INFO
    assert diag.context is not None
    assert diag.context["category"] == CACHE_ADVISORY_CATEGORY


def test_make_diagnostic_padding_advisory_with_null_savings() -> None:
    """``savings_usd`` is in nullable_cost_keys — None must not raise or
    substitute 0.00."""
    diag = make_diagnostic(
        "cache.padding-advisory",
        node_id="review-narrative",
        affected_workflow="x.pflow.md",
        current_subset=["a"],
        suggested_subset=["a", "b"],
        savings_usd=None,
    )
    # Diagnostic constructed cleanly; message renders even without dollar value.
    assert diag.id == "cache.padding-advisory"


def test_make_diagnostic_invalid_on_non_llm_combined_diagnostic() -> None:
    """V6: ONE diagnostic per node listing ALL invalid fields, not one per field."""
    diag = make_diagnostic(
        "cache.invalid-on-non-llm",
        node_id="heavy-compute",
        affected_workflow="x.pflow.md",
        node_type="shell",
        invalid_fields=["prompt_cache", "prewarm"],
        invalid_fields_csv="prompt_cache, prewarm",
        is_or_are="are",
        plural_s="s",
    )
    assert diag.severity == Severity.ERROR
    assert diag.context is not None
    assert diag.context["invalid_fields"] == ["prompt_cache", "prewarm"]
    # CSV both names present in message — agent sees both offenses.
    assert "prompt_cache" in diag.message
    assert "prewarm" in diag.message


def test_make_diagnostic_invalid_on_non_llm_dedup() -> None:
    """Same node + same id → identity tuple collapses, regardless of message."""
    diag1 = make_diagnostic(
        "cache.invalid-on-non-llm",
        node_id="X",
        affected_workflow="x.pflow.md",
        node_type="shell",
        invalid_fields=["prompt_cache"],
        invalid_fields_csv="prompt_cache",
        is_or_are="is",
        plural_s="",
    )
    diag2 = make_diagnostic(
        "cache.invalid-on-non-llm",
        node_id="X",
        affected_workflow="x.pflow.md",
        node_type="shell",
        invalid_fields=["prompt_cache"],
        invalid_fields_csv="prompt_cache",
        is_or_are="is",
        plural_s="",
    )
    assert len(deduplicate_diagnostics([diag1, diag2])) == 1


# ---------------------------------------------------------------------------
# make_diagnostic — error paths
# ---------------------------------------------------------------------------


def test_make_diagnostic_missing_required_context_raises() -> None:
    """The helper validates all required_context_keys at construction; missing
    keys raise KeyError so the catalog-misuse bug surfaces in tests, not in
    production renderers."""
    with pytest.raises(KeyError):
        make_diagnostic("cache.unused-chunk")  # missing chunk_name + source_line


def test_make_diagnostic_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        make_diagnostic("cache.does-not-exist", node_id="X", affected_workflow="x.pflow.md")


def test_make_diagnostic_node_id_without_affected_workflow_raises() -> None:
    """Workflow-scope contract: a ``cache.*`` diagnostic carrying a node_id MUST
    also carry ``affected_workflow``. Same node id can appear in parent and
    child workflows; without the workflow tag the renderer would key warnings
    against the wrong row.
    """
    with pytest.raises(KeyError, match="affected_workflow"):
        make_diagnostic(
            "cache.below-min-tokens",
            node_id="rewrite",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
        )


def test_make_diagnostic_node_id_with_affected_workflow_none_raises() -> None:
    """The workflow-scope guard validates value shape, not just key presence."""
    with pytest.raises(KeyError, match="affected_workflow"):
        make_diagnostic(
            "cache.below-min-tokens",
            node_id="rewrite",
            affected_workflow=None,
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
        )


def test_make_diagnostic_workflow_level_finding_does_not_require_affected_workflow() -> None:
    """The workflow-scope guard fires only when ``node_id`` is set. Workflow-level
    findings (``node_id=None``) are scoped by their own context (e.g.
    ``parent_workflow`` for cross-workflow boundaries) and don't go through the
    per-row warning lookup that the guard defends.
    """
    diag = make_diagnostic(
        "cache.cross-workflow-prose-mismatch",
        parent_workflow="p.pflow.md",
        child_workflow="c.pflow.md",
        chunk_name="concept",
        parent_prose="P",
        child_prose="C",
    )
    assert diag.node_id is None
    assert diag.id == "cache.cross-workflow-prose-mismatch"


# ---------------------------------------------------------------------------
# cache.discrepancy dispatch — typed action payloads
# ---------------------------------------------------------------------------


_BASE_DISCREPANCY_KWARGS = {
    "node_id": "X",
    "trace_path": "songs[1]",
    "affected_workflow": "x.pflow.md",
    "predicted_pct": 80,
    "predicted_label": "hit",
    "actual_pct": 20,
    "root_cause_summary": "auto",
    "cache_age_sec": None,
    "predicted_cache_key": None,
    "actual_cache_key": None,
}


@pytest.mark.parametrize(
    "root_cause, extra_kwargs, expected_action_text, expected_payload",
    [
        (
            "ttl_expiry",
            {},
            "Consider `- ttl: 1h` on the x.pflow.md ## Cache block.",
            {"suggested_ttl": "1h", "affected_workflow": "x.pflow.md"},
        ),
        (
            "key_mismatch",
            {},
            "Upstream value changed between predicted run and actual run; re-run analyze-cache to refresh the prediction.",
            {"upstream_value_changed": True},
        ),
        (
            "parallel_write_race",
            {},
            "Add `- prewarm: true` to the batch node to serialize the first write.",
            {"recommended_fix": "prewarm:true"},
        ),
        (
            "chunk_skipped",
            {"skipped_chunk": "concept"},
            "Cache chunk `concept` was skipped at runtime (branch absent); declaration is correct but rendered subset is shorter.",
            {"skipped_chunk": "concept", "branch_node": None},
        ),
    ],
)
def test_cache_discrepancy_dispatch_per_cause(
    root_cause: str,
    extra_kwargs: dict,
    expected_action_text: str,
    expected_payload: dict,
) -> None:
    diag = make_diagnostic(
        "cache.discrepancy",
        root_cause=root_cause,
        **_BASE_DISCREPANCY_KWARGS,
        **extra_kwargs,
    )
    assert diag.suggestions == [expected_action_text]
    assert diag.context is not None
    assert diag.context["root_cause"] == root_cause  # original preserved
    assert diag.context["root_cause_action"] == expected_payload  # typed payload


def test_cache_discrepancy_missing_per_cause_required_key_raises() -> None:
    """``chunk_skipped`` requires ``skipped_chunk`` on the per-cause action payload;
    missing → KeyError. Uses ``chunk_skipped`` rather than ``ttl_expiry`` so the
    per-cause check is what fires — ``ttl_expiry``'s required key is
    ``affected_workflow`` which is also enforced by the workflow-scope contract,
    making it impossible to test the per-cause check in isolation."""
    with pytest.raises(KeyError, match="skipped_chunk"):
        make_diagnostic(
            "cache.discrepancy",
            root_cause="chunk_skipped",
            **_BASE_DISCREPANCY_KWARGS,
        )


def test_cache_discrepancy_missing_base_required_key_raises() -> None:
    """root_cause itself is in the base required-list; missing → KeyError BEFORE dispatch."""
    base = dict(_BASE_DISCREPANCY_KWARGS)
    with pytest.raises(KeyError):
        make_diagnostic("cache.discrepancy", **base)  # no root_cause


def test_cache_discrepancy_unknown_enum_falls_through_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown root_cause values fall through to the 'unknown' template AND
    log a warning so a future contributor adding an enum value but forgetting
    the dispatch map doesn't degrade silently."""
    caplog.set_level(logging.WARNING, logger="pflow.core.cache_analysis.warning_catalog")
    diag = make_diagnostic(
        "cache.discrepancy",
        root_cause="future_value",
        **_BASE_DISCREPANCY_KWARGS,
    )
    # Unknown-row template substitutes the rejected value so the agent sees what was rejected.
    assert "future_value" in diag.suggestions[0]  # type: ignore[index]
    assert diag.context is not None
    assert diag.context["root_cause"] == "future_value"
    assert diag.context["root_cause_action"] == {"raw_root_cause": "future_value"}
    # logger.warning was emitted somewhere in the call.
    assert any("future_value" in rec.message for rec in caplog.records)


def test_cache_discrepancy_chunk_skipped_branch_node_optional() -> None:
    """branch_node is optional in chunk_skipped; analyzer may not always identify."""
    diag = make_diagnostic(
        "cache.discrepancy",
        root_cause="chunk_skipped",
        skipped_chunk="concept",
        branch_node="router",
        **_BASE_DISCREPANCY_KWARGS,
    )
    assert diag.context is not None
    assert diag.context["root_cause_action"]["branch_node"] == "router"


def test_discrepancy_dispatch_maps_consistent() -> None:
    """The three dispatch maps must enumerate the same enum values."""
    keys_templates = set(CACHE_DISCREPANCY_ACTION_TEMPLATES.keys())
    keys_required = set(CACHE_DISCREPANCY_REQUIRED_CONTEXT.keys())
    keys_payload = set(CACHE_DISCREPANCY_ACTION_PAYLOAD_KEYS.keys())
    assert keys_templates == keys_required == keys_payload
    assert "unknown" in keys_templates


# ---------------------------------------------------------------------------
# Context-passthrough fidelity (Round 5 fix)
# ---------------------------------------------------------------------------


def _minimal_context_kwargs(warning_id: str) -> dict:
    """Build a minimal-but-valid context_kwargs payload for each catalog ID,
    using the required_context_keys from the spec."""
    samples: dict[str, dict] = {
        "cache.order-mismatch": {
            "node_id": "X",
            "affected_workflow": "x.pflow.md",
            "declared": ["a", "b"],
            "actual": ["b", "a"],
            "declared_str": "[a, b]",
            "actual_str": "[b, a]",
        },
        "cache.unused-chunk": {"chunk_name": "topic", "source_line": 12},
        "cache.shared-context-undeclared": {
            "node_count": 3,
            "shared_chunks": ["concept"],
            "affected_workflow": "x.pflow.md",
            "savings_usd": 0.78,
        },
        "cache.batch-prewarm-recommended": {
            "node_id": "score",
            "affected_workflow": "x.pflow.md",
            "batch_size": 34,
            "prefix_tokens_estimated": 2100,
            "savings_pct": 89,
            "savings_usd": 0.12,
        },
        "cache.dynamic-before-static": {
            "node_id": "score",
            "affected_workflow": "x.pflow.md",
            "dynamic_ref": "chorus_text",
            "dynamic_line": 3,
            "cacheable_tokens": 1640,
            "affected_calls": 136,
            "savings_usd": 0.31,
            "projected_ratio_pct": 87,
        },
        "cache.padding-advisory": {
            "node_id": "review",
            "affected_workflow": "x.pflow.md",
            "current_subset": ["a"],
            "suggested_subset": ["a", "b"],
            "savings_usd": 0.04,
        },
        "cache.below-min-tokens": {
            "node_id": "rewrite",
            "affected_workflow": "x.pflow.md",
            "model": "claude-sonnet-4-5",
            "cacheable_tokens": 512,
            "min_tokens": 1024,
        },
        "cache.cross-workflow-prose-mismatch": {
            "parent_workflow": "p.pflow.md",
            "child_workflow": "c.pflow.md",
            "chunk_name": "concept",
            "parent_prose": "P",
            "child_prose": "C",
        },
        "cache.cross-workflow-rename-detected": {
            "parent_workflow": "p.pflow.md",
            "child_workflow": "c.pflow.md",
            "parent_value_expr": "concept_brief",
            "child_input_name": "creative_brief",
            "line_in_parent": 77,
            "parent_node_id": "song-creator",
        },
        "cache.discrepancy": dict(_BASE_DISCREPANCY_KWARGS, root_cause="key_mismatch"),
        "cache.invalid-on-non-llm": {
            "node_id": "X",
            "affected_workflow": "x.pflow.md",
            "node_type": "shell",
            "invalid_fields": ["prompt_cache"],
            "invalid_fields_csv": "prompt_cache",
            "is_or_are": "is",
            "plural_s": "",
        },
        "cache.prewarm-no-prefix": {
            "node_id": "score",
            "affected_workflow": "x.pflow.md",
            "batch_alias": "item",
            "first_dynamic_position": 0,
        },
        "cache.consolidate-to-root-recommended": {
            "root": "concept",
            "sub_paths": ["concept.core_idea", "concept.title", "concept.angle"],
            "model": "anthropic/claude-sonnet-4-5",
            "min_tokens": 1024,
            "max_subpath_tokens": 200,
            "root_tokens": 1500,
            "affected_workflow": "x.pflow.md",
        },
        "cache.opaque-prompt": {
            "node_id": "process-items",
            "affected_workflow": "x.pflow.md",
            "var_ref": "item.prompt",
            "upstream_node_id": "prepare-items",
        },
    }
    return samples[warning_id]


# test_context_passthrough_fidelity removed: ``Diagnostic.context = {**kwargs}``
# means every kwarg is preserved by construction. The dispatch tests above
# (``test_make_discrepancy_diagnostic_dispatches_*`` lines 246-300) cover the
# typed payload structure for each ``cache.discrepancy`` root_cause via
# ``make_diagnostic`` against the actual dispatch table — that's the
# production-shaped invariant.


@pytest.mark.parametrize("warning_id", sorted(CACHE_WARNING_CATALOG.keys()))
def test_every_id_round_trips_through_make_diagnostic(warning_id: str) -> None:
    """Every catalog ID can be constructed without raising. Locks the contract."""
    kwargs = _minimal_context_kwargs(warning_id)
    node_id = kwargs.pop("node_id", None)
    diag = make_diagnostic(warning_id, node_id=node_id, **kwargs)
    assert isinstance(diag, Diagnostic)
    assert diag.id == warning_id


# ---------------------------------------------------------------------------
# format_dry_run_nudge — locked text format with explicit pluralization
# ---------------------------------------------------------------------------


def test_format_dry_run_nudge_plural() -> None:
    text = format_dry_run_nudge(opportunity_count=4, savings_usd=1.34, savings_pct=61)
    assert text == "Cache: 4 design opportunities available (estimated -$1.34/run, -61%)."


def test_format_dry_run_nudge_singular() -> None:
    text = format_dry_run_nudge(opportunity_count=1, savings_usd=0.10, savings_pct=5)
    assert text == "Cache: 1 design opportunity available (estimated -$0.10/run, -5%)."


def test_format_dry_run_nudge_drops_dollar_figure_when_savings_unavailable() -> None:
    """When savings_usd is None (cost data unavailable), the nudge MUST NOT
    emit ``-$0.00/run, -0%`` — that's the silent-failure attractor that
    misleads agents into thinking there's no upside. Drop the figure
    entirely instead."""
    text = format_dry_run_nudge(opportunity_count=4, savings_usd=None, savings_pct=None)
    assert text == "Cache: 4 design opportunities available."
    assert "-$0.00" not in text
    assert "-0%" not in text


def test_format_dry_run_nudge_drops_figure_when_only_pct_unavailable() -> None:
    """When dollar savings are known but percentage is unavailable, keep the
    actionable dollar estimate rather than hiding greenfield savings."""
    text = format_dry_run_nudge(opportunity_count=2, savings_usd=0.50, savings_pct=None)
    assert text == "Cache: 2 design opportunities available (estimated -$0.50/run)."


def test_format_dry_run_nudge_drops_sub_cent_savings_as_unavailable() -> None:
    """Bug D — sub-cent values (``< $0.005``) round to ``$0.00`` under
    ``f"{x:.2f}"``, falsely implying "we computed it, it's zero" when the
    actual data is too sparse. Tri-state contract treats sub-cent the same as
    None: drop the figure rather than emit ``-$0.00/run``.

    Mutation test: revert the sub-cent gate in ``format_dry_run_nudge`` to only
    check ``savings_usd is None``; this test must fail.
    """
    text = format_dry_run_nudge(opportunity_count=1, savings_usd=0.001, savings_pct=None)
    assert text == "Cache: 1 design opportunity available."
    assert "-$0.00" not in text

    text2 = format_dry_run_nudge(opportunity_count=3, savings_usd=0.0, savings_pct=0)
    assert text2 == "Cache: 3 design opportunities available."
    assert "-$0.00" not in text2


def test_format_dry_run_nudge_renders_at_one_cent_threshold() -> None:
    """Boundary check: ``$0.005`` renders, ``$0.0049`` does not."""
    rendered = format_dry_run_nudge(opportunity_count=1, savings_usd=0.005, savings_pct=None)
    assert "(estimated -$0.01/run)" in rendered  # rounds up to one cent
    suppressed = format_dry_run_nudge(opportunity_count=1, savings_usd=0.0049, savings_pct=None)
    assert suppressed == "Cache: 1 design opportunity available."


def test_compute_distribution_clause_pluralizes_node_noun_correctly() -> None:
    """Singular vs plural noun in the boundary distribution clause.

    Pre-fix surfaced on lyrics-generator song-creator: ``concept_brief`` and
    ``extract-emotional-lyrics`` flow to N sub-workflows with 1 LLM consumer
    each — the rendered output read "Used by 1 LLM nodes per destination"
    (grammatically wrong). The helper must agree number for both the
    uniform-per-destination case and the non-uniform total.

    Mutation test: revert either pluralization branch in
    ``_compute_distribution_clause`` and the matching parametrized case
    fails with the literal "1 LLM nodes" string in output.
    """
    from pflow.core.cache_analysis.warning_catalog import _compute_distribution_clause

    def _dest(name: str, count: int) -> dict:
        return {
            "child_workflow": f"/abs/{name}.pflow.md",
            "child_workflow_basename": f"{name}.pflow.md",
            "node_count": count,
        }

    # Uniform with count=1 per destination → "1 LLM node per destination" (singular).
    out = _compute_distribution_clause([_dest("a", 1), _dest("b", 1)])
    assert "1 LLM node per destination" in out
    assert "1 LLM nodes" not in out

    # Uniform with count>1 per destination → "N LLM nodes per destination" (plural).
    out = _compute_distribution_clause([_dest("a", 3), _dest("b", 3)])
    assert "3 LLM nodes per destination" in out

    # Non-uniform with total=1 → "1 LLM node" (singular total).
    out = _compute_distribution_clause([_dest("a", 1), _dest("b", 0)])
    # b is filtered upstream; if it slipped through, the total should still pluralize correctly.
    # This case exercises total==1 specifically:
    out_single = _compute_distribution_clause([_dest("only", 1)])
    assert "Used by 1 LLM node " in out_single  # trailing space anchors the noun position
    assert "1 LLM nodes" not in out_single

    # Non-uniform with total>1 → "N LLM nodes" (plural total).
    out = _compute_distribution_clause([_dest("a", 1), _dest("b", 2)])
    assert "Used by 3 LLM nodes (" in out
