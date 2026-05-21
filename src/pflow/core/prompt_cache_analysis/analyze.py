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
from pflow.core.cache_ttl import parse_cache_ttl
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_config import get_default_workflow_model
from pflow.core.llm_providers import normalize_model_name
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
from .context import AnalysisContext, _normalize_empty
from .cross_workflow import CrossWorkflowEdge, walk_cross_workflow
from .padding_advisor import PaddingCandidate, compute_padding_advisories
from .stages.discrepancy import (
    _attach_predicted_cache_keys,
    _emit_discrepancy_diagnostics,
    _format_dynamic_batches_note,
)
from .stages.summary import (
    _aggregate_confidence,
    _build_summary,
    _filter_trace_dependent_warnings,
    _format_workflow_run_command,
    _maybe_append_gemini_note,
    _trace_coverage_for_rows,
)
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
    CacheAnalysis,
    CacheProjection,
    CacheProjectionComponent,
    CrossWorkflowInputContribution,
    PerCallRow,
    PerNodeThresholdEntry,
    SubWorkflowRollup,
    SubWorkflowRollupEntry,
    SuggestedBlock,
    SuggestedBlockChunk,
    TraceExecutionIndex,
    _projection_component,
    _projection_source_confidence,
    _provider_min_state,
    _safe_pct,
    aggregate_projection,
    invocation_count_for,
)
from .warning_catalog import make_diagnostic

logger = logging.getLogger(__name__)

_SUGGESTED_BLOCK_ACTIONABLE: str = "actionable"
_SUGGESTED_BLOCK_BELOW_THRESHOLD: str = "below_threshold"
_SUGGESTED_BLOCK_EVIDENCE_INCOMPLETE: str = "evidence_incomplete"
_SUGGESTED_BLOCK_INSUFFICIENT_NODES: str = "insufficient_nodes"
_PARENT_PROSE_PREVIEW_LIMIT = 40


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
    from .stages.cross_workflow import _build_cross_workflow_findings

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


__all__ = [
    "analyze",
]
