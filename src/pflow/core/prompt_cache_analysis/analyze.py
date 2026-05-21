"""Tier 2 + Tier 3 cache analyzer entry point.

``analyze(workflow, parameters)`` composes:

- F1.2 ``token_estimation`` (per-call tier),
- F1.3 ``cross_workflow`` walker (Tier 2),
- F1.4 ``padding_advisor`` (sensitivity-floored advisories),
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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

# Imported for the predicted-cache_key contract (Round 4 high-value fix #2):
# when ``cache.discrepancy`` detection wires up in v1.x, it MUST use the shared
# resolution helpers from ``core.prompt_cache`` so predicted cache_keys are
# byte-identical to runtime's. Eager import here locks the layer-policy
# contract — if a future contributor moves either helper, this file fails to
# import and the test suite catches it. v1 scaffolds the discrepancy slot but
# defers full prediction; the helpers will be consumed when that lands.
from pflow.core.cache_ttl import parse_cache_ttl
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import CompilationError, MarkdownParseError, SchemaValidationError, WorkflowValidationError
from pflow.core.llm_capabilities import anthropic_models_at_threshold, get_min_cache_tokens
from pflow.core.llm_config import get_default_workflow_model
from pflow.core.llm_providers import detect_provider, normalize_model_name
from pflow.core.llm_usage import normalize_litellm_usage_tokens
from pflow.core.prompt_cache import (  # noqa: F401 — see docstring.
    _CHUNK_ABSENT,
    _resolve_chunk_value,
    _resolve_static_prefix_for_cache,
    deterministic_serialize,
)
from pflow.core.prompt_refs import PromptRef, classify_prompt_refs, first_per_item_position
from pflow.core.validation_utils import generate_dummy_parameters
from pflow.core.workflow.validator import WorkflowValidator
from pflow.core.workflow_id import synthesize_inline_workflow_id
from pflow.runtime.template_resolver import TemplateResolver

from .below_min_tokens_detector import (
    BatchPrewarmBelowMinEvidence,
    BelowMinTokensEvidence,
    detect_batch_prewarm_below_min,
    is_below_min_cache,
    is_likely_below_min_cache,
)
from .below_min_tokens_detector import (
    detect as detect_below_min_tokens,
)
from .context import _PREDICTION_SKIPPED, AnalysisContext, _latest_memo_for_freshness_check, _normalize_empty
from .cross_workflow import CrossWorkflowEdge, DynamicBatchInfo, walk_cross_workflow
from .padding_advisor import PaddingCandidate, compute_padding_advisories
from .token_estimation import (
    _estimate_ref_tokens,
    estimate_cacheable_tokens,
    estimate_output_tokens,
    estimate_tokens,
    tokenize_prompt_region,
    tokenize_prompt_region_for_projection,
    tokenize_prompt_region_lower_bound_for_projection,
)
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
    _is_llm_node,
    _resolve_ir_static_model_for_node,
    _resolve_trace_data,
    _resolve_trace_scope,
    _scope_workflow_paths,
)
from .types import (
    _BLOCK_ABSENT_BRANCH,
    _BLOCK_BELOW_PROVIDER_MIN,
    _BLOCK_PREWARM_IMAGES,
    _BLOCK_RUNTIME_STRIPPED,
    _PROJECTION_NOT_APPLICABLE,
    _PROJECTION_UNAVAILABLE,
    AnalysisSummary,
    CacheAnalysis,
    CacheProjection,
    CacheProjectionComponent,
    CostDelta,
    CrossWorkflowFindings,
    CrossWorkflowInputContribution,
    PerCallRow,
    PerNodeThresholdEntry,
    SubWorkflowRollup,
    SubWorkflowRollupEntry,
    SuggestedBlock,
    SuggestedBlockChunk,
    TraceExecutionIndex,
    TraceUnexecutedLLMRow,
    _projection_component,
    _projection_source_confidence,
    _provider_min_state,
    _safe_pct,
    aggregate_projection,
    invocation_count_for,
)
from .warning_catalog import CACHE_WARNING_CATALOG, make_diagnostic

logger = logging.getLogger(__name__)

_SUGGESTED_BLOCK_ACTIONABLE: str = "actionable"
_SUGGESTED_BLOCK_BELOW_THRESHOLD: str = "below_threshold"
_SUGGESTED_BLOCK_EVIDENCE_INCOMPLETE: str = "evidence_incomplete"
_SUGGESTED_BLOCK_INSUFFICIENT_NODES: str = "insufficient_nodes"
_PARENT_PROSE_PREVIEW_LIMIT = 40


_PREDICTION_RECOVERABLE_EXCEPTIONS: Final[tuple[type[Exception], ...]] = (
    CompilationError,
    MarkdownParseError,
    SchemaValidationError,
    WorkflowValidationError,
    FileNotFoundError,
    ValueError,
    KeyError,
    RecursionError,
    OSError,
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PromptStaticTailFinding:
    dynamic_ref: str
    dynamic_line: int
    stable_tail_tokens: int
    tokens_before_dynamic: int | None
    template_refs_after_dynamic: int
    static_tail_excerpt: str
    meets_provider_min: bool | None = None
    provider_min_tokens: int | None = None
    blocked_reason: str = ""


@dataclass(frozen=True)
class _PerCallRowsResult:
    rows: list[PerCallRow]
    warnings: list[Diagnostic]
    call_counts_by_node: dict[tuple[str | None, str], int]
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[_RowCrossWorkflowCandidate]]
    has_greenfield_cross_workflow_projection_gap: bool = False


@dataclass(frozen=True)
class _PartialDeclarationFinding:
    node_id: str
    declared_chunks: tuple[str, ...]
    missing_chunks: tuple[str, ...]
    corrected_prompt_cache: tuple[str, ...]
    prompt_body_cleanup: tuple[str, ...]
    missing_chunks_tokens: int | None
    rep_model: str


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
) -> CacheAnalysis:
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
    suggested_blocks: list[SuggestedBlock] = []

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

    return CacheAnalysis(
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
    row: PerCallRow,
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
    per_call_rows: Sequence[PerCallRow],
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


def _extract_cache_ttl(cache_block: Any) -> str | None:
    """Read the validated TTL from a ``## Cache`` block."""
    if not isinstance(cache_block, dict):
        return None
    ttl_value = cache_block.get("ttl")
    if ttl_value is None:
        return None
    if not isinstance(ttl_value, str):
        return None
    try:
        parse_cache_ttl(ttl_value)
    except ValueError:
        return None
    return ttl_value


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
    from .cost_estimation import compute_projections

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
        projections = compute_projections(workflow_rows, output_tokens_by_node=output_tokens, ttl=ttl)
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


def _enrich_shadow_warnings_with_costs(
    *,
    rows: Sequence[PerCallRow],
    warnings: Sequence[Diagnostic],
    output_tokens_by_node: Mapping[tuple[str | None, str], int | None],
    ttl_by_workflow: Mapping[str | None, str | None],
) -> None:
    """Attach body-only vs with-cache per-call costs to shadow warnings.

    The validator owns the structural finding. Analyzer-tier enrichment adds
    cost evidence only when pricing and output tokens are known; otherwise the
    warning remains a pure structural suggestion.
    """
    rows_by_key = {(row.workflow_path, row.node_path): row for row in rows}
    for diag in warnings:
        _enrich_one_shadow_warning(
            diag=diag,
            rows=rows,
            rows_by_key=rows_by_key,
            output_tokens_by_node=output_tokens_by_node,
            ttl_by_workflow=ttl_by_workflow,
        )


def _enrich_one_shadow_warning(
    *,
    diag: Diagnostic,
    rows: Sequence[PerCallRow],
    rows_by_key: Mapping[tuple[str | None, str], PerCallRow],
    output_tokens_by_node: Mapping[tuple[str | None, str], int | None],
    ttl_by_workflow: Mapping[str | None, str | None],
) -> None:
    from .cost_estimation import (
        _row_body_only_cost,
        _row_first_run_with_cache_cost,
        get_model_pricing,
    )

    if diag.id != "cache.prompt-body-shadows-cache" or diag.context is None:
        return
    context = diag.context
    cache_contains_body_pairs = _cache_contains_body_pairs(context.get("shadowing_pairs"))
    node_id = context.get("node_id") or diag.node_id
    if not cache_contains_body_pairs or not isinstance(node_id, str):
        return
    row = _row_for_shadow_warning(
        rows=rows,
        rows_by_key=rows_by_key,
        affected_workflow=context.get("affected_workflow"),
        node_id=node_id,
    )
    if row is None or not row.model:
        return
    pricing = get_model_pricing(row.model)
    output_tokens = _output_tokens_for_row(row, output_tokens_by_node)
    shadowed_chunks = _shadowed_chunk_names(cache_contains_body_pairs)
    if pricing is None or output_tokens is None or not shadowed_chunks:
        return

    invocation_count = invocation_count_for(row)
    context["body_only_cost_usd_per_call"] = _row_body_only_cost(row, pricing, output_tokens) / invocation_count
    context["with_cache_cost_usd_per_call"] = (
        _row_first_run_with_cache_cost(
            row,
            pricing,
            output_tokens,
            ttl=_ttl_for_row(row, ttl_by_workflow),
        )
        / invocation_count
    )
    context["shadowed_chunk_names"] = shadowed_chunks


def _ttl_for_row(row: PerCallRow, ttl_by_workflow: Mapping[str | None, str | None]) -> str | None:
    return ttl_by_workflow.get(row.workflow_path)


def _output_tokens_for_row(
    row: PerCallRow,
    output_tokens_by_node: Mapping[tuple[str | None, str], int | None],
) -> int | None:
    return output_tokens_by_node.get((row.workflow_path, row.node_path))


def _cache_contains_body_pairs(raw_pairs: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_pairs, list):
        return []
    return [pair for pair in raw_pairs if isinstance(pair, dict) and pair.get("direction") == "cache_contains_body"]


def _row_for_shadow_warning(
    *,
    rows: Sequence[PerCallRow],
    rows_by_key: Mapping[tuple[str | None, str], PerCallRow],
    affected_workflow: Any,
    node_id: str,
) -> PerCallRow | None:
    workflow_path = affected_workflow if isinstance(affected_workflow, str) else None
    row = rows_by_key.get((workflow_path, node_id))
    if row is not None:
        return row
    return next((candidate for candidate in rows if candidate.node_path == node_id), None)


def _shadowed_chunk_names(pairs: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted({
            str(pair["chunk_name"])
            for pair in pairs
            if isinstance(pair.get("chunk_name"), str) and pair.get("chunk_name")
        })
    )


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


def _total_observed_invocations(
    *,
    child_workflow: str,
    child_node_ids: tuple[str, ...],
    call_counts_by_node: dict[tuple[str | None, str], int],
) -> int:
    return sum(call_counts_by_node.get((child_workflow, node_id), 0) for node_id in child_node_ids)


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


def _build_per_call_row(
    *,
    node: dict[str, Any],
    ctx: AnalysisContext,
    declared_chunks: list[str],
    candidate_subset: list[str] | None = None,
    trace_cost: tuple[float | None, str] | None = None,
    trace_llm_call: dict[str, Any] | None = None,
    trace_llm_calls: tuple[dict[str, Any], ...] = (),
    provider_trace_llm_call: dict[str, Any] | None = None,
    provider_trace_llm_calls: tuple[dict[str, Any], ...] = (),
    did_not_execute_in_trace: bool = False,
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[_RowCrossWorkflowCandidate]] | None = None,
) -> PerCallRow:
    """Compose a single PerCallRow for an LLM node."""
    workflow_path = ctx.workflow_path
    memo_cache = ctx.memo_cache
    node_id = str(node.get("id", "?"))
    explicit = node.get("params", {}).get("model") or node.get("model")
    observed_models = tuple(sorted({str(call.get("model")) for call in trace_llm_calls if call.get("model")}))
    observed_call_count = len(trace_llm_calls)
    model, model_is_heterogeneous = _resolve_effective_row_model(explicit, observed_models)
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt, str):
        prompt = str(prompt) if prompt is not None else ""
    batch = node.get("batch")
    is_batch = isinstance(batch, dict) and bool(batch)
    batch_size = _estimate_batch_size(batch) if isinstance(batch, dict) and is_batch else None

    # Track C (Phase C): resolve the prompt template before tokenization so
    # ${context}, ${question}, etc. count as their actual byte lengths
    # instead of the literal ``${context}`` string (~5 chars). Trace tier
    # short-circuits before this — for trace data the input_tokens come
    # straight from ``llm_call.input_tokens`` and template resolution is
    # irrelevant. For the estimator tier on greenfield workflows, resolved
    # prompts produce realistic token counts when the agent passes
    # ``--inputs`` covering the referenced variables.
    resolved_prompt, has_unresolved = _resolve_prompt_for_tokenization(prompt, ctx, node)
    declared_subset = node.get("prompt_cache") or None
    if declared_subset is not None and not isinstance(declared_subset, list):
        declared_subset = None
    input_tokens, chunk_tokens, source, output_tokens, output_source = _estimate_row_tokens(
        model=model,
        resolved_prompt=resolved_prompt,
        memo_cache=memo_cache,
        node_id=node_id,
        workflow_path=workflow_path,
        has_unresolved=has_unresolved,
        trace_llm_call=trace_llm_call,
        declared_subset=declared_subset,
        ctx=ctx,
    )
    # Trace token fields are per-call by contract via _aggregate_trace_llm_calls.
    # Keep the clamp as defense for rare tokenizer drift between declared-cache
    # tokenization and provider trace accounting.
    chunk_tokens = min(chunk_tokens, input_tokens)

    # Tiered cacheable estimation (mirrors ``estimate_tokens`` /
    # ``estimate_output_tokens``). Trace beats memo/parameters; honest
    # ``None`` when nothing is projectable. ``declared_chunks`` (workflow-level
    # ## Cache items) is consumed elsewhere; here we pass declared_subset
    # (this node's ``prompt_cache:``) and candidate_subset (greenfield
    # candidates from shared template references).
    declared_tokens: int | None = None
    declared_source = "unavailable"
    if declared_subset:
        declared_tokens, declared_source = estimate_cacheable_tokens(
            declared_subset=declared_subset,
            candidate_subset=None,
            trace_event=provider_trace_llm_call,
            memo_cache=memo_cache,
            model=model,
            workflow_path=workflow_path,
            prompt=resolved_prompt,
            ctx=ctx,
        )

    candidate_tokens: int | None = None
    candidate_source = "unavailable"
    if candidate_subset:
        candidate_tokens, candidate_source = estimate_cacheable_tokens(
            declared_subset=None,
            candidate_subset=candidate_subset,
            trace_event=None,
            memo_cache=memo_cache,
            model=model,
            workflow_path=workflow_path,
            prompt=resolved_prompt,
            ctx=ctx,
        )

    cacheable_tokens, cacheable_source = estimate_cacheable_tokens(
        declared_subset=declared_subset,
        candidate_subset=candidate_subset,
        trace_event=provider_trace_llm_call,
        memo_cache=memo_cache,
        model=model,
        workflow_path=workflow_path,
        prompt=resolved_prompt,
        ctx=ctx,
    )
    batch_prefix_tokens = _estimate_batch_prefix_cacheable_tokens(
        node=node,
        model=model,
        prompt=prompt,
        declared_subset=declared_subset,
        observed_call_count=observed_call_count,
        ctx=ctx,
    )
    dynamic_tail_finding = _estimate_dynamic_tail_opportunity(
        node=node,
        row_model=model,
        prompt=prompt,
        observed_call_count=observed_call_count,
        batch_size=batch_size,
        declared_subset=declared_subset,
        ctx=ctx,
    )
    repeated_ref_component = _detect_repeated_row_stable_refs(
        node=node,
        model=model,
        input_tokens=input_tokens,
        observed_call_count=observed_call_count,
        batch_size=batch_size,
        ctx=ctx,
    )
    cacheable_tokens, cacheable_source = _prefer_batch_prefix_cacheable_tokens(
        node=node,
        model=model,
        prompt=prompt,
        declared_subset=declared_subset,
        observed_call_count=observed_call_count,
        current_tokens=cacheable_tokens,
        current_source=cacheable_source,
        ctx=ctx,
    )

    cross_workflow_components, cross_workflow_component_inputs = _cross_workflow_projection_components(
        workflow_path=workflow_path,
        node_id=node_id,
        model=model,
        input_tokens=input_tokens,
        cross_workflow_candidates_by_row=cross_workflow_candidates_by_row,
    )
    cacheable_tokens, cacheable_source, cross_workflow_inputs = _apply_cross_workflow_projection(
        workflow_path=workflow_path,
        node_id=node_id,
        model=model,
        cacheable_tokens=cacheable_tokens,
        cacheable_source=cacheable_source,
        cross_workflow_candidates_by_row=cross_workflow_candidates_by_row,
    )

    cacheable_with_clamp, ratio = _clamp_legacy_cacheable_projection(
        cacheable_tokens=cacheable_tokens,
        cacheable_source=cacheable_source,
        input_tokens=input_tokens,
        input_source=source,
        node_id=node_id,
        workflow_path=workflow_path,
        model=model,
    )

    # Track A (Phase A): per-node recorded cost from the trace. When trace
    # data exists for this node, the analyzer reports what the workflow
    # actually paid (honoring implicit caching like Gemini's). The renderer
    # uses this for the per-call cost column; the summary's actually-paid
    # figure is sourced separately via ``compute_actually_paid`` (which
    # prefers ``TraceTree.total_cost`` for the canonical sum).
    cost_value: float | None
    cost_source: str
    cost_value, cost_source = trace_cost if trace_cost is not None else ctx.cost_usd_for_node(node_id)
    if did_not_execute_in_trace:
        cost_value = None
        cost_source = "unavailable"
    elif cost_value is None:
        # No trace data — recompute fallback fires downstream. Mark the
        # tier label so the JSON consumer sees ``"recomputed"`` not
        # ``"unavailable"`` (the latter signals "no pricing data either",
        # which is checked by the renderer separately via ``unavailable_models``).
        cost_source = "recomputed"

    trace_cache_creation, trace_cache_read = _trace_cache_token_splits(provider_trace_llm_call)
    (
        cached_now_tokens_estimated,
        cache_configured,
        cache_active,
        cache_ready,
        cache_opportunity,
    ) = _build_cache_projection_components(
        node=node,
        model=model,
        input_tokens=input_tokens,
        declared_subset=declared_subset,
        candidate_subset=candidate_subset,
        declared_tokens=declared_tokens,
        declared_source=declared_source,
        candidate_tokens=candidate_tokens,
        candidate_source=candidate_source,
        batch_prefix_tokens=batch_prefix_tokens,
        dynamic_tail_finding=dynamic_tail_finding,
        repeated_ref_component=repeated_ref_component,
        cross_workflow_components=cross_workflow_components,
        provider_trace_llm_call=provider_trace_llm_call,
        provider_trace_llm_calls=provider_trace_llm_calls,
    )
    if not cross_workflow_inputs and cross_workflow_component_inputs:
        cross_workflow_inputs = cross_workflow_component_inputs

    return PerCallRow(
        node_path=node_id,
        model=model,
        is_batch=is_batch,
        batch_size_estimated=batch_size,
        input_tokens_estimated=input_tokens,
        chunk_tokens_estimated=chunk_tokens,
        cacheable_tokens_estimated=cacheable_with_clamp,
        cache_ratio_pct=ratio,
        data_source=source,
        declared_prompt_cache=list(declared_subset) if declared_subset else None,
        output_tokens_estimated=output_tokens,
        output_data_source=output_source,
        model_is_heterogeneous=model_is_heterogeneous,
        cacheable_data_source=cacheable_source,
        cache_creation_input_tokens=trace_cache_creation,
        cache_read_input_tokens=trace_cache_read,
        cached_now_tokens_estimated=cached_now_tokens_estimated,
        cache_configured=cache_configured,
        cache_active=cache_active,
        cache_ready=cache_ready,
        cache_opportunity=cache_opportunity,
        cost_usd=cost_value,
        cost_data_source=cost_source,
        workflow_path=workflow_path,
        did_not_execute_in_trace=did_not_execute_in_trace,
        observed_models=observed_models,
        observed_call_count=observed_call_count,
        provider_trace_llm_calls=provider_trace_llm_calls,
        cross_workflow_inputs=cross_workflow_inputs,
    )


