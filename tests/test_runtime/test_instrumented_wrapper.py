"""Tests for engine instrumentation behavior.

Tests timing capture, LLM usage tracking, trace recording, error handling,
and execution transparency — all behaviors previously tested on the
InstrumentedNodeWrapper, now implemented by the WorkflowEngine and
standalone instrumentation functions.

Migrated from wrapper-based tests to compile_workflow + WorkflowEngine
and standalone function tests after the wrappers were replaced by the
engine (Task 135/138).
"""

from typing import Any
from unittest.mock import Mock

import pytest

from pflow.core.node import Node
from pflow.runtime.cache import MemoizationCache
from pflow.runtime.engine.instrumentation import (
    call_completion_callback,
    call_start_callback,
    initialize_execution_state,
    record_trace,
)
from pflow.runtime.workflow_trace import WorkflowTraceCollector

# ---------------------------------------------------------------------------
# Test nodes
# ---------------------------------------------------------------------------


class SimpleTestNode(Node):
    """Simple test node that writes output to shared store."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        return "test_result"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["test_output"] = "executed"
        return "default"


class ErrorNode(Node):
    """Node that raises an error for testing error handling."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        raise ValueError("Test error")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _run_single_node_workflow(
    node_type: str,
    params: dict[str, Any],
    shared: dict[str, Any] | None = None,
    metrics: Any = None,
    trace: Any = None,
) -> tuple[dict[str, Any], str]:
    """Run a single-node workflow through compile_workflow + WorkflowEngine.

    Returns (shared_store, action_string).
    """
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow
    from pflow.runtime.engine import WorkflowEngine

    ir = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": node_type, "params": params}],
        "edges": [],
    }

    registry = Registry()
    workflow = compile_workflow(ir_json=ir, registry=registry)

    shared = shared or {}
    shared.update(workflow.resolved_defaults)

    engine = WorkflowEngine(metrics_collector=metrics, trace_collector=trace)
    action = engine.run(workflow, shared)
    return shared, action


# ===========================================================================
# Tests: Execution state initialization
# ===========================================================================


class TestExecutionStateInitialization:
    """Test execution state initialization via standalone functions."""

    def test_initialize_creates_full_structure(self):
        """Test that initialize_execution_state creates the complete structure."""
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        assert "__execution__" in shared
        checkpoint = shared["__execution__"]
        assert "completed_nodes" in checkpoint
        assert "node_actions" in checkpoint
        assert "failed_node" in checkpoint
        assert "node_hashes" in checkpoint
        assert "node_visit_counts" in checkpoint
        assert "__cache_hits__" in shared
        assert shared["__cache_hits__"] == []

    def test_initialize_is_idempotent(self):
        """Calling initialize_execution_state twice does not reset existing data."""
        shared: dict[str, Any] = {}
        initialize_execution_state(shared)

        # Add some data
        shared["__execution__"]["completed_nodes"].append("node1")
        shared["__cache_hits__"].append("node1")

        # Call again — should NOT reset
        initialize_execution_state(shared)
        assert "node1" in shared["__execution__"]["completed_nodes"]
        assert "node1" in shared["__cache_hits__"]

    def test_initialize_adds_missing_keys_to_existing(self):
        """If __execution__ exists but is missing some keys, they are added."""
        shared: dict[str, Any] = {
            "__execution__": {
                "completed_nodes": ["old"],
                "node_actions": {},
                "failed_node": None,
                # Missing: node_hashes, node_visit_counts
            },
        }
        initialize_execution_state(shared)

        assert "node_hashes" in shared["__execution__"]
        assert "node_visit_counts" in shared["__execution__"]
        # Existing data preserved
        assert "old" in shared["__execution__"]["completed_nodes"]


# ===========================================================================
# Tests: Timing capture through engine
# ===========================================================================


class TestTimingCapture:
    """Test that execution timing is captured by the engine."""

    def test_metrics_receive_timing(self):
        """Test that metrics collector receives timing data from a real workflow run."""
        metrics = Mock()
        shared, action = _run_single_node_workflow("shell", {"command": "printf '%s' hello"}, metrics=metrics)

        # Metrics collector should have been called with node_id and duration_ms
        metrics.record_node_execution.assert_called_once()
        call_args = metrics.record_node_execution.call_args
        assert call_args[0][0] == "test"  # node_id
        assert isinstance(call_args[0][1], float)  # duration_ms
        assert call_args[0][1] >= 0


# ===========================================================================
# Tests: LLM usage tracking
# ===========================================================================


