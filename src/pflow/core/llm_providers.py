"""Canonical provider metadata for pflow's LLM adapter.

This module is intentionally small and dependency-free. It is imported by
the adapter, reasoning map, and exception diagnostics, so it must not import
from those modules in return.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    """Static metadata for one LiteLLM provider family."""

    name: str
    provider_prefix: str
    bare_prefixes: tuple[str, ...]
    env_var: str


PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo("anthropic", "anthropic/", ("claude-",), "ANTHROPIC_API_KEY"),
    ProviderInfo("openai", "openai/", ("gpt-", "o1", "o3", "o4"), "OPENAI_API_KEY"),
    ProviderInfo("gemini", "gemini/", ("gemini-",), "GEMINI_API_KEY"),
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


def _matches_bare_prefix(name: str, prefix: str) -> bool:
    """Match either exact family names or dash-prefixed model families."""
    if prefix.endswith("-"):
        return name.startswith(prefix)
    return name == prefix or name.startswith(f"{prefix}-")
