"""Dry-run cache nudge — one-line ``Severity.INFO`` Diagnostic.

The ``--dry-run`` planner appends this Diagnostic to ``plan.diagnostics``;
the existing plan formatter renders it inline. ``None`` is returned when
the cache plan is already optimal so the dry-run output stays silent on
workflows with nothing to surface.

Text shape:

    Cache: {n} design opportunit{y_or_ies} available.
    Cache: {n} design opportunit{y_or_ies} available (saves ~$X/run on first run).
    Cache: {n} design opportunit{y_or_ies} available (saves ~$X/run on rerun; adds ~$Y on first run).
        Run 'pflow analyze-cache' for details.

Direction comes from ``AnalysisSummary``'s ``CostDelta.kind`` fields. Do not
render negative-signed "savings"; first-run write premiums are cost increases.

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
            "estimated_savings_pct": 61,
            "first_run_delta_kind": "savings",
            "rerun_delta_kind": "savings"
        },
        "see_also": ["prompt-caching"]
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
    """Cheaper variant when callers already ran ``analyze``.

    Uses the same section-mapped count surfaced by ``pflow analyze-cache``
    (``recommended actions + cross-workflow boundary findings``, post Cluster A
    grouping) so the dry-run nudge and the analyzer agree on how many things
    the agent will actually see. Raw ``actionable_opportunities`` (pre-collapse
    diagnostic count, e.g. 19 on lyrics-generator) stays in JSON for machine
    consumers.
    """
    from .view_helpers import count_rendered_findings

    rec_count, bnd_count = count_rendered_findings(list(analysis.warnings))
    actionable = rec_count + bnd_count
    if actionable <= 0:
        return None

    summary = analysis.summary
    message = format_dry_run_nudge(
        opportunity_count=actionable,
        first_run_savings_usd=_delta_amount(summary.first_run_delta, "savings"),
        first_run_savings_pct=_delta_pct(summary.first_run_delta, "savings"),
        rerun_savings_usd=_delta_amount(summary.rerun_delta, "savings"),
        rerun_savings_pct=_delta_pct(summary.rerun_delta, "savings"),
        first_run_added_usd=_delta_amount(summary.first_run_delta, "cost_increase"),
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
            "estimated_savings_usd": _delta_amount(summary.first_run_delta, "savings")
            or _delta_amount(summary.rerun_delta, "savings"),
            "estimated_savings_pct": _delta_pct(summary.first_run_delta, "savings")
            or _delta_pct(summary.rerun_delta, "savings"),
            "first_run_delta_kind": summary.first_run_delta.kind,
            "rerun_delta_kind": summary.rerun_delta.kind,
        },
        see_also=["prompt-caching"],
    )


def _delta_amount(delta: Any, kind: str) -> float | None:
    if getattr(delta, "kind", None) != kind:
        return None
    amount = getattr(delta, "amount_usd", None)
    return float(amount) if isinstance(amount, (int, float)) else None


def _delta_pct(delta: Any, kind: str) -> int | None:
    if getattr(delta, "kind", None) != kind:
        return None
    pct = getattr(delta, "pct_of_baseline", None)
    return int(pct) if isinstance(pct, int) else None


__all__ = ["summarize", "summarize_from_analysis"]
