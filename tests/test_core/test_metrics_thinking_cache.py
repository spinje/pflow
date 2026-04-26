"""Test metrics collection for thinking and caching tokens."""

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
            },
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 800,
                "output_tokens": 600,
                "thinking_tokens": 1500,
                "thinking_budget": 4096,
                "node_id": "WorkflowGeneratorNode",
            },
        ]

        collector.record_workflow_start()
        for call in llm_calls:
            collector.record_node_execution(call["node_id"], 1000)
        collector.record_workflow_end()

        summary = collector.get_summary(llm_calls)

        # Check thinking_performance is present
        assert "thinking_performance" in summary
        assert summary["thinking_performance"]["thinking_tokens_used"] == 3548
        assert summary["thinking_performance"]["thinking_budget_allocated"] == 8192
        assert summary["thinking_performance"]["thinking_utilization_pct"] == 43.3

        # Check thinking tokens in detailed metrics
        assert summary["metrics"]["workflow"]["thinking_tokens"] == 3548
        assert summary["metrics"]["workflow"]["thinking_budget"] == 8192

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
            },
            {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "input_tokens": 800,
                "output_tokens": 600,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 2914,
                "node_id": "WorkflowGeneratorNode",
            },
        ]

        collector.record_workflow_start()
        for call in llm_calls:
            collector.record_node_execution(call["node_id"], 1000)
        collector.record_workflow_end()

        summary = collector.get_summary(llm_calls)

        # Check cache_performance is present
        assert "cache_performance" in summary
        assert summary["cache_performance"]["cache_creation_tokens"] == 2914
        assert summary["cache_performance"]["cache_read_tokens"] == 2914
        assert summary["cache_performance"]["cache_efficiency_pct"] == 50.0
        assert summary["cache_performance"]["cache_total_tokens"] == 5828

        # Check cache tokens in detailed metrics
        assert summary["metrics"]["workflow"]["cache_creation_tokens"] == 2914
        assert summary["metrics"]["workflow"]["cache_read_tokens"] == 2914

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
            },
        ]

        collector.record_workflow_start()
        for call in llm_calls:
            collector.record_node_execution(call["node_id"], 1000)
        collector.record_workflow_end()

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
                "cost_usd": 0.0105,  # adapter sets this from LiteLLM's response_cost
                "node_id": "SomeNode",
            },
        ]

        collector.record_workflow_start()
        for call in llm_calls:
            collector.record_node_execution(call["node_id"], 1000)
        collector.record_workflow_end()

        summary = collector.get_summary(llm_calls)

        # Check that cache_performance and thinking_performance are not present
        assert "cache_performance" not in summary
        assert "thinking_performance" not in summary

        # Basic metrics still work — cost flows through, tokens accumulate
        assert summary["total_cost_usd"] == 0.0105
        assert summary["metrics"]["workflow"]["tokens_total"] == 1500
