"""Shared PerCallRow construction helpers for cache-analysis tests."""

from __future__ import annotations

from typing import Any

from pflow.core.prompt_cache_analysis.types import (
    CacheProjection,
    CacheProjectionComponent,
    PerCallRow,
    aggregate_projection,
    not_applicable_projection,
)


def make_cache_projection(
    *,
    tokens_estimated: int | None,
    input_tokens_estimated: int | None,
    data_source: str,
    purpose: str,
    action: str = "none",
    actionability: str = "direct_edit",
    confidence: str = "exact",
    meets_provider_min: bool | None = None,
    provider_min_tokens: int | None = None,
    blocked_reason: str = "",
    affects_cost_projection: bool = False,
    diagnostic_ids: tuple[str, ...] = (),
) -> CacheProjection:
    """Build a projection object explicitly instead of relying on row synthesis."""
    component = CacheProjectionComponent(
        tokens_estimated=tokens_estimated,
        data_source=data_source,
        ratio_pct=(
            round(tokens_estimated / input_tokens_estimated * 100)
            if tokens_estimated is not None and input_tokens_estimated
            else None
        ),
        action=action,
        actionability=actionability,
        confidence=confidence,
        meets_provider_min=meets_provider_min,
        provider_min_tokens=provider_min_tokens,
        blocked_reason=blocked_reason,
        affects_cost_projection=affects_cost_projection,
        diagnostic_ids=diagnostic_ids,
    )
    return aggregate_projection((component,), purpose=purpose, input_tokens=input_tokens_estimated)


def make_per_call_row(
    *,
    node_path: str = "node",
    model: str = "anthropic/claude-sonnet-4-5",
    is_batch: bool = False,
    batch_size_estimated: int | None = None,
    input_tokens_estimated: int = 100,
    cacheable_tokens_estimated: int | None = None,
    cache_ratio_pct: int | None = None,
    data_source: str = "memo",
    declared_prompt_cache: list[str] | None = None,
    cacheable_data_source: str = "unavailable",
    workflow_path: str | None = None,
    cache_configured: CacheProjection | None = None,
    cache_active: CacheProjection | None = None,
    cache_ready: CacheProjection | None = None,
    cache_opportunity: CacheProjection | None = None,
    cached_now_tokens_estimated: int | None = None,
    **kwargs: Any,
) -> PerCallRow:
    """Build a PerCallRow in the projection-object shape.

    This replaces ad-hoc ``PerCallRow(cacheable_tokens_estimated=...)`` test
    constructors that previously relied on ``__post_init__`` to synthesize
    projection fields from the legacy scalar.

    Tests that assert rendered ``ready``, ``upside``, ``cached_now``, or
    ``ratio`` cells must pass explicit projection objects. The defaults are
    intentionally not-applicable so the helper cannot reintroduce the bridge
    this phase removes.
    """
    return PerCallRow(
        node_path=node_path,
        model=model,
        is_batch=is_batch,
        batch_size_estimated=batch_size_estimated,
        input_tokens_estimated=input_tokens_estimated,
        cacheable_tokens_estimated=cacheable_tokens_estimated,
        cache_ratio_pct=cache_ratio_pct,
        data_source=data_source,
        declared_prompt_cache=declared_prompt_cache,
        cacheable_data_source=cacheable_data_source,
        workflow_path=workflow_path,
        cache_configured=cache_configured or not_applicable_projection(),
        cache_active=cache_active or not_applicable_projection(),
        cache_ready=cache_ready or not_applicable_projection(),
        cache_opportunity=cache_opportunity or not_applicable_projection(),
        cached_now_tokens_estimated=cached_now_tokens_estimated,
        **kwargs,
    )
