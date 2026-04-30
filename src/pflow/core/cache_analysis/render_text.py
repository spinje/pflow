"""Text rendering for ``pflow analyze-cache`` (default mode).

Implements spec § "Output Format — Text" with section ordering:

1. Header (workflow path, scale, confidence + coverage detail).
2. Summary (cost tri-state — partial / unavailable rendering).
3. Recommended actions (rank-ordered).
4. Suggested ## Cache block(s) — greenfield-only.
5. Cross-workflow alignment (Tier 2) — only when findings exist.
6. Per-call cache report (default-hide-clean unless ``--all-rows``).
7. All warnings.
8. Notes (info notes appended in the analyzer's locked order).

Cost tri-state contract (Suggestion 26):

- All priced → ``~$2.18``.
- Partial → ``~$0.84 (partial — 2 of 23 nodes use unpriced models)``.
- All unavailable → ``unavailable`` (NEVER ``$0.00``).

Default-hide-clean rule: rows with ``cache_ratio_pct >= 80`` and no inline
warnings collapse into a single ``Hidden: N nodes ...`` line. ``--all-rows``
overrides.
"""

from __future__ import annotations

from collections.abc import Iterable

from pflow.core.diagnostic import Severity

from .analyze import CacheAnalysis, PerCallRow

_HIDDEN_RATIO_THRESHOLD = 80


def render_text(analysis: CacheAnalysis, *, all_rows: bool = False) -> str:
    """Render the analyzer result as markdown-formatted text."""
    lines: list[str] = []
    lines.append(_render_header(analysis))
    lines.append(_render_summary(analysis))

    actions = _render_recommended_actions(analysis)
    if actions:
        lines.append(actions)

    blocks = _render_suggested_blocks(analysis)
    if blocks:
        lines.append(blocks)

    cross = _render_cross_workflow(analysis)
    if cross:
        lines.append(cross)

    per_call = _render_per_call(analysis, all_rows=all_rows)
    if per_call:
        lines.append(per_call)

    warnings = _render_warnings(analysis)
    if warnings:
        lines.append(warnings)

    notes = _render_notes(analysis)
    if notes:
        lines.append(notes)

    return "\n\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _render_header(analysis: CacheAnalysis) -> str:
    s = analysis.summary
    coverage = analysis.estimate_confidence_coverage
    label = analysis.estimate_confidence
    if label in {"medium_from_memo", "high_from_trace"}:
        # Per DD#34 line 638 — append coverage detail.
        source_count = (
            coverage.get("trace", 0)
            if label == "high_from_trace"
            else coverage.get("memo", 0) + coverage.get("trace", 0)
        )
        label = f"{label} ({source_count} of {coverage.get('total', 0)} nodes)"
    lines = [
        f"# Cache Analysis: {analysis.workflow_path}",
        "",
        f"  ~{s.total_llm_calls_estimated} LLM calls · {len(s.models_in_use)} models in use",
        f"  Confidence: {label}",
    ]
    return "\n".join(lines)


def _render_summary(analysis: CacheAnalysis) -> str:
    s = analysis.summary
    current_str = _format_cost(s.current_cost_per_run_usd, s.partial_cost_usd, s.unavailable_models)
    optimized_str = _format_cost(s.optimized_cost_per_run_usd, s.partial_cost_usd, s.unavailable_models)
    rerun_str = _format_cost(s.rerun_cost_per_run_usd, s.partial_cost_usd, s.unavailable_models)

    actionable_word = "opportunity" if s.actionable_opportunities == 1 else "opportunities"
    summary_lines = [
        "## Summary",
        "",
        f"  Current cost per run:        {current_str}",
        f"  Optimized cost per run:      {optimized_str}",
        f"  Cost on rerun (within 1h):   {rerun_str}",
    ]

    # Aggregate savings — meaningful even on greenfield (output cost cancels;
    # input-only math). Only render when ``prompt_cache:`` is declared on at
    # least one node (otherwise the figure is 0 by construction).
    if s.aggregate_savings_first_run_usd is not None and s.aggregate_savings_first_run_usd > 0:
        first_str = f"~${s.aggregate_savings_first_run_usd:.2f}/run"
        rerun_savings = s.aggregate_savings_rerun_usd
        if rerun_savings is not None and rerun_savings > 0:
            summary_lines.append(
                f"  Estimated savings if applied: {first_str} (first run); ~${rerun_savings:.2f}/run on rerun"
            )
        else:
            summary_lines.append(f"  Estimated savings if applied: {first_str}")

    summary_lines.extend([
        "",
        f"  {s.actionable_opportunities} {actionable_word} "
        f"({s.warnings_count} warning{'s' if s.warnings_count != 1 else ''}, "
        f"{s.info_count} info)",
    ])

    if s.partial_cost_usd and s.unavailable_models:
        models_csv = ", ".join(s.unavailable_models)
        summary_lines.append("")
        summary_lines.append(f"  Unpriced models: {models_csv}")
    elif s.current_cost_per_run_usd is None and s.aggregate_savings_first_run_usd is not None:
        # Greenfield path — pricing data exists, but output token counts are
        # unavailable. Tell the agent how to light up the absolute figures.
        summary_lines.append("")
        summary_lines.append(
            "  Absolute cost figures need a prior run (output token counts come from "
            "memo cache or a 2.1.0 trace). Run the workflow once and re-run analyze-cache."
        )
    elif s.current_cost_per_run_usd is None and not s.unavailable_models:
        # All-unavailable case — surface explicit reason.
        summary_lines.append("")
        summary_lines.append("  Cost data unavailable: workflow has no LLM nodes or model pricing is missing.")
    return "\n".join(summary_lines)


