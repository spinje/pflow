"""Regression tests for aggregate_llm_usage_with_retries (Task #465 verification)."""

import pytest

from pflow.runtime.workflow_trace import WorkflowTraceCollector


class TestAggregateLLMUsageWithRetries:
    """Test aggregate_llm_usage_with_retries with None-value edge cases."""

    @pytest.fixture
    def collector(self, tmp_path):
        """Create a trace collector instance."""
        workflow_path = tmp_path / "test.pflow.md"
        return WorkflowTraceCollector(workflow_path=str(workflow_path))

    def test_main_none_retry_values_aggregates_correctly(self, collector):
        """Regression test for None token aggregation crash.

        When main llm_usage has explicit None values and retries have real values,
        aggregation should treat None as 0. Original bug: `None += int` crashed.

        Bug found during verification adversarial testing on 2026-06-03.
        """
        llm_usage = {
            "input_tokens": None,  # Explicit None (not absent)
            "output_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
            "num_turns": None,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "retries": [
                {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_usd": 0.01,
                    "num_turns": 1,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                }
            ],
        }

        result = collector.aggregate_llm_usage_with_retries(llm_usage)

        # Should treat None as 0 and aggregate correctly
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["total_tokens"] == 150  # Recomputed
        assert result["cost_usd"] == 0.01
        assert result["num_turns"] == 1

    def test_multiple_retries_with_mixed_none_values(self, collector):
        """Regression test for retry loop None-value crashes.

        When retry entries have explicit None values, the aggregation loop
        should treat them as 0. Original bug: `int += None` in retry loop crashed.

        Bug found during verification adversarial testing on 2026-06-03.
        """
        llm_usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "cost_usd": 0.01,
            "num_turns": 1,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 20,
            "retries": [
                {
                    "input_tokens": None,  # Explicit None in retry
                    "output_tokens": 30,
                    "cost_usd": None,
                    "num_turns": 1,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 5,
                },
                {
                    "input_tokens": 40,
                    "output_tokens": None,  # Explicit None in retry
                    "cost_usd": 0.005,
                    "num_turns": None,  # Explicit None
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            ],
        }

        result = collector.aggregate_llm_usage_with_retries(llm_usage)

        # Should treat None as 0 in retry loop
        assert result["input_tokens"] == 140  # 100 + 0 + 40
        assert result["output_tokens"] == 80  # 50 + 30 + 0
        assert result["total_tokens"] == 220  # Recomputed
        assert result["cost_usd"] == 0.015  # 0.01 + 0 + 0.005
        assert result["num_turns"] == 2  # 1 + 1 + 0
        assert result["cache_read_input_tokens"] == 25  # 20 + 5 + 0

    def test_no_retries_preserves_original(self, collector):
        """When there are no retries, original llm_usage is returned unchanged."""
        llm_usage = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
            "num_turns": None,
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None,
            "retries": [],  # No retries
        }

        result = collector.aggregate_llm_usage_with_retries(llm_usage)

        # Should return original unchanged (no aggregation needed)
        assert result is llm_usage
        assert result["input_tokens"] is None  # Preserved
        assert result["output_tokens"] is None
        assert result["num_turns"] is None

    def test_zero_values_aggregate_correctly(self, collector):
        """Zero values should aggregate to zero (not None)."""
        llm_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0,
            "num_turns": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "retries": [],
        }

        result = collector.aggregate_llm_usage_with_retries(llm_usage)

        # Zero is a valid numeric value, should stay zero
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_tokens"] == 0
        assert result["cost_usd"] == 0
        assert result["num_turns"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
