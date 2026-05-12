"""F1.1 — closed catalog of cache.* warning IDs and ``make_diagnostic`` helper.

Locks the agent-facing contract: every catalog entry produces a Diagnostic with
the documented severity / source / category / message / suggestions / context;
adding a new ID without updating EXPECTED_CATALOG_COUNT (auto-derived) fails
the integrity test.
"""

from __future__ import annotations

import pytest

from pflow.core.cache_analysis.warning_catalog import (
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


def test_catalog_size_matches_v1_inventory() -> None:
    """v1 currently ships with 23 entries (22 ``cache.*`` plus 1 ``llm.*``):

    - 10 from spec DD#29
    - ``cache.discrepancy`` (Round 2)
    - ``cache.invalid-on-non-llm`` and ``cache.prewarm-no-prefix`` (Round 3)
    - ``cache.consolidate-to-root-recommended`` (CP3)
    - ``cache.opaque-prompt`` (Stage-1.5 / lyrics-generator verification)
    - ``cache.prompt-body-duplicates-cache`` and
      ``cache.prompt-body-shadows-cache`` (Task 159 follow-up:
      detect prompt-body / prompt_cache overlap)
    - ``llm.thinking-temperature-mismatch`` (Task 159 Stage 2 follow-up:
      validate-time check for Anthropic temperature=1.0 + extended-thinking
      requirement; first non-cache entry in the catalog)
    - ``cache.heterogeneous-models-fragment-cache`` and
      ``cache.first-call-write-penalty`` (Task 159 Stage 2 follow-up:
      exact-model cache namespace fragmentation and lone cache writes)
    - ``cache.system-prompts-fragment-cache`` (Task 159 PR #378 review-fix #5:
      divergent ``system:`` strings fragment cross-node cache sharing)
    - ``cache.sub-workflow-cache-undeclared`` (Task 159 Stage 2 follow-up:
      child workflows need their own cache declarations)
    - ``cache.prompt-cache-incomplete`` (Task 159 polish: partial per-node
      `prompt_cache:` declarations inside workflows that already declare
      `## Cache`)
    - ``cache.unsupported-provider-ttl`` (Gemini dynamic-TTL follow-up:
      provider capability validation for minute-level TTLs)

    The catalog is closed per DD#29; expanding requires design review.
    """
    assert len(CACHE_WARNING_CATALOG) == 23


def test_entries_use_known_namespaces() -> None:
    """Every catalog ID lives under one of the supported namespaces.

    Historically the catalog held only ``cache.*`` IDs; ``llm.*`` was added
    when validate-time checks for non-cache provider rules became necessary
    (the temp+thinking constraint). Future namespaces require updating this
    test alongside the catalog addition.
    """
    allowed_prefixes = ("cache.", "llm.")
    for warning_id in CACHE_WARNING_CATALOG:
        assert any(warning_id.startswith(p) for p in allowed_prefixes), (
            f"{warning_id!r} does not start with any allowed prefix in {allowed_prefixes}"
        )


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
        "cache.unsupported-provider-ttl",
        # Task 159 follow-up: prompt-body / prompt_cache overlap detection
        # routes through ``data_flow.py`` (validator) when prompt_cache is
        # declared and overlaps the prompt body.
        "cache.prompt-body-duplicates-cache",
        "cache.prompt-body-shadows-cache",
        # Task 159 Stage 2 follow-up: Anthropic temperature=1.0 +
        # extended-thinking requirement check, also validator-emitted.
        "llm.thinking-temperature-mismatch",
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
        evidence_kind="predicted",
        provider_note="cache_control markers will silently no-op at the provider",
    )
    assert diag.severity == Severity.WARNING
    assert diag.id == "cache.below-min-tokens"
    assert "1024" in diag.message
    assert "claude-sonnet-4-5" in diag.message
    assert "cache_control markers" in diag.message


def test_make_diagnostic_below_min_tokens_observed_message() -> None:
    diag = make_diagnostic(
        "cache.below-min-tokens",
        node_id="rewrite",
        affected_workflow="x.pflow.md",
        model="gemini/gemini-2.5-pro",
        cacheable_tokens=0,
        min_tokens=4096,
        evidence_kind="observed",
        provider_note="explicit `cachedContents` won't fire, but Gemini's automatic implicit cache may still apply",
    )
    assert "did not fire on this call" in diag.message
    assert "0 cache_creation + 0 cache_read tokens" in diag.message
    assert "Gemini's automatic implicit cache" in diag.message


