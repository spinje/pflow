"""Tests for ``core/llm_capabilities.py`` — per-model min-cache-token thresholds.

Per spec DD#32, Anthropic minimums are version-specific (1024 / 2048 / 4096
depending on family); Gemini explicit-cache uses ~4k; OpenAI auto-caches at 1024.
Unknown / unprefixed models fall back to the conservative floor of 4096.

The lookup is pure and dependency-free — `llm_capabilities` must not import from
`llm_client`, `runtime/`, or `nodes/`. Same constraint as `llm_providers.py`.
"""

from __future__ import annotations

import pytest

# ------------------------------------------------------------------------------
# Anthropic version-specific thresholds (DD#32)
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-opus-4-1",
        "anthropic/claude-opus-4",
        "anthropic/claude-sonnet-4",
        "anthropic/claude-sonnet-3-7",
        # Bare names (no provider prefix) must also route correctly via
        # detect_provider's bare-prefix table.
        "claude-sonnet-4-5",
        "claude-opus-4-1",
    ],
)
def test_anthropic_1024_family(model: str) -> None:
    """Anthropic Sonnet 4.5 / Opus 4.1 / Opus 4 / Sonnet 4 / Sonnet 3.7 → 1024."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    assert get_min_cache_tokens(model) == 1024


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-haiku-3-5",
        "claude-sonnet-4-6",
        "claude-haiku-3-5",
    ],
)
def test_anthropic_2048_family(model: str) -> None:
    """Anthropic Sonnet 4.6 / Haiku 3.5 → 2048."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    assert get_min_cache_tokens(model) == 2048


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-opus-4-7",
        "anthropic/claude-opus-4-6",
        "anthropic/claude-opus-4-5",
        "anthropic/claude-haiku-4-5",
        "claude-opus-4-7",
        "claude-haiku-4-5",
    ],
)
def test_anthropic_4096_family(model: str) -> None:
    """Anthropic Opus 4.7 / Opus 4.6 / Opus 4.5 / Haiku 4.5 → 4096."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    assert get_min_cache_tokens(model) == 4096


def test_anthropic_dated_version_suffix_routes_to_family() -> None:
    """Anthropic dated-version suffixes (e.g. ``-20240620``) match the family prefix."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    assert get_min_cache_tokens("anthropic/claude-sonnet-4-5-20240620") == 1024
    assert get_min_cache_tokens("claude-haiku-4-5-20250101") == 4096


def test_anthropic_unknown_model_falls_back_to_conservative_floor() -> None:
    """Unrecognized Anthropic model name → 4096 (conservative floor per DD#32)."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    # Plausible but not in the encoded table (e.g. a future model not yet shipped).
    assert get_min_cache_tokens("anthropic/claude-future-model-99") == 4096


# ------------------------------------------------------------------------------
# OpenAI threshold
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "openai/gpt-4o",
        "openai/gpt-5",
        "openai/o1-preview",
        "openai/o3-mini",
        "openai/o4-mini",
        "gpt-4o",
        "o1",
        "o3",
        "o4",
    ],
)
def test_openai_threshold_is_1024(model: str) -> None:
    """OpenAI auto-cache fires at 1024 tokens uniformly across families."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    assert get_min_cache_tokens(model) == 1024


# ------------------------------------------------------------------------------
# Gemini threshold (explicit cache)
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.5-pro",
        "gemini/gemini-3-flash-preview",
        "gemini/gemini-3.1-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ],
)
def test_gemini_explicit_cache_threshold_is_4096(model: str) -> None:
    """Gemini's explicit ``cachedContents`` requires ~4k tokens (DD#32 + spec note).

    The implicit-cache mode is free at lower thresholds (1024 Flash / 2048 Pro),
    but pflow's ``cache_control`` markers fire the EXPLICIT path; the threshold
    used by ``cache.below-min-predicted`` must reflect when the marker won't fire,
    which is the explicit minimum.
    """
    from pflow.core.llm_capabilities import get_min_cache_tokens

    assert get_min_cache_tokens(model) == 4096


# ------------------------------------------------------------------------------
# Unknown / edge cases
# ------------------------------------------------------------------------------


def test_unknown_provider_returns_conservative_floor() -> None:
    """Unrecognized provider prefix → 4096 (conservative floor)."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    assert get_min_cache_tokens("ollama/llama3:8b") == 4096
    assert get_min_cache_tokens("custom-endpoint/foo-bar") == 4096


def test_empty_string_returns_conservative_floor() -> None:
    """Empty model id → 4096 (defensive fallback, no exception)."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    assert get_min_cache_tokens("") == 4096


