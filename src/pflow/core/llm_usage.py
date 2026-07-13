"""Shared LLM usage normalization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

InputTokenAccounting = Literal["total_includes_cache", "split_cache_fields"]


@dataclass(frozen=True)
class NormalizedLiteLLMUsage:
    input_tokens: int
    uncached_input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    input_token_accounting: InputTokenAccounting
    # ``True`` iff the source provider returned at least one cache-token
    # field. ``False`` means absent telemetry — distinct from "provider
    # reported zero." Consumers that gate observed-tier cache analysis
    # (e.g. ``cache.below-min-predicted`` runtime emission) MUST check this
    # before treating zero counts as evidence the cache failed to fire.
    has_cache_telemetry: bool


def normalize_litellm_usage_tokens(
    *,
    prompt_tokens: int | None,
    cache_creation_input_tokens: int | None = None,
    cache_read_input_tokens: int | None = None,
) -> NormalizedLiteLLMUsage:
    """Normalize LiteLLM prompt-token accounting to pflow's trace contract.

    pflow treats ``input_tokens`` as total prompt/input tokens, including any
    cached prefix. LiteLLM sometimes reports that total directly and sometimes
    reports only the uncached split with cache fields alongside it. The stable
    rule is value-based:

    - ``prompt_tokens >= cache_creation + cache_read`` means prompt_tokens is
      already total.
    - ``prompt_tokens < cache_creation + cache_read`` means prompt_tokens is
      uncached-only, so the cache split is added back.

    Cache-telemetry presence is derived from whether either cache field came
    in non-None — see ``has_cache_telemetry`` field.
    """
    prompt = _non_negative_int(prompt_tokens)
    creation = _non_negative_int(cache_creation_input_tokens)
    read = _non_negative_int(cache_read_input_tokens)
    cacheable = creation + read
    has_cache_telemetry = cache_creation_input_tokens is not None or cache_read_input_tokens is not None

    if prompt >= cacheable:
        input_tokens = prompt
        uncached = max(0, prompt - cacheable)
        accounting: InputTokenAccounting = "total_includes_cache"
    else:
        input_tokens = prompt + cacheable
        uncached = prompt
        accounting = "split_cache_fields"

    return NormalizedLiteLLMUsage(
        input_tokens=input_tokens,
        uncached_input_tokens=uncached,
        cache_creation_input_tokens=creation,
        cache_read_input_tokens=read,
        input_token_accounting=accounting,
        has_cache_telemetry=has_cache_telemetry,
    )


def input_token_total(llm_call: Mapping[str, Any]) -> tuple[int, int]:
    """Return ``(input_tokens, cache_read_tokens)`` for one recorded LLM call.

    The read-side counterpart of :func:`normalize_litellm_usage_tokens`: that
    normalizes a provider's raw usage at WRITE time, this reads pflow's
    cache-INCLUSIVE ``input_tokens`` total back off a trace ``llm_call`` record
    (falling back to ``prompt_tokens`` for older traces). Every producer
    (LLMNode, AgentNode) writes ``input_tokens`` cache-inclusive, so no
    reader does render-time cache arithmetic. ``cache_read`` is returned
    alongside only for the cache-hit-% display. The trailing ``or 0`` guards a
    legacy entry that stored an explicit ``None`` instead of omitting the field.
    """
    total_in = llm_call.get("input_tokens", llm_call.get("prompt_tokens", 0)) or 0
    cache_read = llm_call.get("cache_read_input_tokens", 0) or 0
    return total_in, cache_read


def _non_negative_int(value: int | None) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0