class TestLLMUsageTracking:
    """Test LLM usage tracking via trace collector.

    The engine enriches llm_usage with cost_usd in-place in shared store,
    and record_trace passes node_output to the trace collector which captures
    llm_usage as llm_call in the event.
    """

    def test_llm_usage_captured_in_trace(self):
        """Test that LLM usage is captured as llm_call in the trace event."""
        trace = WorkflowTraceCollector("test")

        # Simulate what record_trace does with a node that has llm_usage
        node_output = {
            "llm_usage": {
                "model": "gpt-4",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            "result": "LLM output",
        }

        import time

        shared: dict[str, Any] = {"llm_node_1": node_output}
        record_trace(
            node_id="llm_node_1",
            node_type_name="LLMNode",
            shared=shared,
            start_time=time.perf_counter(),
            shared_keys_before=set(),
            last_resolutions={},
            batch_trace_items=None,
            child_trace_events=None,
            node_params={},
            trace_collector=trace,
        )

        assert len(trace.events) == 1
        event = trace.events[0]
        assert "llm_call" in event
        assert event["llm_call"]["model"] == "gpt-4"
        assert event["llm_call"]["prompt_tokens"] == 100
        assert event["llm_call"]["completion_tokens"] == 50
        assert event["llm_call"]["total_tokens"] == 150
        assert event["node_id"] == "llm_node_1"

    def test_multiple_llm_calls_captured_in_trace(self):
        """Test that multiple LLM calls produce separate trace events."""
        trace = WorkflowTraceCollector("test")
        import time

        for node_id, model in [("llm1", "gpt-3.5"), ("llm2", "gpt-4")]:
            output = {"llm_usage": {"model": model, "tokens": 100}, "result": "output"}
            shared: dict[str, Any] = {node_id: output}

            record_trace(
                node_id=node_id,
                node_type_name="LLMNode",
                shared=shared,
                start_time=time.perf_counter(),
                shared_keys_before=set(),
                last_resolutions={},
                batch_trace_items=None,
                child_trace_events=None,
                node_params={},
                trace_collector=trace,
            )

        assert len(trace.events) == 2
        assert trace.events[0]["node_id"] == "llm1"
        assert trace.events[1]["node_id"] == "llm2"
        assert "llm_call" in trace.events[0]
        assert "llm_call" in trace.events[1]

    def test_non_llm_node_trace_has_no_llm_call(self):
        """Test that non-LLM nodes produce trace events without llm_call."""
        trace = WorkflowTraceCollector("test")
        import time

        shared: dict[str, Any] = {"regular_node": {"result": "data"}}
        record_trace(
            node_id="regular_node",
            node_type_name="SimpleNode",
            shared=shared,
            start_time=time.perf_counter(),
            shared_keys_before=set(),
            last_resolutions={},
            batch_trace_items=None,
            child_trace_events=None,
            node_params={},
            trace_collector=trace,
        )

        assert len(trace.events) == 1
        assert "llm_call" not in trace.events[0]
        assert trace.events[0]["node_id"] == "regular_node"

    def test_trace_event_has_cost_usd(self):
        """The trace event's ``llm_call`` carries the ``cost_usd`` set upstream.

        The adapter populates ``cost_usd`` on the node's namespaced
        ``llm_usage`` dict from LiteLLM's ``response_cost``. ``record_trace``
        reads the same dict and emits it on ``event['llm_call']``.
        """
        trace = WorkflowTraceCollector("test")
        import time

        node_id = "llm_cost"
        # Single shared usage dict (as in real namespaced execution); cost_usd
        # set as the adapter would set it from LiteLLM's response_cost.
        usage = {
            "model": "gpt-4",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cost_usd": 0.06,
        }
        shared: dict[str, Any] = {
            node_id: {"llm_usage": usage},
        }

        record_trace(
            node_id=node_id,
            node_type_name="LLMNode",
            shared=shared,
            start_time=time.perf_counter(),
            shared_keys_before=set(),
            last_resolutions={},
            batch_trace_items=None,
            child_trace_events=None,
            node_params={},
            trace_collector=trace,
        )

        assert len(trace.events) == 1
        event = trace.events[0]
        assert "llm_call" in event
        assert event["llm_call"]["cost_usd"] == 0.06

    def test_llmnode_post_writes_cost_usd_to_memo_cache(self, tmp_path):
        """LLMNode memoized output includes cost_usd as set by the adapter."""
        cache = MemoizationCache(db_path=tmp_path / "cache.db")
        shared, action = _run_single_node_workflow(
            "llm",
            {"prompt": "say hello", "model": "gpt-4"},
            shared={"__memoization_cache__": cache},
        )

        assert action == "default"
        live_usage = shared.get("llm_usage")
        if not isinstance(live_usage, dict):
            live_usage = shared["test"]["llm_usage"]
        assert "cost_usd" in live_usage
        cached = cache.get_latest_for_node("test")
        assert cached is not None
        output, _created_at = cached
        assert output["llm_usage"]["cost_usd"] == live_usage["cost_usd"]


# ===========================================================================
# Tests: Error handling
# ===========================================================================


class TestErrorHandling:
    """Test error handling during node execution via the engine."""

    def test_metrics_recorded_on_error(self):
        """Test that metrics are still recorded when node raises during execution.

        Uses a shell node with working_dir pointing to a nonexistent directory,
        which raises ValueError in prep() inside the engine's try/except.
        """
        metrics = Mock()

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "error_node",
                    "type": "shell",
                    "params": {"command": "echo hi", "cwd": "/nonexistent/path/xyz"},
                },
            ],
            "edges": [],
        }

        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()
        workflow = compile_workflow(ir_json=ir, registry=registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)

        engine = WorkflowEngine(metrics_collector=metrics)

        with pytest.raises(ValueError, match="does not exist"):
            engine.run(workflow, shared)

        # Verify metrics were recorded despite error
        metrics.record_node_execution.assert_called_once()
        call_args = metrics.record_node_execution.call_args
        assert call_args[0][0] == "error_node"
        assert isinstance(call_args[0][1], float)

    def test_trace_recorded_on_error(self):
        """Test that trace is recorded when node fails via compile_workflow + WorkflowEngine."""
        trace = WorkflowTraceCollector("test")

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "error_node",
                    "type": "shell",
                    "params": {"command": "echo hi", "cwd": "/nonexistent/path/xyz"},
                },
            ],
            "edges": [],
        }

        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        registry = Registry()
        workflow = compile_workflow(ir_json=ir, registry=registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)

        engine = WorkflowEngine(trace_collector=trace)

        with pytest.raises(ValueError, match="does not exist"):
            engine.run(workflow, shared)

        # Verify trace was recorded with error information
        assert len(trace.events) == 1
        event = trace.events[0]
        assert event["node_id"] == "error_node"
        assert event["node_type"] == "ShellNode"
        assert not event["success"]
        assert event["error"] is not None
        assert "does not exist" in event["error"]
        # Format 2.0.0: no shared_before/shared_after
        assert "shared_before" not in event
        assert "mutations" in event


