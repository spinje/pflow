"""Test that cost calculations are included in trace files."""

import json

from pflow.planning.debug import TraceCollector


class TestCostInTrace:
    """Test cost data in traces."""

    def test_cost_included_in_trace(self):
        """Test that cost breakdown is included in trace files."""
        # Create a trace collector
        collector = TraceCollector(user_input="test input")

        # Simulate recording an LLM response with usage data
        usage_data = {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_input_tokens": 2000,
            "cache_read_input_tokens": 1000,
            "thinking_tokens": 1500,
            "thinking_budget": 4096,
        }

        # Record the response
        collector.record_llm_request("TestNode", "Test prompt", {})
        collector.record_llm_response_with_data(
            node="TestNode",
            response_data={"result": "test"},
            duration=2.5,
            usage_data=usage_data,
            model_name="anthropic/claude-3-5-sonnet-20241022",
            shared=None,
        )

        # Verify cost data is present in collector's llm_calls
        assert len(collector.llm_calls) == 1
        call = collector.llm_calls[0]

        # Check that cost field exists
        assert "cost" in call
        cost_data = call["cost"]

        # Verify cost breakdown fields
        assert "input_cost" in cost_data
        assert "output_cost" in cost_data
        assert "cache_creation_cost" in cost_data
        assert "cache_read_cost" in cost_data
        assert "thinking_cost" in cost_data
        assert "total_cost_usd" in cost_data
        assert "pricing_model" in cost_data
        assert "pricing_version" in cost_data

        # Verify specific values
        # Input: 1000 * $3/1M = 0.003
        assert cost_data["input_cost"] == 0.003
        # Output: 500 * $15/1M = 0.0075
        assert cost_data["output_cost"] == 0.0075
        # Cache creation: 2000 * $3/1M * 2 = 0.012
        assert cost_data["cache_creation_cost"] == 0.012
        # Cache read: 1000 * $3/1M * 0.1 = 0.0003
        assert cost_data["cache_read_cost"] == 0.0003
        # Thinking: 1500 * $15/1M = 0.0225
        assert cost_data["thinking_cost"] == 0.0225
        # Total: 0.003 + 0.0075 + 0.012 + 0.0003 + 0.0225 = 0.0453
        assert cost_data["total_cost_usd"] == 0.0453

        # Verify model and version
        assert cost_data["pricing_model"] == "anthropic/claude-3-5-sonnet-20241022"
        assert cost_data["pricing_version"] == "2025-12-19"

    def test_cost_in_saved_trace_file(self):
        """Test that cost data is preserved when saving trace to file."""
        # Create a trace collector
        collector = TraceCollector(user_input="test input")

        # Simulate recording an LLM response
        usage_data = {
            "input_tokens": 500,
            "output_tokens": 250,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1000,
            "thinking_tokens": 0,
            "thinking_budget": 0,
        }

        collector.record_llm_request("TestNode", "Test prompt", {})
        collector.record_llm_response_with_data(
            node="TestNode",
            response_data={"result": "test"},
            duration=1.5,
            usage_data=usage_data,
            model_name="gpt-4o",
            shared=None,
        )

        # Save to file
        trace_path = collector.save_to_file()

        # Read the file back
        with open(trace_path) as f:
            loaded_trace = json.load(f)

        # Verify cost data is in the saved file
        assert len(loaded_trace["llm_calls"]) == 1
        call = loaded_trace["llm_calls"][0]
        assert "cost" in call

        cost_data = call["cost"]
        # GPT-4o: $5/1M input, $15/1M output
        # Input: 500 * $5/1M = 0.0025
        # Cache read: 1000 * $5/1M * 0.1 = 0.0005
        # Output: 250 * $15/1M = 0.00375
        assert cost_data["input_cost"] == 0.0025
        assert cost_data["cache_read_cost"] == 0.0005
        assert cost_data["output_cost"] == 0.00375
        assert cost_data["total_cost_usd"] == 0.00675

    def test_cost_with_unknown_model(self):
        """Test that unknown models use default pricing."""
        collector = TraceCollector(user_input="test input")

        usage_data = {
            "input_tokens": 1000,
            "output_tokens": 500,
        }

        collector.record_llm_request("TestNode", "Test prompt", {})
        collector.record_llm_response_with_data(
            node="TestNode",
            response_data={"result": "test"},
            duration=1.0,
            usage_data=usage_data,
            model_name="unknown-future-model",
            shared=None,
        )

        call = collector.llm_calls[0]
        cost_data = call["cost"]

        # Should gracefully handle unknown model
        assert cost_data["total_cost_usd"] is None
        assert cost_data["pricing_model"] == "unavailable"
        assert cost_data["input_cost"] is None
        assert cost_data["output_cost"] is None
        assert "error" in cost_data  # Should contain error message
