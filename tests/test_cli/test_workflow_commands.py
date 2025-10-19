"""Tests for pflow workflow discovery commands."""

import json
import sys
from io import StringIO
from typing import Any
from unittest.mock import patch


def invoke_cli(args: list[str]) -> Any:
    """Helper to invoke CLI with proper routing through main_wrapper.

    Since main_wrapper manipulates sys.argv directly, we need to simulate that behavior.
    """
    from pflow.cli.main_wrapper import cli_main

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
    """Tests for the 'pflow workflow list' command."""

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["workflow", "list"])

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
        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = []

            result = invoke_cli(["workflow", "list"])

            assert result.exit_code == 0
            assert "No workflows saved yet." in result.output
            assert "To save a workflow:" in result.output
            assert '1. Create one: pflow "your task"' in result.output
            assert "2. Choose to save when prompted" in result.output

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["workflow", "list", "slack"])

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["workflow", "list", "slack qa"])

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["workflow", "list", "slack github"])

            assert result.exit_code == 0
            # Should show custom message
            assert "No workflows match filter: 'slack github'" in result.output
            assert "Found 2 total workflows" in result.output
            assert "Try:" in result.output
            assert "Broader keywords" in result.output
            # Should NOT show the default "No workflows saved yet" message
            assert "No workflows saved yet" not in result.output

    def test_list_workflows_json_format(self) -> None:
        """Test listing workflows with --json flag."""
        mock_workflows = [
            {
                "name": "test-workflow",
                "description": "Test workflow for JSON output",
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["workflow", "list", "--json"])

            assert result.exit_code == 0

            # Parse JSON output
            output_data = json.loads(result.output)
            assert isinstance(output_data, list)
            assert len(output_data) == 1
            assert output_data[0]["name"] == "test-workflow"
            assert output_data[0]["description"] == "Test workflow for JSON output"

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["workflow", "list"])

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            # Try lowercase filter
            result = invoke_cli(["workflow", "list", "github"])

            assert result.exit_code == 0
            # Both should match despite different cases
            assert "GitHub-Analyzer" in result.output
            assert "slack-bot" in result.output
            assert "Total: 2 workflows" in result.output

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["workflow", "list", "github"])

            assert result.exit_code == 0
            # Should show custom message with context (workflows exist but don't match)
            assert "No workflows match filter: 'github'" in result.output
            assert "Found 2 total workflows" in result.output
            # Original workflows should not appear
            assert "backup-photos" not in result.output
            assert "daily-report" not in result.output


class TestWorkflowDescribeCommand:
    """Tests for the 'pflow workflow describe' command."""

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["workflow", "describe", "data-processor"])

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["workflow", "describe", "simple-task"])

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["workflow", "describe", "flexible-task"])

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
        all_workflows = [
            {"name": "process-data"},
            {"name": "process-images"},
            {"name": "process-text"},
            {"name": "backup-files"},
        ]

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_all.return_value = all_workflows

            result = invoke_cli(["workflow", "describe", "process"])

            assert result.exit_code == 1
            # Error messages go to stderr
            assert "❌ Workflow 'process' not found." in result.stderr
            assert "Did you mean:" in result.stderr
            assert "- process-data" in result.stderr
            assert "- process-images" in result.stderr
            assert "- process-text" in result.stderr
            # Should only show top 3 suggestions
            assert "- backup-files" not in result.stderr

    def test_describe_nonexistent_workflow_no_suggestions(self) -> None:
        """Test describing a workflow that doesn't exist with no similar names."""
        all_workflows = [
            {"name": "backup-photos"},
            {"name": "daily-report"},
        ]

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_all.return_value = all_workflows

            result = invoke_cli(["workflow", "describe", "xyz-task"])

            assert result.exit_code == 1
            # Error messages go to stderr
            assert "❌ Workflow 'xyz-task' not found." in result.stderr
            # No suggestions should be shown
            assert "Did you mean:" not in result.stderr

    def test_describe_workflow_case_insensitive_suggestions(self) -> None:
        """Test that suggestions are case-insensitive."""
        all_workflows = [
            {"name": "Backup-Photos"},
            {"name": "backup-videos"},
            {"name": "BACKUP-DOCS"},
        ]

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = False
            mock_wm.list_all.return_value = all_workflows

            result = invoke_cli(["workflow", "describe", "backup"])

            assert result.exit_code == 1
            # Error messages go to stderr
            assert "Did you mean:" in result.stderr
            # All should match due to case-insensitive search
            assert "- Backup-Photos" in result.stderr
            assert "- backup-videos" in result.stderr
            assert "- BACKUP-DOCS" in result.stderr

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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["workflow", "describe", "complex-task"])

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


class TestWorkflowCommandGroup:
    """Tests for the workflow command group itself."""

    def test_workflow_help(self) -> None:
        """Test that workflow command group help is accessible."""
        result = invoke_cli(["workflow", "--help"])

        assert result.exit_code == 0
        assert "Manage saved workflows" in result.output
        assert "list" in result.output
        assert "describe" in result.output

    def test_workflow_without_subcommand(self) -> None:
        """Test that workflow command without subcommand shows help."""
        result = invoke_cli(["workflow"])

        # Click exits with code 2 when a required subcommand is missing
        assert result.exit_code == 2
        # Help message goes to stderr when there's an error
        assert "Manage saved workflows" in result.stderr


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

        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value

            # First, user lists workflows
            mock_wm.list_all.return_value = mock_workflows

            result = invoke_cli(["workflow", "list"])

            assert result.exit_code == 0
            assert "analyze-logs" in result.output

            # Then, user describes a specific workflow
            mock_wm.exists.return_value = True
            mock_wm.load.return_value = mock_metadata

            result = invoke_cli(["workflow", "describe", "analyze-logs"])

            assert result.exit_code == 0
            assert "Workflow: analyze-logs" in result.output
            assert "- log_path (required): Path to log file" in result.output
            assert "- report: Analysis report" in result.output

    def test_empty_list_to_save_workflow_guidance(self) -> None:
        """Test that empty list guides users to save workflows."""
        with patch("pflow.cli.commands.workflow.WorkflowManager") as MockWM:
            mock_wm = MockWM.return_value
            mock_wm.list_all.return_value = []

            # User tries to list workflows but finds none
            result = invoke_cli(["workflow", "list"])

            assert result.exit_code == 0
            assert "No workflows saved yet" in result.output
            assert 'pflow "your task"' in result.output

            # This guides them to create and save a workflow
            # (The actual workflow creation is tested elsewhere)
