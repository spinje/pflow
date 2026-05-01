"""Per-model capability table for prompt caching (Task 159 DD#32).

Hardcoded per-model min-cache-token thresholds. Used by:
  - ``cache.below-min-tokens`` warning emission (looks up the threshold for the
    node's model).
  - Auto batch-prefix detection (skips when prefix is below threshold).

This module is intentionally small and dependency-free. It is imported by the
analyzer, validator, and adapter, so it must not import from those modules in
return — same constraint as ``llm_providers.py``. LiteLLM's ``model_cost`` dict
carries some of this data (``supports_prompt_caching``, the per-token costs)
but per-model min-token coverage is uneven; v1 hardcodes; v1.x may wrap LiteLLM.

Lookup matching is by exact bare-model prefix in declaration order; the
longest matching pattern wins so a future model id like ``claude-sonnet-4-5-20240620``
correctly routes to the ``claude-sonnet-4-5`` family threshold (1024) rather than
the broader ``claude-sonnet-`` family if both are registered.

Unknown / unprefixed models fall back to the conservative floor (``CONSERVATIVE_FLOOR``).
This is preferred over raising — the lookup is on the cache-warning hot path
and a missing model name should degrade visibly (warning still fires) rather
than crash compilation.
"""

from __future__ import annotations

from dataclasses import dataclass

from pflow.core.llm_providers import detect_provider, model_name_without_provider

# Task 94 cross-reference (Display Available LLM Models) — when Task 94 ships
# `pflow llm list` with capability filters, the table below becomes the data
# source for `--min-cache-tokens=<N>` filtering. The analyzer's
# `cache.below-min-tokens` suggestion will then point agents at that command.
# See .taskmaster/tasks/task_94/research/cache-threshold-cross-reference-from-task-159.md
# for the bidirectional cross-reference plan and design choices.

# Conservative fallback when the model isn't in the table or its provider is
# unrecognized. Per DD#32: pick a value high enough that small/incidental cache
# blocks DON'T silently no-op without a warning. 4096 covers the highest known
# Anthropic minimum and matches Gemini's explicit-cache requirement.
CONSERVATIVE_FLOOR: int = 4096


@dataclass(frozen=True)
class ModelCapability:
    """Per-model capability row.

    ``provider`` is the ``ProviderInfo.name`` string (e.g. ``"anthropic"``,
    ``"gemini"``, ``"openai"``). ``model_pattern`` is a lowercase bare-model
    prefix (provider prefix stripped) — the bare model id must START WITH this
    pattern for the row to apply. Most-specific (longest) match wins.

    ``min_cache_tokens`` is the threshold in tokens; rendered prompt-cache
    content below this value will silently no-op at the provider, so the
    validator emits ``cache.below-min-tokens``.
    """

    provider: str
    model_pattern: str
    min_cache_tokens: int
    notes: str = ""


# Per-version Anthropic minimums per DD#32. Order is irrelevant for lookup
# semantics (most-specific match wins) but we keep them grouped by threshold
# for human readability.
MODEL_CAPABILITIES: tuple[ModelCapability, ...] = (
    # Anthropic 1024-token family.
    ModelCapability("anthropic", "claude-sonnet-4-5", 1024),
    ModelCapability("anthropic", "claude-opus-4-1", 1024),
    ModelCapability("anthropic", "claude-opus-4", 1024),  # base 4 (not 4-1, 4-5, ...).
    ModelCapability("anthropic", "claude-sonnet-4", 1024),  # base 4.
    ModelCapability("anthropic", "claude-sonnet-3-7", 1024),
    # Anthropic 2048-token family.
    ModelCapability("anthropic", "claude-sonnet-4-6", 2048),
    ModelCapability("anthropic", "claude-haiku-3-5", 2048),
    # Anthropic 4096-token family (newest models).
    ModelCapability("anthropic", "claude-opus-4-7", 4096),
    ModelCapability("anthropic", "claude-opus-4-6", 4096),
    ModelCapability("anthropic", "claude-opus-4-5", 4096),
    ModelCapability("anthropic", "claude-haiku-4-5", 4096),
    # OpenAI auto-cache fires at 1024 across all GPT/o-series families.
    # Per DD#32; ``prompt_cache_retention`` controls TTL but not the threshold.
    ModelCapability("openai", "", 1024, notes="OpenAI auto-cache threshold"),
    # Gemini explicit ``cachedContents`` requires ~4k tokens. The implicit
    # path fires at lower thresholds (free, automatic) but is independent of
    # the cache_control marker pflow emits — so the threshold used by
    # ``cache.below-min-tokens`` reflects the EXPLICIT path's requirement.
    ModelCapability("gemini", "", 4096, notes="Gemini explicit cachedContents minimum"),
)


def get_min_cache_tokens(model: str | None) -> int:
    """Return the minimum-cache-token threshold for ``model``.

    Lookup strategy:
      1. ``detect_provider(model)`` to normalize bare-name routing.
      2. Iterate ``MODEL_CAPABILITIES`` for rows matching the provider.
      3. Among those, pick the row whose ``model_pattern`` is the longest
         prefix of the bare model name (most-specific match wins).
      4. Fall back to ``CONSERVATIVE_FLOOR`` if no row matches OR provider is
         unrecognized OR ``model`` is empty / ``None``.

    The conservative-floor fallback is intentional: a missing or future model
    name should produce visible cache warnings, not silent no-ops. Returning
    0 (or raising) would be the silent-stale-cache class.
    """
    if not model:
        return CONSERVATIVE_FLOOR

    provider = detect_provider(model)
    if provider is None:
        return CONSERVATIVE_FLOOR

    bare = model_name_without_provider(model, provider)
    best_pattern_len = -1
    best_threshold: int | None = None
    for cap in MODEL_CAPABILITIES:
        if cap.provider != provider.name:
            continue
        if not bare.startswith(cap.model_pattern):
            continue
        if len(cap.model_pattern) > best_pattern_len:
            best_pattern_len = len(cap.model_pattern)
            best_threshold = cap.min_cache_tokens

    if best_threshold is not None:
        return best_threshold
    return CONSERVATIVE_FLOOR
