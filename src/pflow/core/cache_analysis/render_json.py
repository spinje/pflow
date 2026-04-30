"""JSON rendering for ``pflow analyze-cache --format=json`` and the MCP tool.

Format-version policy locked at this module:

- Current version is :data:`JSON_FORMAT_VERSION` (current literal ``"1.0"``).
- Consumer rule: ``format_version.startswith(JSON_FORMAT_VERSION_MAJOR + ".")``.
  Minor bumps (``1.0`` → ``1.1``) are additive; major bumps (``2.x``) are
  breaking. Mirrors the trace ``2.x`` policy at ``trace_report.py:463``.

The constants live here (where they're used) and the package ``__init__``
re-exports them for the public API surface. Top-10% precedent: pytest's
``__version__`` lives in ``pytest/__init__.py`` because that's the public
boundary; we mirror that convention without the upward-import circularity.

Empty-array contract: ``cross_workflow.*`` arrays are always present (empty
when no findings). Text mode hides empty sections; JSON exposes them so
agents can treat absence as a positive signal.
"""

from __future__ import annotations

from typing import Any, Final

from pflow.core.diagnostic import Diagnostic

from .analyze import CacheAnalysis, PerCallRow, RecommendedAction, SuggestedBlock

JSON_FORMAT_VERSION: Final[str] = "1.0"
"""Current JSON output format version. Bump minor on additive changes."""

JSON_FORMAT_VERSION_MAJOR: Final[str] = "1"
"""Major version prefix. Consumer rule: ``format_version.startswith("1.")``."""


def render_json(analysis: CacheAnalysis) -> dict[str, Any]:
    """Render the analyzer result as the agent-facing JSON dict.

    Output shape mirrors spec § "Output Format — JSON" verbatim. Reuses
    :meth:`Diagnostic.to_dict` for warnings so agents see the same shape they
    get from any other pflow diagnostic surface.
    """
    return {
        "format_version": JSON_FORMAT_VERSION,
        "workflow_path": analysis.workflow_path,
        "analyzed_at": analysis.analyzed_at,
        "estimate_confidence": analysis.estimate_confidence,
        "estimate_confidence_coverage": dict(analysis.estimate_confidence_coverage),
        "trace_path": analysis.trace_path,
        "summary": _summary_to_dict(analysis),
        "recommended_actions": [_action_to_dict(a) for a in analysis.recommended_actions],
        "suggested_blocks": [_block_to_dict(b) for b in analysis.suggested_blocks],
        "per_call": [_per_call_to_dict(r) for r in analysis.per_call],
        "cross_workflow": _cross_workflow_to_dict(analysis),
        "warnings": [_warning_to_dict(w) for w in analysis.warnings],
        "notes": list(analysis.notes),
    }


def _summary_to_dict(analysis: CacheAnalysis) -> dict[str, Any]:
    s = analysis.summary
    return {
        "current_cost_per_run_usd": s.current_cost_per_run_usd,
        "optimized_cost_per_run_usd": s.optimized_cost_per_run_usd,
        "rerun_cost_per_run_usd": s.rerun_cost_per_run_usd,
        "savings_pct_first_run": s.savings_pct_first_run,
        "savings_pct_rerun": s.savings_pct_rerun,
        "aggregate_savings_first_run_usd": s.aggregate_savings_first_run_usd,
        "aggregate_savings_rerun_usd": s.aggregate_savings_rerun_usd,
        "blocking_errors": s.blocking_errors,
        "actionable_opportunities": s.actionable_opportunities,
        "warnings_count": s.warnings_count,
        "info_count": s.info_count,
        "total_llm_calls_estimated": s.total_llm_calls_estimated,
        "total_input_tokens_estimated": s.total_input_tokens_estimated,
        "total_cacheable_tokens_estimated": s.total_cacheable_tokens_estimated,
        "models_in_use": list(s.models_in_use),
        "partial_cost_usd": s.partial_cost_usd,
        "unavailable_models": list(s.unavailable_models),
    }


def _action_to_dict(action: RecommendedAction) -> dict[str, Any]:
    return {
        "rank": action.rank,
        "warning_id": action.warning_id,
        "node_id": action.node_id,
        "estimated_savings_usd": action.estimated_savings_usd,
        # ``scope_workflow`` is set when the finding spans multiple nodes in one
        # workflow file (workflow-level scope) rather than being attributable to
        # one specific node. JSON consumers dispatch on (node_id, scope_workflow):
        # at most one is non-null.
        "scope_workflow": action.scope_workflow,
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
    }


def _per_call_to_dict(row: PerCallRow) -> dict[str, Any]:
    return {
        "node_path": row.node_path,
        "model": row.model,
        "is_batch": row.is_batch,
        "batch_size_estimated": row.batch_size_estimated,
        "input_tokens_estimated": row.input_tokens_estimated,
        "output_tokens_estimated": row.output_tokens_estimated,
        "output_data_source": row.output_data_source,
        "cacheable_tokens_estimated": row.cacheable_tokens_estimated,
        "cache_ratio_pct": row.cache_ratio_pct,
        "data_source": row.data_source,
        "declared_prompt_cache": row.declared_prompt_cache,
        "warnings": list(row.warnings),
    }


def _cross_workflow_to_dict(analysis: CacheAnalysis) -> dict[str, Any]:
    """Empty-array contract: always present, even when no findings."""
    cf = analysis.cross_workflow
    return {
        "boundaries_analyzed": cf.boundaries_analyzed,
        "rename_detections": [_warning_to_dict(d) for d in cf.rename_detections],
        "prose_mismatches": [_warning_to_dict(d) for d in cf.prose_mismatches],
        "value_flow_opportunities": [_warning_to_dict(d) for d in cf.value_flow_opportunities],
    }


def _warning_to_dict(diag: Diagnostic) -> dict[str, Any]:
    return diag.to_dict()


__all__ = ["render_json"]
