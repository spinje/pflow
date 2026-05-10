"""Text rendering for ``pflow analyze-cache`` (default mode).

Implements spec § "Output Format — Text" with section ordering:

1. Header (workflow path, scale, confidence label — only when actionable).
2. Summary (cost tri-state — partial / unavailable rendering).
3. Blocking errors (rank-ordered) — must-fix validation findings.
4. Recommended actions (rank-ordered) — optimization opportunities.
5. Suggested ## Cache block(s) — greenfield-only.
6. Cross-workflow alignment (Tier 2) — only when findings exist.
7. Per-call cache report (default-hide-clean unless ``--all-rows``).
8. Notes (info notes appended in the analyzer's locked order).

Cost tri-state contract (Suggestion 26):

- All priced → ``~$2.18``.
- Partial → ``~$0.84 (partial — 2 of 23 nodes use unpriced models)``.
- All unavailable → ``unavailable`` (NEVER ``$0.00``).

Default-hide-clean rule: rows with ``cache_ratio_pct >= 80`` and no inline
warnings collapse into a single ``Hidden: N nodes ...`` line. ``--all-rows``
overrides.

CP4 changes (#16, #9, #7, #6+#13 — agent UX cleanup):

- Dropped the "All warnings" section. Recommended actions IS the canonical
  warnings view, sorted by impact. JSON output (``warnings[]``) keeps the
  full machine-readable list — agents who want raw access run ``--format=json``.
- Per-call token confidence is summarized once below the table instead of
  repeating analyzer-internal source names on every row. JSON keeps the
  granular 4-tier source for machine consumers.
- Per-call section header tells agents whether ratios reflect CURRENT state
  (greenfield: always 0%) or ACTUAL cache hit rate (steady-state: real data).
- ``Confidence: low_no_data`` header line is dropped (it duplicates the
  cost-section call-to-action). ``medium_from_memo`` / ``high_from_trace``
  labels stay — they carry actionable fidelity info.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping

from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_capabilities import get_min_cache_tokens

from .analyze import (
    AnalysisSummary,
    CacheAnalysis,
    CostDelta,
    PerCallRow,
    RecommendedAction,
    SubWorkflowRollup,
    SubWorkflowRollupEntry,
)

_HIDDEN_RATIO_THRESHOLD = 80

# Plain-English labels for ``ProjectionExclusion.reason``. Surfaced inline
# in the Summary block's "Excluded from analysis" line so a fresh agent
# reading the output can see WHY a node was excluded without learning
# the analyzer's internal vocabulary.
_EXCLUSION_REASON_LABELS: dict[str, str] = {
    "heterogeneous_model": "model varies per call",
    "unresolved_model": "model not resolved",
    "unpriced_model": "no pricing data for model",
    "missing_output_tokens": "output token count not in trace",
}


def render_text(analysis: CacheAnalysis, *, all_rows: bool = False) -> str:
    """Render the analyzer result as markdown-formatted text."""
    lines: list[str] = []
    lines.append(_render_header(analysis))
    lines.append(_render_summary(analysis))

    errors = _render_blocking_errors(analysis)
    if errors:
        lines.append(errors)

    other_errors = _render_other_blocking_errors(analysis, cache_blocking_present=bool(errors))
    if other_errors:
        lines.append(other_errors)

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

    drill = _render_sub_workflow_drill_in(analysis)
    if drill:
        lines.append(drill)

    # "## All warnings" section was removed entirely (CP4 #16 — see module
    # docstring). Recommended Actions IS the canonical warnings view, sorted
    # by impact. JSON consumers get the full ``warnings[]`` list via
    # ``--format=json``.

    notes = _render_notes(analysis)
    if notes:
        lines.append(notes)

    return "\n\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


_HETEROGENEOUS_MODEL_TAG = "model varies per batch item"


def _render_header(analysis: CacheAnalysis) -> str:
    """Render workflow path + scale, plus confidence WHEN it carries signal.

    Header shape — one concept per line so an agent can scan without
    parsing a single multi-fact run-on. ``_format_scale_line`` returns
    1-3 lines composing the workflow shape (count + invocation status +
    optional Models line + optional Heterogeneous line); ``_render_header``
    then appends Evidence, IR/settings divergence, sub-workflow breakdown,
    and confidence.

    Scale-line shapes (single-model stays inline; 2+ models break out):
      - 0 LLM nodes → ``0 LLM nodes``
      - 1 model    → ``7 LLM nodes using anthropic/claude-sonnet-4-5``
      - 2+ models  → ``7 LLM nodes`` + ``Models: anthropic/..., gemini/...``
      - No model   → ``7 LLM nodes`` + ``Models: not resolved (set settings.default_model)``
      - Any heterogeneous batch sub-workflow appends a ``Heterogeneous:`` line.

    ``Confidence: low_no_data`` is suppressed (the cost-section's
    call-to-action surfaces the same signal actionably). ``medium_from_memo``
    / ``high_from_trace`` stay — they carry coverage info that helps agents
    reason about how much to trust per-call numbers.
    """
    s = analysis.summary
    coverage = analysis.estimate_confidence_coverage
    label = analysis.estimate_confidence
    scale_lines = _format_scale_line(s)
    lines = [f"# Cache Analysis: {_workflow_filename(analysis.workflow_path)}"]
    display_path = _display_path_from_cwd(analysis.workflow_path)
    if display_path != _workflow_filename(analysis.workflow_path):
        lines.append(f"  File: {display_path}")
    lines.extend([
        "",
        f"  Workflow: {scale_lines[0]}",
        *(f"  {extra}" for extra in scale_lines[1:]),
    ])
    if s.evidence_scope == "truncated_trace_executed_subset":
        lines.append(
            f"  Evidence: trace truncated ({s.trace_llm_nodes_executed} of {s.trace_llm_nodes_static} LLM nodes executed)"
        )
    elif s.evidence_scope == "complete_trace":
        # Case A: workflow finished but some static nodes didn't execute
        # (conditional dispatch, e.g. classify→one-of-N branches). Tell
        # agents the trace IS complete and why per-call may show more rows
        # than the executed count.
        # ``max(0, ...)`` guards against future shape changes where
        # executed count could exceed static (e.g., loop recovery counted
        # per-visit while static is per-node) — current code maintains
        # static >= executed but the guard is cheap defense.
        unreached = max(0, s.trace_llm_nodes_static - s.trace_llm_nodes_executed)
        if unreached > 0:
            lines.append(
                f"  Evidence: complete trace ({s.trace_llm_nodes_executed} of {s.trace_llm_nodes_static} "
                f"LLM nodes executed; {unreached} not reached for these inputs)"
            )
        else:
            lines.append(f"  Evidence: complete trace ({s.trace_llm_nodes_executed} LLM nodes executed)")
    if s.observed_models_in_trace and s.ir_default_model and s.ir_default_model not in s.observed_models_in_trace:
        lines.append(f"  IR/settings declares: {s.ir_default_model} (overridden by trace evidence)")
    sub_line = _format_sub_workflow_breakdown_line(analysis)
    if sub_line:
        lines.append(f"  {sub_line}")
    if label in {"medium_from_memo", "high_from_trace"}:
        # Per DD#34 line 638 — append coverage detail.
        source_count = (
            coverage.get("trace", 0)
            if label == "high_from_trace"
            else coverage.get("memo", 0) + coverage.get("trace", 0)
        )
        lines.append(f"  Confidence: {label} ({source_count} of {coverage.get('total', 0)} nodes)")
    return "\n".join(lines)


def _llm_bearing_rollup_entries(
    rollup: SubWorkflowRollup,
) -> tuple[SubWorkflowRollupEntry, ...]:
    """Filter rollup entries to those with at least one LLM node.

    Workflows with ``llm_node_count == 0`` (e.g., MCP/shell-only orchestrators)
    have no per-call cache findings to surface; the drill-in command and
    breakdown-count both use this filter to keep sub-workflow signals aligned
    with what ``analyze-cache`` would actually report on each child.
    """
    return tuple(entry for entry in rollup.per_workflow if entry.llm_node_count > 0)


def _format_sub_workflow_breakdown_line(analysis: CacheAnalysis) -> str | None:
    """Return the per-workflow LLM-node breakdown parenthetical.

    Names of the child workflows aren't enumerated — they appear in
    ``## Per-call cache report`` headings and ``## Per-child analyze-cache
    commands`` block, so a CSV here is filler.
    """
    rollup = analysis.summary.sub_workflow_rollup
    if rollup is None:
        return None
    s = analysis.summary
    llm_bearing = _llm_bearing_rollup_entries(rollup)
    child_count = len(llm_bearing)
    workflow_word = "sub-workflow" if child_count == 1 else "sub-workflows"
    return (
        f"({s.root_llm_node_count} in {_workflow_filename(analysis.workflow_path)}, "
        f"{s.sub_workflow_llm_node_count} in {child_count} {workflow_word})"
    )


def _format_scale_line(s: AnalysisSummary) -> list[str]:
    """Render the workflow header lines describing scale, models, and heterogeneity.

    Returns 1-3 lines (no leading indent — caller adds it). Each line
    carries one concept so an agent can scan the header without parsing
    a single 5-fact run-on. Single-model workflows keep ``using X``
    inline; 2+ models break out to a dedicated ``Models:`` line; any
    heterogeneous batch (``model: ${item.model}``) breaks out to a
    ``Heterogeneous:`` line so it's findable everywhere.
    """
    node_count = s.total_llm_nodes_estimated
    nodes_word = "node" if node_count == 1 else "nodes"
    if node_count == 0:
        return ["0 LLM nodes"]

    invocation_suffix = _format_invocation_suffix(s)
    hetero_count = len(s.heterogeneous_model_node_paths)

    if hetero_count == node_count:
        # All-heterogeneous workflow — no homogeneous models to list.
        primary = f"{node_count} LLM {nodes_word}{invocation_suffix}"
    elif len(s.models_in_use) == 1:
        primary = f"{node_count} LLM {nodes_word}{invocation_suffix} using {s.models_in_use[0]}"
    else:
        # 2+ models OR no model resolved (with at least one non-heterogeneous
        # node). Both cases break out to a dedicated ``Models:`` line below
        # so the header reads consistently across cases.
        primary = f"{node_count} LLM {nodes_word}{invocation_suffix}"

    lines = [primary]
    if len(s.models_in_use) >= 2:
        lines.append(f"Models: {', '.join(s.models_in_use)}")
    elif not s.models_in_use and hetero_count != node_count:
        lines.append("Models: not resolved (set settings.default_model)")

    hetero_line = _format_heterogeneous_line(s.heterogeneous_model_node_paths)
    if hetero_line:
        lines.append(hetero_line)
    return lines


def _format_heterogeneous_line(paths: tuple[str, ...]) -> str | None:
    """Return the ``Heterogeneous:`` header line, or None when no
    heterogeneous batch sub-workflows exist.

    A single ``', '.join`` covers 1-vs-N — the comma-separated names
    speak for themselves; no pluralization branching needed.
    """
    if not paths:
        return None
    return f"Heterogeneous: {', '.join(paths)} ({_HETEROGENEOUS_MODEL_TAG})"


def _format_invocation_suffix(s: AnalysisSummary) -> str:
    if s.total_llm_invocations_estimated is not None:
        if s.total_llm_invocations_estimated == s.total_llm_nodes_estimated:
            return ""
        return f", ~{s.total_llm_invocations_estimated} invocations"
    dynamic_count = s.dynamic_batch_node_count
    if dynamic_count == 0:
        return ""
    word = "node" if dynamic_count == 1 else "nodes"
    return f", invocation count unavailable ({dynamic_count} dynamic batch {word})"


def _render_cost_block(s: AnalysisSummary) -> list[str]:
    """Compose the cost lines from atomic primitives by context.

    Three contexts, each with a distinct line set so agents skimming see
    only what's load-bearing:

    1. **Trace + workflow paid something** (``actually_paid_usd is not None``):
       show ``Actually paid (trace): $X``, ``Cost without caching: $Y``,
       ``Cost on rerun (within TTL): $Z``. The actual figure is the truth;
       the no-cache hypothetical answers "what would removing caching cost?";
       the rerun answers "what does steady-state cost?"
    2. **Greenfield with declared cache** (``first_run_delta`` is displayable):
       show
       ``Cost without caching: $X``, ``Cost on first run (with cache): $Y``,
       ``Cost on rerun (within TTL): $Z``. The first two differ; the agent
       sees the savings.
    3. **Greenfield without declared cache** (no caching means
       no_cache_hypothetical equals first_run_with_cache exactly): show
       ``Cost per run: $X`` once. Rerun is the same number.
    """
    if s.actually_paid_usd is not None:
        return _render_trace_cost_lines(s)
    if s.first_run_delta.kind in {"savings", "cost_increase"}:
        return _render_greenfield_with_cache_lines(s)
    return _render_greenfield_no_cache_lines(s)


def _render_trace_cost_lines(s: AnalysisSummary) -> list[str]:
    """Cost lines when a trace contributed actual costs."""
    tier = s.actually_paid_tier.value
    actually_paid_str = _format_cost(
        s.actually_paid_usd,
        tier == "trace_partial",
        s.unavailable_models,
        tier_annotation=tier,
    )
    # ``(partial)`` on the no_cache / rerun projections is redundant when a
    # structural signal already names the cohort gap: ``Excluded from analysis:``
    # (complete-trace mode) names the excluded rows in plain English, and the
    # ``(executed)`` label suffix (truncated branch) signals "executed subset
    # only". Suppress the parenthetical in those cases — keep it only for the
    # rare edge where ``partial_cost_usd`` is set without either signal.
    projection_partial_marker = (
        s.partial_cost_usd and not s.projection_exclusions and s.evidence_scope != "truncated_trace_executed_subset"
    )
    no_cache_str = _format_cost(s.no_cache_hypothetical_usd, projection_partial_marker, s.unavailable_models)
    rerun_str = _format_cost(s.rerun_within_ttl_hypothetical_usd, projection_partial_marker, s.unavailable_models)
    if s.evidence_scope == "truncated_trace_executed_subset":
        return [
            f"  Actually paid (executed trace):       {actually_paid_str}",
            f"  Cost without caching (executed):      {no_cache_str}",
            f"  Cost on rerun (executed, within TTL): {rerun_str}",
        ]
    # Label is bare ``Actually paid:`` — the value already carries the tier
    # annotation ``(trace)`` or ``(trace_partial)`` via ``_format_cost``, so
    # repeating ``(trace)`` on the label is redundant. Truncated branch above
    # keeps ``(executed trace)`` because "executed" carries unique signal.
    lines = [f"  Actually paid:               {actually_paid_str}"]
    excluded_line = _format_excluded_from_analysis_line(s)
    if excluded_line is not None:
        lines.append(excluded_line)
    lines.append(f"  Cost without caching:        {no_cache_str}")
    lines.append(f"  Cost on rerun (within TTL):  {rerun_str}")
    return lines


def _format_excluded_from_analysis_line(s: AnalysisSummary) -> str | None:
    """Render the ``Excluded from analysis: ~$X (node: reason, ...)`` line.

    Surfaces nodes that contributed to ``actually_paid_usd`` but were dropped
    from the projection cohort (heterogeneous models, unpriced, etc.). With
    this line visible, a fresh agent doing ``actually_paid - excluded``
    arrives at the cohort the savings are measured over without needing
    analyzer-internal vocabulary.

    The ``~$X`` total is shown when at least one excluded row carries a
    trace-recorded cost; if every exclusion's ``actual_cost_usd`` is ``None``
    (e.g. greenfield mode, or an ``unpriced_model`` exclusion whose trace
    event also lacks a cost), the dollar figure is omitted but the node
    list and reason still render so the agent knows WHY the projection
    cohort excludes them.

    Returns ``None`` only when there are no exclusions at all.
    """
    if not s.projection_exclusions:
        return None
    sorted_exclusions = sorted(
        s.projection_exclusions,
        key=lambda e: (e.workflow_path or "", e.node_path),
    )
    parts = [f"{e.node_path}: {_EXCLUSION_REASON_LABELS.get(e.reason, e.reason)}" for e in sorted_exclusions]
    explanation = ", ".join(parts)
    excluded_total = sum((e.actual_cost_usd or 0.0) for e in s.projection_exclusions)
    if excluded_total > 0:
        amount = _format_dollar_amount(excluded_total)
        return f"  Excluded from analysis:      {amount} ({explanation})"
    return f"  Excluded from analysis:      {explanation}"


def _render_greenfield_with_cache_lines(s: AnalysisSummary) -> list[str]:
    """Cost lines for greenfield workflows that declare ``prompt_cache:``."""
    # ``(partial)`` on the projection lines is redundant when the
    # ``(projected subset)`` label suffix (added below for the
    # ``projection_exclusions`` case) already carries the cohort signal.
    projection_partial_marker = s.partial_cost_usd and not s.projection_exclusions
    no_cache_str = _format_cost(s.no_cache_hypothetical_usd, projection_partial_marker, s.unavailable_models)
    first_run_str = _format_cost(
        s.first_run_with_cache_hypothetical_usd, projection_partial_marker, s.unavailable_models
    )
    rerun_str = _format_cost(s.rerun_within_ttl_hypothetical_usd, projection_partial_marker, s.unavailable_models)
    no_cache_label = "Cost without caching (projected subset)" if s.projection_exclusions else "Cost without caching"
    first_run_label = (
        "Cost on first run (cache, projected subset)" if s.projection_exclusions else "Cost on first run (cache)"
    )
    rerun_label = (
        "Cost on rerun (within TTL, projected subset)" if s.projection_exclusions else "Cost on rerun (within TTL)"
    )
    return [
        f"  {no_cache_label}:        {no_cache_str}",
        f"  {first_run_label}:   {first_run_str}",
        f"  {rerun_label}:  {rerun_str}",
    ]


def _render_greenfield_no_cache_lines(s: AnalysisSummary) -> list[str]:
    """Cost lines for greenfield workflows with no declared caching.

    All three projection atoms collapse to the same number when no row has
    ``prompt_cache:`` (cacheable=0, so write/read rates don't apply).
    Rendering one line is honest; three identical lines would be noise.
    """
    cost_str = _format_cost(s.no_cache_hypothetical_usd, s.partial_cost_usd, s.unavailable_models)
    return [f"  Cost per run:                {cost_str}"]


def _is_post_run_greenfield_with_savings(s: AnalysisSummary) -> bool:
    """Greenfield path where pricing data exists + savings can be computed but
    output tokens aren't available for absolute figures."""
    return (
        s.actually_paid_usd is None
        and s.no_cache_hypothetical_usd is None
        and s.first_run_delta.kind in {"savings", "cost_increase"}
    )


def _all_cost_atoms_unavailable(s: AnalysisSummary) -> bool:
    """True when no cost atom carries a real number.

    Used to dispatch the "Cost data unavailable" message — the four
    sub-cases (no LLM nodes / all heterogeneous / no model resolved /
    no run history) each get a distinct hint.
    """
    return (
        s.actually_paid_usd is None
        and s.no_cache_hypothetical_usd is None
        and s.first_run_with_cache_hypothetical_usd is None
        and s.rerun_within_ttl_hypothetical_usd is None
    )


def _render_summary(analysis: CacheAnalysis) -> str:
    s = analysis.summary
    summary_lines = ["## Summary", ""]
    if s.evidence_scope == "truncated_trace_executed_subset":
        summary_lines.append("  Trace-backed costs below cover executed nodes only.")
    summary_lines.extend(_render_cost_block(s))

    delta_lines = _render_summary_deltas(s)
    if delta_lines:
        summary_lines.extend(delta_lines)

    _append_summary_counts(summary_lines, analysis)

    if s.partial_cost_usd and s.unavailable_models:
        models_csv = _format_unavailable_models(analysis)
        summary_lines.append("")
        summary_lines.append(f"  Unpriced models: {models_csv}")
    elif _is_post_run_greenfield_with_savings(s):
        # Pricing data exists + savings opportunity exists, but output token
        # counts are unavailable for absolute figures. Tell the agent how to
        # light up real cost figures.
        summary_lines.append("")
        summary_lines.append(
            "  Absolute cost figures need a prior run. Run the workflow once, then "
            "re-run analyze-cache for real cost figures and cacheable projections."
        )
        _append_suggested_run_command(summary_lines, s, workflow_path=analysis.workflow_path)
    elif _all_cost_atoms_unavailable(s) and not s.unavailable_models:
        _append_unavailable_cost_message(summary_lines, s, workflow_path=analysis.workflow_path)
    return "\n".join(summary_lines)


def _append_suggested_run_command(summary_lines: list[str], s: AnalysisSummary, *, workflow_path: str) -> None:
    """Emit the paste-ready ``Suggested:`` line when a runnable command exists.

    Shared by the two unavailable-cost branches (priced-with-savings and
    cost-data-unavailable-run-once) so both surface the same agent-actionable
    next step. ``suggested_run_command`` is ``None`` for inline IR /
    ``ir-hash:`` lookup keys.
    """
    if s.suggested_run_command:
        summary_lines.append(f"  Suggested:  {_display_run_command(s.suggested_run_command, workflow_path)}")


def _append_unavailable_cost_message(summary_lines: list[str], s: AnalysisSummary, *, workflow_path: str) -> None:
    """Render the four "Cost data unavailable" sub-branches.

    The branch fires on four distinct sub-cases; conflating them produced the
    lyrics-generator bug where ``Cost data unavailable: workflow has no LLM
    nodes`` rendered above a per-call table listing 2 LLM nodes:

    1. Zero LLM nodes total (rare; e.g. parent workflow that only delegates
       to sub-workflows).
    2. ALL LLM nodes are heterogeneous (``model: ${item.X}`` from
       heterogeneous batch sub-workflows). The "set settings.default_model"
       hint would be wrong here — model resolution isn't the problem;
       pricing per-batch-item models can't be aggregated as one model.
    3. LLM nodes exist but no model could be resolved (no per-node
       ``model:``, ``get_default_workflow_model()`` returned None).
    4. LLM nodes with priced models but no run history yet (greenfield
       without shared context — no opportunity figure to show).
    """
    summary_lines.append("")
    if s.total_llm_nodes_estimated == 0:
        summary_lines.append("  Cost data unavailable: workflow has no LLM nodes.")
    elif s.heterogeneous_model_node_count == s.total_llm_nodes_estimated:
        # Stage C.1: gate ahead of the "no model resolved" branch.
        summary_lines.append("  Cost data unavailable: all LLM nodes use models that vary per batch item.")
    elif not s.models_in_use:
        summary_lines.append(
            "  Cost data unavailable: no model resolved for LLM nodes "
            "(set settings.default_model or add per-node `- model:`)."
        )
    else:
        summary_lines.append("  Cost data unavailable: run the workflow once for cost figures.")
        _append_suggested_run_command(summary_lines, s, workflow_path=workflow_path)


def _append_summary_counts(summary_lines: list[str], analysis: CacheAnalysis) -> None:
    # Counts are section-mapped (not severity-keyed): the headline must
    # match what `## Recommended actions` and `## Sub-workflow boundaries`
    # actually render so an agent skimming the summary doesn't hunt for
    # entries that don't exist. Severity counts stay in JSON
    # (``warnings_count``/``info_count`` on AnalysisSummary) for machine
    # consumers.
    from .view_helpers import count_rendered_findings

    s = analysis.summary
    rec_count, bnd_count = count_rendered_findings(list(analysis.warnings))

    has_blocking = s.blocking_errors > 0
    has_opportunities = rec_count > 0 or bnd_count > 0
    has_truncation_note = s.evidence_scope == "truncated_trace_executed_subset"

    if has_blocking or has_opportunities or has_truncation_note:
        summary_lines.append("")
    if has_blocking:
        error_word = "error" if s.blocking_errors == 1 else "errors"
        summary_lines.append(f"  {s.blocking_errors} {error_word} blocking")
    if has_opportunities:
        parts: list[str] = []
        if rec_count > 0:
            word = "recommended action" if rec_count == 1 else "recommended actions"
            parts.append(f"{rec_count} {word}")
        if bnd_count > 0:
            word = "cross-workflow boundary finding" if bnd_count == 1 else "cross-workflow boundary findings"
            parts.append(f"{bnd_count} {word}")
        summary_lines.append(f"  {' + '.join(parts)}")
    if has_truncation_note:
        summary_lines.append(
            "  Cost-projection findings suppressed because the trace is truncated (workflow did not finish)."
        )


def _render_summary_deltas(s: AnalysisSummary) -> list[str]:
    """Render savings deltas for the Summary block.

    Trace mode shows the measured savings as the headline plus the
    steady-state rerun projection. The first-run-with-cache projection is
    suppressed when actual data exists: the projection models neither memo
    cache hits nor provider implicit caching, so it can be off by an order
    of magnitude and visually compete with the actual figure (BASELINE-AUDIT
    L-3). Greenfield mode only has projections, so both are rendered.
    """
    if s.evidence_scope in {"complete_trace", "truncated_trace_executed_subset"}:
        return _render_trace_deltas(s)
    return _render_greenfield_deltas(s)


def _render_trace_deltas(s: AnalysisSummary) -> list[str]:
    lines: list[str] = []
    actual = _format_delta(s.actual_vs_no_cache_delta, label="vs no-cache")
    actual_label = "Actual savings (this run):"
    if actual:
        lines.append(f"  {actual_label:29s} {actual}")
    elif s.actual_vs_no_cache_delta.unavailable_reason == "projection_exclusions" and s.projection_exclusions:
        # Excluded nodes are surfaced via the ``Excluded from analysis`` line
        # in the cost block above; here we just signal that savings can't be
        # computed for the remaining cohort.
        lines.append(f"  {actual_label:29s} unavailable")
    rerun = _format_delta(s.rerun_delta, label="on rerun")
    if rerun:
        lines.append(f"  {'Rerun delta (projected):':29s} {rerun}")
    return lines


def _render_greenfield_deltas(s: AnalysisSummary) -> list[str]:
    lines: list[str] = []
    first = _format_delta(s.first_run_delta, label="on first run")
    if first:
        lines.append(f"  {'First-run delta:':29s} {first}")
    rerun = _format_delta(s.rerun_delta, label="on rerun")
    if rerun:
        lines.append(f"  {'Rerun delta:':29s} {rerun}")
    return lines


_BASELINE_LABELS: dict[str, str] = {
    "no_cache_hypothetical_usd": "no-cache cost",
}


def _format_delta(delta: CostDelta, *, label: str) -> str:
    if delta.kind == "unavailable":
        return ""
    if delta.kind == "break_even":
        return "no meaningful cost change"
    if delta.amount_usd is None:
        return ""
    amount = _format_dollar_amount(delta.amount_usd)
    baseline_label = _BASELINE_LABELS.get(delta.baseline, "baseline")
    pct = f", {delta.pct_of_baseline}% of {baseline_label}" if delta.pct_of_baseline is not None else ""
    # Note: ``delta.excluded_nodes`` is preserved on the dataclass and emitted
    # in JSON output (``render_json.py``). The text renderer surfaces excluded
    # nodes via the ``Excluded from analysis`` line in the cost block instead
    # so the cohort is established once, near the dollar figures it explains.
    if delta.kind == "savings":
        return f"saves {amount}/run {label}{pct}"
    return f"adds {amount} {label}{pct}"


def _format_unavailable_models(analysis: CacheAnalysis) -> str:
    by_workflow = analysis.summary.unavailable_models_by_workflow or {}
    if not by_workflow:
        return ", ".join(analysis.summary.unavailable_models)
    parts: list[str] = []
    for workflow_path, models in sorted(by_workflow.items(), key=lambda item: str(item[0])):
        workflow_short = _workflow_short_name(str(workflow_path or analysis.workflow_path))
        for model in models:
            suffix = f" (in {workflow_short})" if workflow_path != analysis.workflow_path else ""
            parts.append(f"{model}{suffix}")
    return ", ".join(parts)


def _format_cost(
    value: float | None,
    partial: bool,
    unavailable_models: tuple[str, ...],
    *,
    tier_annotation: str = "",
) -> str:
    """Tri-state cost rendering per the F2 contract.

    Stage C.2: when exactly ONE model is unpriced, name it directly so the
    agent doesn't have to scan ``models_in_use`` to find the culprit. The
    plural-count phrasing remains for N>1.

    Optional ``tier_annotation`` (e.g. ``"trace"``, ``"trace_partial"``)
    appended in parentheses so the agent sees the confidence tier when
    rendering ``actually_paid_usd``. Empty string skips the suffix
    (the no_cache / first_run / rerun projection lines stay unannotated —
    they're hypotheticals; the tier-confidence concept doesn't apply).
    """
    if value is None:
        if len(unavailable_models) == 1:
            return f"unavailable ({unavailable_models[0]} lacks pricing data)"
        if unavailable_models:
            return f"unavailable (all {len(unavailable_models)} models lack pricing data)"
        return "unavailable"
    annotation = f" ({tier_annotation})" if tier_annotation else ""
    amount = _format_dollar_amount(value)
    if partial:
        # Partial — caller must already have appended " (partial — N of M ...)" to value.
        # We don't have N/M here, so just mark as partial.
        return f"{amount} (partial){annotation}"
    return f"{amount}{annotation}"


def _format_dollar_amount(value: float) -> str:
    """Format a USD amount with adaptive precision.

    Track A's accuracy surfaces sub-cent costs that the prior ``:.2f``
    format silently rounded to ``$0.00`` (Gemini Flash, cached calls,
    Haiku). Adaptive precision keeps the common ``~$2.18`` shape for cents+
    while showing real digits for sub-cent.

    - ``value >= 0.01``: ``~$2.18`` / ``~$0.42`` (2 decimals — unchanged).
    - ``0.0001 <= value < 0.01``: ``~$0.0042`` (4 decimals — sub-cent
      precision, agent reads the actual paid amount).
    - ``0 < value < 0.0001``: ``~<$0.0001`` (smaller than displayable,
      effectively free).
    - ``value == 0``: ``~$0.00`` (genuine zero — e.g. cached event,
      reads cleanly with a ``(trace)`` suffix).
    """
    if value >= 0.01 or value == 0:
        return f"~${value:.2f}"
    if value >= 0.0001:
        return f"~${value:.4f}"
    return "~<$0.0001"


def _render_blocking_errors(analysis: CacheAnalysis) -> str:
    """Render must-fix cache-domain findings separately from optimization opportunities.

    B-9 split: cache-domain ERRORs (cache.*, llm.thinking-temperature-mismatch,
    or context.path under cache./prompt_cache) render here under
    ``## Cache blocking errors``. Non-cache validator ERRORs surface via
    ``_render_other_blocking_errors`` so agents distinguish caching work from
    env-config issues.
    """
    from .view_helpers import build_blocking_errors

    actions = build_blocking_errors(list(analysis.warnings))
    if not actions:
        return ""
    return _render_action_list(
        header="## Cache blocking errors (must fix before save and run)",
        intro="",
        actions=actions,
        workflow_path=analysis.workflow_path,
        show_savings=False,
        show_warning_id=True,
    )


def _render_other_blocking_errors(analysis: CacheAnalysis, *, cache_blocking_present: bool) -> str:
    """Render non-cache must-fix findings (B-9 fix).

    Workflow-blocking errors tangential to prompt caching (unknown node types,
    schema violations, LLM param errors). Renders AFTER cache-domain blocking
    errors so caching work surfaces first; agents skimming for caching
    fixes don't conflate env-config issues with caching findings.

    The ``Other`` qualifier is purely relational — it only reads as
    standalone-coherent when a sibling ``## Cache blocking errors`` section
    renders alongside. When cache-domain errors are absent, drop the qualifier
    and emit ``## Blocking errors`` so the heading reads complete on its own.
    """
    from .view_helpers import build_other_blocking_errors

    actions = build_other_blocking_errors(list(analysis.warnings))
    if not actions:
        return ""
    header = "## Other blocking errors (surfaced for awareness)" if cache_blocking_present else "## Blocking errors"
    return _render_action_list(
        header=header,
        intro="",
        actions=actions,
        workflow_path=analysis.workflow_path,
        show_savings=False,
        show_warning_id=True,
    )


def _render_recommended_actions(analysis: CacheAnalysis) -> str:
    """Render optimization findings as action headline + scope + reason.

    A-4: header carries the inline rendered count — ``(N, ordered by impact)``
    or ``(N)`` — so the agent can cross-anchor against the headline summary
    while skim-reading.

    B-6: ``(ordered by impact)`` qualifier only holds when at least one
    action has a positive savings figure. Greenfield without resolved
    models (and trace-mode workflows where every projection is unavailable)
    drop the qualifier — there's no impact to order by.
    """
    from .view_helpers import build_recommended_actions

    actions = build_recommended_actions(list(analysis.warnings))
    if not actions:
        return ""
    has_orderable_savings = any(a.estimated_savings_usd is not None and a.estimated_savings_usd > 0 for a in actions)
    count = len(actions)
    if has_orderable_savings:
        header = f"## Recommended actions ({count}, ordered by impact)"
    else:
        header = f"## Recommended actions ({count})"
    return _render_action_list(
        header=header,
        intro=(
            "Each item below is a cache-optimization opportunity for this workflow.\n"
            "Declared values are sent once and reused at 0.1× input cost."
        ),
        actions=actions,
        workflow_path=analysis.workflow_path,
        show_savings=True,
        show_warning_id=False,
    )


def _render_action_list(
    *,
    header: str,
    intro: str,
    actions: list[RecommendedAction],
    workflow_path: str,
    show_savings: bool,
    show_warning_id: bool,
) -> str:
    """Render ranked action rows with optional savings column.

    Stage-1 final UX pass: dropped the ``[cache.X]`` bracket prefix (visually
    coded category names as error codes — top-10% codebases like mypy/ruff
    don't bracket long namespaced descriptors). Headline leads from the
    catalog's ``headline_template``; scope is on its own line; descriptive
    message is indented underneath as the reason. Blocking errors still show
    their diagnostic ID inline so validator failures remain searchable across
    CLI, JSON, docs, and tests.
    """
    lines = [header, ""]
    if intro:
        for intro_line in intro.splitlines():
            lines.append(f"  {intro_line}")
        lines.append("")
    for action in actions:
        # Headline + savings on the rank line. Falls back to message when no
        # catalog headline (defense-in-depth for non-catalog diagnostics).
        title = _format_action_title(action, show_warning_id=show_warning_id)
        if show_savings:
            savings = _format_action_savings(action)
            lines.append(f"  {action.rank}. {title}{_pad_savings(title, savings)}{savings}")
        else:
            lines.append(f"  {action.rank}. {title}")
        if action.node_id:
            scope_suffix = ""
            if action.scope_workflow and action.scope_workflow != workflow_path:
                scope_suffix = f" in {_short_workflow_label(action.scope_workflow)}"
            lines.append(f"     {action.node_id}{scope_suffix}")
        elif action.scope_workflow:
            # Workflow-level finding (e.g. shared-context spanning N nodes in one
            # file). Without this line the scope would be absent and findings
            # would render indistinguishable from per-node ones (the GH #2
            # surface). Basename keeps the line short.
            lines.append(f"     {_short_workflow_label(action.scope_workflow)}")
        # Reason paragraph — only rendered when distinct from the rendered
        # title. When `headline` is None (un-catalog-IDed errors), the title
        # falls back to `message` via `_format_action_title`; checking against
        # `title` (not `headline`) closes the dedup gap that doubled blocking-
        # error lines.
        if action.message and action.message != title:
            message = _replace_action_scope_in_prose(action.message, action, workflow_path)
            lines.extend(_indent_message(message, prefix="     "))
        lines.extend(_format_action_suggestions(action, workflow_path=workflow_path))
        lines.append("")
    # Drop trailing blank.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _format_action_suggestions(action: RecommendedAction, *, workflow_path: str) -> list[str]:
    return [
        f"     → {_replace_action_scope_as_edit_target(suggestion, action, workflow_path)}"
        for suggestion in action.suggestions
    ]


def _format_action_title(action: RecommendedAction, *, show_warning_id: bool) -> str:
    title = action.headline or action.message or action.warning_id
    if show_warning_id and action.warning_id:
        return f"{title} (`{action.warning_id}`)"
    return title


def _pad_savings(title: str, savings: str) -> str:
    """Right-align savings so the rank line reads as a column.

    Target column at 70; clamp to a minimum 2-space gap when the title is
    long. Mirrors the canonical mode-1 example in the spec where savings
    sit at a stable right column.
    """
    target = 70
    needed = target - len(title) - 2  # 2-char minimum gap before savings
    if needed < 2:
        return "  "
    return " " * needed


def _indent_message(message: str, *, prefix: str) -> list[str]:
    """Indent each line of a multi-line message under a recommendations bullet.

    Long messages render as multiple lines; the prefix keeps them visually
    aligned with the rank line above.
    """
    return [f"{prefix}{line}" for line in message.splitlines() if line.strip()]


def _replace_action_scope_in_prose(text: str, action: RecommendedAction, workflow_path: str) -> str:
    if not action.scope_workflow:
        return text
    return text.replace(action.scope_workflow, _workflow_filename(action.scope_workflow or workflow_path))


def _replace_action_scope_as_edit_target(text: str, action: RecommendedAction, workflow_path: str) -> str:
    if not action.scope_workflow:
        return text
    return text.replace(
        action.scope_workflow, _display_edit_target(action.scope_workflow, root_workflow_path=workflow_path)
    )


def _short_workflow_label(path: str) -> str:
    """Render a workflow path as a short label for the recommended-actions section.

    Filesystem paths get their basename; non-path identifiers (e.g.
    ``"<inline>"``, ``"ir-hash:<md5>"``) pass through as-is.
    """
    if "/" in path:
        return path.rsplit("/", 1)[-1] or path
    return path


def _display_path_from_cwd(path: str) -> str:
    """Return a stable human-facing path relative to the current directory.

    Canonical paths stay in the analyzer model and JSON; text output uses this
    helper so agents see repository-relative locations instead of long absolute
    machine paths. If the path is outside the current working directory, keep it
    unchanged to avoid misleading ``../../../`` paths.
    """
    if not path or path.startswith("ir-hash:") or "/" not in path:
        return path
    if not os.path.isabs(path):
        return path
    try:
        rel = os.path.relpath(path, os.getcwd())
    except ValueError:
        return path
    if rel == "." or rel.startswith(".."):
        return path
    return rel


def _display_edit_target(path: str, *, root_workflow_path: str) -> str:
    """Return a compact path for prose that points at a file to edit."""
    if not path or path.startswith("ir-hash:") or "/" not in path:
        return path
    if path == root_workflow_path:
        return _workflow_filename(path)

    root_dir = os.path.dirname(root_workflow_path)
    if root_dir:
        try:
            rel = os.path.relpath(path, root_dir)
        except ValueError:
            rel = ""
        if rel and rel != "." and not rel.startswith(".."):
            return rel
    return _display_path_from_cwd(path)


def _display_run_command(command: str, workflow_path: str) -> str:
    """Shorten the workflow path in a generated ``pflow run`` command."""
    prefix = "pflow run "
    if not command.startswith(prefix):
        return command
    rest = command[len(prefix) :]
    command_path, sep, args = rest.partition(" ")
    if not command_path:
        command_path = workflow_path
    display_path = _display_path_from_cwd(command_path)
    return f"{prefix}{display_path}{sep}{args}" if sep else f"{prefix}{display_path}"


def _shorten_paths_in_prose(text: str, paths: Iterable[str | None]) -> str:
    replacements = {
        path: _workflow_filename(path) for path in paths if path and "/" in path and not path.startswith("ir-hash:")
    }
    for path in sorted(replacements, key=len, reverse=True):
        text = text.replace(path, replacements[path])
    return text


def _analysis_workflow_paths(analysis: CacheAnalysis) -> set[str]:
    paths = {analysis.workflow_path}
    paths.update(row.workflow_path for row in analysis.per_call if row.workflow_path)
    rollup = analysis.summary.sub_workflow_rollup
    if rollup is not None:
        paths.update(entry.workflow_path for entry in rollup.per_workflow)
    for diag in analysis.warnings:
        context = diag.context or {}
        for key in ("affected_workflow", "parent_workflow", "child_workflow", "trace_path"):
            value = context.get(key)
            if isinstance(value, str):
                paths.add(value)
    if analysis.trace_path:
        paths.add(analysis.trace_path)
    return paths


def _format_savings_usd(value: float | None) -> str:
    """Tri-state savings rendering with adaptive sub-cent precision.

    Mirrors ``_format_dollar_amount``'s precision tiers so Gemini-shaped
    sub-cent savings render honestly instead of collapsing to
    ``"savings unavailable"``:

    - ``None`` → ``"savings unavailable"`` (genuinely unknown).
    - ``< $0.0001`` → ``"savings unavailable"`` (below display precision —
      effectively zero). NOT rendered as ``-$0.0000/run`` which would
      imply "we computed it, it's zero" — same Bug D tri-state contract.
    - ``$0.0001 ≤ value < $0.01`` → ``"-$0.0012/run"`` (4 decimals).
    - ``≥ $0.01`` → ``"-$0.42/run"`` (2 decimals, common case).

    Pre-fix the cutoff was ``< $0.005 → "savings unavailable"``, which
    conflated "too small to display precisely with 2 decimals" with
    "too small to compute". Agents on Gemini-shaped workflows saw
    "savings unavailable" for every real recommendation despite the
    JSON carrying real ``estimated_savings_usd`` numbers.
    """
    if value is None or value < 0.0001:
        return "savings unavailable"
    if value < 0.01:
        return f"saves ~${value:.4f}/run"
    return f"saves ~${value:.2f}/run"


def _format_action_savings(action: RecommendedAction) -> str:
    if action.warning_id != "cache.batch-prewarm-recommended":
        return _format_savings_usd(action.estimated_savings_usd)
    value = action.estimated_savings_usd
    if value is None or value < 0.0001:
        return "savings unavailable"
    if value < 0.01:
        return f"saves ~${value:.4f}/workflow run"
    return f"saves ~${value:.2f}/workflow run"


def _render_suggested_blocks(analysis: CacheAnalysis) -> str:
    if not analysis.suggested_blocks:
        return ""
    chunks = []
    for block in analysis.suggested_blocks:
        chunks.append(f"## Suggested ## Cache block — {block.target_file}")
        chunks.append("")
        chunks.append("  Paste between ## Inputs and ## Steps. The labels above each `${var}` are")
        chunks.append("  auto-generated starters — replace each with a 1-2 sentence description")
        chunks.append("  of what that value is in your workflow's domain. The LLM reads this")
        chunks.append("  prose right before the value, so a clearer label helps the LLM")
        chunks.append("  understand what it's looking at.")
        chunks.append("  `ttl` accepts only `5m` or `1h`.")
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
            chunks.append("  Per-node `prompt_cache:` declarations")
            chunks.append("")
            chunks.append("  Add to each node's params. Order MUST match the ## Cache block above —")
            chunks.append("  pflow rejects mismatched orders as `cache.order-mismatch` ERROR.")
            chunks.append("")
            for node_id, assignment in block.per_node_assignments.items():
                chunks.append(f"  ### {node_id}")
                chunks.append(f"  - prompt_cache: [{', '.join(assignment)}]")
                chunks.append(_format_threshold_line(block.per_node_thresholds.get(node_id) or {}))
                cleanup_refs = block.prompt_body_cleanup.get(node_id) or []
                if cleanup_refs:
                    refs_csv = ", ".join(f"${{{ref}}}" for ref in cleanup_refs)
                    chunks.append(
                        f"  - also remove from prompt body: {refs_csv}    # cached values shouldn't appear inline"
                    )
                chunks.append("")
    # Drop trailing blank line.
    while chunks and chunks[-1] == "":
        chunks.pop()
    return "\n".join(chunks)


def _format_threshold_line(threshold_info: Mapping[str, object]) -> str:
    # Rendered as a `#` comment so agents copy-pasting the suggested block don't
    # accidentally include a `- threshold:` line — pflow rejects it as an unknown
    # node parameter. The leading `#` clearly signals "informational, not part of
    # the paste-target."
    #
    # Dispatch on ``model_state`` (typed discriminator) per Task 159 PR #378
    # review (#4). Human-readable labels (``<varies>``, ``<unknown>``) only
    # appear in rendered text — JSON consumers see ``model: null`` + the
    # discriminator, so they don't need to special-case sentinel strings.
    status = threshold_info.get("meets_threshold")
    total = threshold_info.get("total_tokens")
    min_tokens = threshold_info.get("min_tokens")
    model_state = threshold_info.get("model_state", "unknown")
    model_label = threshold_info.get("model") or _label_for_model_state(model_state)
    if status is True:
        return f"  # threshold: {total} tokens / {min_tokens} ({model_label}) ✓"
    if status is False:
        return (
            f"  # threshold: {total} tokens / {min_tokens} ({model_label}) ⚠ BELOW THRESHOLD — "
            "cache will not fire as suggested"
        )
    if status is None and model_state == "heterogeneous":
        return "  # threshold: varies per item (heterogeneous model)"
    if status is None:
        return "  # threshold: unable to estimate (no run data; first run will populate)"
    return "  # threshold: <unavailable>"


def _label_for_model_state(model_state: object) -> str:
    """Human-readable label for ``model_state`` discriminator values."""
    if model_state == "heterogeneous":
        return "<varies>"
    return "<unknown>"


def _render_cross_workflow(analysis: CacheAnalysis) -> str:
    """Render the "Sub-workflow boundaries" section.

    Renames are source-deduped: each unique
    ``(parent_workflow, parent_value_expr, child_input_name)`` triple becomes
    one entry that lists its consumer children. Multiple consumers of the
    same logical rename (e.g. one parent value passed to N batch children
    under the same input name) collapse to a single "fix at source"
    recommendation. Prose-mismatches stay 1-per-finding (different schema —
    keyed by ``chunk_name``); they render in a parent-grouped sub-section
    after the renames.

    Cross-boundary value-flow opportunities surface in Recommended actions
    only (filtered by ``view_helpers._CROSS_WORKFLOW_ALIGNMENT_IDS``).
    """
    from .view_helpers import group_renames_by_parent

    rename_detections = [d for d in analysis.warnings if d.id == "cache.cross-workflow-rename-detected"]
    prose_mismatches = [d for d in analysis.warnings if d.id == "cache.cross-workflow-prose-mismatch"]
    if not (rename_detections or prose_mismatches):
        return ""

    rename_groups_by_parent = group_renames_by_parent(rename_detections)
    grouped_rename_count = sum(len(g) for g in rename_groups_by_parent.values())
    raw_rename_count = len(rename_detections)
    rendered_count = grouped_rename_count + len(prose_mismatches)
    # Rollup suffix only when grouping actually collapsed something. If every
    # rename had a unique source the rollup adds noise (K==M); same for
    # prose-mismatches alone (no collapse semantics).
    if raw_rename_count > grouped_rename_count:
        header = f"## Sub-workflow boundaries ({rendered_count}, covering {raw_rename_count} underlying renames)"
    else:
        header = f"## Sub-workflow boundaries ({rendered_count})"

    lines = [
        header,
        "",
        "  Prompt-cache hits need byte-exact matches across boundaries. Each",
        "  finding below is a name or prose mismatch between a parent workflow",
        "  and its child sub-workflow that blocks one. Fix at the source once",
        "  to align every listed consumer.",
    ]

    parents = sorted(
        _collect_parent_paths(rename_detections, prose_mismatches),
        key=_workflow_short_name,
    )
    for parent_path in parents:
        parent_short = _workflow_short_name(parent_path)
        parent_rename_groups = rename_groups_by_parent.get(parent_path, {})
        parent_prose = [d for d in prose_mismatches if (d.context or {}).get("parent_workflow") == parent_path]
        if parent_rename_groups:
            lines.append("")
            lines.append(f"  In {parent_short}:")
            lines.extend(_render_renames_for_parent(parent_rename_groups))
        if parent_prose:
            lines.append("")
            lines.append(f"  Prose mismatches in {parent_short}:")
            lines.extend(_render_prose_mismatches_for_parent(parent_prose))

    return "\n".join(lines)


def _collect_parent_paths(*diag_lists: list[Diagnostic]) -> set[str]:
    out: set[str] = set()
    for diags in diag_lists:
        for d in diags:
            parent = (d.context or {}).get("parent_workflow")
            if isinstance(parent, str) and parent:
                out.add(parent)
    return out


def _render_renames_for_parent(
    groups: dict[tuple[str, str], list[tuple[str, int]]],
) -> list[str]:
    """Render the renames sub-block for one parent workflow.

    Takes a pre-grouped dict (from ``_group_renames_by_parent``) so the count
    is derivable up-front for the section header. Within the parent, sort by
    consumer count DESC (highest fan-out first), tiebreak alphabetical on
    source expression — surfaces the "biggest fix" first.
    """
    sorted_keys = sorted(groups.keys(), key=lambda k: (-len(groups[k]), k[0]))

    out: list[str] = []
    for key in sorted_keys:
        source_expr, child_input = key
        out.append("")
        out.append(f"    `{source_expr}` → `{child_input}`")
        out.extend(_format_consumer_summary(groups[key]))
    return out


def _format_consumer_summary(consumers: list[tuple[str, int]]) -> list[str]:
    """Format the "used by ..." block under a source-rename arrow line.

    Three modes:
      1 consumer:        ``used by chorus-chooser (line 97)``
      same line for all: ``used by N children at line L:`` + names
      multiple lines:    ``used by N children at lines L1, L2:`` + names
    """
    if len(consumers) == 1:
        child_wf, line = consumers[0]
        return [f"        used by {_workflow_short_name(child_wf)} (line {line})"]

    seen: set[str] = set()
    ordered_names: list[str] = []
    for child_wf, _line in consumers:
        name = _workflow_short_name(child_wf)
        if name not in seen:
            seen.add(name)
            ordered_names.append(name)

    distinct_lines = sorted({line for _, line in consumers})
    if len(distinct_lines) == 1:
        line_clause = f"line {distinct_lines[0]}"
    else:
        line_clause = "lines " + ", ".join(str(L) for L in distinct_lines)
    header = f"        used by {len(ordered_names)} children at {line_clause}:"
    return [header, *_wrap_csv(ordered_names, indent="        ", max_width=72)]


def _wrap_csv(items: list[str], *, indent: str, max_width: int) -> list[str]:
    """Wrap a comma-separated list so each line stays within ``max_width``.

    Items render as ``a, b, c`` with no trailing comma. Each continuation
    line carries the same ``indent`` as the first.
    """
    if not items:
        return []
    lines: list[str] = []
    current = indent
    for i, item in enumerate(items):
        suffix = "," if i < len(items) - 1 else ""
        chunk = item + suffix
        if current == indent:
            current = indent + chunk
        elif len(current) + 1 + len(chunk) > max_width:
            lines.append(current)
            current = indent + chunk
        else:
            current = current + " " + chunk
    if current != indent:
        lines.append(current)
    return lines


def _render_prose_mismatches_for_parent(diags: list[Diagnostic]) -> list[str]:
    """Render the prose-mismatch sub-block for one parent workflow.

    Each prose-mismatch is keyed by ``(child_workflow, chunk_name)`` (no
    line number on this finding type). Sorted by child basename then chunk.
    """
    sorted_diags = sorted(
        diags,
        key=lambda d: (
            _workflow_short_name(str((d.context or {}).get("child_workflow", ""))),
            str((d.context or {}).get("chunk_name", "")),
        ),
    )
    out: list[str] = []
    for diag in sorted_diags:
        ctx = diag.context or {}
        child_short = _workflow_short_name(str(ctx.get("child_workflow", "")))
        chunk = str(ctx.get("chunk_name", ""))
        parent_prose = str(ctx.get("parent_prose", ""))
        child_prose = str(ctx.get("child_prose", ""))
        out.append("")
        out.append(f"    {child_short}, chunk `{chunk}`:")
        out.append(f'        parent prose: "{parent_prose}"')
        out.append(f'        child prose:  "{child_prose}"')
    return out


def _workflow_short_name(path: str) -> str:
    """Extract a compact identifier for a workflow path.

    ``/abs/path/song-creator.pflow.md`` → ``song-creator``
    ``<inline>`` / ``ir-hash:abc`` → unchanged
    """
    if "/" in path:
        path = path.rsplit("/", 1)[-1]
    if path.endswith(".pflow.md"):
        return path[: -len(".pflow.md")]
    return path


def _workflow_filename(path: str) -> str:
    """Return the filename-like workflow label, preserving .pflow.md suffix."""
    if "/" in path:
        return path.rsplit("/", 1)[-1]
    return path


def _render_per_call(analysis: CacheAnalysis, *, all_rows: bool) -> str:
    if not analysis.per_call:
        return ""
    rows = list(analysis.per_call)
    # Option C — per-row data filter. A row is "real-data-bearing" iff:
    #   - input_tokens reflects ACTUAL runtime tokens (data_source in
    #     {trace, memo}), OR
    #   - the row has a declared subset (steady-state — declared chunks ARE
    #     the cacheable signal regardless of memo).
    # Pure greenfield (estimator/heuristic + no declared subset) rows are
    # filtered out: their input_tokens column shows TEMPLATE size (with
    # ${var} as ~5-token literals — NOT actual runtime size) and their
    # cacheable column is unprojectable without memo. Both columns mislead.
    # When ALL rows are filtered, the section is hidden entirely.
    visible, hidden_count, truncated_trace_default_view = _visible_per_call_rows(analysis, rows, all_rows=all_rows)
    if not visible and hidden_count == 0:
        return ""

    # Build per-row inline warning markers from analysis.warnings keyed by node_id.
    # The ``cache.`` namespace prefix is stripped — every ID in this output is
    # ``cache.*`` so the prefix is 100% redundant in the per-call notes column.
    # Full IDs stay in JSON for machine consumers (DD#27).
    warnings_by_node = _warnings_by_row_key(analysis)
    unavailable_notes_by_node = _unavailable_notes_by_row_key(analysis)

    lines = ["## Per-call cache report"]
    explainer_lines = _per_call_scope_explainer(rows, analysis.summary.evidence_scope)
    for explainer_line in explainer_lines:
        lines.append(f"  {explainer_line}")
    if truncated_trace_default_view and len(visible) < len(rows):
        hidden_unexecuted = len(rows) - len(visible)
        hidden_word = "row" if hidden_unexecuted == 1 else "rows"
        node_word = "node" if len(visible) == 1 else "nodes"
        lines.append(
            f"  Showing {len(visible)} executed LLM {node_word}; "
            f"{hidden_unexecuted} unexecuted {hidden_word} hidden (--all-rows shows everything)."
        )
    elif not all_rows and len(visible) < len(rows):
        lines.append(
            f"  Showing {len(visible)} of {len(rows)} LLM nodes; low-signal rows hidden (--all-rows shows everything)."
        )
    if visible:
        lines.append("")
        _append_per_call_rows(lines, visible, warnings_by_node, unavailable_notes_by_node, analysis)
    if hidden_count > 0:
        lines.append("")
        lines.append(
            f"  Hidden: {hidden_count} low-signal nodes "
            "(no warnings or actionable cache projection; rerun with --all-rows)."
        )
    footer = _per_call_confidence_footer(visible)
    if footer is not None:
        lines.append("")
        lines.append(f"  {footer}")
    return "\n".join(lines)


def _visible_per_call_rows(
    analysis: CacheAnalysis,
    rows: list[PerCallRow],
    *,
    all_rows: bool,
) -> tuple[list[PerCallRow], int, bool]:
    real_data_rows = [row for row in rows if _row_has_real_data(row)]
    if not real_data_rows:
        return [], 0, False
    # Analytical detections (cache.dynamic-before-static, cache.padding-advisory,
    # cache.batch-prewarm-recommended, cache.below-min-tokens, etc.) emit Diagnostic
    # objects to ``analysis.warnings`` rather than populating ``row.warnings``. The
    # default-hide rule MUST consult analysis-wide warnings.
    nodes_with_warnings = set(_warnings_by_row_key(analysis))
    truncated_trace_default_view = analysis.summary.evidence_scope == "truncated_trace_executed_subset" and not all_rows
    if truncated_trace_default_view:
        return [row for row in real_data_rows if not row.did_not_execute_in_trace], 0, True
    visible, hidden_count = _select_visible_rows(
        real_data_rows,
        all_rows=all_rows,
        nodes_with_warnings=nodes_with_warnings,
    )
    return visible, hidden_count, False


def _warnings_by_row_key(analysis: CacheAnalysis) -> dict[tuple[str | None, str], list[str]]:
    warnings_by_node: dict[tuple[str | None, str], list[str]] = {}
    for diag in analysis.warnings:
        if diag.node_id and diag.id:
            context = diag.context or {}
            workflow_path = context.get("affected_workflow")
            key = (str(workflow_path) if workflow_path is not None else None, diag.node_id)
            warnings_by_node.setdefault(key, []).append(_strip_cache_prefix(diag.id))
    return warnings_by_node


def _unavailable_notes_by_row_key(analysis: CacheAnalysis) -> dict[tuple[str | None, str], list[str]]:
    notes_by_node: dict[tuple[str | None, str], list[str]] = {}
    for diag in analysis.warnings:
        if diag.id != "cache.sub-workflow-cache-undeclared":
            continue
        context = diag.context or {}
        child_workflow = context.get("child_workflow") or context.get("affected_workflow")
        child_input_name = context.get("child_input_name")
        tokens = context.get("below_threshold_tokens")
        min_tokens = context.get("below_threshold_min_tokens")
        if not child_workflow or not child_input_name or not isinstance(tokens, int) or not isinstance(min_tokens, int):
            continue
        note = f"below cache minimum: {child_input_name} ~{tokens:,} < {min_tokens:,}"
        for node_id in _node_ids_from_csv(str(context.get("child_node_ids_csv", ""))):
            notes_by_node.setdefault((str(child_workflow), node_id), []).append(note)
    return notes_by_node


def _node_ids_from_csv(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"`([^`]+)`", value))


