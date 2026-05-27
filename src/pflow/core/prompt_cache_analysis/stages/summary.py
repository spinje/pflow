"""Summary aggregation stage for prompt-cache analysis."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.llm_providers import detect_provider

from .. import cost_estimation
from ..context import AnalysisContext
from ..types import (
    _PROJECTION_NOT_APPLICABLE,
    _PROJECTION_UNAVAILABLE,
    AnalysisSummary,
    CacheProjection,
    CostDelta,
    PerCallRow,
    SubWorkflowRollup,
    SubWorkflowRollupEntry,
    TraceExecutionIndex,
    TraceUnexecutedLLMRow,
    invocation_count_for,
)
from ..warning_catalog import CACHE_WARNING_CATALOG

logger = logging.getLogger(__name__)


def _is_cache_focused(diag: Diagnostic) -> bool:
    """Whether a diagnostic belongs to provider prompt-cache analysis.

    The analyzer runs the full validator pipeline, but headline counts and
    advisory actions remain cache-domain signals. Catalog-IDed cache findings
    use the cache warning catalog; intentionally un-IDed cache reference errors
    carry paths under ``cache.*`` or containing ``.prompt_cache``.
    """
    if diag.id and diag.id in CACHE_WARNING_CATALOG:
        return True
    path = (diag.context or {}).get("path")
    return isinstance(path, str) and (path.startswith("cache.") or ".prompt_cache" in path)


# ---------------------------------------------------------------------------
# Confidence aggregation — STRICT per DD#34 verbatim
# ---------------------------------------------------------------------------


def _aggregate_confidence(
    rows: list[PerCallRow],
) -> tuple[str, dict[str, int]]:
    """STRICT semantics per DD#34 line 634.

    - ``all rows trace`` → ``high_from_trace``
    - ``all rows in {trace, memo}`` → ``medium_from_memo``
    - ``any estimator/heuristic`` → ``low_no_data``
    """
    sources = [row.data_source for row in rows]
    coverage: dict[str, int] = {
        "trace": sum(1 for s in sources if s == "trace"),
        "memo": sum(1 for s in sources if s == "memo"),
        "estimator": sum(1 for s in sources if s == "estimator"),
        "heuristic": sum(1 for s in sources if s == "heuristic"),
        "total": len(sources),
    }
    if not sources:
        return "low_no_data", coverage
    if all(src == "trace" for src in sources):
        return "high_from_trace", coverage
    if all(src in ("trace", "memo") for src in sources):
        return "medium_from_memo", coverage
    return "low_no_data", coverage


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def _format_workflow_run_command(workflow_path: str | None, inputs: Mapping[str, Any] | None) -> str | None:
    """Compose a paste-ready ``pflow run`` command from a workflow file path
    and its declared inputs.

    Returns ``None`` when no runnable file path exists — inline IR
    (``workflow_path is None``) and ``ir-hash:<md5>`` lookup keys both lack a
    file the agent could re-run. Callers thread the result onto
    :class:`AnalysisSummary` so renderers can surface the command on
    unavailable-cost branches without reaching into the IR themselves.

    Placeholder values (``<value>``) are intentional: greenfield analysis has
    no resolved parameters yet, and showing defaults would imply they're
    required. The agent fills in real values when running.
    """
    if workflow_path is None or workflow_path.startswith("ir-hash:"):
        return None
    parts = [f"pflow run {workflow_path}"]
    for name in inputs or {}:
        parts.append(f"{name}=<value>")
    return " ".join(parts)


def _build_summary(
    rows: list[PerCallRow],
    warnings: list[Diagnostic],
    *,
    ttl: str | None = None,
    ctx: AnalysisContext | None = None,
    edge_child_paths: dict[str, str] | None = None,
    ir_default_model: str | None = None,
    scope_workflow_paths: frozenset[str] | None = None,
    trace_index: TraceExecutionIndex | None = None,
    trace_workflow_relationship: str | None = None,
    drift_count: int = 0,
    sub_workflow_rollup: SubWorkflowRollup | None = None,
    suggested_run_command: str | None = None,
) -> AnalysisSummary:
    """Aggregate per-call rows + warning counts into the spec's summary block.

    Atomic cost primitives (Phase 5):

    - ``compute_projections(rows, ...)`` produces three independent hypothetical
      figures — ``no_cache_hypothetical_usd``,
      ``first_run_with_cache_hypothetical_usd``,
      ``rerun_within_ttl_hypothetical_usd``. Each carries one meaning;
      the renderer chooses which to show based on context.
    - ``compute_actually_paid(rows, trace, ...)`` produces the trace-driven
      ``actually_paid_usd`` + ``actually_paid_tier`` (``UNAVAILABLE`` for
      greenfield).

    No field is overloaded — agents reading any single primitive know
    exactly what it means independent of greenfield/trace context.

    Absolute hypothetical figures still require output token data per the
    tri-state contract (``None`` on greenfield without memo, real after at
    least one run, partial when some priced rows have memo data and others
    don't). Aggregate savings figures are input-only (output cost cancels)
    and therefore work on greenfield even when absolutes stay ``None``.
    """
    total_nodes = len(rows)
    # Phase 6 split: count root rows vs sub-workflow rows. Mirrors the
    # text renderer's previous inline ``sum(...)`` comprehensions in
    # ``_format_sub_workflow_breakdown_line`` so JSON consumers see the
    # same numbers without recomputing. ``ctx.workflow_path is None``
    # covers the inline-IR case where the analyzed workflow has no
    # resolved path — matches the existing ``or`` pattern in
    # ``render_text._format_sub_workflow_breakdown_line``.
    root_workflow_path = ctx.workflow_path if ctx is not None else None
    root_count = sum(1 for row in rows if root_workflow_path is None or row.workflow_path == root_workflow_path)
    sub_workflow_count = total_nodes - root_count
    total_invocations, dynamic_batch_count = _estimate_total_invocations(rows)
    total_input = sum(r.input_tokens_estimated * invocation_count_for(r) for r in rows)
    # ``cacheable_tokens_estimated`` may be ``None`` for greenfield rows
    # without memo (Option C — projection unmeasurable). Sum only the known
    # values; None rows contribute 0 to the aggregate (honest "we don't know"
    # rather than fabricated 0). Top-level summary still useful — agents
    # see the partial signal from steady-state / post-run rows.
    total_cacheable = sum((r.cacheable_tokens_estimated or 0) * invocation_count_for(r) for r in rows)
    total_cache_active = sum((r.cache_active.tokens_estimated or 0) * invocation_count_for(r) for r in rows)
    total_cache_ready = sum((r.cache_ready.tokens_estimated or 0) * invocation_count_for(r) for r in rows)
    total_cache_opportunity = sum((r.cache_opportunity.tokens_estimated or 0) * invocation_count_for(r) for r in rows)
    unknown_ready = sum(
        1
        for r in rows
        if r.cache_ready.data_source not in {_PROJECTION_NOT_APPLICABLE, _PROJECTION_UNAVAILABLE}
        and r.cache_ready.tokens_estimated is None
    )
    unknown_opportunity = sum(
        1
        for r in rows
        if r.cache_opportunity.data_source not in {_PROJECTION_NOT_APPLICABLE, _PROJECTION_UNAVAILABLE}
        and r.cache_opportunity.tokens_estimated is None
    )
    lower_ready = sum(1 for r in rows if r.cache_ready.confidence == "lower_bound")
    lower_opportunity = sum(1 for r in rows if r.cache_opportunity.confidence == "lower_bound")
    trace_coverage, executed_count, unexecuted_nodes = _trace_coverage_for_rows(rows, ctx)
    models_observed_in_trace = tuple(sorted({model for row in rows for model in row.observed_models}))
    # Stage C.1: heterogeneous rows have ``model = ""`` AND
    # ``model_is_heterogeneous = True``. The ``if r.model`` truthy check below
    # already short-circuits empty strings — the explicit
    # ``not r.model_is_heterogeneous`` clause is defense-in-depth so future
    # contributors who change the empty-string convention don't silently leak
    # ``${item.model}`` literals back into the aggregate.
    static_models = {r.model for r in rows if r.model and not r.model_is_heterogeneous}
    model_set = static_models | (set(models_observed_in_trace) if trace_coverage == "complete" else set())
    models = sorted(model_set)
    heterogeneous_paths = tuple(sorted(r.node_path for r in rows if r.model_is_heterogeneous))
    cache_focused = [d for d in warnings if _is_cache_focused(d)]
    blocking_errors = sum(1 for d in cache_focused if d.severity == Severity.ERROR)
    warnings_count = sum(1 for d in cache_focused if d.severity == Severity.WARNING)
    info_count = sum(1 for d in cache_focused if d.severity == Severity.INFO)
    actionable = warnings_count + info_count

    output_tokens_by_node: Mapping[tuple[str | None, str] | str, int | None] = {
        (r.workflow_path, r.node_path): r.output_tokens_estimated for r in rows
    }
    projections = cost_estimation.compute_projections(rows, output_tokens_by_node=output_tokens_by_node, ttl=ttl)
    actually_paid = cost_estimation.compute_actually_paid(
        rows,
        trace=ctx.trace if ctx is not None else None,
        edges=edge_child_paths,
        scope_workflow_paths=scope_workflow_paths,
    )

    # Partial flag: actually-paid trace_partial OR projection partial. The
    # renderer uses one boolean to decide whether to mark numbers as
    # incomplete (which can happen on EITHER stream independently).
    partial_cost_usd = actually_paid.tier == cost_estimation.CostTier.TRACE_PARTIAL or projections.partial

    no_cache_baseline = "no_cache_hypothetical_usd"
    first_run_delta = _cost_delta(
        baseline_value=projections.no_cache_hypothetical_usd,
        compared_value=projections.first_run_with_cache_hypothetical_usd,
        baseline=no_cache_baseline,
        compared_to="first_run_with_cache_hypothetical_usd",
    )
    rerun_delta = _cost_delta(
        baseline_value=projections.no_cache_hypothetical_usd,
        compared_value=projections.rerun_within_ttl_hypothetical_usd,
        baseline=no_cache_baseline,
        compared_to="rerun_within_ttl_hypothetical_usd",
    )
    if trace_coverage == "none":
        actual_vs_no_cache_delta = _unavailable_delta(
            no_cache_baseline,
            "actually_paid_usd",
            reason="no_trace",
        )
    elif projections.absolute_exclusions:
        # Projection cohort excludes some rows (heterogeneous batch, unpriced
        # model, etc.). Compute savings on the priced subset when total paid
        # is known and the projection cohort has at least one priced row to
        # compare against; otherwise the comparison stays genuinely
        # unavailable (renderer's elif branch surfaces the exclusion list).
        # Each excluded row's cost was already attributed to actually_paid
        # under the same coercion rule as ``row.cost_usd`` (trace_tree treats
        # unpriced events as 0.0 in both totals), so the subtraction is
        # internally consistent. Per-exclusion None values are coerced to 0.0.
        excluded = projections.absolute_exclusions
        no_cache = projections.no_cache_hypothetical_usd
        if actually_paid.total_usd is not None and no_cache is not None and no_cache > 0:
            excluded_total = sum((e.actual_cost_usd or 0.0) for e in excluded)
            actually_paid_subset = actually_paid.total_usd - excluded_total
            excluded_paths = tuple(
                e.node_path
                for e in sorted(
                    excluded,
                    key=lambda x: (x.workflow_path or "", x.node_path),
                )
            )
            actual_vs_no_cache_delta = _cost_delta(
                baseline_value=no_cache,
                compared_value=actually_paid_subset,
                baseline=no_cache_baseline,
                compared_to="actually_paid_priced_cohort_usd",
                excluded_nodes=excluded_paths,
            )
        else:
            actual_vs_no_cache_delta = _unavailable_delta(
                no_cache_baseline,
                "actually_paid_usd",
                reason="projection_exclusions",
            )
    else:
        actual_vs_no_cache_delta = _cost_delta(
            baseline_value=projections.no_cache_hypothetical_usd,
            compared_value=actually_paid.total_usd,
            baseline=no_cache_baseline,
            compared_to="actually_paid_usd",
        )

    # Trace transparency fields: only populated when a trace was actually
    # loaded (autoload or explicit). ``trace_data is None`` → both fields
    # stay ``None`` (renderer reads ``analysis.trace_path`` to decide
    # whether to show the header line). Back-compat fallback mirrors
    # ``_trace_coverage_for_rows``: absent ``final_status`` → ``"success"``.
    if ctx is not None and ctx.trace_data is not None:
        trace_final_status: str | None = str(ctx.trace_data.get("final_status") or "success")
        recorded = ctx.trace_data.get("start_time")
        trace_recorded_at: str | None = str(recorded) if recorded is not None else None
    else:
        trace_final_status = None
        trace_recorded_at = None

    return AnalysisSummary(
        actually_paid_usd=actually_paid.total_usd,
        actually_paid_tier=actually_paid.tier,
        no_cache_hypothetical_usd=projections.no_cache_hypothetical_usd,
        first_run_with_cache_hypothetical_usd=projections.first_run_with_cache_hypothetical_usd,
        rerun_within_ttl_hypothetical_usd=projections.rerun_within_ttl_hypothetical_usd,
        first_run_delta=first_run_delta,
        rerun_delta=rerun_delta,
        actual_vs_no_cache_delta=actual_vs_no_cache_delta,
        trace_coverage=trace_coverage,
        evidence_scope=_evidence_scope_for_trace_coverage(trace_coverage),
        trace_llm_nodes_static=total_nodes,
        trace_llm_nodes_executed=executed_count,
        trace_unexecuted_llm_rows=unexecuted_nodes,
        blocking_errors=blocking_errors,
        actionable_opportunities=actionable,
        warnings_count=warnings_count,
        info_count=info_count,
        total_llm_nodes_estimated=total_nodes,
        total_llm_invocations_estimated=total_invocations,
        dynamic_batch_node_count=dynamic_batch_count,
        total_input_tokens_estimated=total_input,
        total_cacheable_tokens_estimated=total_cacheable,
        total_cache_active_tokens_estimated=total_cache_active,
        total_cache_ready_tokens_estimated=total_cache_ready,
        total_cache_opportunity_tokens_estimated=total_cache_opportunity,
        total_cache_ready_confidence=_aggregate_projection_confidence(row.cache_ready for row in rows),
        total_cache_opportunity_confidence=_aggregate_projection_confidence(row.cache_opportunity for row in rows),
        unknown_cache_ready_row_count=unknown_ready,
        unknown_cache_opportunity_row_count=unknown_opportunity,
        lower_bound_cache_ready_row_count=lower_ready,
        lower_bound_cache_opportunity_row_count=lower_opportunity,
        models_in_use=tuple(models),
        observed_models_in_trace=models_observed_in_trace,
        ir_default_model=ir_default_model,
        partial_cost_usd=partial_cost_usd,
        unavailable_models=projections.unavailable_models,
        unavailable_models_by_workflow=_unavailable_models_by_workflow(rows),
        heterogeneous_model_node_count=len(heterogeneous_paths),
        heterogeneous_model_node_paths=heterogeneous_paths,
        root_llm_node_count=root_count,
        sub_workflow_llm_node_count=sub_workflow_count,
        projection_exclusions=projections.absolute_exclusions,
        trace_final_status=trace_final_status,
        trace_workflow_relationship=trace_workflow_relationship,
        trace_model_drift_count=drift_count,
        trace_recorded_at=trace_recorded_at,
        trace_provider_llm_call_count=trace_index.provider_llm_call_count if trace_index is not None else 0,
        trace_local_memo_llm_hit_count=trace_index.local_memo_llm_hit_count if trace_index is not None else 0,
        trace_local_in_process_llm_hit_count=(
            trace_index.local_in_process_llm_hit_count if trace_index is not None else 0
        ),
        trace_local_cache_input_tokens=trace_index.local_cache_input_tokens if trace_index is not None else 0,
        trace_provider_cache_creation_input_tokens=(
            trace_index.provider_cache_creation_input_tokens if trace_index is not None else 0
        ),
        trace_provider_cache_read_input_tokens=(
            trace_index.provider_cache_read_input_tokens if trace_index is not None else 0
        ),
        sub_workflow_rollup=sub_workflow_rollup,
        suggested_run_command=suggested_run_command,
        stale_memo_skipped_count=len(ctx.stale_memo_skipped) if ctx is not None else 0,
        stale_memo_uncheckable_count=len(ctx.stale_memo_uncheckable) if ctx is not None else 0,
    )


def _trace_coverage_for_rows(
    rows: list[PerCallRow],
    ctx: AnalysisContext | None,
) -> tuple[str, int, tuple[TraceUnexecutedLLMRow, ...]]:
    """Classify trace coverage over the static LLM rows.

    Returns ``"truncated"`` only when the trace's ``final_status`` is
    ``"failed"`` AND some static rows didn't execute (workflow died mid-run,
    cost-projection cohort genuinely incomplete). Returns ``"complete"``
    otherwise — including the case where ``final_status`` is success but
    some rows didn't execute, which is normal conditional dispatch
    (a router routes inputs to one of N branches; only one fires).

    The ``final_status`` field is written by
    ``runtime/workflow_trace.py::WorkflowTraceCollector`` from per-node
    final-event success/failure (see ``_determine_trace_status``).
    Defensively defaults to ``"success"`` when missing (legacy 2.0.0
    fixtures, hand-built test traces).
    """
    if ctx is None or ctx.trace_data is None:
        return "none", 0, ()
    unexecuted = tuple(
        TraceUnexecutedLLMRow(workflow_path=row.workflow_path, node_path=row.node_path)
        for row in sorted(
            (row for row in rows if row.did_not_execute_in_trace),
            key=lambda row: (row.workflow_path or "", row.node_path),
        )
    )
    executed = len(rows) - len(unexecuted)
    if not rows:
        return "complete", 0, ()
    final_status = str(ctx.trace_data.get("final_status") or "success")
    if unexecuted and final_status == "failed":
        return "truncated", executed, unexecuted
    return "complete", executed, unexecuted


def _evidence_scope_for_trace_coverage(trace_coverage: str) -> str:
    if trace_coverage == "truncated":
        return "truncated_trace_executed_subset"
    if trace_coverage == "complete":
        return "complete_trace"
    return "static_analysis"


def _aggregate_projection_confidence(projections: Iterable[CacheProjection]) -> str:
    values = {
        projection.confidence
        for projection in projections
        if projection.data_source not in {_PROJECTION_NOT_APPLICABLE, _PROJECTION_UNAVAILABLE}
    }
    if not values or "unknown" in values:
        return "unknown"
    if "lower_bound" in values:
        return "lower_bound"
    if values == {"observed"}:
        return "observed"
    return "exact"


def _filter_trace_dependent_warnings(warnings: list[Diagnostic]) -> list[Diagnostic]:
    """Drop diagnostics whose catalog spec opts in via ``requires_complete_trace``.

    Applied only when ``trace_coverage == "truncated"`` (workflow died mid-run,
    so cost-projection cohorts are misleading). IR-derived findings (the
    default) flow regardless because they describe workflow structure, not
    execution evidence — the contract documented at
    ``prompt_cache_analysis/CLAUDE.md`` § "Trace Loading".

    Lookup mirrors ``resolve_headline_for`` (warning_catalog.py:1236-1238) —
    catalog SSoT consulted by ID at runtime.
    """
    return [
        warning
        for warning in warnings
        if not (
            warning.id
            and warning.id in CACHE_WARNING_CATALOG
            and CACHE_WARNING_CATALOG[warning.id].requires_complete_trace
        )
    ]


def _cost_delta(
    *,
    baseline_value: float | None,
    compared_value: float | None,
    baseline: str,
    compared_to: str,
    excluded_nodes: tuple[str, ...] = (),
) -> CostDelta:
    if baseline_value is None or compared_value is None or baseline_value <= 0:
        return _unavailable_delta(baseline, compared_to)
    delta = baseline_value - compared_value
    if abs(delta) < 0.0000001:
        return CostDelta(
            amount_usd=0.0,
            pct_of_baseline=0,
            kind="break_even",
            baseline=baseline,
            compared_to=compared_to,
            excluded_nodes=excluded_nodes,
        )
    return CostDelta(
        amount_usd=abs(delta),
        pct_of_baseline=round(100 * abs(delta) / baseline_value),
        kind="savings" if delta > 0 else "cost_increase",
        baseline=baseline,
        compared_to=compared_to,
        excluded_nodes=excluded_nodes,
    )


def _unavailable_delta(baseline: str, compared_to: str, *, reason: str | None = None) -> CostDelta:
    return CostDelta(
        amount_usd=None,
        pct_of_baseline=None,
        kind="unavailable",
        baseline=baseline,
        compared_to=compared_to,
        unavailable_reason=reason,
    )


def _estimate_total_invocations(rows: list[PerCallRow]) -> tuple[int | None, int]:
    """Estimate runtime LLM invocations from static sizes or observed trace counts."""
    total = 0
    dynamic_batch_count = 0
    for row in rows:
        if row.is_batch and row.batch_size_estimated is None and row.observed_call_count <= 0:
            dynamic_batch_count += 1
        else:
            total += invocation_count_for(row)
    if dynamic_batch_count:
        return None, dynamic_batch_count
    return total, dynamic_batch_count


def _unavailable_models_by_workflow(rows: list[PerCallRow]) -> dict[str | None, tuple[str, ...]]:
    """Return unpriced models grouped by workflow path for JSON/text attribution."""
    grouped: dict[str | None, set[str]] = {}
    for row in rows:
        if row.did_not_execute_in_trace or row.model_is_heterogeneous or not row.model:
            continue
        if cost_estimation.get_model_pricing(row.model) is None:
            grouped.setdefault(row.workflow_path, set()).add(row.model)
    return {workflow_path: tuple(sorted(models)) for workflow_path, models in grouped.items()}


def _safe_pct_or_none(numerator: float | None, denominator: float | None) -> int | None:
    """Compute a percent only when both numerator and denominator are real."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(100 * numerator / denominator)


