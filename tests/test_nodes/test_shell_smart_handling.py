"""Tests for shell node smart error handling with stderr check.

Related: Task 110 - Fix Shell Node Smart Error Handling

These tests verify that the shell node correctly distinguishes between:
1. Legitimate "no results" cases (grep no match, which not found) - should succeed
2. Real errors from downstream commands in pipelines - should fail

The key insight: legitimate "no results" cases have empty stderr,
while real errors write to stderr.

Known limitation (Task 110 future work): Commands that fail silently
(exit 1, no stderr) like `grep foo | false` will incorrectly succeed.
This requires PIPESTATUS capture to fix properly.
"""

import json

from click.testing import CliRunner

from pflow.cli.main import main
from tests.shared.markdown_utils import write_workflow_file


class TestSmartHandlingStderrCheck:
    """Test that smart handling checks stderr before applying."""

    def test_grep_no_match_succeeds(self, tmp_path):
        """grep with no matches should succeed (exit 1, stderr empty)."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": False, "default": "hello world"}},
            "nodes": [
                {
                    "id": "grep-nomatch",
                    "type": "shell",
                    "params": {"stdin": "${data}", "command": "grep notfound"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code == 0
        combined = result.output + (result.stderr or "")
        assert "Workflow completed" in combined
        assert "[no matches]" in combined  # Smart handling tag visible

    def test_grep_downstream_error_fails(self, tmp_path):
        """grep + downstream error should fail (exit 1, stderr has content)."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": False, "default": "test"}},
            "nodes": [
                {
                    "id": "grep-sed-fail",
                    "type": "shell",
                    "params": {
                        "stdin": "${data}",
                        # grep matches, then cat fails reading nonexistent file
                        # This works on both BSD (macOS) and GNU (Linux) systems
                        "command": "grep test | cat /nonexistent_file_xyz",
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "execution failed" in combined
        # Error message should mention the missing file
        assert "No such file" in combined or "nonexistent" in combined.lower()

    def test_rg_no_match_succeeds(self, tmp_path):
        """ripgrep with no matches should succeed (exit 1, stderr empty)."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": False, "default": "hello"}},
            "nodes": [
                {
                    "id": "rg-nomatch",
                    "type": "shell",
                    "params": {"stdin": "${data}", "command": "rg notfound"},
                }
            ],
            "edges": [],
        }

        # Skip if rg not installed
        import shutil

        if shutil.which("rg") is None:
            return  # Skip test

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        # Should succeed - rg no match is OK
        assert result.exit_code == 0

    def test_which_not_found_succeeds(self, tmp_path):
        """which for missing command should succeed (exit 1, stderr empty)."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "which-check",
                    "type": "shell",
                    "params": {"command": "which nonexistent_command_xyz_123"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code == 0
        combined = result.output + (result.stderr or "")
        assert "Workflow completed" in combined
        assert "[not found]" in combined  # Smart handling tag visible

    def test_which_downstream_error_fails(self, tmp_path):
        """which + downstream error should fail (exit 1, stderr has content)."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "which-cat-fail",
                    "type": "shell",
                    "params": {
                        # which succeeds, cat fails reading nonexistent file
                        "command": "which ls | cat /nonexistent_file_xyz",
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "execution failed" in combined

    def test_command_v_not_found_succeeds(self, tmp_path):
        """command -v for missing command should succeed."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "cmdv-check",
                    "type": "shell",
                    "params": {"command": "command -v nonexistent_xyz_123"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code == 0
        combined = result.output + (result.stderr or "")
        assert "Workflow completed" in combined

    def test_command_v_downstream_error_fails(self, tmp_path):
        """command -v + downstream error should fail."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "cmdv-cat-fail",
                    "type": "shell",
                    "params": {
                        # command -v succeeds, cat fails reading nonexistent file
                        "command": "command -v ls | cat /nonexistent_file_xyz",
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "execution failed" in combined

    def test_type_downstream_error_fails(self, tmp_path):
        """type + downstream error should fail (not be masked by 'not found' check)."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "type-sed-fail",
                    "type": "shell",
                    "params": {
                        # type succeeds (ls exists), sed fails with unbalanced bracket
                        # Note: Using unbalanced bracket instead of .*? for cross-platform compatibility
                        # (GNU sed on Linux handles .*? differently than BSD sed on macOS)
                        "command": "type ls | sed -E 's/[/bad/'",
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "execution failed" in combined


class TestSmartHandlingKnownLimitations:
    """Document known limitations of smart handling.

    These tests document current behavior for edge cases that will be
    addressed in future work (Task 110 - PIPESTATUS capture).
    """

    def test_silent_downstream_failure_known_limitation(self, tmp_path):
        """Known limitation: grep | false succeeds (no stderr, exit 1).

        This is a documented limitation. Commands that fail silently
        (exit 1 but no stderr) cannot be distinguished from legitimate
        "no results" cases without PIPESTATUS capture.

        Future fix: Task 110 will implement PIPESTATUS to detect which
        command in a pipeline actually failed.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": False, "default": "test"}},
            "nodes": [
                {
                    "id": "grep-false",
                    "type": "shell",
                    "params": {
                        "stdin": "${data}",
                        # grep matches, false fails silently (no stderr)
                        "command": "grep test | false",
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        # KNOWN LIMITATION: This incorrectly succeeds because:
        # - exit code is 1 (from false)
        # - stderr is empty (false doesn't write to stderr)
        # - grep is in the command
        # So it's treated as "grep no match" when it's actually "false failed"
        assert result.exit_code == 0  # Should ideally be != 0
        combined = result.output + (result.stderr or "")
        assert "[no matches]" in combined  # Incorrectly tagged as no matches


class TestSmartHandlingJsonOutput:
    """Test that smart handling is visible in JSON output."""

    def test_smart_handling_in_json_steps(self, tmp_path):
        """JSON output should include smart_handled flag in steps."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": False, "default": "hello"}},
            "nodes": [
                {
                    "id": "grep-nomatch",
                    "type": "shell",
                    "params": {"stdin": "${data}", "command": "grep notfound"},
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
        steps = output["execution"]["steps"]
        assert len(steps) == 1
        assert steps[0]["smart_handled"] is True
        assert "no matches" in steps[0]["smart_handled_reason"]

    def test_no_smart_handling_flag_on_normal_success(self, tmp_path):
        """JSON output should NOT have smart_handled for normal success."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "echo-test",
                    "type": "shell",
                    "params": {"command": "echo hello"},
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
        steps = output["execution"]["steps"]
        assert len(steps) == 1
        assert "smart_handled" not in steps[0]
