"""Test metrics collection for thinking and caching tokens."""

import pytest

from pflow.core.metrics import MetricsCollector


class TestMetricsThinkingCache:
    """Test thinking and caching metrics collection."""

    def test_thinking_tokens_aggregation(self):
        """Test that thinking tokens are properly aggregated."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 1000,
                "output_tokens": 500,
                "thinking_tokens": 2048,
                "thinking_budget": 4096,
                "node_id": "PlanningNode",
                "is_planner": True,
            },
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 800,
                "output_tokens": 600,
                "thinking_tokens": 1500,
                "thinking_budget": 4096,
                "node_id": "WorkflowGeneratorNode",
                "is_planner": True,
            },
        ]

        collector.record_planner_start()
        for call in llm_calls:
            collector.record_node_execution(call["node_id"], 1000, is_planner=True)
        collector.record_planner_end()

        summary = collector.get_summary(llm_calls)

        # Check thinking_performance is present
        assert "thinking_performance" in summary
        assert summary["thinking_performance"]["thinking_tokens_used"] == 3548
        assert summary["thinking_performance"]["thinking_budget_allocated"] == 8192
        assert summary["thinking_performance"]["thinking_utilization_pct"] == 43.3

        # Check thinking tokens in detailed metrics
        assert summary["metrics"]["planner"]["thinking_tokens"] == 3548
        assert summary["metrics"]["planner"]["thinking_budget"] == 8192

    def test_cache_tokens_aggregation(self):
        """Test that cache tokens are properly aggregated."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_creation_input_tokens": 2914,
                "cache_read_input_tokens": 0,
                "node_id": "PlanningNode",
                "is_planner": True,
            },
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 800,
                "output_tokens": 600,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 2914,
                "node_id": "WorkflowGeneratorNode",
                "is_planner": True,
            },
        ]

        collector.record_planner_start()
        for call in llm_calls:
            collector.record_node_execution(call["node_id"], 1000, is_planner=True)
        collector.record_planner_end()

        summary = collector.get_summary(llm_calls)

        # Check cache_performance is present
        assert "cache_performance" in summary
        assert summary["cache_performance"]["cache_creation_tokens"] == 2914
        assert summary["cache_performance"]["cache_read_tokens"] == 2914
        assert summary["cache_performance"]["cache_efficiency_pct"] == 50.0
        assert summary["cache_performance"]["cache_total_tokens"] == 5828

        # Check cache tokens in detailed metrics
        assert summary["metrics"]["planner"]["cache_creation_tokens"] == 2914
        assert summary["metrics"]["planner"]["cache_read_tokens"] == 2914

    def test_combined_thinking_and_cache(self):
        """Test that both thinking and cache metrics work together."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_creation_input_tokens": 2914,
                "cache_read_input_tokens": 0,
                "thinking_tokens": 2048,
                "thinking_budget": 4096,
                "node_id": "PlanningNode",
                "is_planner": True,
            },
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 800,
                "output_tokens": 600,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 2914,
                "thinking_tokens": 1500,
                "thinking_budget": 4096,
                "node_id": "WorkflowGeneratorNode",
                "is_planner": True,
            },
        ]

        collector.record_planner_start()
        for call in llm_calls:
            collector.record_node_execution(call["node_id"], 1000, is_planner=True)
        collector.record_planner_end()

        summary = collector.get_summary(llm_calls)

        # Check both sections are present
        assert "cache_performance" in summary
        assert "thinking_performance" in summary

        # Verify values
        assert summary["cache_performance"]["cache_total_tokens"] == 5828
        assert summary["thinking_performance"]["thinking_tokens_used"] == 3548

    def test_no_thinking_or_cache_tokens(self):
        """Test that metrics work when no thinking or cache tokens are present."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 1000,
                "output_tokens": 500,
                "node_id": "SomeNode",
                "is_planner": False,
            },
        ]

        collector.record_workflow_start()
        for call in llm_calls:
            collector.record_node_execution(call["node_id"], 1000, is_planner=False)
        collector.record_workflow_end()

        summary = collector.get_summary(llm_calls)

        # Check that cache_performance and thinking_performance are not present
        assert "cache_performance" not in summary
        assert "thinking_performance" not in summary

        # But the basic metrics should still work
        assert summary["total_cost_usd"] > 0
        assert summary["metrics"]["workflow"]["tokens_total"] == 1500

    def test_thinking_cost_calculation(self):
        """Test that thinking tokens are properly included in cost calculation."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 1000,  # $0.003
                "output_tokens": 500,  # $0.0075
                "thinking_tokens": 1000,  # $0.015 (billed at output rate)
                "node_id": "PlanningNode",
                "is_planner": True,
            },
        ]

        cost_data = collector.calculate_costs(llm_calls)

        # Expected: 0.003 + 0.0075 + 0.015 = 0.0255
        assert cost_data["pricing_available"] is True
        assert cost_data["total_cost_usd"] == pytest.approx(0.0255, rel=1e-5)

    def test_cache_cost_calculation(self):
        """Test that cache tokens affect cost calculation correctly."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 1000,  # Regular input: $0.003
                "output_tokens": 500,  # Output: $0.0075
                "cache_creation_input_tokens": 1000,  # Cache creation: $0.006 (2x cost)
                "cache_read_input_tokens": 1000,  # Cache read: $0.0003 (10% cost)
                "node_id": "PlanningNode",
                "is_planner": True,
            },
        ]

        cost_data = collector.calculate_costs(llm_calls)

        # Expected: 0.003 + 0.0075 + 0.006 + 0.0003 = 0.0168
        assert cost_data["pricing_available"] is True
        assert cost_data["total_cost_usd"] == pytest.approx(0.0168, rel=1e-5)
