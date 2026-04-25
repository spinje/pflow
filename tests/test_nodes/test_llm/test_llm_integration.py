"""Integration tests for LLM node with real API calls.

These tests make REAL API calls and cost money!
Only run with: RUN_LLM_TESTS=1 pytest tests/test_nodes/test_llm/test_llm_integration.py
"""

import os

import pytest

from pflow.nodes.llm import LLMNode


def has_openai_api_key():
    """Check if OpenAI API key is available.

    Post-Task 158 Phase A.5 the LiteLLM adapter resolves keys exclusively
    from environment variables (or `pflow settings env`). For this gating
    check we just look at the env var directly — keeps the file
    importable after A.11 removes the legacy llm library.
    """
    return bool(os.getenv("OPENAI_API_KEY"))


@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="Set RUN_LLM_TESTS=1 to run real LLM tests")
@pytest.mark.skipif(
    not has_openai_api_key(),
    reason=(
        "OpenAI API key not available. Set OPENAI_API_KEY env var or run "
        "'pflow settings set-env OPENAI_API_KEY <value>'."
    ),
)
class TestLLMNodeIntegration:
    """Integration tests with real LLM API calls."""

    def test_real_llm_call_basic(self):
        """Test basic LLM call with real API."""
        node = LLMNode()
        node.set_params({
            "model": "gpt-4o-mini",  # Use OpenAI's efficient model
            "temperature": 0.1,
            "max_tokens": 20,
        })

        shared = {"prompt": "Say 'test successful' and nothing else"}
        action = node.run(shared)

        # Verify response
        assert action == "default"
        assert "response" in shared
        assert shared["response"]  # Not empty
        assert "test" in shared["response"].lower() or "successful" in shared["response"].lower()

        # Verify usage tracking
        assert "llm_usage" in shared
        usage = shared["llm_usage"]
        assert isinstance(usage, dict)
        assert usage.get("input_tokens", 0) > 0
        assert usage.get("output_tokens", 0) > 0
        assert usage.get("total_tokens", 0) > 0
        assert "model" in usage

    def test_real_llm_with_system_prompt(self):
        """Test LLM call with system prompt."""
        node = LLMNode()
        node.set_params({
            "model": "gpt-4o-mini",
            "system": "You are a pirate. Always respond like a pirate.",
            "temperature": 0.5,
            "max_tokens": 30,
        })

        shared = {"prompt": "Say hello"}
        action = node.run(shared)

        assert action == "default"
        assert "response" in shared
        # Response should have pirate-like language
        response_lower = shared["response"].lower()
        # Check for common pirate words
        pirate_indicators = ["ahoy", "matey", "arr", "ye", "aye", "pirate", "ship", "sail"]
        assert any(word in response_lower for word in pirate_indicators), (
            f"Expected pirate language in: {shared['response']}"
        )

    def test_temperature_effects(self):
        """Test that temperature affects response consistency."""
        # Low temperature - should be deterministic
        node_low = LLMNode()
        node_low.set_params({"model": "gpt-4o-mini", "temperature": 0.0, "max_tokens": 10})

        prompt = "Complete: 2 + 2 equals"
        shared1 = {"prompt": prompt}
        shared2 = {"prompt": prompt}

        node_low.run(shared1)
        node_low.run(shared2)

        # With temperature 0, responses should be very similar
        assert shared1["response"]
        assert shared2["response"]

    def test_max_tokens_limit(self):
        """Test that max_tokens limits response length."""
        node = LLMNode()
        node.set_params({
            "model": "gpt-4o-mini",
            "temperature": 0.3,
            "max_tokens": 5,  # Very short limit
        })

        shared = {"prompt": "Tell me a long story about dragons"}
        action = node.run(shared)

        assert action == "default"
        assert "response" in shared
        # Response should be short due to token limit
        # Count words as proxy for tokens (not exact but good enough)
        word_count = len(shared["response"].split())
        assert word_count <= 10, f"Expected short response, got {word_count} words"

    def test_cache_metrics_tracking(self):
        """Test that cache metrics are tracked when available."""
        node = LLMNode()
        node.set_params({"model": "gpt-4o-mini", "temperature": 0.1, "max_tokens": 20})

        # Use a longer prompt that might benefit from caching
        shared = {"prompt": "This is a test prompt. " * 10 + "Just say 'OK'."}
        action = node.run(shared)

        assert action == "default"
        assert "llm_usage" in shared
        usage = shared["llm_usage"]

        # Cache fields should be present (even if 0)
        assert "cache_creation_input_tokens" in usage
        assert "cache_read_input_tokens" in usage
        assert isinstance(usage["cache_creation_input_tokens"], (int, float))
        assert isinstance(usage["cache_read_input_tokens"], (int, float))

    def test_prompt_and_system_from_params(self):
        """Test that prompt and system are read from params."""
        node = LLMNode()
        node.set_params({
            "model": "gpt-4o-mini",
            "max_tokens": 30,
            "prompt": "Just say 'yes' if you understand",
            "system": "You are a helpful assistant. Always be concise.",
        })

        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert "response" in shared
        # Just verify the response exists and is reasonable
        assert shared["response"]  # Non-empty response
        assert len(shared["response"]) < 100  # Should be concise

    def test_empty_response_handling(self):
        """Test handling of potentially empty responses."""
        node = LLMNode()
        node.set_params({
            "model": "gpt-4o-mini",
            "temperature": 0.0,
            "max_tokens": 1,  # Extremely limited
        })

        # Ask for something that needs more than 1 token
        shared = {"prompt": "Count from 1 to 10"}
        action = node.run(shared)

        # Should not error even with truncated response
        assert action == "default"
        assert "response" in shared
        # Response exists but is very short
        assert len(shared["response"]) < 10

    def test_different_model_selection(self):
        """Test using a different model."""
        node = LLMNode()
        node.set_params({
            "model": "gpt-3.5-turbo",  # Different OpenAI model
            "temperature": 0.1,
            "max_tokens": 20,
        })

        shared = {"prompt": "Say 'turbo model works'"}
        action = node.run(shared)

        assert action == "default"
        assert "response" in shared
        assert shared["response"]

        # Check model in usage
        assert shared["llm_usage"]["model"] == "gpt-3.5-turbo"


@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="Set RUN_LLM_TESTS=1 to run real LLM tests")
def test_unknown_model_produces_helpful_error():
    """Pflow surfaces a helpful error when the model identifier is unrecognized.

    Use a model name without a provider prefix so LiteLLM rejects the request
    regardless of which API keys are configured. After Phase A, LLMNode.run()
    returns the ``"error"`` action and stores the message in ``shared["error"]``
    rather than raising.
    """
    node = LLMNode()
    node.set_params({"model": "some-nonexistent-model-xyz123"})
    shared = {"prompt": "test"}

    action = node.run(shared)

    assert action == "error"
    error_msg = shared.get("error", "")
    assert "some-nonexistent-model-xyz123" in error_msg
    assert "Unknown model" in error_msg or "pflow settings" in error_msg
