"""Tier 2 + Tier 3 cache analyzer entry point.

``analyze(workflow, parameters)`` composes:

- F1.2 ``token_estimation`` (per-call tier),
- F1.3 ``cross_workflow`` walker (Tier 2),
- F1.4 ``stages.suggestions`` (sensitivity-floored advisories),
- F2.2 ``summarize`` (one-line nudge — separately surfaced).

…into a single :class:`CacheAnalysis` result. The analyzer is
*opt-in*: per DD#36 it never gates ``pflow run``; it only fires from
``pflow analyze-cache`` and ``pflow run --dry-run``.

**Predicted cache_key byte-identity** (load-bearing, Round 4 high-value fix):
this module imports ``_resolve_chunk_value`` and ``_resolve_static_prefix_for_cache``
from ``pflow.core.prompt_cache`` so the analyzer's predicted cache_keys are
byte-identical to the runtime's. Inline reimplementation diverges from runtime
resolution and produces false ``cache.discrepancy`` reports.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Imported for the predicted-cache_key contract (Round 4 high-value fix #2):
# when ``cache.discrepancy`` detection wires up in v1.x, it MUST use the shared
# resolution helpers from ``core.prompt_cache`` so predicted cache_keys are
# byte-identical to runtime's. Eager import here locks the layer-policy
# contract — if a future contributor moves either helper, this file fails to
# import and the test suite catches it. v1 scaffolds the discrepancy slot but
# defers full prediction; the helpers will be consumed when that lands.
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_config import get_default_workflow_model
from pflow.core.llm_providers import normalize_model_name
from pflow.core.prompt_cache import (  # noqa: F401 — see docstring.
    _CHUNK_ABSENT,
    _resolve_chunk_value,
    _resolve_static_prefix_for_cache,
    deterministic_serialize,
)
from pflow.core.validation_utils import generate_dummy_parameters
from pflow.core.workflow.validator import WorkflowValidator
from pflow.core.workflow_id import synthesize_inline_workflow_id

from . import types as _types
from .context import AnalysisContext, _normalize_empty
from .cross_workflow import CrossWorkflowEdge, walk_cross_workflow
from .stages.cross_workflow import _build_cross_workflow_findings
from .stages.discrepancy import (
    _attach_predicted_cache_keys,
    _emit_discrepancy_diagnostics,
    _format_dynamic_batches_note,
)
from .stages.fragmentation import _detect_model_cache_fragmentation, _detect_system_cache_fragmentation
from .stages.partial_declarations import _emit_partial_declaration_findings
from .stages.row_builder import _build_per_call_row, _total_observed_invocations
from .stages.suggestions import (
    _cache_item_names,
    _collect_llm_template_references,
    _consolidate_to_root_advisories,
    _emit_padding_advisories,
    _extract_cache_ttl,
    _populate_suggested_blocks,
)
from .stages.summary import (
    _aggregate_confidence,
    _build_sub_workflow_rollup,
    _build_summary,
    _filter_trace_dependent_warnings,
    _format_workflow_run_command,
    _maybe_append_gemini_note,
    _trace_coverage_for_rows,
)
from .stages.warnings import _enrich_shadow_warnings_with_costs, _per_node_warnings
from .token_estimation import (
    build_shared_store_for_refs as _build_shared_store_for_refs,
)
from .token_estimation import (
    extract_unique_refs as _extract_unique_refs,
)
from .trace_loading import (
    _build_trace_execution_index,
    _default_memo_cache,
    _derive_trace_workflow_relationship,
    _diagnostics_from_trace_warnings,
    _edge_child_paths,
    _format_rejection_note,
    _resolve_ir_static_model_for_node,
    _resolve_trace_data,
    _resolve_trace_scope,
    _scope_workflow_paths,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PerCallRowsResult:
    rows: list[_types.PerCallRow]
    warnings: list[Diagnostic]
    call_counts_by_node: dict[tuple[str | None, str], int]
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[_RowCrossWorkflowCandidate]]
    has_greenfield_cross_workflow_projection_gap: bool = False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze(
    workflow_ir: dict[str, Any],
    *,
    parameters: dict[str, Any] | None = None,
    workflow_path: str | None = None,
    base_path: Path | None = None,
    trace_path: Path | None = None,
    auto_load_trace: bool = True,
    memo_cache: Any = None,
) -> _types.CacheAnalysis:
    """Compose the full analysis.

    ``parameters`` is optional per DD#35; token estimation falls back when
    input substitution can't fully resolve a prompt.

    ``trace_path`` is an explicit override (mode-4 from-trace). When ``None``
    and ``auto_load_trace`` is ``True``, the analyzer scans
    ``~/.pflow/debug/`` for the most recent 2.x trace whose ``workflow_path``
    matches, per DD#34.

    ``memo_cache`` is a ``MemoizationCache`` instance for the ``memo`` token
    tier. Pass ``None`` to disable that tier.
    """
    notes: list[str] = []
    suggested_blocks: list[_types.SuggestedBlock] = []

    # Canonical lookup identifier — mirrors ``runner.py``'s trace_workflow_path
    # AND ``MemoizationCache.workflow_path`` at write time (both use
    # ``resolved.file_path or synthesize_inline_workflow_id(ir)``). File/library
    # callers pass ``workflow_path=resolved.file_path``; inline callers pass
    # ``None`` and we derive the same ``ir-hash:<md5>`` the writer used.
    # Threaded through autoload (filename-hash glob), memo cache (SQL
    # ``workflow_path`` scoping), and cross-workflow walker (cycle detection /
    # labeling) — every site that correlates analyzer-time and runtime state.
    # ``"<inline>"`` is reserved for the displayed identifier — a human-readable
    # label kept separate from the lookup key.
    lookup_path = workflow_path if workflow_path is not None else synthesize_inline_workflow_id(workflow_ir)

    # CR-1305 W3: default-construct ``memo_cache`` from disk when the caller
    # didn't supply one. Production entry points (CLI / MCP / dry-run nudge)
    # don't manage ``MemoizationCache`` lifecycle; without this default,
    # ``data_source: "memo"`` was unreachable in production. Top-10% pattern:
    # construct dependencies at the lowest layer that has the data.
    if memo_cache is None:
        memo_cache = _default_memo_cache()

    trace_data, used_trace_path = _resolve_trace_data(trace_path, auto_load_trace, lookup_path, notes)
    ir_default_model = get_default_workflow_model()

    trace_root_workflow_path, scope_mismatch, appears_as_child = _resolve_trace_scope(trace_data, lookup_path, notes)

    cache_block = workflow_ir.get("cache")
    declared_chunks = _extract_declared_chunks(cache_block)

    cw_result = walk_cross_workflow(
        workflow_ir,
        base_path=base_path,
        root_workflow_path=lookup_path,
        notes=notes,
    )
    dynamic_batch_note = _format_dynamic_batches_note(cw_result.dynamic_batches)
    if dynamic_batch_note is not None:
        notes.append(dynamic_batch_note)
    edge_child_paths = _edge_child_paths(cw_result)
    trace_index = _build_trace_execution_index(trace_data, trace_root_workflow_path, edge_child_paths)
    stale_memo_skipped: set[tuple[str | None, str]] = set()
    stale_memo_uncheckable: set[tuple[str | None, str]] = set()
    parameters_by_workflow = _build_parameters_by_workflow(
        cw_result,
        parameters or {},
        lookup_path,
        memo_cache=memo_cache,
        trace_data=trace_data,
        trace_outputs_by_key=trace_index.outputs_by_key,
        base_path=base_path,
        stale_memo_uncheckable=stale_memo_uncheckable,
    )

    # Build the AnalysisContext once and thread it through helpers. Bundles
    # (workflow_ir, parameters, memo_cache, trace_data, workflow_path,
    # base_path) so per-call helpers don't re-marshal these inputs at every
    # signature boundary. Methods on the context (resolve_ref_value,
    # cost_usd_for_node) own the policy that was previously scattered.
    ctx = AnalysisContext.build(
        workflow_ir=workflow_ir,
        parameters=parameters or {},
        memo_cache=memo_cache,
        trace_data=trace_data,
        trace_outputs_by_key=trace_index.outputs_by_key,
        workflow_path=lookup_path,
        base_path=base_path,
        parameters_by_workflow=parameters_by_workflow,
        stale_memo_skipped=stale_memo_skipped,
        stale_memo_uncheckable=stale_memo_uncheckable,
    )
    ctx, predicted_cache_keys, prediction_fidelity_notes = _attach_predicted_cache_keys(ctx, cw_result)

    # Pass 1 (cheap): walk IR for shared template references — no tokenization.
    # Tier 2 of ``estimate_cacheable_tokens`` consumes the per-node candidate
    # subset to project cacheable counts via memo data.
    per_call_result = _build_per_call_rows_and_warnings(
        ctx=ctx,
        cw_result=cw_result,
        trace_index=trace_index,
    )
    per_call_rows = per_call_result.rows
    warnings = per_call_result.warnings
    # Auto-load misalignment fallback: when the auto-loaded trace doesn't
    # cover all root LLM nodes in the IR, fall back to greenfield. This is
    # ORTHOGONAL to ``trace_coverage`` — a trace from a different parameter
    # set (different conditional branches taken) classifies as "complete"
    # under the final_status discriminator but is misaligned for THIS analysis
    # call. Explicit ``--from-trace`` bypasses this gate (agent's choice).
    if trace_path is None and any(row.did_not_execute_in_trace for row in per_call_rows):
        notes.append(_format_rejection_note(used_trace_path, trace_data))
        trace_data = None
        used_trace_path = None
        # trace_data is None here; the function short-circuits, but pass
        # ``lookup_path`` (not trace_root_workflow_path) so the unused seed
        # value matches the no-trace conceptual scope.
        trace_index = _build_trace_execution_index(trace_data, lookup_path, edge_child_paths)
        parameters_by_workflow = _build_parameters_by_workflow(
            cw_result,
            parameters or {},
            lookup_path,
            memo_cache=memo_cache,
            trace_data=trace_data,
            trace_outputs_by_key=trace_index.outputs_by_key,
            base_path=base_path,
        )
        ctx = AnalysisContext.build(
            workflow_ir=workflow_ir,
            parameters=parameters or {},
            memo_cache=memo_cache,
            trace_data=trace_data,
            trace_outputs_by_key=trace_index.outputs_by_key,
            workflow_path=lookup_path,
            base_path=base_path,
            parameters_by_workflow=parameters_by_workflow,
            predicted_cache_keys=predicted_cache_keys,
            prediction_fidelity_notes=tuple(prediction_fidelity_notes),
            stale_memo_skipped=ctx.stale_memo_skipped,
            stale_memo_uncheckable=ctx.stale_memo_uncheckable,
        )
        per_call_result = _build_per_call_rows_and_warnings(
            ctx=ctx,
            cw_result=cw_result,
            trace_index=trace_index,
        )
        per_call_rows = per_call_result.rows
        warnings = per_call_result.warnings

    warnings.extend(_diagnostics_from_trace_warnings(trace_data))

    # Per-node model-drift detection. Replaces the prior whole-trace drift gate
    # (deleted): structural drift (renamed/added/removed nodes) now degrades
    # per-row via ``PerCallRow.data_source``; only model drift needs explicit
    # disclosure because ``_resolve_effective_row_model`` declares "trace wins"
    # and projections would silently use stale pricing.
    drift_note, drift_count = _detect_per_node_model_drift(
        per_call_rows,
        getattr(cw_result, "irs_by_workflow", {}) or {ctx.workflow_path: dict(ctx.workflow_ir)},
        ir_default_model,
    )
    if drift_note is not None:
        notes.append(drift_note)

    # Root-only by design: suggested-block, padding, and consolidate advisories
    # edit the analyzed file's ## Cache block. Child workflow recommendations
    # are exposed through the per-call rollup plus renderer drill-in commands
    # so agents run analyze-cache on the child before editing that file.
    rows_by_node = {row.node_path: row for row in per_call_rows if row.workflow_path == lookup_path}

    # Pass 2 (heavy): build paste-ready blocks. Uses ``model`` from rows +
    # tokenization for chunk sizes. Brownfield early-return preserved.
    suggested_blocks, shared_warnings = _populate_suggested_blocks(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        ctx=ctx,
        notes=notes,
    )
    warnings.extend(shared_warnings)

    # Option C — surface a Notes entry when the per-call section will render
    # empty so agents understand the absence is intentional. The renderer uses
    # the same predicate (``_row_has_real_data``) to decide visibility; we
    # mirror it here at analyze-time so the note appears in JSON too.
    from .rendering.views import per_call_row_has_real_data

    if per_call_rows and not any(per_call_row_has_real_data(r) for r in per_call_rows):
        notes.append(
            "Per-call cache report hidden — workflow has no run data yet. "
            "Run once, then re-run analyze-cache for real per-node token "
            "estimates and cacheable projections."
        )
    if per_call_result.has_greenfield_cross_workflow_projection_gap:
        notes.append(
            "Cross-workflow projections require trace evidence to populate per-call rows. "
            "Recommended actions still surface; run with `--from-trace <path>` for per-call attribution."
        )
    warnings.extend(_emit_padding_advisories(workflow_ir=workflow_ir, rows_by_node=rows_by_node))
    consolidate_root_diags = _consolidate_to_root_advisories(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
    )
    warnings.extend(consolidate_root_diags)
    warnings.extend(
        _detect_model_cache_fragmentation(
            workflow_ir=workflow_ir,
            rows_by_node=rows_by_node,
            declared_chunks=declared_chunks,
            ctx=ctx,
        )
    )
    warnings.extend(
        _detect_system_cache_fragmentation(
            workflow_ir=workflow_ir,
            rows_by_node=rows_by_node,
            declared_chunks=declared_chunks,
            ctx=ctx,
        )
    )
    warnings.extend(_run_full_validation(workflow_ir, workflow_path=lookup_path))
    rows_by_node_path = {(row.workflow_path, row.node_path): row for row in per_call_rows}
    warnings.extend(
        _emit_partial_declaration_findings(
            cw_result=cw_result,
            rows_by_node_path=rows_by_node_path,
            ctx=ctx,
            consolidate_root_diags=consolidate_root_diags,
        )
    )

    # --- Cross-workflow walker ------------------------------------------------
    # Stage 0: walker now returns (graph_info, findings). Findings flow into
    # ``warnings`` (single source of truth); renderers categorize at output
    # time by filtering on ``Diagnostic.id``.
    cross_findings, cross_diagnostics = _build_cross_workflow_findings(
        cw_result=cw_result,
        notes=notes,
        per_call_rows=per_call_rows,
        ctx=ctx,
        call_counts_by_node=per_call_result.call_counts_by_node,
    )
    warnings.extend(cross_diagnostics)
    if trace_data is not None:
        warnings.extend(
            _emit_discrepancy_diagnostics(
                ctx=ctx,
                cw_result=cw_result,
                notes=notes,
            )
        )

    if _trace_coverage_for_rows(per_call_rows, ctx)[0] == "truncated":
        warnings = _filter_trace_dependent_warnings(warnings)
        suggested_blocks = []
        notes.append(
            "Trace-dependent optimization recommendations suppressed because the trace is truncated "
            "(workflow did not finish); per-call rows show executed trace evidence only."
        )

    # --- Confidence aggregation (STRICT per DD#34) ---------------------------
    confidence, coverage = _aggregate_confidence(per_call_rows)
    output_tokens_by_node: Mapping[tuple[str | None, str], int | None] = {
        (row.workflow_path, row.node_path): row.output_tokens_estimated for row in per_call_rows
    }
    ttl_by_workflow = _cache_ttl_by_workflow(cw_result, fallback_workflow_path=lookup_path, fallback_cache=cache_block)
    _enrich_shadow_warnings_with_costs(
        rows=per_call_rows,
        warnings=warnings,
        output_tokens_by_node=output_tokens_by_node,
        ttl_by_workflow=ttl_by_workflow,
    )

    scope_workflow_paths = _scope_workflow_paths(scope_mismatch, lookup_path, per_call_rows)

    summary = _build_summary(
        per_call_rows,
        warnings,
        ttl=_extract_cache_ttl(cache_block),
        ctx=ctx,
        edge_child_paths=edge_child_paths,
        ir_default_model=ir_default_model,
        scope_workflow_paths=scope_workflow_paths,
        trace_index=trace_index,
    )
    summary = replace(
        summary,
        trace_workflow_relationship=_derive_trace_workflow_relationship(
            trace_loaded=trace_data is not None,
            scope_mismatch=scope_mismatch,
            appears_as_child=appears_as_child,
            drift_count=drift_count,
        ),
        trace_model_drift_count=drift_count,
        sub_workflow_rollup=_build_sub_workflow_rollup(
            cw_result,
            lookup_path,
            rows=per_call_rows,
            trace_index=trace_index,
            ttl=_extract_cache_ttl(cache_block),
            notes=notes,
        ),
        suggested_run_command=_format_workflow_run_command(workflow_path, workflow_ir.get("inputs")),
    )

    # Recommended actions are a renderer-side projection over ``warnings``
    # (see ``view_helpers.build_recommended_actions``). No longer pre-computed
    # in the data model — Stage 0 of the data-shape redesign.

    # Gemini telemetry note (Spike 1 outcome — last in note ordering).
    if trace_data is not None:
        _maybe_append_gemini_note(per_call_rows, notes)

    return _types.CacheAnalysis(
        workflow_path=workflow_path or "<inline>",
        analyzed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        estimate_confidence=confidence,
        estimate_confidence_coverage=coverage,
        trace_path=used_trace_path,
        summary=summary,
        suggested_blocks=tuple(suggested_blocks),
        per_call=tuple(per_call_rows),
        cross_workflow=cross_findings,
        warnings=tuple(warnings),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Pipeline helpers (lift complexity out of ``analyze()``)
# ---------------------------------------------------------------------------


def _extract_declared_chunks(cache_block: Any) -> list[str]:
    """Extract chunk names from a workflow's ``## Cache`` block IR."""
    if not isinstance(cache_block, dict):
        return []
    items = cache_block.get("items") or []
    if not isinstance(items, list):
        return []
    return [item.get("name", "") for item in items if isinstance(item, dict) and item.get("name")]