def test_make_diagnostic_below_min_tokens_unknown_evidence_kind_fallback(caplog: pytest.LogCaptureFixture) -> None:
    diag = make_diagnostic(
        "cache.below-min-tokens",
        node_id="rewrite",
        affected_workflow="x.pflow.md",
        model="openai/gpt-5",
        cacheable_tokens=0,
        min_tokens=1024,
        evidence_kind="suspected",
        provider_note="",
    )
    assert "declared cache below openai/gpt-5's minimum of 1024" in diag.message
    assert "unknown evidence_kind" in caplog.text


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
# Headline pluralization
# ---------------------------------------------------------------------------


def test_sub_workflow_cache_undeclared_headline_pluralizes_input_count() -> None:
    """The `cache.sub-workflow-cache-undeclared` headline used to render
    ``declare N input(s)`` regardless of count. Fresh agents read ``declare 1
    input(s)`` as a typo. The catalog now interpolates ``{inputs_phrase}``,
    derived from ``affected_input_count`` at both ``make_diagnostic`` time and
    ``resolve_headline_for`` time.

    Mutation contract: remove the ``inputs_phrase`` derivation in
    ``resolve_headline_for`` and the singular-count assertion fails (the
    headline silently renders empty due to the KeyError-safe fallback).
    """
    from pflow.core.cache_analysis.warning_catalog import resolve_headline_for

    base_inputs = [
        {
            "child_input_name": "lyrics",
            "parent_value_expr": "lyrics",
            "parent_workflow": "parent.pflow.md",
            "parent_node_id": "call-child",
            "line_in_parent": 1,
            "tokens_estimated": 500,
            "consumer_node_ids": ["review"],
            "consumer_node_ids_csv": "`review`",
        }
    ]

    singular = make_diagnostic(
        "cache.sub-workflow-cache-undeclared",
        affected_workflow="child.pflow.md",
        child_workflow="child.pflow.md",
        child_workflow_basename="child.pflow.md",
        affected_input_count=1,
        inputs=base_inputs,
        body_block="(body)",
        case="refactor",
        savings_usd=None,
    )
    plural = make_diagnostic(
        "cache.sub-workflow-cache-undeclared",
        affected_workflow="child.pflow.md",
        child_workflow="child.pflow.md",
        child_workflow_basename="child.pflow.md",
        affected_input_count=3,
        inputs=base_inputs * 3,
        body_block="(body)",
        case="actionable",
        savings_usd=0.01,
    )

    singular_headline = resolve_headline_for(singular)
    plural_headline = resolve_headline_for(plural)

    assert "declare 1 input" in singular_headline
    assert "input(s)" not in singular_headline
    assert "1 inputs" not in singular_headline  # not pluralized for count==1

    assert "declare 3 inputs" in plural_headline
    assert "input(s)" not in plural_headline


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
            evidence_kind="predicted",
            provider_note="",
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
            evidence_kind="predicted",
            provider_note="",
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
# cache.discrepancy
# ---------------------------------------------------------------------------


_BASE_DISCREPANCY_KWARGS = {
    "node_id": "X",
    "workflow_path_short": "workflow",
    "root_cause_summary": "Upstream value changed between predicted run and actual run",
    "suggestion": "Upstream value changed between predicted run and actual run; re-run analyze-cache to refresh the prediction.",
    "predicted_cache_key": None,
    "actual_cache_key": None,
    "affected_workflow": "workflow.pflow.md",
}


def test_cache_discrepancy_missing_base_required_key_raises() -> None:
    """root_cause itself is in the base required-list; missing → KeyError."""
    base = dict(_BASE_DISCREPANCY_KWARGS)
    with pytest.raises(KeyError):
        make_diagnostic("cache.discrepancy", **base)  # no root_cause


def test_cache_discrepancy_uses_flat_suggestion_template() -> None:
    diag = make_diagnostic(
        "cache.discrepancy",
        root_cause="key_mismatch",
        **_BASE_DISCREPANCY_KWARGS,
    )
    assert diag.suggestions == [_BASE_DISCREPANCY_KWARGS["suggestion"]]
    assert diag.context is not None
    assert "root_cause_action" not in diag.context


