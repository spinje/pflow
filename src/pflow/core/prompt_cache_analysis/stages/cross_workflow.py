"""Cross-workflow prompt-cache findings stage."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_config import get_default_workflow_model
from pflow.core.prompt_cache import deterministic_serialize
from pflow.core.prompt_refs import classify_prompt_refs

from ..context import AnalysisContext, _normalize_empty, template_resolver
from ..rendering.cross_workflow_edits import format_grouped_body_block
from ..token_estimation import estimate_tokens
from ..trace_loading import _edge_child_paths
from ..types import (
    CrossWorkflowFindings,
    CrossWorkflowInputContribution,
    PerCallRow,
    TraceExecutionIndex,
    _GroupedConsumerProjection,
    _RowCrossWorkflowCandidate,
    _SubWorkflowCacheCandidate,
    _SubWorkflowCacheGroup,
    _workflow_basename,
    invocation_count_for,
)
from ..warning_catalog import make_diagnostic
from .row_builder import _node_inputs, _total_observed_invocations
from .suggestions import _estimate_token_savings_usd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cross-workflow walking
# ---------------------------------------------------------------------------


def _build_cross_workflow_findings(
    *,
    cw_result: Any,
    notes: list[str],
    per_call_rows: list[PerCallRow],
    ctx: AnalysisContext,
    call_counts_by_node: dict[tuple[str | None, str], int],
) -> tuple[CrossWorkflowFindings, list[Diagnostic]]:
    """Run the F1.3 walker and emit rename / prose-mismatch / value-flow diagnostics.

    Stage 0 (Task 159): returns ``(graph_info, findings)``. Diagnostics flow
    into the analyzer's single ``warnings`` list; the renderers categorize at
    output time by filtering on ``Diagnostic.id``. The graph_info field carries
    pure topology (``boundaries_analyzed``) for JSON consumers that need the
    edge count without inspecting individual findings.

    The walker appends notes to the supplied list when it stops descending
    a branch (max_depth or cycle) — the analyzer surfaces these via
    ``CacheAnalysis.notes`` so agents see truncation rather than silent
    incompleteness.
    """
    result = cw_result
    edges = result.edges

    rename_diags: list[Diagnostic] = []
    prose_mismatches: list[Diagnostic] = []
    sub_workflow_cache_candidates: list[_SubWorkflowCacheCandidate] = []
    for edge in edges:
        is_rename = bool(edge.is_rename and edge.parent_value_expr is not None)
        if is_rename:
            # Evidence-basis principle: the rename warning predicts that
            # cross-workflow byte-level cache match WILL fail because of
            # diverging prose labels. That prediction is only meaningful
            # when (a) the parent value is a stable identifier (not a
            # batch iteration variable), and (b) at least one side has
            # ``## Cache`` declared so there's actual state to break.
            # Without these, the warning fires hypothetically and floods
            # the agent-facing report with non-actionable noise. See
            # GH #362 for the empirical case (lyrics-generator: 23
            # rename warnings, all from batch aliases or non-cache
            # boundaries — zero actionable).
            if edge.is_batch_alias_root:
                continue  # Iteration-variable substitution, not a rename.
            parent_has_cache = bool(result.cache_items_by_workflow.get(edge.parent_workflow))
            child_has_cache = bool(result.cache_items_by_workflow.get(edge.child_workflow))
            if parent_has_cache or child_has_cache:
                rename_diags.append(
                    make_diagnostic(
                        "cache.cross-workflow-rename-detected",
                        parent_workflow=edge.parent_workflow,
                        child_workflow=edge.child_workflow,
                        parent_value_expr=edge.parent_value_expr,
                        child_input_name=edge.child_input_name,
                        line_in_parent=edge.line_in_parent,
                        parent_node_id=edge.parent_node_id,
                    )
                )

        if not is_rename:
            prose_mismatches.extend(_cross_workflow_prose_mismatches(edge, result.cache_items_by_workflow))
        sub_workflow_cache_candidates.extend(
            _sub_workflow_cache_candidates_for_edge(edge, result.cache_items_by_workflow, result.irs_by_workflow)
        )

    rows_by_node_path: dict[tuple[str | None, str], PerCallRow] = {
        (row.workflow_path, row.node_path): row for row in per_call_rows
    }
    sub_workflow_cache_diags = _emit_sub_workflow_cache_findings(
        sub_workflow_cache_candidates,
        rows_by_node_path=rows_by_node_path,
        ctx=ctx,
        cw_result=cw_result,
        call_counts_by_node=call_counts_by_node,
    )

    findings: list[Diagnostic] = [*rename_diags, *prose_mismatches, *sub_workflow_cache_diags]
    return (CrossWorkflowFindings(boundaries_analyzed=len(edges)), findings)


def _cross_workflow_prose_mismatches(
    edge: Any,
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]],
) -> list[Diagnostic]:
    parent_by_name = _items_by_name(cache_items_by_workflow.get(edge.parent_workflow, ()))
    child_by_name = _items_by_name(cache_items_by_workflow.get(edge.child_workflow, ()))
    diagnostics: list[Diagnostic] = []
    for chunk_name in sorted(parent_by_name.keys() & child_by_name.keys()):
        parent_prose = str(parent_by_name[chunk_name].get("prose_before", ""))
        child_prose = str(child_by_name[chunk_name].get("prose_before", ""))
        if parent_prose == child_prose:
            continue
        diagnostics.append(
            make_diagnostic(
                "cache.cross-workflow-prose-mismatch",
                parent_workflow=edge.parent_workflow,
                child_workflow=edge.child_workflow,
                chunk_name=chunk_name,
                parent_prose=parent_prose,
                child_prose=child_prose,
            )
        )
    return diagnostics


@dataclass(frozen=True)
class _ChildCacheRefUse:
    """Actual child prompt refs under a workflow input, grouped by cache entry."""

    child_cache_ref: str
    consumer_node_ids: tuple[str, ...]
    body_refs_by_node: Mapping[str, tuple[str, ...]]


def _sub_workflow_cache_candidates_for_edge(
    edge: Any,
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]],
    irs_by_workflow: dict[str, dict[str, Any]],
) -> tuple[_SubWorkflowCacheCandidate, ...]:
    """Return prompt-ref-level candidates for one boundary edge.

    Suppression rules:
    - ``parent_value_expr is None``: literal or multi-ref string at the
      boundary; no template to track.
    - the child already declares the receiving ref, or an ancestor ref, in its
      own ``## Cache``.
    - no LLM nodes in the child consume the ref.

    Batch-scoped parent values are still valid here: ``${item.concept}`` varies
    across parent fanout items, but inside each child invocation the receiving
    input can be stable context reused by multiple child LLM nodes.
    """
    if edge.parent_value_expr is None:
        return ()
    child_declared = set(_items_by_name(cache_items_by_workflow.get(edge.child_workflow, ())))
    parent_items_by_name = _items_by_name(cache_items_by_workflow.get(edge.parent_workflow, ()))

    candidates: list[_SubWorkflowCacheCandidate] = []
    for use in _child_cache_ref_consumers(irs_by_workflow.get(edge.child_workflow, {}), edge.child_input_name):
        if _cache_ref_is_declared_or_covered(use.child_cache_ref, child_declared):
            continue
        parent_cache_ref = _append_child_suffix(edge.parent_value_expr, edge.child_input_name, use.child_cache_ref)
        parent_prose = _parent_prose_for_cache_ref(parent_items_by_name, parent_cache_ref)
        candidates.append(
            _SubWorkflowCacheCandidate(
                parent_workflow=edge.parent_workflow,
                parent_value_expr=edge.parent_value_expr,
                parent_cache_ref=parent_cache_ref,
                parent_prose=parent_prose,
                parent_node_id=edge.parent_node_id,
                line_in_parent=edge.line_in_parent,
                child_workflow=edge.child_workflow,
                child_input_name=edge.child_input_name,
                child_cache_ref=use.child_cache_ref,
                child_count=len(use.consumer_node_ids),
                child_node_ids=use.consumer_node_ids,
                body_refs_by_node=use.body_refs_by_node,
            )
        )
    return tuple(candidates)


def _child_cache_ref_consumers(child_ir: dict[str, Any], child_input_name: str) -> tuple[_ChildCacheRefUse, ...]:
    """Return prompt refs under ``child_input_name``, grouped by cache entry."""
    if not isinstance(child_ir, dict):
        return ()
    by_ref: dict[str, dict[str, list[str]]] = {}
    first_seen: list[str] = []
    for node in child_ir.get("nodes", []) or []:
        node_id, node_refs = _node_child_cache_ref_body_refs(node, child_input_name)
        if node_id is None:
            continue
        for child_cache_ref, body_refs in node_refs.items():
            if child_cache_ref not in by_ref:
                by_ref[child_cache_ref] = {}
                first_seen.append(child_cache_ref)
            by_ref[child_cache_ref][node_id] = body_refs
    uses: list[_ChildCacheRefUse] = []
    for child_cache_ref in first_seen:
        refs_by_node = by_ref[child_cache_ref]
        uses.append(
            _ChildCacheRefUse(
                child_cache_ref=child_cache_ref,
                consumer_node_ids=tuple(refs_by_node),
                body_refs_by_node={node_id: tuple(refs) for node_id, refs in refs_by_node.items()},
            )
        )
    return tuple(uses)


def _node_child_cache_ref_body_refs(
    node: Any,
    child_input_name: str,
) -> tuple[str | None, dict[str, list[str]]]:
    if not isinstance(node, dict) or node.get("type") != "llm":
        return None, {}
    node_id_raw = node.get("id")
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(node_id_raw, str) or not node_id_raw or not isinstance(prompt, str):
        return None, {}
    node_refs: dict[str, list[str]] = {}
    for ref in classify_prompt_refs(prompt, batch_alias=None, node_inputs=_node_inputs(node)):
        for operand in ref.operand_paths:
            if _path_is_equal_or_descendant(operand, child_input_name):
                node_refs.setdefault(operand, []).append(ref.raw_expr)
    if child_input_name in node_refs:
        node_refs = {child_input_name: node_refs[child_input_name]}
    return node_id_raw, {child_ref: list(dict.fromkeys(refs)) for child_ref, refs in node_refs.items()}


def _path_is_equal_or_descendant(path: str, root: str) -> bool:
    """True when ``path`` is ``root`` or a segment-aware descendant."""
    if not path or not root:
        return False
    return path == root or path.startswith(f"{root}.") or path.startswith(f"{root}[")


def _path_is_ancestor_or_equal(ancestor: str, child: str) -> bool:
    return _path_is_equal_or_descendant(child, ancestor)


def _child_suffix(child_input_name: str, child_ref: str) -> str:
    """Return the suffix of ``child_ref`` after ``child_input_name``."""
    if child_ref == child_input_name:
        return ""
    if child_ref.startswith(f"{child_input_name}."):
        return child_ref[len(child_input_name) :]
    if child_ref.startswith(f"{child_input_name}["):
        return child_ref[len(child_input_name) :]
    return ""


def _append_child_suffix(parent_ref: str, child_input_name: str, child_ref: str) -> str:
    """Map child ref ``concept.title`` through parent ref ``song.concept``."""
    suffix = _child_suffix(child_input_name, child_ref)
    return f"{parent_ref}{suffix}" if suffix else parent_ref


def _parent_prose_for_cache_ref(parent_items_by_name: Mapping[str, dict[str, Any]], parent_cache_ref: str) -> str:
    parent_chunk = parent_items_by_name.get(parent_cache_ref)
    if parent_chunk is None:
        return ""
    return str(parent_chunk.get("prose_before", ""))


def _cache_ref_is_declared_or_covered(child_ref: str, declared: set[str]) -> bool:
    return any(_path_is_ancestor_or_equal(declared_ref, child_ref) for declared_ref in declared)


def _aggregate_sub_workflow_cache_candidates_by_child(
    candidates: list[_SubWorkflowCacheCandidate],
) -> list[_SubWorkflowCacheGroup]:
    """Return deterministic groups with one candidate per child cache ref.

    Tie-break: lex-smallest ``(parent_node_id, parent_workflow, parent_cache_ref)``
    wins for now. Multiple distinct origins for the same cache ref are still
    surfaced as one child edit; token/savings estimates are guarded separately
    so we do not present one origin as measured truth when estimates disagree.
    """
    by_child: dict[str, dict[str, _SubWorkflowCacheCandidate]] = {}
    for candidate in candidates:
        by_ref = by_child.setdefault(candidate.child_workflow, {})
        existing = by_ref.get(candidate.child_cache_ref)
        if existing is None:
            by_ref[candidate.child_cache_ref] = candidate
            continue
        merged_origin_count = existing.origin_count + candidate.origin_count
        chosen = existing
        if (candidate.parent_node_id, candidate.parent_workflow, candidate.parent_cache_ref) < (
            existing.parent_node_id,
            existing.parent_workflow,
            existing.parent_cache_ref,
        ):
            chosen = candidate
        parent_prose_origins_differ = (
            existing.parent_prose_origins_differ
            or candidate.parent_prose_origins_differ
            or existing.parent_prose != candidate.parent_prose
        )
        by_ref[candidate.child_cache_ref] = replace(
            chosen,
            parent_prose="" if parent_prose_origins_differ else existing.parent_prose,
            parent_prose_origins_differ=parent_prose_origins_differ,
            origin_count=merged_origin_count,
            has_multiple_parent_origins=True,
        )

    groups: list[_SubWorkflowCacheGroup] = []
    for child_workflow in sorted(by_child):
        candidates_for_child = tuple(by_child[child_workflow][name] for name in sorted(by_child[child_workflow]))
        groups.append(_SubWorkflowCacheGroup(child_workflow=child_workflow, candidates=candidates_for_child))
    return groups


def _resolve_input_at_workflow_node_invocation(
    *,
    parent_node_id: str,
    parent_workflow: str,
    child_input_name: str,
    child_cache_ref: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> Any | None:
    """Read the resolved input value from the parent's workflow-node trace event.

    Closes the input-passthrough gap left by the trace-output resolver:
    when the parent passes a workflow-input value (e.g. ``${concept}`` where
    ``concept`` is the parent's own input parameter, not a node output), the
    by-node-id walker finds nothing because no node in the parent produces
    ``concept``. The resolved value still exists, recorded on the parent's
    workflow-node event under ``node_params['inputs'][child_input_name]``.

    The engine populates ``node_params`` with template-resolved values prior to
    invoking the child workflow (``runtime/engine/engine.py``: ``node.params =
    merged_params`` after ``resolve_templates``, then ``record_trace(node.params)``).
    Reading that mapping by ``child_input_name`` is robust against complex template
    expressions and is unaffected by the size-trimming applied to
    ``template_resolutions`` in long-running real-world fixtures.

    Last match wins (loop-recovery semantics — mirrors trace output lookup).
    Returns ``None`` if the trace is missing, the parent event has no
    ``node_params['inputs']`` mapping, or the keyed value isn't present.
    """
    if ctx.trace is None:
        return None
    edges = _edge_child_paths(cw_result)
    resolved_value: Any = None
    for we in ctx.trace.walk(edges=edges, workflow_path=ctx.workflow_path):
        if we.workflow_path != parent_workflow:
            continue
        if we.event.get("node_id") != parent_node_id:
            continue
        params = we.event.get("node_params")
        if not isinstance(params, Mapping):
            continue
        inputs = params.get("inputs")
        if not isinstance(inputs, Mapping):
            continue
        candidate_value = inputs.get(child_input_name)
        if candidate_value is None:
            continue
        resolved_value = _resolve_child_suffix_in_value(candidate_value, child_input_name, child_cache_ref)
    return _normalize_empty(resolved_value) if resolved_value is not None else None


def _resolve_child_suffix_in_value(value: Any, child_input_name: str, child_cache_ref: str) -> Any | None:
    suffix = _child_suffix(child_input_name, child_cache_ref)
    if not suffix:
        return value
    synthetic_ref = f"__value{suffix}"
    if not template_resolver().variable_exists(synthetic_ref, {"__value": value}):
        return None
    return template_resolver().resolve_value(synthetic_ref, {"__value": value})


def _estimate_parent_value_tokens(
    *,
    parent_workflow: str,
    parent_value_expr: str,
    parent_node_id: str,
    child_workflow: str,
    child_input_name: str,
    child_cache_ref: str,
    model: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> int | None:
    """Tokens for the parent value flowing across a sub-workflow boundary.

    Tier 0-2: context-level projection resolver scoped to the parent workflow
    (current parameters, memo, then trace by node id).
    Tier 3: parent workflow-node ``node_params['inputs'][child_input_name]`` —
    closes the input-passthrough case (e.g. ``${concept}`` where ``concept`` is
    the parent's own workflow input). Reads from the runtime invocation site
    rather than reconstructing via the upstream node lookup.
    Tier 4: ``None`` (honest unmeasurable — never fabricate).

    Coalesce expressions (``${a ?? b}``) are not handled — too ambiguous
    which operand sourced the value at runtime; returning None keeps the
    rest of the projection honest.
    """
    ref = parent_value_expr
    if "??" in ref:
        return None
    workflow_path = parent_workflow
    value = ctx.resolve_ref_value_for_projection_in_workflow(ref, workflow_path=workflow_path, cw_result=cw_result)
    if value is None:
        value = _resolve_input_at_workflow_node_invocation(
            parent_node_id=parent_node_id,
            parent_workflow=workflow_path,
            child_input_name=child_input_name,
            child_cache_ref=child_cache_ref,
            ctx=ctx,
            cw_result=cw_result,
        )
    if value is None:
        return None
    return estimate_tokens(model, deterministic_serialize(value))[0]


def _build_cross_workflow_candidates_by_row(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    call_counts_by_node: dict[tuple[str | None, str], int],
    trace_index: TraceExecutionIndex,
) -> dict[tuple[str | None, str], list[_RowCrossWorkflowCandidate]]:
    """Build row-level cross-workflow projections for trace-backed attribution."""
    candidates_by_row: dict[tuple[str | None, str], list[_RowCrossWorkflowCandidate]] = {}
    for edge in getattr(cw_result, "edges", ()) or ():
        edge_candidates = _row_cross_workflow_candidates_for_edge(
            edge=edge,
            ctx=ctx,
            cw_result=cw_result,
            call_counts_by_node=call_counts_by_node,
            trace_index=trace_index,
        )
        for candidate in edge_candidates:
            for node_id in candidate.child_node_ids:
                if call_counts_by_node.get((candidate.child_workflow, node_id), 0) <= 0:
                    continue
                candidates_by_row.setdefault((candidate.child_workflow, node_id), []).append(candidate)
    return candidates_by_row


def _row_cross_workflow_candidates_for_edge(
    *,
    edge: Any,
    ctx: AnalysisContext,
    cw_result: Any,
    call_counts_by_node: dict[tuple[str | None, str], int],
    trace_index: TraceExecutionIndex,
) -> tuple[_RowCrossWorkflowCandidate, ...]:
    """Return gated row-level candidates for one cross-workflow edge."""
    if getattr(edge, "is_batch_alias_root", False) or getattr(edge, "parent_value_expr", None) is None:
        return ()
    child_workflow = str(edge.child_workflow)
    child_ir = cw_result.irs_by_workflow.get(child_workflow)
    if not child_ir:
        return ()
    child_declared = set(_items_by_name(cw_result.cache_items_by_workflow.get(child_workflow, ())))
    parent_items_by_name = _items_by_name(cw_result.cache_items_by_workflow.get(edge.parent_workflow, ()))
    candidates: list[_RowCrossWorkflowCandidate] = []
    for use in _child_cache_ref_consumers(child_ir, edge.child_input_name):
        if _cache_ref_is_declared_or_covered(use.child_cache_ref, child_declared):
            continue
        total_invocations = _total_observed_invocations(
            child_workflow=child_workflow,
            child_node_ids=use.consumer_node_ids,
            call_counts_by_node=call_counts_by_node,
        )
        if total_invocations < 2:
            continue
        child_models = _resolved_models_for_child(
            child_ir,
            workflow_path=child_workflow,
            node_ids=use.consumer_node_ids,
            trace_index=trace_index,
        )
        if not child_models:
            continue
        strictest_model = max(child_models, key=get_min_cache_tokens)
        threshold_floor = get_min_cache_tokens(strictest_model)
        parent_cache_ref = _append_child_suffix(
            edge.parent_value_expr or "", edge.child_input_name, use.child_cache_ref
        )
        parent_prose = _parent_prose_for_cache_ref(parent_items_by_name, parent_cache_ref)
        token_estimate = _estimate_parent_value_tokens(
            parent_workflow=edge.parent_workflow,
            parent_value_expr=parent_cache_ref,
            parent_node_id=edge.parent_node_id,
            child_workflow=child_workflow,
            child_input_name=edge.child_input_name,
            child_cache_ref=use.child_cache_ref,
            model=strictest_model,
            ctx=ctx,
            cw_result=cw_result,
        )
        if token_estimate is None or token_estimate <= 0:
            continue
        candidates.append(
            _RowCrossWorkflowCandidate(
                parent_workflow=edge.parent_workflow,
                parent_value_expr=edge.parent_value_expr or "",
                parent_cache_ref=parent_cache_ref,
                parent_node_id=edge.parent_node_id,
                child_workflow=child_workflow,
                child_input_name=edge.child_input_name,
                child_cache_ref=use.child_cache_ref,
                parent_prose=parent_prose,
                estimated_tokens_per_call=token_estimate,
                threshold_floor=threshold_floor,
                child_node_ids=use.consumer_node_ids,
            )
        )
    return tuple(candidates)


def _has_structural_cross_workflow_projection_candidate(cw_result: Any) -> bool:
    """Return True when a no-trace run has rows that trace attribution could fill."""
    for edge in getattr(cw_result, "edges", ()) or ():
        if getattr(edge, "is_batch_alias_root", False):
            continue
        if getattr(edge, "parent_value_expr", None) is None:
            continue
        child_workflow = str(edge.child_workflow)
        child_ir = cw_result.irs_by_workflow.get(child_workflow)
        if not child_ir:
            continue
        child_declared = set(_items_by_name(cw_result.cache_items_by_workflow.get(child_workflow, ())))
        uses = _child_cache_ref_consumers(child_ir, edge.child_input_name)
        consumer_ids = {
            node_id
            for use in uses
            if not _cache_ref_is_declared_or_covered(use.child_cache_ref, child_declared)
            for node_id in use.consumer_node_ids
        }
        if len(consumer_ids) >= 2:
            return True
    return False


def _resolved_models_for_child(
    child_ir: dict[str, Any],
    *,
    workflow_path: str | None = None,
    node_ids: tuple[str, ...] = (),
    trace_index: TraceExecutionIndex | None = None,
) -> list[str]:
    """Resolved LLM models in child source order; template strings are skipped."""
    models: list[str] = []
    node_id_filter = set(node_ids)
    for node in child_ir.get("nodes", []) or []:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        node_id = str(node.get("id", ""))
        if node_id_filter and node_id not in node_id_filter:
            continue
        model = node.get("params", {}).get("model") or node.get("model")
        if (model is None or (isinstance(model, str) and "${" in model)) and trace_index is not None:
            observed = trace_index.llm_call_lists_by_key.get((workflow_path, node_id), ())
            observed_models = sorted({str(call.get("model")) for call in observed if call.get("model")})
            if len(observed_models) == 1:
                model = observed_models[0]
        if model is None:
            model = get_default_workflow_model()
        if not model:
            continue
        model_str = str(model)
        if "${" in model_str:
            continue
        models.append(model_str)
    return models


_MODEL_SWITCH_BAND = 1024


def _project_grouped_cache_savings(
    group: _SubWorkflowCacheGroup,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    ctx: AnalysisContext,
    cw_result: Any,
) -> tuple[int, float | None, tuple[_GroupedConsumerProjection, ...], dict[str, int | None], str]:
    """Compute per-consumer cumulative cache facts for one child workflow.

    Returns ``(strictest_threshold, total_savings_usd, projections,
    tokens_per_input, strictest_model)``. Callers classify the group case from
    ``projections`` (per-consumer per-call check) — the threshold gate is NOT a
    cohort-total comparison. ``total_savings_usd`` is cohort-level (already
    accounts for call count) for honest cost framing.
    """
    consumer_rows = _executed_consumer_rows(group, rows_by_node_path)
    if not consumer_rows:
        return (0, None, (), {}, "")

    strictest_threshold = max(get_min_cache_tokens(row.model) for _, row in consumer_rows)
    strictest_model = next(
        row.model for _, row in consumer_rows if get_min_cache_tokens(row.model) == strictest_threshold
    )
    tokens_per_ref = _tokens_per_group_ref(
        group,
        consumer_rows,
        strictest_model=strictest_model,
        ctx=ctx,
        cw_result=cw_result,
    )
    projections, total_savings = _grouped_consumer_projections(
        group,
        rows_by_node_path,
        tokens_per_ref=tokens_per_ref,
    )
    return (strictest_threshold, total_savings, projections, tokens_per_ref, strictest_model)


def _executed_consumer_rows(
    group: _SubWorkflowCacheGroup,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
) -> list[tuple[str, PerCallRow]]:
    consumer_rows: list[tuple[str, PerCallRow]] = []
    seen: set[str] = set()
    for candidate in group.candidates:
        for node_id in candidate.child_node_ids:
            if node_id in seen:
                continue
            row = rows_by_node_path.get((group.child_workflow, node_id))
            if row is None or not row.model:
                continue
            if row.did_not_execute_in_trace:
                continue
            consumer_rows.append((node_id, row))
            seen.add(node_id)
    return consumer_rows


def _tokens_per_group_ref(
    group: _SubWorkflowCacheGroup,
    consumer_rows: list[tuple[str, PerCallRow]],
    *,
    strictest_model: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> dict[str, int | None]:
    tokens_per_ref: dict[str, int | None] = {}
    for candidate in group.candidates:
        tokens = None
        if not candidate.has_multiple_parent_origins:
            tokens = _tokens_from_cross_workflow_rows(candidate, consumer_rows)
        if tokens is None and not candidate.has_multiple_parent_origins:
            tokens = _estimate_parent_value_tokens(
                parent_workflow=candidate.parent_workflow,
                parent_value_expr=candidate.parent_cache_ref,
                parent_node_id=candidate.parent_node_id,
                child_workflow=candidate.child_workflow,
                child_input_name=candidate.child_input_name,
                child_cache_ref=candidate.child_cache_ref,
                model=strictest_model,
                ctx=ctx,
                cw_result=cw_result,
            )
        tokens_per_ref[candidate.child_cache_ref] = tokens
    return tokens_per_ref


def _grouped_consumer_projections(
    group: _SubWorkflowCacheGroup,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    *,
    tokens_per_ref: dict[str, int | None],
) -> tuple[tuple[_GroupedConsumerProjection, ...], float | None]:
    projections: list[_GroupedConsumerProjection] = []
    total_savings: float | None = 0.0
    for consumer_node_id, cache_refs in sorted(group.cache_refs_by_consumer().items()):
        row = rows_by_node_path.get((group.child_workflow, consumer_node_id))
        if row is None or not row.model or row.did_not_execute_in_trace:
            continue
        multiplier = invocation_count_for(row)
        missing_tokens = any(tokens_per_ref.get(ref) is None for ref in cache_refs)
        per_call_sum = sum(tokens_per_ref[ref] or 0 for ref in cache_refs if tokens_per_ref.get(ref) is not None)
        savings = None if missing_tokens else _estimate_token_savings_usd(row.model, per_call_sum, multiplier)
        if savings is None:
            total_savings = None
        elif total_savings is not None:
            total_savings += savings
        projections.append(
            _GroupedConsumerProjection(
                consumer_node_id=consumer_node_id,
                model=row.model,
                consumed_inputs=tuple(cache_refs),
                per_call_prefix_tokens=per_call_sum,
                threshold=get_min_cache_tokens(row.model),
                savings_usd=savings,
                did_not_execute_in_trace=False,
            )
        )
    return (tuple(projections), total_savings)


def _tokens_from_cross_workflow_rows(
    candidate: _SubWorkflowCacheCandidate,
    consumer_rows: list[tuple[str, PerCallRow]],
) -> int | None:
    """Reuse row-level token estimates when they already exist."""
    for _node_id, row in consumer_rows:
        for contribution in row.cross_workflow_inputs:
            if not isinstance(contribution, CrossWorkflowInputContribution):
                continue
            contribution_ref = contribution.child_cache_ref or contribution.child_input_name
            if contribution_ref == candidate.child_cache_ref:
                return contribution.tokens_per_call
    return None


def _classify_group_case(projections: tuple[_GroupedConsumerProjection, ...]) -> str:
    """Group case = worst per-consumer case.

    Each consumer's case is decided by per-call cache-prefix size against that
    consumer's threshold:

    - ``actionable``  — per_call_prefix_tokens >= consumer.threshold
                        (cache fires for this consumer as-declared)
    - ``model_switch`` — fires below the consumer's current threshold but at
                        the 1,024-tier (smallest Anthropic minimum) after a
                        model swap
    - ``refactor``    — below every provider tier; needs content growth

    Group rolls up to the worst case so the agent gets honest advice. If ANY
    resolved consumer can't fire (e.g., per_call_prefix below 1,024), the
    group is ``refactor`` — switching model wouldn't help that consumer.
    """
    if not projections:
        return "unmeasurable"
    per_consumer_cases = [_projection_case(projection) for projection in projections]
    if "refactor" in per_consumer_cases:
        return "refactor"
    if "model_switch" in per_consumer_cases:
        return "model_switch"
    return "actionable"


def _projection_case(projection: _GroupedConsumerProjection) -> str:
    per_call = projection.per_call_prefix_tokens
    if per_call >= projection.threshold:
        return "actionable"
    if per_call >= _MODEL_SWITCH_BAND:
        return "model_switch"
    return "refactor"


def _split_group_by_projection_case(
    group: _SubWorkflowCacheGroup,
    projections: tuple[_GroupedConsumerProjection, ...],
) -> list[tuple[_SubWorkflowCacheGroup, tuple[_GroupedConsumerProjection, ...], str]]:
    """Split mixed-cacheability child recommendations by consumer case.

    A child workflow can have one consumer whose proposed cache prefix clears
    the provider minimum and another consumer whose narrower prefix is below
    every provider tier. Rendering those as one recommendation forces the body
    to choose one representative token count and produces incoherent text like
    "~8,504 tokens per call, below the 1,024-token minimum". Split at the
    producer boundary so every recommendation has one coherent threshold story.
    """
    if not projections:
        return [(group, projections, "unmeasurable")]

    by_case: dict[str, list[_GroupedConsumerProjection]] = {}
    for projection in projections:
        by_case.setdefault(_projection_case(projection), []).append(projection)

    if len(by_case) == 1:
        case = next(iter(by_case))
        return [(group, projections, case)]

    result: list[tuple[_SubWorkflowCacheGroup, tuple[_GroupedConsumerProjection, ...], str]] = []
    for case in ("actionable", "model_switch", "refactor"):
        case_projections = tuple(by_case.get(case, ()))
        if not case_projections:
            continue
        consumer_ids = frozenset(projection.consumer_node_id for projection in case_projections)
        result.append((_group_for_consumer_nodes(group, consumer_ids), case_projections, case))
    return result


def _group_for_consumer_nodes(group: _SubWorkflowCacheGroup, consumer_ids: frozenset[str]) -> _SubWorkflowCacheGroup:
    candidates: list[_SubWorkflowCacheCandidate] = []
    for candidate in group.candidates:
        child_node_ids = tuple(node_id for node_id in candidate.child_node_ids if node_id in consumer_ids)
        if not child_node_ids:
            continue
        body_refs_by_node = {
            node_id: tuple(refs) for node_id, refs in candidate.body_refs_by_node.items() if node_id in consumer_ids
        }
        candidates.append(
            replace(
                candidate,
                child_count=len(child_node_ids),
                child_node_ids=child_node_ids,
                body_refs_by_node=body_refs_by_node,
            )
        )
    return _SubWorkflowCacheGroup(child_workflow=group.child_workflow, candidates=tuple(candidates))


def _strictest_model_and_threshold(projections: tuple[_GroupedConsumerProjection, ...]) -> tuple[str, int]:
    if not projections:
        return "", 0
    strictest = max(projections, key=lambda projection: projection.threshold)
    return strictest.model, strictest.threshold


def _total_savings_for_case(
    projections: tuple[_GroupedConsumerProjection, ...],
    *,
    case: str,
) -> float | None:
    if case != "actionable":
        return None
    total = 0.0
    for projection in projections:
        if projection.savings_usd is None:
            return None
        total += projection.savings_usd
    return total


def _grouped_inputs_context(
    group: _SubWorkflowCacheGroup,
    tokens_per_input: dict[str, int | None],
) -> list[dict[str, Any]]:
    """Structured input facts for JSON consumers and per-call row notes."""
    items: list[dict[str, Any]] = []
    for candidate in group.candidates:
        consumer_node_ids = list(candidate.child_node_ids)
        items.append({
            "child_input_name": candidate.child_input_name,
            "child_cache_ref": candidate.child_cache_ref,
            "parent_value_expr": candidate.parent_value_expr,
            "parent_cache_ref": candidate.parent_cache_ref,
            "parent_workflow": candidate.parent_workflow,
            "parent_node_id": candidate.parent_node_id,
            "line_in_parent": candidate.line_in_parent,
            "tokens_estimated": tokens_per_input.get(candidate.child_cache_ref),
            "parent_prose": candidate.parent_prose,
            "parent_prose_origins_differ": candidate.parent_prose_origins_differ,
            "origin_count": candidate.origin_count,
            "has_multiple_parent_origins": candidate.has_multiple_parent_origins,
            "consumer_node_ids": consumer_node_ids,
            "consumer_node_ids_csv": ", ".join(f"`{node_id}`" for node_id in consumer_node_ids),
            "template_var_refs_by_node": {node_id: list(refs) for node_id, refs in candidate.body_refs_by_node.items()},
        })
    return items


def _emit_sub_workflow_cache_findings(
    candidates: list[_SubWorkflowCacheCandidate],
    *,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    ctx: AnalysisContext,
    cw_result: Any,
    call_counts_by_node: dict[tuple[str | None, str], int],
) -> list[Diagnostic]:
    """Emit one grouped diagnostic per child workflow."""
    diagnostics: list[Diagnostic] = []
    for group in _aggregate_sub_workflow_cache_candidates_by_child(candidates):
        group_child_node_ids = tuple(sorted({node_id for c in group.candidates for node_id in c.child_node_ids}))
        if ctx.trace is None:
            if len(group_child_node_ids) < 2:
                continue
        else:
            total_invocations = _total_observed_invocations(
                child_workflow=group.child_workflow,
                child_node_ids=group_child_node_ids,
                call_counts_by_node=call_counts_by_node,
            )
            child_has_trace_evidence = any(
                (group.child_workflow, node_id) in call_counts_by_node for node_id in group_child_node_ids
            )
            if child_has_trace_evidence and total_invocations < 2:
                continue
            if not child_has_trace_evidence and len(group_child_node_ids) < 2:
                continue

        _strictest_threshold, _total_savings, projections, tokens_per_input, _strictest_model = (
            _project_grouped_cache_savings(group, rows_by_node_path, ctx, cw_result)
        )
        for split_group, split_projections, case in _split_group_by_projection_case(group, projections):
            strictest_model, strictest_threshold = _strictest_model_and_threshold(split_projections)
            diagnostics.append(
                make_diagnostic(
                    "cache.sub-workflow-cache-undeclared",
                    node_id=None,
                    affected_workflow=split_group.child_workflow,
                    child_workflow=split_group.child_workflow,
                    child_workflow_basename=_workflow_basename(split_group.child_workflow),
                    affected_input_count=len(split_group.candidates),
                    inputs=_grouped_inputs_context(split_group, tokens_per_input),
                    body_block=format_grouped_body_block(
                        split_group,
                        split_projections,
                        tokens_per_input,
                        strictest_model,
                        strictest_threshold,
                        case,
                    ),
                    case=case,
                    savings_usd=_total_savings_for_case(split_projections, case=case),
                )
            )
    return diagnostics


def _collect_llm_nodes_referencing_path(ir: dict[str, Any], template_path: str) -> list[str]:
    """LLM node ids whose ``params.prompt`` references ``${template_path}``.

    Source-order; each LLM node listed at most once. Uses the template-pattern
    walker to handle both bare references (``${X}``) and dotted-path references
    (``${X.field}``, ``${X[0]}``). For coalesce expressions (``${a ?? b}``),
    each operand is checked independently — symmetric with
    ``_dynamic_before_static_warnings``.

    Callers compute count via ``len(...)`` when they need the count. The list
    flows through ``_SubWorkflowCacheCandidate.child_node_ids`` so the
    ``cache.sub-workflow-cache-undeclared`` recommendation can both name the
    affected nodes inline and project per-node cache-read savings.
    """
    ids: list[str] = []
    if not isinstance(ir, dict):
        return ids
    nodes = ir.get("nodes")
    if not isinstance(nodes, list):
        return ids
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        prompt = node.get("params", {}).get("prompt", "")
        if not isinstance(prompt, str):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id or node_id in ids:
            continue
        node_inputs = _node_inputs(node)
        refs = classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs)
        if any(_path_is_equal_or_descendant(operand, template_path) for ref in refs for operand in ref.operand_paths):
            ids.append(node_id)
    return ids


def _items_by_name(items: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(item["name"]): item for item in items if isinstance(item.get("name"), str)}