def _row_model_drift(
    row: _types.PerCallRow,
    irs_by_workflow: Mapping[str, Mapping[str, Any]],
    default_model: str | None,
) -> tuple[str, str] | None:
    """Return ``(trace_model, ir_model)`` if this row has drift, else ``None``.

    Skip conditions (all return ``None``): heterogeneous row, ambiguous or
    missing trace model, missing workflow_path/IR, templated or absent
    IR-static model, normalized models equal.
    """
    if row.model_is_heterogeneous or len(row.observed_models) != 1:
        return None
    trace_model = normalize_model_name(row.observed_models[0])
    if not trace_model or row.workflow_path is None:
        return None
    ir = irs_by_workflow.get(row.workflow_path)
    if ir is None:
        return None
    ir_node = next(
        (n for n in (ir.get("nodes") or []) if isinstance(n, dict) and n.get("id") == row.node_path),
        None,
    )
    ir_model = _resolve_ir_static_model_for_node(ir_node, default_model)
    if ir_model is None or ir_model == trace_model:
        return None
    return trace_model, ir_model


def _detect_per_node_model_drift(
    per_call_rows: Sequence[_types.PerCallRow],
    irs_by_workflow: Mapping[str, Mapping[str, Any]],
    default_model: str | None,
) -> tuple[str | None, int]:
    """Detect per-node model drift between trace and current IR.

    Compares each per-call row's single trace-observed model against the
    IR-static model for that node. Returns one grouped Notes string when any
    drift is found, else ``None``.

    Why this matters: ``_resolve_effective_row_model`` declares "trace wins"
    so ``row.model`` and downstream projections use trace-side pricing. If the
    workflow's model changed after the trace was recorded, projections silently
    misprice. Actually-paid (from recorded ``cost_usd``) is correct regardless.
    """
    drifts: list[tuple[str, str, str]] = []  # (node_id, trace_model, ir_model)
    seen: set[tuple[str | None, str]] = set()
    for row in per_call_rows:
        key = (row.workflow_path, row.node_path)
        if key in seen:
            continue
        seen.add(key)
        drift = _row_model_drift(row, irs_by_workflow, default_model)
        if drift is not None:
            drifts.append((row.node_path, drift[0], drift[1]))

    if not drifts:
        return None, 0

    if len(drifts) == 1:
        node_id, trace_model, ir_model = drifts[0]
        return (
            f"Trace was recorded with model `{trace_model}` for node `{node_id}`; "
            f"current workflow declares `{ir_model}`. Actually-paid is correct; "
            f"cost projections use trace-side pricing. Re-record a trace to refresh."
        ), 1

    items = ", ".join(f"`{node_id}` ({trace_model} → {ir_model})" for node_id, trace_model, ir_model in drifts)
    return (
        f"Trace was recorded with different models than current workflow for "
        f"{len(drifts)} nodes: {items}. Actually-paid is correct; "
        f"cost projections use trace-side pricing. Re-record a trace to refresh."
    ), len(drifts)


