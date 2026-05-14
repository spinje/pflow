"""Test that unknown models don't crash workflows - the actual user experience.

CRITICAL: This tests our most important guarantee - workflows complete even with unknown models.
"""

import time

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
        collector.record_node_execution("read-file", 100.5)
        time.sleep(0.001)  # Ensure measurable duration
        collector.record_node_execution("llm", 500.2)

        # Workflow completes
        collector.record_workflow_end()

        # LLM calls include an unknown model (e.g., user's custom model)
        llm_calls = [
            {
                "model": "my-custom-ollama-model",  # Unknown model
                "input_tokens": 1000,
                "output_tokens": 500,
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

    def test_mixed_priced_unpriced_shows_partial_cost_clearly(self):
        """Calls with ``cost_usd`` set surface as partial cost; calls without
        end up in ``unavailable_models``.

        Post-Task-158 cost determination is LiteLLM's responsibility — pflow
        no longer maintains a per-model pricing table. The "known vs
        unknown" split now manifests as "has cost_usd vs doesn't".
        """
        collector = MetricsCollector()

        llm_calls = [
            # Adapter populated cost_usd from LiteLLM's response_cost
            {
                "model": "gpt-4o-mini",
                "input_tokens": 1000,
                "output_tokens": 500,
                "cost_usd": 0.00045,
            },
            # LiteLLM returned None for response_cost (unknown model, custom endpoint, etc.)
            {
                "model": "future-gpt-5",
                "input_tokens": 2000,
                "output_tokens": 1000,
            },
        ]

        cost_data = collector.calculate_costs(llm_calls)

        # Pricing is unavailable overall (one call lacks cost_usd)
        assert cost_data["pricing_available"] is False
        assert cost_data["total_cost_usd"] is None

        # Partial cost from priced calls is still surfaced
        assert cost_data["partial_cost_usd"] is not None
        assert cost_data["partial_cost_usd"] == 0.00045

        # The unpriced model is listed as unavailable; the priced one is not
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
        # 1. Check if the model name is correct
        # 2. If the model is new/custom, LiteLLM doesn't have pricing for it —
        #    cost reporting will show as unavailable (this is expected, not a bug)

    def test_unknown_model_surfaced_in_unavailable_models(self):
        """Test that unknown models are surfaced via unavailable_models field.

        Unknown models are expected behavior (custom models, new models).
        The diagnostic info is surfaced via the unavailable_models field in the
        return value — no logging needed.
        """
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "unknown-model",
                "input_tokens": 100,
                "output_tokens": 50,
            }
        ]

        cost_data = collector.calculate_costs(llm_calls)

        assert cost_data["pricing_available"] is False
        assert "unknown-model" in cost_data["unavailable_models"]

    def test_call_without_recorded_model_does_not_show_literal_unknown(self):
        """Regression for F#17: a call dict missing ``model`` must NOT
        surface as the literal string ``"unknown"`` in
        ``unavailable_models``. It belongs in the unnamed-count tally so
        users see actionable model names plus a clear "N calls without
        recorded model" rather than the opaque sentinel.
        """
        collector = MetricsCollector()

        # No model recorded (and no cost_usd) — historically would have
        # surfaced as the opaque literal ``"unknown"`` in unavailable_models.
        llm_calls = [{"input_tokens": 100, "output_tokens": 50}]

        cost_data = collector.calculate_costs(llm_calls)

        assert cost_data["pricing_available"] is False
        assert cost_data["unavailable_models"] == []
        assert "unknown" not in cost_data["unavailable_models"]
        assert cost_data["unavailable_models_unnamed_count"] == 1
