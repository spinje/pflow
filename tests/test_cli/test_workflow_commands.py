"""Tests for flattened workflow management commands."""

import json
import sys
from io import StringIO
from typing import Any
from unittest.mock import patch


def invoke_cli(args: list[str]) -> Any:
    """Helper to invoke the CLI through the real entrypoint."""
    from pflow.cli.main import cli_main

    # Save original sys.argv and streams
    original_argv = sys.argv[:]
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # Capture output
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    try:
        # Set up sys.argv as if running from command line
        sys.argv = ["pflow", *args]
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        # Run the CLI
        exit_code = 0
        try:
            cli_main()
        except SystemExit as e:
            exit_code = int(e.code) if e.code is not None else 0

        # Create a result object similar to Click's Result
        class Result:
            def __init__(self, exit_code: int, output: str, stderr: str) -> None:
                self.exit_code = exit_code
                self.output = output
                self.stderr = stderr

        return Result(exit_code, stdout_capture.getvalue(), stderr_capture.getvalue())

    finally:
        # Restore original state
        sys.argv = original_argv
        sys.stdout = original_stdout
        sys.stderr = original_stderr


class TestWorkflowListCommand:
    """Tests for the `pflow list` command."""

    def test_list_workflows_with_multiple_workflows(self) -> None:
        """Test listing workflows when multiple workflows exist."""
        # Create mock workflows
        mock_workflows = [
            {
                "name": "backup-photos",
                "description": "Backup photos to cloud storage",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "daily-report",
                "description": "Generate daily activity report",
                "created_at": "2024-01-02T00:00:00Z",
            },
            {
                "name": "process-csv",
                "description": "Transform CSV data to JSON",
                "created_at": "2024-01-03T00:00:00Z",
            },
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["list"])

            assert result.exit_code == 0
            assert "Saved Workflows:" in result.output
            assert "─" * 40 in result.output

            # Check each workflow is displayed
            assert "backup-photos" in result.output
            assert "Backup photos to cloud storage" in result.output

            assert "daily-report" in result.output
            assert "Generate daily activity report" in result.output

            assert "process-csv" in result.output
            assert "Transform CSV data to JSON" in result.output

            # Check total count
            assert "Total: 3 workflows" in result.output

    def test_list_workflows_empty_state(self) -> None:
        """Test listing workflows when no workflows are saved."""
        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = []

            result = invoke_cli(["list"])

            assert result.exit_code == 0
            assert "No workflows saved yet." in result.output
            assert "To save a workflow:" in result.output
            assert "1. Create a .pflow.md workflow file" in result.output
            assert "pflow save" in result.output

    def test_list_workflows_with_single_keyword_filter(self) -> None:
        """Test filtering workflows with single keyword."""
        mock_workflows = [
            {
                "name": "slack-qa-analyzer",
                "description": "Analyzes QA results and posts to Slack",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "github-pr-analyzer",
                "description": "Analyzes GitHub pull requests",
                "created_at": "2024-01-02T00:00:00Z",
            },
            {
                "name": "slack-notification",
                "description": "Sends notifications to Slack channels",
                "created_at": "2024-01-03T00:00:00Z",
            },
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["list", "slack"])

            assert result.exit_code == 0
            # Should match both slack workflows
            assert "slack-qa-analyzer" in result.output
            assert "slack-notification" in result.output
            # Should NOT match github workflow
            assert "github-pr-analyzer" not in result.output
            assert "Total: 2 workflows" in result.output

    def test_list_workflows_with_multiple_keywords_and_logic(self) -> None:
        """Test filtering workflows with multiple keywords (AND logic)."""
        mock_workflows = [
            {
                "name": "slack-qa-analyzer",
                "description": "Analyzes QA results and posts to Slack",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "slack-notification",
                "description": "Sends notifications to Slack channels",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["list", "slack", "qa"])

            assert result.exit_code == 0
            # Should match slack-qa-analyzer (has both "slack" and "qa")
            assert "slack-qa-analyzer" in result.output
            # Should NOT match slack-notification (has "slack" but not "qa")
            assert "slack-notification" not in result.output
            assert "Total: 1 workflow" in result.output

    def test_list_workflows_filter_no_match_shows_helpful_message(self) -> None:
        """Test that filter with no matches shows helpful message."""
        mock_workflows = [
            {
                "name": "slack-qa-analyzer",
                "description": "Analyzes QA results",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "github-pr-analyzer",
                "description": "Analyzes pull requests",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["list", "slack", "github"])

            assert result.exit_code == 0
            # Filter no-match messages go to stderr
            combined = result.output + result.stderr
            assert "No workflows match filter: 'slack github'" in combined
            assert "Found 2 total workflows" in combined
            assert "Try:" in combined
            assert "Broader keywords" in combined
            # Should NOT show the default "No workflows saved yet" message
            assert "No workflows saved yet" not in combined

    def test_list_workflows_json_format(self) -> None:
        """Test listing workflows with --json flag excludes ir field."""
        mock_workflows = [
            {
                "name": "test-workflow",
                "description": "Test workflow for JSON output",
                "created_at": "2024-01-01T00:00:00Z",
                "ir": {
                    "ir_version": "0.1.0",
                    "nodes": [{"id": "node1", "type": "test-node"}],
                    "edges": [],
                },
            }
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["list", "--json"])

            assert result.exit_code == 0

            # Parse JSON output
            output_data = json.loads(result.output)
            assert isinstance(output_data, list)
            assert len(output_data) == 1
            assert output_data[0]["name"] == "test-workflow"
            assert output_data[0]["description"] == "Test workflow for JSON output"
            # Verify 'ir' field is excluded from JSON output
            assert "ir" not in output_data[0]

    def test_list_workflows_with_missing_description(self) -> None:
        """Test listing workflows when some lack descriptions."""
        mock_workflows = [
            {
                "name": "no-desc-workflow",
                # No description field
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "with-desc-workflow",
                "description": "Has a description",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["list"])

            assert result.exit_code == 0
            assert "no-desc-workflow" in result.output
            assert "No description" in result.output  # Default text for missing description
            assert "with-desc-workflow" in result.output
            assert "Has a description" in result.output

    def test_list_workflows_filter_case_insensitive(self) -> None:
        """Test that filtering is case-insensitive."""
        mock_workflows = [
            {
                "name": "GitHub-Analyzer",
                "description": "Analyzes repos",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "slack-bot",
                "description": "Contains GITHUB token handling",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            # Try lowercase filter
            result = invoke_cli(["list", "github"])

            assert result.exit_code == 0
            # Both should match despite different cases
            assert "GitHub-Analyzer" in result.output
            assert "slack-bot" in result.output
            assert "Total: 2 workflows" in result.output

    def test_list_workflows_smart_case(self) -> None:
        """Uppercase keywords should trigger case-sensitive matching."""
        mock_workflows = [
            {
                "name": "HTTP-analyzer",
                "description": "Processes HTTP responses",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "http-helper",
                "description": "Lowercase helper",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            lowercase = invoke_cli(["list", "http"])
            assert lowercase.exit_code == 0
            assert "HTTP-analyzer" in lowercase.output
            assert "http-helper" in lowercase.output

            uppercase = invoke_cli(["list", "HTTP"])
            assert uppercase.exit_code == 0
            assert "HTTP-analyzer" in uppercase.output
            assert "http-helper" not in uppercase.output

    def test_list_workflows_filter_no_matches(self) -> None:
        """Test filtering with no matching workflows."""
        mock_workflows = [
            {
                "name": "backup-photos",
                "description": "Backs up photos",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "daily-report",
                "description": "Generates reports",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]

        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["list", "github"])

            assert result.exit_code == 0
            # Filter no-match messages go to stderr
            combined = result.output + result.stderr
            assert "No workflows match filter: 'github'" in combined
            assert "Found 2 total workflows" in combined
            # Original workflows should not appear in stdout
            assert "backup-photos" not in result.output
            assert "daily-report" not in result.output


class TestWorkflowDescribeCommand:
    """Tests for the `pflow describe` command."""

    def test_describe_existing_workflow_with_inputs_outputs(self) -> None:
        """Test describing a workflow with inputs and outputs."""
        mock_metadata = {
            "name": "data-processor",
            "description": "Process data files with transformations",
            "ir": {
                "inputs": {
                    "input_file": {
                        "required": True,
                        "description": "Path to input data file",
                    },
                    "format": {
                        "required": False,
                        "description": "Output format (json/csv)",
                        "default": "json",
                    },
                },
                "outputs": {
                    "result_file": {"description": "Path to processed output file"},
                    "summary": {"description": "Processing summary statistics"},
                },
                "nodes": [],  # Not displayed in describe
            },
        }

        with patch("pflow.cli.commands.describe.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["describe", "data-processor"])

            assert result.exit_code == 0

            # Check workflow info
            assert "Workflow: data-processor" in result.output
            assert "Description: Process data files with transformations" in result.output

            # Check inputs section
            assert "Inputs:" in result.output
            assert "- input_file (required): Path to input data file" in result.output
            assert "- format (optional): Output format (json/csv)" in result.output
            assert "Default: json" in result.output

            # Check outputs section
            assert "Outputs:" in result.output
            assert "- result_file: Path to processed output file" in result.output
            assert "- summary: Processing summary statistics" in result.output

            # Check example usage
            assert "Example Usage:" in result.output
            assert "pflow data-processor input_file=<value>" in result.output

    def test_describe_workflow_no_inputs_outputs(self) -> None:
        """Test describing a workflow with no inputs or outputs."""
        mock_metadata = {
            "name": "simple-task",
            "description": "A simple task with no parameters",
            "ir": {
                "nodes": [],
                # No inputs or outputs
            },
        }

        with patch("pflow.cli.commands.describe.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["describe", "simple-task"])

            assert result.exit_code == 0
            assert "Workflow: simple-task" in result.output
            assert "Inputs: None" in result.output
            assert "Outputs: None" in result.output
            assert "Example Usage:" in result.output
            assert "pflow simple-task" in result.output

    def test_describe_workflow_only_optional_inputs(self) -> None:
        """Test describing a workflow with only optional inputs."""
        mock_metadata = {
            "name": "flexible-task",
            "description": "Task with optional parameters",
            "ir": {
                "inputs": {
                    "verbose": {
                        "required": False,
                        "description": "Enable verbose output",
                        "default": False,
                    },
                    "timeout": {
                        "required": False,
                        "description": "Operation timeout in seconds",
                        "default": 30,
                    },
                },
                "nodes": [],
            },
        }

        with patch("pflow.cli.commands.describe.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["describe", "flexible-task"])

            assert result.exit_code == 0
            assert "- verbose (optional): Enable verbose output" in result.output
            assert "Default: False" in result.output
            assert "- timeout (optional): Operation timeout in seconds" in result.output
            assert "Default: 30" in result.output

            # Example should not include optional parameters
            assert "Example Usage:" in result.output
            assert "pflow flexible-task" in result.output
            assert "verbose=" not in result.output

    def test_describe_nonexistent_workflow_with_suggestions(self) -> None:
        """Test describing a workflow that doesn't exist with similar suggestions."""
        with patch("pflow.cli.commands.describe.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_names.return_value = [
                "process-data",
                "process-images",
                "process-text",
                "backup-files",
            ]

            result = invoke_cli(["describe", "process"])

            assert result.exit_code == 1
            assert "Error: Workflow 'process' not found." in result.stderr
            assert "Did you mean: process-data, process-images, process-text" in result.stderr
            assert "backup-files" not in result.stderr

    def test_describe_nonexistent_workflow_no_suggestions(self) -> None:
        """Test describing a workflow that doesn't exist with no similar names."""
        with patch("pflow.cli.commands.describe.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_names.return_value = ["backup-photos", "daily-report"]

            result = invoke_cli(["describe", "xyz-task"])

            assert result.exit_code == 1
            assert "Error: Workflow 'xyz-task' not found." in result.stderr
            assert "Did you mean:" not in result.stderr

    def test_describe_workflow_case_insensitive_suggestions(self) -> None:
        """Test that suggestions are case-insensitive."""
        with patch("pflow.cli.commands.describe.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_names.return_value = [
                "Backup-Photos",
                "backup-videos",
                "BACKUP-DOCS",
            ]

            result = invoke_cli(["describe", "backup"])

            assert result.exit_code == 1
            assert "Did you mean: Backup-Photos, backup-videos, BACKUP-DOCS" in result.stderr

    def test_describe_workflow_mixed_required_optional_inputs(self) -> None:
        """Test describing a workflow with both required and optional inputs."""
        mock_metadata = {
            "name": "complex-task",
            "description": "Task with mixed input requirements",
            "ir": {
                "inputs": {
                    "source": {
                        "required": True,
                        "description": "Source file path",
                    },
                    "target": {
                        "required": True,
                        "description": "Target directory",
                    },
                    "compression": {
                        "required": False,
                        "description": "Compression level (1-9)",
                        "default": 5,
                    },
                },
                "outputs": {"status": {"description": "Operation status"}},
                "nodes": [],
            },
        }

        with patch("pflow.cli.commands.describe.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["describe", "complex-task"])

            assert result.exit_code == 0

            # Check inputs are properly categorized
            assert "- source (required): Source file path" in result.output
            assert "- target (required): Target directory" in result.output
            assert "- compression (optional): Compression level (1-9)" in result.output
            assert "Default: 5" in result.output

            # Example should only include required parameters
            assert "Example Usage:" in result.output
            assert "pflow complex-task source=<value> target=<value>" in result.output
            assert "compression=" not in result.output


class TestWorkflowCommandIntegration:
    """Integration tests for workflow commands."""

    def test_list_then_describe_workflow_flow(self) -> None:
        """Test a typical user flow: list workflows then describe one."""
        mock_workflows = [
            {
                "name": "analyze-logs",
                "description": "Analyze system logs for errors",
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        mock_metadata = {
            "name": "analyze-logs",
            "description": "Analyze system logs for errors",
            "ir": {
                "inputs": {
                    "log_path": {
                        "required": True,
                        "description": "Path to log file",
                    }
                },
                "outputs": {"report": {"description": "Analysis report"}},
                "nodes": [],
            },
        }

        with patch("pflow.cli.commands.list.WorkflowManager") as ListWM:
            mock_list_wm = ListWM.return_value
            mock_list_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["list"])

            assert result.exit_code == 0
            assert "analyze-logs" in result.output

        with patch("pflow.cli.commands.describe.WorkflowManager") as DescribeWM:
            mock_describe_wm = DescribeWM.return_value
            mock_describe_wm.exists.return_value = True
            mock_describe_wm.load.return_value = mock_metadata

            result = invoke_cli(["describe", "analyze-logs"])

            assert result.exit_code == 0
            assert "Workflow: analyze-logs" in result.output
            assert "- log_path (required): Path to log file" in result.output
            assert "- report: Analysis report" in result.output

    def test_empty_list_to_save_workflow_guidance(self) -> None:
        """Test that empty list guides users to save workflows."""
        with patch("pflow.cli.commands.list.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = []

            result = invoke_cli(["list"])

            assert result.exit_code == 0
            assert "No workflows saved yet" in result.output
            assert "Create a .pflow.md workflow file" in result.output

            # This guides them to create and save a workflow
            # (The actual workflow creation is tested elsewhere)


class TestWorkflowHistoryCommand:
    """Tests for the `pflow history` command."""

    def test_history_shows_execution_data_and_inputs(self) -> None:
        """Test history command returns execution data agents need to suggest inputs."""
        mock_metadata = {
            "name": "release-announcements",
            "description": "Generate release announcements",
            "execution_count": 5,
            "last_execution_timestamp": "2026-02-05T02:22:06.123456",
            "last_execution_success": True,
            "last_execution_params": {
                "slack_channel": "C09ABC123",
                "version": "1.2.0",
            },
            "ir": {},
        }

        with patch("pflow.cli.commands.history.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["history", "release-announcements"])

            assert result.exit_code == 0
            # Agent needs: name, run count, last timestamp, status, last inputs
            assert "release-announcements" in result.output
            assert "Runs: 5" in result.output
            assert "2026-02-05" in result.output
            assert "Success" in result.output
            assert "slack_channel: C09ABC123" in result.output

    def test_history_no_execution_returns_clear_message(self) -> None:
        """Test returns actionable message when workflow never executed."""
        mock_metadata = {"execution_count": 0, "ir": {}}

        with patch("pflow.cli.commands.history.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["history", "new-workflow"])

            assert result.exit_code == 0
            assert "No execution history" in result.output

    def test_history_workflow_not_found_errors(self) -> None:
        """Test errors clearly when workflow doesn't exist."""
        with patch("pflow.cli.commands.history.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_names.return_value = []

            result = invoke_cli(["history", "nonexistent"])

            assert result.exit_code == 1
            assert "not found" in result.stderr