def _cache_ttl_by_workflow(
    cw_result: Any,
    *,
    fallback_workflow_path: str,
    fallback_cache: Any,
) -> Mapping[str | None, str | None]:
    """Map workflow path to its own cache TTL for row-scoped pricing.

    Inline / synthesized workflows surface as rows with ``workflow_path=None``;
    their TTL falls back to the analyzed workflow's cache block so Anthropic
    1h declarations don't silently revert to the default write rate.
    """
    irs_by_workflow = getattr(cw_result, "irs_by_workflow", {}) or {}
    result: dict[str | None, str | None] = {}
    for workflow_path, workflow_ir in irs_by_workflow.items():
        cache_block = workflow_ir.get("cache") if isinstance(workflow_ir, dict) else None
        result[str(workflow_path)] = _extract_cache_ttl(cache_block)
    fallback_ttl = _extract_cache_ttl(fallback_cache)
    if fallback_workflow_path not in result:
        result[fallback_workflow_path] = fallback_ttl
    result.setdefault(None, fallback_ttl)
    return result


def _build_parameters_by_workflow(
    cw_result: Any,
    root_parameters: dict[str, Any],
    root_workflow_path: str,
    *,
    memo_cache: Any | None,
    trace_data: Mapping[str, Any] | None,
    base_path: Path | None,
    trace_outputs_by_key: Mapping[tuple[str | None, str], Any] | None = None,
    stale_memo_uncheckable: set[tuple[str | None, str]] | None = None,
) -> dict[str | None, dict[str, Any]]:
    """Build workflow-scoped parameter views from cross-workflow input edges."""
    params_by_workflow: dict[str | None, dict[str, Any]] = {root_workflow_path: dict(root_parameters)}
    irs_by_workflow = getattr(cw_result, "irs_by_workflow", {}) or {}
    remaining = list(getattr(cw_result, "edges", ()) or ())
    made_progress = True
    while remaining and made_progress:
        made_progress = False
        next_remaining = []
        for edge in remaining:
            parent_workflow = str(getattr(edge, "parent_workflow", root_workflow_path))
            if parent_workflow not in params_by_workflow:
                next_remaining.append(edge)
                continue
            child_workflow = getattr(edge, "child_workflow", None)
            child_input_name = getattr(edge, "child_input_name", None)
            if child_workflow is None or child_input_name is None:
                continue
            parent_ctx = AnalysisContext.build(
                workflow_ir=irs_by_workflow.get(parent_workflow, {}),
                parameters=params_by_workflow[parent_workflow],
                memo_cache=memo_cache,
                trace_data=trace_data,
                trace_outputs_by_key=trace_outputs_by_key or {},
                workflow_path=parent_workflow,
                base_path=base_path,
                parameters_by_workflow=params_by_workflow,
            )
            resolved = _resolve_child_input_value(edge, parent_ctx)
            if resolved is None:
                continue
            if stale_memo_uncheckable is not None:
                stale_memo_uncheckable.update(_unchecked_parent_memo_roots(edge, parent_ctx))
            child_params = params_by_workflow.setdefault(str(child_workflow), {})
            child_params[str(child_input_name)] = resolved
            made_progress = True
        remaining = next_remaining
    return params_by_workflow


