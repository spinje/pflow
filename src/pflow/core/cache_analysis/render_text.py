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
from pathlib import Path
from typing import cast

from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_capabilities import get_min_cache_tokens

from .analyze import (
    AnalysisSummary,
    CacheAnalysis,
    CostDelta,
    CrossWorkflowInputContribution,
    PerCallRow,
    RecommendedAction,
    SubWorkflowRollup,
    SubWorkflowRollupEntry,
)

_HIDDEN_RATIO_THRESHOLD = 80
_PER_CALL_COLUMNS: tuple[str, ...] = (
    "node",
    "model",
    "input",
    "cached_now",
    "could_cache",
    "ratio",
    "calls",
    "notes",
)
_ALWAYS_VISIBLE_PER_CALL_COLUMNS: frozenset[str] = frozenset({"node", "model", "input", "notes"})
_LEFT_ALIGNED_PER_CALL_COLUMNS: frozenset[str] = frozenset({"node", "model", "notes"})
_NO_TRACE_RECORDED_NOTE = "no trace recorded — run with --report to populate this row"

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
    # Trace transparency (Bug 1 follow-up): name the loaded trace file +
    # outcome + recording timestamp whenever a trace was loaded. Fires for
    # both autoload and ``--from-trace``. ``analysis.trace_path`` is the
    # authoritative "was a trace loaded" signal — the rejection gate at
    # ``analyze.py:683`` sets it to None when rebuilding to greenfield.
    if analysis.trace_path is not None:
        lines.append(_format_trace_header_line(analysis.trace_path, s))
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
        total_rows = coverage.get("total", 0)
        # Suppress when redundant with the Evidence line. Evidence already
        # conveys "complete trace covers every LLM node" in this state; the
        # Confidence line would render "(N of N nodes)" — same denominator,
        # zero added signal. Keep the line for medium_from_memo (carries
        # memo-tier info Evidence doesn't), for partial trace coverage, for
        # truncated traces, and when conditional dispatch left nodes
        # unreached (Confidence's count is over a different denominator
        # there and is worth showing).
        evidence_complete_all_executed = (
            s.evidence_scope == "complete_trace" and s.trace_llm_nodes_static == s.trace_llm_nodes_executed
        )
        confidence_says_full_trace = label == "high_from_trace" and source_count == total_rows
        suppress = evidence_complete_all_executed and confidence_says_full_trace
        if not suppress:
            lines.append(_format_confidence_line(label, source_count, total_rows))
    return "\n".join(lines)


def _format_confidence_line(label: str, source_count: int, total_rows: int) -> str:
    """Render the Confidence header line in plain English.

    The raw enum values (``medium_from_memo`` / ``high_from_trace``) leak
    analyzer-internal taxonomy to agents reading the text output. Replace
    with a tier word + plain-English source phrase. JSON keeps the enum
    in ``estimate_confidence`` for machine consumers.
    """
    if label == "high_from_trace":
        source = "token counts from this run's trace"
        tier = "high"
    else:  # medium_from_memo — the only other label that reaches this branch
        source = "token counts from memoized prior runs"
        tier = "medium"
    return f"  Confidence: {tier} — {source} ({source_count} of {total_rows} nodes)"


def _format_trace_header_line(trace_path: str, summary: AnalysisSummary) -> str:
    """Render the ``Trace:`` header line for a loaded trace.

    Shape: ``  Trace: <filename> (<status>, recorded <YYYY-MM-DD HH:MM>)``.
    The ``recorded ...`` suffix is dropped when ``trace_recorded_at`` is None
    (defensive — legacy traces from before 2.1.0 may lack ``start_time``).

    The filename alone is the agent-visible identity; the rest of the
    pflow ecosystem already exposes the directory (``~/.pflow/debug/``)
    via ``pflow analyze-cache --help`` text and the trace-saved stderr
    line at run time.
    """
    filename = Path(trace_path).name
    status = summary.trace_final_status or "unknown"
    recorded = _format_recorded_timestamp(summary.trace_recorded_at)
    if recorded is None:
        return f"  Trace: {filename} ({status})"
    return f"  Trace: {filename} ({status}, recorded {recorded})"


