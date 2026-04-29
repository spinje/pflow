"""C1.2 — ``MockLLMClient.set_response`` cache-token staging.

Round 6 made these REQUIRED unit tests: without them, the implementation
could silently ignore the new args (resolver methods returning ``0``
unconditionally would still produce passing cache-hit tests if those tests
don't assert on the field). These tests pin the contract at the test seam.
"""

from __future__ import annotations

from tests.shared.llm_mock import MockLLMClient


def test_set_response_populates_cache_creation_tokens() -> None:
    mock = MockLLMClient()
    mock.set_response(
        "anthropic/claude-sonnet-4-5",
        None,
        "test",
        cache_creation_input_tokens=1024,
    )

    response = mock.complete(model="anthropic/claude-sonnet-4-5", prompt="x")

    assert response.usage["cache_creation_input_tokens"] == 1024


def test_set_response_populates_cache_read_tokens() -> None:
    mock = MockLLMClient()
    mock.set_response(
        "anthropic/claude-sonnet-4-5",
        None,
        "test",
        cache_read_input_tokens=2048,
    )

    response = mock.complete(model="anthropic/claude-sonnet-4-5", prompt="x")

    assert response.usage["cache_read_input_tokens"] == 2048


def test_cache_tokens_default_zero_when_not_set() -> None:
    mock = MockLLMClient()
    mock.set_response("model-X", None, "test")  # No cache_*_tokens kwargs

    response = mock.complete(model="model-X", prompt="x")

    assert response.usage["cache_creation_input_tokens"] == 0
    assert response.usage["cache_read_input_tokens"] == 0


def test_cache_tokens_wildcard_fallback() -> None:
    """Wildcard ``"*"`` model + (schema=None) → matches any model."""
    mock = MockLLMClient()
    mock.set_response("*", None, "test", cache_creation_input_tokens=512)

    response = mock.complete(model="anything", prompt="x")

    assert response.usage["cache_creation_input_tokens"] == 512


def test_cache_tokens_exact_match_takes_precedence_over_wildcard() -> None:
    """Exact (model, schema) entry must beat the ``*`` fallback."""
    mock = MockLLMClient()
    mock.set_response("*", None, "fallback", cache_creation_input_tokens=100)
    mock.set_response("specific", None, "exact", cache_creation_input_tokens=999)

    response = mock.complete(model="specific", prompt="x")

    assert response.usage["cache_creation_input_tokens"] == 999


def test_reset_clears_cache_tokens() -> None:
    mock = MockLLMClient()
    mock.set_response("model-X", None, "test", cache_creation_input_tokens=1024)
    mock.reset()
    mock.set_response("model-X", None, "test")  # No staged cache tokens

    response = mock.complete(model="model-X", prompt="x")

    assert response.usage["cache_creation_input_tokens"] == 0


def test_cache_creation_and_read_tokens_independent() -> None:
    """Setting one shouldn't reset the other on the same key."""
    mock = MockLLMClient()
    mock.set_response(
        "anthropic/claude-sonnet-4-5",
        None,
        "test",
        cache_creation_input_tokens=1024,
        cache_read_input_tokens=2048,
    )

    response = mock.complete(model="anthropic/claude-sonnet-4-5", prompt="x")

    assert response.usage["cache_creation_input_tokens"] == 1024
    assert response.usage["cache_read_input_tokens"] == 2048
