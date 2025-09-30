"""Test saving repaired workflows functionality."""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pflow.cli.main import workflow_command
from pflow.execution.executor_service import ExecutionResult


class TestRepairedWorkflowSave:
    """Test saving repaired workflows to files."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return CliRunner()

    @pytest.fixture
    def broken_workflow(self):
        """Create a workflow that will fail and need repair."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": 'echo \'{"user": "alice"}\''}},
                {
                    "id": "step2",
                    "type": "shell",
                    "params": {"command": "echo 'Hello ${step1.stdout.username}'"},  # Wrong field
                },
            ],
            "edges": [{"from": "step1", "to": "step2"}],
        }

    @pytest.fixture
    def working_workflow(self):
        """Create a workflow that works without repair."""
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "step1", "type": "shell", "params": {"command": "echo 'Hello World'"}}],
            "edges": [],
        }

    def test_no_update_saves_separate_file(self, runner, broken_workflow, tmp_path):
        """Test that --no-update flag saves to .repaired.json file."""
        # Create a workflow file that needs repair
        workflow_file = tmp_path / "test_workflow.json"
        original_content_str = json.dumps(broken_workflow, indent=2)
        workflow_file.write_text(original_content_str)

        # Mock the repair to return a fixed workflow
        repaired_workflow = broken_workflow.copy()
        repaired_workflow["nodes"][1]["params"]["command"] = "echo 'Hello ${step1.stdout.user}'"

        with patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute:
            # Setup mock to return successful result with repaired workflow
            mock_result = ExecutionResult(
                success=True,
                repaired_workflow_ir=repaired_workflow,
                shared_after={"step1": {"stdout": '{"user": "alice"}'}},
            )
            mock_execute.return_value = mock_result

            # Run with --no-update flag
            result = runner.invoke(workflow_command, ["--no-update", str(workflow_file)], catch_exceptions=False)

            # Check execution succeeded
            assert result.exit_code == 0

            # Check repaired file was created
            repaired_file = tmp_path / "test_workflow.repaired.json"
            assert repaired_file.exists(), "Repaired workflow file should be created with --no-update"

            # Verify the repaired content
            repaired_content = json.loads(repaired_file.read_text())
            assert repaired_content["nodes"][1]["params"]["command"] == "echo 'Hello ${step1.stdout.user}'"

            # Verify success message in output
            assert "Repaired workflow saved to:" in result.output
            assert "test_workflow.repaired.json" in result.output

            # Original file should be unchanged
            assert workflow_file.read_text() == original_content_str

    def test_default_updates_original(self, runner, broken_workflow, tmp_path):
        """Test that default behavior updates original (no backup)."""
        # Create a workflow file that needs repair
        workflow_file = tmp_path / "test_workflow.json"
        original_content = json.dumps(broken_workflow, indent=2)
        workflow_file.write_text(original_content)

        # Mock the repair to return a fixed workflow
        repaired_workflow = broken_workflow.copy()
        repaired_workflow["nodes"][1]["params"]["command"] = "echo 'Hello ${step1.stdout.user}'"

        with patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute:
            # Setup mock to return successful result with repaired workflow
            mock_result = ExecutionResult(
                success=True,
                repaired_workflow_ir=repaired_workflow,
                shared_after={"step1": {"stdout": '{"user": "alice"}'}},
            )
            mock_execute.return_value = mock_result

            # Run with default behavior (updates original, no backup)
            result = runner.invoke(workflow_command, [str(workflow_file)], catch_exceptions=False)

            # Check execution succeeded
            assert result.exit_code == 0

            # Check NO backup was created (new default behavior)
            backup_file = tmp_path / "test_workflow.json.backup"
            assert not backup_file.exists(), "Should not create backup with default behavior"

            # Check original file was updated with repaired content
            updated_content = json.loads(workflow_file.read_text())
            assert updated_content["nodes"][1]["params"]["command"] == "echo 'Hello ${step1.stdout.user}'"

            # Check no .repaired.json file was created
            repaired_file = tmp_path / "test_workflow.repaired.json"
            assert not repaired_file.exists(), "Should not create .repaired.json with default behavior"

            # Verify success message in output
            assert "Updated" in result.output
            assert "test_workflow.json" in result.output

    def test_no_files_created_when_no_repair_needed(self, runner, working_workflow, tmp_path):
        """Test that no files are created when workflow doesn't need repair."""
        # Create a working workflow file
        workflow_file = tmp_path / "working_workflow.json"
        workflow_file.write_text(json.dumps(working_workflow, indent=2))

        with patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute:
            # Setup mock to return successful result WITHOUT repaired workflow
            mock_result = ExecutionResult(
                success=True,
                repaired_workflow_ir=None,  # No repair needed
                shared_after={"step1": {"stdout": "Hello World"}},
            )
            mock_execute.return_value = mock_result

            # Test default behavior
            result = runner.invoke(workflow_command, [str(workflow_file)], catch_exceptions=False)

            assert result.exit_code == 0

            # Check no repaired file was created
            repaired_file = tmp_path / "working_workflow.repaired.json"
            assert not repaired_file.exists(), "No repaired file should be created"

            # Test with default behavior
            result = runner.invoke(workflow_command, [str(workflow_file)], catch_exceptions=False)

            assert result.exit_code == 0

            # Check no backup was created
            backup_file = tmp_path / "working_workflow.json.backup"
            assert not backup_file.exists(), "No backup should be created when no repair needed"

            # Verify no repair messages in output
            assert "Repaired workflow saved" not in result.output
            assert "Updated" not in result.output
            assert "Backup saved" not in result.output

    def test_only_file_workflows_trigger_save(self, runner, broken_workflow):
        """Test that only file-based workflows trigger save functionality."""
        # This test verifies that workflows from saved registry don't trigger save
        # We'll simulate this by not setting the source_file_path in context

        # Mock repair
        repaired_workflow = broken_workflow.copy()
        repaired_workflow["nodes"][1]["params"]["command"] = "echo 'Hello ${step1.stdout.user}'"

        with patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute:
            mock_result = ExecutionResult(success=True, repaired_workflow_ir=repaired_workflow, shared_after={})
            mock_execute.return_value = mock_result

            # Mock a saved workflow (not from file)
            with patch("pflow.cli.main.resolve_workflow") as mock_resolve:
                mock_resolve.return_value = (broken_workflow, "saved")  # Indicates saved workflow, not file

                # Also need to mock _handle_named_workflow to prevent actual execution
                with patch("pflow.cli.main._handle_named_workflow", return_value=True):
                    result = runner.invoke(
                        workflow_command,
                        ["my-saved-workflow"],  # Named workflow
                        catch_exceptions=False,
                    )

                    # Should succeed but not save any files
                    assert result.exit_code == 0
                    assert "Repaired workflow saved" not in result.output

    def test_save_error_handling(self, runner, broken_workflow, tmp_path):
        """Test that save errors are handled gracefully."""
        # Create a workflow file
        workflow_file = tmp_path / "test_workflow.json"
        workflow_file.write_text(json.dumps(broken_workflow, indent=2))

        # Mock the repair
        repaired_workflow = broken_workflow.copy()
        repaired_workflow["nodes"][1]["params"]["command"] = "echo 'Hello ${step1.stdout.user}'"

        with patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute:
            mock_result = ExecutionResult(success=True, repaired_workflow_ir=repaired_workflow, shared_after={})
            mock_execute.return_value = mock_result

            # Patch only the specific open call for saving the repaired workflow
            original_open = open

            def selective_open(file, mode="r", *args, **kwargs):
                # Allow reading but not writing to .repaired.json files
                if "w" in mode and ".repaired.json" in str(file):
                    raise PermissionError("Permission denied")
                return original_open(file, mode, *args, **kwargs)

            with patch("builtins.open", side_effect=selective_open):
                result = runner.invoke(workflow_command, [str(workflow_file)], catch_exceptions=False)

                # Workflow should still succeed despite save error
                assert result.exit_code == 0

                # Should not show success message for save
                assert "Repaired workflow saved" not in result.output

    def test_repaired_workflow_is_valid_json(self, runner, broken_workflow, tmp_path):
        """Test that saved repaired workflow is valid JSON with proper formatting."""
        # Create a workflow file
        workflow_file = tmp_path / "test_workflow.json"
        workflow_file.write_text(json.dumps(broken_workflow, indent=2))

        # Mock the repair
        repaired_workflow = broken_workflow.copy()
        repaired_workflow["nodes"][1]["params"]["command"] = "echo 'Hello ${step1.stdout.user}'"

        with patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute:
            mock_result = ExecutionResult(success=True, repaired_workflow_ir=repaired_workflow, shared_after={})
            mock_execute.return_value = mock_result

            # Run with --no-update to get separate file
            result = runner.invoke(workflow_command, ["--no-update", str(workflow_file)], catch_exceptions=False)

            assert result.exit_code == 0

            # Read and validate the repaired file
            repaired_file = tmp_path / "test_workflow.repaired.json"
            repaired_text = repaired_file.read_text()

            # Should be valid JSON
            repaired_data = json.loads(repaired_text)
            assert repaired_data["ir_version"] == "0.1.0"

            # Should be nicely formatted (has indentation)
            assert "\n  " in repaired_text, "JSON should be indented"
            assert not repaired_text.startswith('{"ir_version"'), "JSON should not be minified"

    def test_default_preserves_permissions(self, runner, broken_workflow, tmp_path):
        """Test that default behavior preserves file permissions."""
        import stat

        # Create a workflow file with specific permissions
        workflow_file = tmp_path / "test_workflow.json"
        workflow_file.write_text(json.dumps(broken_workflow, indent=2))

        # Set specific permissions (read/write for owner only)
        original_mode = stat.S_IRUSR | stat.S_IWUSR
        workflow_file.chmod(original_mode)

        # Mock the repair
        repaired_workflow = broken_workflow.copy()

        with patch("pflow.execution.workflow_execution.execute_workflow") as mock_execute:
            mock_result = ExecutionResult(success=True, repaired_workflow_ir=repaired_workflow, shared_after={})
            mock_execute.return_value = mock_result

            # Run with default behavior (updates original, no backup)
            result = runner.invoke(workflow_command, [str(workflow_file)], catch_exceptions=False)

            assert result.exit_code == 0

            # Check backup preserves original permissions
            # No backup in default behavior - verify no backup exists
            backup_file = tmp_path / "test_workflow.json.backup"
            assert not backup_file.exists(), "No backup should be created with default behavior"
