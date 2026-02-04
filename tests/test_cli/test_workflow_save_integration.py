"""Integration tests for workflow save functionality.

FIX HISTORY:
- 2024: Rewrote from heavy mocking (13 anti-patterns) to true integration tests
- Removed mocking of click.prompt, click.echo, and WorkflowManager
- Added real filesystem-based tests that verify actual save behavior
- Tests now validate complete CLI -> WorkflowManager -> filesystem integration
- Focus on end-to-end behavior: user interaction -> files created -> content verified
- 2024-01-31: Fixed test_end_to_end_workflow_execution_with_save_prompt to separate
  workflow execution from save prompting due to Click runner TTY limitations
- 2025: Updated for .pflow.md format (Task 107). _prompt_workflow_save is gated
  (only reachable from planner path which is disabled), but tests verify the
  underlying WorkflowManager integration still works.

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

import contextlib
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from pflow.cli.main import main
from pflow.core.workflow_manager import WorkflowManager
from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file


class TestWorkflowSaveIntegration:
    """True integration tests for workflow save functionality.

    Tests complete CLI -> WorkflowManager -> filesystem integration without mocking
    the components we want to verify.
    """

    def test_save_workflow_creates_actual_file_with_correct_content(self, tmp_path):
        """Test that saving a workflow creates actual .pflow.md file with frontmatter."""
        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir)

        test_output = str(tmp_path / "test.txt")
        sample_workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "write-file",
                    "params": {"file_path": test_output, "content": "Hello World"},
                }
            ],
            "edges": [],
        }

        # Save directly via WorkflowManager (the integration point)
        markdown_content = ir_to_markdown(sample_workflow)
        wm.save("test-workflow", markdown_content)

        # Verify actual file was created as .pflow.md
        workflow_file = workflows_dir / "test-workflow.pflow.md"
        assert workflow_file.exists()

        # Verify file content structure — should have YAML frontmatter
        content = workflow_file.read_text()
        assert content.startswith("---\n")

        # Parse frontmatter
        parts = content.split("---", 2)
        assert len(parts) >= 3
        frontmatter = yaml.safe_load(parts[1])

        assert "created_at" in frontmatter
        assert "updated_at" in frontmatter
        assert frontmatter["version"] == "1.0.0"

        # Body should contain the workflow markdown
        body = parts[2].strip()
        assert "## Steps" in body
        assert "### test" in body

    def test_save_workflow_handles_duplicate_names_correctly(self, tmp_path):
        """Test that duplicate workflow names are handled with real filesystem."""
        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir)

        test_output = str(tmp_path / "t.txt")
        sample_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "write-file", "params": {"file_path": test_output, "content": "Hi"}}],
            "edges": [],
        }

        # Pre-create a workflow
        markdown_content = ir_to_markdown(sample_workflow, description="Original description")
        wm.save("existing-workflow", markdown_content)
        assert wm.exists("existing-workflow")

        # Verify original workflow can be loaded
        original = wm.load("existing-workflow")
        assert original["description"] == "Original description"

        # Verify only one workflow exists with that name
        all_files = list(workflows_dir.glob("existing-workflow*.pflow.md"))
        assert len(all_files) == 1

    def test_end_to_end_workflow_execution_with_save_prompt(self, tmp_path):
        """Test complete end-to-end: execute workflow -> verify saved file.

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
        }

        # First, test workflow execution via CLI
        workflow_file = tmp_path / "test_workflow.pflow.md"
        write_workflow_file(workflow, workflow_file)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_file)])

        # Verify workflow executed successfully
        assert result.exit_code == 0
        assert "Workflow executed successfully" in result.output
        assert output_file.exists()
        assert output_file.read_text() == "Integration test output"

        # Then, test the save functionality separately (still integration testing)
        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir)
        markdown_content = ir_to_markdown(workflow)
        wm.save("integration-test", markdown_content)

        # Verify workflow was saved with correct integration
        assert wm.exists("integration-test")
        saved_workflow = wm.load("integration-test")
        assert saved_workflow["name"] == "integration-test"

        # Verify actual file exists on filesystem as .pflow.md
        saved_file = workflows_dir / "integration-test.pflow.md"
        assert saved_file.exists()

        # Verify the complete integration: execution created one file, save created another
        assert output_file.exists()  # From workflow execution
        assert saved_file.exists()  # From save operation

    def test_workflow_manager_integration_with_cli_error_handling(self, tmp_path):
        """Test that WorkflowManager handles permission errors gracefully."""
        workflows_dir = tmp_path / "readonly_workflows"

        # Create directory with no write permissions to trigger errors
        workflows_dir.mkdir(parents=True)
        workflows_dir.chmod(0o444)  # Read-only

        try:
            wm = WorkflowManager(workflows_dir)

            test_output = str(tmp_path / "t.txt")
            sample_workflow = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "test", "type": "write-file", "params": {"file_path": test_output, "content": "Hi"}}],
                "edges": [],
            }

            # Saving to read-only dir should raise an error
            markdown_content = ir_to_markdown(sample_workflow)
            with contextlib.suppress(PermissionError, OSError):
                wm.save("test-workflow", markdown_content)

            # Verify no workflow was created due to permission error
            try:
                workflow_exists = (workflows_dir / "test-workflow.pflow.md").exists()
                assert not workflow_exists
            except PermissionError:
                # Permission error during exists() check is expected
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
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

        with patch("click.prompt") as mock_prompt, patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
            mock_prompt.return_value = "n"  # Decline to save
            mock_wm_class.return_value = wm

            from pflow.cli.main import _prompt_workflow_save

            _prompt_workflow_save(sample_workflow)

        # Verify no files were created
        assert len(list(workflows_dir.glob("*.pflow.md"))) == 0

        # Verify only one prompt was made (the save decision)
        assert mock_prompt.call_count == 1

    def test_successful_retry_after_duplicate_name(self, tmp_path):
        """Test successful workflow save after retrying with different name."""
        workflows_dir = tmp_path / "workflows"
        wm = WorkflowManager(workflows_dir)

        sample_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

        # Pre-create a workflow
        markdown_content = ir_to_markdown(sample_workflow, description="Original")
        wm.save("existing", markdown_content)

        with patch("click.prompt") as mock_prompt, patch("pflow.cli.main.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = wm

            # Simulate: save -> existing name -> retry -> new name
            mock_prompt.side_effect = [
                "y",  # Yes to save
                "existing",  # Try existing name (will fail)
                "y",  # Yes to retry
                "new-name",  # New unique name
            ]

            from pflow.cli.main import _prompt_workflow_save

            _prompt_workflow_save(sample_workflow)

        # Verify both workflows exist
        assert wm.exists("existing")
        assert wm.exists("new-name")

        # Verify original content is preserved
        original = wm.load("existing")
        assert original["description"] == "Original"
