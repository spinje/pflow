"""F2.3 — text and JSON renderer tests.

Locks the agent-facing format contracts:
- JSON ``format_version`` is the constant ``JSON_FORMAT_VERSION`` (current ``"1.0"``).
- Empty-array contract for ``cross_workflow.*`` fields.
- Tri-state cost rendering (priced / partial / unavailable — never silent ``$0.00``).
- Default-hide-clean per-call rule + ``--all-rows`` override.
"""

from __future__ import annotations

import json

from pflow.core.cache_analysis import (
    JSON_FORMAT_VERSION,
    JSON_FORMAT_VERSION_MAJOR,
    render_json,
    render_text,
)
from pflow.core.cache_analysis.analyze import (
    AnalysisSummary,
    CacheAnalysis,
    CrossWorkflowFindings,
    PerCallRow,
)
from pflow.core.diagnostic import Diagnostic, Severity


def _make_analysis(
    *,
    rows: list[PerCallRow] | None = None,
    warnings: list[Diagnostic] | None = None,
    notes: list[str] | None = None,
    current: float | None = None,
    optimized: float | None = None,
    partial: bool = False,
    unavailable: tuple[str, ...] = (),
) -> CacheAnalysis:
    rows = rows or []
    warnings = warnings or []
    return CacheAnalysis(
        workflow_path="/abs/x.pflow.md",
        analyzed_at="2026-04-29T12:00:00Z",
        estimate_confidence="low_no_data",
        estimate_confidence_coverage={
            "trace": 0,
            "memo": 0,
            "estimator": len(rows),
            "heuristic": 0,
            "total": len(rows),
        },
        trace_path=None,
        summary=AnalysisSummary(
            current_cost_per_run_usd=current,
            optimized_cost_per_run_usd=optimized,
            rerun_cost_per_run_usd=None,
            savings_pct_first_run=None,
            savings_pct_rerun=None,
            blocking_errors=sum(1 for d in warnings if d.severity == Severity.ERROR),
            actionable_opportunities=len(warnings),
            warnings_count=sum(1 for d in warnings if d.severity == Severity.WARNING),
            info_count=sum(1 for d in warnings if d.severity == Severity.INFO),
            total_llm_calls_estimated=len(rows),
            total_input_tokens_estimated=sum(r.input_tokens_estimated for r in rows),
            total_cacheable_tokens_estimated=sum(r.cacheable_tokens_estimated for r in rows),
            models_in_use=tuple(sorted({r.model for r in rows if r.model})),
            partial_cost_usd=partial,
            unavailable_models=unavailable,
        ),
        recommended_actions=(),
        suggested_blocks=(),
        per_call=tuple(rows),
        cross_workflow=CrossWorkflowFindings(0, (), (), ()),
        warnings=tuple(warnings),
        notes=tuple(notes or []),
    )


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------


def test_json_format_version_is_constant() -> None:
    """JSON output reads from JSON_FORMAT_VERSION; consumer rule passes."""
    result = render_json(_make_analysis())
    assert result["format_version"] == JSON_FORMAT_VERSION
    # Consumer rule contract — would still pass on a future "1.1" minor bump.
    assert result["format_version"].startswith(JSON_FORMAT_VERSION_MAJOR + ".")


def test_json_cross_workflow_empty_arrays_are_present() -> None:
    """Empty-array contract — agents treat absence as a positive signal."""
    result = render_json(_make_analysis())
    cw = result["cross_workflow"]
    assert cw["rename_detections"] == []
    assert cw["prose_mismatches"] == []
    assert cw["value_flow_opportunities"] == []
    assert cw["boundaries_analyzed"] == 0


def test_json_round_trips_through_dumps_loads() -> None:
    """Catches non-serializable values leaking into the response."""
    result = render_json(_make_analysis())
    round_tripped = json.loads(json.dumps(result))
    assert round_tripped == result


def test_json_warnings_use_diagnostic_to_dict_shape() -> None:
    diag = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.below-min-tokens",
        message="X: declared cache content is ~512 tokens, below claude/min of 1024",
        suggestions=["Add chunks"],
        context={"category": "cache_warning", "model": "claude-sonnet-4-5"},
    )
    result = render_json(_make_analysis(warnings=[diag]))
    assert result["warnings"][0]["id"] == "cache.below-min-tokens"
    assert result["warnings"][0]["severity"] == "warning"


# ---------------------------------------------------------------------------
# Text renderer — cost tri-state
# ---------------------------------------------------------------------------


def test_text_renders_priced_cost_normally() -> None:
    text = render_text(_make_analysis(current=2.18, optimized=0.84, partial=False))
    assert "~$2.18" in text
    assert "~$0.84" in text
    assert "$0.00" not in text


def test_text_renders_unavailable_cost_explicitly_not_zero() -> None:
    """All unpriced models → ``unavailable`` (NEVER ``$0.00``)."""
    text = render_text(_make_analysis(current=None, optimized=None))
    assert "$0.00" not in text
    assert "unavailable" in text.lower()


def test_text_renders_partial_cost_with_marker() -> None:
    text = render_text(
        _make_analysis(
            current=0.84,
            optimized=0.42,
            partial=True,
            unavailable=("ollama/llama3.2:8b",),
        )
    )
    assert "~$0.84 (partial)" in text
    assert "ollama/llama3.2:8b" in text


# ---------------------------------------------------------------------------
# Text renderer — default-hide-clean per-call rule
# ---------------------------------------------------------------------------