def _format_recorded_timestamp(iso: str | None) -> str | None:
    """Convert ``start_time`` ISO 8601 to ``YYYY-MM-DD HH:MM`` for display.

    Returns None on missing input or any parse failure — the caller drops
    the "recorded ..." suffix when None.
    """
    if iso is None:
        return None
    # ISO format from ``workflow_trace.py:528`` is
    # ``datetime.now().isoformat()`` → ``2026-05-11T15:32:28.123456``.
    # Strip microseconds via the ``T`` split and slice minute-precision.
    try:
        date_part, time_part = iso.split("T", 1)
        # ``time_part`` is HH:MM:SS[.fraction]; trim to HH:MM.
        hhmm = time_part[:5]
        if len(date_part) != 10 or len(hhmm) != 5 or hhmm[2] != ":":
            return None
        return f"{date_part} {hhmm}"
    except (ValueError, AttributeError):
        return None


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
    """Cost lines when a trace contributed actual costs.

    Fix 7: when ``projection_exclusions`` is non-empty and every excluded
    row carries a trace-recorded ``actual_cost_usd``, FOLD that cost into
    the no-cache and rerun projection lines (pass-through) so the cost
    block reconciles in-place without the agent doing subtraction. Drop
    the standalone ``Excluded from analysis:`` line in that case and
    surface the same info as a footnote below the cost block.

    Fallback: when an excluded row has ``actual_cost_usd is None`` (rare
    in production — trace_tree coerces unpriced events to 0.0, but the
    honest-unmeasurable contract requires None when truly absent), keep
    the original ``Excluded from analysis:`` line and priced-cohort
    projections. Can't pass through what we didn't measure.
    """
    tier = s.actually_paid_tier.value
    actually_paid_str = _format_cost(
        s.actually_paid_usd,
        tier == "trace_partial",
        s.unavailable_models,
        tier_annotation=tier,
    )
    if s.evidence_scope == "truncated_trace_executed_subset":
        # Truncated branch is structurally different (executed subset is the
        # cohort by construction). Unchanged by Fix 7.
        no_cache_str = _format_cost(s.no_cache_hypothetical_usd, False, s.unavailable_models)
        rerun_str = _format_cost(s.rerun_within_ttl_hypothetical_usd, False, s.unavailable_models)
        return [
            f"  Actually paid (executed trace):       {actually_paid_str}",
            f"  Cost without caching (executed):      {no_cache_str}",
            f"  Cost on rerun (executed, within TTL): {rerun_str}",
        ]
    # Complete-trace branch — try to fold pass-through.
    can_fold = (
        bool(s.projection_exclusions)
        and all(e.actual_cost_usd is not None for e in s.projection_exclusions)
        and s.no_cache_hypothetical_usd is not None
    )
    if can_fold:
        # mypy: all() narrowed actual_cost_usd to float, but the generator
        # still types the elements as ``float | None``. Cast at the use site.
        excluded_total = sum(cast(float, e.actual_cost_usd) for e in s.projection_exclusions)
        no_cache_folded = cast(float, s.no_cache_hypothetical_usd) + excluded_total
        rerun_folded: float | None = (
            s.rerun_within_ttl_hypothetical_usd + excluded_total
            if s.rerun_within_ttl_hypothetical_usd is not None
            else None
        )
        no_cache_str = _format_cost(no_cache_folded, False, s.unavailable_models)
        rerun_str = _format_cost(rerun_folded, False, s.unavailable_models)
        lines = [
            f"  Actually paid:               {actually_paid_str}",
            f"  Cost without caching:        {no_cache_str}",
            f"  Cost on rerun (within TTL):  {rerun_str}",
        ]
        footnote = _format_passthrough_footnote(s, excluded_total)
        if footnote is not None:
            lines.append("")
            lines.append(footnote)
        return lines
    # Fall back: keep the standalone Excluded line + priced-cohort projections.
    projection_partial_marker = s.partial_cost_usd and not s.projection_exclusions
    no_cache_str = _format_cost(s.no_cache_hypothetical_usd, projection_partial_marker, s.unavailable_models)
    rerun_str = _format_cost(s.rerun_within_ttl_hypothetical_usd, projection_partial_marker, s.unavailable_models)
    lines = [f"  Actually paid:               {actually_paid_str}"]
    excluded_line = _format_excluded_from_analysis_line(s)
    if excluded_line is not None:
        lines.append(excluded_line)
    lines.append(f"  Cost without caching:        {no_cache_str}")
    lines.append(f"  Cost on rerun (within TTL):  {rerun_str}")
    return lines