def test_cache_discrepancy_chunk_skipped_branch_node_optional() -> None:
    """branch_node is optional passthrough context; analyzer may not always identify it."""
    diag = make_diagnostic(
        "cache.discrepancy",
        root_cause="chunk_skipped",
        skipped_chunk="concept",
        branch_node="router",
        **_BASE_DISCREPANCY_KWARGS,
    )
    assert diag.context is not None
    assert diag.context["branch_node"] == "router"


# ---------------------------------------------------------------------------
# Context-passthrough fidelity (Round 5 fix)
# ---------------------------------------------------------------------------


def test_sub_workflow_cache_suggestions_use_exact_pflow_syntax() -> None:
    """Catalog suggestion points at the child workflow edit target."""
    diag = make_diagnostic(
        "cache.sub-workflow-cache-undeclared",
        affected_workflow="child.pflow.md",
        child_workflow="child.pflow.md",
        child_workflow_basename="child.pflow.md",
        affected_input_count=1,
        inputs=[
            {
                "child_input_name": "shared_doc",
                "parent_value_expr": "shared_doc",
                "parent_workflow": "parent.pflow.md",
                "parent_node_id": "call-child",
                "line_in_parent": 42,
                "tokens_estimated": 2048,
                "consumer_node_ids": ["child-llm-a", "child-llm-b"],
                "consumer_node_ids_csv": "`child-llm-a`, `child-llm-b`",
            }
        ],
        body_block="Template variables to remove:\n  • `shared_doc` ~2,048 tokens — node(s) `child-llm-a` use `${shared_doc}`",
        case="actionable",
        savings_usd=None,
    )

    assert diag.suggestions is not None
    assert diag.suggestions == ["Edit: child.pflow.md"]
    assert "`$shared_doc`" not in diag.suggestions[0]


