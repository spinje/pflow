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
    return PerCallRow(
        node_path=node_path,
        model="anthropic/claude-sonnet-4-5",
        is_batch=False,
        batch_size_estimated=None,
        input_tokens_estimated=10_000,
        cacheable_tokens_estimated=int(10_000 * ratio / 100),
        cache_ratio_pct=ratio,
        data_source="estimator",
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
    # The warning ID surfaces inline on the row line.
    review_lines = [line for line in text.splitlines() if "review" in line and "model=" in line]
    assert review_lines, "expected a per-call row line for review"
    assert "cache.dynamic-before-static" in review_lines[0]


def test_text_recommended_actions_drop_sub_cent_savings() -> None:
    """Bug D — sub-cent estimated_savings_usd must render as 'savings unavailable',
    not '-$0.00/run'. Tri-state contract: rounds-to-zero == unavailable."""
    from pflow.core.cache_analysis.analyze import RecommendedAction

    actions = (
        RecommendedAction(
            rank=1, warning_id="cache.shared-context-undeclared", node_id=None, estimated_savings_usd=0.001
        ),
        RecommendedAction(rank=2, warning_id="cache.dynamic-before-static", node_id="x", estimated_savings_usd=None),
        RecommendedAction(
            rank=3, warning_id="cache.batch-prewarm-recommended", node_id="y", estimated_savings_usd=0.42
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
    assert "1. [cache.shared-context-undeclared]  savings unavailable" in text
    assert "2. [cache.dynamic-before-static]  savings unavailable" in text
    # Above-threshold value still renders the dollar figure.
    assert "3. [cache.batch-prewarm-recommended]  -$0.42/run" in text
    # Critical: NO "$0.00" anywhere.
    assert "$0.00" not in text


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
