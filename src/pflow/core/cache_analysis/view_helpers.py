"""Renderer-side projections over a stable findings list.

Stage 0 of the analyze-cache data-model redesign: ``CacheAnalysis.warnings`` is
the single source of truth for findings; ranked / categorized / filtered
*views* are computed at output time. mypy / rustc / clippy / ruff all follow
this shape — pre-computed views in the data model create duplication, drift,
and ordering invariants that test fixtures encode incorrectly.

The blocking-errors / recommended-actions rankings and the cross-workflow
alignment filter live here. Both renderers (``render_text``, ``render_json``)
call into this module; no caller in ``analyze.py`` needs them.
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

    Used by ``_render_cross_workflow`` (include) and both action-view builders
    (exclude). Single source of truth for the renderer-side dispatch.
    """
    return diag.id in _CROSS_WORKFLOW_ALIGNMENT_IDS


# ---------------------------------------------------------------------------
# Action-view ranking
# ---------------------------------------------------------------------------


def build_blocking_errors(warnings: list[Diagnostic]) -> list[RecommendedAction]:
    """Project cache-domain ERROR-severity findings into a ranked action list.

    Cross-workflow alignment findings (rename, prose-mismatch) are filtered
    out — they render in the "Sub-workflow boundaries" section instead.

    Restricting to cache-domain (id startswith ``cache.``,
    ``llm.thinking-temperature-mismatch``, or ``context.path`` under
    ``cache.``/``prompt_cache``) aligns this view with
    ``AnalysisSummary.blocking_errors`` count. Non-cache validator errors
    surface via ``build_other_blocking_errors`` so agents distinguish caching
    work from env-config issues (B-9 fix).

    Ranking reuses the same core key as recommended actions. The severity
    dimension is degenerate inside this bucket because every eligible finding
    is an ERROR, so priority then savings then stable ID decide ties.
    """
    eligible = [
        d
        for d in warnings
        if d.severity == Severity.ERROR and not is_cross_workflow_alignment(d) and _is_cache_focused_for_advisory(d)
    ]
    return _build_actions(eligible)


def build_other_blocking_errors(warnings: list[Diagnostic]) -> list[RecommendedAction]:
    """Project non-cache ERROR-severity findings into a ranked action list.

    Workflow-blocking errors tangential to prompt caching (unknown node types,
    schema violations, LLM param errors). Surfaced under ``## Other blocking
    errors`` so agents can fix env-config issues without conflating them with
    caching work (B-9 fix).

    Cross-workflow alignment findings (rename, prose-mismatch) are filtered
    out — they render in the "Sub-workflow boundaries" section instead.
    """
    eligible = [
        d
        for d in warnings
        if d.severity == Severity.ERROR and not is_cross_workflow_alignment(d) and not _is_cache_focused_for_advisory(d)
    ]
    return _build_actions(eligible)


def build_recommended_actions(warnings: list[Diagnostic]) -> list[RecommendedAction]:
    """Project cache-domain WARNING + INFO findings into a ranked action list.

    Cross-workflow alignment findings (rename, prose-mismatch) are filtered
    out — they render in the "Sub-workflow boundaries" section instead.
    Non-cache advisory diagnostics remain in ``analysis.warnings`` for raw
    consumers, but they do not belong in analyze-cache's provider-cache action
    list.

    Sort key dimensions (lexicographic, all ascending after negation/inversion):

    1. **Severity** (WARNING > INFO) — higher-severity opportunities first.
    2. **Detection-class priority** (``RECOMMENDED_ACTION_PRIORITY`` in
       ``warning_catalog``) — actionable opportunities ahead of informational
       findings. Resolves the common "all INFO, no savings" case where
       alphabetical tie-break used to bury ``cache.shared-context-undeclared``
       (priority 10) under other findings. See GH #1 / #361 thread.
    3. **Savings** (when known) — higher dollar impact ranks ahead within a
       priority tier.
    4. **Stable alphabetical** on ``d.id`` — deterministic tie-break.
    """
    eligible = [
        d
        for d in warnings
        if d.severity != Severity.ERROR and not is_cross_workflow_alignment(d) and _is_cache_focused_for_advisory(d)
    ]
    return _build_actions(eligible)