def _apply_cross_workflow_projection(
    *,
    workflow_path: str | None,
    node_id: str,
    model: str,
    cacheable_tokens: int | None,
    cacheable_source: str,
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[_RowCrossWorkflowCandidate]] | None,
) -> tuple[int | None, str, tuple[CrossWorkflowInputContribution, ...]]:
    """Promote weak row evidence to a broader cross-workflow projection.

    Returns per-call projected tokens to match ``PerCallRow.cacheable_tokens_estimated``
    semantics — downstream cost helpers multiply by invocation count themselves.
    """
    if cross_workflow_candidates_by_row is None or cacheable_source not in {"unavailable", "parameters"}:
        return cacheable_tokens, cacheable_source, ()
    row_candidates = cross_workflow_candidates_by_row.get((workflow_path, node_id), [])
    if not row_candidates:
        return cacheable_tokens, cacheable_source, ()
    projected_tokens = sum(candidate.estimated_tokens_per_call for candidate in row_candidates)
    threshold_floor = max(
        (candidate.threshold_floor for candidate in row_candidates), default=get_min_cache_tokens(model)
    )
    if projected_tokens < threshold_floor:
        return cacheable_tokens, cacheable_source, ()
    if projected_tokens <= (cacheable_tokens or 0):
        return cacheable_tokens, cacheable_source, ()
    return (
        projected_tokens,
        "cross_workflow_projection",
        tuple(
            CrossWorkflowInputContribution(
                child_input_name=candidate.child_input_name,
                child_cache_ref=candidate.child_cache_ref,
                parent_value_expr=candidate.parent_value_expr,
                parent_cache_ref=candidate.parent_cache_ref,
                parent_prose=candidate.parent_prose or None,
                tokens_per_call=candidate.estimated_tokens_per_call,
                model=model,
            )
            for candidate in sorted(
                row_candidates,
                key=lambda c: (c.child_cache_ref, c.parent_node_id, c.parent_workflow, c.parent_cache_ref),
            )
        ),
    )


def _clamp_legacy_cacheable_projection(
    *,
    cacheable_tokens: int | None,
    cacheable_source: str,
    input_tokens: int,
    input_source: str,
    node_id: str,
    workflow_path: str | None,
    model: str,
) -> tuple[int | None, int | None]:
    """Return the legacy bridge token+ratio pair without leaking impossible totals."""
    if cacheable_tokens is None:
        return None, None
    if cacheable_tokens <= 0:
        return 0, 0
    if cacheable_tokens > input_tokens:
        logger.debug(
            "cacheable_tokens (%d, source=%s) exceeded input_tokens (%d, source=%s) "
            "for node=%s workflow=%s model=%s; clamping. Likely tokenizer drift "
            "between projection and prompt-resolution paths; see PerCallRow docstring.",
            cacheable_tokens,
            cacheable_source,
            input_tokens,
            input_source,
            node_id,
            workflow_path,
            model,
        )
    clamped = min(cacheable_tokens, input_tokens)
    return clamped, _safe_pct(clamped, input_tokens)


def _trace_cache_token_splits(provider_trace_llm_call: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if provider_trace_llm_call is None:
        return None, None
    return (
        int(provider_trace_llm_call.get("cache_creation_input_tokens") or 0),
        int(provider_trace_llm_call.get("cache_read_input_tokens") or 0),
    )


def _cross_workflow_projection_components(
    *,
    workflow_path: str | None,
    node_id: str,
    model: str,
    input_tokens: int,
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[_RowCrossWorkflowCandidate]] | None,
) -> tuple[tuple[CacheProjectionComponent, ...], tuple[CrossWorkflowInputContribution, ...]]:
    if cross_workflow_candidates_by_row is None:
        return (), ()
    row_candidates = cross_workflow_candidates_by_row.get((workflow_path, node_id), [])
    if not row_candidates:
        return (), ()
    projected_tokens = sum(candidate.estimated_tokens_per_call for candidate in row_candidates)
    min_tokens = get_min_cache_tokens(model)
    below_min = is_likely_below_min_cache(model, projected_tokens)
    component = _projection_component(
        tokens=projected_tokens,
        input_tokens=input_tokens,
        data_source="cross_workflow_projection",
        action="declare_child_cache",
        actionability="direct_edit_blocked" if below_min else "direct_edit",
        meets_provider_min=not below_min,
        provider_min_tokens=min_tokens,
        blocked_reason=_BLOCK_BELOW_PROVIDER_MIN if below_min else "",
        affects_cost_projection=False,
        diagnostic_ids=("cache.sub-workflow-cache-undeclared",) if not below_min else (),
    )
    contributions = tuple(
        CrossWorkflowInputContribution(
            child_input_name=candidate.child_input_name,
            child_cache_ref=candidate.child_cache_ref,
            parent_value_expr=candidate.parent_value_expr,
            parent_cache_ref=candidate.parent_cache_ref,
            parent_prose=candidate.parent_prose or None,
            tokens_per_call=candidate.estimated_tokens_per_call,
            model=model,
        )
        for candidate in sorted(
            row_candidates,
            key=lambda c: (c.child_cache_ref, c.parent_node_id, c.parent_workflow, c.parent_cache_ref),
        )
    )
    return (component,), contributions


def _node_has_images(node: Mapping[str, Any]) -> bool:
    params = node.get("params")
    if not isinstance(params, Mapping):
        return False
    images = params.get("images")
    if images is None:
        return False
    if isinstance(images, (list, tuple, set, dict, str)):
        return bool(images)
    return True


def _runtime_trace_blocker(calls: tuple[dict[str, Any], ...], *, kind: str) -> str:
    key = "prewarm_disabled_reason" if kind == "prewarm" else "cache_skipped_reason"
    reasons = {str(call.get(key)) for call in calls if call.get(key)}
    if "below_min" in reasons:
        return _BLOCK_BELOW_PROVIDER_MIN
    if reasons:
        return _BLOCK_RUNTIME_STRIPPED
    return ""


def _estimate_dynamic_tail_opportunity(
    *,
    node: dict[str, Any],
    row_model: str,
    prompt: str,
    observed_call_count: int,
    batch_size: int | None,
    declared_subset: list[str] | None,
    ctx: AnalysisContext,
) -> _PromptStaticTailFinding | None:
    if declared_subset:
        return None
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return None
    affected_calls = batch_size or observed_call_count
    if affected_calls < 2:
        return None
    alias = str(batch.get("as", "item"))
    finding = _find_batch_static_tail_after_dynamic(
        prompt=prompt,
        model=row_model,
        batch_alias=alias,
        node_inputs=_node_inputs(node),
        ctx=ctx,
        include_below_min=True,
    )
    if finding is None:
        return None
    return finding


def _detect_repeated_row_stable_refs(
    *,
    node: dict[str, Any],
    model: str,
    input_tokens: int,
    observed_call_count: int,
    batch_size: int | None,
    ctx: AnalysisContext,
) -> CacheProjectionComponent | None:
    if isinstance(node.get("batch"), dict):
        return None
    invocations = observed_call_count or batch_size or 1
    if invocations < 2:
        return None
    prompt = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt, str):
        return None
    refs = _extract_unique_refs(prompt)
    if not refs:
        return None
    total = 0
    for ref in refs:
        value = ctx.resolve_ref_value_for_projection(ref)
        if value is None:
            return None
        total += estimate_tokens(model, deterministic_serialize(value))[0]
    if total <= 0:
        return None
    meets_min, provider_min, blocked = _provider_min_state(model, total)
    return _projection_component(
        tokens=total,
        input_tokens=input_tokens,
        data_source="candidate_chunks",
        action="declare_prompt_cache",
        actionability="direct_edit_blocked" if blocked else "direct_edit",
        confidence="exact",
        meets_provider_min=meets_min,
        provider_min_tokens=provider_min,
        blocked_reason=blocked,
        affects_cost_projection=False,
        diagnostic_ids=("cache.shared-context-undeclared",) if not blocked else (),
    )


def _provider_trace_cached_now(provider_trace_llm_call: dict[str, Any] | None) -> int | None:
    creation, read = _trace_cache_token_splits(provider_trace_llm_call)
    if creation is None and read is None:
        return None
    return int(creation or 0) + int(read or 0)


def _declared_projection_component(
    *,
    model: str,
    input_tokens: int,
    declared_tokens: int | None,
    declared_source: str,
    provider_trace_llm_call: dict[str, Any] | None,
    provider_trace_llm_calls: tuple[dict[str, Any], ...],
) -> CacheProjectionComponent:
    meets_min, provider_min, blocked = _provider_min_state(model, declared_tokens)
    if declared_source == "trace" and declared_tokens is not None and declared_tokens > 0:
        meets_min = True
        blocked = ""
    chunks = provider_trace_llm_call.get("cache_chunks_skipped") if provider_trace_llm_call is not None else None
    if isinstance(chunks, list) and chunks:
        blocked = _BLOCK_ABSENT_BRANCH
    runtime_blocked = _runtime_trace_blocker(provider_trace_llm_calls, kind="declared")
    if runtime_blocked:
        blocked = runtime_blocked
    is_active = bool(declared_tokens is not None and declared_tokens > 0 and not blocked and meets_min is not False)
    # Pick the diagnostic ID that matches the evidence source: trace shows runtime
    # stripped → `cache.below-min-rendered`; static analyzer prediction →
    # `cache.below-min-predicted`. Mismatching the two leaves agents looking up
    # a diagnostic ID that isn't in `analysis.warnings`.
    below_min_id = (
        "cache.below-min-rendered" if runtime_blocked == _BLOCK_BELOW_PROVIDER_MIN else "cache.below-min-predicted"
    )
    return _projection_component(
        tokens=declared_tokens,
        input_tokens=input_tokens,
        data_source="declared_chunks" if declared_source != "trace" else "trace",
        action="none",
        actionability="active" if is_active else "configured_blocked",
        confidence=_projection_source_confidence(declared_source),
        meets_provider_min=meets_min,
        provider_min_tokens=provider_min,
        blocked_reason=blocked,
        affects_cost_projection=is_active,
        diagnostic_ids=() if is_active else (below_min_id,) if blocked == _BLOCK_BELOW_PROVIDER_MIN else (),
    )


def _configured_prewarm_projection_component(
    *,
    model: str,
    input_tokens: int,
    batch_prefix_tokens: int,
    has_images: bool,
    provider_trace_llm_calls: tuple[dict[str, Any], ...],
    declared_active_tokens: int = 0,
) -> CacheProjectionComponent:
    meets_min, provider_min, blocked = _provider_min_state(model, batch_prefix_tokens + declared_active_tokens)
    runtime_blocked = _runtime_trace_blocker(provider_trace_llm_calls, kind="prewarm")
    if runtime_blocked:
        blocked = runtime_blocked
        meets_min = False if runtime_blocked == _BLOCK_BELOW_PROVIDER_MIN else meets_min
    if has_images:
        blocked = _BLOCK_PREWARM_IMAGES
    is_active = bool(batch_prefix_tokens > 0 and not blocked and meets_min is not False)
    # Pick the diagnostic ID that matches the evidence source: trace shows runtime
    # pre-flight disabled the marker → `cache.prewarm-disabled-below-min`; static
    # analyzer prediction → `cache.batch-prewarm-below-min`. Mismatching the two
    # leaves agents looking up a diagnostic ID that isn't in `analysis.warnings`.
    below_min_id = (
        "cache.prewarm-disabled-below-min"
        if runtime_blocked == _BLOCK_BELOW_PROVIDER_MIN
        else "cache.batch-prewarm-below-min"
    )
    return _projection_component(
        tokens=batch_prefix_tokens,
        input_tokens=input_tokens,
        data_source="configured_prewarm",
        action="none",
        actionability="active" if is_active else "configured_blocked",
        confidence="exact",
        meets_provider_min=meets_min,
        provider_min_tokens=provider_min,
        blocked_reason=blocked,
        affects_cost_projection=is_active,
        diagnostic_ids=() if is_active else (below_min_id,) if blocked == _BLOCK_BELOW_PROVIDER_MIN else (),
    )


def _candidate_cache_projection_component(
    *,
    model: str,
    input_tokens: int,
    candidate_tokens: int | None,
    candidate_source: str,
) -> CacheProjectionComponent:
    meets_min, provider_min, blocked = _provider_min_state(model, candidate_tokens)
    return _projection_component(
        tokens=candidate_tokens,
        input_tokens=input_tokens,
        data_source="candidate_chunks" if candidate_source != "unavailable" else "unavailable",
        action="declare_prompt_cache",
        actionability="direct_edit_blocked" if blocked else "direct_edit",
        confidence=_projection_source_confidence(candidate_source),
        meets_provider_min=meets_min,
        provider_min_tokens=provider_min,
        blocked_reason=blocked,
        affects_cost_projection=False,
        diagnostic_ids=("cache.shared-context-undeclared",) if not blocked else (),
    )


def _prewarm_opportunity_projection_component(
    *,
    model: str,
    input_tokens: int,
    batch_prefix_tokens: int,
) -> CacheProjectionComponent:
    meets_min, provider_min, blocked = _provider_min_state(model, batch_prefix_tokens)
    return _projection_component(
        tokens=batch_prefix_tokens,
        input_tokens=input_tokens,
        data_source="batch_prefix",
        action="add_prewarm",
        actionability="direct_edit_blocked" if blocked else "direct_edit",
        confidence="exact",
        meets_provider_min=meets_min,
        provider_min_tokens=provider_min,
        blocked_reason=blocked,
        affects_cost_projection=False,
        diagnostic_ids=("cache.batch-prewarm-recommended",) if not blocked else (),
    )


def _dynamic_tail_projection_component(
    *,
    input_tokens: int,
    finding: _PromptStaticTailFinding,
) -> CacheProjectionComponent:
    blocked = finding.blocked_reason
    return _projection_component(
        tokens=finding.stable_tail_tokens,
        input_tokens=input_tokens,
        data_source="dynamic_before_static",
        action="move_dynamic_ref_after_stable_prefix",
        actionability="structural_edit_blocked" if blocked else "structural_edit",
        confidence="exact",
        meets_provider_min=finding.meets_provider_min,
        provider_min_tokens=finding.provider_min_tokens,
        blocked_reason=blocked,
        affects_cost_projection=False,
        diagnostic_ids=("cache.dynamic-before-static",) if not blocked else (),
    )


def _build_cache_projection_components(
    *,
    node: dict[str, Any],
    model: str,
    input_tokens: int,
    declared_subset: list[str] | None,
    candidate_subset: list[str] | None,
    declared_tokens: int | None,
    declared_source: str,
    candidate_tokens: int | None,
    candidate_source: str,
    batch_prefix_tokens: int | None,
    dynamic_tail_finding: _PromptStaticTailFinding | None,
    repeated_ref_component: CacheProjectionComponent | None,
    cross_workflow_components: tuple[CacheProjectionComponent, ...],
    provider_trace_llm_call: dict[str, Any] | None,
    provider_trace_llm_calls: tuple[dict[str, Any], ...],
) -> tuple[int | None, CacheProjection, CacheProjection, CacheProjection, CacheProjection]:
    configured: list[CacheProjectionComponent] = []
    active: list[CacheProjectionComponent] = []
    ready: list[CacheProjectionComponent] = []
    opportunity: list[CacheProjectionComponent] = []

    cached_now = _provider_trace_cached_now(provider_trace_llm_call)

    declared_active_tokens = 0
    if declared_subset:
        declared_component = _declared_projection_component(
            model=model,
            input_tokens=input_tokens,
            declared_tokens=declared_tokens,
            declared_source=declared_source,
            provider_trace_llm_call=provider_trace_llm_call,
            provider_trace_llm_calls=provider_trace_llm_calls,
        )
        configured.append(declared_component)
        ready.append(declared_component)
        if declared_component.affects_cost_projection:
            declared_active_tokens = declared_component.tokens_estimated or 0
            active.append(replace(declared_component, affects_cost_projection=True, actionability="active"))

    prewarm = node.get("prewarm")
    has_images = _node_has_images(node)
    if prewarm is True and batch_prefix_tokens is not None:
        prewarm_component = _configured_prewarm_projection_component(
            model=model,
            input_tokens=input_tokens,
            batch_prefix_tokens=batch_prefix_tokens,
            has_images=has_images,
            provider_trace_llm_calls=provider_trace_llm_calls,
            declared_active_tokens=declared_active_tokens,
        )
        configured.append(prewarm_component)
        ready.append(prewarm_component)
        if prewarm_component.affects_cost_projection:
            active.append(replace(prewarm_component, affects_cost_projection=True, actionability="active"))

    if not declared_subset and candidate_subset:
        candidate_component = _candidate_cache_projection_component(
            model=model,
            input_tokens=input_tokens,
            candidate_tokens=candidate_tokens,
            candidate_source=candidate_source,
        )
        ready.append(candidate_component)
        opportunity.append(candidate_component)

    if prewarm is None and batch_prefix_tokens is not None and not has_images:
        prewarm_opportunity = _prewarm_opportunity_projection_component(
            model=model,
            input_tokens=input_tokens,
            batch_prefix_tokens=batch_prefix_tokens,
        )
        ready.append(prewarm_opportunity)
        opportunity.append(prewarm_opportunity)

    ready.extend(cross_workflow_components)
    opportunity.extend(cross_workflow_components)

    if dynamic_tail_finding is not None:
        dynamic_component = _dynamic_tail_projection_component(
            input_tokens=input_tokens,
            finding=dynamic_tail_finding,
        )
        opportunity.append(dynamic_component)

    if repeated_ref_component is not None:
        ready.append(repeated_ref_component)
        opportunity.append(repeated_ref_component)

    return (
        cached_now,
        aggregate_projection(configured, purpose="configured", input_tokens=input_tokens),
        aggregate_projection(active, purpose="active", input_tokens=input_tokens),
        aggregate_projection(ready, purpose="ready", input_tokens=input_tokens),
        aggregate_projection(opportunity, purpose="opportunity", input_tokens=input_tokens),
    )


def _resolve_effective_row_model(explicit: Any, observed_models: tuple[str, ...]) -> tuple[str, bool]:
    """Return ``(model, model_is_heterogeneous)`` for one per-call row."""
    # Trace truth wins when present and unambiguous, because pricing,
    # tokenization, thresholds, and rendering all need the model that actually
    # ran. IR-declared heterogeneous models stay heterogeneous; trace-only
    # multi-observed rows remain unpriced and render as <varies> without
    # broadening model_is_heterogeneous semantics.
    model_is_heterogeneous = isinstance(explicit, str) and "${" in explicit
    if model_is_heterogeneous or len(observed_models) > 1:
        return "", model_is_heterogeneous
    if len(observed_models) == 1:
        return observed_models[0], model_is_heterogeneous
    if explicit:
        return str(explicit), model_is_heterogeneous
    return get_default_workflow_model() or "", model_is_heterogeneous


