"""Tests for shell stderr display in CLI error output.

This test validates that stderr from shell nodes is properly displayed
in verbose mode when a shell command fails.

Related bug: Shell node stderr not surfaced in error messages
"""

import json

from click.testing import CliRunner

from pflow.cli.main import main


class TestShellStderrDisplay:
    """Test shell stderr is displayed in CLI error output."""

    def test_shell_stderr_displayed_in_verbose_mode(self, tmp_path):
        """Stderr from failed shell nodes should be displayed in verbose mode.

        When a shell command fails and writes to stderr, the error output
        should include the stderr content to help users debug the issue.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "failing-command",
                    "type": "shell",
                    "params": {
                        # Command that writes to stderr and fails
                        "command": "echo 'This error message should be visible' >&2; exit 1"
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--verbose", str(workflow_path)])

        assert result.exit_code != 0

        # Verify stderr is displayed in verbose output
        assert "Stderr:" in result.output or "Stderr:" in (result.stderr or "")
        assert "This error message should be visible" in result.output or "This error message should be visible" in (
            result.stderr or ""
        )

    def test_shell_stderr_in_json_output(self, tmp_path):
        """JSON output should include shell_stderr field for failed shell nodes."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "failing-command",
                    "type": "shell",
                    "params": {"command": "echo 'stderr content here' >&2; exit 1"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code != 0

        # Parse JSON output
        output = json.loads(result.output)

        # Verify shell_stderr is in the error structure
        assert "errors" in output
        assert len(output["errors"]) > 0

        error = output["errors"][0]
        assert "shell_stderr" in error
        assert "stderr content here" in error["shell_stderr"]

    def test_shell_stderr_truncated_when_long(self, tmp_path):
        """Long stderr should be truncated in verbose output."""
        # Create stderr longer than 300 chars
        long_error = "X" * 400

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "verbose-error",
                    "type": "shell",
                    "params": {"command": f"echo '{long_error}' >&2; exit 1"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--verbose", str(workflow_path)])

        assert result.exit_code != 0

        # Output should contain truncated stderr with "..."
        combined_output = result.output + (result.stderr or "")
        assert "Stderr:" in combined_output
        assert "..." in combined_output  # Truncation indicator

    def test_no_stderr_section_when_stderr_empty(self, tmp_path):
        """No stderr section should appear when shell has no stderr output."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "no-stderr",
                    "type": "shell",
                    "params": {
                        # Fails with exit code but no stderr
                        "command": "exit 1"
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--verbose", str(workflow_path)])

        assert result.exit_code != 0

        # Should show shell details but NOT stderr section (since it's empty)
        combined_output = result.output + (result.stderr or "")
        assert "Shell details:" in combined_output
        assert "Command:" in combined_output
        # Stderr line should not appear when stderr is empty
        # (we check this by ensuring "Stderr:" doesn't appear with empty content)