def _is_cache_focused_for_advisory(diag: Diagnostic) -> bool:
    """Whether an advisory diagnostic belongs to provider prompt-cache UX."""
    if diag.id and diag.id.startswith("cache."):
        return True
    if diag.id == "llm.thinking-temperature-mismatch":
        return True
    path = (diag.context or {}).get("path")
    return isinstance(path, str) and (path.startswith("cache.") or ".prompt_cache" in path)


def _build_actions(eligible: list[Diagnostic]) -> list[RecommendedAction]:
    """Sort eligible findings and project them to ``RecommendedAction``."""
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
        if isinstance(savings_value, (int, float)) and savings_value > 0:
            savings = float(savings_value)
        return (-sev_weight, priority, -savings, d.id or "")

    sorted_warnings = sorted(eligible, key=_key)
    actions: list[RecommendedAction] = []
    for rank, d in enumerate(sorted_warnings, start=1):
        ctx = d.context or {}
        savings = ctx.get("savings_usd")
        if not isinstance(savings, (int, float)) or savings <= 0:
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
                suggestions=tuple(d.suggestions or ()),
            )
        )
    return actions


# ---------------------------------------------------------------------------
# Cross-workflow rename grouping (used by both renderer and dry-run nudge)
# ---------------------------------------------------------------------------


def group_renames_by_parent(
    rename_detections: list[Diagnostic],
) -> dict[str, dict[tuple[str, str], list[tuple[str, int]]]]:
    """Source-dedup renames into ``parent → (source_expr, child_input) → consumers``.

    Single-pass grouping that mirrors what ``## Sub-workflow boundaries``
    renders. Lives here (not in ``render_text``) so the dry-run nudge and
    other downstream surfaces can derive the same rendered count without
    re-walking diagnostic context.
    """
    by_parent: dict[str, dict[tuple[str, str], list[tuple[str, int]]]] = {}
    for diag in rename_detections:
        ctx = diag.context or {}
        parent = str(ctx.get("parent_workflow", ""))
        source_expr = str(ctx.get("parent_value_expr", ""))
        child_input = str(ctx.get("child_input_name", ""))
        child_wf = str(ctx.get("child_workflow", ""))
        try:
            line = int(ctx.get("line_in_parent", 0))
        except (TypeError, ValueError):
            line = 0
        groups = by_parent.setdefault(parent, {})
        groups.setdefault((source_expr, child_input), []).append((child_wf, line))
    return by_parent


def count_rendered_findings(warnings: list[Diagnostic]) -> tuple[int, int]:
    """Return ``(recommended_action_count, cross_workflow_boundary_count)``.

    Section-mapped counts that surface in ``pflow analyze-cache`` text output
    after Cluster A's parent-grouped collapse for renames. Use these on any
    surface (dry-run nudge, MCP, downstream tooling) that wants the
    user-facing count rather than ``actionable_opportunities`` (raw
    diagnostic count, pre-collapse — exposed in JSON for machine consumers).

    For lyrics-generator: raw ``actionable_opportunities=19``; this returns
    ``(2, 5) → 7`` rendered entries.
    """
    rec_count = len(build_recommended_actions(list(warnings)))
    rename_detections = [d for d in warnings if d.id == "cache.cross-workflow-rename-detected"]
    prose_mismatches = [d for d in warnings if d.id == "cache.cross-workflow-prose-mismatch"]
    grouped_rename_count = sum(len(g) for g in group_renames_by_parent(rename_detections).values())
    return (rec_count, grouped_rename_count + len(prose_mismatches))


__all__ = [
    "build_blocking_errors",
    "build_other_blocking_errors",
    "build_recommended_actions",
    "count_rendered_findings",
    "group_renames_by_parent",
    "is_cross_workflow_alignment",
]