def _resolve_child_input_value(edge: CrossWorkflowEdge, parent_ctx: AnalysisContext) -> Any | None:
    """Resolve a child workflow input value from the parent's analysis context.

    Batch sub-workflow calls can pass values rooted on the parent batch alias
    (for example ``${item}`` or ``${item.field}``). Static analysis cannot know
    every runtime item, so this uses ``items[0]`` as a deterministic exemplar
    when the parent's ``batch.items`` expression is resolvable, falling back to
    trace-recorded batch items when the trace is the only available evidence.
    """
    value = edge.parent_input_value
    if not isinstance(value, str):
        return _normalize_empty(value)
    refs = _extract_unique_refs(value)
    if not refs:
        return _normalize_empty(value)
    shared = _build_shared_store_for_refs(refs, parent_ctx)
    if edge.is_batch_alias_root:
        first_item = _resolve_first_batch_item(edge, parent_ctx)
        if first_item is None:
            return None
        if edge.parent_batch_alias is not None:
            shared[edge.parent_batch_alias] = first_item
    from pflow.runtime.template_resolver import TemplateResolver

    try:
        resolved = TemplateResolver.resolve_template(value, shared)
    except Exception:
        logger.debug("failed to resolve child workflow input value", exc_info=True)
        return None
    if isinstance(resolved, str) and TemplateResolver.TEMPLATE_PATTERN.search(resolved):
        return None
    return _normalize_empty(resolved)