def _append_per_call_rows(
    lines: list[str],
    visible: list[PerCallRow],
    warnings_by_node: dict[tuple[str | None, str], list[str]],
    unavailable_notes_by_node: dict[tuple[str | None, str], list[str]],
    analysis: CacheAnalysis | None = None,
) -> None:
    # In static-analysis mode (no trace evidence) every row's
    # ``observed_call_count`` is 0 by construction. Rendering ``0`` in the
    # ``calls`` column reads as "this node never runs" — a misleading signal
    # for a workflow analyzed standalone (see ``## Per-child analyze-cache
    # commands``, which instructs agents to run the analyzer on sub-workflows
    # directly). Render ``—`` instead so the column means "no execution
    # evidence" consistent with the ``cached_now`` column's ``—`` semantics.
    static_mode = analysis is not None and analysis.summary.evidence_scope == "static_analysis"
    widths = _compute_per_call_column_widths(
        visible,
        warnings_by_node,
        unavailable_notes_by_node,
        static_mode=static_mode,
    )
    header = _format_table_row(
        ["node", "model", "input", "cached_now", "could_cache", "ratio", "calls", "notes"],
        widths,
    )
    lines.append(header)
    # Divider tracks the structured-column width (everything left of and
    # including ``calls``). The trailing ``notes`` column is unbounded prose
    # whose length should not stretch the divider — when one row has long
    # observed=... or warning IDs, the divider would otherwise blow out
    # ~160 chars and overshoot every other row visually.
    lines.append("  " + "-" * _structured_columns_width(widths))
    lines.append("")
    grouped = _group_rows_by_workflow(visible)
    multiple_workflows = len(grouped) > 1
    for workflow_path, group_rows in grouped:
        if multiple_workflows:
            lines.append(f"### {_format_workflow_group_heading(workflow_path, analysis)}")
        for row in group_rows:
            lines.append(
                _format_per_call_row(
                    row,
                    warnings_by_node,
                    unavailable_notes_by_node,
                    widths,
                    static_mode=static_mode,
                )
            )
        if multiple_workflows:
            lines.append("")
    if multiple_workflows and lines and lines[-1] == "":
        lines.pop()


