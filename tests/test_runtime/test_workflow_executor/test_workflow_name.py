"""Tests for WorkflowExecutor's workflow_name parameter functionality."""

from unittest.mock import Mock, patch

import pytest

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.workflow_manager import WorkflowManager
from pflow.runtime.workflow_executor import WorkflowExecutor
from tests.shared.markdown_utils import ir_to_markdown


class TestWorkflowNameParameter:
    """Test WorkflowExecutor's ability to load workflows by name."""

    @pytest.fixture
    def simple_workflow_ir(self):
        """Basic workflow IR for testing."""
        return {"nodes": [{"id": "test_node", "type": "echo", "params": {"message": "test"}}], "edges": []}

    @pytest.fixture
    def workflow_manager(self, tmp_path, simple_workflow_ir):
        """Create WorkflowManager with a test workflow."""
        workflows_dir = tmp_path / ".pflow" / "workflows"
        workflows_dir.mkdir(parents=True)

        manager = WorkflowManager(workflows_dir)
        markdown_content = ir_to_markdown(
            simple_workflow_ir,
            title="Test Workflow",
            description="Test workflow for testing",
        )
        manager.save("test-workflow", markdown_content)

        return manager

    def test_workflow_name_only(self, workflow_manager, simple_workflow_ir):
        """Test loading workflow by name using WorkflowManager."""
        # Mock WorkflowManager to return our test workflow
        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({"workflow_name": "test-workflow"})

            shared = {}
            prep_res = node.prep(shared)

            # Verify workflow was loaded correctly
            loaded_ir = prep_res["workflow_ir"]
            assert loaded_ir["nodes"][0]["id"] == simple_workflow_ir["nodes"][0]["id"]
            assert loaded_ir["nodes"][0]["type"] == simple_workflow_ir["nodes"][0]["type"]
            assert loaded_ir["nodes"][0]["params"] == simple_workflow_ir["nodes"][0]["params"]
            assert "test-workflow.pflow.md" in prep_res["workflow_path"]
            assert prep_res["workflow_source"] == "name:test-workflow"

    def test_workflow_name_not_found(self):
        """Test error when workflow name doesn't exist."""
        node = WorkflowExecutor()
        node.set_params({"workflow_name": "non-existent-workflow"})

        shared = {}
        with pytest.raises(ValueError, match="Failed to load workflow 'non-existent-workflow'"):
            node.prep(shared)

    def test_workflow_name_takes_precedence_over_ref(self, workflow_manager, simple_workflow_ir, tmp_path):
        """Test that workflow_name takes precedence over workflow_ref."""
        # Create a different workflow file
        from tests.shared.markdown_utils import write_workflow_file

        other_workflow = {"nodes": [{"id": "other", "type": "echo", "params": {"message": "other"}}], "edges": []}
        workflow_file = tmp_path / "other.pflow.md"
        write_workflow_file(other_workflow, workflow_file)

        node = WorkflowExecutor()
        node.set_params({
            "workflow_name": "test-workflow",
            "workflow_ref": str(workflow_file),  # Should be ignored
        })

        shared = {}
        with pytest.raises(ValueError, match="Only one of"):
            node.prep(shared)

    def test_workflow_name_with_all_three_params(self, workflow_manager, simple_workflow_ir):
        """Test error when all three workflow sources are provided."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_name": "test-workflow",
            "workflow_ref": "some-file.pflow.md",
            "workflow_ir": simple_workflow_ir,
        })

        shared = {}
        with pytest.raises(ValueError, match="Only one of"):
            node.prep(shared)

    def test_workflow_name_circular_dependency(self, workflow_manager):
        """Test circular dependency detection with workflow_name."""
        workflow_path = workflow_manager.get_path("test-workflow")

        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({"workflow_name": "test-workflow"})

            # Simulate being called from within the same workflow
            shared = {"_pflow_stack": [workflow_path]}

            with pytest.raises(ValueError, match="Circular workflow reference detected"):
                node.prep(shared)

    def test_workflow_name_with_param_mapping(self, workflow_manager):
        """Test workflow_name with parameter mapping."""
        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({
                "workflow_name": "test-workflow",
                "param_mapping": {
                    "input_value": "static_value",  # Test static value
                    "dynamic_value": "${parent_value}",  # Test template
                },
            })

            shared = {"parent_value": "test123"}
            prep_res = node.prep(shared)

            assert prep_res["child_params"]["input_value"] == "static_value"
            assert prep_res["child_params"]["dynamic_value"] == "test123"

    def test_workflow_name_logging(self, workflow_manager, caplog):
        """Test that proper debug logging occurs when loading by name."""
        import logging

        caplog.set_level(logging.DEBUG)

        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({"workflow_name": "test-workflow"})

            shared = {}
            prep_res = node.prep(shared)

            # Check debug log messages
            assert "Loading workflow by name: test-workflow" in caplog.text

        # Mock the exec phase to test execution logging
        with patch("pflow.runtime.compile_ir_to_flow") as mock_compile:
            mock_flow = Mock()
            mock_flow.run.return_value = "success"
            mock_compile.return_value = mock_flow

            node.exec(prep_res)

            assert "Executing sub-workflow from name:test-workflow" in caplog.text

    @patch("pflow.runtime.workflow_executor.WorkflowManager")
    def test_workflow_manager_error_handling(self, mock_manager_class):
        """Test proper error handling when WorkflowManager fails."""
        # Mock WorkflowManager to raise an exception
        mock_manager = Mock()
        mock_manager.load_ir.side_effect = WorkflowNotFoundError("Workflow 'test' not found")
        mock_manager_class.return_value = mock_manager

        node = WorkflowExecutor()
        node.set_params({"workflow_name": "test"})

        shared = {}
        with pytest.raises(ValueError, match=r"Failed to load workflow 'test'.*not found"):
            node.prep(shared)

    def test_workflow_name_integration(self, workflow_manager, simple_workflow_ir):
        """Test full integration with workflow_name through prep and exec phases."""
        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({
                "workflow_name": "test-workflow",
                "param_mapping": {"test_param": "value123"},
                "output_mapping": {"result": "parent_result"},
            })

            # Create a real Registry instance instead of a mock
            from pflow.registry import Registry

            registry = Registry()
            node.params["__registry__"] = registry

            shared = {}
            prep_res = node.prep(shared)

            # Verify prep results (markdown IR adds 'purpose' field from descriptions)
            loaded_ir = prep_res["workflow_ir"]
            assert loaded_ir["nodes"][0]["id"] == simple_workflow_ir["nodes"][0]["id"]
            assert loaded_ir["nodes"][0]["type"] == simple_workflow_ir["nodes"][0]["type"]
            assert prep_res["child_params"]["test_param"] == "value123"

            # Update prep_res to include parent_shared which is needed by exec
            prep_res["parent_shared"] = shared

            # Mock compilation for exec phase
            with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
                mock_flow = Mock()
                mock_flow.run.return_value = "success"
                mock_compile.return_value = mock_flow

                exec_res = node.exec(prep_res)

                # Debug output if test fails
                if not exec_res.get("success"):
                    print(f"exec_res error: {exec_res}")

                assert exec_res["success"] is True
                assert exec_res["result"] == "success"

                # Verify compile was called with correct parameters
                mock_compile.assert_called_once()
                call_args = mock_compile.call_args
                # Markdown IR includes 'purpose' from required descriptions
                compiled_ir = call_args[0][0]
                assert compiled_ir["nodes"][0]["id"] == simple_workflow_ir["nodes"][0]["id"]
                assert call_args[1]["initial_params"]["test_param"] == "value123"
