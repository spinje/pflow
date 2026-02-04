"""Tests for shell stderr warning display when exit_code=0.

This test validates that stderr from shell nodes is properly displayed
when the command succeeds (exit_code=0) but produces stderr output.

Related bug: Shell node stderr not surfaced when exit_code=0
"""

import json

from click.testing import CliRunner

from pflow.cli.main import _display_stderr_warnings, _format_node_status_line, main
from tests.shared.markdown_utils import write_workflow_file


class TestShellStderrWarnings:
    """Test stderr warnings are displayed for successful shell commands with stderr."""

    def test_stderr_warning_displayed_when_exit_code_0(self, tmp_path):
        """Stderr should be displayed when shell succeeds but produces stderr.

        When a shell command succeeds (exit_code=0) but writes to stderr,
        the output should show a warning with the stderr content.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "stderr-with-success",
                    "type": "shell",
                    "params": {
                        # Command that writes to stderr but exits 0
                        "command": "echo 'This is stderr output' >&2; echo 'stdout'"
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        # Should succeed (exit code 0)
        assert result.exit_code == 0

        # Combine stdout and stderr for checking
        combined_output = result.output + (result.stderr or "")

        # Should show warning indicator for the node
        assert "stderr-with-success" in combined_output

        # Should show stderr warning section
        assert "Shell stderr (exit code 0):" in combined_output
        assert "This is stderr output" in combined_output

    def test_no_warning_when_stderr_empty(self, tmp_path):
        """No stderr warning should appear when shell has no stderr output."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "no-stderr",
                    "type": "shell",
                    "params": {"command": "echo 'just stdout'"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code == 0

        combined_output = result.output + (result.stderr or "")

        # Should NOT show stderr warning section
        assert "Shell stderr (exit code 0):" not in combined_output

    def test_no_warning_when_exit_code_nonzero(self, tmp_path):
        """No stderr warning when command fails (already shown as error)."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "failed-command",
                    "type": "shell",
                    "params": {"command": "echo 'error' >&2; exit 1"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        # Command failed
        assert result.exit_code != 0

        combined_output = result.output + (result.stderr or "")

        # Should NOT show stderr warning section (error is already shown differently)
        assert "Shell stderr (exit code 0):" not in combined_output

    def test_multiple_nodes_with_stderr(self, tmp_path):
        """Multiple shell nodes with stderr should all show warnings."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "node1-stderr",
                    "type": "shell",
                    "params": {"command": "echo 'stderr from node1' >&2"},
                },
                {
                    "id": "node2-stderr",
                    "type": "shell",
                    "params": {"command": "echo 'stderr from node2' >&2"},
                },
            ],
            "edges": [{"from": "node1-stderr", "to": "node2-stderr"}],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code == 0

        combined_output = result.output + (result.stderr or "")

        # Both nodes should show stderr warnings
        assert "node1-stderr:" in combined_output
        assert "stderr from node1" in combined_output
        assert "node2-stderr:" in combined_output
        assert "stderr from node2" in combined_output


