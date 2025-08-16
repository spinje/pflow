"""Unit tests for WorkflowExecutor."""

import pytest

from pflow.runtime.workflow_executor import WorkflowExecutor


class TestWorkflowExecutor:
    """Test WorkflowExecutor functionality."""

    def test_node_creation(self):
        """Test basic node instantiation."""
        node = WorkflowExecutor()
        assert node is not None
        assert hasattr(node, "prep")
        assert hasattr(node, "exec")
        assert hasattr(node, "post")

    def test_parameter_validation(self):
        """Test parameter validation in prep phase."""
        node = WorkflowExecutor()
        shared = {}

        # No parameters should raise error
        node.set_params({})
        with pytest.raises(ValueError, match="WorkflowExecutor requires either"):
            node.prep(shared)

        # Both parameters should raise error
        node.set_params({"workflow_ref": "test.json", "workflow_ir": {"nodes": []}})
        with pytest.raises(ValueError, match="Only one of"):
            node.prep(shared)

    def test_circular_dependency_detection(self):
        """Test circular dependency detection."""
        node = WorkflowExecutor()

        # Set up circular reference
        shared = {"_pflow_stack": ["/path/to/workflow1.json", "/path/to/workflow2.json"]}

        node.set_params({
            "workflow_ref": "/path/to/workflow1.json"  # Already in stack
        })

        with pytest.raises(ValueError, match="Circular workflow reference"):
            node.prep(shared)

    def test_max_depth_enforcement(self):
        """Test maximum nesting depth."""
        node = WorkflowExecutor()

        shared = {
            "_pflow_depth": 10  # Already at max depth
        }

        node.set_params({"workflow_ir": {"nodes": []}, "max_depth": 10})

        with pytest.raises(RecursionError, match="Maximum workflow nesting depth"):
            node.prep(shared)

    def test_parameter_mapping(self):
        """Test parameter mapping resolution."""
        node = WorkflowExecutor()

        shared = {"input_data": "test_value", "config": {"api_key": "secret"}}

        node.set_params({
            "workflow_ir": {"nodes": []},
            "param_mapping": {"data": "${input_data}", "key": "${config.api_key}", "static": "fixed_value"},
        })

        prep_res = node.prep(shared)

        assert prep_res["child_params"]["data"] == "test_value"
        assert prep_res["child_params"]["key"] == "secret"
        assert prep_res["child_params"]["static"] == "fixed_value"

    def test_storage_modes(self):
        """Test different storage isolation modes."""
        node = WorkflowExecutor()
        parent_shared = {"parent_data": "value", "child_data": "child_value", "_pflow_internal": "reserved"}

        prep_res = {
            "child_params": {"param": "value"},
            "current_depth": 0,
            "execution_stack": [],
            "workflow_path": "test.json",
        }

        # Test mapped mode
        storage = node._create_child_storage(parent_shared, "mapped", prep_res)
        assert storage["param"] == "value"
        assert "parent_data" not in storage

        # Test isolated mode
        storage = node._create_child_storage(parent_shared, "isolated", prep_res)
        assert len([k for k in storage if not k.startswith("_pflow_")]) == 0

        # Test scoped mode
        node.set_params({"scope_prefix": "child_"})
        storage = node._create_child_storage(parent_shared, "scoped", prep_res)
        assert storage["data"] == "child_value"
        assert "parent_data" not in storage

        # Test shared mode
        storage = node._create_child_storage(parent_shared, "shared", prep_res)
        assert storage is parent_shared  # Same reference
