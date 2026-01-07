"""Integration tests for workflow save functionality.

FIX HISTORY:
- 2024: Rewrote from heavy mocking (13 anti-patterns) to true integration tests
- Removed mocking of click.prompt, click.echo, and WorkflowManager
- Added real filesystem-based tests that verify actual save behavior
- Tests now validate complete CLI -> WorkflowManager -> filesystem integration
- Focus on end-to-end behavior: user interaction -> files created -> content verified
- 2024-01-31: Fixed test_end_to_end_workflow_execution_with_save_prompt to separate
  workflow execution from save prompting due to Click runner TTY limitations

LESSONS LEARNED:
- Integration tests should test actual integration, not mocked interactions
- Use real temporary directories and files to verify behavior
- Test the complete user journey from CLI input to persistent storage
- Mock only external boundaries (user input), not system components
- Click's test runner cannot simulate interactive TTY behavior (sys.stdin.isatty()
  always returns False), so interactive features must be tested separately
- Separate complex integration tests into focused components while maintaining
  real integration between CLI execution, save functionality, and filesystem
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pflow.cli.main import _prompt_workflow_save, main
from pflow.core.workflow_manager import WorkflowManager


class TestWorkflowSaveIntegration:
    """True integration tests for workflow save functionality.

    Tests complete CLI -> WorkflowManager -> filesystem integration without mocking
    the components we want to verify.
    """

    @pytest.fixture
    def sample_workflow(self, tmp_path):
        """Create a sample workflow IR."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "write-file",
                    "params": {"file_path": str(tmp_path / "test_output.txt"), "content": "Hello World"},
                }
            ],
            "edges": [],
            "start_node": "test",
        }

    def test_save_workflow_creates_actual_file_with_correct_content(self, sample_workflow):
        """Test that saving a workflow creates actual file with correct structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workflows_dir = Path(temp_dir) / "workflows"
            wm = WorkflowManager(workflows_dir)

            # Mock only user input, not the WorkflowManager
            with patch("click.prompt") as mock_prompt:
                # Only two prompts now: save (y/n) and workflow name
                # Description is no longer prompted for
                mock_prompt.side_effect = ["y", "test-workflow"]

                # Use real WorkflowManager with temporary directory
                with patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
                    mock_wm_class.return_value = wm

                    _prompt_workflow_save(sample_workflow)

            # Verify actual file was created
            workflow_file = workflows_dir / "test-workflow.json"
            assert workflow_file.exists()

            # Verify file content structure
            with open(workflow_file) as f:
                saved_data = json.load(f)

            # Note: name is NOT stored in file - it's derived from filename at load time
            assert "name" not in saved_data  # Name derived from filename, not stored
            # Description should be empty when no metadata is provided
            assert saved_data["description"] == ""
            assert saved_data["ir"] == sample_workflow
            assert "created_at" in saved_data
            assert "updated_at" in saved_data
            assert saved_data["version"] == "1.0.0"

    def test_save_workflow_handles_duplicate_names_correctly(self, sample_workflow):
        """Test that duplicate workflow names are handled with real filesystem."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workflows_dir = Path(temp_dir) / "workflows"
            wm = WorkflowManager(workflows_dir)

            # Pre-create a workflow
            wm.save("existing-workflow", sample_workflow, "Original description")
            assert wm.exists("existing-workflow")

            # Try to save with same name - should fail appropriately
            with patch("click.prompt") as mock_prompt:
                # First attempt with duplicate name, then decline retry
                mock_prompt.side_effect = ["y", "existing-workflow", "New description", "n"]

                with patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
                    mock_wm_class.return_value = wm

                    _prompt_workflow_save(sample_workflow)

            # Verify original workflow unchanged
            original = wm.load("existing-workflow")
            assert original["description"] == "Original description"

            # Verify only one workflow exists with that name
            all_files = list(workflows_dir.glob("existing-workflow*.json"))
            assert len(all_files) == 1

    def test_save_workflow_validates_names_with_real_filesystem(self, sample_workflow):
        """Test that invalid workflow names are rejected with real filesystem errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workflows_dir = Path(temp_dir) / "workflows"
            wm = WorkflowManager(workflows_dir)

            with patch("click.prompt") as mock_prompt:
                # Only two prompts now: save (y/n) and workflow name
                mock_prompt.side_effect = ["y", "invalid/name"]

                with patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
                    mock_wm_class.return_value = wm

                    _prompt_workflow_save(sample_workflow)

            # Verify no invalid files were created
            assert not (workflows_dir / "invalid/name.json").exists()
            assert not (workflows_dir / "invalid").exists()

            # Verify workflows directory still exists and is clean
            assert workflows_dir.exists()
            assert len(list(workflows_dir.glob("*.json"))) == 0

    def test_end_to_end_workflow_execution_with_save_prompt(self, tmp_path):
        """Test complete end-to-end: execute workflow -> prompt save -> verify saved file.

        Note: This test separates workflow execution from save prompting because
        Click's test runner cannot properly simulate interactive TTY behavior.
        This still provides integration testing by using real workflow execution
        and real filesystem operations.
        """
        # Create a workflow that actually executes
        output_file = tmp_path / "test_output.txt"
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {"file_path": str(output_file), "content": "Integration test output"},
                }
            ],
            "edges": [],
            "start_node": "writer",
        }

        workflows_dir = tmp_path / "workflows"

        # First, test workflow execution via CLI
        # With Task 22 changes, we need to provide the workflow as a file
        workflow_file = tmp_path / "test_workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_file)])

        # Verify workflow executed successfully
        assert result.exit_code == 0
        assert "Workflow executed successfully" in result.output
        assert output_file.exists()
        assert output_file.read_text() == "Integration test output"

        # Then, test the save functionality separately (still integration testing)
        # This tests the same save flow that would be triggered in interactive mode
        with patch("click.prompt") as mock_prompt, patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
            # Setup WorkflowManager with temp directory
            wm = WorkflowManager(workflows_dir)
            mock_wm_class.return_value = wm

            # Mock save prompts: yes to save, name (no description prompt anymore)
            mock_prompt.side_effect = ["y", "integration-test"]

            # Call the save function directly (same as CLI would call)
            _prompt_workflow_save(workflow)

        # Verify workflow was saved with correct integration
        assert wm.exists("integration-test")
        saved_workflow = wm.load("integration-test")
        assert saved_workflow["name"] == "integration-test"
        # Description should be empty when no metadata is provided
        assert saved_workflow["description"] == ""
        assert saved_workflow["ir"] == workflow

        # Verify actual file exists on filesystem
        workflow_file = workflows_dir / "integration-test.json"
        assert workflow_file.exists()

        # Verify the complete integration: execution created one file, save created another
        assert output_file.exists()  # From workflow execution
        assert workflow_file.exists()  # From save operation

    def test_workflow_manager_integration_with_cli_error_handling(self, sample_workflow):
        """Test that CLI properly handles WorkflowManager errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workflows_dir = Path(temp_dir) / "workflows"

            # Create directory with no write permissions to trigger errors
            workflows_dir.mkdir(parents=True)
            workflows_dir.chmod(0o444)  # Read-only

            try:
                wm = WorkflowManager(workflows_dir)

                with patch("click.prompt") as mock_prompt:
                    # Only two prompts now: save (y/n) and workflow name
                    mock_prompt.side_effect = ["y", "test-workflow"]

                    with patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
                        mock_wm_class.return_value = wm

                        # This should handle the error gracefully
                        _prompt_workflow_save(sample_workflow)

                # Verify no workflow was created due to permission error
                # Note: Use try/except to handle permission error when checking file existence
                try:
                    workflow_exists = (workflows_dir / "test-workflow.json").exists()
                    assert not workflow_exists
                except PermissionError:
                    # Permission error during exists() check is expected - means file wasn't created
                    pass

            finally:
                # Restore permissions for cleanup
                workflows_dir.chmod(0o755)