def _unchecked_parent_memo_roots(
    edge: CrossWorkflowEdge,
    parent_ctx: AnalysisContext,
) -> set[tuple[str | None, str]]:
    """Node-output roots used to seed child params before prediction can verify memo."""
    value = edge.parent_input_value
    if not isinstance(value, str) or parent_ctx.memo_cache is None:
        return set()
    declared_inputs = parent_ctx.workflow_ir.get("inputs") if isinstance(parent_ctx.workflow_ir, Mapping) else None
    input_names = set(declared_inputs) if isinstance(declared_inputs, Mapping) else set()
    tainted: set[tuple[str | None, str]] = set()
    from pflow.runtime.template_resolver import TemplateResolver

    for ref in _extract_unique_refs(value):
        root = TemplateResolver.extract_root_node_id(ref)
        if not root or root in input_names or root == edge.parent_batch_alias:
            continue
        tainted.add((parent_ctx.workflow_path, root))
    return tainted


def _resolve_first_batch_item(edge: CrossWorkflowEdge, parent_ctx: AnalysisContext) -> Any | None:
    """Resolve the parent batch's ``items:`` expression and return its first item."""
    nodes_by_id = {
        str(n["id"]): n for n in parent_ctx.workflow_ir.get("nodes", []) if isinstance(n, dict) and "id" in n
    }
    parent_node = nodes_by_id.get(edge.parent_node_id)
    if parent_node is None:
        return None
    batch = parent_node.get("batch")
    if not isinstance(batch, dict):
        return None
    items_expr = batch.get("items")
    if isinstance(items_expr, list):
        return _normalize_empty(items_expr[0]) if items_expr else None
    if not isinstance(items_expr, str):
        return None
    from pflow.runtime.template_resolver import TemplateResolver

    try:
        resolved = TemplateResolver.resolve_template(
            items_expr,
            _build_shared_store_for_refs(_extract_unique_refs(items_expr), parent_ctx),
        )
    except Exception:
        logger.debug("failed to resolve batch items expression", exc_info=True)
        return None
    if isinstance(resolved, list) and resolved:
        return _normalize_empty(resolved[0])
    trace_item = _resolve_first_trace_batch_item(edge, parent_ctx)
    if trace_item is not None:
        return trace_item
    return None