def _format_cost(value: float | None, partial: bool, unavailable_models: tuple[str, ...]) -> str:
    """Tri-state cost rendering per the F2 contract."""
    if value is None:
        if unavailable_models:
            return f"unavailable (all {len(unavailable_models)} models lack pricing data)"
        return "unavailable"
    if partial:
        # Partial — caller must already have appended " (partial — N of M ...)" to value.
        # We don't have N/M here, so just mark as partial.
        return f"~${value:.2f} (partial)"
    return f"~${value:.2f}"


def _render_recommended_actions(analysis: CacheAnalysis) -> str:
    if not analysis.recommended_actions:
        return ""
    lines = ["## Recommended actions (ordered by impact)", ""]
    for action in analysis.recommended_actions:
        lines.append(f"  {action.rank}. [{action.warning_id}]  {_format_savings_usd(action.estimated_savings_usd)}")
        if action.node_id:
            lines.append(f"     Node: {action.node_id}")
        elif action.scope_workflow:
            # Workflow-level finding (e.g. shared-context spanning N nodes in one
            # file). Without this branch, the scope line would be absent and the
            # finding would render indistinguishable from per-node ones — the
            # GH #2 surface. Use basename to keep the line short.
            lines.append(f"     Workflow: {_short_workflow_label(action.scope_workflow)}")
    return "\n".join(lines)


def _short_workflow_label(path: str) -> str:
    """Render a workflow path as a short label for the recommended-actions section.

    Filesystem paths get their basename; non-path identifiers (e.g.
    ``"<inline>"``, ``"ir-hash:<md5>"``) pass through as-is.
    """
    if "/" in path:
        return path.rsplit("/", 1)[-1] or path
    return path


def _format_savings_usd(value: float | None) -> str:
    """Tri-state savings rendering — mirrors ``warning_catalog.format_dry_run_nudge``.

    ``None`` (no estimate) and sub-cent (``< $0.005``, rounds-to-zero) both
    render as ``"savings unavailable"``. Emitting ``-$0.00/run`` would imply
    "we computed it, it's zero" when the actual data is too sparse — same
    tri-state contract violation top-10% codebases avoid (Bug D).
    """
    if value is None or value < 0.005:
        return "savings unavailable"
    return f"-${value:.2f}/run"


def _render_suggested_blocks(analysis: CacheAnalysis) -> str:
    if not analysis.suggested_blocks:
        return ""
    chunks = []
    for block in analysis.suggested_blocks:
        chunks.append(f"## Suggested ## Cache block — {block.target_file}")
        chunks.append("")
        chunks.append("  Paste between ## Inputs and ## Steps:")
        chunks.append("")
        chunks.append("  ## Cache")
        chunks.append("")
        chunks.append(f"  - ttl: {block.ttl}")
        chunks.append("")
        chunks.append("  ```cache")
        for chunk in block.chunks:
            chunks.append(f"  {chunk.prose_placeholder}")
            chunks.append("")
            chunks.append(f"  {chunk.var}")
            chunks.append("")
        chunks.append("  ```")
        if block.per_node_assignments:
            chunks.append("")
            chunks.append("  Per-node prompt_cache: assignments:")
            chunks.append("")
            for node_id, assignment in block.per_node_assignments.items():
                chunks.append(f"    {node_id}: {assignment}")
    return "\n".join(chunks)


def _render_cross_workflow(analysis: CacheAnalysis) -> str:
    cf = analysis.cross_workflow
    if not (cf.rename_detections or cf.prose_mismatches or cf.value_flow_opportunities):
        return ""
    lines = ["## Cross-workflow alignment (Tier 2)", ""]
    for diag in cf.rename_detections:
        lines.append(f"  ▸ [{diag.id}]  {diag.message}")
    for diag in cf.prose_mismatches:
        lines.append(f"  ▸ [{diag.id}]  {diag.message}")
    for diag in cf.value_flow_opportunities:
        lines.append(f"  ▸ [{diag.id}]  {diag.message}")
    return "\n".join(lines)


