"""Tier 2 + Tier 3 cache analyzer entry point.

``analyze(workflow, parameters)`` composes:

- F1.2 ``token_estimation`` (per-call tier),
- F1.3 ``sub_workflow_walker`` walker (Tier 2),
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
from dataclasses import replace
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
from pflow.core.llm_config import get_default_workflow_model
from pflow.core.prompt_cache import (  # noqa: F401 — see docstring.
    _CHUNK_ABSENT,
    _resolve_chunk_value,
    _resolve_static_prefix_for_cache,
    deterministic_serialize,
)
from pflow.core.trace_tree import normalize_workflow_path_key
from pflow.core.validation_utils import generate_dummy_parameters
from pflow.core.workflow.validator import WorkflowValidator
from pflow.core.workflow_id import synthesize_inline_workflow_id

from . import types as _types
from .context import AnalysisContext
from .stages.cross_workflow import _build_cross_workflow_findings
from .stages.discrepancy import (
    _attach_predicted_cache_keys,
    _emit_discrepancy_diagnostics,
    _format_dynamic_batches_note,
)
from .stages.fragmentation import _detect_model_cache_fragmentation, _detect_system_cache_fragmentation
from .stages.partial_declarations import _emit_partial_declaration_findings
from .stages.per_call_pipeline import _build_per_call_rows_and_warnings, _PerCallRowsResult
from .stages.row_builder import _extract_declared_chunks
from .stages.suggestions import (
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
from .stages.warnings import _enrich_shadow_warnings_with_costs
from .sub_workflow_walker import _build_parameters_by_workflow, walk_cross_workflow
from .trace_loading import (
    _build_trace_execution_index,
    _default_memo_cache,
    _derive_trace_workflow_relationship,
    _detect_per_node_model_drift,
    _diagnostics_from_trace_warnings,
    _edge_child_paths,
    _format_rejection_note,
    _resolve_trace_data,
    _resolve_trace_scope,
    _scope_workflow_paths,
)

logger = logging.getLogger(__name__)


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
    lookup_path = (
        normalize_workflow_path_key(workflow_path)
        if workflow_path is not None
        else synthesize_inline_workflow_id(workflow_ir)
    )

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
    ctx, _predicted_cache_keys, _prediction_fidelity_notes = _attach_predicted_cache_keys(ctx, cw_result)

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
    if trace_path is None and any(row.did_not_execute_in_trace for row in per_call_rows):
        per_call_result, ctx, trace_index, trace_data, used_trace_path = _recompute_after_trace_misalignment(
            ctx=ctx,
            cw_result=cw_result,
            lookup_path=lookup_path,
            used_trace_path=used_trace_path,
            trace_data=trace_data,
            notes=notes,
            edge_child_paths=edge_child_paths,
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

    _append_per_call_visibility_notes(per_call_rows, per_call_result, notes)
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
        trace_workflow_relationship=_derive_trace_workflow_relationship(
            trace_loaded=trace_data is not None,
            scope_mismatch=scope_mismatch,
            appears_as_child=appears_as_child,
            drift_count=drift_count,
        ),
        drift_count=drift_count,
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


def _recompute_after_trace_misalignment(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    lookup_path: str,
    used_trace_path: str | None,
    trace_data: dict[str, Any] | None,
    notes: list[str],
    edge_child_paths: dict[str, str],
) -> tuple[_PerCallRowsResult, AnalysisContext, _types.TraceExecutionIndex, dict[str, Any] | None, str | None]:
    """Fall back to greenfield when an auto-loaded trace does not match this IR."""
    notes.append(_format_rejection_note(used_trace_path, trace_data))
    trace_data = None
    used_trace_path = None
    trace_index = _build_trace_execution_index(trace_data, lookup_path, edge_child_paths)
    parameters_by_workflow = _build_parameters_by_workflow(
        cw_result,
        dict(ctx.parameters),
        lookup_path,
        memo_cache=ctx.memo_cache,
        trace_data=trace_data,
        trace_outputs_by_key=trace_index.outputs_by_key,
        base_path=ctx.base_path,
    )
    new_ctx = AnalysisContext.build(
        workflow_ir=ctx.workflow_ir,
        parameters=dict(ctx.parameters),
        memo_cache=ctx.memo_cache,
        trace_data=trace_data,
        trace_outputs_by_key=trace_index.outputs_by_key,
        workflow_path=lookup_path,
        base_path=ctx.base_path,
        parameters_by_workflow=parameters_by_workflow,
        predicted_cache_keys=ctx.predicted_cache_keys,
        prediction_fidelity_notes=ctx.prediction_fidelity_notes,
        stale_memo_skipped=ctx.stale_memo_skipped,
        stale_memo_uncheckable=ctx.stale_memo_uncheckable,
    )
    per_call_result = _build_per_call_rows_and_warnings(
        ctx=new_ctx,
        cw_result=cw_result,
        trace_index=trace_index,
    )
    return per_call_result, new_ctx, trace_index, trace_data, used_trace_path


def _append_per_call_visibility_notes(
    per_call_rows: Sequence[_types.PerCallRow],
    per_call_result: _PerCallRowsResult,
    notes: list[str],
) -> None:
    """Append notes that explain why per-call rows may be hidden or incomplete."""
    if per_call_rows and not any(row.has_real_data for row in per_call_rows):
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
        elif isinstance(current, str):
            context["affected_workflow"] = normalize_workflow_path_key(current)
        enriched.append(replace(diag, context=context))
    return enriched


__all__ = [
    "analyze",
]