def _row(node_path: str, ratio: int, warnings: tuple[str, ...] = ()) -> PerCallRow:
    """Build a PerCallRow that survives the Option C real-data filter.

    Default ``data_source="memo"`` makes the row visible in the per-call cache
    report — the section is hidden entirely when no row has real data
    (``data_source in {"trace", "memo"}`` OR ``declared_prompt_cache`` set).
    Tests that specifically exercise the data-source display mapping override
    this with ``"estimator"``/``"heuristic"`` AND set ``declared_prompt_cache``
    so the row passes the filter via the steady-state branch.
    """
    return PerCallRow(
        node_path=node_path,
        model="anthropic/claude-sonnet-4-5",
        is_batch=False,
        batch_size_estimated=None,
        input_tokens_estimated=10_000,
        cacheable_tokens_estimated=int(10_000 * ratio / 100),
        cache_ratio_pct=ratio,
        data_source="memo",
        declared_prompt_cache=None,
        warnings=warnings,
    )


def test_text_default_hides_clean_rows_above_80_pct() -> None:
    rows = [_row("clean1", 90), _row("clean2", 95), _row("dirty", 30)]
    text = render_text(_make_analysis(rows=rows))
    assert "dirty" in text
    assert "clean1" not in text
    assert "clean2" not in text
    assert "Hidden: 2 nodes" in text


def test_text_all_rows_flag_shows_everything() -> None:
    rows = [_row("clean1", 90), _row("clean2", 95), _row("dirty", 30)]
    text = render_text(_make_analysis(rows=rows), all_rows=True)
    assert "clean1" in text
    assert "clean2" in text
    assert "dirty" in text
    assert "Hidden:" not in text


def test_text_rows_with_warnings_show_even_above_threshold() -> None:
    """A row at 95% ratio but with an inline warning must NOT be hidden."""
    rows = [_row("noisy", 95, warnings=("cache.below-min-tokens",))]
    text = render_text(_make_analysis(rows=rows))
    assert "noisy" in text


def test_text_rows_with_analysis_wide_warning_show_even_above_threshold() -> None:
    """Bug B regression — a row at ≥80% ratio with NO inline warnings but a
    matching ``analysis.warnings`` Diagnostic (the production shape; analytical
    detections emit Diagnostics, not row-inline tuples) must NOT be hidden.

    Mutation test: remove the ``row.node_path in nodes_with_warnings`` clause
    from ``_is_row_visible_by_default``; this test must fail.
    """
    rows = [_row("review", 95)]  # row.warnings = () — empty inline tuple
    diag = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.dynamic-before-static",
        message="x",
        node_id="review",
    )
    text = render_text(_make_analysis(rows=rows, warnings=[diag]))
    assert "review" in text
    assert "Hidden: 1" not in text


def test_text_per_call_inline_marker_includes_analysis_wide_warning_id() -> None:
    """When a row has an analysis-wide warning, render its ID inline next to
    the row (so agents reading the per-call report see WHY the row is shown).

    Stage-1 final UX pass: the ``cache.`` namespace prefix is stripped from
    inline markers since every ID in this column is namespaced ``cache.*``
    — the prefix is 100% redundant in the per-call notes column. Full IDs
    stay in JSON for machine consumers (DD#27).
    """
    rows = [_row("review", 30)]  # already visible due to ratio
    diag = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.dynamic-before-static",
        message="x",
        node_id="review",
    )
    text = render_text(_make_analysis(rows=rows, warnings=[diag]))
    # The warning ID surfaces inline on the row line — without ``cache.`` prefix.
    review_lines = [line for line in text.splitlines() if "review" in line and "model=" in line]
    assert review_lines, "expected a per-call row line for review"
    assert "dynamic-before-static" in review_lines[0]
    # Critical: the redundant ``cache.`` prefix is gone from the inline column.
    assert "cache.dynamic-before-static" not in review_lines[0]


def test_text_recommended_actions_render_workflow_scope_for_workflow_level_findings() -> None:
    """When ``RecommendedAction.node_id is None`` AND ``scope_workflow`` is set,
    the renderer surfaces the workflow basename on its scope line so
    workflow-level findings are distinguishable from per-node ones (the GH #2
    surface).

    Stage-1 final UX pass: the ``[cache.X]`` bracket prefix and ``Workflow:``/
    ``Node:`` labels were dropped — the rank-line headline + scope-line
    basename/node_id carry enough discriminator. The load-bearing contract is
    that workflow-level and per-node findings render with DIFFERENT scope
    lines.

    Mutation test: comment out the ``elif action.scope_workflow:`` branch in
    ``render_text._render_recommended_actions`` and this test fails — the
    workflow-level finding renders with no scope line, indistinguishable
    from a fully-unscoped finding.
    """
    from pflow.core.cache_analysis.analyze import RecommendedAction

    actions = (
        RecommendedAction(
            rank=1,
            warning_id="cache.shared-context-undeclared",
            node_id=None,
            estimated_savings_usd=None,
            scope_workflow="/abs/path/song-creator.pflow.md",
            headline="Shared context undeclared — declare `concept` in ## Cache",
        ),
        # Per-node finding alongside (existing rendering preserved).
        RecommendedAction(
            rank=2,
            warning_id="cache.shared-context-undeclared",
            node_id="emotional-reviews",
            estimated_savings_usd=None,
            headline="Shared context undeclared — declare `concept` in ## Cache",
        ),
    )
    base = _make_analysis()
    analysis = type(base)(
        workflow_path=base.workflow_path,
        analyzed_at=base.analyzed_at,
        estimate_confidence=base.estimate_confidence,
        estimate_confidence_coverage=base.estimate_confidence_coverage,
        trace_path=base.trace_path,
        summary=base.summary,
        recommended_actions=actions,
        suggested_blocks=base.suggested_blocks,
        per_call=base.per_call,
        cross_workflow=base.cross_workflow,
        warnings=base.warnings,
        notes=base.notes,
    )
    text = render_text(analysis)
    # The headline is the rank-line title.
    assert "Shared context undeclared" in text
    # Workflow-level finding gets the basename on its scope line, NOT the full path.
    assert "song-creator.pflow.md" in text
    assert "/abs/path/" not in text  # Full path NOT surfaced; basename only.
    # Per-node finding renders the node_id on its scope line.
    assert "emotional-reviews" in text
    # The bracketed ID prefix is GONE from rank lines — top-10% codebases
    # don't visually code long namespaced descriptors as error codes.
    assert "[cache.shared-context-undeclared]" not in text


