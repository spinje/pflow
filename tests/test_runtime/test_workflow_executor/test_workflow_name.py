"""Tests for WorkflowExecutor's saved workflow name loading via the 'workflow' parameter.

The unified 'workflow' parameter accepts both file paths and saved workflow names.
When the value does NOT contain '/' or '\\', does NOT start with '.', and does NOT
end with '.pflow.md', it is treated as a saved workflow name and loaded via
WorkflowManager.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.runtime.workflow_executor import WorkflowExecutor
from tests.shared.markdown_utils import ir_to_markdown


class TestWorkflowSavedName:
    """Test WorkflowExecutor's ability to load workflows by saved name."""

    @pytest.fixture
    def simple_workflow_ir(self):
        """Basic workflow IR for testing."""
        return {
            "nodes": [{"id": "test_node", "type": "echo", "params": {"message": "test"}}],
            "edges": [],
        }

    @pytest.fixture
    def workflow_manager(self, tmp_path, simple_workflow_ir):
        """Create WorkflowManager with a test workflow saved to disk."""
        from pflow.core.workflow.manager import WorkflowManager

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
        """When workflow param is a plain name (no path chars), load via WorkflowManager."""
        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({"workflow": "test-workflow"})

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
        """When saved workflow name does not exist, raise ValueError with descriptive message."""
        node = WorkflowExecutor()
        node.set_params({"workflow": "non-existent-workflow"})

        shared = {}
        with pytest.raises(ValueError, match="Failed to load workflow 'non-existent-workflow'"):
            node.prep(shared)

    def test_workflow_and_workflow_ir_raises_error(self, simple_workflow_ir):
        """When both 'workflow' and 'workflow_ir' are provided, raise ValueError."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow": "test-workflow",
            "workflow_ir": simple_workflow_ir,
        })

        shared = {}
        with pytest.raises(ValueError, match="Only one of"):
            node.prep(shared)

    def test_workflow_name_circular_dependency(self, workflow_manager):
        """When saved workflow is already on the execution stack, detect circular reference."""
        workflow_path = workflow_manager.get_path("test-workflow")

        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({"workflow": "test-workflow"})

            # Simulate being called from within the same workflow
            shared = {"_pflow_stack": [workflow_path]}

            with pytest.raises(ValueError, match="Circular workflow reference detected"):
                node.prep(shared)

    def test_workflow_name_with_direct_params(self, workflow_manager):
        """Non-reserved params are passed directly as child inputs (no param_mapping)."""
        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({
                "workflow": "test-workflow",
                "input_value": "static_value",
                "dynamic_value": "${parent_value}",
            })

            shared = {"parent_value": "test123"}
            prep_res = node.prep(shared)

            assert prep_res["child_params"]["input_value"] == "static_value"
            assert prep_res["child_params"]["dynamic_value"] == "test123"

    def test_workflow_name_logging(self, workflow_manager, caplog):
        """Verify debug logging when loading a workflow by saved name."""
        import logging

        caplog.set_level(logging.DEBUG, logger="pflow.runtime.workflow_executor")

        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({"workflow": "test-workflow"})

            shared = {}
            prep_res = node.prep(shared)

            assert "Loading workflow by name: test-workflow" in caplog.text

        # Verify execution logging too
        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_flow = Mock()
            mock_flow.run.return_value = "success"
            mock_compile.return_value = mock_flow

            node.exec(prep_res)

            assert "Executing sub-workflow from name:test-workflow" in caplog.text

    @patch("pflow.runtime.workflow_executor.WorkflowManager")
    def test_workflow_manager_error_handling(self, mock_manager_class):
        """When WorkflowManager raises, wrap in ValueError with workflow name context."""
        mock_manager = Mock()
        mock_manager.load_ir.side_effect = WorkflowNotFoundError("Workflow 'test' not found")
        mock_manager_class.return_value = mock_manager

        node = WorkflowExecutor()
        node.set_params({"workflow": "test"})

        shared = {}
        with pytest.raises(ValueError, match=r"Failed to load workflow 'test'.*not found"):
            node.prep(shared)

    def test_workflow_name_integration(self, workflow_manager, simple_workflow_ir):
        """Full prep-exec cycle: saved name loading with direct params, no output_mapping."""
        with patch("pflow.runtime.workflow_executor.WorkflowManager") as mock_manager_class:
            mock_manager_class.return_value = workflow_manager

            node = WorkflowExecutor()
            node.set_params({
                "workflow": "test-workflow",
                "test_param": "value123",
            })

            # Inject a real Registry for the exec phase
            from pflow.registry import Registry

            registry = Registry()
            node.params["__registry__"] = registry

            shared = {}
            prep_res = node.prep(shared)

            # Verify prep results
            loaded_ir = prep_res["workflow_ir"]
            assert loaded_ir["nodes"][0]["id"] == simple_workflow_ir["nodes"][0]["id"]
            assert loaded_ir["nodes"][0]["type"] == simple_workflow_ir["nodes"][0]["type"]
            assert prep_res["child_params"]["test_param"] == "value123"

            # Mock compilation for exec phase
            with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
                mock_flow = Mock()
                mock_flow.run.return_value = "success"
                mock_compile.return_value = mock_flow

                exec_res = node.exec(prep_res)

                assert exec_res["success"] is True
                assert exec_res["result"] == "success"

                # Verify compile was called with correct parameters
                mock_compile.assert_called_once()
                call_args = mock_compile.call_args
                compiled_ir = call_args[0][0]
                assert compiled_ir["nodes"][0]["id"] == simple_workflow_ir["nodes"][0]["id"]
                assert call_args[1]["initial_params"]["test_param"] == "value123"