def _estimate_row_tokens(
    *,
    model: str,
    resolved_prompt: str,
    memo_cache: Any,
    node_id: str,
    workflow_path: str | None,
    has_unresolved: bool,
    trace_llm_call: dict[str, Any] | None,
    declared_subset: list[str] | None = None,
    ctx: AnalysisContext | None = None,
) -> tuple[int, int, str, int | None, str]:
    """Estimate input/output tokens for one workflow-scoped row.

    ``input_tokens`` is the LLM-billed total — prompt body PLUS cache content.
    Without that semantic, the cacheable-vs-input clamp at the call site
    would truncate correct cacheable estimates whenever ``## Cache`` chunks
    were referenced by name (``prompt_cache: [name]``) but not inlined in
    the prompt body. See Bug 4 in the verification report.

    Trace-tier accounting uses the same LiteLLM normalization rule as the
    runtime adapter. Older traces may contain either total-style
    ``input_tokens`` or split-style ``input_tokens``; provider metadata must
    not decide trace arithmetic because LiteLLM's behavior changed under us.
    """
    if trace_llm_call is not None and isinstance(trace_llm_call.get("input_tokens"), int):
        normalized_usage = normalize_litellm_usage_tokens(
            prompt_tokens=int(trace_llm_call["input_tokens"]),
            cache_creation_input_tokens=int(trace_llm_call.get("cache_creation_input_tokens") or 0),
            cache_read_input_tokens=int(trace_llm_call.get("cache_read_input_tokens") or 0),
        )
        input_tokens = normalized_usage.input_tokens
        if declared_subset and ctx is not None and model:
            chunk_tokens = min(
                _tokenize_declared_cache_chunks(
                    declared_subset=declared_subset,
                    workflow_ir=ctx.workflow_ir,
                    model=model,
                    memo_cache=memo_cache,
                    workflow_path=workflow_path,
                    ctx=ctx,
                ),
                input_tokens,
            )
        else:
            chunk_tokens = 0
        source = "trace"
    else:
        input_tokens, source = estimate_tokens(
            model,
            resolved_prompt,
            trace=None,
            memo_cache=memo_cache,
            node_id=node_id,
            workflow_path=workflow_path,
            has_unresolved_refs=has_unresolved,
            ctx=ctx,
        )
        chunk_tokens = 0
        if declared_subset and ctx is not None and model:
            chunk_tokens = _tokenize_declared_cache_chunks(
                declared_subset=declared_subset,
                workflow_ir=ctx.workflow_ir,
                model=model,
                memo_cache=memo_cache,
                workflow_path=workflow_path,
                ctx=ctx,
            )
            input_tokens += chunk_tokens
    if trace_llm_call is not None and isinstance(trace_llm_call.get("output_tokens"), int):
        output_tokens: int | None = int(trace_llm_call["output_tokens"])
        output_source = "trace"
    else:
        output_tokens, output_source = estimate_output_tokens(
            trace=None,
            memo_cache=memo_cache,
            node_id=node_id,
            workflow_path=workflow_path,
            ctx=ctx,
        )
    return input_tokens, chunk_tokens, source, output_tokens, output_source


def _tokenize_declared_cache_chunks(
    *,
    declared_subset: list[str],
    workflow_ir: Mapping[str, Any],
    model: str,
    memo_cache: Any,
    workflow_path: str | None,
    ctx: AnalysisContext,
) -> int:
    """Tokenize the resolved values of declared cache chunks.

    Returns the total token count for chunks that resolved against parameters
    or memo. Unresolvable chunks contribute 0 (matching the partial-resolution
    semantics callers already accept for the prompt body itself).
    """
    if not isinstance(workflow_ir, Mapping):
        return 0
    cache_block = workflow_ir.get("cache")
    if not isinstance(cache_block, dict):
        return 0
    items = cache_block.get("items") or []
    if not isinstance(items, list):
        return 0
    chunks_by_name: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        var_expr = item.get("var") or name
        if isinstance(name, str) and isinstance(var_expr, str) and var_expr:
            chunks_by_name[name] = var_expr
    total = 0
    for chunk_name in declared_subset:
        var_expr = chunks_by_name.get(str(chunk_name))
        if not var_expr:
            continue
        tokens = _estimate_ref_tokens(
            var_expr,
            model=model,
            memo_cache=memo_cache,
            workflow_path=workflow_path,
            ctx=ctx,
        )
        if tokens is not None:
            total += tokens
    return total


def _resolve_prompt_for_tokenization(prompt: str, ctx: AnalysisContext, node: dict[str, Any]) -> tuple[str, bool]:
    """Substitute ``${...}`` refs in ``prompt`` against parameters + memo.

    Returns ``(resolved_text, has_unresolved_refs)``. ``has_unresolved_refs``
    is True when at least one ``${...}`` remained unresolved after the
    substitution pass — caller passes this through to ``estimate_tokens``
    so the tier label can shift to ``"estimator-partial"``.

    Batch nodes: alias references (``${item.X}``) are inherently dynamic
    (resolved per item at run-time); they always remain unresolved here
    and trip ``has_unresolved_refs=True`` — correct, tokenization without
    a concrete batch item is necessarily approximate.
    """
    if not isinstance(prompt, str) or not prompt:
        return prompt or "", False

    refs = _extract_unique_refs(prompt)
    if not refs:
        return prompt, False

    shared = _build_shared_store_for_refs(refs, ctx)

    try:
        resolved = TemplateResolver.resolve_template(prompt, shared)
    except Exception:
        # Defensive: a malformed template shouldn't take down the analyzer.
        logger.debug("template resolution raised on prompt for node %r", node.get("id"), exc_info=True)
        return prompt, True

    if not isinstance(resolved, str):
        # Single-ref templates can return non-string values (e.g. dict).
        from pflow.core.prompt_cache import deterministic_serialize

        resolved = deterministic_serialize(resolved)

    has_unresolved = bool(TemplateResolver.TEMPLATE_PATTERN.search(resolved))
    return resolved, has_unresolved


def _node_inputs(node: dict[str, Any]) -> Mapping[str, Any] | None:
    """Return an LLM node's ``params.inputs`` mapping, if present."""
    params = node.get("params")
    if not isinstance(params, Mapping):
        return None
    inputs = params.get("inputs")
    return inputs if isinstance(inputs, Mapping) else None


def _per_node_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    declared_chunks: list[str],
    nodes_by_id: dict[str, dict[str, Any]],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit analytical-tier warnings for one LLM node.

    Full-path matching is load-bearing: cache chunk identifiers are
    ``creative-direction.response`` rather than root ids.

    ``nodes_by_id`` is the workflow-wide node lookup (id → node dict). Detectors
    that need to inspect upstream node types (e.g. ``cache.opaque-prompt``)
    consume it; detectors that only inspect the focal node ignore it.
    """
    diagnostics: list[Diagnostic] = []
    node_id = row.node_path

    if row.declared_prompt_cache:
        declared_component = next(
            (
                component
                for component in row.cache_configured.components
                if component.data_source in {"declared_chunks", "trace"}
            ),
            None,
        )
        finding = detect_below_min_tokens(
            BelowMinTokensEvidence(
                node_id=node_id,
                model=row.model,
                declared_prompt_cache=list(row.declared_prompt_cache),
                estimated_tokens=declared_component.tokens_estimated if declared_component else None,
                estimated_data_source=declared_component.data_source if declared_component else "unavailable",
            )
        )
        if finding is not None:
            diagnostics.append(
                make_diagnostic(
                    "cache.below-min-predicted",
                    node_id=finding.node_id,
                    affected_workflow=row.workflow_path,
                    model=finding.model,
                    min_tokens=finding.min_tokens,
                    cacheable_tokens=finding.cacheable_tokens,
                    provider_note=finding.provider_note,
                )
            )

    diagnostics.extend(_batch_prewarm_recommendations(node, row, ctx=ctx))
    diagnostics.extend(_dynamic_before_static_warnings(node, row, declared_chunks=declared_chunks, ctx=ctx))
    diagnostics.extend(_opaque_prompt_warnings(node, row, nodes_by_id=nodes_by_id))

    # Prewarm boundary classification MUST match the runtime gate at
    # ``nodes/llm/llm.py`` so analyzer and runtime agree on what counts as
    # batch-scoped, including refs indirected through ``params.inputs``.
    #
    # Two mutually-exclusive findings fire on the position of the first
    # per-item ref:
    #   * ``cache.prewarm-no-prefix`` — first == 0 (no static bytes before
    #     the per-item ref; nothing to cache).
    #   * ``cache.batch-prewarm-below-min`` — first > 0 but the bytes before
    #     it tokenize below the provider's minimum (auto batch-prefix marker
    #     will silently no-op at the provider). Gated on
    prewarm = node.get("prewarm")
    batch = node.get("batch")
    if prewarm is True and isinstance(batch, dict):
        alias = str(batch.get("as", "item"))
        prompt = node.get("params", {}).get("prompt", "") or ""
        # Per-call _strip_below_min_cache_markers is authoritative for combined channels.
        has_declared_cache = bool(node.get("prompt_cache"))
        if isinstance(prompt, str) and not has_declared_cache:
            node_inputs = _node_inputs(node)
            first = first_per_item_position(prompt, alias, node_inputs)
            if first == 0:
                diagnostics.append(
                    make_diagnostic(
                        "cache.prewarm-no-prefix",
                        node_id=node_id,
                        affected_workflow=row.workflow_path,
                        batch_alias=alias,
                        first_dynamic_position=0,
                    )
                )
            elif first is not None and first > 0:
                # Unresolved refs in the static prefix make below-min unprovable;
                # skip the static-analysis emit but fall through so the trace-driven
                # conditional-warmup detector below can still run.
                prefix_tokens = tokenize_prompt_region_for_projection(prompt[:first], model=row.model, ctx=ctx)
                if prefix_tokens is not None:
                    prewarm_diag = _emit_batch_prewarm_below_min(
                        node_id=node_id,
                        model=row.model,
                        prefix_tokens=prefix_tokens,
                        batch_alias=alias,
                        workflow_path=row.workflow_path,
                    )
                    if prewarm_diag is not None:
                        diagnostics.append(prewarm_diag)

        below_min_count = sum(
            1 for call in row.provider_trace_llm_calls if call.get("prewarm_disabled_reason") == "below_min"
        )
        total_count = len(row.provider_trace_llm_calls)
        if below_min_count >= 1 and below_min_count < total_count and total_count >= 2:
            diagnostics.append(
                make_diagnostic(
                    "cache.conditional-warmup-recommended",
                    node_id=node_id,
                    affected_workflow=row.workflow_path,
                    model=row.model,
                    below_min_count=below_min_count,
                    total_count=total_count,
                    min_tokens=get_min_cache_tokens(row.model),
                )
            )

    return diagnostics


def _emit_batch_prewarm_below_min(
    *,
    node_id: str,
    model: str,
    prefix_tokens: int,
    batch_alias: str,
    workflow_path: str | None,
) -> Diagnostic | None:
    """Shared producer for ``cache.batch-prewarm-below-min``.

    Routes three call sites through one helper so the convergence between
    per-call row UX and Recommended-Actions UX stays in lockstep:

    * ``_per_node_warnings``: declared ``prewarm: true`` with a measured
      static prefix below the provider minimum (original site).
    * ``_confident_batch_prewarm_recommendation``: undeclared prewarm where
      the analyzer has a measured prefix that is below min (F#4 — silenced
      previously by an early ``return []``).
    * ``_batch_prewarm_recommendations`` lower-bound branch: undeclared
      prewarm with unresolved refs; even the lower-bound measurable prefix
      is below min (F#4 — same silenced shape).

    Predicate stays ``is_below_min_cache`` via the detector — honest
    unmeasurable for empty/unknown model, matching Bundle 5 Option B scope.
    Returns ``None`` when the detector decides no finding applies (e.g.
    threshold met or unknown model); callers append only when non-None.

    ``workflow_path`` is typed ``str | None`` to mirror ``PerCallRow``'s
    field nullability; the catalog's ``_ensure_workflow_scope`` will reject
    None at construction (raising ``KeyError``), which is the desired
    contract — analyzer rows without a workflow_path shouldn't surface
    workflow-scoped diagnostics.
    """
    finding = detect_batch_prewarm_below_min(
        BatchPrewarmBelowMinEvidence(
            node_id=node_id,
            model=model,
            prefix_tokens=prefix_tokens,
            batch_alias=batch_alias,
        )
    )
    if finding is None:
        return None
    return make_diagnostic(
        "cache.batch-prewarm-below-min",
        node_id=finding.node_id,
        affected_workflow=workflow_path,
        model=finding.model,
        prefix_tokens=finding.prefix_tokens,
        min_tokens=finding.min_tokens,
        batch_alias=finding.batch_alias,
        provider_note=finding.provider_note,
    )


def _batch_prewarm_recommendations(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit ``cache.batch-prewarm-recommended`` per DD#33.

    ``prewarm: false`` is an explicit opt-out and suppresses this warning; only
    absence of the field means the author has not made a decision.

    When the analyzer can prove the would-be prefix is below the provider
    minimum (measurable or lower-bound), this function instead emits
    ``cache.batch-prewarm-below-min`` so the Recommended-Actions surface
    matches the per-call row's structural blocker (F#4 follow-ups-2).
    """
    batch = node.get("batch")
    if "prewarm" in node or not isinstance(batch, dict):
        return []
    affected_calls = row.batch_size_estimated or row.observed_call_count
    if affected_calls < 2:
        return []
    prompt = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt, str):
        return []

    alias = str(batch.get("as", "item"))
    uses_existing_prefix_evidence = False
    prefix_tokens: int | None = None
    dynamic_tokens: int | None = None
    # Reuse row-level batch-prefix evidence when available. Row token fields
    # are per-call by contract; cohort math happens only at explicit consumers.
    if row.observed_call_count >= 2 and row.cacheable_data_source == "batch_prefix" and row.cacheable_tokens_estimated:
        uses_existing_prefix_evidence = True
        prefix_tokens = row.cacheable_tokens_estimated
        dynamic_tokens = max(0, row.input_tokens_estimated - prefix_tokens)
    else:
        node_inputs = _node_inputs(node)
        first = first_per_item_position(prompt, alias, node_inputs)
        if first is None or first == 0:
            return []
        prefix_tokens = tokenize_prompt_region_for_projection(prompt[:first], model=row.model, ctx=ctx)
        dynamic_tokens = tokenize_prompt_region_for_projection(prompt[first:], model=row.model, ctx=ctx)
    if prefix_tokens is not None and dynamic_tokens is not None:
        return _confident_batch_prewarm_recommendation(
            row=row,
            affected_calls=affected_calls,
            prefix_tokens=prefix_tokens,
            dynamic_tokens=dynamic_tokens,
            alias=alias,
        )

    if prefix_tokens is None and not uses_existing_prefix_evidence:
        measurable_tokens, unresolved_refs = tokenize_prompt_region_lower_bound_for_projection(
            prompt[:first],
            model=row.model,
            ctx=ctx,
        )
        # F#4 (follow-ups-2): below-min on the lower-bound branch must surface
        # at the Recommended-Actions block so the agent sees the structural
        # blocker, not just the per-call row. Same convergence rationale as
        # the confident branch below.
        if is_below_min_cache(row.model, measurable_tokens):
            below_min_diag = _emit_batch_prewarm_below_min(
                node_id=row.node_path,
                model=row.model,
                prefix_tokens=measurable_tokens,
                batch_alias=alias,
                workflow_path=row.workflow_path,
            )
            return [below_min_diag] if below_min_diag is not None else []
        if not unresolved_refs:
            # No refs to verify with --report AND measurable cleared min — but
            # if there were no refs the confident branch above would have
            # taken this case. Defensive: nothing actionable to recommend.
            return []
        return [
            make_diagnostic(
                "cache.batch-prewarm-lower-bound-recommended",
                node_id=row.node_path,
                affected_workflow=row.workflow_path,
                measurable_tokens=measurable_tokens,
                batch_alias=alias,
                unresolved_refs=unresolved_refs,
                savings_lower_bound_usd=_estimate_token_savings_usd(
                    row.model,
                    measurable_tokens,
                    affected_calls - 1,
                ),
                batch_size=affected_calls,
            )
        ]

    return []


def _confident_batch_prewarm_recommendation(
    *,
    row: PerCallRow,
    affected_calls: int,
    prefix_tokens: int,
    dynamic_tokens: int,
    alias: str,
) -> list[Diagnostic]:
    # F#4 (follow-ups-2): converge with the per-call row UX. The row already
    # renders ``add prewarm; below provider min`` via
    # ``_prewarm_opportunity_projection_component`` (blocked_reason=
    # ``below_provider_min``). The Recommended-Actions block must also
    # surface the structural blocker so the agent can act on it without
    # cross-referencing the row table — emit ``cache.batch-prewarm-below-min``
    # in place of the previous silent ``return []``.
    if is_below_min_cache(row.model, prefix_tokens):
        below_min_diag = _emit_batch_prewarm_below_min(
            node_id=row.node_path,
            model=row.model,
            prefix_tokens=prefix_tokens,
            batch_alias=alias,
            workflow_path=row.workflow_path,
        )
        return [below_min_diag] if below_min_diag is not None else []

    savings_ratio = ((affected_calls - 1) * 1.15 * prefix_tokens) / (
        affected_calls * ((1.25 * prefix_tokens) + dynamic_tokens)
    )
    savings_pct = round(100 * savings_ratio)
    if savings_pct < 5:
        return []

    return [
        make_diagnostic(
            "cache.batch-prewarm-recommended",
            node_id=row.node_path,
            affected_workflow=row.workflow_path,
            batch_size=affected_calls,
            prefix_tokens_estimated=prefix_tokens,
            prefix_tokens_cohort_estimated=prefix_tokens * affected_calls,
            savings_pct=savings_pct,
            savings_usd=_estimate_token_savings_usd(row.model, prefix_tokens, affected_calls - 1),
        )
    ]


