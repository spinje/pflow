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
        shared: dict = {}

        # No parameters should raise error
        node.set_params({})
        with pytest.raises(ValueError, match="requires either 'workflow' or 'workflow_ir'"):
            node.prep(shared)

        # Both parameters should raise error
        node.set_params({"workflow": "test.json", "workflow_ir": {"nodes": []}})
        with pytest.raises(ValueError, match="Only one of 'workflow' or 'workflow_ir'"):
            node.prep(shared)

    def test_circular_dependency_detection(self):
        """Test circular dependency detection."""
        node = WorkflowExecutor()

        # Set up circular reference — /path/to/workflow1.json is already in the stack
        shared = {"_pflow_stack": ["/path/to/workflow1.json", "/path/to/workflow2.json"]}

        node.set_params({
            "workflow": "/path/to/workflow1.json"  # Already in stack
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
        """Test that non-reserved params are passed as child inputs with template resolution."""
        node = WorkflowExecutor()

        shared = {"input_data": "test_value", "config": {"api_key": "secret"}}

        # Non-reserved params become child inputs directly (no param_mapping wrapper)
        node.set_params({
            "workflow_ir": {"nodes": []},
            "data": "${input_data}",
            "key": "${config.api_key}",
            "static": "fixed_value",
        })

        prep_res = node.prep(shared)

        assert prep_res["child_params"]["data"] == "test_value"
        assert prep_res["child_params"]["key"] == "secret"
        assert prep_res["child_params"]["static"] == "fixed_value"

    def test_reserved_params_excluded_from_child_inputs(self):
        """Test that reserved params (workflow_ir, storage_mode, etc.) are not passed to child."""
        node = WorkflowExecutor()
        shared: dict = {}

        node.set_params({
            "workflow_ir": {"nodes": []},
            "storage_mode": "mapped",
            "max_depth": 5,
            "error_action": "fail",
            "user_param": "should_pass",
        })

        prep_res = node.prep(shared)

        # Only non-reserved params should appear in child_params
        assert "user_param" in prep_res["child_params"]
        assert prep_res["child_params"]["user_param"] == "should_pass"
        assert "workflow_ir" not in prep_res["child_params"]
        assert "storage_mode" not in prep_res["child_params"]
        assert "max_depth" not in prep_res["child_params"]
        assert "error_action" not in prep_res["child_params"]

    def test_storage_modes(self):
        """Test mapped and shared storage isolation modes."""
        node = WorkflowExecutor()
        parent_shared = {"parent_data": "value", "_pflow_internal": "reserved"}

        prep_res = {
            "child_params": {"param": "value"},
            "current_depth": 0,
            "execution_stack": [],
            "workflow_path": "test.json",
        }

        # Test mapped mode — child gets only child_params (plus pflow internals)
        storage = node._create_child_storage(parent_shared, "mapped", prep_res)
        assert storage["param"] == "value"
        assert "parent_data" not in storage
        # Execution context is always injected
        assert storage["_pflow_depth"] == 1
        assert storage["_pflow_stack"] == ["test.json"]
        assert storage["_pflow_workflow_file"] == "test.json"

        # Test shared mode — child gets the exact same reference as parent
        storage = node._create_child_storage(parent_shared, "shared", prep_res)
        assert storage is parent_shared  # Same reference

        # Test invalid mode — should raise ValueError
        with pytest.raises(ValueError, match="Invalid storage_mode"):
            node._create_child_storage(parent_shared, "isolated", prep_res)
