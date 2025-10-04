"""Test that unknown models don't crash workflows - the actual user experience.

CRITICAL: This tests our most important guarantee - workflows complete even with unknown models.
"""

import time
from unittest.mock import patch

from pflow.core.metrics import MetricsCollector


class TestUnknownModelUserExperience:
    """Test the full user experience when using unknown models."""

    def test_workflow_completes_with_unknown_model(self):
        """Test that a workflow with unknown model completes and shows clear message."""
        # Simulate a real workflow execution
        collector = MetricsCollector()

        # Start workflow
        collector.record_workflow_start()

        # Execute some nodes
        collector.record_node_execution("read-file", 100.5, is_planner=False)
        time.sleep(0.001)  # Ensure measurable duration
        collector.record_node_execution("llm", 500.2, is_planner=False)

        # Workflow completes
        collector.record_workflow_end()

        # LLM calls include an unknown model (e.g., user's custom model)
        llm_calls = [
            {
                "model": "my-custom-ollama-model",  # Unknown model
                "input_tokens": 1000,
                "output_tokens": 500,
                "is_planner": False,
            }
        ]

        # Get the summary that would be shown to user
        summary = collector.get_summary(llm_calls)

        # CRITICAL ASSERTIONS:
        # 1. Summary was generated (no crash)
        assert summary is not None

        # 2. Workflow metrics are present
        assert summary["duration_ms"] > 0
        assert summary["num_nodes"] == 2

        # 3. Cost is clearly marked as unavailable
        assert summary["total_cost_usd"] is None
        assert summary["pricing_available"] is False
        assert "my-custom-ollama-model" in summary["unavailable_models"]

        # 4. Token counts are still tracked (for debugging)
        assert summary["metrics"]["total"]["tokens_input"] == 1000
        assert summary["metrics"]["total"]["tokens_output"] == 500

        # This proves the workflow completed successfully despite unknown model

    def test_mixed_models_shows_partial_cost_clearly(self):
        """Test that mixed known/unknown models show partial costs clearly."""
        collector = MetricsCollector()

        llm_calls = [
            # Known model
            {
                "model": "gpt-4o-mini",
                "input_tokens": 1000,
                "output_tokens": 500,
            },
            # Unknown model
            {
                "model": "future-gpt-5",
                "input_tokens": 2000,
                "output_tokens": 1000,
            },
        ]

        cost_data = collector.calculate_costs(llm_calls)

        # Should indicate pricing is unavailable overall
        assert cost_data["pricing_available"] is False
        assert cost_data["total_cost_usd"] is None

        # But should show partial cost from known models
        assert cost_data["partial_cost_usd"] is not None
        assert cost_data["partial_cost_usd"] > 0

        # Should list which models are unavailable
        assert "future-gpt-5" in cost_data["unavailable_models"]
        assert "gpt-4o-mini" not in cost_data["unavailable_models"]

    def test_user_message_is_actionable(self):
        """Test that the error information is actionable for users."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "anthropic/claude-4-ultra",  # Hypothetical future model
                "input_tokens": 1000,
                "output_tokens": 500,
            }
        ]

        cost_data = collector.calculate_costs(llm_calls)

        # The unavailable_models list tells user exactly which models need pricing
        assert cost_data["unavailable_models"] == ["anthropic/claude-4-ultra"]

        # With this info, user knows to:
        # 1. Check if model name is correct
        # 2. Update MODEL_PRICING if it's a new model
        # 3. File an issue if it's a legitimate new model

    @patch("logging.Logger.debug")
    def test_debug_logged_for_unknown_model(self, mock_debug):
        """Test that debug info is logged for unknown models.

        NOTE: Changed from warning to debug level in commit 76e0bc2.
        Unknown models are expected behavior (custom models, new models),
        and the information is already surfaced to users via unavailable_models.
        Debug logging is more appropriate for diagnostics.
        """
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "unknown-model",
                "input_tokens": 100,
                "output_tokens": 50,
            }
        ]

        collector.calculate_costs(llm_calls)

        # Verify debug message was logged with helpful diagnostic info
        mock_debug.assert_called()
        debug_message = mock_debug.call_args[0][0]
        assert "unknown-model" in debug_message
        assert "Pricing not available" in debug_message
