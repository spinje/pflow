"""F2.2 — dry-run nudge: locked text format + None on optimal plans."""

from __future__ import annotations

from pflow.core.cache_analysis.analyze import (
    AnalysisSummary,
    CacheAnalysis,
    CostDelta,
    CrossWorkflowFindings,
)
from pflow.core.cache_analysis.cost_estimation import CostTier
from pflow.core.cache_analysis.summarize import summarize, summarize_from_analysis
from pflow.core.diagnostic import Severity


def _analysis_with(
    actionable: int,
    current: float | None = None,
    optimized: float | None = None,
    first_run_savings: float | None = None,
) -> CacheAnalysis:
    """Build a minimal analysis around explicit cost deltas."""
    if first_run_savings is not None:
        first_run_delta = CostDelta(first_run_savings, None, "savings", "no_cache", "first_run")
    elif current is not None and optimized is not None and current > 0:
        raw_delta = current - optimized
        first_run_delta = CostDelta(
            abs(raw_delta),
            round(100 * abs(raw_delta) / current),
            "savings" if raw_delta > 0 else "cost_increase" if raw_delta < 0 else "break_even",
            "no_cache",
            "first_run",
        )
    else:
        first_run_delta = CostDelta(None, None, "unavailable", "no_cache", "first_run")
    summary = AnalysisSummary(
        actually_paid_usd=current,
        actually_paid_tier=CostTier.TRACE if current is not None else CostTier.UNAVAILABLE,
        no_cache_hypothetical_usd=current,
        first_run_with_cache_hypothetical_usd=optimized,
        rerun_within_ttl_hypothetical_usd=None,
        first_run_delta=first_run_delta,
        rerun_delta=CostDelta(None, None, "unavailable", "no_cache", "rerun"),
        actual_vs_no_cache_delta=CostDelta(None, None, "unavailable", "no_cache", "actual"),
        trace_coverage="none",
        trace_llm_nodes_static=10,
        trace_llm_nodes_executed=0,
        trace_unexecuted_llm_nodes=(),
        blocking_errors=0,
        actionable_opportunities=actionable,
        warnings_count=actionable,
        info_count=0,
        total_llm_nodes_estimated=10,
        total_llm_invocations_estimated=10,
        dynamic_batch_node_count=0,
        total_input_tokens_estimated=1000,
        total_cacheable_tokens_estimated=500,
        models_in_use=("anthropic/claude-sonnet-4-5",),
        partial_cost_usd=False,
        unavailable_models=(),
    )
    return CacheAnalysis(
        workflow_path="x.pflow.md",
        analyzed_at="2026-04-29T12:00:00Z",
        estimate_confidence="low_no_data",
        estimate_confidence_coverage={"trace": 0, "memo": 0, "estimator": 10, "heuristic": 0, "total": 10},
        trace_path=None,
        summary=summary,
        suggested_blocks=(),
        per_call=(),
        cross_workflow=CrossWorkflowFindings(0),
        warnings=(),
        notes=(),
    )


def test_returns_none_when_no_opportunities() -> None:
    diag = summarize_from_analysis(_analysis_with(actionable=0))
    assert diag is None


def test_singular_pluralization() -> None:
    """n=1 emits "1 design opportunity" (singular)."""
    diag = summarize_from_analysis(_analysis_with(actionable=1, current=2.0, optimized=1.9))
    assert diag is not None
    assert "1 design opportunity available" in diag.message
    assert "1 design opportunities" not in diag.message


def test_plural_pluralization() -> None:
    diag = summarize_from_analysis(_analysis_with(actionable=4, current=2.18, optimized=0.84))
    assert diag is not None
    assert "4 design opportunities available" in diag.message


def test_severity_info_and_id_set() -> None:
    diag = summarize_from_analysis(_analysis_with(actionable=2, current=1.0, optimized=0.5))
    assert diag is not None
    assert diag.severity == Severity.INFO
    assert diag.id == "cache.opportunities-available"


def test_suggestions_locked_text() -> None:
    diag = summarize_from_analysis(_analysis_with(actionable=2, current=1.0, optimized=0.5))
    assert diag is not None
    assert diag.suggestions == ["Run 'pflow analyze-cache' for details."]


def test_context_carries_opportunity_count_and_savings() -> None:
    diag = summarize_from_analysis(_analysis_with(actionable=4, current=2.18, optimized=0.84))
    assert diag is not None
    assert diag.context is not None
    assert diag.context["opportunity_count"] == 4
    assert diag.context["estimated_savings_usd"] == pytest_approx(1.34)
    assert diag.context["estimated_savings_pct"] == 61


def test_summarize_from_workflow_ir_returns_none_on_optimal() -> None:
    """Top-level summarize() smoke test on an empty workflow."""
    workflow_ir: dict = {"nodes": []}
    diag = summarize(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False)
    assert diag is None


def test_nudge_drops_dollar_figure_when_cost_unavailable() -> None:
    """Silent-failure regression: when current_cost / optimized_cost are None
    (cost tri-state unavailable), the nudge MUST NOT emit ``-$0.00/run, -0%``.
    Drop the figure entirely so agents see "opportunities exist" without the
    misleading zero-savings claim that would gate them out."""
    diag = summarize_from_analysis(_analysis_with(actionable=4, current=None, optimized=None))
    assert diag is not None
    assert "-$0.00" not in diag.message
    assert "-0%" not in diag.message
    assert diag.message == "Cache: 4 design opportunities available."
    # Context carries None to signal "unavailable" — agents distinguish None
    # from 0.0 when cost-gating their own decisions.
    assert diag.context is not None
    assert diag.context["estimated_savings_usd"] is None
    assert diag.context["estimated_savings_pct"] is None


def test_nudge_uses_first_run_delta_when_absolute_cost_unavailable() -> None:
    """A precomputed first-run delta can be rendered without absolute atoms."""
    diag = summarize_from_analysis(_analysis_with(actionable=2, first_run_savings=0.42))
    assert diag is not None
    assert diag.message == "Cache: 2 design opportunities available (saves ~$0.42/run on first run)."
    assert diag.context is not None
    assert diag.context["estimated_savings_usd"] == pytest_approx(0.42)
    assert diag.context["estimated_savings_pct"] is None


# Inline approx helper to avoid pytest fixture import order weirdness.
def pytest_approx(target: float, tol: float = 1e-6):
    class _Approx:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, (int, float)) and abs(other - target) < tol

    return _Approx()
