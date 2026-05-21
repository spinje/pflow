"""Trace discrepancy diagnostics for prompt-cache analysis."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from pflow.core.diagnostic import Diagnostic

from ...context import _PREDICTION_SKIPPED, AnalysisContext
from ...trace_loading import _edge_child_paths
from ...warning_catalog import make_diagnostic
from .predict import (
    _PREDICTION_RECOVERABLE_EXCEPTIONS,
    _mark_all_prediction_skipped,
    _predict_cache_keys,
)

logger = logging.getLogger(__name__)


def _emit_discrepancy_diagnostics(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    notes: list[str],
) -> list[Diagnostic]:
    trace_data = ctx.trace_data
    if trace_data is None:
        return []
    workflow_path = ctx.workflow_path
    # Trace consumer rule (runtime/CLAUDE.md): gate on the major version.
    # Per-event guards below handle missing optional fields, so future
    # additive minor bumps are forward-compat.
    fv = str(trace_data.get("format_version", ""))
    if not fv.startswith("2."):
        return []

    if ctx.predicted_cache_keys or ctx.prediction_fidelity_notes:
        predicted_keys = dict(ctx.predicted_cache_keys)
        predict_notes = list(ctx.prediction_fidelity_notes)
    else:
        try:
            predicted_keys, predict_notes = _predict_cache_keys(cw_result, ctx)
        except _PREDICTION_RECOVERABLE_EXCEPTIONS:
            logger.debug("trace discrepancy prediction failed", exc_info=True)
            predicted_keys = {}
            _mark_all_prediction_skipped(predicted_keys, cw_result, ctx)
            predict_notes = list(ctx.prediction_fidelity_notes)
    notes.extend(predict_notes)

    diagnostics: list[Diagnostic] = []
    from pflow.core.trace_tree import TraceTree

    edge_child_paths = _edge_child_paths(cw_result)
    try:
        trace_tree = TraceTree.from_dict(trace_data)
    except ValueError:
        return []
    # Bug 5 fix: seed the walker with the trace's actual root workflow_path so
    # that top-level events get attributed to whoever produced them rather than
    # being mis-attributed to the analyzed workflow. When trace was recorded
    # for the analyzed workflow itself, this is a no-op.
    trace_root = trace_data.get("workflow_path") or workflow_path
    for leaf in trace_tree.iter_llm_leaves(edges=edge_child_paths, workflow_path=trace_root):
        node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
        event = dict(leaf.event)
        leaf_workflow_path = leaf.workflow_path or workflow_path
        llm_call = event.get("llm_call") or {}
        if not isinstance(llm_call, dict):
            continue
        if llm_call.get("is_warmup"):
            continue

        chunks_skipped = llm_call.get("cache_chunks_skipped")
        actual_key = llm_call.get("cache_key") or event.get("cache_key")
        predicted_key = _predicted_key_for_event(predicted_keys, workflow_path=leaf_workflow_path, node_id=node_id)

        # Skip when there is no discrepancy to surface. Missing key cases are
        # covered by prediction skip notes from ``_predict_cache_keys`` rather
        # than by noisy observable-only discrepancy attributions.
        if not chunks_skipped and (actual_key is None or predicted_key is None or predicted_key == actual_key):
            continue

        root_cause, summary, suggestion, extra = _attribute_root_cause(
            chunks_skipped=chunks_skipped,
        )
        context_extra = dict(extra)
        context_extra.setdefault("affected_workflow", leaf_workflow_path or "<root>")
        diagnostics.append(
            make_diagnostic(
                "cache.discrepancy",
                node_id=node_id,
                root_cause=root_cause,
                root_cause_summary=summary,
                suggestion=suggestion,
                predicted_cache_key=predicted_key,
                actual_cache_key=actual_key,
                **context_extra,
            )
        )
    return _aggregate_and_cap_discrepancies(diagnostics, max_total=20, notes=notes)


def _predicted_key_for_event(
    predicted_keys: Mapping[tuple[str | None, str], str],
    *,
    workflow_path: str | None,
    node_id: str,
) -> str | None:
    """Return predicted key for a (workflow_path, node_id) pair.

    ``_predict_cache_keys`` emits tuple keys exclusively. The lookup
    here is direct — no fallback, no implicit re-keying.

    Returns ``None`` for both a missing entry AND the ``_PREDICTION_SKIPPED``
    sentinel (prediction was attempted but intentionally skipped — sub-workflow
    placeholder taint, missing required params). The discrepancy stage treats
    both as "no prediction available" so the catalog ID never carries the
    internal sentinel string in ``predicted_cache_key`` and never fabricates a
    ``key_mismatch`` attribution against a non-prediction.
    """
    predicted = predicted_keys.get((workflow_path, node_id))
    if predicted is None or predicted == _PREDICTION_SKIPPED:
        return None
    return predicted


def _attribute_root_cause(*, chunks_skipped: Any) -> tuple[str, str, str, dict[str, Any]]:
    """Attribute a discrepancy event to one of two structural causes.

    Returns ``(root_cause, summary, suggestion, extra_context)``.

    The caller's gate guarantees we are only invoked when there is a
    discrepancy to attribute: ``chunks_skipped`` is truthy, or both keys are
    set and differ. No ``unknown`` fallback is reachable in this shape.
    """
    if chunks_skipped:
        skipped = str(chunks_skipped[0])
        return (
            "chunk_skipped",
            f"Cache chunk {skipped!r} skipped at runtime (branch absent)",
            (
                f"Cache chunk `{skipped}` was skipped at runtime (branch absent); "
                "declaration is correct but rendered subset is shorter."
            ),
            {"skipped_chunk": skipped},
        )
    return (
        "key_mismatch",
        "Upstream value changed between predicted run and actual run",
        "Upstream value changed between predicted run and actual run; re-run analyze-cache to refresh the prediction.",
        {},
    )


def _aggregate_and_cap_discrepancies(
    diags: list[Diagnostic],
    *,
    max_total: int,
    notes: list[str] | None = None,
) -> list[Diagnostic]:
    groups: dict[tuple[str | None, str], list[Diagnostic]] = {}
    for diag in diags:
        ctx = diag.context or {}
        groups.setdefault((diag.node_id, str(ctx.get("root_cause", "unknown"))), []).append(diag)

    aggregated: list[Diagnostic] = []
    for group in groups.values():
        representative = group[0]
        merged_context = {**(representative.context or {}), "affected_invocations": len(group)}
        # ``replace`` rather than in-place mutation: ``make_diagnostic`` may
        # share context refs across diagnostics in the same group, so mutating
        # ``representative.context`` would leak ``affected_invocations`` to
        # the rest of the group (silent shared-state bug).
        aggregated.append(replace(representative, context=merged_context))
    aggregated.sort(key=lambda diag: -int((diag.context or {}).get("affected_invocations", 1)))
    if notes is not None and len(aggregated) > max_total:
        notes.append(
            f"Discrepancies: {len(aggregated) - max_total} additional group(s) suppressed by cap "
            f"(showing top {max_total} by frequency)."
        )
    return aggregated[:max_total]
