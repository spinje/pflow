"""Map unified reasoning params to provider-specific reasoning option kwargs.

Replaces the live `model.Options.model_fields` introspection that the previous
LLMNode used (against Simon Willison's `llm` library plugins). LiteLLM does not
expose an equivalent introspection contract, so capabilities are detected by
model-name string sniffing.

Output shape matches what the previous llm-library code path produced, e.g.
``{"thinking": True, "thinking_budget": 1024}`` for Anthropic. The
LLM adapter (`pflow.core.llm_client`) translates these kwargs to LiteLLM's
native shape (``{"thinking": {"type": "enabled", "budget_tokens": N}}``) at
the API boundary. Keeping the translation in the adapter localizes provider
quirks; this map only decides "which kwargs does this model accept".

CRITICAL: Anthropic Opus 4.5 supports `thinking_effort`, `thinking`, AND
`thinking_budget`. `thinking_effort` MUST be checked first — getting this
wrong silently degrades Opus 4.5 reasoning. This precedence is preserved
from the previous `nodes/llm/llm.py::_map_effort` implementation.
"""

from __future__ import annotations

from typing import Any

from pflow.core.llm_providers import detect_provider, model_name_without_provider

# OpenRouter-style effort-to-token-budget ratios. Moved verbatim from the
# previous nodes/llm/llm.py:22-32. Five levels intentional (matches what
# pflow accepts as `reasoning_effort` parameter input).
EFFORT_RATIOS: dict[str, float] = {
    "xhigh": 0.95,
    "high": 0.80,
    "medium": 0.50,
    "low": 0.20,
    "minimal": 0.10,
}

# Default base for token budget calculation when max_tokens is not set.
# Moved verbatim from the previous nodes/llm/llm.py:32.
DEFAULT_MAX_TOKENS_BASE = 16000


def _detect_capabilities(model: str) -> set[str]:
    """Return the set of reasoning option keys this model accepts.

    Mirrors what `model.Options.model_fields` would have exposed under the
    previous llm-library + llm-anthropic/llm-gemini/llm-openai plugin path.
    Detection is by model-name string sniffing (the same approach
    `registry/smart_filter.py` uses for Gemini variant heuristics).

    The returned set drives `_map_effort` and `_map_direct_budget` dispatch
    below — same logic as the previous implementation.
    """
    provider = detect_provider(model)

    # Anthropic Opus 4.5 — supports thinking_effort (precedence!), plus
    # thinking and thinking_budget for direct-budget callers.
    if provider is not None and provider.name == "anthropic":
        provider_model = model_name_without_provider(model, provider)
        if "claude-opus-4-5" in provider_model or "claude-opus-4.5" in provider_model:
            return {"thinking_effort", "thinking", "thinking_budget"}

        # Other Anthropic models (Sonnet 4.x, Opus 4.0/4.1, older Sonnet,
        # Haiku, etc.) — extended thinking via thinking + thinking_budget.
        return {"thinking", "thinking_budget"}

    if provider is not None and provider.name == "gemini":
        provider_model = model_name_without_provider(model, provider)
        # Gemini 3 family — categorical thinking_level.
        if "gemini-3" in provider_model:
            return {"thinking_level"}

        # Gemini 2.5 (non-lite) — token-budget thinking.
        # Lite variants (gemini-2.5-flash-lite) have no thinking support; the
        # `lite` substring check matches existing pflow heuristic in
        # registry/smart_filter.py:178.
        if "gemini-2.5" in provider_model and "lite" not in provider_model:
            return {"thinking_budget"}

        # Gemini 2.5 lite, gemini-2.0-*, gemini-1.5-*, etc. — no reasoning.
        return set()

    if provider is not None and provider.name == "openai":
        provider_model = model_name_without_provider(model, provider)
        # OpenAI reasoning models: gpt-5* family, o1*, o3*, o4*. Preserves
        # the previous llm-openai plugin's contract that exposed
        # reasoning_effort and reasoning_max_tokens as Options fields.
        if provider_model.startswith("gpt-5") or _matches_openai_o_family(provider_model):
            return {"reasoning_effort", "reasoning_max_tokens"}

        # GPT-4* and unknown OpenAI models — no reasoning support.
        return set()

    # Unknown providers — no reasoning support until explicitly modeled.
    return set()


