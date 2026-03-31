"""Integration tests for WorkflowExecutor with full workflow execution.

These tests compile and run full parent workflows that contain WorkflowExecutor
nodes, verifying the end-to-end pipeline: IR -> compile -> run -> shared store.

API (v0.9.0):
  - workflow: file path or saved name (replaces old workflow_ref)
  - workflow_ir: inline IR dict
  - Non-reserved params passed directly as child inputs (replaces old param_mapping)
  - Child outputs auto-exposed via namespace (replaces old output_mapping)
  - Storage modes: "mapped" (default) and "shared" only ("isolated" removed)
"""

from unittest.mock import Mock, patch

import pytest

from pflow.core.node import BaseNode
from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from pflow.runtime.workflow_executor import WorkflowExecutor
from tests.shared.markdown_utils import write_workflow_file


class TestWorkflowExecutorIntegration:
    """Integration tests for WorkflowExecutor with the full compilation pipeline."""

    def _setup_mock_imports(self, mock_test_node_class=None):
        """Setup mock imports for test nodes.

        The compiler uses importlib.import_module to load node classes from
        registry metadata. We mock this to provide test node implementations
        without needing real module files on disk.

        Args:
            mock_test_node_class: Optional custom test node class to use.
                If None, a default MockExampleNode is created that reads
                test_input from shared and writes test_output.

        Returns:
            Context manager for mocking imports
        """
        if mock_test_node_class is None:

            class MockExampleNode(BaseNode):
                def prep(self, shared):
                    return shared.get("test_input", "no input")

                def exec(self, prep_res):
                    return f"Processed: {prep_res}"

                def post(self, shared, prep_res, exec_res):
                    shared["test_output"] = exec_res
                    return "default"

            mock_test_node_class = MockExampleNode

        mock_module = Mock()
        mock_module.ExampleNode = mock_test_node_class
        mock_module.WorkflowExecutor = WorkflowExecutor

        def side_effect(module_path):
            if module_path == "pflow.nodes.test_node":
                return mock_module
            elif module_path == "pflow.runtime.workflow_executor":
                import pflow.runtime.workflow_executor

                return pflow.runtime.workflow_executor
            else:
                return mock_module

        return patch("importlib.import_module", side_effect=side_effect)

    @pytest.fixture
    def simple_workflow_ir(self):
        """A minimal child workflow IR with one test node."""
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "pflow.nodes.test_node", "params": {}}],
            "edges": [],
        }

    @pytest.fixture
    def nested_workflow_ir(self):
        """A parent workflow that calls a child workflow via inline IR.

        Uses direct params (new API) instead of param_mapping.
        """
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": {
                            "ir_version": "0.1.0",
                            "nodes": [{"id": "inner", "type": "pflow.nodes.test_node", "params": {}}],
                            "edges": [],
                        },
                        "test_input": "${outer_input}",
                    },
                }
            ],
            "edges": [],
        }

    @pytest.fixture
    def mock_registry(self, tmp_path):
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
        }

        registry.save(registry_data)
        return registry

    @pytest.fixture
    def workflow_file(self, simple_workflow_ir, tmp_path):
        """Create a temporary .pflow.md workflow file from simple_workflow_ir."""
        workflow_path = tmp_path / "test_workflow.pflow.md"
        write_workflow_file(simple_workflow_ir, workflow_path)
        return workflow_path

    # ------------------------------------------------------------------ #
    # Tests
    # ------------------------------------------------------------------ #

    def test_inline_workflow_execution(self, simple_workflow_ir, mock_registry):
        """When a parent workflow contains an inline child, execution succeeds.

        Verifies the full pipeline: compile parent IR with a WorkflowExecutor
        node that uses workflow_ir, pass child inputs as direct params, and
        confirm the flow returns "default".
        """
        parent_ir = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": simple_workflow_ir,
                        # Direct param — passed as child input (new API)
                        "test_input": "Hello from parent",
                    },
                }
            ],
            "edges": [],
            "outputs": {},
        }

        with self._setup_mock_imports():
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

            assert result == "default"

    def test_file_workflow_execution(self, workflow_file, mock_registry):
        """When a parent workflow references a child by file path, execution succeeds.

        Uses the new 'workflow' param (replaces old 'workflow_ref') and direct
        child input params (replaces old 'param_mapping').
        """
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow": str(workflow_file),
                        "test_input": "Hello from file",
                    },
                }
            ],
            "edges": [],
        }

        with self._setup_mock_imports():
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

            assert result == "default"

    def test_nested_workflow_execution(self, nested_workflow_ir, mock_registry):
        """When workflows nest (parent -> child -> inner node), all levels execute."""
        execution_order = []

        class TrackingExampleNode(BaseNode):
            def prep(self, shared):
                return None

            def exec(self, prep_res):
                execution_order.append("inner")
                return None

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(TrackingExampleNode):
            workflow = compile_workflow(nested_workflow_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["outer_input"] = "test_value"
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

            assert result == "default"
            assert len(execution_order) > 0, "Inner node should have executed"

    def test_error_propagation(self, simple_workflow_ir, mock_registry):
        """When a child workflow node raises, the error propagates to parent shared store."""
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {"workflow_ir": simple_workflow_ir, "error_action": "error"},
                }
            ],
            "edges": [],
        }

        class FailingExampleNode(BaseNode):
            def prep(self, shared):
                return None

            def exec(self, prep_res):
                raise RuntimeError("Child failed")

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(FailingExampleNode):
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

            # WorkflowExecutor returns error_action value
            assert result == "error"
            # With namespacing, error is at shared[node_id]["error"]
            assert "sub" in shared
            assert "error" in shared["sub"]
            assert "Child failed" in shared["sub"]["error"]

    def test_storage_mapped_isolation(self, simple_workflow_ir, mock_registry):
        """When storage_mode is 'mapped' (default), child does not see parent data.

        The child storage starts with only the mapped child inputs and internal
        _pflow_ keys. Parent-level data like 'parent_data' is invisible.
        """
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": simple_workflow_ir,
                        "storage_mode": "mapped",
                        "test_input": "child_sees_this",
                    },
                }
            ],
            "edges": [],
        }

        child_storage_snapshot = {}

        class StorageCapturingNode(BaseNode):
            def prep(self, shared):
                nonlocal child_storage_snapshot
                # Capture all non-internal keys that the child can see
                child_storage_snapshot = {
                    k: v for k, v in shared.items() if not k.startswith("_pflow_") and not k.startswith("__")
                }
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(StorageCapturingNode):
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["parent_data"] = "should_not_leak"
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

            assert result == "default"
            # Child should see only its mapped input, not parent_data
            assert "parent_data" not in child_storage_snapshot
            assert child_storage_snapshot.get("test_input") == "child_sees_this"

    def test_parameter_passing_to_child(self, mock_registry):
        """When direct params are set on the workflow executor node, child receives them.

        Uses the new API where non-reserved params are passed directly as child
        inputs (replaces old param_mapping dict).
        """
        child_workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "pflow.nodes.test_node",
                    "params": {},
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_workflow,
                        "test_input": "mapped_value",
                    },
                }
            ],
            "edges": [],
        }

        received_input = {}

        class InputCapturingNode(BaseNode):
            def prep(self, shared):
                nonlocal received_input
                received_input["test_input"] = shared.get("test_input")
                return shared.get("test_input")

            def exec(self, prep_res):
                return f"Processed: {prep_res}"

            def post(self, shared, prep_res, exec_res):
                shared["test_output"] = exec_res
                return "default"

        with self._setup_mock_imports(InputCapturingNode):
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

            assert result == "default"
            assert received_input["test_input"] == "mapped_value"

    def test_depth_tracking(self, mock_registry):
        """When workflows nest 3 levels deep, depth increments at each level."""
        level3 = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "leaf", "type": "pflow.nodes.test_node", "params": {}}],
            "edges": [],
        }

        level2 = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "l2", "type": "pflow.runtime.workflow_executor", "params": {"workflow_ir": level3}}],
            "edges": [],
        }

        level1 = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "l1", "type": "pflow.runtime.workflow_executor", "params": {"workflow_ir": level2}}],
            "edges": [],
        }

        depths_seen = []

        class DepthTrackingNode(BaseNode):
            def prep(self, shared):
                depth = shared.get("_pflow_depth", 0)
                depths_seen.append(depth)
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(DepthTrackingNode):
            workflow = compile_workflow(level1, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

            assert result == "default"
            # Leaf node is at depth 2 (level1=0, level2=1, level3=2)
            assert max(depths_seen) >= 2

    def test_auto_output_exposure(self, mock_registry):
        """When child workflow writes to shared, outputs are auto-exposed in parent namespace.

        The chain is:
        1. Child node "producer" writes to its NamespacedSharedStore, landing in
           child_storage["producer"]["result_key"]
        2. WorkflowExecutor.post() iterates child_storage root keys and copies
           non-internal ones to its own shared (which is the parent's NamespacedSharedStore)
        3. The parent NamespacedNodeWrapper for "sub" redirects writes so the
           final location is: parent_shared["sub"]["producer"]["result_key"]
        """
        child_workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "producer",
                    "type": "pflow.nodes.test_node",
                    "params": {},
                }
            ],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_workflow,
                    },
                }
            ],
            "edges": [],
        }

        class OutputProducingNode(BaseNode):
            """Node that writes a known value to shared store."""

            def prep(self, shared):
                return None

            def exec(self, prep_res):
                return "computed_result"

            def post(self, shared, prep_res, exec_res):
                shared["result_key"] = exec_res
                shared["extra_data"] = {"nested": True}
                return "default"

        with self._setup_mock_imports(OutputProducingNode):
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            result = engine.run(workflow, shared)

            assert result == "default"
            # Child outputs are auto-exposed under the parent node's namespace.
            # Because the child node "producer" is also namespaced inside the child
            # workflow, its outputs land at shared["sub"]["producer"][key].
            assert "sub" in shared
            assert "producer" in shared["sub"]
            assert shared["sub"]["producer"]["result_key"] == "computed_result"
            assert shared["sub"]["producer"]["extra_data"] == {"nested": True}