def _render_per_call(analysis: CacheAnalysis, *, all_rows: bool) -> str:
    if not analysis.per_call:
        return ""
    rows = list(analysis.per_call)
    # Analytical detections (cache.dynamic-before-static, cache.padding-advisory,
    # cache.batch-prewarm-recommended, cache.below-min-tokens, etc.) emit Diagnostic
    # objects to ``analysis.warnings`` rather than populating ``row.warnings`` (the
    # inline tuple). The default-hide rule MUST consult analysis-wide warnings;
    # otherwise nodes with cache_ratio ≥ 80% AND analytical warnings get silently
    # hidden from the default report — agents miss high-leverage recommendations.
    nodes_with_warnings = {d.node_id for d in analysis.warnings if d.node_id}
    visible, hidden_count = _select_visible_rows(
        rows,
        all_rows=all_rows,
        nodes_with_warnings=nodes_with_warnings,
    )
    if not visible and hidden_count == 0:
        return ""

    if all_rows:
        header = "## Per-call cache report"
    else:
        header = f"## Per-call cache report (showing {len(visible)} of {len(rows)} LLM nodes; all-clean rows hidden)"

    # Build per-row inline warning markers from analysis.warnings keyed by node_id.
    warnings_by_node: dict[str, list[str]] = {}
    for diag in analysis.warnings:
        if diag.node_id and diag.id:
            warnings_by_node.setdefault(diag.node_id, []).append(diag.id)

    lines = [header, ""]
    for row in visible:
        marker = f"(×{row.batch_size_estimated})" if row.is_batch and row.batch_size_estimated else ""
        inline_ids = warnings_by_node.get(row.node_path) or list(row.warnings)
        warning_marker = ", ".join(inline_ids)
        lines.append(
            f"  {row.node_path:30s} {marker:<6} model={row.model:35s} "
            f"tokens={row.input_tokens_estimated:>5}  "
            f"cacheable={row.cacheable_tokens_estimated:>5}  "
            f"ratio={row.cache_ratio_pct:>3}%  "
            f"src={row.data_source}  {warning_marker}"
        )
    if hidden_count > 0:
        lines.append("")
        lines.append(
            f"  Hidden: {hidden_count} nodes at ≥{_HIDDEN_RATIO_THRESHOLD}% projected "
            "cache ratio with no warnings (rerun with --all-rows)."
        )
    return "\n".join(lines)


def _select_visible_rows(
    rows: Iterable[PerCallRow],
    *,
    all_rows: bool,
    nodes_with_warnings: set[str],
) -> tuple[list[PerCallRow], int]:
    """Apply the default-hide-clean rule.

    Returns ``(visible_rows, hidden_count)``. Sorted: warnings first, then by
    ``input_tokens_estimated`` descending.
    """
    rows_list = list(rows)
    if all_rows:
        sorted_rows = sorted(rows_list, key=lambda r: -r.input_tokens_estimated)
        return sorted_rows, 0
    visible = [r for r in rows_list if _is_row_visible_by_default(r, nodes_with_warnings)]
    hidden = len(rows_list) - len(visible)
    sorted_visible = sorted(visible, key=lambda r: -r.input_tokens_estimated)
    return sorted_visible, hidden


def _is_row_visible_by_default(row: PerCallRow, nodes_with_warnings: set[str]) -> bool:
    """Per spec — show rows with warnings (inline OR analysis-wide) OR ratio < 80%."""
    if row.warnings or row.node_path in nodes_with_warnings:
        return True
    return row.cache_ratio_pct < _HIDDEN_RATIO_THRESHOLD


def _render_warnings(analysis: CacheAnalysis) -> str:
    if not analysis.warnings:
        return ""
    lines = ["## All warnings", ""]
    for diag in analysis.warnings:
        sev = {
            Severity.ERROR: "error",
            Severity.WARNING: "warning",
            Severity.INFO: "info",
        }.get(diag.severity, "")
        node_part = f"  {diag.node_id}" if diag.node_id else ""
        id_part = f"[{diag.id}]" if diag.id else ""
        lines.append(f"  {sev:8s} {id_part}{node_part}")
    return "\n".join(lines)


def _render_notes(analysis: CacheAnalysis) -> str:
    if not analysis.notes:
        return ""
    lines = ["## Notes", ""]
    for note in analysis.notes:
        lines.append(f"  · {note}")
    return "\n".join(lines)


__all__ = ["render_text"]