def test_text_recommended_actions_inline_label_passes_through() -> None:
    """Non-path scope identifiers (``<inline>``, ``ir-hash:abc123``) pass through
    unchanged — they're not filesystem paths, so basename extraction shouldn't
    chop a meaningful prefix off them.

    Stage-1 final UX pass: the ``Workflow:`` prefix label was dropped — the
    scope-line basename/identifier alone is the discriminator. The
    load-bearing contract is that ``<inline>`` survives intact (no
    accidental basename chopping).
    """
    from pflow.core.cache_analysis.analyze import RecommendedAction

    actions = (
        RecommendedAction(
            rank=1,
            warning_id="cache.shared-context-undeclared",
            node_id=None,
            estimated_savings_usd=None,
            scope_workflow="<inline>",
            headline="Shared context undeclared — declare `concept` in ## Cache",
        ),
    )
    base = _make_analysis()
    analysis = type(base)(
        workflow_path=base.workflow_path,
        analyzed_at=base.analyzed_at,
        estimate_confidence=base.estimate_confidence,
        estimate_confidence_coverage=base.estimate_confidence_coverage,
        trace_path=base.trace_path,
        summary=base.summary,
        recommended_actions=actions,
        suggested_blocks=base.suggested_blocks,
        per_call=base.per_call,
        cross_workflow=base.cross_workflow,
        warnings=base.warnings,
        notes=base.notes,
    )
    text = render_text(analysis)
    # ``<inline>`` survives intact on its scope line — no basename chopping.
    assert "<inline>" in text


def test_text_recommended_actions_unscoped_finding_omits_scope_line() -> None:
    """When neither node_id nor scope_workflow is set (defensive fallback),
    the renderer omits the scope line entirely rather than showing an empty
    line.

    Stage-1 final UX pass: the rank line carries the headline (no
    ``[cache.X]`` prefix anymore). The load-bearing invariant is still:
    no spurious blank scope line for fully-unscoped findings.
    """
    from pflow.core.cache_analysis.analyze import RecommendedAction

    headline = "Shared context undeclared — declare `concept` in ## Cache"
    actions = (
        RecommendedAction(
            rank=1,
            warning_id="cache.shared-context-undeclared",
            node_id=None,
            estimated_savings_usd=None,
            scope_workflow=None,
            headline=headline,
        ),
    )
    base = _make_analysis()
    analysis = type(base)(
        workflow_path=base.workflow_path,
        analyzed_at=base.analyzed_at,
        estimate_confidence=base.estimate_confidence,
        estimate_confidence_coverage=base.estimate_confidence_coverage,
        trace_path=base.trace_path,
        summary=base.summary,
        recommended_actions=actions,
        suggested_blocks=base.suggested_blocks,
        per_call=base.per_call,
        cross_workflow=base.cross_workflow,
        warnings=base.warnings,
        notes=base.notes,
    )
    text = render_text(analysis)
    # Headline renders as the rank line.
    assert headline in text
    # The bracketed ID prefix is GONE (Stage-1 UX pass).
    assert "[cache.shared-context-undeclared]" not in text
    # Locate the rank line, then verify nothing follows it that looks like a
    # scope line (i.e. no indented content immediately under the headline).
    lines = text.splitlines()
    rank_line_idx = next(i for i, line in enumerate(lines) if headline in line)
    # Whatever is on the next non-empty line should NOT be a stray scope line
    # belonging to this action — there should be no scope content here.
    # The line immediately after the rank line should be blank or end-of-section.
    next_line = lines[rank_line_idx + 1] if rank_line_idx + 1 < len(lines) else ""
    assert next_line.strip() == "", f"Expected no scope line after unscoped rank entry; got: {next_line!r}"


