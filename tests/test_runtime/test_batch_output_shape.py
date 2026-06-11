"""Unit tests for the shared batch output-shape builder.

``build_batch_output`` is the single source of the batch output contract
consumed by BOTH the engine's ``_aggregate_batch_results`` and the dry-run
planner's ``_build_batch_output_shape``. These tests pin the contract
directly; engine/planner parity rides on both callers delegating here
(pinned end-to-end by tests/test_execution/test_plan_drift.py).
"""

from pflow.runtime.engine.batch_executor import build_batch_output
from pflow.runtime.engine.types import BatchConfig


def _config(**overrides) -> BatchConfig:
    defaults = {
        "items_template": "${items}",
        "item_alias": "item",
        "error_handling": "continue",
        "parallel": False,
        "max_concurrent": 5,
        "max_retries": 1,
        "retry_wait": 0,
    }
    defaults.update(overrides)
    return BatchConfig(**defaults)


class TestBuildBatchOutput:
    def test_top_level_keys_match_contract(self):
        output = build_batch_output(
            [{"a": 1}], total_count=2, errors=[{"index": 1, "error": "boom"}], timing_stats=None, batch_config=_config()
        )
        assert set(output) == {"results", "count", "success_count", "error_count", "errors", "batch_metadata"}
        assert output["results"] == [{"a": 1}]
        assert output["count"] == 2
        assert output["error_count"] == 1

    def test_batch_metadata_keys_match_contract(self):
        output = build_batch_output([], total_count=0, errors=[], timing_stats=None, batch_config=_config())
        assert set(output["batch_metadata"]) == {
            "parallel",
            "max_concurrent",
            "max_retries",
            "retry_wait",
            "execution_mode",
            "timing",
        }

    def test_sequential_nulls_max_concurrent(self):
        output = build_batch_output(
            [], total_count=0, errors=[], timing_stats=None, batch_config=_config(parallel=False)
        )
        assert output["batch_metadata"]["max_concurrent"] is None
        assert output["batch_metadata"]["execution_mode"] == "sequential"

    def test_parallel_keeps_max_concurrent(self):
        output = build_batch_output(
            [], total_count=0, errors=[], timing_stats=None, batch_config=_config(parallel=True, max_concurrent=3)
        )
        assert output["batch_metadata"]["max_concurrent"] == 3
        assert output["batch_metadata"]["execution_mode"] == "parallel"

    def test_zero_retry_wait_is_null(self):
        output = build_batch_output([], total_count=0, errors=[], timing_stats=None, batch_config=_config(retry_wait=0))
        assert output["batch_metadata"]["retry_wait"] is None

    def test_positive_retry_wait_preserved(self):
        output = build_batch_output(
            [], total_count=0, errors=[], timing_stats=None, batch_config=_config(retry_wait=1.5)
        )
        assert output["batch_metadata"]["retry_wait"] == 1.5

    def test_success_count_is_len_results(self):
        output = build_batch_output(
            [{"a": 1}, {"b": 2}],
            total_count=5,
            errors=[{"index": 0, "error": "x"}],
            timing_stats=None,
            batch_config=_config(),
        )
        assert output["success_count"] == 2

    def test_errors_always_a_list(self):
        """``errors`` is declared ``type: array`` — never None (GH #484)."""
        output = build_batch_output([], total_count=0, errors=[], timing_stats=None, batch_config=_config())
        assert output["errors"] == []

    def test_timing_stats_passed_through(self):
        timing = {"total_items_ms": 10.0, "avg_item_ms": 5.0, "min_item_ms": 4.0, "max_item_ms": 6.0}
        output = build_batch_output([{}], total_count=1, errors=[], timing_stats=timing, batch_config=_config())
        assert output["batch_metadata"]["timing"] == timing