def _format_passthrough_footnote(s: AnalysisSummary, excluded_total: float) -> str | None:
    """Footnote naming nodes whose paid cost is included above but excluded
    from cache-savings projections.

    "Pass-through" jargon was confusing for fresh agents (Bug 13); the
    rewrite leads with what the amount represents and why no projection is
    available. Caching may still apply at the provider level when model +
    content combinations repeat across calls — that's surfaced as a follow-up
    sentence rather than the first clause.
    """
    if not s.projection_exclusions:
        return None
    sorted_exclusions = sorted(
        s.projection_exclusions,
        key=lambda e: (e.workflow_path or "", e.node_path),
    )
    amount = _format_dollar_amount(excluded_total)
    if len(sorted_exclusions) == 1:
        e = sorted_exclusions[0]
        reason = _EXCLUSION_REASON_LABELS.get(e.reason, e.reason)
        return (
            f"  · {amount} of the above was paid by {e.node_path} but couldn't be "
            f"analyzed for cache savings ({reason}). Caching may still apply at "
            "runtime if its content repeats across calls."
        )
    node_csv = ", ".join(
        f"{e.node_path} ({_EXCLUSION_REASON_LABELS.get(e.reason, e.reason)})" for e in sorted_exclusions
    )
    return (
        f"  · {amount} of the above was paid by nodes that couldn't be analyzed "
        f"for cache savings: {node_csv}. Caching may still apply at runtime if "
        "their content repeats across calls."
    )


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
            "  Trace-dependent optimization recommendations suppressed because the trace is truncated (workflow did not finish)."
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


