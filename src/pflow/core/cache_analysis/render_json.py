"""JSON rendering for ``pflow analyze-cache --format=json`` and the MCP tool.

Current shape: ``warnings`` is the raw diagnostic list; ``blocking_errors``,
``other_blocking_errors``, ``recommended_actions``, and ``cross_workflow`` are
derived views over it. Text mode hides empty sections, while JSON always emits
empty arrays so agents can treat absence as a positive signal.

Empty-array contract: ``cross_workflow.*`` arrays are always present (empty
when no findings). ``blocking_errors``, ``other_blocking_errors``, and
``recommended_actions`` follow the same contract.

Domain split (B-9 fix): ``blocking_errors[]`` carries cache-domain ERRORs only
(matches ``summary.blocking_errors`` count). Non-cache validator ERRORs go to
``other_blocking_errors[]``.
"""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import Diagnostic

from .analyze import CacheAnalysis, CostDelta, PerCallRow, RecommendedAction, SuggestedBlock


def render_json(analysis: CacheAnalysis) -> dict[str, Any]:
    """Render the analyzer result as the agent-facing JSON dict.

    Output shape mirrors spec § "Output Format — JSON" verbatim. Reuses
    :meth:`Diagnostic.to_dict` for warnings so agents see the same shape they
    get from any other pflow diagnostic surface.

    ``blocking_errors``, ``other_blocking_errors``, and ``recommended_actions``
    are computed on demand from ``analysis.warnings`` via ``view_helpers``;
    cross-workflow alignment findings (rename, prose-mismatch) are excluded
    from both ranked lists and surfaced under ``cross_workflow.*``.

    B-9 split: ``blocking_errors[]`` carries cache-domain ERRORs (matches
    ``summary.blocking_errors`` count); non-cache validator ERRORs go to
    ``other_blocking_errors[]``.
    """
    # Local import: ``JSON_FORMAT_VERSION`` lives at the package root for
    # consumer-side reachability; importing here avoids a circular ref between
    # ``__init__.py`` and the renderers.
    from . import JSON_FORMAT_VERSION
    from .view_helpers import build_blocking_errors, build_other_blocking_errors, build_recommended_actions

    blocking = build_blocking_errors(list(analysis.warnings))
    other_blocking = build_other_blocking_errors(list(analysis.warnings))
    actions = build_recommended_actions(list(analysis.warnings))
    return {
        # First key — agents version-gate via ``startswith(MAJOR + ".")`` per
        # the consumer rule documented in ``cache_analysis/__init__.py``.
        "format_version": JSON_FORMAT_VERSION,
        "workflow_path": analysis.workflow_path,
        "analyzed_at": analysis.analyzed_at,
        "estimate_confidence": analysis.estimate_confidence,
        "estimate_confidence_coverage": dict(analysis.estimate_confidence_coverage),
        "trace_path": analysis.trace_path,
        "summary": _summary_to_dict(analysis),
        "blocking_errors": [_action_to_dict(a) for a in blocking],
        "other_blocking_errors": [_action_to_dict(a) for a in other_blocking],
        "recommended_actions": [_action_to_dict(a) for a in actions],
        "suggested_blocks": [_block_to_dict(b) for b in analysis.suggested_blocks],
        "per_call": [_per_call_to_dict(r) for r in analysis.per_call],
        "cross_workflow": _cross_workflow_to_dict(analysis),
        "warnings": [_warning_to_dict(w) for w in analysis.warnings],
        "notes": list(analysis.notes),
    }