def _group_rows_by_workflow(rows: list[PerCallRow]) -> list[tuple[str | None, list[PerCallRow]]]:
    groups: dict[str | None, list[PerCallRow]] = {}
    order: list[str | None] = []
    for row in rows:
        if row.workflow_path not in groups:
            groups[row.workflow_path] = []
            order.append(row.workflow_path)
        groups[row.workflow_path].append(row)
    return [(workflow_path, groups[workflow_path]) for workflow_path in order]


def _format_workflow_group_heading(workflow_path: str | None, analysis: CacheAnalysis | None) -> str:
    label = _workflow_filename(workflow_path or "<root>")
    if analysis is None or workflow_path == analysis.workflow_path:
        return label
    rollup = analysis.summary.sub_workflow_rollup
    if rollup is not None:
        for entry in rollup.per_workflow:
            if entry.workflow_path == workflow_path and entry.called_by_node_id:
                return f"{label} (called by {entry.called_by_node_id})"
    return label


def _format_per_call_row(
    row: PerCallRow,
    warnings_by_node: dict[tuple[str | None, str], list[str]],
    unavailable_notes_by_node: dict[tuple[str | None, str], list[str]],
    widths: tuple[int, ...],
    *,
    static_mode: bool = False,
) -> str:
    return _format_table_row(
        _per_call_cells(
            row,
            warnings_by_node,
            unavailable_notes_by_node,
            static_mode=static_mode,
        ),
        widths,
    )


