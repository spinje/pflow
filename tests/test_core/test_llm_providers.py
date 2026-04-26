"""Tests for canonical LLM provider metadata."""

from __future__ import annotations

from pflow.core.llm_providers import (
    PROVIDERS,
    detect_provider,
    extract_provider_prefix,
    normalize_model_name,
)


def test_detect_provider_known_prefixed_models() -> None:
    anthropic = detect_provider("anthropic/claude-sonnet-4-5")
    openai = detect_provider("openai/o4-mini")
    gemini = detect_provider("gemini/gemini-3-flash-preview")
    assert anthropic is not None and anthropic.name == "anthropic"
    assert openai is not None and openai.name == "openai"
    assert gemini is not None and gemini.name == "gemini"


def test_provider_env_vars_canonical_first() -> None:
    """Each provider's env_vars tuple must be non-empty with the canonical first.

    Gemini specifically must include both GEMINI_API_KEY (canonical, matches
    the provider prefix for naming consistency) and GOOGLE_API_KEY (the
    alias LiteLLM checks first in its Gemini auth path).
    """
    by_name = {p.name: p for p in PROVIDERS}
    assert by_name["anthropic"].env_vars == ("ANTHROPIC_API_KEY",)
    assert by_name["openai"].env_vars == ("OPENAI_API_KEY",)
    assert by_name["gemini"].env_vars == ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    for provider in PROVIDERS:
        assert provider.env_vars  # non-empty


def test_detect_provider_known_bare_models() -> None:
    anthropic = detect_provider("claude-sonnet-4-5")
    openai = detect_provider("o4-mini")
    gemini = detect_provider("gemini-2.5-pro")
    assert anthropic is not None and anthropic.name == "anthropic"
    assert openai is not None and openai.name == "openai"
    assert gemini is not None and gemini.name == "gemini"


def test_openrouter_anthropic_path_is_not_classified_as_anthropic() -> None:
    assert detect_provider("openrouter/anthropic/claude-sonnet-4-5") is None


def test_normalize_model_name_uses_registry() -> None:
    assert normalize_model_name("o4-mini") == "openai/o4-mini"
    assert normalize_model_name("claude-sonnet-4-5") == "anthropic/claude-sonnet-4-5"
    assert normalize_model_name("openrouter/anthropic/claude-sonnet-4-5") == ("openrouter/anthropic/claude-sonnet-4-5")


def test_extract_provider_prefix_returns_first_segment() -> None:
    """Used by exception diagnostics for unknown providers — extracts the
    LiteLLM routing prefix without consulting the registry."""
    assert extract_provider_prefix("together_ai/llama-3-70b") == "together_ai"
    assert extract_provider_prefix("mistral/mistral-large") == "mistral"
    # Multi-segment prefixes (OpenRouter) take only the first segment.
    assert extract_provider_prefix("openrouter/anthropic/claude-sonnet-4-5") == "openrouter"


def test_extract_provider_prefix_returns_none_for_bare_or_empty() -> None:
    assert extract_provider_prefix("gpt-4o-mini") is None
    assert extract_provider_prefix("") is None
    assert extract_provider_prefix(None) is None
