"""Tests for the MetricsCollector class."""

import time
from unittest.mock import patch

from pflow.core.metrics import MetricsCollector, format_unavailable_models_phrase
from pflow.core.validation_utils import VALIDATION_PLACEHOLDER


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
        """Test that unknown models are handled gracefully.

        Bundle 7 / F#17 deferred: ``unavailable_models`` is now a list of
        ``{"name": str, "calls": int}`` dicts so renderers can surface
        per-model call counts.
        """
        collector = MetricsCollector()

        llm_calls = [{"model": "unknown-model-xyz", "input_tokens": 1000, "output_tokens": 500}]

        # Should return unavailable pricing info
        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["pricing_available"] is False
        assert cost_data["total_cost_usd"] is None
        assert cost_data["unavailable_models"] == [{"name": "unknown-model-xyz", "calls": 1}]

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

        Calls without ``cost_usd`` and WITH a real model name surface in
        ``unavailable_models``; calls without a recorded model accumulate
        into ``unavailable_models_unnamed_count`` (never the opaque
        ``"unknown"`` string). Calls with ``cost_usd`` contribute to
        ``partial_cost_usd``. Tokens accumulate from every entry regardless
        of cost availability.
        """
        collector = MetricsCollector()

        # Test various incomplete data scenarios. Empty dicts are skipped
        # via the ``if not call:`` guard, so they don't contribute anywhere.
        llm_calls = [
            {},  # Empty dict — skipped by the falsy guard
            {"model": "gpt-4o-mini"},  # Missing token counts AND cost_usd → unavailable (named)
            {"input_tokens": 100},  # Missing model AND cost_usd → unnamed count
            {"output_tokens": 50},  # Missing model AND cost_usd → unnamed count
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
        # The "unknown" opaque sentinel is GONE — real names land in
        # unavailable_models, genuinely-unrecorded calls are counted instead.
        names = [entry["name"] for entry in cost_data["unavailable_models"]]
        assert "unknown" not in names
        assert "gpt-4o-mini" in names
        # 2 unnamed: {input_tokens}, {output_tokens} (the empty {} is skipped)
        assert cost_data["unavailable_models_unnamed_count"] == 2
        assert cost_data["partial_cost_usd"] == 0.00009  # Only the priced entry contributes

        # Test summary generation - tokens from all entries are summed
        summary = collector.get_summary(llm_calls)
        assert summary["total_cost_usd"] is None  # Because some calls lack cost
        assert summary["pricing_available"] is False
        assert summary["unavailable_models_unnamed_count"] == 2
        assert summary["metrics"]["total"]["tokens_input"] == 300  # 0 + 100 + 0 + 200
        assert summary["metrics"]["total"]["tokens_output"] == 150  # 0 + 0 + 50 + 100
        assert summary["metrics"]["total"]["unavailable_models_unnamed_count"] == 2

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


class TestUnnamedCallTracking:
    """Genuinely-unrecorded model calls go into the unnamed counter, not the
    opaque ``"unknown"`` string in ``unavailable_models``.
    """

    def test_call_without_model_goes_to_unnamed_count(self):
        """A call dict with no ``model`` field but ``cost_usd: None`` lands
        in ``unavailable_models_unnamed_count``, NOT ``unavailable_models``."""
        collector = MetricsCollector()

        llm_calls = [
            # Genuinely unrecorded — no model field
            {"input_tokens": 100, "output_tokens": 50, "cost_usd": None},
        ]

        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["pricing_available"] is False
        assert cost_data["total_cost_usd"] is None
        assert cost_data["unavailable_models"] == []
        assert cost_data["unavailable_models_unnamed_count"] == 1

    def test_empty_string_model_treated_as_unnamed(self):
        """An empty string ``model`` value is treated as unnamed."""
        collector = MetricsCollector()

        llm_calls = [{"model": "", "cost_usd": None}]

        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["unavailable_models"] == []
        assert cost_data["unavailable_models_unnamed_count"] == 1

    def test_validation_placeholder_treated_as_unnamed(self):
        """A call carrying the S#4 ``__validation_placeholder__`` sentinel
        for ``model`` is treated as unnamed (the sentinel must never surface
        to users)."""
        collector = MetricsCollector()

        llm_calls = [{"model": VALIDATION_PLACEHOLDER, "cost_usd": None}]

        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["unavailable_models"] == []
        assert cost_data["unavailable_models_unnamed_count"] == 1
        # Sentinel must not appear in the displayed models_used list either
        summary = collector.get_summary(llm_calls)
        workflow_metrics = summary["metrics"].get("workflow")
        if workflow_metrics is not None:
            assert VALIDATION_PLACEHOLDER not in workflow_metrics["models_used"]

    def test_mixed_named_and_unnamed_split_correctly(self):
        """A real-name unpriced call and a no-model unpriced call land in
        their respective tracks; both contribute to the unavailability
        signal."""
        collector = MetricsCollector()

        llm_calls = [
            {"model": "anthropic/claude-future"},  # named, unpriced
            {"input_tokens": 5},  # unnamed, unpriced
        ]

        cost_data = collector.calculate_costs(llm_calls)
        assert cost_data["unavailable_models"] == [{"name": "anthropic/claude-future", "calls": 1}]
        assert cost_data["unavailable_models_unnamed_count"] == 1

    def test_workflow_trace_accumulator_unnamed_call_path(self):
        """The trace accumulator mirrors the same behavior — no ``"unknown"``
        sentinel in its ``unavailable_models``; unnamed calls increment the
        count instead."""
        from pflow.runtime.workflow_trace import _LLMSummaryAccumulator

        agg = _LLMSummaryAccumulator()
        agg.add_leaf({"input_tokens": 100, "cost_usd": None})  # no model
        agg.add_leaf({"model": "ollama/llama3.2", "cost_usd": None})  # real name
        agg.add_leaf({"model": VALIDATION_PLACEHOLDER, "cost_usd": None})  # sentinel

        result = agg.as_dict()
        assert result["pricing_available"] is False
        assert result["unavailable_models"] == [{"name": "ollama/llama3.2", "calls": 1}]
        assert result["unavailable_models_unnamed_count"] == 2
        assert VALIDATION_PLACEHOLDER not in result["models_used"]


class TestFormatUnavailableModelsPhrase:
    """Tests for the shared rendering helper.

    Bundle 7 / F#17 deferred: helper now takes ``Mapping[str, int]`` so it
    can render per-model call counts; multiple names sort alphabetically
    for deterministic output.
    """

    def test_single_named_model_singular(self):
        # 1 call uses singular noun
        phrase = format_unavailable_models_phrase({"gpt-5": 1}, 0)
        assert phrase == "gpt-5 (1 call)"

    def test_single_named_model_plural(self):
        # Multiple calls use plural noun
        phrase = format_unavailable_models_phrase({"gpt-5": 3}, 0)
        assert phrase == "gpt-5 (3 calls)"

    def test_named_models_sort_by_name(self):
        # Deterministic order regardless of dict insertion order
        phrase = format_unavailable_models_phrase(
            {"openai/gpt-5": 4, "anthropic/claude-future": 2},
            0,
        )
        assert phrase == "anthropic/claude-future (2 calls), openai/gpt-5 (4 calls)"

    def test_unnamed_count_only_singular(self):
        phrase = format_unavailable_models_phrase({}, 1)
        assert phrase == "1 call without recorded model"

    def test_unnamed_count_only_plural(self):
        phrase = format_unavailable_models_phrase({}, 3)
        assert phrase == "3 calls without recorded model"

    def test_both_named_and_unnamed(self):
        phrase = format_unavailable_models_phrase({"gpt-5": 1}, 2)
        assert phrase == "gpt-5 (1 call); 2 calls without recorded model"

    def test_neither_returns_empty_string(self):
        # F#17 deferred: empty + zero unnamed returns empty string (not the
        # legacy "no models" placeholder — callers gate emission externally).
        phrase = format_unavailable_models_phrase({}, 0)
        assert phrase == ""

    def test_legacy_count_zero_renders_bare_name(self):
        # Defensive: a Mapping carrying count=0 (legacy trace shape after
        # passing through ``unavailable_models_to_counts``) renders the bare
        # model name rather than a confusing "(0 calls)".
        phrase = format_unavailable_models_phrase({"legacy-model": 0}, 0)
        assert phrase == "legacy-model"

    def test_mixed_singular_and_plural(self):
        # F#17 wording lock: each model independently picks singular/plural
        phrase = format_unavailable_models_phrase(
            {"alpha": 1, "beta": 2},
            0,
        )
        assert phrase == "alpha (1 call), beta (2 calls)"


class TestCalculateCostsCounterShape:
    """Bundle 7 / F#17 deferred: per-model call counts ride through the
    ``unavailable_models`` JSON shape so renderers don't have to rebuild
    them from individual call events. Producer-shape tests (not synthetic
    dicts): drive ``MetricsCollector.calculate_costs`` with realistic call
    lists.
    """

    def test_unavailable_models_carries_call_count_per_model(self):
        collector = MetricsCollector()

        llm_calls = [
            {"model": "ollama/llama3.2", "cost_usd": None},
            {"model": "ollama/llama3.2", "cost_usd": None},
            {"model": "ollama/llama3.2", "cost_usd": None},
            {"model": "custom/foo", "cost_usd": None},
        ]

        cost_data = collector.calculate_costs(llm_calls)
        # Sorted by name for determinism
        assert cost_data["unavailable_models"] == [
            {"name": "custom/foo", "calls": 1},
            {"name": "ollama/llama3.2", "calls": 3},
        ]

    def test_total_calls_in_summary(self):
        """``get_summary`` exposes ``total_calls`` at ``metrics.total`` so
        renderers can surface a ``Total LLM calls: N`` sibling line."""
        collector = MetricsCollector()
        collector.record_node_execution("llm-1", 10.0)

        llm_calls = [
            {"model": "gpt-4", "cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50},
            {"model": "gpt-4", "cost_usd": 0.02, "input_tokens": 200, "output_tokens": 75},
            {"model": "ollama/llama3.2", "cost_usd": None, "input_tokens": 50, "output_tokens": 25},
        ]

        summary = collector.get_summary(llm_calls)
        assert summary["metrics"]["total"]["total_calls"] == 3

    def test_total_calls_zero_when_no_llm_calls(self):
        collector = MetricsCollector()
        summary = collector.get_summary([])
        assert summary["metrics"]["total"]["total_calls"] == 0

    def test_total_calls_ignores_empty_dicts(self):
        """Empty/falsy entries are skipped — mirrors ``calculate_costs``'s
        ``if not call:`` guard so the displayed count never reports
        phantom invocations."""
        collector = MetricsCollector()
        llm_calls = [
            {},  # skipped
            {"model": "gpt-4", "cost_usd": 0.01},
            None,  # skipped (falsy)
            {"model": "gpt-4", "cost_usd": 0.02},
        ]
        summary = collector.get_summary(llm_calls)
        assert summary["metrics"]["total"]["total_calls"] == 2