def test_text_recommended_actions_drop_sub_cent_savings() -> None:
    """Bug D — sub-cent estimated_savings_usd must render as 'savings unavailable',
    not '-$0.00/run'. Tri-state contract: rounds-to-zero == unavailable.

    Stage-1 final UX pass: the ``[cache.X]`` bracket prefix is gone from rank
    lines. The savings tri-state contract (None / sub-cent → 'savings
    unavailable'; real value → '-$X.XX/run') is unchanged.
    """
    from pflow.core.cache_analysis.analyze import RecommendedAction

    actions = (
        RecommendedAction(
            rank=1,
            warning_id="cache.shared-context-undeclared",
            node_id=None,
            estimated_savings_usd=0.001,
            headline="Shared context undeclared — declare `concept` in ## Cache",
        ),
        RecommendedAction(
            rank=2,
            warning_id="cache.dynamic-before-static",
            node_id="x",
            estimated_savings_usd=None,
            headline="Dynamic ref blocks caching on x — move ref after stable content",
        ),
        RecommendedAction(
            rank=3,
            warning_id="cache.batch-prewarm-recommended",
            node_id="y",
            estimated_savings_usd=0.42,
            headline="Batch prewarm not declared — add `- prewarm: true` to y",
        ),
    )
    analysis = _make_analysis()
    analysis = type(analysis)(  # rebuild with non-empty recommended_actions
        workflow_path=analysis.workflow_path,
        analyzed_at=analysis.analyzed_at,
        estimate_confidence=analysis.estimate_confidence,
        estimate_confidence_coverage=analysis.estimate_confidence_coverage,
        trace_path=analysis.trace_path,
        summary=analysis.summary,
        recommended_actions=actions,
        suggested_blocks=analysis.suggested_blocks,
        per_call=analysis.per_call,
        cross_workflow=analysis.cross_workflow,
        warnings=analysis.warnings,
        notes=analysis.notes,
    )
    text = render_text(analysis)
    # Sub-cent (0.001) and None both render as "savings unavailable".
    # Two findings render with this label — both rank lines must carry it.
    savings_unavailable_count = text.count("savings unavailable")
    assert savings_unavailable_count >= 2, (
        f"expected ≥2 'savings unavailable' rank lines (sub-cent + None); got {savings_unavailable_count}"
    )
    # Above-threshold value still renders the dollar figure on its rank line.
    assert "-$0.42/run" in text
    # Critical: NO "$0.00" anywhere.
    assert "$0.00" not in text
    # Stage-1 UX pass: the ``[cache.X]`` bracket prefix is gone from rank lines.
    assert "[cache.shared-context-undeclared]" not in text
    assert "[cache.dynamic-before-static]" not in text
    assert "[cache.batch-prewarm-recommended]" not in text


# ---------------------------------------------------------------------------
# Text renderer — notes
# ---------------------------------------------------------------------------


def test_text_renders_notes_in_locked_order() -> None:
    notes = [
        "Found 2 2.0.0 traces matching this workflow but skipped...",
        "Found 1 unparseable trace files in ~/.pflow/debug/...",
        "Gemini telemetry note: ...",
    ]
    text = render_text(_make_analysis(notes=notes))
    # Each note appears in order in the text output.
    pos_2_0 = text.find("2.0.0 traces")
    pos_unparseable = text.find("unparseable")
    pos_gemini = text.find("Gemini telemetry")
    assert pos_2_0 < pos_unparseable < pos_gemini


# ---------------------------------------------------------------------------
# CP2 (#11) — Cross-workflow rendering surfaces node_id + chunks
# ---------------------------------------------------------------------------


def _make_value_flow_diag(node_id: str, chunk: str, child_workflow: str = "/abs/child.pflow.md") -> Diagnostic:
    """Build a cache.shared-context-undeclared diag mirroring how the analyzer
    emits it for cross-workflow value-flow boundaries (analyze.py:_cross_workflow_value_flow_opportunity).
    """
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    return make_diagnostic(
        "cache.shared-context-undeclared",
        node_id=node_id,
        node_count=6,
        shared_chunks=[chunk],
        affected_workflow="/abs/parent.pflow.md",
        child_workflow=child_workflow,
        savings_usd=None,
    )


def test_text_cross_workflow_section_uses_sub_workflow_boundaries_header() -> None:
    """CP5 #3 — section renamed from 'Cross-workflow alignment (Tier 2)' to
    'Sub-workflow boundaries' so agents don't have to know what 'Tier 2' is.

    Mutation test: revert the header in ``_render_cross_workflow``; this test
    fails because the agent-facing section name regresses to internal pflow
    architecture jargon.
    """
    diag = _make_value_flow_diag("choose-chorus", "concept")
    analysis = _make_analysis()
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "cross_workflow": CrossWorkflowFindings(1, (), (), (diag,)),
    })
    text = render_text(analysis)
    assert "## Sub-workflow boundaries" in text
    assert "Cross-workflow alignment" not in text
    assert "Tier 2" not in text


def test_text_cross_workflow_findings_are_distinguishable() -> None:
    """CP5 #3 — three findings with different node_id / shared_chunks render
    as three DISTINCT multi-line blocks.

    Multiple findings of the same warning_id MUST produce different output;
    pre-CP2 they were byte-identical (the lyrics-generator three-line bug).

    Mutation test: revert the value-flow finding renderer to drop ``node_id``
    or ``shared_chunks`` from the boundary header — the three blocks collapse
    to identical text and this test fails.
    """
    diag1 = _make_value_flow_diag("choose-chorus", "concept", child_workflow="/abs/chorus-chooser.pflow.md")
    diag2 = _make_value_flow_diag("emotional-reviews", "concept_brief", child_workflow="/abs/review-emotional.pflow.md")
    diag3 = _make_value_flow_diag("craft-reviews", "concept_brief", child_workflow="/abs/review-craft.pflow.md")

    analysis = _make_analysis()
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "cross_workflow": CrossWorkflowFindings(3, (), (), (diag1, diag2, diag3)),
    })
    text = render_text(analysis)

    # Each block has a distinct boundary header line.
    assert "→ chorus-chooser" in text
    assert "→ review-emotional" in text
    assert "→ review-craft" in text
    # Via the parent's type:workflow node ID — distinguishes findings that
    # share the same parent → child pair (heterogeneous batches, etc.).
    assert "via choose-chorus" in text
    assert "via emotional-reviews" in text
    assert "via craft-reviews" in text
    # The chunks each finding is about.
    assert "`concept`" in text
    assert "`concept_brief`" in text