def _compute_per_call_column_widths(
    rows: list[PerCallRow],
    warnings_by_node: dict[tuple[str | None, str], list[str]],
    unavailable_notes_by_node: dict[tuple[str | None, str], list[str]],
    *,
    static_mode: bool = False,
) -> tuple[int, ...]:
    headers = ["node", "model", "input", "cached_now", "could_cache", "ratio", "calls", "notes"]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(
            _per_call_cells(
                row,
                warnings_by_node,
                unavailable_notes_by_node,
                static_mode=static_mode,
            )
        ):
            widths[index] = max(widths[index], len(cell))
    return tuple(widths)


def _format_table_row(cells: list[str], widths: tuple[int, ...]) -> str:
    left_aligned = {0, 1, 7}
    padded = [
        cell.ljust(widths[index]) if index in left_aligned else cell.rjust(widths[index])
        for index, cell in enumerate(cells)
    ]
    # Trim trailing whitespace on the (left-aligned) notes column. Padding
    # the last column to its max-width creates trailing spaces on shorter-
    # notes rows; ``rstrip`` keeps the per-row line tight without affecting
    # earlier columns' alignment.
    return ("  " + "  ".join(padded)).rstrip()


def _structured_columns_width(widths: tuple[int, ...]) -> int:
    """Width of the structured column block (everything before ``notes``).

    The notes column trails as unbounded prose; including it in the divider
    width would let one long row (e.g., ``observed=A,B,C; warning-id``)
    stretch the divider far beyond every other row's width. The divider
    is sized to span ``node`` through ``calls``: indent (2) + sum(column
    widths 0..6) + separators (2 chars between each of 7 columns = 12).
    """
    structured = widths[:7]
    separators = 2 * max(0, len(structured) - 1)
    return 2 + sum(structured) + separators


