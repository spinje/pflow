"""Detectors for prompt-cache content below provider thresholds.

Two analyzer-facing detectors share the provider-min lookup and
provider-note helper:

* ``detect`` (declared cache): fires when a node has ``prompt_cache:`` AND
  the declared chunks resolve to bytes below the provider's minimum.
* ``detect_batch_prewarm_below_min`` (prewarm without declared cache):
  fires when a batch node has ``prewarm: true`` AND the static prefix
  before the first per-item ref is below the provider's minimum.

The two paths differ in remediation: declared-cache callers grow the
``## Cache`` block or drop ``prompt_cache:``; prewarm callers restructure
the prompt prefix or remove ``- prewarm: true``. Keeping the detectors
separate keeps each finding's agent-facing prose honest.
"""

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


@dataclass(frozen=True)
class BatchPrewarmBelowMinEvidence:
    """Inputs for analyzer-predicted prewarm-prefix-too-short detection."""

    node_id: str
    model: str
    prefix_tokens: int
    batch_alias: str


@dataclass(frozen=True)
class BatchPrewarmBelowMinFinding:
    """Finding for ``cache.batch-prewarm-below-min``.

    Analyzer-only — the runtime cannot observe the byte boundary between
    the static prefix and the first per-item reference, so there is no
    observed counterpart.
    """

    node_id: str
    model: str
    min_tokens: int
    prefix_tokens: int
    batch_alias: str
    provider_note: str


def is_below_min_cache(model: str | None, tokens: int | None) -> bool:
    """Return True when populated token evidence is below the provider minimum.

    "Honest unmeasurable" variant — returns False when the model is None or
    empty (heterogeneous-batch rows carry ``model=""``). Use at CLAIM-type
    emission sites (e.g. ``cache.below-min-predicted``) where emitting a
    "below min" claim against an unknown model would render an awkward
    message and risk false claims.
    """
    if not model or tokens is None:
        return False
    return tokens < get_min_cache_tokens(model)


def detect(evidence: BelowMinTokensEvidence) -> BelowMinTokensFinding | None:
    """Return a below-minimum finding when supplied evidence proves one."""
    if not evidence.declared_prompt_cache or not evidence.model:
        return None

    threshold = get_min_cache_tokens(evidence.model)
    note = provider_note(evidence.model)

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
            provider_note=note,
        )

    if evidence.estimated_tokens is None or evidence.estimated_tokens <= 0:
        return None
    if evidence.estimated_data_source == "trace":
        return None
    if not is_below_min_cache(evidence.model, evidence.estimated_tokens):
        return None
    return BelowMinTokensFinding(
        node_id=evidence.node_id,
        model=evidence.model,
        min_tokens=threshold,
        evidence_kind="predicted",
        cacheable_tokens=evidence.estimated_tokens,
        provider_note=note,
    )


def detect_batch_prewarm_below_min(
    evidence: BatchPrewarmBelowMinEvidence,
) -> BatchPrewarmBelowMinFinding | None:
    """Return a finding when a prewarm batch's static prefix is below the
    provider minimum.

    Caller contract: only invoke with ``prefix_tokens > 0`` — the zero-prefix
    case is owned by ``cache.prewarm-no-prefix`` and conflating them would
    double-emit. The detector still defends against bad callers by returning
    ``None`` for non-positive prefixes.
    """
    if not evidence.model:
        return None
    if evidence.prefix_tokens <= 0:
        return None
    threshold = get_min_cache_tokens(evidence.model)
    if not is_below_min_cache(evidence.model, evidence.prefix_tokens):
        return None
    return BatchPrewarmBelowMinFinding(
        node_id=evidence.node_id,
        model=evidence.model,
        min_tokens=threshold,
        prefix_tokens=evidence.prefix_tokens,
        batch_alias=evidence.batch_alias,
        provider_note=provider_note(evidence.model),
    )


def provider_note(model: str) -> str:
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