def test_text_cross_workflow_value_flow_emits_action_line() -> None:
    """Stage-1 final UX pass: every finding has an explicit headline-led action
    so the agent knows what to do without inferring from the symptom prose.

    Pre-fix this was a bullet-led ``→ Add`` action line; post-fix it's the
    catalog's headline_template at the top of the finding block (rank line).
    The catalog headline for ``cache.shared-context-undeclared`` boundary
    scope is "Cross-boundary value undeclared — declare ``X`` in either
    ## Cache".

    Mutation test: drop the headline source from
    ``_format_boundary_finding``; this test fails because the finding
    renders with the prose message as the rank-line title and the
    discriminator-bearing headline disappears.
    """
    diag = _make_value_flow_diag("choose-chorus", "concept")
    analysis = _make_analysis()
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "cross_workflow": CrossWorkflowFindings(1, (), (), (diag,)),
    })
    text = render_text(analysis)
    # New shape: headline carries the action, the message body explains why.
    assert "Cross-boundary value undeclared" in text
    assert "`concept`" in text
    # Action context still surfaces in the message paragraph.
    assert "either workflow's ## Cache" in text
    # Stage-1 UX pass: per-finding ``[cache.X]`` footer is gone.
    assert "[cache.shared-context-undeclared]" not in text


def test_text_cross_workflow_rename_finding_full_format() -> None:
    """Stage-1 final UX pass: rename findings render as headline + scope + reason.

    Layout: rank line is the catalog headline (e.g. ``Cross-workflow rename
    — `concept_brief` ↔ `creative_brief```), scope line is ``parent → child
     (line N)``, reason paragraph is the descriptive message body.

    Pre-fix: 4-line block with bullet ``→ Rename`` action + ``[cache.X]``
    footer. Post-fix: catalog-driven headline + scope + reason. Same
    Diagnostic data, restructured presentation.

    Mutation test: revert ``_format_boundary_finding`` to drop the headline
    source; this test fails because the discriminator-bearing rename arrow
    (``↔``) disappears from the rank line.
    """
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.cross-workflow-rename-detected",
        node_id="parent-step",
        parent_workflow="/abs/song-creator.pflow.md",
        child_workflow="/abs/chorus-chooser.pflow.md",
        parent_value_expr="concept_brief",
        child_input_name="creative_brief",
        line_in_parent=42,
        parent_node_id="parent-step",
    )
    analysis = _make_analysis()
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "cross_workflow": CrossWorkflowFindings(1, (diag,), (), ()),
    })
    text = render_text(analysis)
    # Headline rank line carries the rename arrow + both names.
    assert "Cross-workflow rename" in text
    assert "`concept_brief`" in text
    assert "`creative_brief`" in text
    # Scope line: parent → child  (line N).
    assert "song-creator → chorus-chooser" in text
    assert "(line 42)" in text
    # Stage-1 UX pass: bullet ``→ Rename`` action and ``[cache.X]`` footer
    # are gone — the headline carries the action and section context disambiguates.
    assert "→ Rename" not in text
    assert "[cache.cross-workflow-rename-detected]" not in text


def test_text_cross_workflow_prose_mismatch_finding_full_format() -> None:
    """Stage-1 final UX pass: prose-mismatch findings render as headline +
    scope + reason.

    Layout: rank line is the catalog headline (``Cross-workflow prose
    mismatch — align `concept` in both ## Cache blocks``), scope line is
    ``parent → child`` (no ``(line N)`` for prose mismatches), reason
    paragraph is the descriptive message body.

    Pre-fix: 4-line block with ``Chunk `X```, ``→ Pick one prose label``
    action + ``[cache.X]`` footer. Post-fix: catalog-driven headline +
    scope + reason.

    Mutation test: revert ``_format_boundary_finding`` to drop the headline
    source; this test fails because the discriminator (chunk_name in the
    headline) disappears from the rank line.
    """
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.cross-workflow-prose-mismatch",
        node_id=None,
        parent_workflow="/abs/song-creator.pflow.md",
        child_workflow="/abs/chorus-chooser.pflow.md",
        chunk_name="concept",
        parent_prose="Parent prose",
        child_prose="Different prose",
    )
    analysis = _make_analysis()
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "cross_workflow": CrossWorkflowFindings(1, (), (diag,), ()),
    })
    text = render_text(analysis)
    # Headline rank line carries the discriminator-bearing chunk name.
    assert "Cross-workflow prose mismatch" in text
    assert "`concept`" in text
    # Scope line: parent → child (no `(line N)` for prose mismatch).
    assert "song-creator → chorus-chooser" in text
    # Stage-1 UX pass: ``→ Pick one prose label`` bullet + ``[cache.X]``
    # footer are gone — the headline carries the action.
    assert "→ Pick one prose label" not in text
    assert "[cache.cross-workflow-prose-mismatch]" not in text


# ---------------------------------------------------------------------------
# CP5 Pass 3 — per-node .pflow.md syntax + header phrasing (#4, #6)
# ---------------------------------------------------------------------------


def test_text_per_node_assignments_render_as_pflow_md_syntax() -> None:
    """CP5 #4 — per-node section shows ``- prompt_cache: [a, b, c]`` syntax,
    NOT Python repr ``['a', 'b']``. The agent can copy-paste the exact lines
    they need to add to their workflow file.

    Mutation test: revert ``_render_suggested_blocks`` to the prior format
    (``f"    {node_id}: {assignment}"``); this test fails because Python
    repr brackets/quotes return.
    """
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept", var="${concept}", size_tokens_est=500, prose_placeholder="<DESCRIBE concept>"
            ),
            SuggestedBlockChunk(
                name="brief", var="${brief}", size_tokens_est=300, prose_placeholder="<DESCRIBE brief>"
            ),
        ),
        per_node_assignments={
            "write-lyrics": ["concept", "brief"],
        },
        estimated_savings_usd=None,
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)

    # Actual .pflow.md syntax — agent copy-pastes this directly.
    assert "### write-lyrics" in text
    assert "- prompt_cache: [concept, brief]" in text
    # The Python repr shape is GONE — no quotes around chunk names.
    assert "['concept', 'brief']" not in text
    assert "write-lyrics: ['concept'" not in text