def _per_call_cells(
    row: PerCallRow,
    warnings_by_node: dict[tuple[str | None, str], list[str]],
    unavailable_notes_by_node: dict[tuple[str | None, str], list[str]],
    *,
    static_mode: bool = False,
) -> list[str]:
    inline_warnings = warnings_by_node.get((row.workflow_path, row.node_path), [])
    unavailable_notes = unavailable_notes_by_node.get((row.workflow_path, row.node_path), [])
    return [
        row.node_path,
        _cell_model(row),
        _cell_input(row, inline_warnings),
        _cell_cached_now(row),
        _cell_could_cache(row),
        _cell_ratio(row),
        _cell_calls(row, static_mode=static_mode),
        _cell_notes(row, inline_warnings, unavailable_notes),
    ]


def _cell_model(row: PerCallRow) -> str:
    if row.model_is_heterogeneous or len(row.observed_models) > 1:
        return "<varies>"
    if row.model:
        return row.model
    # Empty model: pricing/capabilities couldn't be resolved (no
    # ``settings.default_model``, no per-node ``- model:``). Sentinel mirrors
    # the header's "no model resolved" wording.
    return "<unresolved>"


def _cell_input(row: PerCallRow, inline_warnings: list[str]) -> str:
    # For opaque prompts without runtime/cacheable evidence, the token count is
    # only the literal "${...}" template size, not a meaningful prompt size.
    if "opaque-prompt" in inline_warnings and row.cacheable_data_source == "unavailable":
        return "?"
    return f"{row.input_tokens_estimated:,}"


