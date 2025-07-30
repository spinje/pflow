"""Integration tests for workflow save functionality."""

from unittest.mock import patch

import pytest

from pflow.cli.main import _prompt_workflow_save
from pflow.core.workflow_manager import WorkflowManager


class TestWorkflowSaveIntegration:
    """Test the workflow save functionality directly."""

    @pytest.fixture
    def sample_workflow(self):
        """Create a sample workflow IR."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"message": "Hello"},
                }
            ],
            "edges": [],
            "start_node": "test",
        }

    def test_prompt_workflow_save_decline(self, sample_workflow, tmp_path):
        """Test declining to save workflow."""
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "n"

            # Should return early without saving
            _prompt_workflow_save(sample_workflow)

            # Only one prompt for save decision
            assert mock_prompt.call_count == 1

    def test_prompt_workflow_save_success(self, sample_workflow, tmp_path):
        """Test successfully saving a workflow."""
        workflows_dir = tmp_path / "workflows"

        with (
            patch("click.prompt") as mock_prompt,
            patch("click.echo") as mock_echo,
            patch("pflow.cli.main.WorkflowManager") as mock_wm_class,
        ):
            # Mock user inputs
            mock_prompt.side_effect = ["y", "test-workflow", "Test description"]

            # Mock WorkflowManager
            wm_instance = WorkflowManager(workflows_dir)
            mock_wm_class.return_value = wm_instance

            # Call the function
            _prompt_workflow_save(sample_workflow)

            # Verify prompts
            assert mock_prompt.call_count == 3

            # Verify success message
            success_calls = [call for call in mock_echo.call_args_list if "✅ Workflow saved to:" in str(call)]
            assert len(success_calls) == 1

            # Verify workflow was saved
            assert wm_instance.exists("test-workflow")
            saved = wm_instance.load("test-workflow")
            assert saved["name"] == "test-workflow"
            assert saved["description"] == "Test description"
            assert saved["ir"] == sample_workflow

    def test_prompt_workflow_save_duplicate_retry(self, sample_workflow, tmp_path):
        """Test handling duplicate names with retry."""
        workflows_dir = tmp_path / "workflows"

        with (
            patch("click.prompt") as mock_prompt,
            patch("click.echo") as mock_echo,
            patch("pflow.cli.main.WorkflowManager") as mock_wm_class,
        ):
            # Mock WorkflowManager
            wm_instance = WorkflowManager(workflows_dir)
            mock_wm_class.return_value = wm_instance

            # Pre-save a workflow
            wm_instance.save("existing", sample_workflow, "Original")

            # Mock user inputs: try duplicate, then retry with new name
            mock_prompt.side_effect = [
                "y",  # Yes to save
                "existing",  # Duplicate name
                "Desc",  # Description (won't be used)
                "y",  # Yes to retry
                "new-name",  # New name
                "New desc",  # New description
            ]

            # Call the function
            _prompt_workflow_save(sample_workflow)

            # Verify error message shown
            error_calls = [
                call
                for call in mock_echo.call_args_list
                if "❌ Error: A workflow named 'existing' already exists." in str(call)
            ]
            assert len(error_calls) == 1

            # Verify retry prompt was called
            # We expect 5 prompts total (the 6th would be in the recursive call which creates new instance)
            assert mock_prompt.call_count >= 4  # At least the first 4 prompts

            # Verify the retry prompt was shown
            retry_prompts = [str(call) for call in mock_prompt.call_args_list]
            assert any("Try with a different name?" in prompt for prompt in retry_prompts)

    def test_prompt_workflow_save_invalid_name(self, sample_workflow, tmp_path):
        """Test handling invalid workflow names."""
        workflows_dir = tmp_path / "workflows"

        with (
            patch("click.prompt") as mock_prompt,
            patch("click.echo") as mock_echo,
            patch("pflow.cli.main.WorkflowManager") as mock_wm_class,
        ):
            # Mock user inputs
            mock_prompt.side_effect = ["y", "invalid/name", "Description"]

            # Mock WorkflowManager
            wm_instance = WorkflowManager(workflows_dir)
            mock_wm_class.return_value = wm_instance

            # Call the function
            _prompt_workflow_save(sample_workflow)

            # Verify error message
            error_calls = [call for call in mock_echo.call_args_list if "❌ Error: Invalid workflow name:" in str(call)]
            assert len(error_calls) == 1

            # Verify no workflow was saved
            assert not (workflows_dir / "invalid/name.json").exists()
