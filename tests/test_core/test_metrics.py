"""Tests for the MetricsCollector class."""

import time
from unittest.mock import patch

from pflow.core.metrics import MetricsCollector


class TestMetricsCollector:
    """Test suite for MetricsCollector functionality."""

    def test_initialization(self):
        """Test that MetricsCollector initializes with correct defaults."""
        collector = MetricsCollector()

        assert collector.start_time is not None
        assert collector.workflow_start is None
        assert collector.workflow_end is None
        assert collector.workflow_nodes == {}

    def test_aggregation_sums_explicit_cost_usd(self):
        """``calculate_costs`` sums ``cost_usd`` from each call.

        Pricing is LiteLLM's job (set by the adapter on ``llm_usage.cost_usd``);
        ``MetricsCollector`` only sums what's already there.
        """
        collector = MetricsCollector()

        llm_calls = [
            {"model": "gpt-4o-mini", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.000045},
            {"model": "gpt-4o-mini", "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.00009},
            {"model": "gpt-4o-mini", "input_tokens": 150, "output_tokens": 75, "cost_usd": 0.0000675},
        ]

        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["pricing_available"] is True
        assert cost_data["total_cost_usd"] == round(0.000045 + 0.00009 + 0.0000675, 6)

    def test_unknown_model_uses_default_pricing(self):
        """Test that unknown models are handled gracefully."""
        collector = MetricsCollector()

        llm_calls = [{"model": "unknown-model-xyz", "input_tokens": 1000, "output_tokens": 500}]

        # Should return unavailable pricing info
        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["pricing_available"] is False
        assert cost_data["total_cost_usd"] is None
        assert "unknown-model-xyz" in cost_data["unavailable_models"]

    def test_summary_generation_with_workflow_metrics(self):
        """Test summary generation when workflow metrics are present."""
        collector = MetricsCollector()

        # Record workflow execution
        collector.record_workflow_start()
        time.sleep(0.01)  # Small delay to ensure measurable duration
        collector.record_node_execution("node1", 10.5)
        collector.record_node_execution("node2", 20.3)
        collector.record_workflow_end()

        # cost_usd populated as the adapter would set it from LiteLLM's response_cost
        llm_calls = [{"model": "gpt-4o-mini", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.000045}]

        summary = collector.get_summary(llm_calls)

        # Check top-level metrics
        assert "duration_ms" in summary
        assert summary["duration_ms"] > 0
        assert summary["total_cost_usd"] == 0.000045
        assert summary["num_nodes"] == 2

        # Check metrics structure
        assert "metrics" in summary
        assert "workflow" in summary["metrics"]

        # Check workflow metrics
        workflow_metrics = summary["metrics"]["workflow"]
        assert workflow_metrics["nodes_executed"] == 2
        assert workflow_metrics["duration_ms"] > 0
        assert workflow_metrics["node_timings"] == {"node1": 10.5, "node2": 20.3}

    def test_timing_methods(self):
        """Test that timing methods correctly record timestamps."""
        collector = MetricsCollector()

        # Test workflow timing
        collector.record_workflow_start()
        assert collector.workflow_start is not None
        workflow_start = collector.workflow_start

        time.sleep(0.01)  # Small delay

        collector.record_workflow_end()
        assert collector.workflow_end is not None
        assert collector.workflow_end > workflow_start

    def test_node_execution_recording(self):
        """Test node execution recording for workflow nodes."""
        collector = MetricsCollector()

        # Record workflow nodes
        collector.record_node_execution("workflow_node1", 30.2)
        collector.record_node_execution("workflow_node2", 40.7)
        collector.record_node_execution("workflow_node3", 50.1)

        # Check workflow nodes
        assert len(collector.workflow_nodes) == 3
        assert collector.workflow_nodes["workflow_node1"] == 30.2
        assert collector.workflow_nodes["workflow_node2"] == 40.7
        assert collector.workflow_nodes["workflow_node3"] == 50.1

    def test_empty_llm_calls_returns_zero_cost(self):
        """Test that empty LLM calls list returns zero cost."""
        collector = MetricsCollector()

        # Test with empty list
        cost_data = collector.calculate_costs([])
        assert cost_data["pricing_available"] is True
        assert cost_data["total_cost_usd"] == 0.0

        # Test summary with empty list
        summary = collector.get_summary([])
        assert summary["total_cost_usd"] == 0.0
        assert summary["metrics"]["total"]["tokens_input"] == 0
        assert summary["metrics"]["total"]["tokens_output"] == 0
        assert summary["metrics"]["total"]["tokens_total"] == 0

    def test_missing_fields_in_llm_usage_handled_gracefully(self):
        """Test that missing fields in LLM usage data are handled gracefully.

        Calls without ``cost_usd`` set surface in ``unavailable_models``;
        calls with ``cost_usd`` contribute to ``partial_cost_usd``. Tokens
        accumulate from every entry regardless of cost availability.
        """
        collector = MetricsCollector()

        # Test various incomplete data scenarios
        llm_calls = [
            {},  # Empty dict
            {"model": "gpt-4o-mini"},  # Missing token counts AND cost_usd → unavailable
            {"input_tokens": 100},  # Missing model AND cost_usd → unavailable as "unknown"
            {"output_tokens": 50},  # Missing model AND cost_usd → unavailable as "unknown"
            {  # Complete entry with explicit cost (as the adapter sets it)
                "model": "gpt-4o-mini",
                "input_tokens": 200,
                "output_tokens": 100,
                "cost_usd": 0.00009,
            },
        ]

        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["pricing_available"] is False  # Some calls lack cost_usd
        assert cost_data["total_cost_usd"] is None
        assert "unknown" in cost_data["unavailable_models"]
        assert "gpt-4o-mini" in cost_data["unavailable_models"]
        assert cost_data["partial_cost_usd"] == 0.00009  # Only the priced entry contributes

        # Test summary generation - tokens from all entries are summed
        summary = collector.get_summary(llm_calls)
        assert summary["total_cost_usd"] is None  # Because some calls lack cost
        assert summary["pricing_available"] is False
        assert summary["metrics"]["total"]["tokens_input"] == 300  # 0 + 100 + 0 + 200
        assert summary["metrics"]["total"]["tokens_output"] == 150  # 0 + 0 + 50 + 100

    def test_cost_rounding_to_six_decimal_places(self):
        """``calculate_costs`` rounds the summed total to 6 decimal places."""
        collector = MetricsCollector()

        # Cost values whose sum has many decimal places
        llm_calls = [
            {"model": "gpt-4o-mini", "input_tokens": 333, "output_tokens": 777, "cost_usd": 1 / 3},
            {"model": "gpt-4o-mini", "input_tokens": 333, "output_tokens": 777, "cost_usd": 1 / 7},
        ]

        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["pricing_available"] is True

        cost = cost_data["total_cost_usd"]
        cost_str = str(cost)
        if "." in cost_str:
            decimal_places = len(cost_str.split(".")[1])
            assert decimal_places <= 6

    def test_duration_measurements_in_milliseconds(self):
        """Test that all duration measurements are correctly converted to milliseconds."""
        collector = MetricsCollector()

        # Manually set times to test conversion to milliseconds
        # Using seconds as the unit (perf_counter returns seconds)
        collector.start_time = 0.0
        collector.workflow_start = 2.0
        collector.workflow_end = 3.2  # 1.2 seconds duration

        # Add a workflow node to ensure metrics are generated
        collector.record_node_execution("w1", 200)

        # Mock the current time for total duration calculation
        with patch("pflow.core.metrics.time.perf_counter", return_value=4.0):
            summary = collector.get_summary([])

        # Check durations are in milliseconds
        assert summary["duration_ms"] == 4000.0  # 4 seconds = 4000ms
        assert summary["metrics"]["workflow"]["duration_ms"] == 1200.0  # 1.2 seconds = 1200ms

    def test_total_metrics_aggregation(self):
        """Test that total metrics correctly aggregate all LLM calls."""
        collector = MetricsCollector()

        llm_calls = [
            {"model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            {"model": "gpt-4o", "input_tokens": 200, "output_tokens": 100},
            {"model": "gpt-3.5-turbo", "input_tokens": 150, "output_tokens": 75},
            {"model": "gpt-4o-mini", "input_tokens": 250, "output_tokens": 125},
        ]

        summary = collector.get_summary(llm_calls)

        # Check total token counts
        assert summary["metrics"]["total"]["tokens_input"] == 700  # 100+200+150+250
        assert summary["metrics"]["total"]["tokens_output"] == 350  # 50+100+75+125
        assert summary["metrics"]["total"]["tokens_total"] == 1050  # 700+350

    def test_model_deduplication_in_workflow(self):
        """Test that duplicate models only appear once in models_used array."""
        collector = MetricsCollector()

        collector.record_node_execution("workflow_node", 20.0)

        llm_calls = [
            # Same model used multiple times
            {"model": "gpt-4", "input_tokens": 400, "output_tokens": 200},
            {"model": "gpt-4", "input_tokens": 500, "output_tokens": 250},
        ]

        summary = collector.get_summary(llm_calls)

        # Each model should appear only once despite multiple uses
        assert summary["metrics"]["workflow"]["models_used"] == ["gpt-4"]

    def test_multiple_models_in_workflow(self):
        """Test that multiple different models are all included in models_used array."""
        collector = MetricsCollector()

        collector.record_node_execution("workflow_node", 20.0)

        llm_calls = [
            # Different models in workflow
            {"model": "gpt-4", "input_tokens": 400, "output_tokens": 200},
            {"model": "gpt-4o-mini", "input_tokens": 500, "output_tokens": 250},
            {"model": "gpt-3.5-turbo", "input_tokens": 600, "output_tokens": 300},
        ]

        summary = collector.get_summary(llm_calls)

        # All unique models should be present (order doesn't matter, so use sets)
        workflow_models = set(summary["metrics"]["workflow"]["models_used"])
        assert workflow_models == {"gpt-4", "gpt-4o-mini", "gpt-3.5-turbo"}

    def test_empty_llm_calls_shows_zero_tokens_and_empty_models(self):
        """Test that workflow section with no LLM calls shows 0 tokens and empty models array."""
        collector = MetricsCollector()

        # Create workflow section but no LLM calls
        collector.record_node_execution("workflow_node", 20.0)

        summary = collector.get_summary([])  # Empty LLM calls

        # Workflow should have zeros and empty array
        workflow_metrics = summary["metrics"]["workflow"]
        assert workflow_metrics["tokens_input"] == 0
        assert workflow_metrics["tokens_output"] == 0
        assert workflow_metrics["tokens_total"] == 0
        assert workflow_metrics["models_used"] == []