def _cell_cached_now(row: PerCallRow) -> str:
    if row.cacheable_data_source == "trace" and row.declared_prompt_cache:
        return _format_nullable_int(row.cacheable_tokens_estimated)
    return "—"


def _cell_could_cache(row: PerCallRow) -> str:
    if row.cacheable_data_source == "trace":
        # Tier 1 fired (declared + cache_creation/read recorded). cached_now
        # carries the number; could_cache has no projection role here.
        return "—"
    if row.cacheable_data_source in {"memo", "parameters", "batch_prefix", "cross_workflow_projection"}:
        # Tier 2 / heuristic projection — show the projected count.
        return _format_nullable_int(row.cacheable_tokens_estimated)
    if row.cacheable_data_source == "unavailable":
        return "?"
    # Future tier: fail-loud, fail-actionable — show the value if the analyzer
    # produced one, else fall through to the formatter's None handling.
    return _format_nullable_int(row.cacheable_tokens_estimated)


def _cell_ratio(row: PerCallRow) -> str:
    return f"{row.cache_ratio_pct}%" if row.cache_ratio_pct is not None else "?%"


def _cell_calls(row: PerCallRow, *, static_mode: bool = False) -> str:
    # Static-analysis mode means no trace evidence is available, so every
    # row's ``observed_call_count`` is 0 by construction. Render ``—``
    # instead of ``0`` so the column reads as "no execution evidence"
    # rather than the misleading "this node never runs". In trace mode,
    # ``observed_call_count == 0`` is a real signal (conditional branch
    # not taken) and must render as ``0``.
    if static_mode:
        return "—"
    return str(row.observed_call_count)


