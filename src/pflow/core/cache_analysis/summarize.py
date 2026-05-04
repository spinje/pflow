"""Dry-run cache nudge — one-line ``Severity.INFO`` Diagnostic.

The ``--dry-run`` planner appends this Diagnostic to ``plan.diagnostics``;
the existing plan formatter renders it inline. ``None`` is returned when
the cache plan is already optimal so the dry-run output stays silent on
workflows with nothing to surface.

Locked text format (per spec § "—dry-run Cache Nudge"):

    Cache: {n} design opportunit{y_or_ies} available (estimated -${savings:.2f}/run, -{pct}%).
        Run 'pflow analyze-cache' for details.

JSON shape (emitted via ``Diagnostic.to_dict()`` with
``id="cache.opportunities-available"``):

    {
        "severity": "info",
        "id": "cache.opportunities-available",
        "message": "<locked text format>",
        "suggestions": ["Run 'pflow analyze-cache' for details."],
        "context": {
            "category": "cache_advisory",
            "opportunity_count": 4,
            "estimated_savings_usd": 1.34,
            "estimated_savings_pct": 61
        },
        "see_also": ["caching"]
    }
"""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import CACHE_ADVISORY_CATEGORY, Diagnostic, Severity

from .analyze import CacheAnalysis, analyze
from .warning_catalog import CACHE_OPPORTUNITIES_NUDGE_ID, format_dry_run_nudge


def summarize(
    workflow_ir: dict[str, Any],
    *,
    parameters: dict[str, Any] | None = None,
    workflow_path: str | None = None,
    **analyze_kwargs: Any,
) -> Diagnostic | None:
    """Produce the dry-run nudge Diagnostic, or ``None`` if no opportunities.

    Per DD#36, ``--dry-run`` runs the FULL analytical pass — agents opted in.
    Costs (token counting, historical state lookup, Tier 2 walk) are accepted.
    The nudge stays silent when the cache plan is optimal.
    """
    analysis = analyze(
        workflow_ir,
        parameters=parameters,
        workflow_path=workflow_path,
        **analyze_kwargs,
    )
    return summarize_from_analysis(analysis)


def summarize_from_analysis(analysis: CacheAnalysis) -> Diagnostic | None:
    """Cheaper variant when callers already ran ``analyze``."""
    actionable = analysis.summary.actionable_opportunities
    if actionable <= 0:
        return None

    # Anchor the savings percentage on the most authoritative figure:
    # ``actually_paid_usd`` when a trace contributed; ``no_cache_hypothetical_usd``
    # otherwise. Both atoms carry one meaning — agents reading the dry-run
    # nudge see "savings vs what was paid" or "savings vs no-cache baseline."
    summary = analysis.summary
    anchor = summary.actually_paid_usd if summary.actually_paid_usd is not None else summary.no_cache_hypothetical_usd
    first_run_with_cache = summary.first_run_with_cache_hypothetical_usd
    savings_value: float | None
    savings_pct: int | None
    if summary.aggregate_savings_first_run_usd is not None:
        savings_value = max(0.0, summary.aggregate_savings_first_run_usd)
        savings_pct = summary.savings_pct_first_run
        if savings_pct is None and anchor is not None and anchor > 0:
            savings_pct = round(100 * savings_value / anchor)
    elif first_run_with_cache is None or anchor is None or anchor <= 0:
        savings_value = None
        savings_pct = None
    else:
        savings_value = max(0.0, anchor - first_run_with_cache)
        savings_pct = round(100 * savings_value / anchor)

    message = format_dry_run_nudge(
        opportunity_count=actionable,
        savings_usd=savings_value,
        savings_pct=savings_pct,
    )

    return Diagnostic(
        severity=Severity.INFO,
        source="cache_analyzer",
        title="Cache Advisory",
        id=CACHE_OPPORTUNITIES_NUDGE_ID,
        message=message,
        suggestions=["Run 'pflow analyze-cache' for details."],
        context={
            "category": CACHE_ADVISORY_CATEGORY,
            "opportunity_count": actionable,
            "estimated_savings_usd": savings_value,
            "estimated_savings_pct": savings_pct,
        },
        see_also=["caching"],
    )


__all__ = ["summarize", "summarize_from_analysis"]
