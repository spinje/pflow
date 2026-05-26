"""Per-model capability table for prompt caching (Task 159 DD#32).

Hardcoded per-model min-cache-token thresholds. Used by:
  - ``cache.below-min-predicted`` warning emission (looks up the threshold for the
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
# `cache.below-min-predicted` suggestion will then point agents at that command.
# See .taskmaster/tasks/task_94/research/cache-threshold-cross-reference-from-task-159.md
# for the bidirectional cross-reference plan and design choices.

# Conservative fallback when the model isn't in the table or its provider is
# unrecognized. Per DD#32: pick a value high enough that small/incidental cache
# blocks DON'T silently no-op without a warning. 4096 covers the highest known
# Anthropic minimum and Gemini's Pro-tier explicit-cache minimum (Flash tiers
# are lower and listed explicitly below; the deprecated gemini-1.5-* models are
# actually HIGHER at ~32k and are intentionally under-served here — see the
# Gemini catch-all row).
CONSERVATIVE_FLOOR: int = 4096


CONSERVATIVE_BREAKPOINT_BUDGET: int = 1
"""Conservative breakpoint budget for unknown/non-Anthropic providers.

Anthropic supports up to 4 cache_control breakpoints per request; every other
provider in pflow's matrix (openai, gemini) either ignores cache_control
markers or routes them through a different mechanism that pflow handles as a
single terminal marker. Conservative default is 1 — emit only the terminal
marker on unknown providers to avoid silently exceeding API limits."""

ANTHROPIC_BREAKPOINT_BUDGET: int = 4
"""Anthropic's documented maximum cache_control breakpoints per request.
API returns 400 error if exceeded. See:
https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching"""


@dataclass(frozen=True)
class ModelCapability:
    """Per-model capability row.

    ``provider`` is the ``ProviderInfo.name`` string (e.g. ``"anthropic"``,
    ``"gemini"``, ``"openai"``). ``model_pattern`` is a lowercase bare-model
    prefix (provider prefix stripped) — the bare model id must START WITH this
    pattern for the row to apply. Most-specific (longest) match wins.

    ``min_cache_tokens`` is the threshold in tokens. Below it the provider
    either silently no-ops the cache (OpenAI / Anthropic auto-cache) OR
    HARD-FAILS the request (Gemini explicit ``cachedContents`` returns
    ``BadRequestError``); either way the validator emits
    ``cache.below-min-predicted``. Because the runtime also gates prewarm on
    this value, it must be >= the provider's true minimum — a value set too low
    makes prewarm create a too-small cache and crash the call.
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
    # Gemini minimums per https://ai.google.dev/gemini-api/docs/caching
    # (verified 2026-05-26): Flash-tier 1024, Pro-tier 4096.
    #
    # THIS VALUE IS A CRASH BOUNDARY, not just a recommendation knob. It gates
    # both (a) whether `analyze-cache` recommends caching and (b) whether the
    # runtime fires a prewarm marker — and prewarm creates an EXPLICIT
    # `cachedContents`. If the threshold sits BELOW the provider's true
    # explicit-cache minimum, prewarm builds a too-small cache and Gemini
    # rejects the whole request (`BadRequestError`). So each value must be
    # >= the explicit API minimum; set it as LOW as the provider actually
    # accepts (so caching is recommended wherever it legitimately helps) but
    # NEVER lower. Earlier this was a flat 4096 (DD#32), which over-stated the
    # Flash floor and made `analyze-cache` wrongly tell users a 1024-4096 token
    # Flash prefix "won't cache."
    #
    # Empirical basis (discriminator runs, gemini-2.5-flash, ~1514-token prefix):
    #   - marker stripped (prewarm off): 18/31 calls cache-read (implicit only)
    #   - prewarm on (threshold 1024):   31/31 calls cache-read
    # The marker is accepted at/above 1024 and reliably improves coverage, so
    # Flash's explicit minimum is 1024 (matches the published table).
    #
    # flash-lite is 2048, NOT 1024 — verified 2026-05-26 from a live API error:
    # "Cached content is too small. total_token_count=1221, min_total_token_count=2048"
    # (gemini-2.5-flash-lite). The crash boundary in action: the earlier inferred
    # 1024 broke 27/31 calls. flash-lite is NOT in the published table; 2048
    # comes from ground truth.
    #
    # PREFIX-MATCH NOTE: lookup is longest-prefix-wins, and
    # "gemini-2.5-flash-lite".startswith("gemini-2.5-flash") is True, so
    # flash-lite needs its OWN row or it would inherit the flash 1024 and crash.
    # The same trap is latent for the 3.5 line: a future `gemini-3.5-flash-lite`
    # would inherit 1024 from the `gemini-3.5-flash` prefix below — add an
    # explicit (verified) row before that model ships.
    ModelCapability("gemini", "gemini-2.5-flash-lite", 2048),
    ModelCapability("gemini", "gemini-2.5-flash", 1024),
    # gemini-3.5-flash is documented at 1024 in the same published table as 2.5-flash.
    ModelCapability("gemini", "gemini-3.5-flash", 1024),
    # Catch-all (4096) for Pro-tier (2.5 Pro, 3 Pro Preview) and any
    # unrecognized/future Gemini name. Unverified models route here ON PURPOSE
    # rather than to an optimistic 1024 — e.g. gemini-3-flash-preview (min not
    # published). This UNDER-states the deprecated gemini-1.5-flash/-pro (whose
    # explicit minimum is ~32k), so they would hard-fail prewarm here; that is
    # pre-existing, and they are NOT added at 1024 precisely because the crash
    # boundary above forbids guessing low. Do not add 1.5/2.0-flash rows without
    # a verified minimum.
    ModelCapability("gemini", "", 4096, notes="Gemini Pro / unknown — conservative floor"),
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


def anthropic_models_at_threshold(threshold: int) -> tuple[str, ...]:
    """Anthropic model patterns whose cache minimum equals ``threshold``.

    Wildcard rows are excluded so caller suggestions name concrete model
    families instead of broad provider defaults.
    """
    return tuple(
        cap.model_pattern
        for cap in MODEL_CAPABILITIES
        if cap.provider == "anthropic" and cap.model_pattern and cap.min_cache_tokens == threshold
    )


def get_breakpoint_budget(provider_name: str | None) -> int:
    """Return the maximum cache_control breakpoints supported per request.

    Anthropic: 4 (native multi-breakpoint support).
    All others (openai, gemini, unknown, None): 1 (terminal marker only).
    """
    if provider_name == "anthropic":
        return ANTHROPIC_BREAKPOINT_BUDGET
    return CONSERVATIVE_BREAKPOINT_BUDGET