def _cell_notes(row: PerCallRow, inline_warnings: list[str], unavailable_notes: list[str]) -> str:
    notes: list[str] = []
    if row.did_not_execute_in_trace:
        notes.append("[unexecuted]")
    if "opaque-prompt" in inline_warnings:
        notes.append("opaque-prompt")
    if row.is_batch and row.batch_size_estimated:
        notes.append(f"batch_items={row.batch_size_estimated}")
    if row.observed_models and (row.model_is_heterogeneous or len(row.observed_models) > 1):
        observed = ",".join(_short_observed_model_name(model) for model in row.observed_models)
        notes.append(f"observed={observed}")
    if row.cacheable_data_source == "cross_workflow_projection" and len(row.cross_workflow_inputs) > 1:
        notes.append(_format_cross_workflow_inputs_note(row.cross_workflow_inputs))
    if row.cacheable_data_source == "unavailable":
        notes.extend(unavailable_notes)
        fallback_note = _unavailable_could_cache_note(row, inline_warnings, has_specific_note=bool(unavailable_notes))
        if fallback_note:
            notes.append(fallback_note)
    notes.extend(warning_id for warning_id in inline_warnings if warning_id != "opaque-prompt")
    return "; ".join(notes)


def _format_cross_workflow_inputs_note(inputs: tuple[str, ...]) -> str:
    if len(inputs) <= 3:
        return f"cacheable inputs: {', '.join(inputs)}"
    return f"cacheable inputs: {', '.join(inputs[:3])}, +{len(inputs) - 3} more"