_TIER_LABELS: dict[str, str] = {
    "trace": "from trace",
    "trace_partial": "from partial trace",
}


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

    Optional ``tier_annotation`` (a ``CostTier`` enum value like ``"trace"``
    or ``"trace_partial"``) appended in parentheses as plain English via
    ``_TIER_LABELS`` so the agent reads ``(from trace)`` / ``(from partial
    trace)`` rather than the raw snake_case enum. Empty string skips the
    suffix (the no_cache / first_run / rerun projection lines stay
    unannotated — they're hypotheticals; the tier-confidence concept
    doesn't apply). Unknown tier values fall through to the raw string,
    preserving information if a new enum value reaches this code path
    without a label mapping.
    """
    if value is None:
        if len(unavailable_models) == 1:
            return f"unavailable ({unavailable_models[0]} lacks pricing data)"
        if unavailable_models:
            return f"unavailable (all {len(unavailable_models)} models lack pricing data)"
        return "unavailable"
    label = _TIER_LABELS.get(tier_annotation, tier_annotation)
    annotation = f" ({label})" if label else ""
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
    intro = (
        "Each item below is a cache-optimization opportunity for this workflow.\n"
        "Declared values are sent once and reused at 0.1× input cost."
    )
    if any(action.warning_id == "cache.sub-workflow-cache-undeclared" for action in actions):
        intro += (
            '\n\nFor each "Sub-workflow cache undeclared" finding, apply ALL THREE edits '
            "in the listed child workflow. Doing only some leaves the cache disabled:\n"
            "  (1) Remove the `${var}` references from each affected node's prompt. "
            "Leaving them re-sends the content uncached.\n"
            "  (2) Add the listed values as named entries under the child workflow's ## Cache section.\n"
            "  (3) Reference that named entry in `prompt_cache:` on each consumer node."
        )
    return _render_action_list(
        header=header,
        intro=intro,
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
    lines: list[str] = []
    if action.warning_id == "cache.prompt-body-shadows-cache":
        lines.extend(_format_shadow_cache_cost_comparison(action))
    lines.extend(
        f"     → {_replace_action_scope_as_edit_target(suggestion, action, workflow_path)}"
        for suggestion in action.suggestions
    )
    return lines


def _format_shadow_cache_cost_comparison(action: RecommendedAction) -> list[str]:
    """Render cost evidence for prompt-body/cache sub-path shadow warnings."""
    body_only = action.context.get("body_only_cost_usd_per_call")
    with_cache = action.context.get("with_cache_cost_usd_per_call")
    shadowed = action.context.get("shadowed_chunk_names") or ()
    node_id = action.context.get("node_id") or action.node_id
    if not isinstance(body_only, (int, float)) or not isinstance(with_cache, (int, float)):
        return []
    if not isinstance(node_id, str) or not isinstance(shadowed, (list, tuple)) or not shadowed:
        return []

    body_value = float(body_only)
    cache_value = float(with_cache)
    body_str = _format_dollar_amount(body_value)
    cache_str = _format_dollar_amount(cache_value)
    ratio_phrase = ""
    if body_value > 0:
        ratio = cache_value / body_value
        if ratio >= 2.0:
            ratio_phrase = f" — caching is {ratio:.0f}× more expensive than removing the declaration"

    chunks_csv = ", ".join(f"`{chunk}`" for chunk in shadowed)
    return [
        f"     → Removing `prompt_cache:` for {chunks_csv} from `{node_id}` "
        f"would drop per-call cost from {cache_str} to {body_str}{ratio_phrase}.",
        "       The body only references a sub-path of the cached value; the rest is sent to the model "
        "but unused by your prompt.",
        "       Note: the summary's 'saves N%' compares against inlining the full chunk uncached — "
        "a different baseline than your body actually uses.",
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
    aligned with the rank line above. Blank lines are preserved verbatim so
    that diagnostics whose message templates embed `\\n\\n` between sections
    (e.g. ``cache.prompt-cache-incomplete``'s intro vs. findings block, the
    paste-ready ``## Cache`` block in ``cache.sub-workflow-cache-undeclared``)
    render with the visual separation their authors intended.
    """
    return [f"{prefix}{line}" for line in message.splitlines()]


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
    """Return a path for prose that points at a file to edit.

    Anchored at the invocation cwd: the agent's cwd is the only frame they
    can navigate paths from reliably. Anchoring at the analyzed workflow's
    directory produced shorter strings but they were invalid from the
    agent's actual cwd (e.g. ``chorus-chooser/...`` when the agent ran
    analyze-cache from project root). The basename short-circuit is kept
    for self-references — ``Edit chorus-chooser.pflow.md`` reads cleaner
    than the full path when prose context already established the workflow.
    """
    if not path or path.startswith("ir-hash:") or "/" not in path:
        return path
    if path == root_workflow_path:
        return _workflow_filename(path)
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
        for key in ("affected_workflow", "parent_workflow", "child_workflow"):
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
    if action.warning_id == "cache.sub-workflow-cache-undeclared" and action.estimated_savings_usd is None:
        if "Switch model:" in action.message:
            return "savings available with model switch"
        if "cannot compute the cache threshold" in action.message:
            return "unmeasurable"
        if "below the smallest provider cache minimum" in action.message:
            return "not yet cacheable"
    if action.warning_id == "cache.batch-prewarm-lower-bound-recommended":
        return _format_lower_bound_action_savings(action.context.get("savings_lower_bound_usd"))
    if action.warning_id != "cache.batch-prewarm-recommended":
        return _format_savings_usd(action.estimated_savings_usd)
    value = action.estimated_savings_usd
    if value is None or value < 0.0001:
        return "savings unavailable"
    if value < 0.01:
        return f"saves ~${value:.4f}/run"
    return f"saves ~${value:.2f}/run"


def _format_lower_bound_action_savings(value: object) -> str:
    if not isinstance(value, (int, float)) or value < 0.0001:
        return "savings at least unknown"
    if value < 0.01:
        return f"savings at least ~${value:.4f}/run"
    return f"savings at least ~${value:.2f}/run"


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
        chunks.append("  `ttl` accepts `1m` through `60m`; `1h` is also accepted.")
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

    Prose-mismatches render 1-per-finding, parent-grouped by source workflow.
    Rename diagnostics are still emitted for JSON/raw consumers, but are not
    rendered in agent-facing text because variable names are stripped before
    provider-cache bytes are sent.

    Cross-boundary value-flow opportunities surface in Recommended actions
    only (filtered by ``view_helpers._CROSS_WORKFLOW_ALIGNMENT_IDS``).
    """
    prose_mismatches = [d for d in analysis.warnings if d.id == "cache.cross-workflow-prose-mismatch"]
    if not prose_mismatches:
        return ""

    lines = [
        f"## Sub-workflow boundaries ({len(prose_mismatches)})",
        "",
        "  Prompt-cache hits need byte-exact matches across boundaries. Each",
        "  finding below is a prose mismatch between cached chunk content in",
        "  a parent workflow and its child sub-workflow that blocks one.",
        "  Fix at the source once to align every listed consumer.",
    ]

    parents = sorted(
        _collect_parent_paths(prose_mismatches),
        key=_workflow_short_name,
    )
    for parent_path in parents:
        parent_short = _workflow_short_name(parent_path)
        parent_prose = [d for d in prose_mismatches if (d.context or {}).get("parent_workflow") == parent_path]
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
    below_min_notes_by_node = _below_provider_min_note_by_row_key(analysis)
    static_mode = analysis.summary.evidence_scope == "static_analysis"
    visible_columns = _visible_per_call_columns(visible, static_mode=static_mode)
    components_by_row = [
        _cell_note_components(
            row,
            warnings_by_node.get((row.workflow_path, row.node_path), []),
            unavailable_notes_by_node.get((row.workflow_path, row.node_path), []),
            below_min_notes_by_node.get((row.workflow_path, row.node_path), []),
        )
        for row in visible
    ]
    deduped_components_by_row, per_call_notes = _dedup_row_note_components(visible, components_by_row)

    lines = ["## Per-call cache report"]
    explainer_lines = _per_call_scope_explainer(rows, analysis.summary.evidence_scope, visible_columns)
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
        _append_per_call_rows(
            lines,
            visible,
            warnings_by_node,
            visible_columns=visible_columns,
            deduped_components_by_row=deduped_components_by_row,
            analysis=analysis,
        )
    _append_per_call_footer_blocks(lines, visible, hidden_count, per_call_notes)
    return "\n".join(lines)


def _append_per_call_footer_blocks(
    lines: list[str],
    visible: list[PerCallRow],
    hidden_count: int,
    per_call_notes: list[tuple[str, int]],
) -> None:
    notes_footer_lines = _render_per_call_notes_footer(per_call_notes)
    if notes_footer_lines:
        lines.append("")
        for line in notes_footer_lines:
            lines.append(f"  {line}")
    footer_lines = _per_call_confidence_footer(visible)
    if footer_lines is not None:
        lines.append("")
        for line in footer_lines:
            lines.append(f"  {line}")
    if hidden_count > 0:
        lines.append("")
        lines.append(
            f"  Hidden: {hidden_count} low-signal nodes "
            "(no warnings or actionable cache projection; rerun with --all-rows)."
        )


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
        case = context.get("case")
        if case not in {"model_switch", "refactor"} or not child_workflow:
            continue
        inputs = context.get("inputs", [])
        if not isinstance(inputs, list):
            continue
        for input_dict in inputs:
            if not isinstance(input_dict, dict):
                continue
            tokens = input_dict.get("tokens_estimated")
            input_name = input_dict.get("child_cache_ref") or input_dict.get("child_input_name", "")
            consumer_ids = input_dict.get("consumer_node_ids", [])
            if not isinstance(tokens, int) or not input_name or not isinstance(consumer_ids, list):
                continue
            note = f"below cache minimum: {input_name} ~{tokens:,}"
            for node_id in consumer_ids:
                notes_by_node.setdefault((str(child_workflow), str(node_id)), []).append(note)
    return notes_by_node


def _below_provider_min_note_by_row_key(analysis: CacheAnalysis) -> dict[tuple[str | None, str], list[str]]:
    """Per-row notes for projected cacheable tokens below the provider minimum."""
    notes_by_node: dict[tuple[str | None, str], list[str]] = {}
    projected_tiers = {"parameters", "memo", "batch_prefix", "cross_workflow_projection"}
    for row in analysis.per_call:
        if row.cacheable_data_source not in projected_tiers:
            continue
        if row.declared_prompt_cache:
            continue
        if row.cacheable_tokens_estimated is None:
            continue
        if not row.model:
            continue
        min_tokens = get_min_cache_tokens(row.model)
        if row.cacheable_tokens_estimated >= min_tokens:
            continue
        key = (row.workflow_path, row.node_path)
        notes_by_node.setdefault(key, []).append(f"below provider min (need ≥{min_tokens:,} for this model)")
    return notes_by_node


def _node_ids_from_csv(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"`([^`]+)`", value))


def _append_per_call_rows(
    lines: list[str],
    visible: list[PerCallRow],
    warnings_by_node: dict[tuple[str | None, str], list[str]],
    *,
    visible_columns: tuple[str, ...],
    deduped_components_by_row: list[list[str]],
    analysis: CacheAnalysis | None = None,
) -> None:
    # In static-analysis mode (no trace evidence) every row's
    # ``observed_call_count`` is 0 by construction. The calls column is hidden
    # in that mode so agents do not misread "0" as "this node never runs".
    static_mode = analysis is not None and analysis.summary.evidence_scope == "static_analysis"
    widths = _compute_per_call_column_widths(
        visible,
        warnings_by_node,
        visible_columns=visible_columns,
        deduped_components_by_row=deduped_components_by_row,
        static_mode=static_mode,
    )
    left_aligned_indices = {
        visible_columns.index(name) for name in _LEFT_ALIGNED_PER_CALL_COLUMNS if name in visible_columns
    }
    header = _format_table_row(
        list(visible_columns),
        widths,
        left_aligned_indices,
    )
    lines.append(header)
    # Divider tracks the structured-column width (everything left of the
    # trailing ``notes`` column). Notes are unbounded prose; one long
    # observed=... or warning-ID cell should not stretch the divider.
    lines.append("  " + "-" * _structured_columns_width(widths))
    lines.append("")
    components_by_row_id = {
        id(row): components for row, components in zip(visible, deduped_components_by_row, strict=True)
    }
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
                    widths,
                    visible_columns=visible_columns,
                    deduped_components=components_by_row_id[id(row)],
                    left_aligned_indices=left_aligned_indices,
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
    widths: tuple[int, ...],
    *,
    visible_columns: tuple[str, ...],
    deduped_components: list[str],
    left_aligned_indices: set[int],
    static_mode: bool = False,
) -> str:
    return _format_table_row(
        _per_call_cells(
            row,
            warnings_by_node,
            visible_columns=visible_columns,
            deduped_components=deduped_components,
            static_mode=static_mode,
        ),
        widths,
        left_aligned_indices,
    )


def _compute_per_call_column_widths(
    rows: list[PerCallRow],
    warnings_by_node: dict[tuple[str | None, str], list[str]],
    *,
    visible_columns: tuple[str, ...],
    deduped_components_by_row: list[list[str]],
    static_mode: bool = False,
) -> tuple[int, ...]:
    widths = [len(header) for header in visible_columns]
    for row, deduped_components in zip(rows, deduped_components_by_row):
        for index, cell in enumerate(
            _per_call_cells(
                row,
                warnings_by_node,
                visible_columns=visible_columns,
                deduped_components=deduped_components,
                static_mode=static_mode,
            )
        ):
            widths[index] = max(widths[index], len(cell))
    return tuple(widths)


def _format_table_row(cells: list[str], widths: tuple[int, ...], left_aligned_indices: set[int]) -> str:
    padded = [
        cell.ljust(widths[index]) if index in left_aligned_indices else cell.rjust(widths[index])
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
    is sized to span every visible column before ``notes``: indent (2) +
    sum(structured widths) + separators (2 chars between each structured
    column).
    """
    structured = widths[:-1]
    separators = 2 * max(0, len(structured) - 1)
    return 2 + sum(structured) + separators


def _per_call_cells(
    row: PerCallRow,
    warnings_by_node: dict[tuple[str | None, str], list[str]],
    *,
    visible_columns: tuple[str, ...],
    deduped_components: list[str],
    static_mode: bool = False,
) -> list[str]:
    inline_warnings = warnings_by_node.get((row.workflow_path, row.node_path), [])
    all_cells = {
        "node": row.node_path,
        "model": _cell_model(row),
        "input": _cell_input(row, inline_warnings),
        "cached_now": _cell_cached_now(row),
        "could_cache": _cell_could_cache(row),
        "ratio": _cell_ratio(row),
        "calls": _cell_calls(row, static_mode=static_mode),
        "notes": "; ".join(deduped_components),
    }
    return [all_cells[column] for column in visible_columns]


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
    # Static-analysis mode means no trace evidence is available. The calls
    # column is normally hidden in that mode; this fallback preserves the
    # old "no execution evidence" marker for direct helper callers.
    if static_mode:
        return "—"
    return str(row.observed_call_count)


def _visible_per_call_columns(rows: list[PerCallRow], *, static_mode: bool) -> tuple[str, ...]:
    """Compute the per-call table columns from the rows that will render.

    Identity columns and notes are always present. Trace-backed reports keep
    the established full table. Static reports hide columns that would carry
    only placeholders, except for resolved declared-cache rows where
    ``could_cache: ?`` is the useful signal that projection needs trace data.
    """
    if not static_mode:
        return _PER_CALL_COLUMNS
    has_real = {
        "cached_now": any(
            row.cacheable_data_source == "trace"
            and bool(row.declared_prompt_cache)
            and row.cacheable_tokens_estimated is not None
            for row in rows
        ),
        "could_cache": any(
            (
                row.cacheable_data_source in {"memo", "parameters", "batch_prefix", "cross_workflow_projection"}
                and row.cacheable_tokens_estimated is not None
            )
            or (bool(row.declared_prompt_cache) and bool(row.model) and not row.model_is_heterogeneous)
            for row in rows
        ),
        "ratio": any(row.cache_ratio_pct is not None for row in rows),
        "calls": not static_mode,
    }
    return tuple(
        column
        for column in _PER_CALL_COLUMNS
        if column in _ALWAYS_VISIBLE_PER_CALL_COLUMNS or has_real.get(column, False)
    )


def _cell_note_components(
    row: PerCallRow,
    inline_warnings: list[str],
    unavailable_notes: list[str],
    below_min_notes: list[str],
) -> list[str]:
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
    notes.extend(below_min_notes)
    notes.extend(warning_id for warning_id in inline_warnings if warning_id != "opaque-prompt")
    return notes


def _dedup_row_note_components(
    rows: list[PerCallRow],
    components_per_row: list[list[str]],
    *,
    threshold: int = 2,
) -> tuple[list[list[str]], list[tuple[str, int]]]:
    """Aggregate repeated note components into a footer.

    Deduping by component, rather than whole note cell, preserves unique row
    notes. A row with ``no trace recorded`` plus a unique warning marker still
    keeps that warning inline while the repeated no-trace component is counted
    in the footer.
    """
    del rows  # reserved for future row-aware aggregate copy without changing the call shape
    counts: dict[str, int] = {}
    for components in components_per_row:
        for component in dict.fromkeys(components):
            counts[component] = counts.get(component, 0) + 1
    deduped_components = [
        component for component, count in counts.items() if count >= threshold and component == _NO_TRACE_RECORDED_NOTE
    ]
    if not deduped_components:
        return [list(components) for components in components_per_row], []

    deduped_set = set(deduped_components)
    per_row = [
        [component for component in components if component not in deduped_set] for components in components_per_row
    ]
    footer_entries = [(component, counts[component]) for component in deduped_components]
    return per_row, footer_entries


def _render_per_call_notes_footer(footer_entries: list[tuple[str, int]]) -> list[str]:
    if not footer_entries:
        return []
    lines = ["Per-call notes:"]
    for component, count in footer_entries:
        if component == _NO_TRACE_RECORDED_NOTE:
            node_word = "node" if count == 1 else "nodes"
            lines.append(f"  · {count} {node_word} lack trace data — run with --report to populate cache columns.")
        else:
            lines.append(f"  · {count} rows: {component}")
    return lines


def _format_cross_workflow_inputs_note(inputs: tuple[CrossWorkflowInputContribution, ...]) -> str:
    names = tuple(
        (item.child_cache_ref or item.child_input_name)
        if isinstance(item, CrossWorkflowInputContribution)
        else str(item)
        for item in inputs
    )
    if len(names) <= 3:
        return f"cacheable values: {', '.join(names)}"
    return f"cacheable values: {', '.join(names[:3])}, +{len(names) - 3} more"


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
    if row.observed_call_count == 0:
        # Static-mode rows (no trace) had no fallback note before, leaving the
        # row with `cached_now: —`, `could_cache: ?`, `ratio: ?%`, `calls: —`
        # and a blank notes column. The agent saw only placeholders with no
        # explanation or next step. Name the cause and the unblocking action.
        return _NO_TRACE_RECORDED_NOTE
    if row.observed_call_count == 1:
        return "single call; no repeated cache use observed"
    if not row.model:
        return "no stable repeated cache prefix found"
    return f"no stable {get_min_cache_tokens(row.model):,}-token repeated prefix found"


def _format_nullable_int(value: int | None) -> str:
    return f"{value:,}" if value is not None else "?"


def _short_observed_model_name(model: str) -> str:
    return model.removeprefix("gemini/")


def _render_sub_workflow_drill_in(analysis: CacheAnalysis) -> str:
    """Emit a paste-ready block of per-child ``pflow analyze-cache`` commands.

    Each line is a self-contained ``pflow analyze-cache <path>`` runnable
    from the invocation cwd. We never emit ``cd``: agents fire parallel
    Bash calls and cannot reliably share cwd state across invocations,
    and even sequentially the agent's cwd tracker is the only frame they
    can navigate paths from. Paths render cwd-relative when the workflow
    lives under cwd, absolute otherwise.
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
    for entry in llm_bearing:
        lines.append(f"    pflow analyze-cache {_display_path_from_cwd(entry.workflow_path)}")
    return "\n".join(lines)


def _per_call_scope_explainer(
    rows: list[PerCallRow],
    evidence_scope: str = "static_analysis",
    visible_columns: tuple[str, ...] = _PER_CALL_COLUMNS,
) -> list[str]:
    """Return multi-line explainer describing what the per-call columns mean.

    Two modes:

    - **Truncated trace**: the trace covered only an executed subset.
      Distinct lead because partial coverage changes how missing values
      should be interpreted.
    - **All other modes**: one shared block that names each column and
      explains the ``?`` / ``—`` placeholders in the column they appear in.

    Caller renders each string as its own line (indented at the call site).

    The prior version split the all-other-modes case into "steady-state"
    vs "post-run greenfield" leads with a four-bullet block whose last
    line read ``"— means the column does not apply to this row's tier."``
    That phrasing leaked pflow-internal vocabulary (``tier`` is shorthand
    for the ``data_source`` / ``cacheable_data_source`` enum classification)
    into stdout and forced agents to infer enum semantics to read ``—``.
    The collapsed block explains each placeholder where it appears.
    """
    del rows  # kept for call-site stability and older tests that pass rows explicitly
    if evidence_scope == "truncated_trace_executed_subset":
        return ["Executed trace rows are evidence-only; unexecuted rows are marked when shown."]
    bullets: list[str] = []
    if "cached_now" in visible_columns:
        bullets.append("cached_now: tokens served from cache during this run (requires trace).")
    if "could_cache" in visible_columns:
        bullets.append(
            "could_cache: extra tokens that would be cached if you declared/extended `prompt_cache:`. "
            "`?` if not projectable statically. "
            "Numbers below your model's provider minimum won't cache — see notes column."
        )
    if not bullets:
        return []
    return ["How to read each row:", *(f"  · {bullet}" for bullet in bullets)]


def _format_node_list(node_paths: list[str]) -> str:
    """Format a list of node names, aggregating duplicates.

    The same ``node_path`` repeats across rows when distinct sub-workflows
    each contain a node with the same id (lyrics-generator's 8 review
    sub-workflows each name their node ``review``). A bare
    ``", ".join(...)`` produces ``"review, review, review, ..."`` — reads
    as a string-join bug. Aggregate duplicates into ``"N <name> nodes"``
    and preserve first-seen order for unique names.
    """
    from collections import Counter

    counts = Counter(node_paths)
    parts: list[str] = []
    for name in dict.fromkeys(node_paths):  # preserves first-seen order, dedupes
        n = counts[name]
        parts.append(name if n == 1 else f"{n} {name} nodes")
    return ", ".join(parts)


def _per_call_confidence_footer(rows: list[PerCallRow]) -> list[str] | None:
    """Build the multi-line token-estimate-confidence footer block.

    Returns ``["Token estimate confidence:", "  · <bullet>", ...]`` or
    ``None`` when no tier-specific guidance applies. Caller renders each
    string as its own line (indented at the call site).
    """
    low_input_nodes = [row.node_path for row in rows if row.data_source in {"estimator", "heuristic"}]
    batch_exemplar_nodes = [row.node_path for row in rows if row.cacheable_data_source == "parameters" and row.is_batch]
    batch_prefix_nodes = [row.node_path for row in rows if row.cacheable_data_source == "batch_prefix"]
    cross_workflow_nodes = [row.node_path for row in rows if row.cacheable_data_source == "cross_workflow_projection"]
    bullets: list[str] = []
    if low_input_nodes:
        bullets.append(f"Projected input tokens for: {_format_node_list(low_input_nodes)}.")
    if batch_exemplar_nodes:
        bullets.append(
            f"{_format_node_list(batch_exemplar_nodes)}: tokens estimated from the first batch item "
            "as a representative sample. Actual tokens may vary for later items."
        )
    if batch_prefix_nodes:
        # Distinct from the batch-exemplar case above: this projection scans
        # the prompt's static prefix (bytes before the first per-item ref)
        # and multiplies by observed call count or static batch size. No item
        # content participates, so the message must not claim sampling.
        bullets.append(
            f"{_format_node_list(batch_prefix_nodes)}: savings projected from a stable prompt prefix "
            "repeated across the batch. Declare prompt_cache to confirm."
        )
    if cross_workflow_nodes:
        bullets.append(
            f"{_format_node_list(cross_workflow_nodes)}: savings projected from values flowing in "
            "from parent workflow(s). See Recommended actions for the per-boundary fix."
        )
    if not bullets:
        return None
    return ["Token estimate confidence:", *(f"  · {bullet}" for bullet in bullets)]


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
