"""Per-call row construction for prompt-cache analysis."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_config import get_default_workflow_model
from pflow.core.llm_usage import normalize_litellm_usage_tokens
from pflow.core.prompt_cache import deterministic_serialize
from pflow.core.prompt_refs import PromptRef, classify_prompt_refs, first_per_item_position

from ..below_min_tokens_detector import is_likely_below_min_cache
from ..context import AnalysisContext
from ..token_estimation import (
    _estimate_ref_tokens,
    estimate_cacheable_tokens,
    estimate_output_tokens,
    estimate_tokens,
    tokenize_prompt_region,
    tokenize_prompt_region_for_projection,
)
from ..token_estimation import (
    build_shared_store_for_refs as _build_shared_store_for_refs,
)
from ..token_estimation import (
    extract_unique_refs as _extract_unique_refs,
)
from ..types import (
    _BLOCK_ABSENT_BRANCH,
    _BLOCK_BELOW_PROVIDER_MIN,
    _BLOCK_PREWARM_IMAGES,
    _BLOCK_RUNTIME_STRIPPED,
    CacheProjection,
    CacheProjectionComponent,
    CrossWorkflowInputContribution,
    PerCallRow,
    _projection_component,
    _projection_source_confidence,
    _provider_min_state,
    _safe_pct,
    aggregate_projection,
)

logger = logging.getLogger(__name__)


def _template_resolver() -> Any:
    from pflow.runtime.template_resolver import TemplateResolver

    return TemplateResolver


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


def _total_observed_invocations(
    *,
    child_workflow: str,
    child_node_ids: tuple[str, ...],
    call_counts_by_node: dict[tuple[str | None, str], int],
) -> int:
    return sum(call_counts_by_node.get((child_workflow, node_id), 0) for node_id in child_node_ids)


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
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[Any]] | None = None,
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
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[Any]] | None,
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
    cross_workflow_candidates_by_row: dict[tuple[str | None, str], list[Any]] | None,
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
        template_resolver = _template_resolver()
        resolved = template_resolver.resolve_template(prompt, shared)
    except Exception:
        # Defensive: a malformed template shouldn't take down the analyzer.
        logger.debug("template resolution raised on prompt for node %r", node.get("id"), exc_info=True)
        return prompt, True

    if not isinstance(resolved, str):
        # Single-ref templates can return non-string values (e.g. dict).
        from pflow.core.prompt_cache import deterministic_serialize

        resolved = deterministic_serialize(resolved)

    has_unresolved = bool(template_resolver.TEMPLATE_PATTERN.search(resolved))
    return resolved, has_unresolved


def _node_inputs(node: dict[str, Any]) -> Mapping[str, Any] | None:
    """Return an LLM node's ``params.inputs`` mapping, if present."""
    params = node.get("params")
    if not isinstance(params, Mapping):
        return None
    inputs = params.get("inputs")
    return inputs if isinstance(inputs, Mapping) else None


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
