"""Unified detector for prompt-cache content below provider thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_providers import detect_provider


@dataclass(frozen=True)
class BelowMinTokensEvidence:
    """Inputs for analyzer-predicted and runtime-observed detection.

    Analyzer callers fill ``estimated_tokens`` and ``estimated_data_source``.
    Runtime callers opt into observed-tier detection with ``has_observed=True``.
    The explicit flag is load-bearing because runtime usage normalization
    represents missing provider telemetry as zeroes.
    """

    node_id: str
    model: str
    declared_prompt_cache: list[str]
    estimated_tokens: int | None = None
    estimated_data_source: str | None = None
    has_observed: bool = False
    observed_creation_tokens: int = 0
    observed_read_tokens: int = 0


@dataclass(frozen=True)
class BelowMinTokensFinding:
    """One finding shape for both analyzer and runtime drivers."""

    node_id: str
    model: str
    min_tokens: int
    evidence_kind: Literal["predicted", "observed"]
    cacheable_tokens: int
    provider_note: str


def detect(evidence: BelowMinTokensEvidence) -> BelowMinTokensFinding | None:
    """Return a below-minimum finding when supplied evidence proves one."""
    if not evidence.declared_prompt_cache or not evidence.model:
        return None

    threshold = get_min_cache_tokens(evidence.model)
    provider_note = _provider_note(evidence.model)

    if evidence.has_observed:
        observed_total = evidence.observed_creation_tokens + evidence.observed_read_tokens
        if observed_total > 0:
            return None
        return BelowMinTokensFinding(
            node_id=evidence.node_id,
            model=evidence.model,
            min_tokens=threshold,
            evidence_kind="observed",
            cacheable_tokens=0,
            provider_note=provider_note,
        )

    if evidence.estimated_tokens is None or evidence.estimated_tokens <= 0:
        return None
    if evidence.estimated_data_source == "trace":
        return None
    if evidence.estimated_tokens >= threshold:
        return None
    return BelowMinTokensFinding(
        node_id=evidence.node_id,
        model=evidence.model,
        min_tokens=threshold,
        evidence_kind="predicted",
        cacheable_tokens=evidence.estimated_tokens,
        provider_note=provider_note,
    )


def _provider_note(model: str) -> str:
    provider = detect_provider(model)
    if provider is None:
        return ""
    if provider.name == "anthropic":
        return "cache_control markers will silently no-op at the provider"
    if provider.name == "gemini":
        return (
            "explicit `cachedContents` won't fire, but Gemini's automatic "
            "implicit cache may still apply for stable prefixes"
        )
    return ""