def _dynamic_before_static_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Detect a dynamic template reference before a large stable suffix."""
    prompt = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt, str):
        return []

    batch = node.get("batch")
    if not row.declared_prompt_cache and isinstance(batch, dict):
        affected_calls = row.batch_size_estimated or row.observed_call_count
        if affected_calls < 2:
            return []
        alias = str(batch.get("as", "item"))
        node_inputs = _node_inputs(node)
        finding = _find_batch_static_tail_after_dynamic(
            prompt=prompt,
            model=row.model,
            batch_alias=alias,
            node_inputs=node_inputs,
            ctx=ctx,
        )
        if finding is None:
            return []
        return [
            make_diagnostic(
                "cache.dynamic-before-static",
                node_id=row.node_path,
                affected_workflow=row.workflow_path,
                dynamic_ref=finding.dynamic_ref,
                dynamic_line=finding.dynamic_line,
                cacheable_tokens=finding.stable_tail_tokens,
                affected_calls=affected_calls,
                savings_usd=_estimate_token_savings_usd(row.model, finding.stable_tail_tokens, affected_calls),
                projected_ratio_pct=(
                    _safe_pct(
                        finding.stable_tail_tokens,
                        finding.stable_tail_tokens + finding.tokens_before_dynamic,
                    )
                    if finding.tokens_before_dynamic is not None
                    else None
                ),
                detection_mode="batch_static_tail",
                min_cache_tokens=get_min_cache_tokens(row.model),
                model=row.model,
                tokens_before_dynamic=finding.tokens_before_dynamic,
                template_refs_after_dynamic=finding.template_refs_after_dynamic,
                static_tail_excerpt=finding.static_tail_excerpt,
            )
        ]

    if not row.declared_prompt_cache or not declared_chunks:
        return []

    declared = set(declared_chunks)
    node_inputs = _node_inputs(node)
    refs = classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs)
    for index, ref in enumerate(refs):
        if any(path in declared for path in ref.operand_paths):
            continue

        cacheable_tokens = tokenize_prompt_region(prompt[ref.end :], model=row.model, ctx=ctx)
        if cacheable_tokens is None:
            continue
        if is_below_min_cache(row.model, cacheable_tokens):
            break

        affected_calls = invocation_count_for(row)
        tokens_before = tokenize_prompt_region(prompt[: ref.position], model=row.model, ctx=ctx)
        return [
            make_diagnostic(
                "cache.dynamic-before-static",
                node_id=row.node_path,
                affected_workflow=row.workflow_path,
                dynamic_ref=ref.raw_expr,
                dynamic_line=1 + prompt[: ref.position].count("\n"),
                cacheable_tokens=cacheable_tokens,
                affected_calls=affected_calls,
                savings_usd=_estimate_token_savings_usd(row.model, cacheable_tokens, affected_calls),
                projected_ratio_pct=(
                    _safe_pct(cacheable_tokens, cacheable_tokens + tokens_before) if tokens_before is not None else None
                ),
                detection_mode="declared_cache",
                min_cache_tokens=get_min_cache_tokens(row.model),
                model=row.model,
                tokens_before_dynamic=tokens_before,
                template_refs_after_dynamic=len(refs) - index - 1,
                static_tail_excerpt=_static_excerpt(prompt[ref.end :]),
            )
        ]
    return []


def _find_batch_static_tail_after_dynamic(
    *,
    prompt: str,
    model: str,
    batch_alias: str,
    node_inputs: Mapping[str, Any] | None = None,
    ctx: AnalysisContext,
    include_below_min: bool = False,
) -> _PromptStaticTailFinding | None:
    """Find a local-batch dynamic ref followed by enough literal stable text."""
    refs = list(classify_prompt_refs(prompt, batch_alias, node_inputs))
    for index, ref in enumerate(refs):
        if not ref.is_per_item:
            continue

        literal_tail = _literal_spans_after_template(prompt, refs, index)
        stable_tail_tokens = tokenize_prompt_region(literal_tail, model=model, ctx=ctx)
        # A "move stable content before the dynamic ref" recommendation has no
        # agent-actionable payoff when stable_tail_tokens is 0 — typical for
        # heterogeneous-batch prompts like ``prompt: ${item.prompt}`` where
        # nothing follows the per-item ref. Without this guard, the diagnostic
        # renders as "move 0 stable tokens" with "projected cache ratio after
        # fix: 0%" — internally contradictory advice.
        if stable_tail_tokens is None or stable_tail_tokens <= 0:
            return None
        meets_min, provider_min, blocked = _provider_min_state(model, stable_tail_tokens)
        if blocked and not include_below_min:
            return None
        tokens_before_dynamic = tokenize_prompt_region(prompt[: ref.position], model=model, ctx=ctx)
        return _PromptStaticTailFinding(
            dynamic_ref=ref.raw_expr,
            dynamic_line=1 + prompt[: ref.position].count("\n"),
            stable_tail_tokens=stable_tail_tokens,
            tokens_before_dynamic=tokens_before_dynamic,
            template_refs_after_dynamic=len(refs) - index - 1,
            static_tail_excerpt=_static_excerpt(literal_tail),
            meets_provider_min=meets_min,
            provider_min_tokens=provider_min,
            blocked_reason=blocked,
        )
    return None


def _literal_spans_after_template(
    prompt: str,
    refs: list[PromptRef],
    dynamic_match_index: int,
) -> str:
    spans: list[str] = []
    cursor = refs[dynamic_match_index].end
    for ref in refs[dynamic_match_index + 1 :]:
        spans.append(prompt[cursor : ref.position])
        cursor = ref.end
    spans.append(prompt[cursor:])
    return "".join(spans)


def _static_excerpt(text: str, *, limit: int = 120) -> str:
    excerpt = " ".join(text.split())
    if len(excerpt) <= limit:
        return excerpt
    return f"{excerpt[: limit - 1].rstrip()}..."


def _opaque_prompt_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    """Detect LLM nodes whose prompt is a single var-ref to a code-node output.

    Static walkers (``cache.dynamic-before-static``, ``cache.batch-prewarm-recommended``,
    ``cache.shared-context-undeclared``) read ``node.params.prompt`` as a literal
    template. When the prompt is just ``${X}`` and X resolves through a
    ``type: code`` node, those walkers see one ref and find nothing — even when
    the assembled prompt has substantial cache potential. This detector points
    the agent at the refactor.

    Two patterns trigger:
      - **Direct**: ``prompt: ${some_code.result.field}``.
      - **Through batch alias**: ``prompt: ${item.X}`` AND
        ``batch.items: ${some_code.result}``.

    Coalesce expressions (``${a ?? b}``) are skipped — they have multiple paths
    and the "opaque" framing doesn't fit cleanly.
    """
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt, str):
        return []
    stripped = prompt.strip()
    if not TemplateResolver.is_simple_template(stripped):
        return []

    inner = stripped[2:-1]
    if TemplateResolver.is_coalesce_expression(inner):
        return []
    root = TemplateResolver.extract_root_node_id(inner)

    upstream_node = nodes_by_id.get(root)
    if upstream_node is None:
        # Try one level of indirection through the batch alias.
        upstream_node = _resolve_through_batch_alias(node, root, nodes_by_id)

    if upstream_node is None or upstream_node.get("type") != "code":
        return []

    return [
        make_diagnostic(
            "cache.opaque-prompt",
            node_id=row.node_path,
            affected_workflow=row.workflow_path,
            var_ref=inner,
            upstream_node_id=str(upstream_node.get("id", "?")),
        )
    ]


def _resolve_through_batch_alias(
    node: dict[str, Any],
    root: str,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """If ``root`` is the node's batch alias, follow ``batch.items`` to its source node."""
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return None
    alias = str(batch.get("as", "item"))
    if root != alias:
        return None
    items_expr = batch.get("items", "")
    if not isinstance(items_expr, str):
        return None
    items_stripped = items_expr.strip()
    if not TemplateResolver.is_simple_template(items_stripped):
        return None
    items_inner = items_stripped[2:-1]
    if TemplateResolver.is_coalesce_expression(items_inner):
        return None
    items_root = TemplateResolver.extract_root_node_id(items_inner)
    return nodes_by_id.get(items_root)


def _estimate_batch_size(batch: dict[str, Any]) -> int | None:
    """Heuristic estimate of batch size from inline-static items list."""
    items = batch.get("items")
    if isinstance(items, list):
        return len(items)
    return None


def _estimate_batch_prefix_cacheable_tokens(
    *,
    node: dict[str, Any],
    model: str,
    prompt: str,
    declared_subset: list[str] | None,
    observed_call_count: int,
    ctx: AnalysisContext,
) -> int | None:
    """Estimate per-call cacheable prefix tokens before the first batch-item ref.

    Returns ``None`` for non-batch nodes or batches with fewer than 2 calls
    (no cache fan-out benefit). Declared cache and prewarm are independent
    runtime markers, so declared rows still need prefix evidence.
    """
    del declared_subset
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return None
    affected_call_count = observed_call_count or (_estimate_batch_size(batch) or 0)
    if affected_call_count < 2:
        return None
    alias = str(batch.get("as", "item"))
    node_inputs = _node_inputs(node)
    boundary = first_per_item_position(prompt, alias, node_inputs)
    if boundary is None or boundary == 0:
        return None
    prefix_tokens = tokenize_prompt_region_for_projection(prompt[:boundary], model=model, ctx=ctx)
    if prefix_tokens is None or prefix_tokens <= 0:
        return None
    return prefix_tokens


def _prefer_batch_prefix_cacheable_tokens(
    *,
    node: dict[str, Any],
    model: str,
    prompt: str,
    declared_subset: list[str] | None,
    observed_call_count: int,
    current_tokens: int | None,
    current_source: str,
    ctx: AnalysisContext,
) -> tuple[int | None, str]:
    prefix_tokens = _estimate_batch_prefix_cacheable_tokens(
        node=node,
        model=model,
        prompt=prompt,
        declared_subset=declared_subset,
        observed_call_count=observed_call_count,
        ctx=ctx,
    )
    if prefix_tokens is not None and prefix_tokens > (current_tokens or 0):
        # Distinct tier label: this is a static-prefix scan, not
        # chunk-resolution-via-CLI-parameters. Sharing the ``"parameters"``
        # label would violate the documented contract on
        # ``cacheable_data_source`` and mis-route the confidence footer's
        # "first batch item as a representative sample" message (no batch
        # item content participates in this projection).
        return prefix_tokens, "batch_prefix"
    return current_tokens, current_source


def _starter_prose_for_ref(ref: str) -> str:
    """Auto-generated humble label for a suggested cache chunk.

    Single-segment paths render as ``The X:`` (underscores → spaces).
    Dotted paths render as ``The Y from X:`` (Y = field, X = node).

    The agent should replace these with workflow-domain-specific prose
    before first run; the analyzer can't synthesize semantic descriptions
    because it doesn't know the workflow's domain. The starter form is
    byte-valid as-is so caching works on first run even without editing.
    """
    if "." in ref:
        node, _, tail = ref.partition(".")
        field = tail.replace("_", " ")
        return f"The {field} from {node}:"
    return f"The {ref.replace('_', ' ')}:"


def _populate_suggested_blocks(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
    notes: list[str],
) -> tuple[list[SuggestedBlock], list[Diagnostic]]:
    """Build greenfield suggested ``## Cache`` blocks + advisory.

    v1 covers greenfield only (per DD#3). When ``## Cache`` is already
    declared, append a note so agents understand why no suggestion was
    produced — silent return would otherwise hide the deferral.

    Per-node cacheable projection used to flow back via this pass; that
    responsibility now lives in ``estimate_cacheable_tokens`` (Tier 2 reads
    candidate subsets directly from the IR walker via
    ``_detect_candidate_subsets``).
    """
    if _skip_suggested_blocks_for_declared_cache(workflow_ir, notes):
        return [], []

    ref_to_nodes, first_seen = _collect_llm_template_references(workflow_ir)
    shared_refs = [(ref, nodes) for ref, nodes in ref_to_nodes.items() if len(nodes) >= 2]
    if not shared_refs:
        return [], []

    # Sort key has 5 dimensions (CP3 #4 fix — sibling clustering):
    #   1. Most-shared root first. Roots like ``concept`` (used by 7 nodes via
    #      various sub-paths) outrank singleton roots regardless of any
    #      individual sub-path's count.
    #   2. Root segment alphabetical — deterministic tie-break BETWEEN roots
    #      with equal popularity. Crucially, this also keeps ALL sub-paths of
    #      the same root contiguous in the output (siblings cluster).
    #   3. Within a root, most-shared sub-path first. ``concept.core_idea``
    #      (used by 7) outranks ``concept.angle`` (used by 4).
    #   4. First-seen-in-prompt-walk-order — preserves narrative order between
    #      otherwise-equivalent refs.
    #   5. Alphabetical — final deterministic tie-break.
    # Pre-fix the sort scattered ``concept.core_idea`` / ``concept.title`` /
    # ``concept.angle`` across positions 1, 2, 5 because they had different
    # share counts and got ranked individually. Lyrics-generator song-creator
    # rendered ``concept.angle`` between ``creative-direction.response`` and
    # ``song-architecture.response`` — broke narrative flow AND made the
    # generated ``prompt_cache:`` lists non-prefix-contiguous for nodes using
    # only some sub-paths.
    root_to_nodes: dict[str, set[str]] = {}
    for ref, nodes in shared_refs:
        root_to_nodes.setdefault(_template_root_segment(ref), set()).update(nodes)
    root_popularity = {root: len(node_set) for root, node_set in root_to_nodes.items()}

    shared_refs.sort(
        key=lambda item: (
            -root_popularity[_template_root_segment(item[0])],
            _template_root_segment(item[0]),
            -len(item[1]),
            first_seen[item[0]],
            item[0],
        )
    )
    chunks, assignments, ref_sizes, affected_nodes = _build_suggested_chunks_and_assignments(
        shared_refs=shared_refs,
        rows_by_node=rows_by_node,
        ctx=ctx,
    )
    total_savings: float | None = 0.0

    memo_cache = ctx.memo_cache
    workflow_path = ctx.workflow_path

    per_node_thresholds, eligible_nodes = _thresholds_for_assignments(
        assignments=assignments,
        rows_by_node=rows_by_node,
        ctx=ctx,
        memo_cache=memo_cache,
        workflow_path=workflow_path,
    )
    actionability_state = _classify_suggested_block_actionability(per_node_thresholds)
    if actionability_state == _SUGGESTED_BLOCK_BELOW_THRESHOLD:
        min_tokens_strictest = max(
            entry["min_tokens"] for entry in per_node_thresholds.values() if entry["min_tokens"] is not None
        )
        target_file = workflow_path or "<root>"
        conditional = make_diagnostic(
            "cache.shared-context-undeclared-conditional",
            node_id=None,
            node_count=len(affected_nodes),
            shared_chunks=[chunk.name for chunk in chunks],
            affected_workflow=target_file,
            min_tokens=min_tokens_strictest,
            affected_nodes=sorted(affected_nodes),
        )
        return [], [conditional]

    if actionability_state != _SUGGESTED_BLOCK_ACTIONABLE:
        note = _note_for_non_actionable_state(actionability_state)
        if note is not None:
            notes.append(note)
        return [], []

    for ref, node_ids in shared_refs:
        chunk_savings = _savings_for_shared_ref(ref, node_ids, rows_by_node, ref_sizes[ref], eligible_nodes)
        if chunk_savings is None:
            total_savings = None
        elif total_savings is not None:
            total_savings += chunk_savings

    target_file = workflow_path or "<root>"
    block = SuggestedBlock(
        target_file=target_file,
        ttl="5m",
        chunks=tuple(chunks),
        per_node_assignments={node_id: assignments[node_id] for node_id in sorted(assignments)},
        estimated_savings_usd=total_savings,
        prompt_body_cleanup=_compute_prompt_body_cleanup(workflow_ir, chunks, assignments),
        per_node_thresholds={node_id: per_node_thresholds[node_id] for node_id in sorted(per_node_thresholds)},
    )
    warning = make_diagnostic(
        "cache.shared-context-undeclared",
        node_id=None,
        node_count=len(affected_nodes),
        shared_chunks=[chunk.name for chunk in chunks],
        affected_workflow=target_file,
        savings_usd=total_savings,
    )
    return [block], [warning]


def _build_suggested_chunks_and_assignments(
    *,
    shared_refs: list[tuple[str, list[str]]],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
) -> tuple[list[SuggestedBlockChunk], dict[str, list[str]], dict[str, int | None], set[str]]:
    chunks: list[SuggestedBlockChunk] = []
    assignments: dict[str, list[str]] = {}
    ref_sizes: dict[str, int | None] = {}
    affected_nodes: set[str] = set()
    for ref, node_ids in shared_refs:
        first_row = rows_by_node.get(node_ids[0])
        model = first_row.model if first_row else ""
        size_tokens = _estimate_ref_tokens(
            ref,
            model=model,
            memo_cache=ctx.memo_cache,
            workflow_path=ctx.workflow_path,
            ctx=ctx,
        )
        ref_sizes[ref] = size_tokens
        chunks.append(
            SuggestedBlockChunk(
                name=ref,
                var=f"${{{ref}}}",
                size_tokens_est=size_tokens if size_tokens is not None else 0,
                prose_placeholder=_starter_prose_for_ref(ref),
            )
        )
        for node_id in node_ids:
            affected_nodes.add(node_id)
            assignments.setdefault(node_id, []).append(ref)
    return chunks, assignments, ref_sizes, affected_nodes


def _skip_suggested_blocks_for_declared_cache(workflow_ir: dict[str, Any], notes: list[str]) -> bool:
    # The previous "Suggested-blocks: workflow already declares ## Cache;
    # steady-state (partial-block) suggestions deferred to v1.x." Note was
    # internal-jargon roadmap leak ("Suggested-blocks", "partial-block",
    # "v1.x"). Workflows with a declared ## Cache simply don't get block
    # suggestions; that's neutral state, not actionable signal. Silence
    # over noise.
    del notes  # Reserved for future agent-facing signal at this gate.
    return bool(_cache_item_names(workflow_ir))


def _classify_suggested_block_actionability(
    per_node_thresholds: Mapping[str, PerNodeThresholdEntry],
) -> str:
    """Classify the suggested-block state for dispatch.

    The caller emits the confident ``cache.shared-context-undeclared`` only for
    actionable blocks, emits a conditional advisory for known-below-threshold
    blocks, and leaves only plain notes for incomplete evidence or too few
    reusable nodes.
    """
    if len(per_node_thresholds) < 2:
        return _SUGGESTED_BLOCK_INSUFFICIENT_NODES
    statuses = [entry["meets_threshold"] for entry in per_node_thresholds.values()]
    if any(status is None for status in statuses):
        return _SUGGESTED_BLOCK_EVIDENCE_INCOMPLETE
    if any(status is False for status in statuses):
        return _SUGGESTED_BLOCK_BELOW_THRESHOLD
    return _SUGGESTED_BLOCK_ACTIONABLE


def _note_for_non_actionable_state(state: str) -> str | None:
    """Plain-English note text for states without a structured advisory."""
    if state == _SUGGESTED_BLOCK_INSUFFICIENT_NODES:
        return (
            "Suggested-blocks: shared refs were found, but fewer than two LLM nodes can "
            "reuse the provider cache; no cache edit will fire at the provider yet."
        )
    if state == _SUGGESTED_BLOCK_EVIDENCE_INCOMPLETE:
        return (
            "Suggested-blocks: shared refs were found, but the analyzer cannot yet tell "
            "whether a cache edit would fire (set settings.default_model or run the "
            "workflow once, then re-run analyze-cache)."
        )
    return None


def _thresholds_for_assignments(
    *,
    assignments: dict[str, list[str]],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
    memo_cache: Any,
    workflow_path: str | None,
) -> tuple[dict[str, PerNodeThresholdEntry], set[str]]:
    per_node_thresholds: dict[str, PerNodeThresholdEntry] = {}
    eligible_nodes: set[str] = set()
    for node_id, assigned_refs in assignments.items():
        entry = _threshold_entry_for_node(
            node_id=node_id,
            assigned_refs=assigned_refs,
            rows_by_node=rows_by_node,
            ctx=ctx,
            memo_cache=memo_cache,
            workflow_path=workflow_path,
        )
        per_node_thresholds[node_id] = entry
        if entry["meets_threshold"] is True:
            eligible_nodes.add(node_id)
    return per_node_thresholds, eligible_nodes


def _threshold_entry_for_node(
    *,
    node_id: str,
    assigned_refs: list[str],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
    memo_cache: Any,
    workflow_path: str | None,
) -> PerNodeThresholdEntry:
    node_row = rows_by_node.get(node_id)
    if node_row is None:
        return {
            "model": None,
            "model_state": "unknown",
            "min_tokens": None,
            "total_tokens": None,
            "meets_threshold": None,
        }
    if node_row.model_is_heterogeneous:
        return {
            "model": None,
            "model_state": "heterogeneous",
            "min_tokens": None,
            "total_tokens": None,
            "meets_threshold": None,
        }
    if not node_row.model:
        return {
            "model": None,
            "model_state": "unknown",
            "min_tokens": None,
            "total_tokens": None,
            "meets_threshold": None,
        }

    total = _sum_chunk_tokens(assigned_refs, node_row.model, ctx, memo_cache, workflow_path)
    threshold = get_min_cache_tokens(node_row.model)
    return {
        "model": node_row.model,
        "model_state": "resolved",
        "min_tokens": threshold,
        "total_tokens": total,
        "meets_threshold": (total >= threshold) if total is not None else None,
    }