def _resolve_first_trace_batch_item(edge: CrossWorkflowEdge, parent_ctx: AnalysisContext) -> Any | None:
    """Return the first recorded runtime batch item for ``edge.parent_node_id``."""
    event = parent_ctx.trace_event_for(edge.parent_node_id)
    if not isinstance(event, Mapping):
        return None
    batch_items = event.get("batch_items")
    if not isinstance(batch_items, list):
        return None
    item_events = [item for item in batch_items if isinstance(item, Mapping)]
    if not item_events:
        return None
    first = min(item_events, key=lambda item: int(item.get("index") or 0))
    return _normalize_empty(first.get("item"))


def _build_per_call_rows_and_warnings(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    trace_index: _types.TraceExecutionIndex,
) -> _PerCallRowsResult:
    """Walk every reachable workflow IR and build LLM rows."""
    rows: list[_types.PerCallRow] = []
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


def _build_call_counts_by_node(ctx: AnalysisContext, cw_result: Any) -> dict[tuple[str | None, str], int]:
    """Observed LLM call counts keyed like per-call rows."""
    if ctx.trace is None:
        return {}
    counts: dict[tuple[str | None, str], int] = {}
    edges_map = _edge_child_paths(cw_result)
    for leaf in ctx.trace.iter_llm_leaves(edges=edges_map, workflow_path=ctx.workflow_path):
        llm_call = leaf.llm_call
        if llm_call is not None and llm_call.get("is_warmup"):
            continue
        node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
        key = (leaf.workflow_path, node_id)
        counts[key] = counts.get(key, 0) + 1
    return counts


