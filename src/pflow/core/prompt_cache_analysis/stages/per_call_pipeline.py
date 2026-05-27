"""Per-call row pipeline for prompt-cache analysis.

This module owns the multi-stage seam between row construction, per-node
warnings, and cross-workflow candidate attachment. Keeping the pipeline outside
``row_builder.py`` lets sibling stages import row primitives at module top
without forcing row_builder to lazy-import those siblings back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pflow.core.diagnostic import Diagnostic

from ..context import AnalysisContext
from ..trace_loading import _build_call_counts_by_node
from ..types import PerCallRow, TraceExecutionIndex, _RowCrossWorkflowCandidate
from .cross_workflow import (
    _build_cross_workflow_candidates_by_row,
    _has_structural_cross_workflow_projection_candidate,
)
from .row_builder import _build_per_call_row, _detect_candidate_subsets, _extract_declared_chunks
from .warnings import _per_node_warnings


@dataclass(frozen=True)
class _PerCallRowsResult:
    rows: list[PerCallRow]
    warnings: list[Diagnostic]
    call_counts_by_node: dict[tuple[str | None, str], int]
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[_RowCrossWorkflowCandidate]]
    has_greenfield_cross_workflow_projection_gap: bool = False


def _build_per_call_rows_and_warnings(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    trace_index: TraceExecutionIndex,
) -> _PerCallRowsResult:
    """Walk every reachable workflow IR and build LLM rows."""
    rows: list[PerCallRow] = []
    warnings: list[Diagnostic] = []
    call_counts_by_node = _build_call_counts_by_node(ctx, cw_result)
    cross_workflow_candidates_by_row = _build_cross_workflow_candidates_by_row(
        ctx=ctx,
        cw_result=cw_result,
        call_counts_by_node=call_counts_by_node,
        trace_index=trace_index,
    )
    has_greenfield_projection_gap = (
        ctx.trace is None
        and bool(getattr(cw_result, "edges", ()) or ())
        and not cross_workflow_candidates_by_row
        and _has_structural_cross_workflow_projection_candidate(cw_result)
    )
    for workflow_path, workflow_ir in getattr(cw_result, "irs_by_workflow", {}).items():
        declared_chunks = _extract_declared_chunks(workflow_ir.get("cache"))
        candidate_subsets_by_node = _detect_candidate_subsets(workflow_ir)
        wf_ctx = AnalysisContext.build(
            workflow_ir=workflow_ir,
            parameters=ctx.parameters_for_workflow(workflow_path),
            memo_cache=ctx.memo_cache,
            trace_data=ctx.trace_data,
            trace_outputs_by_key=ctx.trace_outputs_by_key,
            workflow_path=workflow_path,
            base_path=ctx.base_path,
            parameters_by_workflow=ctx.parameters_by_workflow,
            predicted_cache_keys=ctx.predicted_cache_keys,
            prediction_fidelity_notes=ctx.prediction_fidelity_notes,
            stale_memo_skipped=ctx.stale_memo_skipped,
            stale_memo_uncheckable=ctx.stale_memo_uncheckable,
        )
        nodes = workflow_ir.get("nodes", []) or []
        nodes_by_id: dict[str, dict[str, Any]] = {
            str(n.get("id", "")): n for n in nodes if isinstance(n, dict) and n.get("id")
        }
        for node in nodes:
            if not isinstance(node, dict) or node.get("type") != "llm":
                continue
            node_id = str(node.get("id", "?"))
            row = _build_per_call_row(
                node=node,
                ctx=wf_ctx,
                declared_chunks=declared_chunks,
                candidate_subset=candidate_subsets_by_node.get(node_id),
                trace_cost=trace_index.costs_by_key.get((workflow_path, node_id)),
                trace_llm_call=trace_index.llm_calls_by_key.get((workflow_path, node_id)),
                trace_llm_calls=trace_index.llm_call_lists_by_key.get((workflow_path, node_id), ()),
                provider_trace_llm_call=trace_index.provider_llm_calls_by_key.get((workflow_path, node_id)),
                provider_trace_llm_calls=trace_index.provider_llm_call_lists_by_key.get((workflow_path, node_id), ()),
                did_not_execute_in_trace=(
                    trace_index.trace_loaded and (workflow_path, node_id) not in trace_index.executed_keys
                ),
                cross_workflow_candidates_by_row=cross_workflow_candidates_by_row,
            )
            rows.append(row)
            if not row.did_not_execute_in_trace:
                warnings.extend(
                    _per_node_warnings(
                        node,
                        row,
                        declared_chunks=declared_chunks,
                        nodes_by_id=nodes_by_id,
                        ctx=wf_ctx,
                    )
                )
    return _PerCallRowsResult(
        rows=rows,
        warnings=warnings,
        call_counts_by_node=call_counts_by_node,
        cross_workflow_candidates_by_row=cross_workflow_candidates_by_row,
        has_greenfield_cross_workflow_projection_gap=has_greenfield_projection_gap,
    )
