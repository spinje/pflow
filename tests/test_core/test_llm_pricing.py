"""Test LLM pricing calculations."""

import pytest

from pflow.core.llm_pricing import MODEL_PRICING, PRICING_VERSION, calculate_llm_cost, get_model_pricing


class TestLLMPricing:
    """Test LLM pricing calculations."""

    def test_regular_token_pricing(self):
        """Test basic input/output token pricing."""
        cost = calculate_llm_cost(
            model="anthropic/claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
        )

        # Claude Sonnet: $3/1M input, $15/1M output
        # 1000 input = 0.003, 500 output = 0.0075
        assert cost["input_cost"] == 0.003
        assert cost["output_cost"] == 0.0075
        assert cost["total_cost_usd"] == 0.0105
        assert cost["pricing_model"] == "anthropic/claude-3-5-sonnet-20241022"

    def test_cache_creation_pricing(self):
        """Test cache creation token pricing (2x premium)."""
        cost = calculate_llm_cost(
            model="anthropic/claude-sonnet-4-0",
            input_tokens=1000,
            cache_creation_tokens=2000,
        )

        # Regular: 1000 * $3/1M = 0.003
        # Cache creation: 2000 * $3/1M * 2 = 0.012
        assert cost["input_cost"] == 0.003
        assert cost["cache_creation_cost"] == 0.012
        assert cost["total_cost_usd"] == 0.015

    def test_cache_read_pricing(self):
        """Test cache read token pricing (90% discount)."""
        cost = calculate_llm_cost(
            model="anthropic/claude-sonnet-4-0",
            input_tokens=1000,
            cache_read_tokens=5000,
        )

        # Regular: 1000 * $3/1M = 0.003
        # Cache read: 5000 * $3/1M * 0.1 = 0.0015
        assert cost["input_cost"] == 0.003
        assert cost["cache_read_cost"] == 0.0015
        assert cost["total_cost_usd"] == 0.0045

    def test_thinking_token_pricing(self):
        """Test thinking token pricing (billed at output rate)."""
        cost = calculate_llm_cost(
            model="anthropic/claude-3-5-sonnet-20241022",
            output_tokens=500,
            thinking_tokens=2000,
        )

        # Output: 500 * $15/1M = 0.0075
        # Thinking: 2000 * $15/1M = 0.03
        assert cost["output_cost"] == 0.0075
        assert cost["thinking_cost"] == 0.03
        assert cost["total_cost_usd"] == 0.0375

    def test_combined_pricing(self):
        """Test combined pricing with all token types."""
        cost = calculate_llm_cost(
            model="anthropic/claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=2000,
            cache_read_tokens=3000,
            thinking_tokens=1500,
        )

        # Input: 1000 * $3/1M = 0.003
        # Output: 500 * $15/1M = 0.0075
        # Cache creation: 2000 * $3/1M * 2 = 0.012
        # Cache read: 3000 * $3/1M * 0.1 = 0.0009
        # Thinking: 1500 * $15/1M = 0.0225
        assert cost["input_cost"] == 0.003
        assert cost["output_cost"] == 0.0075
        assert cost["cache_creation_cost"] == 0.012
        assert cost["cache_read_cost"] == 0.0009
        assert cost["thinking_cost"] == 0.0225
        assert cost["total_cost_usd"] == 0.0459

    def test_unknown_model_raises_error(self):
        """Test that unknown models raise helpful errors."""
        with pytest.raises(ValueError) as exc_info:
            calculate_llm_cost(
                model="unknown-model-xyz",
                input_tokens=1000,
                output_tokens=500,
            )

        error_msg = str(exc_info.value)
        assert "Unknown model 'unknown-model-xyz'" in error_msg
        assert "pricing not available" in error_msg

    def test_zero_tokens(self):
        """Test with zero tokens."""
        cost = calculate_llm_cost(
            model="gpt-4",
            input_tokens=0,
            output_tokens=0,
        )

        assert cost["input_cost"] == 0.0
        assert cost["output_cost"] == 0.0
        assert cost["total_cost_usd"] == 0.0

    def test_large_token_counts(self):
        """Test with large token counts (100K tokens)."""
        cost = calculate_llm_cost(
            model="gpt-4",
            input_tokens=100000,
            output_tokens=50000,
        )

        # GPT-4: $30/1M input, $60/1M output
        # 100K input = 3.0, 50K output = 3.0
        assert cost["input_cost"] == 3.0
        assert cost["output_cost"] == 3.0
        assert cost["total_cost_usd"] == 6.0

    def test_precision_rounding(self):
        """Test that costs are rounded to 6 decimal places."""
        cost = calculate_llm_cost(
            model="gemini-1.5-flash",
            input_tokens=333,  # Will create repeating decimals
            output_tokens=777,
        )

        # Gemini Flash: $0.075/1M input, $0.30/1M output
        # 333 * 0.075 / 1000000 = 0.000024975 -> 0.000025
        # 777 * 0.30 / 1000000 = 0.0002331 -> 0.000233
        assert cost["input_cost"] == 0.000025
        assert cost["output_cost"] == 0.000233
        assert cost["total_cost_usd"] == 0.000258

    def test_get_model_pricing(self):
        """Test getting pricing for specific models."""
        # Known model
        pricing = get_model_pricing("gpt-4o")
        assert pricing["input"] == 5.0
        assert pricing["output"] == 15.0

        # Unknown model raises error
        with pytest.raises(ValueError) as exc_info:
            get_model_pricing("unknown-model")

        error_msg = str(exc_info.value)
        assert "Unknown model 'unknown-model'" in error_msg
        assert "pricing not available" in error_msg

    def test_all_models_have_pricing(self):
        """Test that all models in MODEL_PRICING have valid pricing."""
        for _model, pricing in MODEL_PRICING.items():
            assert "input" in pricing
            assert "output" in pricing
            assert pricing["input"] > 0
            assert pricing["output"] > 0
            assert isinstance(pricing["input"], (int, float))
            assert isinstance(pricing["output"], (int, float))

    def test_pricing_version_exists(self):
        """Test that pricing version is included in cost calculation."""
        cost = calculate_llm_cost(
            model="gpt-4",
            input_tokens=1000,
        )

        assert "pricing_version" in cost
        assert cost["pricing_version"] == PRICING_VERSION

    def test_model_aliases(self):
        """Test that model aliases resolve correctly."""
        # Test OpenAI aliases
        cost_alias = calculate_llm_cost(model="4o", input_tokens=1000)
        cost_canonical = calculate_llm_cost(model="gpt-4o", input_tokens=1000)
        assert cost_alias["total_cost_usd"] == cost_canonical["total_cost_usd"]
        assert cost_alias["pricing_model"] == "gpt-4o"  # Both resolve to canonical

        # Test Anthropic aliases
        cost_alias = calculate_llm_cost(model="claude-3.5-sonnet", input_tokens=1000)
        cost_canonical = calculate_llm_cost(model="anthropic/claude-3-5-sonnet-20241022", input_tokens=1000)
        assert cost_alias["total_cost_usd"] == cost_canonical["total_cost_usd"]
        assert cost_alias["pricing_model"] == "anthropic/claude-3-5-sonnet-20241022"

        # Test Gemini aliases
        cost_alias = calculate_llm_cost(model="gemini-1.5-flash", input_tokens=1000)
        cost_canonical = calculate_llm_cost(model="gemini/gemini-1.5-flash", input_tokens=1000)
        assert cost_alias["total_cost_usd"] == cost_canonical["total_cost_usd"]
        # Note: "gemini-1.5-flash" maps to "gemini/gemini-1.5-flash" which is in MODEL_PRICING
        assert cost_alias["pricing_model"] == "gemini/gemini-1.5-flash"

    def test_error_message_suggestions(self):
        """Test that error messages provide helpful suggestions for partial matches."""
        # Test with a truly unknown model that contains a partial match
        with pytest.raises(ValueError) as exc_info:
            calculate_llm_cost(model="anthropic/claude", input_tokens=1000)  # Partial match

        error_msg = str(exc_info.value)
        assert "Unknown model 'anthropic/claude'" in error_msg
        # The suggestions would show models containing "anthropic/claude" in their name
        assert "Did you mean" in error_msg  # Should suggest similar models like anthropic/claude-3-opus-20240229

    def test_model_alias_resolution(self):
        """Test that model aliases work correctly without raising errors."""
        # "claude-3-opus" is an alias that should work
        cost = calculate_llm_cost(model="claude-3-opus", input_tokens=1000)
        assert cost["pricing_model"] == "anthropic/claude-3-opus-20240229"

        # "gpt-4" is directly in MODEL_PRICING, not an alias
        cost = calculate_llm_cost(model="gpt-4", input_tokens=1000)
        assert cost["pricing_model"] == "gpt-4"

        # "4o" is an alias for "gpt-4o"
        cost = calculate_llm_cost(model="4o", input_tokens=1000)
        assert cost["pricing_model"] == "gpt-4o"