def test_lookup_is_pure_and_deterministic() -> None:
    """Repeated calls return the same value with no side effects."""
    from pflow.core.llm_capabilities import get_min_cache_tokens

    a = get_min_cache_tokens("anthropic/claude-sonnet-4-5")
    b = get_min_cache_tokens("anthropic/claude-sonnet-4-5")
    c = get_min_cache_tokens("anthropic/claude-sonnet-4-5")
    assert a == b == c == 1024


def test_module_capabilities_tuple_is_immutable() -> None:
    """``MODEL_CAPABILITIES`` is a tuple of frozen dataclass instances — mutation-proof.

    Mirrors ``llm_providers.PROVIDERS`` shape and protects against accidental
    runtime mutation that would corrupt the global lookup.
    """
    from dataclasses import FrozenInstanceError

    from pflow.core.llm_capabilities import MODEL_CAPABILITIES, ModelCapability

    assert isinstance(MODEL_CAPABILITIES, tuple)
    assert len(MODEL_CAPABILITIES) > 0
    assert all(isinstance(c, ModelCapability) for c in MODEL_CAPABILITIES)
    # Frozen dataclass: mutation raises FrozenInstanceError.
    with pytest.raises(FrozenInstanceError):
        MODEL_CAPABILITIES[0].min_cache_tokens = 9999  # type: ignore[misc]


def test_module_is_dependency_free() -> None:
    """``llm_capabilities`` must not import from ``llm_client``, ``runtime/``, or ``nodes/``.

    Same constraint as ``llm_providers.py`` — these modules are imported by the
    adapter, exception diagnostics, and analyzers, so they must not pull heavier
    layers into their import graph.
    """
    import pflow.core.llm_capabilities as mod

    src = mod.__file__
    assert src is not None
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert "from pflow.core.llm_client" not in text
    assert "from pflow.runtime" not in text
    assert "from pflow.nodes" not in text
    assert "import pflow.core.llm_client" not in text
    assert "import pflow.runtime" not in text
    assert "import pflow.nodes" not in text


def test_get_min_cache_tokens_for_unknown_anthropic_uses_floor_not_zero() -> None:
    """A future-version Anthropic model never returns 0 (would be a silent skip).

    Defensive against the regression class where the lookup returns the
    integer-default of 0 rather than the conservative floor — ``cache.below-min-predicted``
    would never fire and the user wouldn't know caching is silently no-op.
    """
    from pflow.core.llm_capabilities import get_min_cache_tokens

    threshold = get_min_cache_tokens("anthropic/claude-opus-99-99")
    assert threshold > 0
    assert threshold == 4096


def test_anthropic_models_at_threshold_lists_named_1024_models() -> None:
    from pflow.core.llm_capabilities import anthropic_models_at_threshold

    assert anthropic_models_at_threshold(1024) == (
        "claude-sonnet-4-5",
        "claude-opus-4-1",
        "claude-opus-4",
        "claude-sonnet-4",
        "claude-sonnet-3-7",
    )


def test_anthropic_models_at_threshold_lists_named_2048_models() -> None:
    from pflow.core.llm_capabilities import anthropic_models_at_threshold

    assert anthropic_models_at_threshold(2048) == (
        "claude-sonnet-4-6",
        "claude-haiku-3-5",
    )


def test_anthropic_models_at_threshold_returns_empty_for_unknown_threshold() -> None:
    from pflow.core.llm_capabilities import anthropic_models_at_threshold

    assert anthropic_models_at_threshold(12345) == ()


def test_anthropic_models_at_threshold_excludes_provider_wildcards() -> None:
    from pflow.core.llm_capabilities import anthropic_models_at_threshold

    assert "" not in anthropic_models_at_threshold(1024)
    assert all("/" not in model for model in anthropic_models_at_threshold(1024))


@pytest.mark.parametrize(
    "provider_name,expected_budget",
    [
        ("anthropic", 4),
        ("openai", 1),
        ("gemini", 1),
        (None, 1),
        ("ollama", 1),
        ("bedrock", 1),
    ],
)
def test_get_breakpoint_budget(provider_name: str | None, expected_budget: int) -> None:
    """Anthropic gets 4 (native multi-breakpoint); everyone else (including
    routed Anthropic via proxy prefixes that don't classify as ``anthropic``)
    falls through to the conservative floor of 1."""
    from pflow.core.llm_capabilities import get_breakpoint_budget

    assert get_breakpoint_budget(provider_name) == expected_budget
