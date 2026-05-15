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
        # F#17 deferred: ``unavailable_models`` carries per-model call counts
        # as ``[{"name": str, "calls": int}, ...]``.
        names = [entry["name"] for entry in summary["unavailable_models"]]
        assert "my-custom-ollama-model" in names

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
        names = [entry["name"] for entry in cost_data["unavailable_models"]]
        assert "future-gpt-5" in names
        assert "gpt-4o-mini" not in names

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
        # plus how many calls hit each model (F#17 deferred).
        assert cost_data["unavailable_models"] == [{"name": "anthropic/claude-4-ultra", "calls": 1}]

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
        names = [entry["name"] for entry in cost_data["unavailable_models"]]
        assert "unknown-model" in names

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
        names = [entry["name"] for entry in cost_data["unavailable_models"]]
        assert "unknown" not in names
        assert cost_data["unavailable_models_unnamed_count"] == 1

    def test_rendered_phrase_includes_per_model_call_count(self):
        """F#17 deferred: the rendered pricing-unavailable phrase carries
        per-model call counts so users can size the missing-pricing impact
        without drilling into the raw JSON.
        """
        from pflow.core.metrics import format_unavailable_models_phrase, unavailable_models_to_counts

        collector = MetricsCollector()

        # 3 calls to a model LiteLLM doesn't have pricing for, 2 calls
        # without a recorded model (e.g. cached calls that stripped model
        # before reaching the cost summary path).
        llm_calls = [
            {"model": "gemini/gemini-3-flash-preview", "cost_usd": None},
            {"model": "gemini/gemini-3-flash-preview", "cost_usd": None},
            {"model": "gemini/gemini-3-flash-preview", "cost_usd": None},
            {"cost_usd": None},  # unnamed
            {"cost_usd": None},  # unnamed
        ]

        cost_data = collector.calculate_costs(llm_calls)
        counts = unavailable_models_to_counts(cost_data["unavailable_models"])
        phrase = format_unavailable_models_phrase(
            counts,
            cost_data["unavailable_models_unnamed_count"],
        )

        assert phrase == "gemini/gemini-3-flash-preview (3 calls); 2 calls without recorded model"