def _summary_to_dict(analysis: CacheAnalysis) -> dict[str, Any]:
    s = analysis.summary
    return {
        # Atomic cost primitives. Each field carries one meaning.
        # ``actually_paid_usd`` is ``null`` for greenfield (no trace);
        # the three hypothetical fields are projections from IR rows.
        "actually_paid_usd": s.actually_paid_usd,
        "actually_paid_tier": s.actually_paid_tier.value,
        "no_cache_hypothetical_usd": s.no_cache_hypothetical_usd,
        "first_run_with_cache_hypothetical_usd": s.first_run_with_cache_hypothetical_usd,
        "rerun_within_ttl_hypothetical_usd": s.rerun_within_ttl_hypothetical_usd,
        "first_run_delta": _delta_to_dict(s.first_run_delta),
        "rerun_delta": _delta_to_dict(s.rerun_delta),
        "actual_vs_no_cache_delta": _delta_to_dict(s.actual_vs_no_cache_delta),
        "trace_coverage": s.trace_coverage,
        "evidence_scope": s.evidence_scope,
        "trace_llm_nodes_static": s.trace_llm_nodes_static,
        "trace_llm_nodes_executed": s.trace_llm_nodes_executed,
        "trace_unexecuted_llm_rows": [
            {
                "workflow_path": row.workflow_path,
                "node_path": row.node_path,
            }
            for row in s.trace_unexecuted_llm_rows
        ],
        "blocking_errors": s.blocking_errors,
        "actionable_opportunities": s.actionable_opportunities,
        "warnings_count": s.warnings_count,
        "info_count": s.info_count,
        "total_llm_nodes_estimated": s.total_llm_nodes_estimated,
        "total_llm_invocations_estimated": s.total_llm_invocations_estimated,
        "dynamic_batch_node_count": s.dynamic_batch_node_count,
        "total_input_tokens_estimated": s.total_input_tokens_estimated,
        "total_cacheable_tokens_estimated": s.total_cacheable_tokens_estimated,
        "models_in_use": list(s.models_in_use),
        "ir_default_model": s.ir_default_model,
        "observed_models_in_trace": list(s.observed_models_in_trace),
        "partial_cost_usd": s.partial_cost_usd,
        "unavailable_models": list(s.unavailable_models),
        "unavailable_models_by_workflow": {
            str(workflow_path): list(models)
            for workflow_path, models in (s.unavailable_models_by_workflow or {}).items()
        },
        "projection_exclusions": [
            {
                "workflow_path": exclusion.workflow_path,
                "node_path": exclusion.node_path,
                "reason": exclusion.reason,
                "actual_cost_usd": exclusion.actual_cost_usd,
            }
            for exclusion in s.projection_exclusions
        ],
        # Heterogeneous batch sub-workflows whose ``model: ${item.model}``
        # can't be aggregated as one model.
        # Excluded from ``models_in_use`` so the literal template doesn't
        # leak into the rendered list. Node paths surfaced separately so
        # agents can see WHICH nodes vary without scanning ``per_call[]``.
        "heterogeneous_model_node_count": s.heterogeneous_model_node_count,
        "heterogeneous_model_node_paths": list(s.heterogeneous_model_node_paths),
        # Root vs sub-workflow LLM node count split. Text renderer reads
        # from these fields too, so JSON and text stay equivalent for the
        # breakdown line.
        "root_llm_node_count": s.root_llm_node_count,
        "sub_workflow_llm_node_count": s.sub_workflow_llm_node_count,
        "sub_workflow_rollup": _sub_workflow_rollup_to_dict(s.sub_workflow_rollup),
        # Paste-ready ``pflow run`` command for greenfield "run once" hints.
        # ``null`` for inline IR or ``ir-hash:`` lookup keys (no file path
        # the agent can re-run). See ``AnalysisSummary.suggested_run_command``.
        "suggested_run_command": s.suggested_run_command,
    }


def _delta_to_dict(delta: CostDelta) -> dict[str, Any]:
    return {
        "amount_usd": delta.amount_usd,
        "pct_of_baseline": delta.pct_of_baseline,
        "kind": delta.kind,
        "baseline": delta.baseline,
        "compared_to": delta.compared_to,
        "unavailable_reason": delta.unavailable_reason,
        "excluded_nodes": list(delta.excluded_nodes),
    }


def _sub_workflow_rollup_to_dict(rollup: Any) -> dict[str, Any] | None:
    if rollup is None:
        return None
    return {
        "workflows_included": list(rollup.workflows_included),
        "max_depth_walked": rollup.max_depth_walked,
        "truncated": rollup.truncated,
        "per_workflow": [
            {
                "workflow_path": entry.workflow_path,
                "called_by_node_id": entry.called_by_node_id,
                "llm_node_count": entry.llm_node_count,
                # Mirrors AnalysisSummary's atomic cost primitives at
                # child-workflow scope. ``actually_paid_usd`` is sourced from
                # the trace execution index for this child's workflow_path;
                # the hypotheticals come from this child's IR row projections.
                "actually_paid_usd": entry.actually_paid_usd,
                "no_cache_hypothetical_usd": entry.no_cache_hypothetical_usd,
                "first_run_with_cache_hypothetical_usd": entry.first_run_with_cache_hypothetical_usd,
                "rerun_within_ttl_hypothetical_usd": entry.rerun_within_ttl_hypothetical_usd,
            }
            for entry in rollup.per_workflow
        ],
    }


def _action_to_dict(action: RecommendedAction) -> dict[str, Any]:
    return {
        "rank": action.rank,
        "warning_id": action.warning_id,
        "node_id": action.node_id,
        "estimated_savings_usd": action.estimated_savings_usd,
        # ``scope_workflow`` is set whenever the finding carries a workflow
        # location, including per-node diagnostics. Same-id nodes can appear in
        # parent and child workflows, so consumers dispatch on
        # ``(node_id, scope_workflow)`` when both are populated.
        "scope_workflow": action.scope_workflow,
        "message": action.message,
        "suggestions": list(action.suggestions),
    }