@dataclass(frozen=True)
class _RowCrossWorkflowCandidate:
    """Per-row cache opportunity from a cross-workflow boundary."""

    parent_workflow: str
    parent_value_expr: str
    parent_cache_ref: str
    parent_node_id: str
    child_workflow: str
    child_input_name: str
    child_cache_ref: str
    parent_prose: str
    child_node_ids: tuple[str, ...]
    estimated_tokens_per_call: int
    threshold_floor: int


def _build_cross_workflow_candidates_by_row(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    call_counts_by_node: dict[tuple[str | None, str], int],
    trace_index: _types.TraceExecutionIndex,
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
    trace_index: _types.TraceExecutionIndex,
) -> tuple[_RowCrossWorkflowCandidate, ...]:
    """Return gated row-level candidates for one cross-workflow edge."""
    from .stages.cross_workflow import (
        _append_child_suffix,
        _cache_ref_is_declared_or_covered,
        _child_cache_ref_consumers,
        _estimate_parent_value_tokens,
        _items_by_name,
        _parent_prose_for_cache_ref,
    )

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
    from .stages.cross_workflow import (
        _cache_ref_is_declared_or_covered,
        _child_cache_ref_consumers,
        _items_by_name,
    )

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
    trace_index: _types.TraceExecutionIndex | None = None,
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