# ---------------------------------------------------------------------------
# Gemini telemetry note (Spike 1 outcome — last in note ordering)
# ---------------------------------------------------------------------------


_GEMINI_TELEMETRY_NOTE = (
    "Gemini caching: Gemini reports cache reads via 'cache_read_input_tokens' "
    "in trace events. Cache writes don't show in telemetry, so verify caching "
    "is working by checking that follow-up calls show cache reads. Explicit "
    "## Cache declarations are required for Gemini."
)


def _maybe_append_gemini_note(rows: list[PerCallRow], notes: list[str]) -> None:
    """Append the Gemini telemetry note if any analyzed call targets Gemini."""
    for row in rows:
        if not row.model:
            continue
        try:
            provider_info = detect_provider(row.model)
        except Exception:
            # detect_provider raises on malformed model strings; the row is
            # still analyzable — skip the gemini note for it but surface at
            # debug so a typo isn't completely silent.
            logger.debug("detect_provider failed for model %r", row.model, exc_info=True)
            continue
        if provider_info is None:
            continue
        if provider_info.name == "gemini":
            notes.append(_GEMINI_TELEMETRY_NOTE)
            return


def _build_sub_workflow_rollup(
    cw_result: Any,
    root_workflow_path: str,
    *,
    rows: list[PerCallRow],
    trace_index: TraceExecutionIndex,
    ttl: str | None,
    notes: list[str],
) -> SubWorkflowRollup | None:
    """Build metadata and dollar attribution for included child workflows."""
    workflows = [path for path in getattr(cw_result, "irs_by_workflow", {}) if path != root_workflow_path]
    if not workflows:
        return None
    parent_by_child: dict[str, str] = {}
    for edge in getattr(cw_result, "edges", ()) or ():
        child = str(getattr(edge, "child_workflow", ""))
        parent_by_child.setdefault(child, str(getattr(edge, "parent_node_id", "")))
    rows_by_workflow: dict[str | None, list[PerCallRow]] = {}
    for row in rows:
        rows_by_workflow.setdefault(row.workflow_path, []).append(row)
    entries_list: list[SubWorkflowRollupEntry] = []
    for path in sorted(workflows):
        workflow_rows = rows_by_workflow.get(path, [])
        output_tokens: Mapping[tuple[str | None, str] | str, int | None] = {
            (row.workflow_path, row.node_path): row.output_tokens_estimated for row in workflow_rows
        }
        projections = cost_estimation.compute_projections(workflow_rows, output_tokens_by_node=output_tokens, ttl=ttl)
        entries_list.append(
            SubWorkflowRollupEntry(
                workflow_path=str(path),
                called_by_node_id=parent_by_child.get(str(path), ""),
                llm_node_count=_count_llm_nodes(getattr(cw_result, "irs_by_workflow", {}).get(path, {})),
                actually_paid_usd=trace_index.current_cost_by_workflow.get(path),
                no_cache_hypothetical_usd=projections.no_cache_hypothetical_usd,
                first_run_with_cache_hypothetical_usd=projections.first_run_with_cache_hypothetical_usd,
                rerun_within_ttl_hypothetical_usd=projections.rerun_within_ttl_hypothetical_usd,
            )
        )
    truncated = _has_cross_workflow_truncation(notes)
    return SubWorkflowRollup(
        workflows_included=tuple(entry.workflow_path for entry in entries_list),
        max_depth_walked=len(entries_list),
        truncated=truncated,
        per_workflow=tuple(entries_list),
    )


def _has_cross_workflow_truncation(notes: list[str]) -> bool:
    return any(
        "Cross-workflow walker reached max_depth" in note or "Cross-workflow walker detected cycle" in note
        for note in notes
    )


def _count_llm_nodes(ir: dict[str, Any]) -> int:
    return sum(1 for node in ir.get("nodes", []) or [] if isinstance(node, dict) and node.get("type") == "llm")
