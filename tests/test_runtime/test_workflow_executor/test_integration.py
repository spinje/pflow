"""Integration tests for WorkflowExecutor with full workflow execution."""

import json
from unittest.mock import Mock, patch

import pytest

from pflow.pocketflow import BaseNode
from pflow.registry import Registry
from pflow.runtime import compile_ir_to_flow
from pflow.runtime.workflow_executor import WorkflowExecutor


class TestWorkflowExecutorIntegration:
    """Integration tests for WorkflowExecutor."""

    def _setup_mock_imports(self, mock_test_node_class=None):
        """Setup mock imports for test nodes.

        Args:
            mock_test_node_class: Optional custom test node class to use

        Returns:
            Context manager for mocking imports
        """
        from pflow.pocketflow import BaseNode

        # Default mock ExampleNode if not provided
        if mock_test_node_class is None:

            class MockExampleNode(BaseNode):
                def prep(self, shared):
                    return None

                def exec(self, prep_res):
                    return None

                def post(self, shared, prep_res, exec_res):
                    return "default"

            mock_test_node_class = MockExampleNode

        # Create the patch context
        mock_module = Mock()
        mock_module.ExampleNode = mock_test_node_class
        mock_module.WorkflowExecutor = WorkflowExecutor  # Real WorkflowExecutor
        mock_module.WriteFileNode = Mock()  # For other tests

        def side_effect(module_path):
            if module_path == "pflow.nodes.test_node":
                return mock_module
            elif module_path == "pflow.runtime.workflow_executor":
                # Return the actual workflow module
                import pflow.runtime.workflow_executor

                return pflow.runtime.workflow_executor
            elif module_path == "pflow.nodes.file.write_file":
                # For file tests
                return mock_module
            else:
                # For other modules, return a mock
                return mock_module

        return patch("importlib.import_module", side_effect=side_effect)

    @pytest.fixture
    def simple_workflow_ir(self):
        """Create a simple test workflow IR."""
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "pflow.nodes.test_node", "params": {}}],
            "edges": [],
        }

    @pytest.fixture
    def file_workflow_ir(self, tmp_path):
        """Create a workflow using file nodes."""
        # Note: Don't use templates in nested workflow_ir since they can't be resolved
        # at parent level. Templates should be resolved within the nested workflow.
        test_file = tmp_path / "test.txt"
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "write",
                    "type": "pflow.nodes.file.write_file",
                    "params": {"file_path": str(test_file), "content": "test content"},
                }
            ],
            "edges": [],
        }

    @pytest.fixture
    def nested_workflow_ir(self):
        """Create a workflow that calls another workflow."""
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
                        "param_mapping": {"test_input": "${outer_input}"},
                        "output_mapping": {"test_output": "inner_result"},
                    },
                }
            ],
            "edges": [],
        }

    @pytest.fixture
    def mock_registry(self, tmp_path):
        """Create a mock registry with test nodes."""
        registry_path = tmp_path / "test_registry.json"
        registry = Registry(registry_path)

        # Create registry data
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
                        {"key": "workflow_ref", "type": "string", "required": False},
                        {"key": "parameter_mapping", "type": "dict", "required": False},
                    ],
                },
            },
            "pflow.nodes.file.write_file": {
                "module": "pflow.nodes.file.write_file",
                "class_name": "WriteFileNode",
                "docstring": "Write content to a file",
                "file_path": "/mock/path/write_file.py",
                "interface": {
                    "inputs": [],
                    "outputs": [],
                    "parameters": [
                        {"key": "file_path", "type": "string", "required": True},
                        {"key": "content", "type": "string", "required": True},
                    ],
                },
            },
        }

        # Save registry data
        registry.save(registry_data)

        return registry

    @pytest.fixture
    def workflow_file(self, simple_workflow_ir, tmp_path):
        """Create a temporary workflow file."""
        workflow_path = tmp_path / "test_workflow.json"
        with open(workflow_path, "w") as f:
            json.dump(simple_workflow_ir, f)
        return workflow_path

    def test_inline_workflow_execution(self, simple_workflow_ir, mock_registry):
        """Test executing an inline workflow."""
        # Create parent workflow with WorkflowExecutor
        parent_ir = {
            "ir_version": "0.1.0",
            "inputs": {},  # No inputs, message comes from shared store at runtime
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": simple_workflow_ir,
                        # Don't use templates here, pass concrete values
                        "param_mapping": {"test_input": "Hello from parent"},
                        "output_mapping": {"test_output": "result"},
                    },
                }
            ],
            "edges": [],
            "outputs": {},
        }

        # Use the helper to setup mocks
        with self._setup_mock_imports():
            # Compile and run
            flow = compile_ir_to_flow(parent_ir, registry=mock_registry, validate=False)
            shared = {}
            result = flow.run(shared)

            assert result == "default"

    def test_file_workflow_execution(self, workflow_file, mock_registry):
        """Test loading and executing workflow from file."""
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {"workflow_ref": str(workflow_file), "param_mapping": {"test_input": "Hello from file"}},
                }
            ],
            "edges": [],
        }

        with self._setup_mock_imports():
            flow = compile_ir_to_flow(parent_ir, registry=mock_registry, validate=False)
            shared = {"__registry__": mock_registry}
            result = flow.run(shared)

            assert result == "default"

    def test_nested_workflow_execution(self, nested_workflow_ir, mock_registry):
        """Test workflows calling other workflows."""
        # Track execution order
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
            flow = compile_ir_to_flow(nested_workflow_ir, registry=mock_registry, validate=False)
            shared = {"outer_input": "test_value", "__registry__": mock_registry}
            result = flow.run(shared)

            assert result == "default"
            assert len(execution_order) > 0  # Inner node was executed

    def test_error_propagation(self, simple_workflow_ir, mock_registry):
        """Test error propagation from child workflow."""
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    # WorkflowExecutor returns the value of error_action param (or "error" by default)
                    "params": {"workflow_ir": simple_workflow_ir, "error_action": "error"},
                }
            ],
            "edges": [],
        }

        # Create a failing test node
        class FailingExampleNode(BaseNode):
            def prep(self, shared):
                return None

            def exec(self, prep_res):
                raise RuntimeError("Child failed")

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(FailingExampleNode):
            flow = compile_ir_to_flow(parent_ir, registry=mock_registry, validate=False)
            shared = {"__registry__": mock_registry}
            result = flow.run(shared)

            # WorkflowExecutor returns error_action value (or "error" by default)
            assert result == "error"
            # With namespacing, error is at shared[node_id]["error"]
            assert "sub" in shared
            assert "error" in shared["sub"]
            assert "Child failed" in shared["sub"]["error"]

    def test_storage_isolation(self, simple_workflow_ir, mock_registry):
        """Test that storage isolation works correctly."""
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {"workflow_ir": simple_workflow_ir, "storage_mode": "isolated"},
                }
            ],
            "edges": [],
        }

        # Track what the child sees
        child_storage_snapshot = None

        class StorageCapturingNode(BaseNode):
            def prep(self, shared):
                nonlocal child_storage_snapshot
                child_storage_snapshot = {
                    k: v for k, v in shared.items() if not k.startswith("_pflow_") and not k.startswith("__")
                }
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(StorageCapturingNode):
            flow = compile_ir_to_flow(parent_ir, registry=mock_registry, validate=False)
            shared = {"parent_data": "should_not_see", "__registry__": mock_registry}
            result = flow.run(shared)

            assert result == "default"
            assert len(child_storage_snapshot) == 0  # Isolated mode = empty

    def test_parameter_mapping_flow(self, mock_registry, tmp_path):
        """Test parameter mapping through workflow execution."""
        # Create a simple workflow using test node instead of file node
        # (file nodes are harder to mock correctly in nested workflows)
        simple_test_workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "pflow.nodes.test_node",
                    "params": {},  # Params will be provided via param_mapping
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
                        "workflow_ir": simple_test_workflow,
                        # Use concrete values for parameter mapping
                        "param_mapping": {"test_input": "mapped_value"},
                    },
                }
            ],
            "edges": [],
        }

        # Track execution to verify nested workflow ran
        execution_tracker = []

        class TrackingTestNode(BaseNode):
            def prep(self, shared):
                execution_tracker.append("executed")
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(TrackingTestNode):
            flow = compile_ir_to_flow(parent_ir, registry=mock_registry, validate=False)
            shared = {"__registry__": mock_registry}
            result = flow.run(shared)

            # Verify workflow executed successfully
            assert result == "default"
            # Verify nested workflow's node was executed
            assert len(execution_tracker) > 0, "Nested workflow node should have executed"

    def test_depth_tracking(self, mock_registry):
        """Test that depth is properly tracked through nested workflows."""
        # Create a 3-level nested workflow
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
            flow = compile_ir_to_flow(level1, registry=mock_registry)
            shared = {"__registry__": mock_registry}
            result = flow.run(shared)

            assert result == "default"
            # Should see depths 0, 1, 2, 3 (including root)
            assert max(depths_seen) >= 2  # At least reached depth 2