def _block_to_dict(block: SuggestedBlock) -> dict[str, Any]:
    return {
        "target_file": block.target_file,
        "ttl": block.ttl,
        "chunks": [
            {
                "name": c.name,
                "var": c.var,
                "size_tokens_est": c.size_tokens_est,
                "prose_placeholder": c.prose_placeholder,
            }
            for c in block.chunks
        ],
        "per_node_assignments": dict(block.per_node_assignments),
        "estimated_savings_usd": block.estimated_savings_usd,
        # Task 159 follow-up: per-node prompt-body refs to remove so the
        # analyzer's prompt_cache: recommendation isn't silently cancelled
        # by inline duplication. Empty dict when no overlaps exist.
        "prompt_body_cleanup": dict(block.prompt_body_cleanup),
        # dict[node_id, {model, min_tokens, total_tokens, meets_threshold}]
        "per_node_thresholds": dict(block.per_node_thresholds),
    }


def _per_call_to_dict(row: PerCallRow) -> dict[str, Any]:
    return {
        "node_path": row.node_path,
        "workflow_path": row.workflow_path,
        "model": row.model,
        "is_batch": row.is_batch,
        "batch_size_estimated": row.batch_size_estimated,
        "input_tokens_estimated": row.input_tokens_estimated,
        "output_tokens_estimated": row.output_tokens_estimated,
        "output_data_source": row.output_data_source,
        "cacheable_tokens_estimated": row.cacheable_tokens_estimated,
        "cache_ratio_pct": row.cache_ratio_pct,
        "cache_creation_input_tokens": row.cache_creation_input_tokens,
        "cache_read_input_tokens": row.cache_read_input_tokens,
        "data_source": row.data_source,
        # Independent tier label for the cacheable metric. Sources:
        # ``"trace"``, ``"memo"``, ``"parameters"``, ``"unavailable"``.
        # Independent from ``data_source`` (input) — the two may legitimately
        # diverge (e.g., trace fires for input but cacheable falls through
        # to memo when ``cache_creation+cache_read == 0``).
        "cacheable_data_source": row.cacheable_data_source,
        "declared_prompt_cache": row.declared_prompt_cache,
        # Stage C.1 (2.0 minor-additive): True when the IR's ``params.model``
        # was an unresolved ``${...}`` template (heterogeneous batch
        # sub-workflow). When True, ``model`` is the empty string so consumers
        # have a single clear discriminator.
        "model_is_heterogeneous": row.model_is_heterogeneous,
        # Track A (2.1 minor-additive): per-node recorded cost from trace.
        # ``null`` when no trace data — see ``cost_data_source`` for the
        # 4-state tier label.
        "cost_usd": row.cost_usd,
        "cost_data_source": row.cost_data_source,
        "did_not_execute_in_trace": row.did_not_execute_in_trace,
        "observed_models": list(row.observed_models),
        "observed_call_count": row.observed_call_count,
        # Stage 0.3 (Task 159): per-call ``warnings`` array dropped — production
        # never populated it. JSON consumers needing per-row warning markers
        # filter ``warnings[]`` (top-level) by ``node_id``.
    }


def _cross_workflow_to_dict(analysis: CacheAnalysis) -> dict[str, Any]:
    """Empty-array contract: always present, even when no findings.

    Stage 0 (Task 159): the three arrays are DERIVED from ``analysis.warnings``
    by filtering on ``Diagnostic.id``. Pre-Stage-0, the same Diagnostics were
    duplicated on ``analysis.cross_workflow.{rename_detections, prose_mismatches,
    value_flow_opportunities}`` AND in ``analysis.warnings`` — that
    pre-computed-view smell is gone. JSON shape preserved for consumer
    compatibility (1.x → 2.x bump documents the source change in the
    version-history block at module top).

    Filter discriminators:
    - ``rename_detections``: ``Diagnostic.id == "cache.cross-workflow-rename-detected"``
    - ``prose_mismatches``: ``Diagnostic.id == "cache.cross-workflow-prose-mismatch"``
    - ``value_flow_opportunities``:
      ``Diagnostic.id == "cache.sub-workflow-cache-undeclared"``.
    """
    cf = analysis.cross_workflow
    return {
        "boundaries_analyzed": cf.boundaries_analyzed,
        "rename_detections": [
            _warning_to_dict(d) for d in analysis.warnings if d.id == "cache.cross-workflow-rename-detected"
        ],
        "prose_mismatches": [
            _warning_to_dict(d) for d in analysis.warnings if d.id == "cache.cross-workflow-prose-mismatch"
        ],
        "value_flow_opportunities": [
            _warning_to_dict(d) for d in analysis.warnings if d.id == "cache.sub-workflow-cache-undeclared"
        ],
    }


def _warning_to_dict(diag: Diagnostic) -> dict[str, Any]:
    return diag.to_dict()


__all__ = ["render_json"]