def _collect_llm_template_references(workflow_ir: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Return ``template_ref -> node_ids`` for LLM prompt references."""
    ref_to_nodes: dict[str, list[str]] = {}
    first_seen: dict[str, int] = {}
    for node_idx, node in enumerate(workflow_ir.get("nodes", []) or []):
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        prompt = node.get("params", {}).get("prompt", "")
        if not isinstance(prompt, str):
            continue
        batch_aliases = _batch_aliases(node)
        seen_in_node: set[str] = set()
        node_inputs = _node_inputs(node)
        for classified_ref in classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs):
            for ref in classified_ref.operand_paths:
                if _is_batch_scoped_ref(ref, batch_aliases) or ref in seen_in_node:
                    continue
                seen_in_node.add(ref)
                ref_to_nodes.setdefault(ref, []).append(str(node["id"]))
                first_seen.setdefault(ref, node_idx)
    return ref_to_nodes, first_seen


def _collect_llm_template_root_references(
    workflow_ir: dict[str, Any],
    var_to_name: dict[str, str],
) -> dict[str, list[str]]:
    """Return ``cache_item_name -> node_ids`` for LLM prompt references.

    Sibling of ``_collect_llm_template_references``: the existing helper
    preserves literal refs for token pricing; this helper buckets by the cache
    item whose ``var`` is the longest prefix of each operand. Batch-scoped refs
    are filtered to match validator overlap behavior.
    """
    refs_by_name: dict[str, list[str]] = {}
    vars_ = tuple(var_to_name.keys())
    for node in workflow_ir.get("nodes", []) or []:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        node_id = node.get("id")
        prompt = node.get("params", {}).get("prompt", "")
        if not node_id or not isinstance(prompt, str):
            continue
        batch_aliases = _batch_aliases(node)
        seen_names: set[str] = set()
        node_inputs = _node_inputs(node)
        for ref in classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs):
            for operand in ref.operand_paths:
                if _is_batch_scoped_ref(operand, batch_aliases):
                    continue
                matched_var = _longest_var_prefix_match(operand, vars_)
                if matched_var is None:
                    continue
                name = var_to_name[matched_var]
                if name in seen_names:
                    continue
                seen_names.add(name)
                refs_by_name.setdefault(name, []).append(str(node_id))
    return refs_by_name


def _longest_var_prefix_match(operand: str, vars_: Iterable[str]) -> str | None:
    """Return the longest cache var matching ``operand`` by root/sub-path prefix."""
    if not operand:
        return None
    best: str | None = None
    for var in vars_:
        if not isinstance(var, str) or not var:
            continue
        if (operand == var or operand.startswith(f"{var}.") or operand.startswith(f"{var}[")) and (
            best is None or len(var) > len(best)
        ):
            best = var
    return best


def _template_root_segment(ref: str) -> str:
    """Return the first segment of a template path.

    Examples:
        ``concept.core_idea`` → ``concept``
        ``concept`` → ``concept``
        ``items[0].name`` → ``items``
        ``creative-direction.response`` → ``creative-direction``

    Used by:
    - the ``_populate_suggested_blocks`` sort key (CP3 #4 — sibling clustering),
    - the ``_consolidate_to_root_advisories`` detector (CP3 #3 — sub-path
      clusters that fall below the provider's min-cache threshold).
    """
    return ref.split(".", 1)[0].split("[", 1)[0]


def _consolidate_to_root_advisories(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit ``cache.consolidate-to-root-recommended`` advisories.

    Fires when sub-paths of a parent dict (e.g. ``concept.core_idea``,
    ``concept.title``) are individually below the provider's min-cache token
    threshold AND consolidating to ``${root}`` would cross the threshold.
    The pre-fix sub-path declarations cache_control markers silently no-op
    at the provider; the agent thinks they're caching but they aren't.

    Greenfield path (no ``## Cache`` declared): audits shared template
    references. Only fires when memo data is available — without it,
    ``_estimate_ref_tokens`` falls back to tokenizing the literal
    ``${concept}`` string (~3 tokens), making the threshold check naturally
    suppress the advisory for pure-greenfield workflows. After the first
    run, memo data populates and the advisory becomes meaningful.

    Brownfield path (``## Cache`` declared with sub-path chunks): audits the
    declared chunks directly. The user has explicitly chosen these chunks;
    the advisory tells them why caching isn't actually firing.
    """
    candidates = _collect_consolidate_candidates(workflow_ir, declared_chunks)
    if not candidates:
        return []
    candidate_set = set(candidates)
    by_root = _group_subpaths_by_root(candidates)
    if not by_root:
        return []

    rows = list(rows_by_node.values())
    resolved_models = tuple(row.model for row in rows if row.model)
    representative_model = max(
        resolved_models,
        key=get_min_cache_tokens,
        default="",
    )
    if not representative_model:
        return []
    min_tokens = get_min_cache_tokens(representative_model)

    diagnostics: list[Diagnostic] = []
    for root, sub_paths in sorted(by_root.items()):
        diag = _check_root_for_consolidation(
            root=root,
            sub_paths=sub_paths,
            candidate_set=candidate_set,
            model=representative_model,
            min_tokens=min_tokens,
            ctx=ctx,
        )
        if diag is not None:
            diagnostics.append(diag)
    return diagnostics


def _collect_consolidate_candidates(workflow_ir: dict[str, Any], declared_chunks: list[str]) -> list[str]:
    """Pick the chunk set the consolidate-advisory should examine."""
    if declared_chunks:
        # Brownfield — agent has explicitly declared these chunks.
        return list(set(declared_chunks))
    # Greenfield — shared template references (≥2 LLM nodes).
    ref_to_nodes, _ = _collect_llm_template_references(workflow_ir)
    return [ref for ref, node_ids in ref_to_nodes.items() if len(node_ids) >= 2]


def _group_subpaths_by_root(candidates: list[str]) -> dict[str, list[str]]:
    """Group sub-paths by their root segment.

    Root form chunks (``concept`` itself, where root == ref) are excluded:
    they ARE the root, not candidates for consolidation. Only genuine
    sub-paths (``concept.title``) get grouped.
    """
    by_root: dict[str, list[str]] = {}
    for ref in candidates:
        root = _template_root_segment(ref)
        if root != ref:
            by_root.setdefault(root, []).append(ref)
    return by_root


def _check_root_for_consolidation(
    *,
    root: str,
    sub_paths: list[str],
    candidate_set: set[str],
    model: str,
    min_tokens: int,
    ctx: AnalysisContext,
) -> Diagnostic | None:
    """Run the threshold check for one root group.

    Returns a Diagnostic when consolidation would cross the threshold; None
    when any of the suppression rules fires:
      - <2 sub-paths (no consolidation case)
      - root already declared/used (redundancy, not consolidation)
      - some sub-path already crosses threshold (caching already works)
      - root itself wouldn't cross threshold (cache.below-min-predicted covers it)
    """
    if len(sub_paths) < 2:
        return None
    if root in candidate_set:
        # Root already declared/used directly — sub-paths are a redundancy
        # issue, not a consolidation case. The right fix is "remove the
        # redundant sub-path entries", not "consolidate to root".
        return None
    memo_cache = ctx.memo_cache
    workflow_path = ctx.workflow_path
    sub_path_tokens = [
        _estimate_ref_tokens(sp, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
        for sp in sub_paths
    ]
    # Pre-Option-C this advisory relied on ``_estimate_ref_tokens`` returning
    # ~3-5 tokens (literal ``${ref}``) on memo miss — implicit suppression via
    # "small number trickles past threshold". Now ``_estimate_ref_tokens``
    # returns ``None`` on memo miss; explicit check needed. The advisory's
    # whole premise (compare sub-path tokens vs root tokens vs threshold) is
    # only meaningful with real value sizes. Any None → skip.
    if any(t is None for t in sub_path_tokens):
        return None
    max_subpath = max(t for t in sub_path_tokens if t is not None)
    if max_subpath >= min_tokens:
        # At least one sub-path is large enough to cache on its own;
        # cache_control on the largest sub-path already fires.
        return None
    root_tokens = _estimate_ref_tokens(root, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
    if root_tokens is None or root_tokens < min_tokens:
        # Either no run data for the root (unmeasurable) or even consolidation
        # wouldn't cross the threshold (``cache.below-min-predicted`` covers
        # the latter case for declared subsets).
        return None
    return make_diagnostic(
        "cache.consolidate-to-root-recommended",
        node_id=None,
        root=root,
        sub_paths=sorted(sub_paths),
        model=model,
        min_tokens=min_tokens,
        max_subpath_tokens=max_subpath,
        root_tokens=root_tokens,
        affected_workflow=workflow_path,
    )


def _detect_cache_fragmentation_by(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
    key_fn: Callable[[PerCallRow, dict[str, Any]], str | None],
    warning_id: str,
    representative_model_fn: Callable[[dict[str, Any]], str | None],
    context_builder_fn: Callable[[list[dict[str, Any]], dict[str, float]], dict[str, Any]],
) -> list[Diagnostic]:
    """Emit one workflow-scoped warning for cache-prefix fragmentation.

    This is the shared engine for warnings whose invariant is "shared cache
    chunks are declared across groups that cannot share provider cache prefix
    bytes." Callers supply the grouping key, the representative model used for
    pricing each group, and the warning-specific diagnostic context.
    """
    if not declared_chunks:
        return []

    rows_with_keys = _fragmentation_rows_with_keys(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        key_fn=key_fn,
    )
    if not rows_with_keys:
        return []

    groups = _group_rows_by_fragmentation_key(rows_with_keys)
    fragmented_groups = [group for group in groups.values() if _chunks_shared_with_other_group(group, groups.values())]
    if len(fragmented_groups) < 2:
        return []

    sorted_groups = sorted(
        fragmented_groups,
        key=lambda group: (-len(group["rows"]), str(group["key"] or "")),
    )
    shared_chunks = _chunks_shared_across_groups(sorted_groups)
    costs = _compute_fragmentation_costs(
        sorted_groups,
        shared_chunks,
        ttl=_extract_cache_ttl(workflow_ir.get("cache")),
        ctx=ctx,
        representative_model_fn=representative_model_fn,
    )
    if costs is None:
        return []

    participating_groups = [group for group in sorted_groups if str(group["key"] or "") in costs]
    if len(participating_groups) < 2:
        return []

    redundant_groups = participating_groups[1:]
    savings_usd = sum(costs[str(group["key"] or "")] for group in redundant_groups)
    extra_context = context_builder_fn(participating_groups, costs)
    return [
        make_diagnostic(
            warning_id,
            node_id=None,
            shared_chunks=sorted(shared_chunks),
            affected_workflow=ctx.workflow_path,
            savings_usd=savings_usd,
            **extra_context,
        )
    ]


def _fragmentation_rows_with_keys(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    key_fn: Callable[[PerCallRow, dict[str, Any]], str | None],
) -> list[tuple[PerCallRow, str | None]]:
    node_by_id = {str(n.get("id")): n for n in workflow_ir.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    rows_with_keys: list[tuple[PerCallRow, str | None]] = []
    for row in rows_by_node.values():
        if not row.declared_prompt_cache:
            continue
        if not row.model:
            continue
        if row.model_is_heterogeneous or row.did_not_execute_in_trace:
            continue
        node = node_by_id.get(row.node_path)
        if node is None:
            continue
        rows_with_keys.append((row, key_fn(row, node)))
    return rows_with_keys


def _group_rows_by_fragmentation_key(
    rows_with_keys: list[tuple[PerCallRow, str | None]],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row, key in rows_with_keys:
        bucket_key = key or ""
        group = groups.setdefault(bucket_key, {"key": key, "rows": [], "chunks": set()})
        group["rows"].append(row)
        group["chunks"].update(str(chunk) for chunk in row.declared_prompt_cache or ())
    return groups


def _detect_model_cache_fragmentation(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit model-fragmentation and write-penalty diagnostics.

    The fragmentation warning delegates to ``_detect_cache_fragmentation_by``.
    The write-penalty advisory stays here because it is model-specific: one
    exact-model group with one cache-declaring call pays a write premium that
    cannot amortize in the current workflow. Sibling fragmentation detector:
    ``_detect_system_cache_fragmentation``.
    """
    rows = [
        row
        for row in rows_by_node.values()
        if row.declared_prompt_cache
        and row.model
        and not row.model_is_heterogeneous
        and not row.did_not_execute_in_trace
    ]
    node_by_id = {str(n.get("id")): n for n in workflow_ir.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    diagnostics = _detect_cache_fragmentation_by(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
        key_fn=lambda row, node: normalize_model_name(row.model),
        warning_id="cache.heterogeneous-models-fragment-cache",
        representative_model_fn=lambda group: str(group["key"]) if group["key"] else None,
        context_builder_fn=_build_model_fragmentation_context,
    )

    groups = _group_prompt_cache_rows_by_model(rows)
    for group in sorted(groups.values(), key=lambda item: str(item["model"])):
        group_rows = group["rows"]
        if len(group_rows) != 1:
            continue
        row = group_rows[0]
        node = node_by_id.get(row.node_path)
        if isinstance(node, dict) and node.get("prewarm") is True:
            continue
        model = str(group["model"])
        if model.startswith("gemini/"):
            continue
        penalty = _single_call_write_penalty(row, ttl=_extract_cache_ttl(workflow_ir.get("cache")))
        if penalty is None:
            continue
        diagnostics.append(
            make_diagnostic(
                "cache.first-call-write-penalty",
                node_id=row.node_path,
                model=model,
                affected_workflow=ctx.workflow_path,
                savings_usd=penalty,
            )
        )

    return diagnostics


def _detect_system_cache_fragmentation(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit system-prompt cache-prefix fragmentation diagnostics.

    Provider cache prefixes include the rendered ``system:`` content before the
    first cache marker. LLM nodes that share ``prompt_cache:`` chunks but use
    distinct ``system:`` strings therefore create distinct provider cache
    namespaces even when model and chunks match. Sibling fragmentation detector:
    ``_detect_model_cache_fragmentation``.
    """
    return _detect_cache_fragmentation_by(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        declared_chunks=declared_chunks,
        ctx=ctx,
        key_fn=_system_fragmentation_key,
        warning_id="cache.system-prompts-fragment-cache",
        representative_model_fn=_homogeneous_model_for_system_group,
        context_builder_fn=_build_system_fragmentation_context,
    )


def _system_fragmentation_key(_row: PerCallRow, node: dict[str, Any]) -> str | None:
    """Return the LLM node's ``system:`` value for cache-prefix grouping."""
    system_value = node.get("params", {}).get("system")
    if not isinstance(system_value, str) or not system_value:
        return None
    return system_value


def _homogeneous_model_for_system_group(group: dict[str, Any]) -> str | None:
    """Return the group's single model, or None when models are mixed."""
    models: set[str] = {str(row.model) for row in group["rows"] if row.model}
    if len(models) != 1:
        return None
    return next(iter(models))


def _build_model_fragmentation_context(
    participating_groups: list[dict[str, Any]],
    costs: dict[str, float],
) -> dict[str, Any]:
    model_groups = _model_groups_payload(participating_groups, costs)
    return {
        "model_group_count": len(participating_groups),
        "models_csv": ", ".join(str(group["key"]) for group in participating_groups),
        "model_groups": model_groups,
        "model_groups_lines": _format_model_groups_lines(model_groups),
    }


def _build_system_fragmentation_context(
    participating_groups: list[dict[str, Any]],
    costs: dict[str, float],
) -> dict[str, Any]:
    payload = _system_groups_payload(participating_groups, costs)
    node_ids_csv = ", ".join(sorted({row.node_path for group in participating_groups for row in group["rows"]}))
    return {
        "system_group_count": len(participating_groups),
        "system_groups": payload,
        "system_groups_lines": _format_system_groups_lines(payload),
        "node_ids_csv": node_ids_csv,
    }


def _group_prompt_cache_rows_by_model(rows: list[PerCallRow]) -> dict[str, dict[str, Any]]:
    """Group rows for the model-specific write-penalty loop.

    This legacy helper emits ``{"model", "rows", "chunks"}``; the generalized
    fragmentation helper emits ``{"key", "rows", "chunks"}``.
    """
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        model = normalize_model_name(row.model)
        group = groups.setdefault(model, {"model": model, "rows": [], "chunks": set()})
        group["rows"].append(row)
        group["chunks"].update(str(chunk) for chunk in row.declared_prompt_cache or ())
    return groups


def _chunks_shared_with_other_group(group: dict[str, Any], all_groups: Iterable[dict[str, Any]]) -> set[str]:
    chunks = set(group["chunks"])
    shared: set[str] = set()
    for other in all_groups:
        if other is group:
            continue
        shared.update(chunks & set(other["chunks"]))
    return shared


def _chunks_shared_across_groups(groups: list[dict[str, Any]]) -> set[str]:
    shared: set[str] = set()
    for group in groups:
        shared.update(_chunks_shared_with_other_group(group, iter(groups)))
    return shared


def _compute_fragmentation_costs(
    groups: list[dict[str, Any]],
    shared_chunks: set[str],
    *,
    ttl: str | None,
    ctx: AnalysisContext,
    representative_model_fn: Callable[[dict[str, Any]], str | None],
) -> dict[str, float] | None:
    """Sum each group's redundant cache_creation cost over the shared chunks.

    Honest-unmeasurable: returns ``None`` if any group lacks pricing OR any
    shared chunk has no resolvable token estimate (memo miss in greenfield).
    Mirrors ``_check_root_for_consolidation``'s "any None → skip" pattern so
    the warning never fabricates dollars when chunk-level data is unavailable.
    """
    from .cost_estimation import _write_rate_for_ttl, get_model_pricing

    costs: dict[str, float] = {}
    for group in groups:
        model = representative_model_fn(group)
        if model is None:
            return None
        pricing = get_model_pricing(model)
        if pricing is None:
            return None
        group_shared = group["chunks"] & shared_chunks
        total_tokens = _sum_chunk_tokens(list(group_shared), model, ctx, ctx.memo_cache, ctx.workflow_path)
        if total_tokens is None:
            return None
        if is_likely_below_min_cache(model, total_tokens):
            continue
        costs[str(group["key"] or "")] = total_tokens * _write_rate_for_ttl(pricing, ttl, model)
    return costs


def _model_groups_payload(groups: list[dict[str, Any]], costs: dict[str, float]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for group in groups:
        rows = sorted(group["rows"], key=lambda row: row.node_path)
        model = str(group["key"])
        payload.append({
            "model": model,
            "node_paths": [row.node_path for row in rows],
            "node_count": len(rows),
            "cache_creation_cost_usd": costs[model],
        })
    return payload


def _format_model_groups_lines(groups: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for group in groups:
        node_paths = ", ".join(str(path) for path in group["node_paths"])
        noun = "node" if group["node_count"] == 1 else "nodes"
        lines.append(f"  - {group['model']} ({group['node_count']} {noun}): {node_paths}")
    return "\n".join(lines)


def _system_groups_payload(groups: list[dict[str, Any]], costs: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {
            "system_preview": _preview_system(group["key"]),
            "node_ids": sorted(row.node_path for row in group["rows"]),
            "redundant_write_usd": costs[str(group["key"] or "")],
        }
        for group in groups
    ]


def _preview_system(system: str | None) -> str:
    if not system:
        return "(no system)"
    text = system.replace("\n", " ⏎ ")
    return text if len(text) <= 80 else text[:77] + "..."


def _format_system_groups_lines(groups: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for group in groups:
        node_ids = ", ".join(str(node_id) for node_id in group["node_ids"])
        lines.append(f"  - `{group['system_preview']}` -> {len(group['node_ids'])} node(s): {node_ids}")
    return "\n".join(lines)


def _single_call_write_penalty(row: PerCallRow, *, ttl: str | None) -> float | None:
    """Return the savings (write premium - input cost) from removing the cache declaration.

    ``None`` when pricing or token data is unavailable (honest-unmeasurable).
    Positive value = removing the declaration saves money. Mirrors the catalog's
    ``savings_usd`` semantics ("savings from fixing it").
    """
    from .cost_estimation import _write_rate_for_ttl, get_model_pricing

    tokens = row.cacheable_tokens_estimated
    if tokens is None:
        return None
    if is_likely_below_min_cache(row.model, tokens):
        return None
    pricing = get_model_pricing(row.model)
    if pricing is None:
        return None
    input_rate = _input_rate(row.model)
    if input_rate is None:
        return None
    return tokens * _write_rate_for_ttl(pricing, ttl, row.model) - tokens * input_rate


def _batch_aliases(node: dict[str, Any]) -> set[str]:
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return set()
    return {str(batch.get("as", "item"))}


def _compute_prompt_body_cleanup(
    workflow_ir: dict[str, Any],
    chunks: list[SuggestedBlockChunk],
    assignments: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Per-node prompt-body cleanup hint for greenfield SuggestedBlock.

    For each node being assigned cached chunks, lists the inline ``${...}``
    references that would overlap and need to be removed from the prompt
    body so agents following the analyzer's recommendation don't silently
    keep the inline refs and cancel out the cache savings.

    Returns ``{node_id: sorted unique body refs}``. Nodes without overlap
    don't appear in the dict.
    """
    from pflow.core.cache_overlap import compute_overlaps

    nodes_by_id_local = {n["id"]: n for n in workflow_ir.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    chunk_name_set = {chunk.name for chunk in chunks}
    cleanup: dict[str, list[str]] = {}
    for node_id, assigned_chunk_names in assignments.items():
        node = nodes_by_id_local.get(node_id)
        if node is None:
            continue
        prompt_text = node.get("params", {}).get("prompt", "") or ""
        if not isinstance(prompt_text, str):
            continue
        overlaps = compute_overlaps(
            prompt_text=prompt_text,
            prompt_cache=assigned_chunk_names,
            cache_item_names=chunk_name_set,
            batch_aliases=_batch_aliases(node),
        )
        if overlaps:
            cleanup[node_id] = sorted({o.body_ref for o in overlaps})
    return cleanup


def _prompt_body_cleanup_for_node(
    node: dict[str, Any],
    corrected_prompt_cache: tuple[str, ...],
    cache_item_names: set[str],
) -> tuple[str, ...]:
    """Return prompt-body refs that overlap the corrected cache declaration."""
    from pflow.core.cache_overlap import compute_overlaps

    prompt_text = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt_text, str):
        return ()
    overlaps = compute_overlaps(
        prompt_text=prompt_text,
        prompt_cache=list(corrected_prompt_cache),
        cache_item_names=cache_item_names,
        batch_aliases=_batch_aliases(node),
    )
    return tuple(sorted({overlap.body_ref for overlap in overlaps}))


def _detect_partial_prompt_cache_declarations(
    workflow_ir: dict[str, Any],
    workflow_path: str | None,
    ctx: AnalysisContext,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
) -> list[_PartialDeclarationFinding]:
    """Find LLM nodes that reference shared cache chunks they do not declare."""
    items = _cache_items(workflow_ir)
    if not items:
        return []
    name_order = [str(item["name"]) for item in items]
    var_to_name = _cache_item_var_to_name(items)
    if not var_to_name:
        return []

    refs_by_name = _collect_llm_template_root_references(workflow_ir, var_to_name)
    cache_item_names = set(name_order)
    findings: list[_PartialDeclarationFinding] = []
    for node in workflow_ir.get("nodes", []) or []:
        finding = _partial_declaration_finding_for_node(
            node=node,
            name_order=name_order,
            var_to_name=var_to_name,
            refs_by_name=refs_by_name,
            cache_item_names=cache_item_names,
            workflow_path=workflow_path,
            ctx=ctx,
            rows_by_node_path=rows_by_node_path,
        )
        if finding is not None:
            findings.append(finding)
    return findings


def _cache_item_var_to_name(items: list[dict[str, Any]]) -> dict[str, str]:
    var_to_name: dict[str, str] = {}
    for item in items:
        name = item.get("name")
        if not isinstance(name, str):
            continue
        var = item.get("var", name)
        if isinstance(var, str) and var:
            var_to_name[var] = name
    return var_to_name


def _partial_declaration_finding_for_node(
    *,
    node: dict[str, Any],
    name_order: list[str],
    var_to_name: dict[str, str],
    refs_by_name: dict[str, list[str]],
    cache_item_names: set[str],
    workflow_path: str | None,
    ctx: AnalysisContext,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
) -> _PartialDeclarationFinding | None:
    if not isinstance(node, dict) or node.get("type") != "llm":
        return None
    node_id_raw = node.get("id")
    declared_raw = node.get("prompt_cache")
    prompt = node.get("params", {}).get("prompt", "")
    if not node_id_raw or not isinstance(declared_raw, list) or not isinstance(prompt, str):
        return None
    node_id = str(node_id_raw)
    declared = tuple(str(chunk) for chunk in declared_raw)
    node_refs = _node_referenced_cache_names(node, var_to_name)
    missing = _missing_shared_cache_names(name_order, node_refs, set(declared), refs_by_name)
    if not missing:
        return None

    corrected_set = set(declared) | set(missing)
    corrected = tuple(name for name in name_order if name in corrected_set)
    rep_model = _representative_model_for_node(node_id, workflow_path, rows_by_node_path)
    missing_tokens = _estimate_missing_chunks_tokens(
        missing,
        var_to_name,
        model=rep_model,
        ctx=ctx,
        workflow_path=workflow_path,
    )
    return _PartialDeclarationFinding(
        node_id=node_id,
        declared_chunks=declared,
        missing_chunks=tuple(missing),
        corrected_prompt_cache=corrected,
        prompt_body_cleanup=_prompt_body_cleanup_for_node(node, corrected, cache_item_names),
        missing_chunks_tokens=missing_tokens,
        rep_model=rep_model,
    )


def _node_referenced_cache_names(node: dict[str, Any], var_to_name: dict[str, str]) -> set[str]:
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt, str):
        return set()
    node_refs: set[str] = set()
    batch_aliases = _batch_aliases(node)
    node_inputs = _node_inputs(node)
    for ref in classify_prompt_refs(prompt, batch_alias=None, node_inputs=node_inputs):
        for operand in ref.operand_paths:
            if _is_batch_scoped_ref(operand, batch_aliases):
                continue
            matched_var = _longest_var_prefix_match(operand, var_to_name.keys())
            if matched_var is not None:
                node_refs.add(var_to_name[matched_var])
    return node_refs


def _missing_shared_cache_names(
    name_order: list[str],
    node_refs: set[str],
    declared: set[str],
    refs_by_name: dict[str, list[str]],
) -> list[str]:
    missing: list[str] = []
    for name in name_order:
        if name not in node_refs or name in declared:
            continue
        if len(set(refs_by_name.get(name, []))) >= 2:
            missing.append(name)
    return missing


def _estimate_missing_chunks_tokens(
    missing_names: list[str],
    var_to_name: dict[str, str],
    *,
    model: str,
    ctx: AnalysisContext,
    workflow_path: str | None,
) -> int | None:
    """Sum per-call token estimates for missing cache items' values."""
    if not model:
        return None
    name_to_var = {name: var for var, name in var_to_name.items()}
    total = 0
    for name in missing_names:
        var = name_to_var.get(name)
        if var is None:
            return None
        tokens = _estimate_ref_tokens(
            var,
            model=model,
            memo_cache=ctx.memo_cache,
            workflow_path=workflow_path,
            ctx=ctx,
        )
        if tokens is None:
            return None
        total += tokens
    return total


def _representative_model_for_node(
    node_id: str,
    workflow_path: str | None,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
) -> str:
    row = rows_by_node_path.get((workflow_path, node_id))
    return row.model if row is not None and row.model else ""


def _emit_partial_declaration_findings(
    *,
    cw_result: Any,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    ctx: AnalysisContext,
    consolidate_root_diags: list[Diagnostic],
) -> list[Diagnostic]:
    """Emit one grouped ``cache.prompt-cache-incomplete`` diagnostic per workflow."""
    consolidate_roots = _extract_consolidate_roots(consolidate_root_diags)
    diagnostics: list[Diagnostic] = []
    for workflow_path, workflow_ir in getattr(cw_result, "irs_by_workflow", {}).items():
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
        findings = _detect_partial_prompt_cache_declarations(
            workflow_ir,
            workflow_path,
            wf_ctx,
            rows_by_node_path,
        )
        findings = [
            finding
            for finding in findings
            if not _finding_chunks_overlap_with_consolidate(finding.missing_chunks, consolidate_roots, workflow_path)
        ]
        if not findings:
            continue
        below_threshold = any(is_below_min_cache(f.rep_model, f.missing_chunks_tokens) for f in findings)
        below_threshold_clause = _below_threshold_clause_for_findings(findings) if below_threshold else ""
        savings_usd = (
            None
            if below_threshold
            else _project_partial_declaration_savings(findings, rows_by_node_path, workflow_path)
        )
        workflow_label = workflow_path or "<inline>"
        diagnostics.append(
            make_diagnostic(
                "cache.prompt-cache-incomplete",
                node_id=None,
                affected_workflow=workflow_label,
                workflow_basename=Path(workflow_label).name if workflow_path else "<inline>",
                affected_node_count=len(findings),
                node_findings=_node_findings_context(findings),
                node_findings_block=_format_node_findings_block(findings),
                below_threshold_clause=below_threshold_clause,
                savings_usd=savings_usd,
            )
        )
    return diagnostics


def _extract_consolidate_roots(diagnostics: list[Diagnostic]) -> dict[str | None, set[str]]:
    roots: dict[str | None, set[str]] = {}
    for diag in diagnostics:
        if diag.id != "cache.consolidate-to-root-recommended":
            continue
        ctx = diag.context or {}
        workflow = ctx.get("affected_workflow")
        root = ctx.get("root")
        if isinstance(root, str):
            roots.setdefault(str(workflow) if isinstance(workflow, str) else None, set()).add(root)
    return roots


def _finding_chunks_overlap_with_consolidate(
    missing_chunks: tuple[str, ...],
    consolidate_roots: dict[str | None, set[str]],
    workflow_path: str | None,
) -> bool:
    roots = consolidate_roots.get(workflow_path, set())
    return any(_template_root_segment(chunk) in roots for chunk in missing_chunks)


def _below_threshold_clause_for_findings(findings: list[_PartialDeclarationFinding]) -> str:
    entries: list[str] = []
    for finding in findings:
        tokens = finding.missing_chunks_tokens
        if not is_below_min_cache(finding.rep_model, tokens) or tokens is None:
            continue
        threshold = get_min_cache_tokens(finding.rep_model)
        entries.append(f"{finding.node_id}: ~{tokens:,} tokens below {finding.rep_model}'s {threshold:,}-token minimum")
    if not entries:
        return ""
    return "\nNote: " + "; ".join(entries) + " — caching won't fire until rendered content reaches the minimum."


def _project_partial_declaration_savings(
    findings: list[_PartialDeclarationFinding],
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    workflow_path: str | None,
) -> float | None:
    total = 0.0
    for finding in findings:
        if finding.missing_chunks_tokens is None:
            return None
        row = rows_by_node_path.get((workflow_path, finding.node_id))
        if row is None or not row.model:
            return None
        # Trace observations win when present; greenfield rows fall back to the
        # row contract multiplier (batch size or 1).
        calls = row.observed_call_count or invocation_count_for(row)
        savings = _estimate_token_savings_usd(row.model, finding.missing_chunks_tokens, calls)
        if savings is None:
            return None
        total += savings
    return total


def _node_findings_context(findings: list[_PartialDeclarationFinding]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": finding.node_id,
            "missing_chunks": list(finding.missing_chunks),
            "missing_chunks_csv": ", ".join(f"`{chunk}`" for chunk in finding.missing_chunks),
            "corrected_prompt_cache": list(finding.corrected_prompt_cache),
            "corrected_prompt_cache_inline": "[" + ", ".join(finding.corrected_prompt_cache) + "]",
            "prompt_body_cleanup": list(finding.prompt_body_cleanup),
            "prompt_body_cleanup_csv": ", ".join(f"${{{ref}}}" for ref in finding.prompt_body_cleanup) or "(none)",
            "rep_model": finding.rep_model,
            "missing_chunks_tokens": finding.missing_chunks_tokens,
        }
        for finding in findings
    ]


def _format_node_findings_block(findings: list[_PartialDeclarationFinding]) -> str:
    lines = ["Affected nodes:"]
    for finding in findings:
        cleanup = ", ".join(f"${{{ref}}}" for ref in finding.prompt_body_cleanup) or "(none)"
        corrected = "[" + ", ".join(finding.corrected_prompt_cache) + "]"
        model = finding.rep_model or "<unresolved>"
        lines.extend([
            f"- `{finding.node_id}` (model: {model}):",
            f"    1. Remove from prompt body: {cleanup}",
            f"    2. Set prompt_cache: {corrected}",
        ])
    return "\n".join(lines)


def _is_batch_scoped_ref(ref: str, aliases: set[str]) -> bool:
    return any(ref == alias or ref.startswith(f"{alias}.") or ref.startswith(f"{alias}[") for alias in aliases)


def _emit_padding_advisories(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
) -> list[Diagnostic]:
    """Build and filter ``cache.padding-advisory`` candidates."""
    cache_items = _cache_items(workflow_ir)
    declared_names = [str(item["name"]) for item in cache_items]
    if not declared_names:
        return []
    candidates: list[PaddingCandidate] = []
    for node in workflow_ir.get("nodes", []) or []:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        subset = node.get("prompt_cache")
        if not isinstance(subset, list) or not subset:
            continue
        current_subset = tuple(str(item) for item in subset)
        if current_subset[0] not in declared_names:
            continue
        first_pos = declared_names.index(current_subset[0])
        if first_pos == 0:
            continue
        row = rows_by_node.get(str(node.get("id")))
        if row is None:
            continue
        rate = _input_rate(row.model)
        if rate is None:
            continue
        prefix_tokens = sum(_estimate_chunk_tokens(item, row.model) for item in cache_items[:first_pos])
        call_count = invocation_count_for(row)
        savings_usd = 0.9 * prefix_tokens * call_count * rate
        candidates.append(
            PaddingCandidate(
                node_id=row.node_path,
                workflow_path=row.workflow_path,
                current_subset=current_subset,
                suggested_subset=tuple(declared_names[:first_pos]) + current_subset,
                savings_usd=savings_usd,
            )
        )
    return compute_padding_advisories(candidates)


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


def _cache_items(workflow_ir: dict[str, Any]) -> list[dict[str, Any]]:
    cache = workflow_ir.get("cache")
    if not isinstance(cache, dict):
        return []
    items = cache.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("name"), str)]


def _cache_item_names(workflow_ir: dict[str, Any]) -> list[str]:
    return [str(item["name"]) for item in _cache_items(workflow_ir)]


def _estimate_chunk_tokens(item: dict[str, Any], model: str) -> int:
    text = f"{item.get('prose_before', '')}\n${{{item.get('var', item.get('name', ''))}}}"
    return estimate_tokens(model, text)[0]


def _sum_chunk_tokens(
    refs: list[str],
    model: str,
    ctx: AnalysisContext,
    memo_cache: Any,
    workflow_path: str | None,
) -> int | None:
    """Sum chunk tokens across refs. Returns None if any ref is unmeasurable."""
    total = 0
    for ref in refs:
        tokens = _estimate_ref_tokens(ref, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
        if tokens is None:
            return None
        total += tokens
    return total


def _savings_for_shared_ref(
    ref: str,
    node_ids: list[str],
    rows_by_node: dict[str, PerCallRow],
    tokens: int | None,
    eligible_nodes: set[str],
) -> float | None:
    if tokens is None:
        # No memo data → can't compute savings honestly. Mirror the existing
        # cost tri-state contract: None propagates rather than fabricating 0.
        return None
    eligible_in_order = [node_id for node_id in node_ids if node_id in eligible_nodes]
    if len(eligible_in_order) < 2:
        return 0.0
    total = 0.0
    for node_id in eligible_in_order[1:]:
        row = rows_by_node.get(node_id)
        if row is None:
            return None
        savings = _estimate_token_savings_usd(row.model, tokens, invocation_count_for(row))
        if savings is None:
            return None
        total += savings
    return total


def _estimate_token_savings_usd(model: str, tokens: int, calls: int) -> float | None:
    rate = _input_rate(model)
    if rate is None:
        return None
    return 0.9 * tokens * calls * rate


def _input_rate(model: str) -> float | None:
    from .cost_estimation import get_model_pricing

    pricing = get_model_pricing(model)
    return pricing.input_rate if pricing is not None else None


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
class _SubWorkflowCacheCandidate:
    """One child-workflow cache declaration opportunity.

    Sub-workflows do not inherit parent ``## Cache`` blocks, so a parent-side
    declaration never satisfies the child. The actionable edit is in the
    receiving workflow when that child has repeated LLM consumers of the
    incoming input.
    """

    parent_workflow: str
    parent_value_expr: str
    parent_node_id: str
    line_in_parent: int
    child_workflow: str
    child_input_name: str
    child_count: int
    child_node_ids: tuple[str, ...]
    parent_cache_ref: str = ""
    child_cache_ref: str = ""
    parent_prose: str = ""
    parent_prose_origins_differ: bool = False
    body_refs_by_node: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    origin_count: int = 1
    has_multiple_parent_origins: bool = False

    def __post_init__(self) -> None:
        if not self.child_cache_ref:
            object.__setattr__(self, "child_cache_ref", self.child_input_name)
        if not self.parent_cache_ref:
            object.__setattr__(self, "parent_cache_ref", self.parent_value_expr)


@dataclass(frozen=True)
class _ChildCacheRefUse:
    """Actual child prompt refs under a workflow input, grouped by cache entry."""

    child_cache_ref: str
    consumer_node_ids: tuple[str, ...]
    body_refs_by_node: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class _GroupedConsumerProjection:
    """One child LLM node's cumulative cache opportunity within a group.

    ``per_call_prefix_tokens`` is the sum of input tokens this consumer receives
    on each call. It's what the provider's cache minimum is checked against —
    pflow emits one or more ``cache_control`` markers per call (Anthropic
    multi-breakpoint); the terminal marker sees the full per-call prefix bytes.
    The threshold gate must use this field (per-call prefix tokens), NOT a
    cohort total (per_call × call_count), which mixes units and silently
    mis-classifies low-per-call high-call-count cases. Multi-breakpoint
    placement does not change the per-call denominator.

    ``threshold`` is the provider's per-call minimum for this consumer's model.
    ``savings_usd`` is cohort-level (already multiplied by call count) — the
    cost projection is honest about per-workflow-run savings.
    """

    consumer_node_id: str
    model: str
    consumed_inputs: tuple[str, ...]
    per_call_prefix_tokens: int
    threshold: int
    savings_usd: float | None
    did_not_execute_in_trace: bool


@dataclass(frozen=True)
class _SubWorkflowCacheGroup:
    """All undeclared cache inputs flowing into one child workflow."""

    child_workflow: str
    candidates: tuple[_SubWorkflowCacheCandidate, ...]


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


def _resolve_value_in_workflow_memo(
    ref: str,
    *,
    workflow_path: str,
    ctx: AnalysisContext,
) -> Any | None:
    """Resolve ``ref`` against memo cache scoped to a specific workflow path.

    Cross-workflow analog to ``AnalysisContext._resolve_from_memo`` (which
    keys on ``self.workflow_path``). For sub-workflow boundary findings the
    parent value lives in the parent workflow, not the root.
    """
    if ctx.memo_cache is None:
        return None
    root = TemplateResolver.extract_root_node_id(ref)
    if not root:
        return None
    try:
        latest = _latest_memo_for_freshness_check(ctx.memo_cache, root, workflow_path=workflow_path, ctx=ctx)
    except Exception:
        logger.debug("memo_cache freshness check failed for %s in %s", ref, workflow_path, exc_info=True)
        return None
    if latest is None:
        return None
    output, _created_at = latest
    if not isinstance(output, dict):
        return None
    try:
        resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: output})
    except Exception:
        logger.debug("memo resolve failed for %s in %s", ref, workflow_path, exc_info=True)
        return None
    if isinstance(resolved, str) and resolved == f"${{{ref}}}":
        return None
    return _normalize_empty(resolved)


def _resolve_value_in_workflow_parameters(
    ref: str,
    *,
    workflow_path: str,
    ctx: AnalysisContext,
) -> Any | None:
    """Resolve ``ref`` against workflow-scoped parameters (Tier 0).

    Cross-workflow analog to ``AnalysisContext._resolve_from_parameters``.
    For sub-workflow boundary findings the parent value lives in the parent
    workflow, not necessarily the analyzed root.

    Reads from ``ctx.parameters_for_workflow(workflow_path)``. For the analyzed
    root that is the caller's current parameters; for nested children that is
    the walker-resolved parameter dict from ``_build_parameters_by_workflow``.
    Both are honest signals because the walker resolves parent ``inputs:``
    expressions through the same template resolver used elsewhere in analysis.

    Placement before memo mirrors ``AnalysisContext.resolve_ref_value``:
    current parameters win over historical memo values from prior runs.
    """
    params = ctx.parameters_for_workflow(workflow_path)
    root = TemplateResolver.extract_root_node_id(ref)
    if not root:
        return None
    if root not in params and root in ctx.parameters:
        params = ctx.parameters
    if root not in params:
        return None
    try:
        resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: params[root]})
    except Exception:
        logger.debug("parameters resolve failed for %s in %s", ref, workflow_path, exc_info=True)
        return None
    if isinstance(resolved, str) and resolved == f"${{{ref}}}":
        return None
    return _normalize_empty(resolved)


def _trace_node_output_for(
    node_id: str,
    *,
    workflow_path: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> dict[str, Any] | None:
    """Latest event output for ``(workflow_path, node_id)`` from trace.

    Last match wins (loop-recovery semantics — ``workflow_trace.py`` uses the
    final event per node id as the canonical "current state"). Prefers
    ``event["node_output"]`` (full namespaced dict — supports dotted paths)
    over ``event["llm_response"]`` (literal string for ``${node.response}``
    refs on LLM nodes that didn't write a structured output).
    """
    if ctx.trace is None:
        return None
    edges = _edge_child_paths(cw_result)
    output: dict[str, Any] | None = None
    for we in ctx.trace.walk(edges=edges, workflow_path=ctx.workflow_path):
        if we.workflow_path != workflow_path or we.event.get("node_id") != node_id:
            continue
        event_output = we.event.get("node_output")
        if isinstance(event_output, Mapping):
            output = dict(event_output)
            continue
        llm_response = we.event.get("llm_response")
        if isinstance(llm_response, str):
            output = {"response": llm_response}
    return output


def _resolve_value_in_workflow_trace(
    ref: str,
    *,
    workflow_path: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> Any | None:
    """Resolve ``ref`` against trace data scoped to ``workflow_path``.

    Walker attribution: ``TraceTree.walk(edges=...)`` threads workflow_path
    via the cross-workflow edge map for sub-workflows / batch items; we
    filter on ``we.workflow_path == workflow_path AND we.event['node_id']
    == root`` to find the parent's event.
    """
    root = TemplateResolver.extract_root_node_id(ref)
    if not root:
        return None
    output = _trace_node_output_for(root, workflow_path=workflow_path, ctx=ctx, cw_result=cw_result)
    if output is None:
        return None
    try:
        resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: output})
    except Exception:
        logger.debug("trace resolve failed for %s in %s", ref, workflow_path, exc_info=True)
        return None
    if isinstance(resolved, str) and resolved == f"${{{ref}}}":
        return None
    return _normalize_empty(resolved)


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

    Closes the input-passthrough gap left by ``_resolve_value_in_workflow_trace``:
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

    Last match wins (loop-recovery semantics — mirrors ``_trace_node_output_for``).
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
    if not TemplateResolver.variable_exists(synthetic_ref, {"__value": value}):
        return None
    return TemplateResolver.resolve_value(synthetic_ref, {"__value": value})


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

    Tier 0: workflow parameters (caller-provided for the analyzed root, or
    walker-propagated values for nested children). Mirrors the "parameters win
    over memo" convention so current inputs beat stale memo from prior runs.
    Tier 1: memo cache (cross-workflow scoped, by ``parent_value_expr`` root).
    Tier 2: trace by node_id — for node-output-rooted refs (e.g. ``${creative.direction}``)
    where ``creative`` is a node id in the parent workflow.
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
    value = _resolve_value_in_workflow_parameters(ref, workflow_path=workflow_path, ctx=ctx)
    if value is None:
        value = _resolve_value_in_workflow_memo(ref, workflow_path=workflow_path, ctx=ctx)
    if value is None:
        value = _resolve_value_in_workflow_trace(ref, workflow_path=workflow_path, ctx=ctx, cw_result=cw_result)
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


def _workflow_basename(workflow_path: str) -> str:
    return workflow_path.rsplit("/", 1)[-1] if "/" in workflow_path else workflow_path


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


def _cache_refs_by_consumer(group: _SubWorkflowCacheGroup) -> dict[str, list[str]]:
    refs_by_consumer: dict[str, list[str]] = {}
    for candidate in group.candidates:
        for node_id in candidate.child_node_ids:
            refs_by_consumer.setdefault(node_id, []).append(candidate.child_cache_ref)
    return refs_by_consumer


def _grouped_consumer_projections(
    group: _SubWorkflowCacheGroup,
    rows_by_node_path: dict[tuple[str | None, str], PerCallRow],
    *,
    tokens_per_ref: dict[str, int | None],
) -> tuple[tuple[_GroupedConsumerProjection, ...], float | None]:
    projections: list[_GroupedConsumerProjection] = []
    total_savings: float | None = 0.0
    for consumer_node_id, cache_refs in sorted(_cache_refs_by_consumer(group).items()):
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


def _format_grouped_body_block(
    group: _SubWorkflowCacheGroup,
    projections: tuple[_GroupedConsumerProjection, ...],
    tokens_per_input: dict[str, int | None],
    strictest_model: str,
    strictest_threshold: int,
    case: str,
    cw_result: Any,
) -> str:
    """Render the case-specific body embedded in the diagnostic message.

    All threshold comparisons use ``per_call_prefix_tokens`` — the bytes the
    provider's cache marker sees on each call. Cohort totals (per_call × calls)
    drive ``savings_usd`` only; they're irrelevant to whether the cache fires.
    """
    candidates_by_ref = {candidate.child_cache_ref: candidate for candidate in group.candidates}
    parent_label = _workflow_basename(group.candidates[0].parent_workflow) if group.candidates else "parent workflow"
    ref_count = len(group.candidates)
    input_phrase = _count_phrase(ref_count, "value")
    # Per-call prefix size of the LARGEST consumer in the group — used as the
    # representative "what does the provider see per call" number for body text.
    # For multi-consumer groups we still render per-consumer lines below.
    per_call_max = max((p.per_call_prefix_tokens for p in projections), default=0)
    lines: list[str] = []

    if case == "unmeasurable":
        return _format_unmeasurable_grouped_body(
            group=group,
            input_phrase=input_phrase,
            tokens_per_input=tokens_per_input,
            cw_result=cw_result,
        )

    if case == "refactor":
        return _format_refactor_grouped_body(
            group=group,
            input_phrase=input_phrase,
            ref_count=ref_count,
            per_call_max=per_call_max,
            tokens_per_input=tokens_per_input,
            cw_result=cw_result,
        )

    threshold_clause = (
        f"above {strictest_model}'s {strictest_threshold:,}-token cache minimum"
        if per_call_max >= strictest_threshold
        else f"below {strictest_model}'s {strictest_threshold:,}-token cache minimum"
    )
    if len(projections) > 1:
        lines.append(
            f"{input_phrase.capitalize()} {_flow_verb(ref_count)} in from parent {parent_label}, used by "
            f"{_count_phrase(len(projections), 'consumer node')}."
        )
        _append_honest_edit_lines(
            lines, group, tokens_per_input=tokens_per_input, cw_result=cw_result, include_cleanup=False
        )
        lines.append("Prompt-body templates to remove and per-consumer cache prefix:")
        for projection in projections:
            lines.extend(
                _format_per_consumer_input_lines(
                    projection=projection,
                    candidates_by_input=candidates_by_ref,
                    tokens_per_input=tokens_per_input,
                    cw_result=cw_result,
                )
            )
    else:
        lines.append(
            f"{input_phrase.capitalize()} {_flow_verb(ref_count)} in from parent {parent_label}: "
            f"{_format_tokens_phrase(per_call_max)} per call ({threshold_clause})."
        )
        _append_honest_edit_lines(lines, group, tokens_per_input=tokens_per_input, cw_result=cw_result)

    if case == "model_switch":
        alternatives = anthropic_models_at_threshold(_MODEL_SWITCH_BAND)
        lines.append(
            f"→ Switch model: replace the `- model:` line in {_workflow_basename(group.child_workflow)} with one of:"
        )
        for model in alternatives:
            suffix = " (recommended — pflow's default)" if model == "claude-sonnet-4-5" else ""
            lines.append(f"    anthropic/{model}{suffix}")
        lines.append(
            "  These cache at ≥1,024 tokens. `prompt_cache:` declarations transfer unchanged. "
            "Switching providers changes base inference cost — see `pflow guide prompt-caching`."
        )
        lines.append("→ Then: apply steps (1)(2)(3) above.")
        lines.append(
            f"→ Monitor: re-run analyze-cache when per-call content grows past {strictest_threshold:,} tokens "
            "to enable caching at the current model."
        )

    return "\n".join(lines)


def _format_unmeasurable_grouped_body(
    *,
    group: _SubWorkflowCacheGroup,
    input_phrase: str,
    tokens_per_input: dict[str, int | None],
    cw_result: Any,
) -> str:
    lines = [
        f"{input_phrase.capitalize()} flow in but no consumer node has a resolved model — "
        "cannot compute the cache threshold."
    ]
    _append_honest_edit_lines(lines, group, tokens_per_input=tokens_per_input, cw_result=cw_result)
    lines.append(
        "→ Set `settings.default_model` or add `- model:` to each consumer node in "
        f"{_workflow_basename(group.child_workflow)}, then re-run analyze-cache."
    )
    return "\n".join(lines)


def _format_refactor_grouped_body(
    *,
    group: _SubWorkflowCacheGroup,
    input_phrase: str,
    ref_count: int,
    per_call_max: int,
    tokens_per_input: dict[str, int | None],
    cw_result: Any,
) -> str:
    subject = f"One value `{group.candidates[0].child_cache_ref}`" if ref_count == 1 else input_phrase.capitalize()
    lines = [
        f"{subject} {_format_tokens_phrase(per_call_max)} per call, "
        "below the smallest provider cache minimum (1,024 — Anthropic Sonnet 4.5)."
    ]
    _append_honest_edit_lines(lines, group, tokens_per_input=tokens_per_input, cw_result=cw_result)
    lines.append("→ Monitor: re-run analyze-cache when per-call content grows past 1,024 tokens.")
    lines.append(f"→ Verify: confirm {_format_tokens_phrase(per_call_max)} is the realistic per-call size.")
    return "\n".join(lines)


def _append_honest_edit_lines(
    lines: list[str],
    group: _SubWorkflowCacheGroup,
    *,
    tokens_per_input: dict[str, int | None],
    cw_result: Any,
    include_cleanup: bool = True,
) -> None:
    if _group_has_subpath_candidates(group):
        lines.append(_subpath_honesty_sentence(group))
    lines.extend(_format_exact_child_cache_edits(group))
    if include_cleanup:
        lines.append("Prompt-body templates to remove:")
        lines.extend(
            _format_single_consumer_input_lines(
                candidates=group.candidates,
                tokens_per_input=tokens_per_input,
                cw_result=cw_result,
            )
        )


def _group_has_subpath_candidates(group: _SubWorkflowCacheGroup) -> bool:
    return any(candidate.child_cache_ref != candidate.child_input_name for candidate in group.candidates)


def _subpath_honesty_sentence(group: _SubWorkflowCacheGroup) -> str:
    roots = tuple(dict.fromkeys(candidate.child_input_name for candidate in group.candidates))
    root_text = ", ".join(f"`{root}`" for root in roots)
    return (
        "Only these listed values are used by prompts. Do not cache full objects like "
        f"{root_text} unless you intentionally want every field in that object sent to the model."
    )


def _format_exact_child_cache_edits(group: _SubWorkflowCacheGroup) -> list[str]:
    lines = ["Edit child workflow:", "  Add or extend ## Cache:"]
    lines.append("    ```cache")
    lines.extend(f"    {line}" for line in _exact_child_cache_block_content(group).split("\n"))
    lines.append("    ```")
    lines.append("  Add prompt_cache entries:")
    for node_id, refs in sorted(_cache_refs_by_consumer(group).items()):
        ordered_refs = [
            candidate.child_cache_ref for candidate in group.candidates if candidate.child_cache_ref in refs
        ]
        lines.append(f"    {node_id}: prompt_cache: [{', '.join(ordered_refs)}]")
    return lines


def _exact_child_cache_block_content(group: _SubWorkflowCacheGroup) -> str:
    """Render the paste-ready child ``## Cache`` block content.

    Each chunk emits the var line on its own; when a matching parent chunk
    contributes prose, a 40-char single-line preview of that prose is rendered
    immediately above the var line. Chunks are separated by blank lines to
    mirror the parent's ``## Cache`` visual structure. The single-line preview
    is intentional: it stays scannable for agents and (because
    ``_static_excerpt`` collapses internal whitespace) survives the renderer's
    line-by-line indenting without breaking the cache block layout.
    """
    parts: list[str] = []
    for candidate in group.candidates:
        chunk = ""
        if candidate.parent_prose.strip() and not candidate.parent_prose_origins_differ:
            chunk += _static_excerpt(candidate.parent_prose, limit=_PARENT_PROSE_PREVIEW_LIMIT)
            chunk += "\n\n"
        chunk += f"${{{candidate.child_cache_ref}}}"
        parts.append(chunk)
    return "\n\n".join(parts)


def _threshold_relation(tokens: int, threshold: int) -> str:
    return "above" if tokens >= threshold else "below"


def _parent_origin_clause(candidate: _SubWorkflowCacheCandidate) -> str | None:
    """Sub-line text naming the parent expression when it differs from the child input name.

    Surfaces parent→child data flow inside the action body for renamed inputs.
    Returns ``None`` for same-name passthroughs (no signal to add) and for
    multi-ref/literal parent values where ``parent_value_expr`` is empty.
    """
    expr = candidate.parent_value_expr
    if not expr or candidate.parent_cache_ref == candidate.child_cache_ref:
        return None
    return f"flows in from parent as `${{{candidate.parent_cache_ref}}}`"


def _format_per_consumer_input_lines(
    *,
    projection: _GroupedConsumerProjection,
    candidates_by_input: dict[str, _SubWorkflowCacheCandidate],
    tokens_per_input: dict[str, int | None],
    cw_result: Any,
) -> list[str]:
    """Render input bullets under one consumer-node heading in the multi-consumer case."""
    lines = [
        f"  Node `{projection.consumer_node_id}` "
        f"({_format_tokens_phrase(projection.per_call_prefix_tokens)} per call — "
        f"{_threshold_relation(projection.per_call_prefix_tokens, projection.threshold)} "
        f"{projection.threshold:,}-token minimum):"
    ]
    for input_name in projection.consumed_inputs:
        candidate = candidates_by_input[input_name]
        refs = _per_input_var_refs(candidate, cw_result).get(projection.consumer_node_id, ())
        lines.append(
            f"    • `{input_name}` {_format_nullable_tokens(tokens_per_input.get(input_name))} — "
            f"uses {_format_var_refs(refs, fallback=input_name)}"
        )
        origin = _parent_origin_clause(candidate)
        if origin is not None:
            lines.append(f"        {origin}")
    return lines


def _format_single_consumer_input_lines(
    *,
    candidates: tuple[_SubWorkflowCacheCandidate, ...],
    tokens_per_input: dict[str, int | None],
    cw_result: Any,
) -> list[str]:
    """Render input bullets when the group has a single consumer node."""
    lines: list[str] = []
    for candidate in candidates:
        refs_by_node = _per_input_var_refs(candidate, cw_result)
        refs = tuple(ref for node_refs in refs_by_node.values() for ref in node_refs)
        consumer_text = ", ".join(f"`{node_id}`" for node_id in candidate.child_node_ids)
        lines.append(
            f"  • `{candidate.child_cache_ref}` "
            f"{_format_nullable_tokens(tokens_per_input.get(candidate.child_cache_ref))} — "
            f"node(s) {consumer_text} use {_format_var_refs(refs, fallback=candidate.child_cache_ref)}"
        )
        origin = _parent_origin_clause(candidate)
        if origin is not None:
            lines.append(f"      {origin}")
    return lines


def _count_phrase(count: int, singular: str) -> str:
    if count == 1:
        return f"1 {singular}"
    if singular == "value":
        words = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}
        return f"{words.get(count, str(count))} values"
    return f"{count} {singular}s"


def _flow_verb(count: int) -> str:
    return "flows" if count == 1 else "flow"


def _format_tokens_phrase(tokens: int) -> str:
    return f"~{tokens:,} tokens"


def _format_nullable_tokens(tokens: int | None) -> str:
    return "unmeasurable" if tokens is None else f"~{tokens:,} tokens"


def _format_var_refs(refs: Iterable[str], *, fallback: str) -> str:
    unique = tuple(dict.fromkeys(refs))
    if not unique:
        unique = (fallback,)
    return ", ".join(f"`${{{ref}}}`" for ref in unique)


def _per_input_var_refs(candidate: _SubWorkflowCacheCandidate, cw_result: Any) -> dict[str, tuple[str, ...]]:
    """Prompt `${var}` references that must be removed before caching the input."""
    return {node_id: tuple(refs) for node_id, refs in candidate.body_refs_by_node.items()}


def _grouped_inputs_context(
    group: _SubWorkflowCacheGroup,
    tokens_per_input: dict[str, int | None],
    cw_result: Any,
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
            "template_var_refs_by_node": {
                node_id: list(refs) for node_id, refs in _per_input_var_refs(candidate, cw_result).items()
            },
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
                    inputs=_grouped_inputs_context(split_group, tokens_per_input, cw_result),
                    body_block=_format_grouped_body_block(
                        split_group,
                        split_projections,
                        tokens_per_input,
                        strictest_model,
                        strictest_threshold,
                        case,
                        cw_result,
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


# ---------------------------------------------------------------------------
# Trace discrepancy detection
# ---------------------------------------------------------------------------


def _predict_cache_keys(
    cw_result: Any,
    ctx: AnalysisContext,
) -> tuple[dict[tuple[str | None, str], str], list[str]]:
    """Predict the runtime cache_key for every LLM node, scoped per workflow.

    Walks every workflow's IR independently (root + descendants from
    ``cw_result.irs_by_workflow``) and computes the byte-identical
    cache_key the runtime would compute via ``plan_node`` — the same
    canonical site the engine and the dry-run planner consume. This
    bypasses ``build_plan``'s BFS-downstream mode (which sets
    ``cache_key=None`` for child nodes whose parent took the downstream
    path), the source of Bug 5 in the verification report.

    ``compile_workflow`` + ``create_planner_shared`` are hoisted to the
    per-workflow loop — N LLM nodes in one workflow incur ONE compile, not
    N. ``plan_node`` is then invoked per LLM node against the shared
    compiled+shared scaffold.

    Per-node skip reasons replace the catch-all silent-skip count that the
    legacy implementation produced — agents see exactly which node's
    prediction failed and why.

    Returns ``(predicted_keys, notes)`` where ``predicted_keys`` keys
    ``(workflow_path, node_id) -> cache_key``. The contract matches the
    legacy implementation; only the production path changes.
    """
    notes: list[str] = []
    if ctx.memo_cache is None:
        notes.append(
            "Cache fidelity check skipped: this is a first run "
            "(no prior runs to compare cached vs uncached against). "
            "On later runs, specific cache misfires (TTL expired, chunks skipped) will appear here."
        )
        return {}, notes

    irs_by_workflow = getattr(cw_result, "irs_by_workflow", None) or {}
    if not irs_by_workflow:
        # Defensive fallback: no cross-workflow walker output. Use the root
        # IR alone (analyzer never calls _predict_cache_keys without the root).
        irs_by_workflow = {ctx.workflow_path: dict(ctx.workflow_ir)}

    predicted_keys: dict[tuple[str | None, str], str] = {}
    skipped_input_workflows: list[str] = []
    for workflow_path, ir in irs_by_workflow.items():
        _predict_one_workflow(
            workflow_path=workflow_path,
            ir=ir,
            ctx=ctx,
            predicted_keys=predicted_keys,
            notes=notes,
            skipped_input_workflows=skipped_input_workflows,
        )
    if skipped_input_workflows:
        notes.append(_format_skipped_workflows_note(skipped_input_workflows))
    return predicted_keys, notes


def _format_dynamic_batches_note(batches: tuple[DynamicBatchInfo, ...]) -> str | None:
    """Aggregate runtime-template batches into ONE Note (B-4).

    Workflow-type nodes whose ``batch.items`` is a ``${...}`` template can't
    have their per-item children enumerated statically. Pre-B-4 rendering
    emitted ~150 chars of near-identical prose per occurrence — lyrics-
    generator's 3 batches blew up to ~500 chars of repeated content in
    ``## Notes``. The aggregated form lists each batch's ``node_id`` +
    ``items_expression`` once and shares the explanatory prose.

    Single-batch case keeps the original phrasing for continuity with
    pre-B-4 baselines and the existing substring-only test
    (``test_template_items_gap_note_uses_real_analyze_cache_cli_param_wording``).
    """
    if not batches:
        return None
    if len(batches) == 1:
        b = batches[0]
        return (
            f"Workflow batch {b.node_id} in {b.parent_workflow} uses items: {b.items_expression}; sub-workflow "
            "rows for these runtime items are not in the per-call table. The displayed cost is measured from "
            "trace events, not estimated. Pass the resolved list as a CLI parameter, or use inline static batch "
            "items, to enable static child enumeration."
        )
    listing = ", ".join(f"`{b.node_id}` (items: `{b.items_expression}`)" for b in batches)
    return (
        f"{len(batches)} dynamic batches not in per-call table: {listing}. Batch items are computed at runtime, "
        "so per-item rows can't be enumerated statically. Pass items as a CLI parameter or use inline static "
        "items to list them. (Cost shown is measured from the trace, not estimated.)"
    )


def _format_fidelity_skip_note(target: str, reason: str, *, applicable: bool = True) -> str:
    """Single SSoT for the "we couldn't verify cache fidelity here" notes.

    Every skip-note in the discrepancy stage describes the same shape: the
    analyzer wanted to compare predicted cache_keys against trace evidence
    for a specific target (workflow or workflow.node), couldn't, and falls
    back to reporting explicit skipped-chunk events from the trace. The
    framing is jargon-free and consistent across all
    9 emit sites so an agent reading the Notes section never has to map
    "Discrepancy detection: predicted-key matching" → "cache fidelity
    check" by themselves.

    ``applicable=False`` switches the prefix for cases like ``cache: false``
    on a node — the check isn't unavailable; it doesn't apply at all.

    Mutation contract: if a producer ever bypasses this helper and emits
    the old "Discrepancy detection: ..." prefix directly, the jargon
    returns. The wording lives in this one place to prevent that drift.
    """
    prefix = "Cache fidelity check skipped for" if applicable else "Cache fidelity check not applicable to"
    return f"{prefix} {target}: {reason}. Chunk-skip detection still applies."


def _format_skipped_workflows_note(paths: list[str]) -> str:
    """Aggregate per-sub-workflow skip notes into one summary (L-4).

    Single-workflow case keeps the per-workflow detail. Multi-workflow case
    lists up to 5 basenames; overflow as ``+N more``. Real lyrics-generator
    runs emit 15 of these — pre-L-4 rendering blew ~4KB of repeated prose
    into the Notes section.
    """
    if len(paths) == 1:
        return _format_fidelity_skip_note(
            paths[0],
            "that sub-workflow declares inputs which weren't supplied as parameters",
        )
    shown = [Path(p).name if p and p != "<root>" else "<root>" for p in paths[:5]]
    suffix = "" if len(paths) <= 5 else f" + {len(paths) - 5} more"
    return _format_fidelity_skip_note(
        f"{len(paths)} sub-workflows ({', '.join(shown)}{suffix})",
        "they declare inputs which weren't supplied as parameters. "
        "Pass concrete `<input>=<value>` parameters via CLI to enable per-workflow checks",
    )


def _attach_predicted_cache_keys(
    ctx: AnalysisContext,
    cw_result: Any,
) -> tuple[AnalysisContext, dict[tuple[str | None, str], str], list[str]]:
    """Run cache-key prediction once and store the result on the context."""
    predicted_cache_keys: dict[tuple[str | None, str], str] = {}
    prediction_fidelity_notes: list[str] = []
    try:
        predicted_cache_keys, prediction_fidelity_notes = _predict_cache_keys(cw_result, ctx)
    except _PREDICTION_RECOVERABLE_EXCEPTIONS as exc:
        logger.debug("memo freshness prediction disabled: %s", exc, exc_info=True)
        _mark_all_prediction_skipped(predicted_cache_keys, cw_result, ctx)
    return (
        replace(
            ctx,
            predicted_cache_keys=predicted_cache_keys,
            prediction_fidelity_notes=tuple(prediction_fidelity_notes),
        ),
        predicted_cache_keys,
        prediction_fidelity_notes,
    )


def _predict_one_workflow(
    *,
    workflow_path: str | None,
    ir: Mapping[str, Any],
    ctx: AnalysisContext,
    predicted_keys: dict[tuple[str | None, str], str],
    notes: list[str],
    skipped_input_workflows: list[str],
) -> None:
    """Compute predictions for every LLM node in one workflow IR.

    Mutates ``predicted_keys``, ``notes``, and ``skipped_input_workflows``
    in place. Extracted from ``_predict_cache_keys`` to keep that function
    under the cyclomatic-complexity budget; the per-workflow body has its
    own classification branches (input-gate, no-LLM-shortcut, scaffold
    build, per-node loop) that naturally cluster together.
    """
    params = ctx.parameters_for_workflow(workflow_path)
    declared_inputs_raw = ir.get("inputs")
    declared_inputs: Mapping[str, Any] | None = (
        declared_inputs_raw if isinstance(declared_inputs_raw, Mapping) else None
    )
    # Truly cold case: walker resolved NOTHING and the workflow declares
    # inputs. Skip the whole workflow and aggregate to a single Notes
    # summary at the caller level (L-4). Distinct from the partial-params
    # case below where some inputs were resolved and we want to predict
    # what we can on a per-node basis.
    llm_nodes = [node for node in ir.get("nodes", []) if _is_llm_node(node)]
    if not params and declared_inputs:
        skipped_input_workflows.append(workflow_path or "<root>")
        _mark_prediction_skipped(predicted_keys, workflow_path, llm_nodes)
        return
    if not llm_nodes:
        return
    # Partial-params case: walker resolved some inputs but not all (e.g.,
    # a child input that flows from an upstream sub-workflow output the
    # walker can't reach statically). Pad the missing slots with the
    # standard placeholder so compile succeeds; then skip prediction per
    # node for any node whose templates or referenced cache chunks touch
    # a padded slot — its predicted cache_key would be placeholder-
    # tainted and never match the trace. Per-node skip is silent;
    # skipped-chunk attribution covers real branch-absent misses on those
    # nodes.
    padded_params, dummied_keys = _pad_inputs_for_prediction(params, declared_inputs)
    dummied_chunks = _dummied_cache_chunks(ir, dummied_keys)
    scaffold = _build_predict_scaffold(ir, padded_params, ctx.memo_cache, workflow_path)
    if scaffold is None:
        _mark_prediction_skipped(predicted_keys, workflow_path, llm_nodes)
        return
    for node in llm_nodes:
        if _node_references_any(node, dummied_keys, dummied_chunks):
            predicted_keys[(workflow_path, str(node["id"]))] = _PREDICTION_SKIPPED
            continue
        cache_key, skip_reason = _predict_node_with_scaffold(node, scaffold, workflow_path)
        if cache_key is not None:
            predicted_keys[(workflow_path, str(node["id"]))] = cache_key
        elif skip_reason:
            predicted_keys[(workflow_path, str(node["id"]))] = _PREDICTION_SKIPPED
            notes.append(skip_reason)


def _mark_prediction_skipped(
    predicted_keys: dict[tuple[str | None, str], str],
    workflow_path: str | None,
    nodes: Iterable[Mapping[str, Any]],
) -> None:
    for node in nodes:
        node_id = node.get("id")
        if isinstance(node_id, str):
            predicted_keys[(workflow_path, node_id)] = _PREDICTION_SKIPPED


def _mark_all_prediction_skipped(
    predicted_keys: dict[tuple[str | None, str], str],
    cw_result: Any,
    ctx: AnalysisContext,
) -> None:
    """Mark every known LLM node as attempted-but-uncheckable after prediction outage."""
    irs_by_workflow = getattr(cw_result, "irs_by_workflow", None) or {ctx.workflow_path: dict(ctx.workflow_ir)}
    for workflow_path, workflow_ir in irs_by_workflow.items():
        nodes = workflow_ir.get("nodes", []) if isinstance(workflow_ir, Mapping) else []
        _mark_prediction_skipped(
            predicted_keys,
            workflow_path,
            (node for node in nodes if isinstance(node, Mapping) and _is_llm_node(node)),
        )


def _pad_inputs_for_prediction(
    known_params: Mapping[str, Any],
    declared_inputs: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], frozenset[str]]:
    """Merge walker-resolved params with placeholders for missing inputs.

    The discrepancy stage compiles every sub-workflow to predict runtime
    cache_keys, but the cross-workflow walker can only resolve inputs
    whose values flow statically from the parent. For inputs that come
    from upstream node outputs (e.g. ``${upstream.results}``) the walker
    leaves the slot empty — and ``compile_workflow`` would reject the
    incomplete params dict with ``SchemaValidationError`` before any
    per-node prediction could run, emitting a misleading "workflow failed
    to compile" Note for workflows that run fine end-to-end.

    Padding the missing slots with ``"__validation_placeholder__"`` lets
    compile succeed (same idiom ``WorkflowValidator._validate_one_child_call``
    uses for structural validation). The returned ``dummied_keys`` set
    lets ``_predict_one_workflow`` skip prediction for any node whose
    templates touch a placeholder; those predictions would never match
    the trace's real values.
    """
    padded: dict[str, Any] = dict(known_params)
    if not declared_inputs:
        return padded, frozenset()
    dummies = generate_dummy_parameters(dict(declared_inputs))
    dummied: set[str] = set()
    for key, placeholder in dummies.items():
        if key not in padded:
            padded[key] = placeholder
            dummied.add(key)
    return padded, frozenset(dummied)


def _node_references_any(
    node: Mapping[str, Any],
    dummied_keys: frozenset[str],
    dummied_chunks: frozenset[str],
) -> bool:
    """True iff ``node``'s cache_key would be placeholder-tainted.

    Used by the discrepancy stage to skip cache_key prediction for nodes
    whose inputs depend on dummied (un-walker-resolved) workflow inputs.
    A node is tainted if EITHER:

    - it declares ``prompt_cache: [name]`` referencing a chunk whose
      ``var`` traces back to a dummied input (``dummied_chunks``), OR
    - any ``${var}`` ref in the node's IR has a root in ``dummied_keys``.

    Conservative on coalesce: if ANY operand of ``${a ?? b}`` has a root
    in ``dummied_keys``, returns True. The alternative (only skip when
    ALL operands are dummied) risks producing placeholder-tainted
    predictions when the resolver happens to pick the dummied operand
    first.
    """
    if not isinstance(node, Mapping):
        return False
    if _node_prompt_cache_touches(node, dummied_chunks):
        return True
    return _node_templates_touch(node, dummied_keys)


def _node_prompt_cache_touches(node: Mapping[str, Any], dummied_chunks: frozenset[str]) -> bool:
    """True iff the node's ``prompt_cache:`` lists any dummied chunk name."""
    if not dummied_chunks:
        return False
    prompt_cache = node.get("prompt_cache")
    if not isinstance(prompt_cache, list):
        return False
    return any(isinstance(name, str) and name in dummied_chunks for name in prompt_cache)


def _node_templates_touch(node: Mapping[str, Any], dummied_keys: frozenset[str]) -> bool:
    """True iff any ``${var}`` ref in the node's IR has a root in ``dummied_keys``.

    Walks every nested string value in the node dict — broader than
    ``_collect_llm_nodes_referencing_path`` (which only inspects
    ``params.prompt``) because cache_key inputs come from any templated
    field on the node (``params``, ``inputs``, ``batch``, nested
    code-block inputs, etc.).
    """
    if not dummied_keys:
        return False
    for text in _walk_strings(node):
        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(text):
            for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
                root = TemplateResolver.extract_root_node_id(operand)
                if root and root in dummied_keys:
                    return True
    return False


def _dummied_cache_chunks(
    workflow_ir: Mapping[str, Any],
    dummied_keys: frozenset[str],
) -> frozenset[str]:
    """Cache chunk names whose ``var`` traces back to a dummied input.

    A ``## Cache`` block declares chunks with ``var: <ref>``; when a
    node's ``prompt_cache:`` references such a chunk, the runtime
    resolves ``var`` against parameters to produce the chunk's content.
    If ``var``'s root is dummied, the chunk content carries the
    placeholder and any node consuming it via ``prompt_cache`` would
    produce a placeholder-tainted cache_key — same outcome as a direct
    template ref to a dummied input.

    Pre-computed once per workflow so the per-node check stays O(1) in
    the number of chunks.
    """
    if not dummied_keys:
        return frozenset()
    cache = workflow_ir.get("cache") if isinstance(workflow_ir, Mapping) else None
    if not isinstance(cache, Mapping):
        return frozenset()
    items = cache.get("items")
    if not isinstance(items, list):
        return frozenset()
    tainted: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        var = item.get("var")
        if not isinstance(var, str):
            continue
        root = TemplateResolver.extract_root_node_id(var)
        if root and root in dummied_keys:
            name = item.get("name")
            if isinstance(name, str):
                tainted.add(name)
    return frozenset(tainted)


def _walk_strings(value: Any) -> Iterable[str]:
    """Yield every string value reachable from ``value`` via dict/list nesting."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for inner in value.values():
            yield from _walk_strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _walk_strings(inner)


@dataclass(frozen=True)
class _PredictScaffold:
    """Per-workflow scaffold reused across all LLM nodes in one workflow."""

    compiled: Any
    shared: dict[str, Any]
    bare_nodes_by_id: dict[str, Any]


def _build_predict_scaffold(
    workflow_ir: Mapping[str, Any],
    params: Mapping[str, Any],
    memo_cache: Any,
    workflow_path: str | None,
) -> _PredictScaffold | None:
    """Compile + planner-shared once per workflow.

    Returns the scaffold, or ``None`` if compile/planner setup fails. The
    unified validator (``_run_full_validation``) runs strictly earlier in
    ``analyze()`` and surfaces structural errors via ``blocking_errors[]``
    /``other_blocking_errors[]``, so this catch only fires for compiler-
    internal failures the validator missed. Those degrade silently with
    a debug log — the agent already has the actionable structural signal
    from the validator pass, and a misleading "workflow failed to compile
    (SchemaValidationError)" Note (the Bug 3 symptom) is worse than no
    Note at all.

    Callers inject ``_pflow_workflow_file`` so relative ``@./file.ext``
    refs resolve against the workflow's own directory instead of CWD —
    matches ``WorkflowValidator._validate_one_child_call``'s pattern.

    Lazy imports keep the analyzer package import-cheap (mirrors
    ``token_estimation.py``'s LiteLLM lazy-import).
    """
    from pflow.execution.plan import create_planner_shared
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow

    compile_params: dict[str, Any] = dict(params)
    if workflow_path is not None:
        compile_params.setdefault("_pflow_workflow_file", str(workflow_path))
    try:
        compiled = compile_workflow(dict(workflow_ir), Registry(), dict(compile_params))
        shared = create_planner_shared(compiled, dict(compile_params), memo_cache, workflow_path)
    except _PREDICTION_RECOVERABLE_EXCEPTIONS as exc:
        logger.debug(
            "predict-stage setup failed for %s: %s",
            workflow_path or "<root>",
            exc,
            exc_info=True,
        )
        return None
    bare_nodes_by_id = _enumerate_compiled_bare_nodes(compiled)
    return _PredictScaffold(compiled=compiled, shared=shared, bare_nodes_by_id=bare_nodes_by_id)


def _predict_node_with_scaffold(
    node: dict[str, Any],
    scaffold: _PredictScaffold,
    workflow_path: str | None,
) -> tuple[str | None, str | None]:
    """Compute the cache_key for one node against a pre-built scaffold.

    Returns ``(cache_key, skip_reason)`` — same shape as ``_predict_node_cache_key``
    but doesn't recompile the workflow. Suitable for the per-workflow loop in
    ``_predict_cache_keys``; tests that want a self-contained per-node call
    use ``_predict_node_cache_key`` instead (it builds its own scaffold).
    """
    from pflow.runtime.engine.plan_node import plan_node

    node_id = str(node.get("id", "?"))
    workflow_label = workflow_path or "<root>"
    target = f"{workflow_label}.{node_id}"
    config = scaffold.compiled.node_configs.get(node_id)
    if config is None:
        return None, _format_fidelity_skip_note(target, "node missing from the compiled workflow (parser/IR mismatch)")
    bare_node = scaffold.bare_nodes_by_id.get(node_id)
    if bare_node is None:
        return None, _format_fidelity_skip_note(target, "node not reachable from the workflow's start")
    try:
        plan = plan_node(bare_node, config, scaffold.shared)
    except Exception as exc:
        logger.debug("plan_node raised for %s.%s", workflow_label, node_id, exc_info=True)
        return None, _format_fidelity_skip_note(target, f"planner raised {type(exc).__name__} during prediction")

    if plan.cache_key is not None:
        return plan.cache_key, None
    if plan.template_exception is not None:
        return None, _format_fidelity_skip_note(
            target,
            "a template reference couldn't be resolved at analysis time (depends on a runtime value)",
        )
    if plan.status == "cache_disabled":
        return None, _format_fidelity_skip_note(target, "this node has `cache: false`", applicable=False)
    return None, _format_fidelity_skip_note(target, f"planner returned no cache key (status={plan.status})")


def _predict_node_cache_key(
    *,
    node: dict[str, Any],
    workflow_ir: Mapping[str, Any],
    params: Mapping[str, Any],
    memo_cache: Any,
    workflow_path: str | None,
) -> tuple[str | None, str | None]:
    """Self-contained per-node prediction — builds its own scaffold.

    Production callers should use ``_predict_cache_keys`` (which hoists the
    compile + shared per workflow, applies dummy padding for partial
    walker params, and skips nodes whose templates touch a padded slot).
    This helper is kept for direct test callers that want a single-node
    prediction without setting up a ``cw_result`` / ``AnalysisContext``;
    they pass real (already-resolved) params, so no padding is needed.
    Returns ``(None, None)`` on scaffold failure — the silent-skip
    contract matches production.
    """
    scaffold = _build_predict_scaffold(workflow_ir, params, memo_cache, workflow_path)
    if scaffold is None:
        return None, None
    return _predict_node_with_scaffold(node, scaffold, workflow_path)


def _enumerate_compiled_bare_nodes(compiled: Any) -> dict[str, Any]:
    """BFS from ``compiled.start_node`` collecting node_id → bare-node."""
    bare_nodes_by_id: dict[str, Any] = {}
    start = getattr(compiled, "start_node", None)
    if start is None:
        return bare_nodes_by_id
    queue: list[Any] = [start]
    while queue:
        bare = queue.pop(0)
        bare_id = getattr(bare, "node_id", None)
        if not isinstance(bare_id, str) or bare_id in bare_nodes_by_id:
            continue
        bare_nodes_by_id[bare_id] = bare
        successors = getattr(bare, "successors", None) or {}
        for succ in successors.values():
            if succ is not None:
                queue.append(succ)
    return bare_nodes_by_id


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
    # Lazy-import to avoid a circular when ``cost_estimation.py`` imports
    # ``PerCallRow`` from this module at module load time.
    from .cost_estimation import CostTier, compute_actually_paid, compute_projections

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
    projections = compute_projections(rows, output_tokens_by_node=output_tokens_by_node, ttl=ttl)
    actually_paid = compute_actually_paid(
        rows,
        trace=ctx.trace if ctx is not None else None,
        edges=edge_child_paths,
        scope_workflow_paths=scope_workflow_paths,
    )

    # Partial flag: actually-paid trace_partial OR projection partial. The
    # renderer uses one boolean to decide whether to mark numbers as
    # incomplete (which can happen on EITHER stream independently).
    partial_cost_usd = actually_paid.tier == CostTier.TRACE_PARTIAL or projections.partial

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
    ``prompt_cache_analysis/CLAUDE.md`` § "Trace coverage is first-class".

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
    from .cost_estimation import get_model_pricing

    grouped: dict[str | None, set[str]] = {}
    for row in rows:
        if row.did_not_execute_in_trace or row.model_is_heterogeneous or not row.model:
            continue
        if get_model_pricing(row.model) is None:
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


__all__ = [
    "analyze",
]
