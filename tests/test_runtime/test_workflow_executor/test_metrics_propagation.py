"""Tests for cross-cutting key propagation from parent to child workflows.

Verifies that infrastructure keys (__progress_callback__, __mcp_pool__,
__warnings__, _trace_collector) are propagated through workflow nesting
boundaries via WorkflowExecutor._PROPAGATED_KEYS / _create_child_storage().

This ensures progress callbacks reach nested nodes, MCP connection pools
are shared, and trace collectors are propagated for LLM data capture.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.pocketflow import BaseNode
from pflow.registry import Registry
from pflow.runtime import compile_ir_to_flow
from pflow.runtime.workflow_executor import WorkflowExecutor


class MockLLMNode(BaseNode):
    """Simulates an LLM node by writing llm_usage to the shared store.

    InstrumentedNodeWrapper enriches llm_usage with cost via _enrich_llm_cost(),
    then the trace collector captures it via _record_trace() → _add_llm_data().
    """

    def prep(self, shared):
        return None

    def exec(self, prep_res):
        return "mock response"

    def post(self, shared, prep_res, exec_res):
        shared["response"] = exec_res
        shared["llm_usage"] = {
            "model": "test-model",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }
        return "default"


class SourceNode(BaseNode):
    """Provides a list of items for batch processing."""

    def prep(self, shared):
        return None

    def exec(self, prep_res):
        return None

    def post(self, shared, prep_res, exec_res):
        shared["result"] = ["alpha", "beta", "gamma"]
        return "default"


def _setup_mock_imports(mock_node_class=None):
    """Setup mock imports for test nodes.

    Follows the exact pattern from test_integration.py. The compiler uses
    importlib.import_module to load node classes from registry metadata.
    We mock this to provide test node implementations.
    """
    if mock_node_class is None:
        mock_node_class = MockLLMNode

    mock_llm_module = Mock()
    mock_llm_module.ExampleNode = mock_node_class
    mock_llm_module.WorkflowExecutor = WorkflowExecutor

    mock_source_module = Mock()
    mock_source_module.SourceNode = SourceNode

    def side_effect(module_path):
        if module_path == "pflow.nodes.test_node":
            return mock_llm_module
        elif module_path == "pflow.nodes.source_node":
            return mock_source_module
        elif module_path == "pflow.runtime.workflow_executor":
            import pflow.runtime.workflow_executor

            return pflow.runtime.workflow_executor
        else:
            return mock_llm_module

    return patch("importlib.import_module", side_effect=side_effect)


@pytest.fixture
def mock_registry(tmp_path):
    """Create a mock registry with test nodes and workflow executor."""
    registry_path = tmp_path / "test_registry.json"
    registry = Registry(registry_path)

    registry_data = {
        "pflow.nodes.test_node": {
            "module": "pflow.nodes.test_node",
            "class_name": "ExampleNode",
            "docstring": "Test node for testing",
            "file_path": "/mock/path/test_node.py",
            "interface": {
                "inputs": [],
                "outputs": [{"key": "test_output", "type": "string"}],
                "parameters": [],
            },
        },
        "pflow.runtime.workflow_executor": {
            "module": "pflow.runtime.workflow_executor",
            "class_name": "WorkflowExecutor",
            "docstring": "Runtime executor for nested workflow execution",
            "file_path": "/mock/path/workflow_executor.py",
            "interface": {
                "inputs": [],
                "outputs": [],
                "parameters": [
                    {"key": "workflow", "type": "string", "required": False},
                    {"key": "workflow_ir", "type": "dict", "required": False},
                    {"key": "storage_mode", "type": "string", "required": False},
                    {"key": "max_depth", "type": "integer", "required": False},
                    {"key": "error_action", "type": "string", "required": False},
                ],
            },
        },
        "pflow.nodes.source_node": {
            "module": "pflow.nodes.source_node",
            "class_name": "SourceNode",
            "docstring": "Provides items for batch processing",
            "file_path": "/mock/path/source_node.py",
            "interface": {
                "inputs": [],
                "outputs": [{"key": "result", "type": "array"}],
                "parameters": [],
            },
        },
    }

    registry.save(registry_data)
    return registry


# ------------------------------------------------------------------ #
# Integration tests: full compile + run pipeline
# ------------------------------------------------------------------ #


class TestLLMCallsViaTrace:
    """Verify LLM data is captured via trace events across workflow nesting."""

    def test_single_sub_workflow_llm_calls_in_trace(self, mock_registry):
        """When parent and child each have an LLM node, trace captures both.

        Parent runs "direct-llm" (MockLLMNode), then "child-call" (WorkflowExecutor
        with inline IR containing one MockLLMNode). The trace collector should
        capture LLM calls from both levels via collect_llm_calls().
        """
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "inner-llm",
                    "type": "pflow.nodes.test_node",
                    "params": {},
                    "purpose": "Simulate LLM call inside child workflow",
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "direct-llm",
                    "type": "pflow.nodes.test_node",
                    "params": {},
                    "purpose": "Simulate LLM call in parent workflow",
                },
                {
                    "id": "child-call",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_ir,
                    },
                    "purpose": "Execute child workflow with LLM node",
                },
            ],
            "edges": [{"from": "direct-llm", "to": "child-call"}],
        }

        trace = WorkflowTraceCollector("test")

        with _setup_mock_imports():
            flow = compile_ir_to_flow(parent_ir, registry=mock_registry, trace_collector=trace)
            shared: dict = {"_trace_collector": trace}
            flow.run(shared)

            # Both parent and child LLM calls must appear in collect_llm_calls()
            calls = trace.collect_llm_calls()
            assert len(calls) == 2, f"Expected 2 LLM calls (parent + child), got {len(calls)}"
            node_ids = [call["node_id"] for call in calls]
            assert "direct-llm" in node_ids, "Parent LLM call not captured"
            assert "inner-llm" in node_ids, "Child sub-workflow LLM call not captured"

            # Verify token counts survive the trace path
            for call in calls:
                assert call["total_tokens"] == 150
                assert call["input_tokens"] == 100
                assert call["output_tokens"] == 50

    def test_batched_sub_workflow_llm_calls_in_trace(self, mock_registry):
        """Batch items each running a child workflow with LLM — all costs captured.

        This is the highest-risk scenario: batch creates shallow copies of shared,
        then each batch item runs a WorkflowExecutor. The child creates its own
        trace collector, which the parent embeds as sub_workflow_events.
        Three layers of indirection must work correctly.

        Topology: source -> batch-children (3 items, each runs child workflow with 1 LLM)
        Expected: 3 LLM calls in collect_llm_calls() (one per batch item's child).
        """
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "child-llm",
                    "type": "pflow.nodes.test_node",
                    "params": {},
                    "purpose": "Simulate LLM call inside batched child workflow",
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "pflow.nodes.source_node",
                    "params": {},
                    "purpose": "Provide items list for batch processing",
                },
                {
                    "id": "batch-children",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_ir,
                    },
                    "batch": {"items": "${source.result}"},
                    "purpose": "Run child workflow for each item in batch",
                },
            ],
            "edges": [{"from": "source", "to": "batch-children"}],
        }

        trace = WorkflowTraceCollector("test")

        with _setup_mock_imports():
            flow = compile_ir_to_flow(parent_ir, registry=mock_registry, trace_collector=trace)
            shared: dict = {"_trace_collector": trace}
            flow.run(shared)

            # 3 batch items x 1 LLM call each = 3 total
            calls = trace.collect_llm_calls()
            assert len(calls) == 3, f"Expected 3 LLM calls (one per batch item), got {len(calls)}"
            for call in calls:
                assert call["node_id"] == "child-llm"
                assert call["total_tokens"] == 150


class TestProgressCallbackPropagation:
    """Verify __progress_callback__ is propagated to child workflows."""

    def test_progress_callback_propagated(self, mock_registry):
        """When parent has a progress callback, child's InstrumentedNodeWrapper invokes it.

        The progress callback is used for real-time execution feedback. If it's not
        propagated, nested workflow execution appears silent to the user.
        """
        callback = Mock()

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "inner-node",
                    "type": "pflow.nodes.test_node",
                    "params": {},
                    "purpose": "Node inside child that should trigger callback",
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "child-call",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_ir,
                    },
                    "purpose": "Execute child workflow to test callback propagation",
                },
            ],
            "edges": [],
        }

        with _setup_mock_imports():
            flow = compile_ir_to_flow(parent_ir, registry=mock_registry)
            shared: dict = {"__progress_callback__": callback}
            flow.run(shared)

            # The callback should have been called at least once by the child's
            # InstrumentedNodeWrapper (it calls on node start and completion)
            assert callback.call_count > 0


# ------------------------------------------------------------------ #
# Unit tests: _create_child_storage directly
# ------------------------------------------------------------------ #


class TestCreateChildStorage:
    """Unit tests for WorkflowExecutor._create_child_storage().

    Tests the propagation mechanism directly without the full compilation
    pipeline overhead.
    """

    def _make_prep_res(self, workflow_path="test.pflow.md"):
        """Create a minimal prep_res dict for _create_child_storage."""
        return {
            "child_params": {"input1": "value1"},
            "current_depth": 0,
            "execution_stack": [],
            "workflow_path": workflow_path,
        }

    def test_propagated_keys_in_child_storage(self):
        """When parent has all propagated keys, child storage gets same object references.

        This is the core invariant: propagated keys must be the SAME objects
        (not copies), so that child workflows share resources with the parent.
        """
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": {"nodes": [], "ir_version": "0.1.0"}})

        progress_cb = Mock()
        mcp_pool = Mock()
        warnings_dict: dict = {}
        registry = Mock()
        trace_collector = Mock()

        memo_cache = Mock()

        parent_shared: dict = {
            "__progress_callback__": progress_cb,
            "__mcp_pool__": mcp_pool,
            "__warnings__": warnings_dict,
            "__registry__": registry,
            "_trace_collector": trace_collector,
            "__memoization_cache__": memo_cache,
            "_pflow_depth": 0,
            "_pflow_stack": [],
        }

        prep_res = self._make_prep_res()
        child_storage = node._create_child_storage(parent_shared, "mapped", prep_res)

        # All propagated keys present and are same object references
        assert child_storage["__progress_callback__"] is progress_cb
        assert child_storage["__mcp_pool__"] is mcp_pool
        assert child_storage["__warnings__"] is warnings_dict
        assert child_storage["__registry__"] is registry
        assert child_storage["_trace_collector"] is trace_collector
        assert child_storage["__memoization_cache__"] is memo_cache

        # Child params are present
        assert child_storage["input1"] == "value1"

        # Execution-scoped keys are NOT propagated (they are per-workflow)
        assert "__execution__" not in child_storage
        assert "__cache_hits__" not in child_storage
        assert "__template_errors__" not in child_storage

    def test_propagated_keys_not_present_in_parent(self):
        """When parent lacks propagated keys, child simply does not have them.

        No KeyError should occur. This handles the case where a workflow is
        run without the full executor service (e.g., in tests).
        """
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": {"nodes": [], "ir_version": "0.1.0"}})

        parent_shared: dict = {
            "_pflow_depth": 0,
            "_pflow_stack": [],
        }

        prep_res = self._make_prep_res()
        child_storage = node._create_child_storage(parent_shared, "mapped", prep_res)

        # None of the propagated keys should be present
        assert "__progress_callback__" not in child_storage
        assert "__mcp_pool__" not in child_storage
        assert "__warnings__" not in child_storage
        assert "__registry__" not in child_storage
        assert "_trace_collector" not in child_storage

        # Should still have child params and execution context
        assert child_storage["input1"] == "value1"
        assert child_storage["_pflow_depth"] == 1

    def test_shared_mode_propagation_is_noop(self):
        """When storage_mode is 'shared', child_storage IS parent_shared (same object).

        In shared mode, the child operates directly on the parent's storage.
        Propagation is effectively a no-op because the keys are already there.
        """
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": {"nodes": [], "ir_version": "0.1.0"}})

        trace_collector = Mock()
        parent_shared: dict = {
            "_trace_collector": trace_collector,
            "__progress_callback__": Mock(),
            "_pflow_depth": 0,
            "_pflow_stack": [],
        }

        prep_res = self._make_prep_res()
        child_storage = node._create_child_storage(parent_shared, "shared", prep_res)

        # In shared mode, child_storage IS parent_shared
        assert child_storage is parent_shared

        # The propagated keys are naturally present since it's the same dict
        assert child_storage["_trace_collector"] is trace_collector

    def test_trace_collector_reference_identity(self):
        """_trace_collector in child is the same object as in parent.

        This ensures child workflows can detect tracing is active by checking
        for the presence of _trace_collector in their storage.
        """
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": {"nodes": [], "ir_version": "0.1.0"}})

        trace_collector = Mock()
        parent_shared: dict = {
            "_trace_collector": trace_collector,
            "_pflow_depth": 0,
            "_pflow_stack": [],
        }

        prep_res = self._make_prep_res()
        child_storage = node._create_child_storage(parent_shared, "mapped", prep_res)

        # Same object reference — not a copy
        assert child_storage["_trace_collector"] is trace_collector