def test_cross_workflow_rename_suggestion_is_informational() -> None:
    """Rename diagnostics are JSON-only and must not claim cache fidelity risk."""
    diag = make_diagnostic(
        "cache.cross-workflow-rename-detected",
        parent_workflow="parent.pflow.md",
        child_workflow="child.pflow.md",
        parent_value_expr="concept_brief",
        child_input_name="creative_brief",
        line_in_parent=42,
        parent_node_id="call-child",
    )

    assert diag.suggestions == [
        "This warning is informational. Provider cache hits do not depend on "
        "variable names; they depend on the exact prose before each cached "
        "value and the resolved value bytes. Align names only if it improves "
        "code clarity."
    ]


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
        "cache.sub-workflow-cache-undeclared": {
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
        "cache.prompt-cache-incomplete": {
            "affected_workflow": "x.pflow.md",
            "workflow_basename": "x.pflow.md",
            "affected_node_count": 1,
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
            "evidence_kind": "predicted",
            "provider_note": "",
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
        "cache.unsupported-provider-ttl": {
            "node_id": "X",
            "affected_workflow": "x.pflow.md",
            "provider": "anthropic",
            "model": "anthropic/claude-sonnet-4-5",
            "ttl": "11m",
            "ttl_seconds": 660,
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
        "cache.heterogeneous-models-fragment-cache": {
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
        "cache.system-prompts-fragment-cache": {
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
        "cache.first-call-write-penalty": {
            "node_id": "draft",
            "model": "anthropic/claude-haiku-4-5",
            "affected_workflow": "x.pflow.md",
            "savings_usd": 0.0002,
        },
        "cache.opaque-prompt": {
            "node_id": "process-items",
            "affected_workflow": "x.pflow.md",
            "var_ref": "item.prompt",
            "upstream_node_id": "prepare-items",
        },
        "cache.prompt-body-duplicates-cache": {
            "node_id": "write-lyrics",
            "affected_workflow": "x.pflow.md",
            "overlapping_pairs": [{"chunk_name": "concept", "body_ref": "concept"}],
            "overlap_lines": "  - cached `${concept}` AND inline `${concept}`",
        },
        "cache.prompt-body-shadows-cache": {
            "node_id": "write-lyrics",
            "affected_workflow": "x.pflow.md",
            "shadowing_pairs": [
                {"chunk_name": "concept", "body_ref": "concept.title", "direction": "cache_contains_body"}
            ],
            "overlap_lines": "  - cached `${concept}` overlaps inline `${concept.title}` (cache_contains_body)",
        },
        "llm.thinking-temperature-mismatch": {
            "node_id": "score-choruses",
            "affected_workflow": "x.pflow.md",
            "model": "anthropic/claude-haiku-4-5",
            "reasoning_effort": "low",
            "temperature": 0.3,
        },
    }
    return samples[warning_id]


# test_context_passthrough_fidelity removed: ``Diagnostic.context = {**kwargs}``
# means every kwarg is preserved by construction. The per-ID round-trip below
# covers ``make_diagnostic`` against the actual catalog rows.


@pytest.mark.parametrize("warning_id", sorted(CACHE_WARNING_CATALOG.keys()))
def test_every_id_round_trips_through_make_diagnostic(warning_id: str) -> None:
    """Every catalog ID can be constructed without raising. Locks the contract."""
    kwargs = _minimal_context_kwargs(warning_id)
    node_id = kwargs.pop("node_id", None)
    diag = make_diagnostic(warning_id, node_id=node_id, **kwargs)
    assert isinstance(diag, Diagnostic)
    assert diag.id == warning_id


@pytest.mark.parametrize(
    "warning_id",
    [
        "cache.sub-workflow-cache-undeclared",
        "cache.cross-workflow-rename-detected",
        "cache.cross-workflow-prose-mismatch",
        "cache.consolidate-to-root-recommended",
        "cache.prompt-cache-incomplete",
    ],
)
def test_workflow_level_same_id_diagnostics_would_collapse_under_generic_dedup(warning_id: str) -> None:
    """Document the N4 trust boundary for workflow-level cache advisories.

    ``Diagnostic.__hash__`` ignores context and keys id-bearing diagnostics by
    ``(severity, source, node_id, id)``. These workflow-level advisories use
    ``node_id=None`` and encode workflow identity in context, so a generic
    dedup pass would erase later workflows. Analyzer warning lists therefore
    intentionally remain undeduped until the diagnostic identity is extended.
    """
    first = _minimal_context_kwargs(warning_id)
    second = dict(first)
    if "affected_workflow" in second:
        second["affected_workflow"] = "other.pflow.md"
    if "workflow_basename" in second:
        second["workflow_basename"] = "other.pflow.md"
    if "parent_workflow" in second:
        second["parent_workflow"] = "other-parent.pflow.md"
    if "child_workflow" in second:
        second["child_workflow"] = "other-child.pflow.md"
    if "child_workflow_basename" in second:
        second["child_workflow_basename"] = "other-child.pflow.md"

    first_diag = make_diagnostic(warning_id, **first)
    second_diag = make_diagnostic(warning_id, **second)

    assert first_diag.context != second_diag.context
    assert len([first_diag, second_diag]) == 2
    assert deduplicate_diagnostics([first_diag, second_diag]) == [first_diag]


# ---------------------------------------------------------------------------
# format_dry_run_nudge — locked text format with explicit pluralization
# ---------------------------------------------------------------------------


def test_format_dry_run_nudge_plural() -> None:
    text = format_dry_run_nudge(opportunity_count=4, first_run_savings_usd=1.34, first_run_savings_pct=61)
    assert text == "Cache: 4 design opportunities available (saves ~$1.34/run, 61% on first run)."


def test_format_dry_run_nudge_singular() -> None:
    text = format_dry_run_nudge(opportunity_count=1, first_run_savings_usd=0.10, first_run_savings_pct=5)
    assert text == "Cache: 1 design opportunity available (saves ~$0.10/run, 5% on first run)."


def test_format_dry_run_nudge_drops_dollar_figure_when_savings_unavailable() -> None:
    """When savings_usd is None (cost data unavailable), the nudge MUST NOT
    emit ``-$0.00/run, -0%`` — that's the silent-failure attractor that
    misleads agents into thinking there's no upside. Drop the figure
    entirely instead."""
    text = format_dry_run_nudge(opportunity_count=4)
    assert text == "Cache: 4 design opportunities available."
    assert "-$0.00" not in text
    assert "-0%" not in text


def test_format_dry_run_nudge_drops_figure_when_only_pct_unavailable() -> None:
    """When dollar savings are known but percentage is unavailable, keep the
    actionable dollar estimate rather than hiding greenfield savings."""
    text = format_dry_run_nudge(opportunity_count=2, first_run_savings_usd=0.50)
    assert text == "Cache: 2 design opportunities available (saves ~$0.50/run on first run)."


def test_format_dry_run_nudge_rerun_savings_with_first_run_write_premium() -> None:
    text = format_dry_run_nudge(
        opportunity_count=2,
        rerun_savings_usd=0.0267,
        rerun_savings_pct=85,
        first_run_added_usd=0.0049,
    )
    assert text == (
        "Cache: 2 design opportunities available (saves ~$0.03/run, 85% on rerun; adds ~$0.0049 on first run)."
    )
    assert "-$" not in text


def test_format_dry_run_nudge_renders_sub_cent_with_4_decimal_precision() -> None:
    """Sub-cent UX gap fix — sub-cent values render with 4-decimal precision
    instead of dropping to ``"available."`` placeholder.

    Pre-fix the ``< $0.005`` cutoff hid every Gemini-shaped sub-cent
    recommendation. Post-fix the cutoff is ``< $0.0001`` (truly negligible);
    values in the $0.0001-$0.01 range render with 4 decimals so agents see
    real magnitudes in text mode (matching the JSON contract).

    The Bug D regression invariant — "no -$0.00/run anywhere" — is still
    enforced: ``f"{x:.4f}"`` keeps real digits visible, never produces
    ``-$0.0000/run`` for the values in this range.

    Mutation test: revert the 4-decimal branch in ``format_dry_run_nudge``
    to always use 2 decimals; ``-$0.00/run`` reappears for $0.001 → this
    test must fail.
    """
    # Sub-cent values render with 4-decimal precision.
    text = format_dry_run_nudge(opportunity_count=1, first_run_savings_usd=0.0012)
    assert text == "Cache: 1 design opportunity available (saves ~$0.0012/run on first run)."
    assert "-$0.00/run" not in text  # Bug D regression — never the placeholder.

    # With percentage too.
    text2 = format_dry_run_nudge(opportunity_count=4, first_run_savings_usd=0.005, first_run_savings_pct=12)
    assert text2 == "Cache: 4 design opportunities available (saves ~$0.0050/run, 12% on first run)."

    # Below display ($0.00005) — drops the figure (truly negligible).
    text3 = format_dry_run_nudge(opportunity_count=2, first_run_savings_usd=0.00005)
    assert text3 == "Cache: 2 design opportunities available."

    # Zero / None — drops the figure (genuinely unavailable).
    text4 = format_dry_run_nudge(opportunity_count=3, first_run_savings_usd=0.0, first_run_savings_pct=0)
    assert text4 == "Cache: 3 design opportunities available."
    assert "-$0.00" not in text4

    text5 = format_dry_run_nudge(opportunity_count=1)
    assert text5 == "Cache: 1 design opportunity available."


def test_format_dry_run_nudge_renders_at_one_cent_threshold() -> None:
    """Boundary check: precision swap at the cent boundary.

    - ``$0.01`` and above use 2-decimal precision (e.g., ``-$0.01/run``).
    - ``$0.0001`` through ``$0.0099`` use 4-decimal precision (sub-cent).
    - Below ``$0.0001`` drops the figure entirely (truly negligible).
    """
    # At the cent boundary — 2-decimal rendering kicks in.
    at_cent = format_dry_run_nudge(opportunity_count=1, first_run_savings_usd=0.01)
    assert "(saves ~$0.01/run on first run)" in at_cent
    # Just below the cent boundary — 4-decimal precision.
    just_below = format_dry_run_nudge(opportunity_count=1, first_run_savings_usd=0.0099)
    assert "(saves ~$0.0099/run on first run)" in just_below
    # At the display floor — 4-decimal precision.
    at_floor = format_dry_run_nudge(opportunity_count=1, first_run_savings_usd=0.0001)
    assert "(saves ~$0.0001/run on first run)" in at_floor
    # Below the floor — figure dropped.
    below_floor = format_dry_run_nudge(opportunity_count=1, first_run_savings_usd=0.00009)
    assert below_floor == "Cache: 1 design opportunity available."