def test_text_per_node_assignments_include_order_warning() -> None:
    """CP5 #4 — per-node section includes a brief explainer about the strict
    order requirement. Without this, agents pasting the lines might reorder
    them and trip cache.order-mismatch ERROR.

    Mutation test: drop the explainer block from ``_render_suggested_blocks``;
    this test fails because the order-warning text disappears.
    """
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(SuggestedBlockChunk(name="x", var="${x}", size_tokens_est=100, prose_placeholder="<x>"),),
        per_node_assignments={"node1": ["x"]},
        estimated_savings_usd=None,
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)
    # Order-warning explainer present.
    assert "Order MUST match" in text
    assert "cache.order-mismatch" in text


def test_text_header_lists_models_when_one_resolved() -> None:
    """CP5 #6 — when 1 model is in use, header reads
    ``"7 LLM nodes using anthropic/claude-sonnet-4-5"``.

    Mutation test: revert to ``"X LLM calls · Y models in use"``; this test
    fails because models_in_use[0] doesn't surface.
    """
    rows = [_row("n1", 50)]  # has model="anthropic/claude-sonnet-4-5" via _row
    text = render_text(_make_analysis(rows=rows))
    assert "1 LLM node using anthropic/claude-sonnet-4-5" in text


def test_text_header_lists_models_when_two_resolved() -> None:
    """CP5 #6 — when 2+ models, header lists them comma-separated.

    Mutation test: revert to count-only rendering; this test fails because
    individual model names disappear from the header.
    """
    row_a = PerCallRow(**{**_row("a", 50).__dict__, "model": "anthropic/claude-sonnet-4-5"})
    row_b = PerCallRow(**{**_row("b", 50).__dict__, "model": "gemini/gemini-3.1-pro-preview"})
    text = render_text(_make_analysis(rows=[row_a, row_b]))
    assert "2 models:" in text
    assert "anthropic/claude-sonnet-4-5" in text
    assert "gemini/gemini-3.1-pro-preview" in text


def test_text_header_handles_no_model_resolved() -> None:
    """CP5 #6 — when LLM nodes exist but no model resolves, surface the
    actionable hint inline with the count.

    Mutation test: drop the empty-models branch from ``_format_scale_line``;
    this test fails because the hint text doesn't appear.
    """
    row = PerCallRow(**{**_row("n1", 50).__dict__, "model": ""})
    text = render_text(_make_analysis(rows=[row]))
    assert "1 LLM node (no model resolved" in text
    assert "settings.default_model" in text


def test_text_header_handles_zero_llm_nodes() -> None:
    """CP5 #6 — workflow with no LLM nodes renders simply.

    Mutation test: drop the zero-nodes branch from ``_format_scale_line``;
    this test would fail with a divide-by-zero or odd output.
    """
    text = render_text(_make_analysis())  # no rows
    assert "0 LLM nodes" in text


def test_shared_chunks_csv_typed_alias_in_make_diagnostic() -> None:
    """make_diagnostic computes ``shared_chunks_csv`` from ``shared_chunks`` so
    every catalog template has a join-free way to render the discriminator.

    Mutation test: revert the format_dict population in warning_catalog.py;
    the message renders ``{shared_chunks_csv}`` literally (KeyError-free
    because str.format is permissive — but the typed alias would be missing).
    """
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.shared-context-undeclared",
        node_id="X",
        node_count=3,
        shared_chunks=["a", "b", "c"],
        affected_workflow="/abs/x.pflow.md",
        savings_usd=None,
    )
    assert "a, b, c" in diag.message


# ---------------------------------------------------------------------------
# CP4 — rendering polish (#16 #9 #7 #6+#13)
# ---------------------------------------------------------------------------


def _analysis_with_actions(actions: tuple) -> CacheAnalysis:
    """Replace the recommended_actions tuple on a base analysis."""
    base = _make_analysis()
    return CacheAnalysis(
        workflow_path=base.workflow_path,
        analyzed_at=base.analyzed_at,
        estimate_confidence=base.estimate_confidence,
        estimate_confidence_coverage=base.estimate_confidence_coverage,
        trace_path=base.trace_path,
        summary=base.summary,
        recommended_actions=actions,
        suggested_blocks=base.suggested_blocks,
        per_call=base.per_call,
        cross_workflow=base.cross_workflow,
        warnings=base.warnings,
        notes=base.notes,
    )


def test_text_does_NOT_render_all_warnings_section() -> None:
    """CP4 #16 — the "## All warnings" section is dropped from text output.

    Recommended Actions IS the canonical warnings view (sorted by impact).
    JSON output (``warnings[]``) keeps the full machine-readable list for
    consumers who want raw access via ``--format=json``.

    Stage-1 final UX pass: the ``[cache.X]`` bracket prefix and ``Node:``
    label are also gone. The contract that matters: agent visibility into
    the warning is preserved through Recommended Actions (now via headline
    + scope-line node_id).

    Mutation test: re-add the ``warnings = _render_warnings(analysis)``
    branch to ``render_text()``; this test fails because "## All warnings"
    re-appears in the text output.
    """
    from pflow.core.cache_analysis.analyze import RecommendedAction
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic, resolve_headline_for

    diag = make_diagnostic(
        "cache.shared-context-undeclared",
        node_id="some-node",
        node_count=3,
        shared_chunks=["concept"],
        affected_workflow="/abs/x.pflow.md",
        savings_usd=None,
    )
    # Resolve the headline via the catalog (catalog-as-SSoT — works whether
    # the diag came from make_diagnostic or was built directly).
    headline = resolve_headline_for(diag)
    actions = (
        RecommendedAction(
            rank=1,
            warning_id="cache.shared-context-undeclared",
            node_id="some-node",
            estimated_savings_usd=None,
            headline=headline,
            message=diag.message,
        ),
    )
    base = _analysis_with_actions(actions)
    analysis = CacheAnalysis(**{**base.__dict__, "warnings": (diag,)})
    text = render_text(analysis)
    assert "## All warnings" not in text, "All warnings section should be dropped from text output"
    # Recommended Actions IS the warnings view — agent visibility into the
    # warning MUST still surface there. The new shape carries this via
    # headline (rank line) + node_id (scope line).
    assert "Shared context undeclared" in text  # headline
    assert "some-node" in text  # scope-line node_id
    # Stage-1 UX pass: brackets gone, ``Node:`` label gone.
    assert "[cache.shared-context-undeclared]" not in text
    assert "Node: some-node" not in text


