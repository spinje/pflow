"""Tests for canonical LLM provider metadata."""

from __future__ import annotations

from pflow.core.llm_providers import detect_provider, normalize_model_name


def test_detect_provider_known_prefixed_models() -> None:
    anthropic = detect_provider("anthropic/claude-sonnet-4-5")
    openai = detect_provider("openai/o4-mini")
    gemini = detect_provider("gemini/gemini-3-flash-preview")
    assert anthropic is not None and anthropic.name == "anthropic"
    assert openai is not None and openai.name == "openai"
    assert gemini is not None and gemini.name == "gemini"


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
