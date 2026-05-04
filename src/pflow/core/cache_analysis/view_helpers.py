"""Renderer-side projections over a stable findings list.

Stage 0 of the analyze-cache data-model redesign: ``CacheAnalysis.warnings`` is
the single source of truth for findings; ranked / categorized / filtered
*views* are computed at output time. mypy / rustc / clippy / ruff all follow
this shape — pre-computed views in the data model create duplication, drift,
and ordering invariants that test fixtures encode incorrectly.

The recommended-actions ranking and the cross-workflow alignment filter live
here. Both renderers (``render_text``, ``render_json``) call into this module;
no caller in ``analyze.py`` needs them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pflow.core.diagnostic import Diagnostic, Severity

if TYPE_CHECKING:
    from .analyze import RecommendedAction


# ---------------------------------------------------------------------------
# Cross-workflow alignment filter
# ---------------------------------------------------------------------------
#
# These finding IDs render in the "Sub-workflow boundaries" section ONLY —
# their ``parent → child (line N)`` framing is load-bearing and they're not
# aggregable into a single resolution edit. Filtering them OUT of Recommended
# actions keeps each finding visible in exactly ONE section.
#
# Without the filter, post-Stage-0 the priority-50 entries in
# ``warning_catalog.RECOMMENDED_ACTION_PRIORITY`` would surface them in BOTH
# sections — that's the same duplication smell Stage 0 exists to remove
# (latent today on lyrics-generator because no rename findings fire, but
# would re-appear the moment a workflow has divergent prose labels).
#
# Adding new cross-workflow alignment IDs (per DD#29 catalog growth review)
# extends this constant in lockstep.
# ---------------------------------------------------------------------------


_CROSS_WORKFLOW_ALIGNMENT_IDS: frozenset[str] = frozenset({
    "cache.cross-workflow-rename-detected",
    "cache.cross-workflow-prose-mismatch",
})


def is_cross_workflow_alignment(diag: Diagnostic) -> bool:
    """Return True when the diagnostic belongs in the Sub-workflow boundaries section.

    Used by ``_render_cross_workflow`` (include) and ``build_recommended_actions``
    (exclude). Single source of truth for the renderer-side dispatch.
    """
    return diag.id in _CROSS_WORKFLOW_ALIGNMENT_IDS


# ---------------------------------------------------------------------------
# Recommended-actions ranking (relocated from analyze.py:2087)
# ---------------------------------------------------------------------------


def build_recommended_actions(warnings: list[Diagnostic]) -> list[RecommendedAction]:
    """Order findings by impact descending; rank starts at 1.

    Cross-workflow alignment findings (rename, prose-mismatch) are filtered
    out — they render in the "Sub-workflow boundaries" section instead.

    Sort key dimensions (lexicographic, all ascending after negation/inversion):

    1. **Severity** (ERROR > WARNING > INFO) — structural blockers first.
    2. **Detection-class priority** (``RECOMMENDED_ACTION_PRIORITY`` in
       ``warning_catalog``) — actionable opportunities ahead of informational
       findings. Resolves the common "all INFO, no savings" case where
       alphabetical tie-break used to bury ``cache.shared-context-undeclared``
       (priority 10) under other findings. See GH #1 / #361 thread.
    3. **Savings** (when known) — higher dollar impact ranks ahead within a
       priority tier.
    4. **Stable alphabetical** on ``d.id`` — deterministic tie-break.
    """
    # Local imports keep this module light and avoid a circular import with
    # ``analyze`` (RecommendedAction) and ``warning_catalog`` (priority table).
    from .analyze import RecommendedAction
    from .warning_catalog import (
        DEFAULT_RECOMMENDED_ACTION_PRIORITY,
        RECOMMENDED_ACTION_PRIORITY,
        resolve_headline_for,
    )

    def _key(d: Diagnostic) -> tuple[int, int, float, str]:
        sev_weight = {Severity.ERROR: 2, Severity.WARNING: 1, Severity.INFO: 0}.get(d.severity, 0)
        priority = RECOMMENDED_ACTION_PRIORITY.get(d.id or "", DEFAULT_RECOMMENDED_ACTION_PRIORITY)
        savings = 0.0
        ctx = d.context or {}
        savings_value = ctx.get("savings_usd")
        if isinstance(savings_value, (int, float)):
            savings = float(savings_value)
        return (-sev_weight, priority, -savings, d.id or "")

    # Filter cross-workflow alignment findings out before ranking — they
    # belong in the Sub-workflow boundaries section. Mutation contract:
    # removing this filter causes rename + prose-mismatch findings to appear
    # in BOTH sections (regression test in test_cache_analysis_renderers).
    eligible = [d for d in warnings if not is_cross_workflow_alignment(d)]
    sorted_warnings = sorted(eligible, key=_key)
    actions: list[RecommendedAction] = []
    for rank, d in enumerate(sorted_warnings, start=1):
        ctx = d.context or {}
        savings = ctx.get("savings_usd")
        if not isinstance(savings, (int, float)):
            savings = None
        # Workflow scope: when ``context.affected_workflow`` is set, surface it
        # for both workflow-level and per-node findings. Per-node diagnostics
        # need the location too because same node ids can appear in parent and
        # child workflows.
        scope_workflow: str | None = None
        affected = ctx.get("affected_workflow")
        if isinstance(affected, str) and affected:
            scope_workflow = affected
        # Catalog-as-SSoT: looks up headline_template by diag.id and formats
        # against context. Works whether the diag came from make_diagnostic OR
        # was built directly via Diagnostic(...) (validator emitters in
        # data_flow.py — _make_order_mismatch_diagnostic etc.).
        headline = resolve_headline_for(d)
        actions.append(
            RecommendedAction(
                rank=rank,
                warning_id=d.id or "",
                node_id=d.node_id,
                estimated_savings_usd=float(savings) if savings is not None else None,
                scope_workflow=scope_workflow,
                message=d.message or "",
                headline=headline,
            )
        )
    return actions


__all__ = [
    "build_recommended_actions",
    "is_cross_workflow_alignment",
]
