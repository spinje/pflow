"""Tests for instrumented node wrapper."""

import copy
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pflow.pocketflow import Node
from pflow.runtime.workflow_trace import WorkflowTraceCollector
from pflow.runtime.wrappers.instrumented_wrapper import InstrumentedNodeWrapper


class SimpleTestNode(Node):
    """Simple test node for wrapper testing."""

    def __init__(self):
        super().__init__()
        self.exec_called = False
        self.test_attribute = "test_value"
        self.params = {}
        self.successors = []

    def exec(self, shared, **kwargs):
        self.exec_called = True
        shared["test_output"] = "executed"
        return "test_result"

    def _run(self, shared):
        """Mock _run method that Node class would have."""
        return self.exec(shared)

    def custom_method(self):
        """Custom method to test delegation."""
        return "custom_result"

    def set_params(self, params: dict[str, Any]) -> None:
        """Set parameters on the node."""
        self.params = params


class ErrorNode(Node):
    """Node that raises an error for testing error handling."""

    def exec(self, shared, **kwargs):
        raise ValueError("Test error")

    def _run(self, shared):
        """Mock _run method that raises an error."""
        return self.exec(shared)


class LLMSimulatorNode(Node):
    """Node that simulates LLM usage for testing."""

    def exec(self, shared, **kwargs):
        # Simulate LLM usage being set
        shared["llm_usage"] = {
            "model": "gpt-4",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        shared["result"] = "LLM output"
        return "llm_result"

    def _run(self, shared):
        """Mock _run method that simulates LLM usage."""
        return self.exec(shared)


class TestInstrumentedWrapperBasics:
    """Test basic wrapper functionality."""

    def test_initialization(self):
        """Test wrapper initialization."""
        node = SimpleTestNode()
        metrics = Mock()
        trace = Mock()
        wrapper = InstrumentedNodeWrapper(node, "test_id", metrics, trace)

        assert wrapper.inner_node is node
        assert wrapper.node_id == "test_id"
        assert wrapper.metrics is metrics
        assert wrapper.trace is trace

    def test_initialization_without_collectors(self):
        """Test wrapper works without metrics or trace collectors."""
        node = SimpleTestNode()
        wrapper = InstrumentedNodeWrapper(node, "test_id", None, None)

        assert wrapper.inner_node is node
        assert wrapper.node_id == "test_id"
        assert wrapper.metrics is None
        assert wrapper.trace is None

    def test_copies_flow_attributes(self):
        """Test that Flow-required attributes are copied from inner node."""
        node = SimpleTestNode()
        node.successors = ["successor1", "successor2"]
        node.params = {"param1": "value1"}

        wrapper = InstrumentedNodeWrapper(node, "test_id")

        assert wrapper.successors == ["successor1", "successor2"]
        assert wrapper.params == {"param1": "value1"}

    def test_attribute_delegation(self):
        """Test that attributes are delegated to inner node."""
        node = SimpleTestNode()
        wrapper = InstrumentedNodeWrapper(node, "test_id")

        # Test accessing regular attributes
        assert wrapper.test_attribute == "test_value"
        assert not wrapper.exec_called

        # Test calling methods
        assert wrapper.custom_method() == "custom_result"

    def test_copy_operations_work_without_recursion(self):
        """Test that wrapper can be copied without infinite recursion.

        The wrapper's __getattr__ method prevents infinite recursion by
        explicitly raising AttributeError for certain pickle-related attributes
        when they're not found, preventing Python's copy mechanism from
        entering an infinite loop.
        """
        node = SimpleTestNode()
        wrapper = InstrumentedNodeWrapper(node, "test_id")

        # The main test is that these operations complete without infinite recursion
        import pickle

        # Test shallow copy works
        copied = copy.copy(wrapper)
        assert copied.node_id == "test_id"

        # Test deep copy works
        deep_copied = copy.deepcopy(wrapper)
        assert deep_copied.node_id == "test_id"

        # Test pickle works (which uses __getstate__/__setstate__)
        pickled = pickle.dumps(wrapper)
        # Safe to use pickle.loads in test context - we're testing our own pickled data
        unpickled = pickle.loads(pickled)  # noqa: S301
        assert unpickled.node_id == "test_id"

        # The AttributeError prevention is specifically for attributes that
        # don't exist on the inner node but would cause recursion
        class ObjectWithoutPickleMethods:
            """Object that explicitly lacks pickle methods."""

            def _run(self, shared):
                return "result"

        node2 = ObjectWithoutPickleMethods()
        node2.successors = []
        node2.params = {}
        wrapper2 = InstrumentedNodeWrapper(node2, "test_id2")

        # These specific attributes should raise AttributeError when not found
        # to prevent recursion (not all objects have these)
        for attr in ["__setstate__", "__getnewargs__", "__getnewargs_ex__"]:
            if not hasattr(node2, attr):
                with pytest.raises(AttributeError, match=f"object has no attribute '{attr}'"):
                    getattr(wrapper2, attr)


class TestOperatorDelegation:
    """Test operator delegation for flow connections."""

    def test_rshift_operator_delegation(self):
        """Test >> operator is delegated to inner node."""
        node = Mock()
        node.successors = []
        node.params = {}
        node.__rshift__ = Mock(return_value="rshift_result")

        wrapper = InstrumentedNodeWrapper(node, "test_id")
        result = wrapper >> "action"

        node.__rshift__.assert_called_once_with("action")
        assert result == "rshift_result"

    def test_sub_operator_delegation(self):
        """Test - operator is delegated to inner node."""
        node = Mock()
        node.successors = []
        node.params = {}
        node.__sub__ = Mock(return_value="sub_result")

        wrapper = InstrumentedNodeWrapper(node, "test_id")
        result = wrapper - "action"

        node.__sub__.assert_called_once_with("action")
        assert result == "sub_result"


class TestTimingCapture:
    """Test execution timing capture."""

    @patch("time.perf_counter")
    def test_timing_capture(self, mock_perf_counter):
        """Test that execution time is measured correctly."""
        # Setup mock timer to return predictable values
        mock_perf_counter.side_effect = [1.0, 1.5]  # Start and end times

        node = SimpleTestNode()
        metrics = Mock()
        wrapper = InstrumentedNodeWrapper(node, "test_id", metrics, None)

        shared = {}
        wrapper._run(shared)

        # Verify timing was calculated correctly (500ms)
        metrics.record_node_execution.assert_called_once_with("test_id", 500.0)

    @patch("time.perf_counter")
    def test_timing_capture_with_error(self, mock_perf_counter):
        """Test that timing is captured even when node raises an error."""
        mock_perf_counter.side_effect = [2.0, 2.25]  # Start and end times

        node = ErrorNode()
        metrics = Mock()
        wrapper = InstrumentedNodeWrapper(node, "test_id", metrics, None)

        shared = {}
        with pytest.raises(ValueError, match="Test error"):
            wrapper._run(shared)

        # Verify timing was still recorded (250ms)
        metrics.record_node_execution.assert_called_once_with("test_id", 250.0)


class TestLLMUsageTracking:
    """Test LLM usage tracking via trace collector.

    After the removal of __llm_calls__ accumulator, LLM usage is tracked via the
    WorkflowTraceCollector. The wrapper enriches llm_usage with cost_usd in-place
    in shared store, and _record_trace() passes node_output to the trace collector
    which captures llm_usage as llm_call in the event.
    """

    @staticmethod
    def _make_namespaced_llm_node(node_id: str, usage_data: dict[str, Any]) -> type:
        """Create an LLM node class that writes output under its namespace.

        In a real workflow, the namespace wrapper writes node output under
        shared[node_id]. These test nodes simulate that behavior directly.
        """

        class NamespacedLLMNode(Node):
            def _run(self, shared: dict[str, Any]) -> str:
                shared[node_id] = {"llm_usage": dict(usage_data), "result": "LLM output"}
                # Also write at root level (as nodes do before namespacing moves it)
                shared["llm_usage"] = shared[node_id]["llm_usage"]
                return "done"

        return NamespacedLLMNode

    def test_llm_usage_captured_in_trace(self):
        """Test that LLM usage is captured as llm_call in the trace event."""
        trace = WorkflowTraceCollector("test")
        usage_data = {
            "model": "gpt-4",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        node_cls = self._make_namespaced_llm_node("llm_node_1", usage_data)
        wrapper = InstrumentedNodeWrapper(node_cls(), "llm_node_1", None, trace)

        shared: dict[str, Any] = {}
        wrapper._run(shared)

        # Trace collector should have one event with llm_call data
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
        usage_data = {
            "model": "gpt-4",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }

        node1_cls = self._make_namespaced_llm_node("llm_node_1", usage_data)
        wrapper1 = InstrumentedNodeWrapper(node1_cls(), "llm_node_1", None, trace)

        node2_cls = self._make_namespaced_llm_node("llm_node_2", usage_data)
        wrapper2 = InstrumentedNodeWrapper(node2_cls(), "llm_node_2", None, trace)

        shared: dict[str, Any] = {}
        wrapper1._run(shared)
        wrapper2._run(shared)

        # Both calls should be captured as separate trace events
        assert len(trace.events) == 2
        assert trace.events[0]["node_id"] == "llm_node_1"
        assert trace.events[1]["node_id"] == "llm_node_2"
        assert "llm_call" in trace.events[0]
        assert "llm_call" in trace.events[1]

    def test_non_llm_node_trace_has_no_llm_call(self):
        """Test that non-LLM nodes produce trace events without llm_call."""
        trace = WorkflowTraceCollector("test")
        node = SimpleTestNode()
        wrapper = InstrumentedNodeWrapper(node, "regular_node", None, trace)

        shared: dict[str, Any] = {}
        wrapper._run(shared)

        # Trace event should exist but without llm_call
        assert len(trace.events) == 1
        assert "llm_call" not in trace.events[0]
        assert trace.events[0]["node_id"] == "regular_node"

    def _make_llm_cost_wrapper(self, trace: WorkflowTraceCollector | None = None) -> InstrumentedNodeWrapper:
        """Create an InstrumentedNodeWrapper around a node that writes standard llm_usage."""
        node_id = "llm_cost"

        class LLMNodeWithStandardTokenKeys(Node):
            """Node simulating LLM usage with input_tokens/output_tokens keys."""

            def _run(self, shared: dict[str, Any]) -> str:
                usage = {
                    "model": "gpt-4",
                    "input_tokens": 1000,
                    "output_tokens": 500,
                }
                shared[node_id] = {"llm_usage": usage}
                shared["llm_usage"] = usage
                return "done"

        return InstrumentedNodeWrapper(LLMNodeWithStandardTokenKeys(), node_id, None, trace)

    def test_llm_usage_enriched_with_cost_in_shared_store(self):
        """After execution, shared store's llm_usage dict should have cost_usd added.

        Uses input_tokens/output_tokens keys (the standard keys enrich_llm_usage_with_cost reads).
        """
        wrapper = self._make_llm_cost_wrapper()

        shared: dict[str, Any] = {}
        wrapper._run(shared)

        # The original llm_usage in shared store should be enriched in-place
        assert "llm_usage" in shared
        assert "cost_usd" in shared["llm_usage"]
        # gpt-4: $30/1M input, $60/1M output
        # 1000 input = 0.03, 500 output = 0.03 => total = 0.06
        assert isinstance(shared["llm_usage"]["cost_usd"], float)
        assert shared["llm_usage"]["cost_usd"] == 0.06

    def test_trace_event_has_cost_usd(self):
        """The trace event's llm_call should contain cost_usd from enrichment."""
        trace = WorkflowTraceCollector("test")
        wrapper = self._make_llm_cost_wrapper(trace)

        shared: dict[str, Any] = {}
        wrapper._run(shared)

        # Trace event should have llm_call with cost
        assert len(trace.events) == 1
        event = trace.events[0]
        assert "llm_call" in event
        assert "cost_usd" in event["llm_call"]
        assert isinstance(event["llm_call"]["cost_usd"], float)
        assert event["llm_call"]["cost_usd"] == 0.06
        # The trace cost should match the shared store cost
        assert event["llm_call"]["cost_usd"] == shared["llm_usage"]["cost_usd"]


class TestErrorHandling:
    """Test error handling during node execution."""

    def test_metrics_recorded_on_error(self):
        """Test that metrics are still recorded when node fails."""
        node = ErrorNode()
        metrics = Mock()
        wrapper = InstrumentedNodeWrapper(node, "error_node", metrics, None)

        shared = {}
        with pytest.raises(ValueError):
            wrapper._run(shared)

        # Verify metrics were recorded despite error
        metrics.record_node_execution.assert_called_once()
        call_args = metrics.record_node_execution.call_args
        assert call_args[0][0] == "error_node"  # node_id
        assert isinstance(call_args[0][1], float)  # duration_ms

    def test_trace_recorded_on_error(self):
        """Test that trace is recorded when node fails."""
        node = ErrorNode()
        trace = Mock()
        wrapper = InstrumentedNodeWrapper(node, "error_node", None, trace)

        shared = {"initial": "state"}
        with pytest.raises(ValueError):
            wrapper._run(shared)

        # Verify trace was recorded with error information
        trace.record_node_execution.assert_called_once()
        call_kwargs = trace.record_node_execution.call_args[1]
        assert call_kwargs["node_id"] == "error_node"
        assert call_kwargs["node_type"] == "ErrorNode"
        assert not call_kwargs["success"]
        assert call_kwargs["error"] == "Test error"
        # Format 2.0.0: no shared_before/shared_after, uses node_output/mutations instead
        assert "shared_before" not in call_kwargs
        assert "node_output" in call_kwargs
        assert "mutations" in call_kwargs

    def test_exception_propagated(self):
        """Test that exceptions are re-raised after recording metrics."""
        node = ErrorNode()
        metrics = Mock()
        trace = Mock()
        wrapper = InstrumentedNodeWrapper(node, "error_node", metrics, trace)

        shared = {}
        with pytest.raises(ValueError, match="Test error"):
            wrapper._run(shared)

        # Verify both collectors were called
        metrics.record_node_execution.assert_called_once()
        trace.record_node_execution.assert_called_once()


class TestCollectorIntegration:
    """Test integration with metrics and trace collectors."""

    def test_metrics_collector_integration(self):
        """Test integration with metrics collector."""
        node = SimpleTestNode()
        metrics = Mock()
        wrapper = InstrumentedNodeWrapper(node, "test_node", metrics, None)

        shared = {"input": "data"}
        result = wrapper._run(shared)

        # Verify metrics collector was called correctly
        metrics.record_node_execution.assert_called_once()
        call_args = metrics.record_node_execution.call_args
        assert call_args[0][0] == "test_node"
        assert isinstance(call_args[0][1], float)  # duration_ms

        # Verify node still executed correctly
        assert result == "test_result"
        assert shared["test_output"] == "executed"

    def test_trace_collector_integration(self):
        """Test integration with trace collector."""
        node = SimpleTestNode()
        trace = Mock()
        wrapper = InstrumentedNodeWrapper(node, "test_node", None, trace)

        shared = {"input": "data"}
        result = wrapper._run(shared)

        # Verify trace collector was called correctly
        trace.record_node_execution.assert_called_once()
        call_kwargs = trace.record_node_execution.call_args[1]
        assert call_kwargs["node_id"] == "test_node"
        assert call_kwargs["node_type"] == "SimpleTestNode"
        assert isinstance(call_kwargs["duration_ms"], float)
        # Format 2.0.0: no shared_before/shared_after
        assert "shared_before" not in call_kwargs
        assert "shared_after" not in call_kwargs
        # node_output is the node's namespace from shared store
        assert "node_output" in call_kwargs
        # mutations computed from key sets
        assert "mutations" in call_kwargs
        assert call_kwargs["success"]
        assert call_kwargs["error"] is None
        assert call_kwargs["template_resolutions"] == {}

        # Verify node still executed correctly
        assert result == "test_result"

    def test_both_collectors_integration(self):
        """Test with both metrics and trace collectors."""
        node = SimpleTestNode()
        metrics = Mock()
        trace = Mock()
        wrapper = InstrumentedNodeWrapper(node, "test_node", metrics, trace)

        shared = {}
        wrapper._run(shared)

        # Verify both collectors were called
        metrics.record_node_execution.assert_called_once()
        trace.record_node_execution.assert_called_once()

    def test_no_collectors(self):
        """Test that wrapper works without any collectors."""
        node = SimpleTestNode()
        wrapper = InstrumentedNodeWrapper(node, "test_node", None, None)

        shared = {}
        result = wrapper._run(shared)

        # Verify node executed successfully without collectors
        assert result == "test_result"
        assert shared["test_output"] == "executed"


class TestSetParams:
    """Test set_params delegation."""

    def test_set_params_delegation(self):
        """Test that set_params is delegated to inner node."""
        node = SimpleTestNode()
        wrapper = InstrumentedNodeWrapper(node, "test_node")

        params = {"param1": "value1", "param2": "value2"}
        wrapper.set_params(params)

        assert node.params == params

    def test_set_params_without_method(self):
        """Test set_params when inner node doesn't have the method."""

        # Create a simple object without set_params
        class NodeWithoutSetParams:
            def __init__(self):
                self.params = {}
                self.successors = []

            def _run(self, shared):
                return "result"

        node = NodeWithoutSetParams()
        wrapper = InstrumentedNodeWrapper(node, "test_node")

        params = {"param1": "value1"}
        wrapper.set_params(params)

        # When inner node doesn't have set_params, wrapper stores params directly
        # Use object.__getattribute__ to bypass delegation and check wrapper's own attribute
        stored_params = object.__getattribute__(wrapper, "params")
        assert stored_params == params


class TestCopyOperations:
    """Test copy and deepcopy operations."""

    def test_shallow_copy(self):
        """Test shallow copy operation."""
        node = SimpleTestNode()
        node.successors = ["s1", "s2"]
        node.params = {"p1": "v1"}
        metrics = Mock()
        trace = Mock()

        wrapper = InstrumentedNodeWrapper(node, "test_node", metrics, trace)
        wrapper.successors = ["s1", "s2"]
        wrapper.params = {"p1": "v1"}

        # Perform shallow copy
        copied = copy.copy(wrapper)

        # Verify copy structure
        assert copied.node_id == "test_node"
        assert copied.metrics is metrics  # Same reference
        assert copied.trace is trace  # Same reference
        assert copied.successors == ["s1", "s2"]
        assert copied.params == {"p1": "v1"}

        # Verify successors list was copied (not same reference)
        assert copied.successors is not wrapper.successors

        # Inner node should be shallow copied
        assert copied.inner_node is not wrapper.inner_node
        assert isinstance(copied.inner_node, type(wrapper.inner_node))

    def test_deep_copy(self):
        """Test deep copy operation."""
        node = SimpleTestNode()
        node.successors = ["s1", "s2"]
        node.params = {"p1": {"nested": "value"}}
        metrics = Mock()
        trace = Mock()

        wrapper = InstrumentedNodeWrapper(node, "test_node", metrics, trace)
        wrapper.successors = ["s1", "s2"]
        wrapper.params = {"p1": {"nested": "value"}}

        # Perform deep copy
        copied = copy.deepcopy(wrapper)

        # Verify copy structure
        assert copied.node_id == "test_node"
        assert copied.metrics is metrics  # Not deep copied
        assert copied.trace is trace  # Not deep copied
        assert copied.successors == ["s1", "s2"]
        assert copied.params == {"p1": {"nested": "value"}}

        # Verify deep copy (different references)
        assert copied.successors is not wrapper.successors
        assert copied.params is not wrapper.params
        assert copied.params["p1"] is not wrapper.params["p1"]

        # Inner node should be deep copied
        assert copied.inner_node is not wrapper.inner_node

    def test_copy_without_attributes(self):
        """Test copy when node doesn't have successors or params."""
        node = Mock()
        node._run = Mock(return_value="result")
        # Don't set successors or params

        wrapper = InstrumentedNodeWrapper(node, "test_node")

        # Should copy without error
        copied = copy.copy(wrapper)
        assert copied.node_id == "test_node"

        # Deep copy should also work
        deep_copied = copy.deepcopy(wrapper)
        assert deep_copied.node_id == "test_node"


class TestTransparency:
    """Test that wrapper is transparent to inner node behavior."""

    def test_wrapper_transparency(self):
        """Test that wrapper doesn't change inner node behavior."""
        # Run node directly
        node = SimpleTestNode()
        shared_direct = {"input": "test"}
        result_direct = node._run(shared_direct)

        # Run same node through wrapper
        wrapped_node = SimpleTestNode()
        wrapper = InstrumentedNodeWrapper(wrapped_node, "test_node")
        shared_wrapped = {"input": "test"}
        result_wrapped = wrapper._run(shared_wrapped)

        # Results should be identical
        assert result_direct == result_wrapped
        assert shared_direct["test_output"] == shared_wrapped["test_output"]

        # Both nodes should have been executed
        assert node.exec_called
        assert wrapped_node.exec_called

    def test_shared_store_modifications_preserved(self):
        """Test that modifications to shared store are preserved."""

        class ModifyingNode(Node):
            def _run(self, shared):
                shared["added_key"] = "added_value"
                shared["counter"] = shared.get("counter", 0) + 1
                if "remove_me" in shared:
                    del shared["remove_me"]
                return "done"

        node = ModifyingNode()
        wrapper = InstrumentedNodeWrapper(node, "test_node")

        shared = {"counter": 5, "remove_me": "value", "keep_me": "value"}
        result = wrapper._run(shared)

        # Verify all modifications were preserved
        assert result == "done"
        assert shared["added_key"] == "added_value"
        assert shared["counter"] == 6
        assert "remove_me" not in shared
        assert shared["keep_me"] == "value"

    def test_return_value_preserved(self):
        """Test that return values are preserved exactly."""

        class ComplexReturnNode(Node):
            def _run(self, shared):
                return {"complex": "structure", "list": [1, 2, 3], "nested": {"a": "b"}}

        node = ComplexReturnNode()
        wrapper = InstrumentedNodeWrapper(node, "test_node")

        shared = {}
        result = wrapper._run(shared)

        assert result == {"complex": "structure", "list": [1, 2, 3], "nested": {"a": "b"}}


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_shared_store(self):
        """Test execution with empty shared store."""
        node = SimpleTestNode()
        wrapper = InstrumentedNodeWrapper(node, "test_node")

        shared: dict[str, Any] = {}
        result = wrapper._run(shared)

        assert result == "test_result"
        # __llm_calls__ is no longer initialized by the wrapper
        assert "__llm_calls__" not in shared
        assert shared["test_output"] == "executed"

    def test_llm_usage_overwrite_captured_in_trace(self):
        """Test that each LLM call's usage is captured separately in trace events.

        When two nodes both write llm_usage to the shared store (overwriting each
        other), both should still be captured as separate trace events because the
        trace collector records each node's execution independently.
        """
        trace = WorkflowTraceCollector("test")

        class OverwritingLLMNode(Node):
            def __init__(self, node_id: str, usage_data: dict[str, Any]):
                self._node_id = node_id
                self.usage_data = usage_data

            def _run(self, shared: dict[str, Any]) -> str:
                # Write under namespace (simulating namespace wrapper)
                shared[self._node_id] = {"llm_usage": dict(self.usage_data)}
                # Also write at root level (would be overwritten by next node)
                shared["llm_usage"] = self.usage_data
                return "done"

        # First call sets one usage
        node1 = OverwritingLLMNode("llm1", {"model": "gpt-3.5", "tokens": 100})
        wrapper1 = InstrumentedNodeWrapper(node1, "llm1", None, trace)

        # Second call overwrites root llm_usage with different data
        node2 = OverwritingLLMNode("llm2", {"model": "gpt-4", "tokens": 200})
        wrapper2 = InstrumentedNodeWrapper(node2, "llm2", None, trace)

        shared: dict[str, Any] = {}
        wrapper1._run(shared)
        wrapper2._run(shared)

        # Both usages should be captured in separate trace events
        assert len(trace.events) == 2
        assert trace.events[0]["llm_call"]["model"] == "gpt-3.5"
        assert trace.events[0]["llm_call"]["tokens"] == 100
        assert trace.events[0]["node_id"] == "llm1"
        assert trace.events[1]["llm_call"]["model"] == "gpt-4"
        assert trace.events[1]["llm_call"]["tokens"] == 200
        assert trace.events[1]["node_id"] == "llm2"

        # The last usage should still be in shared (not removed)
        assert shared["llm_usage"]["model"] == "gpt-4"

    def test_none_return_value(self):
        """Test handling of None return value."""

        class NoneReturnNode(Node):
            def _run(self, shared):
                return None

        node = NoneReturnNode()
        wrapper = InstrumentedNodeWrapper(node, "test_node")

        shared = {}
        result = wrapper._run(shared)

        assert result is None

    @patch("time.perf_counter")
    def test_zero_duration(self, mock_perf_counter):
        """Test handling of zero duration (same start and end time)."""
        # Same time for start and end
        mock_perf_counter.side_effect = [1.0, 1.0]

        node = SimpleTestNode()
        metrics = Mock()
        wrapper = InstrumentedNodeWrapper(node, "test_node", metrics)

        shared = {}
        wrapper._run(shared)

        # Should record 0.0 duration
        metrics.record_node_execution.assert_called_once_with("test_node", 0.0)
