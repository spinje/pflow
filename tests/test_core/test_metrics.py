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
        assert collector.planner_start is None
        assert collector.planner_end is None
        assert collector.workflow_start is None
        assert collector.workflow_end is None
        assert collector.planner_nodes == {}
        assert collector.workflow_nodes == {}

    def test_aggregation_from_multiple_llm_calls(self):
        """Test that costs from multiple LLM calls add up correctly."""
        collector = MetricsCollector()

        llm_calls = [
            {"model": "gpt-4o-mini", "input_tokens": 100, "output_tokens": 50},
            {"model": "gpt-4o-mini", "input_tokens": 200, "output_tokens": 100},
            {"model": "gpt-4o-mini", "input_tokens": 150, "output_tokens": 75},
        ]

        # Calculate expected cost
        # Total input: 450 tokens, output: 225 tokens
        # gpt-4o-mini pricing: $0.15/M input, $0.60/M output
        expected_input_cost = (450 / 1_000_000) * 0.15
        expected_output_cost = (225 / 1_000_000) * 0.60
        expected_total = round(expected_input_cost + expected_output_cost, 6)

        total_cost = collector.calculate_costs(llm_calls)
        assert total_cost == expected_total

    def test_cost_calculation_for_different_models(self):
        """Test that pricing is accurate for different models."""
        collector = MetricsCollector()

        # Test various models with known pricing
        test_cases = [
            {
                "model": "anthropic/claude-3-haiku-20240307",
                "input_tokens": 1000,
                "output_tokens": 500,
                "expected_cost": round((1000 / 1_000_000 * 0.25) + (500 / 1_000_000 * 1.25), 6),
            },
            {
                "model": "gpt-4",
                "input_tokens": 2000,
                "output_tokens": 1000,
                "expected_cost": round((2000 / 1_000_000 * 30.0) + (1000 / 1_000_000 * 60.0), 6),
            },
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 5000,
                "output_tokens": 2500,
                "expected_cost": round((5000 / 1_000_000 * 3.0) + (2500 / 1_000_000 * 15.0), 6),
            },
            {
                "model": "gemini-1.5-flash",
                "input_tokens": 10000,
                "output_tokens": 5000,
                "expected_cost": round((10000 / 1_000_000 * 0.075) + (5000 / 1_000_000 * 0.30), 6),
            },
        ]

        for test_case in test_cases:
            llm_calls = [
                {
                    "model": test_case["model"],
                    "input_tokens": test_case["input_tokens"],
                    "output_tokens": test_case["output_tokens"],
                }
            ]

            cost = collector.calculate_costs(llm_calls)
            assert cost == test_case["expected_cost"], f"Failed for model {test_case['model']}"

    def test_unknown_model_uses_default_pricing(self):
        """Test that unknown models use default pricing."""
        collector = MetricsCollector()

        llm_calls = [{"model": "unknown-model-xyz", "input_tokens": 1000, "output_tokens": 500}]

        # Should use default pricing (gpt-4o-mini): $0.15/M input, $0.60/M output
        expected_cost = round((1000 / 1_000_000 * 0.15) + (500 / 1_000_000 * 0.60), 6)

        cost = collector.calculate_costs(llm_calls)
        assert cost == expected_cost

    def test_summary_generation_without_planner_metrics(self):
        """Test summary generation when only workflow metrics are present."""
        collector = MetricsCollector()

        # Record workflow execution
        collector.record_workflow_start()
        time.sleep(0.01)  # Small delay to ensure measurable duration
        collector.record_node_execution("node1", 10.5, is_planner=False)
        collector.record_node_execution("node2", 20.3, is_planner=False)
        collector.record_workflow_end()

        llm_calls = [{"model": "gpt-4o-mini", "input_tokens": 100, "output_tokens": 50, "is_planner": False}]

        summary = collector.get_summary(llm_calls)

        # Check top-level metrics
        assert "duration_ms" in summary
        assert summary["duration_ms"] > 0
        assert summary["duration_planner_ms"] is None
        assert summary["total_cost_usd"] > 0
        assert summary["num_nodes"] == 2

        # Check metrics structure
        assert "metrics" in summary
        assert "workflow" in summary["metrics"]
        assert "planner" not in summary["metrics"]

        # Check workflow metrics
        workflow_metrics = summary["metrics"]["workflow"]
        assert workflow_metrics["nodes_executed"] == 2
        assert workflow_metrics["duration_ms"] > 0
        assert workflow_metrics["node_timings"] == {"node1": 10.5, "node2": 20.3}

    def test_summary_generation_with_planner_metrics(self):
        """Test summary generation when both planner and workflow metrics are present."""
        collector = MetricsCollector()

        # Record planner execution
        collector.record_planner_start()
        time.sleep(0.01)
        collector.record_node_execution("planner_node1", 5.2, is_planner=True)
        collector.record_planner_end()

        # Record workflow execution
        collector.record_workflow_start()
        time.sleep(0.01)
        collector.record_node_execution("workflow_node1", 15.7, is_planner=False)
        collector.record_workflow_end()

        llm_calls = [
            {"model": "gpt-4o-mini", "input_tokens": 50, "output_tokens": 25, "is_planner": True},
            {"model": "gpt-4o-mini", "input_tokens": 100, "output_tokens": 50, "is_planner": False},
        ]

        summary = collector.get_summary(llm_calls)

        # Check top-level metrics
        assert summary["duration_planner_ms"] > 0
        assert summary["num_nodes"] == 2

        # Check both planner and workflow metrics exist
        assert "planner" in summary["metrics"]
        assert "workflow" in summary["metrics"]

        # Check planner metrics
        planner_metrics = summary["metrics"]["planner"]
        assert planner_metrics["nodes_executed"] == 1
        assert planner_metrics["node_timings"] == {"planner_node1": 5.2}

        # Check workflow metrics
        workflow_metrics = summary["metrics"]["workflow"]
        assert workflow_metrics["nodes_executed"] == 1
        assert workflow_metrics["node_timings"] == {"workflow_node1": 15.7}

    def test_timing_methods(self):
        """Test that timing methods correctly record timestamps."""
        collector = MetricsCollector()

        # Test planner timing
        collector.record_planner_start()
        assert collector.planner_start is not None
        start_time = collector.planner_start

        time.sleep(0.01)  # Small delay

        collector.record_planner_end()
        assert collector.planner_end is not None
        assert collector.planner_end > start_time

        # Test workflow timing
        collector.record_workflow_start()
        assert collector.workflow_start is not None
        workflow_start = collector.workflow_start

        time.sleep(0.01)  # Small delay

        collector.record_workflow_end()
        assert collector.workflow_end is not None
        assert collector.workflow_end > workflow_start

    def test_node_execution_recording(self):
        """Test node execution recording for both planner and workflow nodes."""
        collector = MetricsCollector()

        # Record planner nodes
        collector.record_node_execution("planner_node1", 10.5, is_planner=True)
        collector.record_node_execution("planner_node2", 20.3, is_planner=True)

        # Record workflow nodes
        collector.record_node_execution("workflow_node1", 30.2, is_planner=False)
        collector.record_node_execution("workflow_node2", 40.7, is_planner=False)
        collector.record_node_execution("workflow_node3", 50.1, is_planner=False)

        # Check planner nodes
        assert len(collector.planner_nodes) == 2
        assert collector.planner_nodes["planner_node1"] == 10.5
        assert collector.planner_nodes["planner_node2"] == 20.3

        # Check workflow nodes
        assert len(collector.workflow_nodes) == 3
        assert collector.workflow_nodes["workflow_node1"] == 30.2
        assert collector.workflow_nodes["workflow_node2"] == 40.7
        assert collector.workflow_nodes["workflow_node3"] == 50.1

    def test_empty_llm_calls_returns_zero_cost(self):
        """Test that empty LLM calls list returns zero cost."""
        collector = MetricsCollector()

        # Test with empty list
        cost = collector.calculate_costs([])
        assert cost == 0.0

        # Test summary with empty list
        summary = collector.get_summary([])
        assert summary["total_cost_usd"] == 0.0
        assert summary["metrics"]["total"]["tokens_input"] == 0
        assert summary["metrics"]["total"]["tokens_output"] == 0
        assert summary["metrics"]["total"]["tokens_total"] == 0

    def test_missing_fields_in_llm_usage_handled_gracefully(self):
        """Test that missing fields in LLM usage data are handled gracefully."""
        collector = MetricsCollector()

        # Test various incomplete data scenarios
        llm_calls = [
            {},  # Empty dict
            {"model": "gpt-4o-mini"},  # Missing token counts
            {"input_tokens": 100},  # Missing model and output tokens
            {"output_tokens": 50},  # Missing model and input tokens
            {  # Complete valid entry
                "model": "gpt-4o-mini",
                "input_tokens": 200,
                "output_tokens": 100,
            },
        ]

        # Calculate expected cost for all entries with missing fields treated as 0
        # Entry 1: Empty dict - skipped
        # Entry 2: gpt-4o-mini with 0 tokens - no cost
        # Entry 3: unknown model with 100 input, 0 output
        cost3 = round((100 / 1_000_000 * 0.15), 6)  # Default pricing
        # Entry 4: unknown model with 0 input, 50 output
        cost4 = round((50 / 1_000_000 * 0.60), 6)  # Default pricing
        # Entry 5: Complete entry
        cost5 = round((200 / 1_000_000 * 0.15) + (100 / 1_000_000 * 0.60), 6)

        expected_cost = round(cost3 + cost4 + cost5, 6)

        cost = collector.calculate_costs(llm_calls)
        assert cost == expected_cost

        # Test summary generation - tokens from all entries are summed
        summary = collector.get_summary(llm_calls)
        assert summary["total_cost_usd"] == expected_cost
        assert summary["metrics"]["total"]["tokens_input"] == 300  # 0 + 100 + 0 + 200
        assert summary["metrics"]["total"]["tokens_output"] == 150  # 0 + 0 + 50 + 100

    def test_cost_rounding_to_six_decimal_places(self):
        """Test that costs are consistently rounded to 6 decimal places."""
        collector = MetricsCollector()

        # Use token counts that would produce many decimal places
        llm_calls = [
            {
                "model": "gpt-4o-mini",
                "input_tokens": 333,  # Will produce repeating decimals
                "output_tokens": 777,
            }
        ]

        cost = collector.calculate_costs(llm_calls)

        # Check that the cost has at most 6 decimal places
        cost_str = str(cost)
        if "." in cost_str:
            decimal_places = len(cost_str.split(".")[1])
            assert decimal_places <= 6

    def test_separate_cost_tracking_for_planner_and_workflow(self):
        """Test that planner and workflow costs are tracked separately."""
        collector = MetricsCollector()

        # Record some nodes for context
        collector.record_node_execution("planner_node", 10.0, is_planner=True)
        collector.record_node_execution("workflow_node", 20.0, is_planner=False)

        llm_calls = [
            {"model": "gpt-4o", "input_tokens": 1000, "output_tokens": 500, "is_planner": True},
            {"model": "gpt-4o-mini", "input_tokens": 2000, "output_tokens": 1000, "is_planner": False},
            {"model": "gpt-3.5-turbo", "input_tokens": 500, "output_tokens": 250, "is_planner": True},
        ]

        summary = collector.get_summary(llm_calls)

        # Calculate expected costs
        planner_cost = round(
            (1000 / 1_000_000 * 5.0)
            + (500 / 1_000_000 * 15.0)  # gpt-4o
            + (500 / 1_000_000 * 0.5)
            + (250 / 1_000_000 * 1.5),  # gpt-3.5-turbo
            6,
        )
        workflow_cost = round(
            (2000 / 1_000_000 * 0.15) + (1000 / 1_000_000 * 0.60),  # gpt-4o-mini
            6,
        )

        assert summary["metrics"]["planner"]["cost_usd"] == planner_cost
        assert summary["metrics"]["workflow"]["cost_usd"] == workflow_cost
        assert summary["total_cost_usd"] == round(planner_cost + workflow_cost, 6)

    def test_duration_measurements_in_milliseconds(self):
        """Test that all duration measurements are correctly converted to milliseconds."""
        collector = MetricsCollector()

        # Manually set times to test conversion to milliseconds
        # Using seconds as the unit (perf_counter returns seconds)
        collector.start_time = 0.0
        collector.planner_start = 1.0
        collector.planner_end = 1.5  # 0.5 seconds duration
        collector.workflow_start = 2.0
        collector.workflow_end = 3.2  # 1.2 seconds duration

        # Add some nodes to ensure metrics are generated
        collector.record_node_execution("p1", 100, is_planner=True)
        collector.record_node_execution("w1", 200, is_planner=False)

        # Mock the current time for total duration calculation
        with patch("pflow.core.metrics.time.perf_counter", return_value=4.0):
            summary = collector.get_summary([])

        # Check durations are in milliseconds
        assert summary["duration_ms"] == 4000.0  # 4 seconds = 4000ms
        assert summary["duration_planner_ms"] == 500.0  # 0.5 seconds = 500ms
        assert summary["metrics"]["planner"]["duration_ms"] == 500.0
        assert summary["metrics"]["workflow"]["duration_ms"] == 1200.0  # 1.2 seconds = 1200ms

    def test_node_id_uniqueness_per_category(self):
        """Test that node IDs can be reused between planner and workflow categories."""
        collector = MetricsCollector()

        # Use same node ID for both planner and workflow
        collector.record_node_execution("shared_node", 10.0, is_planner=True)
        collector.record_node_execution("shared_node", 20.0, is_planner=False)

        # They should be stored separately
        assert collector.planner_nodes["shared_node"] == 10.0
        assert collector.workflow_nodes["shared_node"] == 20.0

        # Overwriting should work within same category
        collector.record_node_execution("shared_node", 15.0, is_planner=True)
        assert collector.planner_nodes["shared_node"] == 15.0
        assert collector.workflow_nodes["shared_node"] == 20.0  # Unchanged

    def test_total_metrics_aggregation(self):
        """Test that total metrics correctly aggregate all LLM calls."""
        collector = MetricsCollector()

        llm_calls = [
            {"model": "gpt-4", "input_tokens": 100, "output_tokens": 50, "is_planner": True},
            {"model": "gpt-4o", "input_tokens": 200, "output_tokens": 100, "is_planner": False},
            {"model": "gpt-3.5-turbo", "input_tokens": 150, "output_tokens": 75, "is_planner": True},
            {"model": "gpt-4o-mini", "input_tokens": 250, "output_tokens": 125, "is_planner": False},
        ]

        summary = collector.get_summary(llm_calls)

        # Check total token counts
        assert summary["metrics"]["total"]["tokens_input"] == 700  # 100+200+150+250
        assert summary["metrics"]["total"]["tokens_output"] == 350  # 50+100+75+125
        assert summary["metrics"]["total"]["tokens_total"] == 1050  # 700+350

        # Verify total cost matches sum of all calls
        total_cost = collector.calculate_costs(llm_calls)
        assert summary["metrics"]["total"]["cost_usd"] == total_cost
        assert summary["total_cost_usd"] == total_cost