class TestWorkflowSaveUIBehavior:
    """Test user interface behavior for workflow saving without mocking core components."""

    def test_decline_save_exits_cleanly(self, tmp_path):
        """Test that declining to save a workflow exits cleanly without side effects."""
        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir)

        sample_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "test-node", "params": {}}],
            "edges": [],
            "start_node": "test",
        }

        with patch("click.prompt") as mock_prompt, patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
            mock_prompt.return_value = "n"  # Decline to save
            mock_wm_class.return_value = wm

            _prompt_workflow_save(sample_workflow)

        # Verify no files were created
        assert len(list(workflows_dir.glob("*.json"))) == 0

        # Verify only one prompt was made (the save decision)
        assert mock_prompt.call_count == 1

    def test_successful_retry_after_duplicate_name(self, tmp_path):
        """Test successful workflow save after retrying with different name."""
        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir)

        sample_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "test-node", "params": {}}],
            "edges": [],
            "start_node": "test",
        }

        # Pre-create a workflow
        wm.save("existing", sample_workflow, "Original")

        with patch("click.prompt") as mock_prompt, patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = wm

            # Simulate: save -> existing name -> retry -> new name
            # No description prompts anymore
            mock_prompt.side_effect = [
                "y",  # Yes to save
                "existing",  # Try existing name (will fail)
                "y",  # Yes to retry
                "new-name",  # New unique name
            ]

            _prompt_workflow_save(sample_workflow)

        # Verify both workflows exist
        assert wm.exists("existing")
        assert wm.exists("new-name")

        # Verify content is correct
        original = wm.load("existing")
        new_workflow = wm.load("new-name")

        assert original["description"] == "Original"
        # New workflow has empty description when no metadata provided
        assert new_workflow["description"] == ""
        assert new_workflow["ir"] == sample_workflow