def _unavailable_could_cache_note(
    row: PerCallRow,
    inline_warnings: list[str],
    *,
    has_specific_note: bool,
) -> str | None:
    if row.did_not_execute_in_trace or has_specific_note:
        return None
    if row.model_is_heterogeneous or "opaque-prompt" in inline_warnings:
        return None
    if row.observed_call_count == 1:
        return "single call; no repeated cache use observed"
    if row.observed_call_count < 2:
        return None
    if not row.model:
        return "no stable repeated cache prefix found"
    return f"no stable {get_min_cache_tokens(row.model):,}-token repeated prefix found"


def _format_nullable_int(value: int | None) -> str:
    return f"{value:,}" if value is not None else "?"


def _short_observed_model_name(model: str) -> str:
    return model.removeprefix("gemini/")


def _render_sub_workflow_drill_in(analysis: CacheAnalysis) -> str:
    """Emit a paste-ready block of per-child ``pflow analyze-cache`` commands.

    B-3: 15 absolute paths × ~200 chars each was the loudest noise block in
    real-world output. Compress by emitting one ``cd <parent-dir>`` line then
    relative child paths — children of a workflow naturally live under or
    near the parent's directory, so the relpath form is short and the block
    stays paste-runnable line-by-line.

    Falls back to absolute paths when the workflow_path has no directory
    component (bare filename or ``ir-hash:`` synthetic key for inline IR).
    """
    rollup = analysis.summary.sub_workflow_rollup
    if rollup is None:
        return ""
    llm_bearing = _llm_bearing_rollup_entries(rollup)
    if not llm_bearing:
        return ""
    lines = [
        "## Per-child analyze-cache commands",
        "",
        "  Sub-workflow opportunities don't surface here — run analyze-cache per child:",
    ]
    parent_dir = os.path.dirname(analysis.workflow_path)
    if parent_dir:
        lines.append(f"    cd {_display_path_from_cwd(parent_dir)}")
        for entry in llm_bearing:
            lines.append(f"    pflow analyze-cache {os.path.relpath(entry.workflow_path, parent_dir)}")
    else:
        for entry in llm_bearing:
            lines.append(f"    pflow analyze-cache {entry.workflow_path}")
    return "\n".join(lines)


def _per_call_scope_explainer(rows: list[PerCallRow], evidence_scope: str = "static_analysis") -> list[str]:
    """Return multi-line explainer describing what the per-call columns mean.

    Two modes that survive the Option C row filter:

    - **Steady-state**: at least one row has ``declared_prompt_cache``.
      Values reflect declared subsets.
    - **Post-run greenfield**: rows have memo/trace data; values are projected
      from real run history.

    Returned as ``list[str]`` so the caller can emit one indented line per
    bullet — the prior single-line form packed four facts into a 60-word
    run-on that agents skimmed past. The prior form also carried a
    "divide by calls for per-call values" hint that became wrong after
    static-list batch trace rows were normalized to per-call units; the
    blanket advice is dropped here rather than caveated, since column-by-
    column meaning is the agent-actionable signal.
    """
    if evidence_scope == "truncated_trace_executed_subset":
        return ["Executed trace rows are evidence-only; unexecuted rows are marked when shown."]
    is_steady_state = any(row.declared_prompt_cache is not None for row in rows)
    lead = (
        "Actual cache ratios from declared `prompt_cache:` subsets."
        if is_steady_state
        else "Projected cache ratios from prior run data."
    )
    return [
        lead,
        "  · cached_now: tokens that went through cache this run.",
        "  · could_cache: tokens that could be cached if you declare/extend prompt_cache:; ? means no cacheable chunk could be projected.",
        "  · — means the column does not apply to this row's tier.",
    ]


def _per_call_confidence_footer(rows: list[PerCallRow]) -> str | None:
    low_input_nodes = [row.node_path for row in rows if row.data_source in {"estimator", "heuristic"}]
    batch_exemplar_nodes = [row.node_path for row in rows if row.cacheable_data_source == "parameters" and row.is_batch]
    batch_prefix_nodes = [row.node_path for row in rows if row.cacheable_data_source == "batch_prefix"]
    cross_workflow_nodes = [row.node_path for row in rows if row.cacheable_data_source == "cross_workflow_projection"]
    parts: list[str] = []
    if low_input_nodes:
        parts.append(f"projected input tokens: {', '.join(low_input_nodes)}")
    if batch_exemplar_nodes:
        parts.append(
            f"{', '.join(batch_exemplar_nodes)} uses the first batch item as a representative sample; "
            "actual tokens may vary for later items"
        )
    if batch_prefix_nodes:
        # Distinct from the batch-exemplar case above: this projection scans
        # the prompt's static prefix (bytes before the first per-item ref)
        # and multiplies by observed call count. No item content participates,
        # so the message must not claim sampling.
        parts.append(
            f"{', '.join(batch_prefix_nodes)} projects savings from the prompt's static prefix repeated "
            "across observed calls; declare prompt_cache to confirm"
        )
    if cross_workflow_nodes:
        subject = ", ".join(cross_workflow_nodes)
        verb = "uses" if len(cross_workflow_nodes) == 1 else "use"
        parts.append(
            f"{subject} {verb} cross-workflow projections from shared inputs declared "
            "in parent workflow(s); declare the listed values in the receiving sub-workflow's ## Cache "
            "and remove inline body refs (see Recommended actions for the boundary's recommended fix and "
            "Sub-workflow boundaries for source-side renames)"
        )
    if not parts:
        return None
    return "Token estimate confidence: " + "; ".join(parts) + "."


def _row_has_real_data(row: PerCallRow) -> bool:
    from .view_helpers import per_call_row_has_real_data

    return per_call_row_has_real_data(row)


def _strip_cache_prefix(warning_id: str) -> str:
    """Strip the ``cache.`` namespace prefix for compact text rendering.

    Every catalog ID is namespaced ``cache.*`` so the prefix is redundant in
    the analyze-cache text output. Full IDs stay in JSON via
    ``Diagnostic.to_dict()`` for machine consumers (DD#27).
    """
    return warning_id.removeprefix("cache.") if warning_id else warning_id


def _select_visible_rows(
    rows: Iterable[PerCallRow],
    *,
    all_rows: bool,
    nodes_with_warnings: set[tuple[str | None, str]],
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


def _is_row_visible_by_default(row: PerCallRow, nodes_with_warnings: set[tuple[str | None, str]]) -> bool:
    """Per spec — show rows with analysis-wide warnings OR ratio < 80%.

    Stage 0.3: the inline ``row.warnings`` fallback is gone — production
    never populated it. Per-row warning visibility is keyed entirely by
    ``analysis.warnings`` filtered by node_id.

    ``cache_ratio_pct`` may be ``None`` (mixed-state row that survived the
    real-data filter but has no projection). Treat None as "below threshold"
    — show by default since the agent should at least see that the row exists.
    """
    if (row.workflow_path, row.node_path) in nodes_with_warnings or (None, row.node_path) in nodes_with_warnings:
        return True
    if row.cacheable_data_source != "unavailable" and not row.declared_prompt_cache:
        return True
    if row.model_is_heterogeneous:
        return True
    if row.cache_ratio_pct is None:
        if row.declared_prompt_cache:
            return True
        return row.observed_call_count != 1
    return row.cache_ratio_pct < _HIDDEN_RATIO_THRESHOLD


def _render_notes(analysis: CacheAnalysis) -> str:
    if not analysis.notes:
        return ""
    lines = ["## Notes", ""]
    prose_paths = _analysis_workflow_paths(analysis)
    for note in analysis.notes:
        lines.append(f"  · {_shorten_paths_in_prose(note, prose_paths)}")
    return "\n".join(lines)


__all__ = ["render_text"]
