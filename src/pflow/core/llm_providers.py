"""Canonical provider metadata for pflow's LLM adapter.

This module is intentionally small and dependency-free. It is imported by
the adapter, reasoning map, and exception diagnostics, so it must not import
from those modules in return.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    """Static metadata for one LiteLLM provider family.

    ``env_vars`` lists every API-key environment variable LiteLLM accepts
    for this provider, canonical first. Multiple entries reflect the
    provider's actual aliasing (e.g. LiteLLM's Gemini path checks both
    ``GEMINI_API_KEY`` and ``GOOGLE_API_KEY``); the canonical entry is
    what pflow surfaces as the recommended setup target.

    Cache-token accounting is intentionally NOT represented here. LiteLLM's
    response shape can vary by provider version and trace vintage; pflow
    normalizes usage with ``core.llm_usage.normalize_litellm_usage_tokens()``
    at the adapter/analyzer boundary instead of trusting static provider
    metadata for arithmetic.
    """

    name: str
    provider_prefix: str
    bare_prefixes: tuple[str, ...]
    env_vars: tuple[str, ...]


PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo("anthropic", "anthropic/", ("claude-",), ("ANTHROPIC_API_KEY",)),
    ProviderInfo("openai", "openai/", ("gpt-", "o1", "o3", "o4"), ("OPENAI_API_KEY",)),
    # LiteLLM's own env lookup checks GOOGLE_API_KEY first then
    # GEMINI_API_KEY (see litellm/llms/gemini/common_utils.py) — the reverse
    # of this canonical-first order. pflow neutralizes that by resolving the
    # key itself (llm_config.resolve_provider_api_key) and passing it
    # explicitly to litellm.completion, so this tuple's order is the one
    # that actually governs which key a call uses.
    ProviderInfo("gemini", "gemini/", ("gemini-",), ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
)


def detect_provider(model: str | None) -> ProviderInfo | None:
    """Return provider metadata for known pflow model prefixes.

    Prefixed model identifiers must start with the provider prefix exactly.
    A model such as ``openrouter/anthropic/claude-sonnet-4-5`` is therefore
    not classified as Anthropic; it belongs to OpenRouter, whose behavior
    should be handled explicitly when pflow supports it.
    """
    if not model:
        return None

    name = model.lower()
    for provider in PROVIDERS:
        if name.startswith(provider.provider_prefix):
            return provider

    if "/" in name:
        return None

    for provider in PROVIDERS:
        if any(_matches_bare_prefix(name, prefix) for prefix in provider.bare_prefixes):
            return provider
    return None


def normalize_model_name(model: str) -> str:
    """Add a provider prefix to known bare model names."""
    if "/" in model:
        return model
    provider = detect_provider(model)
    if provider is None:
        return model
    normalized = provider.provider_prefix + model
    return normalized


def model_name_without_provider(model: str, provider: ProviderInfo) -> str:
    """Return the model id after the provider prefix when present."""
    name = model.lower()
    if name.startswith(provider.provider_prefix):
        return name.removeprefix(provider.provider_prefix)
    return name


def extract_provider_prefix(model: str | None) -> str | None:
    """Return the LiteLLM provider prefix for a slash-prefixed model.

    The prefix is the segment before the first slash — what LiteLLM uses
    to route to a provider handler (e.g. ``together_ai`` from
    ``together_ai/llama-3-70b``). Returns ``None`` for bare model names
    or absent input. Distinct from ``detect_provider``: this primitive
    does NOT consult the registry; it just parses the string. Used for
    best-effort env-var derivation when a model's provider isn't in
    pflow's registry but we still want to give a user actionable
    remediation.
    """
    if not model or "/" not in model:
        return None
    return model.split("/", 1)[0]


def _matches_bare_prefix(name: str, prefix: str) -> bool:
    """Match either exact family names or dash-prefixed model families."""
    if prefix.endswith("-"):
        return name.startswith(prefix)
    return name == prefix or name.startswith(f"{prefix}-")
