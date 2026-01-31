"""Tests for instrumented node wrapper."""

import copy
from typing import Any
from unittest.mock import ANY, Mock, patch

import pytest

from pflow.pocketflow import Node
from pflow.runtime.instrumented_wrapper import InstrumentedNodeWrapper


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
        metrics.record_node_execution.assert_called_once_with("test_id", 500.0, is_planner=False)

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
        metrics.record_node_execution.assert_called_once_with("test_id", 250.0, is_planner=False)


class TestLLMUsageAccumulation:
    """Test LLM usage tracking and accumulation."""

    def test_llm_usage_accumulation(self):
        """Test that LLM usage is accumulated in shared store."""
        node = LLMSimulatorNode()
        wrapper = InstrumentedNodeWrapper(node, "llm_node_1", None, None)

        shared = {}
        wrapper._run(shared)

        # Check that __llm_calls__ list was created and populated
        assert "__llm_calls__" in shared
        assert len(shared["__llm_calls__"]) == 1

        llm_call = shared["__llm_calls__"][0]
        assert llm_call["model"] == "gpt-4"
        assert llm_call["prompt_tokens"] == 100
        assert llm_call["completion_tokens"] == 50
        assert llm_call["total_tokens"] == 150
        assert llm_call["node_id"] == "llm_node_1"
        assert "duration_ms" in llm_call
        assert not llm_call["is_planner"]

    def test_multiple_llm_calls_accumulation(self):
        """Test that multiple LLM calls are accumulated correctly."""
        node1 = LLMSimulatorNode()
        wrapper1 = InstrumentedNodeWrapper(node1, "llm_node_1", None, None)

        node2 = LLMSimulatorNode()
        wrapper2 = InstrumentedNodeWrapper(node2, "llm_node_2", None, None)

        shared = {}

        # First LLM call
        wrapper1._run(shared)
        # Second LLM call
        wrapper2._run(shared)

        # Check that both calls were accumulated
        assert len(shared["__llm_calls__"]) == 2
        assert shared["__llm_calls__"][0]["node_id"] == "llm_node_1"
        assert shared["__llm_calls__"][1]["node_id"] == "llm_node_2"

    def test_llm_usage_with_planner_flag(self):
        """Test that is_planner flag is correctly captured."""
        node = LLMSimulatorNode()
        wrapper = InstrumentedNodeWrapper(node, "planner_llm", None, None)

        shared = {"__is_planner__": True}
        wrapper._run(shared)

        # Check that is_planner flag was captured
        assert shared["__llm_calls__"][0]["is_planner"]

    def test_preserves_existing_llm_calls(self):
        """Test that existing __llm_calls__ list is preserved."""
        node = LLMSimulatorNode()
        wrapper = InstrumentedNodeWrapper(node, "new_llm", None, None)

        # Pre-existing LLM calls
        shared = {"__llm_calls__": [{"node_id": "old_llm", "model": "gpt-3.5", "total_tokens": 75}]}

        wrapper._run(shared)

        # Check that old call is preserved and new one is added
        assert len(shared["__llm_calls__"]) == 2
        assert shared["__llm_calls__"][0]["node_id"] == "old_llm"
        assert shared["__llm_calls__"][1]["node_id"] == "new_llm"

    def test_no_llm_usage_no_accumulation(self):
        """Test that nodes without LLM usage don't add to __llm_calls__."""
        node = SimpleTestNode()  # This node doesn't set llm_usage
        wrapper = InstrumentedNodeWrapper(node, "regular_node", None, None)

        shared = {}
        wrapper._run(shared)

        # __llm_calls__ should be created but empty
        assert "__llm_calls__" in shared
        assert len(shared["__llm_calls__"]) == 0


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
        assert not call_args[1]["is_planner"]

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
        # shared_before is captured before __llm_calls__ is added
        assert call_kwargs["shared_before"] == {"initial": "state"}

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
        assert not call_args[1]["is_planner"]

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
        assert call_kwargs["shared_before"] == {"input": "data"}
        # shared_after will include __llm_calls__ list and __execution__ checkpoint added by wrapper
        expected_shared = {
            "input": "data",
            "test_output": "executed",
            "__llm_calls__": [],
            "__cache_hits__": [],
            "__execution__": {
                "completed_nodes": ["test_node"],
                "node_actions": {"test_node": "test_result"},
                "node_hashes": {"test_node": ANY},  # Hash value depends on config
                "failed_node": None,
            },
        }
        assert call_kwargs["shared_after"] == expected_shared
        # Verify that a hash was computed
        assert isinstance(call_kwargs["shared_after"]["__execution__"]["node_hashes"]["test_node"], str)
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

        shared = {}
        result = wrapper._run(shared)

        assert result == "test_result"
        assert "__llm_calls__" in shared
        assert shared["test_output"] == "executed"

    def test_llm_usage_overwrite(self):
        """Test that each LLM call's usage is captured separately."""

        class OverwritingLLMNode(Node):
            def __init__(self, usage_data):
                self.usage_data = usage_data

            def _run(self, shared):
                shared["llm_usage"] = self.usage_data
                return "done"

        # First call sets one usage
        node1 = OverwritingLLMNode({"model": "gpt-3.5", "tokens": 100})
        wrapper1 = InstrumentedNodeWrapper(node1, "llm1")

        # Second call overwrites with different usage
        node2 = OverwritingLLMNode({"model": "gpt-4", "tokens": 200})
        wrapper2 = InstrumentedNodeWrapper(node2, "llm2")

        shared = {}
        wrapper1._run(shared)
        wrapper2._run(shared)

        # Both usages should be captured despite overwriting
        assert len(shared["__llm_calls__"]) == 2
        assert shared["__llm_calls__"][0]["model"] == "gpt-3.5"
        assert shared["__llm_calls__"][0]["tokens"] == 100
        assert shared["__llm_calls__"][0]["node_id"] == "llm1"
        assert shared["__llm_calls__"][1]["model"] == "gpt-4"
        assert shared["__llm_calls__"][1]["tokens"] == 200
        assert shared["__llm_calls__"][1]["node_id"] == "llm2"

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
        metrics.record_node_execution.assert_called_once_with("test_node", 0.0, is_planner=False)