def test_text_brownfield_error_diagnostic_visible_in_recommended_actions() -> None:
    """Brownfield safety (CP4 #16): ERROR-severity diagnostics MUST stay
    visible after dropping "## All warnings".

    A workflow with ``cache.order-mismatch`` (ERROR) had its sole text-mode
    rendering path through the now-deleted "## All warnings" section if
    Recommended Actions skipped errors. Mutation test: drop ERROR severity
    from priority sort or omit ERRORs from ``_build_recommended_actions``;
    this test fails because the order-mismatch becomes invisible to text
    consumers.

    This is the load-bearing brownfield contract: workflows with declared
    ``## Cache`` blocks may have validator-emitted ERRORs that previously
    appeared ONLY in the now-deleted ``## All warnings`` view. The test
    drives the analyzer through a real production-shape workflow that
    triggers ``cache.order-mismatch``, then asserts the diagnostic survives
    in Recommended Actions.
    """
    from pflow.core.cache_analysis import analyze

    workflow_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "write-lyrics",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["b", "a"],  # wrong order — fires cache.order-mismatch ERROR
                "params": {"prompt": "${a} ${b}"},
            }
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    text = render_text(analysis)
    assert "## Recommended actions" in text
    # Stage-1 final UX pass: ``[cache.order-mismatch]`` brackets are gone.
    # The load-bearing brownfield contract: the ERROR-severity diagnostic
    # surfaces in Recommended Actions with enough discriminator for the
    # agent to act on it. The order-mismatch message body carries the
    # exact fix (``expected:``/``you wrote:``/``fix:`` lines), so the
    # agent sees both WHAT failed and HOW to fix without ID brackets.
    #
    # Verified:
    # - Recommended Actions section renders the diagnostic
    # - Node ID is visible (so the agent knows which node failed)
    # - The fix lines from the message body are visible
    # - Brackets are gone (the visual coding regression we deliberately
    #   removed in this UX pass)
    assert "write-lyrics" in text
    assert "expected:" in text  # one of the message body's fix lines
    assert "you wrote:" in text  # ditto — confirms full message rendered
    assert "[cache.order-mismatch]" not in text  # brackets dropped
    # Crucially, "## All warnings" is gone — the ERROR's ONLY rendering
    # path is now Recommended Actions.
    assert "## All warnings" not in text


def test_text_per_call_src_renders_as_confidence_labels() -> None:
    """CP4 #9 — internal data_source values map to user-facing confidence labels.

    JSON keeps the granular 4-tier (`per_call[].data_source` is unchanged
    machine consumers).

    Option C note: ``estimator`` and ``heuristic`` rows fail
    ``_row_has_real_data`` and would normally be hidden — pin them visible by
    setting ``declared_prompt_cache=["foo"]`` (steady-state branch passes the
    filter regardless of data_source).

    Mutation test: revert ``_data_source_display`` mapping to passthrough;
    this test fails because ``src=estimator`` re-appears in the rendered text.
    """
    rows = [
        _row("trace-row", 50),
        _row("memo-row", 50),
        _row("estim-row", 50),
        _row("heur-row", 50),
    ]
    rows[0] = PerCallRow(**{**rows[0].__dict__, "data_source": "trace"})
    rows[1] = PerCallRow(**{**rows[1].__dict__, "data_source": "memo"})
    # ``estimator``/``heuristic`` rows need declared_prompt_cache to survive
    # the Option C visibility filter — without it they're hidden.
    rows[2] = PerCallRow(**{**rows[2].__dict__, "data_source": "estimator", "declared_prompt_cache": ["foo"]})
    rows[3] = PerCallRow(**{**rows[3].__dict__, "data_source": "heuristic", "declared_prompt_cache": ["foo"]})
    text = render_text(_make_analysis(rows=rows))
    assert "src=high" in text  # trace + memo
    assert "src=medium" in text  # estimator
    assert "src=low" in text  # heuristic
    # Internal values must NOT leak into rendered text:
    assert "src=estimator" not in text
    assert "src=heuristic" not in text
    assert "src=trace" not in text
    assert "src=memo" not in text


def test_text_per_call_src_passes_through_unknown_values() -> None:
    """CP4 #9 — unknown source values pass through unmapped (fail-loud).

    A future tier (e.g. ``inferred``) surfaces verbatim until the map gains a
    row. This is intentional: silently mapping unknown values to a default
    confidence would mislead agents during the rollout window.

    Option C note: ``mystery`` is an unknown data_source so the row would be
    filtered out — pin it visible via ``declared_prompt_cache=["foo"]``
    (steady-state branch passes the filter regardless of data_source).

    Mutation test: replace the dict ``.get(value, value)`` with ``.get(value,
    "low")`` (a permissive default); this test fails because ``src=mystery``
    becomes ``src=low``, hiding the new tier.
    """
    rows = [_row("X", 50)]
    rows[0] = PerCallRow(**{**rows[0].__dict__, "data_source": "mystery", "declared_prompt_cache": ["foo"]})
    text = render_text(_make_analysis(rows=rows))
    assert "src=mystery" in text  # passes through unchanged