# ===========================================================================
# Tests: Trace collector integration
# ===========================================================================


class TestCollectorIntegration:
    """Test integration with metrics and trace collectors through compile_workflow + WorkflowEngine."""

    def test_metrics_collector_integration(self):
        """Test integration with metrics collector."""
        metrics = Mock()
        shared, action = _run_single_node_workflow("shell", {"command": "printf '%s' hello"}, metrics=metrics)

        # Verify metrics collector was called correctly
        metrics.record_node_execution.assert_called_once()
        call_args = metrics.record_node_execution.call_args
        assert call_args[0][0] == "test"  # node_id
        assert isinstance(call_args[0][1], float)  # duration_ms

    def test_trace_collector_integration(self):
        """Test integration with trace collector."""
        trace = WorkflowTraceCollector("test")
        shared, action = _run_single_node_workflow("shell", {"command": "printf '%s' hello"}, trace=trace)

        # Verify trace collector was called correctly
        assert len(trace.events) == 1
        event = trace.events[0]
        assert event["node_id"] == "test"
        assert event["success"]
        assert isinstance(event["duration_ms"], float)
        # Format 2.0.0: no shared_before/shared_after
        assert "shared_before" not in event
        assert "shared_after" not in event

    def test_both_collectors_integration(self):
        """Test with both metrics and trace collectors."""
        metrics = Mock()
        trace = WorkflowTraceCollector("test")
        shared, action = _run_single_node_workflow(
            "shell", {"command": "printf '%s' hello"}, metrics=metrics, trace=trace
        )

        # Verify both collectors were called
        metrics.record_node_execution.assert_called_once()
        assert len(trace.events) == 1

    def test_no_collectors(self):
        """Test that workflow works without any collectors."""
        shared, action = _run_single_node_workflow("shell", {"command": "printf '%s' hello"})

        # Verify node executed successfully without collectors
        assert shared["test"]["stdout"] == "hello"


# ===========================================================================
# Tests: Engine transparency
# ===========================================================================


