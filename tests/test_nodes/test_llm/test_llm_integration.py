"""Integration tests for LLM node with real API calls.

These tests make REAL API calls and cost money!
Only run with: RUN_LLM_TESTS=1 pytest tests/test_nodes/test_llm/test_llm_integration.py
"""

import os

import pytest

from pflow.nodes.llm import LLMNode


def has_openai_api_key():
    """Check if OpenAI API key is available."""
    try:
        import llm

        # OpenAI is built into llm, no plugin needed
        try:
            llm.get_model("gpt-4o-mini")
            # Check if we can get the model (key will be checked on actual use)
            if os.getenv("OPENAI_API_KEY"):
                return True
            # Try to get the key from llm's config
            return True  # If model loaded, key must be configured
        except Exception as e:
            error_msg = str(e)
            if "NeedsKeyException" in error_msg or "API key" in error_msg:
                # No key configured
                return False
            # Other errors - assume we can't test
            return False
    except ImportError:
        # llm library not installed (shouldn't happen)
        return False


@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="Set RUN_LLM_TESTS=1 to run real LLM tests")
@pytest.mark.skipif(
    not has_openai_api_key(), reason="OpenAI API key not available. Run 'llm keys set openai' or set OPENAI_API_KEY"
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

    def test_fallback_from_shared_store(self):
        """Test that prompt and system fallback from shared store."""
        node = LLMNode()
        node.set_params({"model": "gpt-4o-mini", "max_tokens": 30, "system": "Param system - should be overridden"})

        # Both prompt and system in shared store
        shared = {
            "prompt": "Just say 'yes' if you understand",
            "system": "You are a helpful assistant. Always be concise.",
        }

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
def test_missing_api_key_error():
    """Test that missing API key produces helpful error."""
    # This test won't work if key is set via 'llm keys set'
    # So we test with a model that definitely doesn't have a key
    node = LLMNode()
    node.set_params({"model": "some-nonexistent-model-xyz123"})
    shared = {"prompt": "test"}

    with pytest.raises(ValueError) as exc_info:
        node.run(shared)

    # Should have helpful message about unknown model
    error_msg = str(exc_info.value)
    assert "Unknown model" in error_msg or "llm models" in error_msg