def _matches_openai_o_family(model_name: str) -> bool:
    """Return true for known OpenAI o-series reasoning model families."""
    return any(model_name == family or model_name.startswith(f"{family}-") for family in ("o1", "o3", "o4"))


def _map_direct_budget(option_fields: set[str], reasoning_max_tokens: int) -> dict[str, Any]:
    """Map reasoning_max_tokens to provider-specific token budget param.

    Logic ported verbatim from the previous `nodes/llm/llm.py::_map_direct_budget`.
    """
    if "thinking_budget" in option_fields:
        kwargs: dict[str, Any] = {"thinking_budget": reasoning_max_tokens}
        if "thinking" in option_fields:
            kwargs["thinking"] = True
        return kwargs
    if "reasoning_max_tokens" in option_fields:
        return {"reasoning_max_tokens": reasoning_max_tokens}
    return {}


def _map_effort(option_fields: set[str], effort: str, max_tokens: int | None) -> dict[str, Any]:
    """Map effort level string to provider-specific reasoning params.

    Logic ported verbatim from the previous `nodes/llm/llm.py::_map_effort`.

    Provider detection order matters — Anthropic Opus 4.5 has thinking_effort,
    thinking, AND thinking_budget, so thinking_effort must be checked first.
    """
    # Anthropic Opus 4.5 — thinking_effort natively
    if "thinking_effort" in option_fields:
        mapped = {"xhigh": "high", "minimal": "low"}.get(effort, effort)
        return {"thinking_effort": mapped}
    # OpenAI / OpenRouter — reasoning_effort natively
    if "reasoning_effort" in option_fields:
        return {"reasoning_effort": effort}
    # Gemini 3 — thinking_level natively
    if "thinking_level" in option_fields:
        mapped = {"xhigh": "high"}.get(effort, effort)
        return {"thinking_level": mapped}
    # Anthropic older / Gemini 2.5 — needs token budget calculation
    if "thinking_budget" in option_fields:
        base = max_tokens or DEFAULT_MAX_TOKENS_BASE
        ratio = EFFORT_RATIOS.get(effort, 0.50)
        budget = max(min(int(base * ratio), 128000), 1024)
        kwargs: dict[str, Any] = {"thinking_budget": budget}
        if "thinking" in option_fields:
            kwargs["thinking"] = True
        return kwargs
    # Thinking-only (no budget control)
    if "thinking" in option_fields:
        return {"thinking": True}
    return {}


def map_reasoning_options(
    model: str,
    reasoning_effort: str | None,
    reasoning_max_tokens: int | None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Return the reasoning option kwargs for a given model and intent.

    The output shape matches what the previous llm-library code path
    produced (e.g., ``{"thinking": True, "thinking_budget": 1024}`` for
    Anthropic). The LLM adapter is responsible for any further translation
    to LiteLLM-native shapes.

    Args:
        model: Model identifier, e.g. ``"anthropic/claude-opus-4-5"``,
            ``"gpt-5-mini"``, ``"gemini-2.5-pro"``. Provider detection
            uses substring matching on the lowercased name.
        reasoning_effort: One of ``xhigh/high/medium/low/minimal/none``,
            or ``None`` for default.
        reasoning_max_tokens: Direct token budget. Mutually exclusive with
            ``reasoning_effort`` — when both are set, this takes precedence.
        max_tokens: The max response tokens, used as base for the budget
            formula when only effort is given on a budget-style model.

    Returns:
        Dict of kwargs to merge into the LLM call. Empty dict when no
        reasoning option applies (model doesn't support it, or no input
        provided).
    """
    if not reasoning_effort and reasoning_max_tokens is None:
        return {}

    option_fields = _detect_capabilities(model)
    if not option_fields:
        return {}

    # Direct token budget takes precedence over effort
    if reasoning_max_tokens is not None:
        return _map_direct_budget(option_fields, reasoning_max_tokens)

    effort = reasoning_effort.lower()  # type: ignore[union-attr]

    if effort == "none":
        if "thinking" in option_fields:
            return {"thinking": False}
        if "thinking_budget" in option_fields:
            return {"thinking_budget": 0}
        if "thinking_level" in option_fields:
            # Gemini 3 has no off-switch; "minimal" is the lowest equivalent.
            return {"thinking_level": "minimal"}
        return {}

    return _map_effort(option_fields, effort, max_tokens)