class TestTransparency:
    """Test that the engine doesn't change node behavior."""

    def test_engine_transparency_via_workflow(self):
        """Test that engine execution produces correct node outputs."""
        shared, action = _run_single_node_workflow("shell", {"command": "printf '%s' 'hello world'"})

        # shell node writes output to shared[node_id]
        assert shared["test"]["stdout"] == "hello world"

    def test_shared_store_modifications_preserved(self):
        """Test that modifications to shared store are preserved through the engine."""
        shared, action = _run_single_node_workflow("shell", {"command": "echo 'hello world'"})

        # Shell node writes stdout to shared[node_id]
        assert "test" in shared
        assert "stdout" in shared["test"]
        assert "hello world" in shared["test"]["stdout"]


# ===========================================================================
# Tests: Progress callbacks
# ===========================================================================


class TestProgressCallbacks:
    """Test progress callback integration with standalone functions."""

    def test_start_callback_called(self):
        """Test that call_start_callback fires the callback."""
        events: list[tuple[str, str]] = []

        def callback(node_id: str, event: str, *args: Any, **kwargs: Any) -> None:
            events.append((node_id, event))

        shared: dict[str, Any] = {"__progress_callback__": callback}
        call_start_callback("my_node", shared)

        assert ("my_node", "node_start") in events

    def test_completion_callback_called(self):
        """Test that call_completion_callback fires the callback."""
        events: list[tuple[str, str]] = []

        def callback(node_id: str, event: str, *args: Any, **kwargs: Any) -> None:
            events.append((node_id, event))

        shared: dict[str, Any] = {"__progress_callback__": callback}
        call_completion_callback("my_node", shared, "default", 100.0)

        assert ("my_node", "node_complete") in events

    def test_no_callback_no_error(self):
        """Test that missing callback doesn't cause errors."""
        shared: dict[str, Any] = {}
        # These should not raise
        call_start_callback("my_node", shared)
        call_completion_callback("my_node", shared, "default", 100.0)


# ===========================================================================
# Tests: Edge cases
# ===========================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_shared_store(self):
        """Test execution with empty shared store via compile_workflow + WorkflowEngine."""
        shared, action = _run_single_node_workflow("shell", {"command": "printf '%s' test"})

        # __llm_calls__ is no longer initialized by the engine
        assert "__llm_calls__" not in shared

    def test_llm_usage_overwrite_captured_in_trace(self):
        """Test that each node's LLM usage is captured in its own trace event.

        When two nodes both write llm_usage (overwriting at root level),
        both should still be captured as separate trace events because
        record_trace reads from shared[node_id] (namespaced).
        """
        trace = WorkflowTraceCollector("test")
        import time

        # First node
        shared: dict[str, Any] = {
            "llm1": {"llm_usage": {"model": "gpt-3.5", "tokens": 100}},
            "llm_usage": {"model": "gpt-3.5", "tokens": 100},
        }
        record_trace(
            node_id="llm1",
            node_type_name="LLMNode",
            shared=shared,
            start_time=time.perf_counter(),
            shared_keys_before=set(),
            last_resolutions={},
            batch_trace_items=None,
            child_trace_events=None,
            node_params={},
            trace_collector=trace,
        )

        # Second node overwrites root level
        shared["llm2"] = {"llm_usage": {"model": "gpt-4", "tokens": 200}}
        shared["llm_usage"] = {"model": "gpt-4", "tokens": 200}
        record_trace(
            node_id="llm2",
            node_type_name="LLMNode",
            shared=shared,
            start_time=time.perf_counter(),
            shared_keys_before=set(),
            last_resolutions={},
            batch_trace_items=None,
            child_trace_events=None,
            node_params={},
            trace_collector=trace,
        )

        # Both usages should be captured in separate trace events
        assert len(trace.events) == 2
        assert trace.events[0]["llm_call"]["model"] == "gpt-3.5"
        assert trace.events[0]["llm_call"]["tokens"] == 100
        assert trace.events[0]["node_id"] == "llm1"
        assert trace.events[1]["llm_call"]["model"] == "gpt-4"
        assert trace.events[1]["llm_call"]["tokens"] == 200
        assert trace.events[1]["node_id"] == "llm2"

    def test_record_trace_without_collector(self):
        """Test that record_trace with no collector is a no-op."""
        import time

        shared: dict[str, Any] = {"test": {"result": "data"}}
        # Should not raise
        record_trace(
            node_id="test",
            node_type_name="TestNode",
            shared=shared,
            start_time=time.perf_counter(),
            shared_keys_before=set(),
            last_resolutions={},
            batch_trace_items=None,
            child_trace_events=None,
            node_params={},
            trace_collector=None,
        )
