"""Tests for prompt-cache TTL parsing and provider capability."""

from __future__ import annotations

import pytest

from pflow.core.cache_ttl import is_cache_ttl_supported_by_provider, parse_cache_ttl


@pytest.mark.parametrize(
    ("value", "label", "seconds"),
    [
        (None, "5m", 300),
        ("1m", "1m", 60),
        ("11m", "11m", 660),
        ("55m", "55m", 3300),
        ("60m", "60m", 3600),
        ("1h", "1h", 3600),
    ],
)
def test_parse_cache_ttl_accepts_supported_values(value: str | None, label: str, seconds: int) -> None:
    parsed = parse_cache_ttl(value)
    assert parsed.label == label
    assert parsed.seconds == seconds


@pytest.mark.parametrize("value", ["0m", "61m", "2h", "90s", "1.5m", "3600s", "5 min", ""])
def test_parse_cache_ttl_rejects_unsupported_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_cache_ttl(value)


def test_provider_support_matrix_for_dynamic_ttl() -> None:
    assert is_cache_ttl_supported_by_provider("gemini", "11m")
    assert not is_cache_ttl_supported_by_provider("anthropic", "11m")
    assert not is_cache_ttl_supported_by_provider("openai", "11m")
    assert not is_cache_ttl_supported_by_provider(None, "11m")


def test_provider_support_matrix_keeps_discrete_ttls() -> None:
    for provider in ("anthropic", "openai", None):
        assert is_cache_ttl_supported_by_provider(provider, None)
        assert is_cache_ttl_supported_by_provider(provider, "5m")
        assert is_cache_ttl_supported_by_provider(provider, "1h")
        assert is_cache_ttl_supported_by_provider(provider, "60m")