def test_text_pure_greenfield_hides_per_call_section_with_explanatory_note() -> None:
    """Option C: pure-greenfield workflows (no ``prompt_cache:`` declared AND
    no memo/trace data) hide the entire ``## Per-call cache report`` section.

    Pure-greenfield rows fail ``_row_has_real_data`` — their input_tokens
    column shows TEMPLATE size (with ``${var}`` references counted as ~5-token
    literals — NOT actual runtime size) and their cacheable column is
    unprojectable. Both columns mislead, so the section disappears entirely.

    The analyzer mirrors the renderer's filter at analyze-time and appends a
    Notes entry explaining the absence so agents understand it's intentional.
    The renderer must surface that note even though the per-call section is
    suppressed — the note IS the agent's signal to run the workflow once.

    Mutation test: remove the section-hide branch in ``_render_per_call``
    (return early when ``not real_data_rows``); this test fails because the
    misleading per-call table renders again.
    """
    # data_source="estimator" + declared_prompt_cache=None → fails filter.
    raw_rows = [_row("n1", 0), _row("n2", 0)]
    rows = [PerCallRow(**{**r.__dict__, "data_source": "estimator"}) for r in raw_rows]
    # The analyzer would append this note; mirror that here so the renderer
    # surfaces the agent-facing explanation.
    hidden_note = (
        "Per-call cache report hidden — workflow has no run data yet. "
        "Run once to populate memo cache; analyze-cache then shows real "
        "per-node token estimates and cacheable projections."
    )
    text = render_text(_make_analysis(rows=rows, notes=[hidden_note]))
    # Per-call section is hidden entirely.
    assert "## Per-call cache report" not in text
    # Notes entry surfaces the explanatory message.
    assert "Per-call cache report hidden" in text
    assert "no run data yet" in text
    # Mode-specific explainers must NOT render either (the section is gone).
    assert "Actual cache ratios" not in text
    assert "Projected cache ratios" not in text
    assert "No shared context detected" not in text


def test_text_per_call_explainer_post_run_greenfield_says_projected() -> None:
    """Option C: post-run greenfield workflows (no ``prompt_cache:`` declared
    but rows have memo/trace data) show the "Projected cache ratios from prior
    run data." explainer.

    Two explainer modes survive Option C's row filter:
    - **Steady-state** (any row has ``declared_prompt_cache``):
      "Actual cache ratios from declared `prompt_cache:` subsets."
    - **Post-run greenfield** (memo/trace rows, no declared):
      "Projected cache ratios from prior run data."

    The pure-greenfield "no shared context" branch was removed — those rows
    are filtered out before reaching the explainer (see
    ``test_text_pure_greenfield_hides_per_call_section_with_explanatory_note``).

    Mutation test: invert ``is_steady_state`` detection or change the
    post-run explainer string; this test fails because the wrong explainer
    renders for a memo-data row with no declared subset.
    """
    # ``_row("n1", 50)`` defaults to data_source="memo", declared_prompt_cache=None
    # — the post-run greenfield path that survives the Option C filter.
    rows = [_row("n1", 50)]
    text = render_text(_make_analysis(rows=rows))
    assert "## Per-call cache report" in text
    assert "Projected cache ratios from prior run data." in text
    # Other modes' explainers must NOT render here.
    assert "Actual cache ratios" not in text
    assert "No shared context detected" not in text


def test_text_per_call_explainer_steady_state_says_actual_ratios() -> None:
    """CP4 #7 — steady-state workflows (≥1 node has declared prompt_cache)
    show the "Actual cache ratios" explainer.

    Mutation test: invert the ``is_steady_state`` detection; this test fails.
    """
    rows = [_row("n1", 0), _row("n2", 75)]
    rows[1] = PerCallRow(**{**rows[1].__dict__, "declared_prompt_cache": ["concept", "concept_brief"]})
    text = render_text(_make_analysis(rows=rows))
    assert "Actual cache ratios" in text
    assert "Current ratios" not in text or "pre-cache" not in text


def test_text_header_drops_low_no_data_confidence() -> None:
    """CP4 #6+#13 — header omits ``Confidence: low_no_data`` line.

    The cost-section call-to-action ("run the workflow once") communicates
    the same info actionably; the header line was a redundant signal.

    Mutation test: revert ``_render_header`` to always emit the confidence
    line; this test fails because ``low_no_data`` re-appears.
    """
    text = render_text(_make_analysis())
    assert "low_no_data" not in text


def test_text_header_keeps_medium_from_memo_with_coverage() -> None:
    """CP4 #6+#13 — header KEEPS confidence label for medium/high tiers.

    These labels carry coverage info that helps agents reason about how much
    to trust the per-call numbers. Suppressing ALL confidence labels would
    hide actionable fidelity info; we only suppress the no-info ``low_no_data``.

    Mutation test: drop the ``if label in {medium..., high...}:`` branch from
    ``_render_header``; this test fails because the actionable label
    disappears alongside the redundant one.
    """
    rows = [_row("n1", 50), _row("n2", 50)]
    analysis = _make_analysis(rows=rows)
    # Override confidence label for testing
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "estimate_confidence": "medium_from_memo",
        "estimate_confidence_coverage": {"trace": 0, "memo": 2, "estimator": 0, "heuristic": 0, "total": 2},
    })
    text = render_text(analysis)
    assert "Confidence: medium_from_memo" in text
    assert "(2 of 2 nodes)" in text