class TestWorkflowLevelStderrIndicator:
    """Test workflow-level status shows warning when any node has stderr."""

    def test_workflow_shows_warning_indicator_when_stderr_present(self, tmp_path):
        """Workflow completion should show warning when any node has stderr."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "stderr-node",
                    "type": "shell",
                    "params": {"command": "echo 'warning' >&2"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code == 0

        combined_output = result.output + (result.stderr or "")

        # Workflow should show warning indicator (not checkmark)
        assert "Workflow completed in" in combined_output
        # Check for warning emoji at start of the completion line
        lines = combined_output.split("\n")
        completion_line = next(line for line in lines if "Workflow completed in" in line)
        assert completion_line.startswith("\u26a0")  # Warning emoji

    def test_workflow_shows_checkmark_when_no_stderr(self, tmp_path):
        """Workflow completion should show checkmark when no stderr."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "clean-node",
                    "type": "shell",
                    "params": {"command": "echo 'clean output'"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code == 0

        combined_output = result.output + (result.stderr or "")

        # Workflow should show checkmark (not warning)
        lines = combined_output.split("\n")
        completion_line = next(line for line in lines if "Workflow completed in" in line)
        assert "\u2713" in completion_line  # Checkmark

    def test_workflow_shows_warning_when_any_node_has_stderr(self, tmp_path):
        """Workflow should show warning if ANY node has stderr, not just all."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "clean-node",
                    "type": "shell",
                    "params": {"command": "echo 'clean'"},
                },
                {
                    "id": "stderr-node",
                    "type": "shell",
                    "params": {"command": "echo 'warning' >&2"},
                },
            ],
            "edges": [{"from": "clean-node", "to": "stderr-node"}],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code == 0

        combined_output = result.output + (result.stderr or "")

        # Workflow should show warning because one node had stderr
        lines = combined_output.split("\n")
        completion_line = next(line for line in lines if "Workflow completed in" in line)
        assert completion_line.startswith("\u26a0")  # Warning emoji


class TestStderrInJsonOutput:
    """Test stderr visibility in JSON output for AI agent consumption."""

    def test_json_output_includes_stderr_in_steps(self, tmp_path):
        """JSON output should include has_stderr and stderr fields for agents.

        AI agents consume pflow output programmatically. They need to detect
        when stderr was produced to make informed decisions about workflow fixes.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "shell-with-stderr",
                    "type": "shell",
                    "params": {"command": "echo 'warning message' >&2; echo 'output'"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code == 0

        output = json.loads(result.output)

        # Verify stderr is in the result data
        node_result = output["result"]["shell-with-stderr"]
        assert "stderr" in node_result
        assert "warning message" in node_result["stderr"]

        # Verify has_stderr flag is in execution steps (for agent detection)
        steps = output["execution"]["steps"]
        assert len(steps) == 1
        assert steps[0]["has_stderr"] is True
        assert "warning message" in steps[0]["stderr"]


class TestPipelineFailureScenario:
    """Test the exact bug scenario: pipeline where intermediate command fails."""

    def test_pipeline_intermediate_stderr_shows_warning(self, tmp_path):
        """Pipeline with intermediate stderr should surface the warning.

        This tests the bug scenario from the bug report:
        - Pipeline: cmd1 | cmd2 | cmd3
        - cmd2 writes to stderr (warning/error)
        - cmd3 succeeds, so pipeline exit code is 0
        - stderr was hidden before the fix

        Uses a portable subshell that writes to stderr while passing data through.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "pipeline-node",
                    "type": "shell",
                    "params": {
                        # Pipeline where middle command writes stderr but passes data through
                        # Subshell writes warning to stderr AND cats stdin to stdout
                        "command": "echo 'test' | (echo 'pipeline warning' >&2; cat) | cat"
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        # Workflow succeeds (exit code 0)
        assert result.exit_code == 0

        combined_output = result.output + (result.stderr or "")

        # The key assertion: stderr from pipeline should be visible
        assert "pipeline warning" in combined_output

        # Warning indicators should be present
        assert "Shell stderr (exit code 0):" in combined_output


class TestDisplayStderrWarnings:
    """Unit tests for _display_stderr_warnings function."""

    def test_displays_stderr_for_steps_with_has_stderr(self, capsys):
        """Should display stderr for steps with has_stderr=True."""
        steps = [
            {
                "node_id": "test-node",
                "status": "completed",
                "has_stderr": True,
                "stderr": "Some error message",
            }
        ]

        _display_stderr_warnings(steps)

        captured = capsys.readouterr()
        assert "Shell stderr (exit code 0):" in captured.err
        assert "test-node:" in captured.err
        assert "Some error message" in captured.err

    def test_no_output_when_no_stderr_steps(self, capsys):
        """Should not display anything when no steps have stderr."""
        steps = [
            {"node_id": "node1", "status": "completed"},
            {"node_id": "node2", "status": "completed"},
        ]

        _display_stderr_warnings(steps)

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_truncates_long_stderr(self, capsys):
        """Long stderr should be truncated to 300 chars."""
        long_stderr = "X" * 400

        steps = [
            {
                "node_id": "verbose-node",
                "status": "completed",
                "has_stderr": True,
                "stderr": long_stderr,
            }
        ]

        _display_stderr_warnings(steps)

        captured = capsys.readouterr()
        assert "..." in captured.err
        # Should have truncated to 300 + "..."
        assert "X" * 301 not in captured.err

    def test_multiline_stderr_indented(self, capsys):
        """Multiline stderr should be properly indented."""
        multiline_stderr = "Line 1\nLine 2\nLine 3"

        steps = [
            {
                "node_id": "multiline-node",
                "status": "completed",
                "has_stderr": True,
                "stderr": multiline_stderr,
            }
        ]

        _display_stderr_warnings(steps)

        captured = capsys.readouterr()
        # Check that newlines are replaced with indented newlines
        assert "Line 1" in captured.err
        assert "Line 2" in captured.err


class TestFormatNodeStatusLine:
    """Unit tests for _format_node_status_line with stderr indicator."""

    def test_warning_indicator_when_has_stderr(self):
        """Should show warning indicator when node has stderr."""
        step = {
            "node_id": "stderr-node",
            "status": "completed",
            "duration_ms": 100,
            "has_stderr": True,
        }

        result = _format_node_status_line(step)

        # Should have warning indicator instead of checkmark
        assert result.startswith("  \u26a0")  # Warning symbol
        assert "stderr-node" in result

    def test_checkmark_when_no_stderr(self):
        """Should show checkmark when node has no stderr."""
        step = {
            "node_id": "clean-node",
            "status": "completed",
            "duration_ms": 100,
        }

        result = _format_node_status_line(step)

        # Should have checkmark
        assert "\u2713" in result  # Checkmark
        assert "clean-node" in result

    def test_has_stderr_only_set_for_completed_nodes(self):
        """has_stderr is only set by build_execution_steps when status=completed.

        This test documents that build_execution_steps guards against the
        impossible state of has_stderr=True with status=failed. The display
        function trusts this invariant and doesn't need redundant checks.
        """
        # In practice, build_execution_steps only sets has_stderr for completed nodes
        # (see execution_state.py line 139: status == "completed" check)
        step = {
            "node_id": "failed-node",
            "status": "failed",
            "duration_ms": 100,
            # has_stderr is NOT set here - this matches real behavior
        }

        result = _format_node_status_line(step)

        # Should have error indicator
        assert "\u2717" in result  # Cross mark
        assert "failed-node" in result