def _detect_candidate_subsets(workflow_ir: dict[str, Any]) -> dict[str, list[str]]:
    """Map LLM node_id → list of shared template refs (≥2 nodes share each).

    Pure walker — no tokenization. Tier 2 of ``estimate_cacheable_tokens``
    consumes the per-node candidate to project cacheable counts via memo.

    Returns an empty dict when the workflow already declares ``## Cache``
    (greenfield-only signal — declared subsets win at Tier 1/2; candidates
    don't apply when ``prompt_cache:`` is set).
    """
    if _cache_item_names(workflow_ir):
        return {}
    ref_to_nodes, _ = _collect_llm_template_references(workflow_ir)
    candidates_by_node: dict[str, list[str]] = {}
    for ref, node_ids in ref_to_nodes.items():
        if len(node_ids) < 2:
            continue
        for node_id in node_ids:
            candidates_by_node.setdefault(node_id, []).append(ref)
    return candidates_by_node


# ---------------------------------------------------------------------------
# Per-node analysis
# ---------------------------------------------------------------------------


def _run_full_validation(
    workflow_ir: dict[str, Any],
    *,
    workflow_path: str | None,
) -> list[Diagnostic]:
    """Run the same validator pipeline used by run, validate-only, and save.

    Real analyzer parameters are intentionally not merged into validation
    parameters here. ``WorkflowValidator`` receives dummy values derived from
    declared inputs, matching the other validation entry points and avoiding a
    stricter analyze-cache-only interpretation of user-provided params.
    """
    inputs = workflow_ir.get("inputs") or {}
    validation_params = generate_dummy_parameters(inputs)
    workflow_file: Path | None = None
    if workflow_path and not workflow_path.startswith("ir-hash:"):
        workflow_file = Path(workflow_path)

    try:
        diagnostics = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            extracted_params=validation_params,
            workflow_file=workflow_file,
        )
    except Exception as exc:
        logger.warning(
            "WorkflowValidator.validate raised %s during analyze-cache; findings may be incomplete",
            type(exc).__name__,
            exc_info=True,
        )
        return [
            Diagnostic(
                severity=Severity.WARNING,
                source="cache_analyzer",
                title="Validator Error",
                node_id=None,
                message=(
                    f"Validation pipeline failed during analyze-cache ({type(exc).__name__}). "
                    "Cache analysis is best-effort; findings may be incomplete. "
                    "Run `pflow run --validate-only <workflow>` to see the underlying error."
                ),
                context={
                    "category": "cache_analyzer",
                    "affected_workflow": workflow_path,
                    "exception_class": type(exc).__name__,
                },
            )
        ]

    enriched: list[Diagnostic] = []
    for diag in diagnostics:
        context = dict(diag.context or {})
        current = context.get("affected_workflow")
        if (not current or current == "<unknown>") and workflow_path:
            context["affected_workflow"] = workflow_path
        enriched.append(replace(diag, context=context))
    return enriched


__all__ = [
    "analyze",
]
