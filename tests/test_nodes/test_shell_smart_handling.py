"""Tests for shell node smart error handling with stderr check.

These tests verify that the shell node correctly distinguishes between:
1. Legitimate "no results" cases (grep no match, which not found) - should succeed
2. Real errors from downstream commands in pipelines - should fail

The key insight: legitimate "no results" cases have empty stderr,
while real errors write to stderr.
"""

import json

from click.testing import CliRunner

from pflow.cli.main import main


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

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

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
                        # grep matches, sed fails with invalid regex
                        "command": "grep test | sed -E 's/.*?/bad/'",
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "execution failed" in combined
        # Error message should show the sed error
        assert "RE error" in combined or "repetition-operator" in combined

    def test_rg_no_match_succeeds(self, tmp_path):
        """ripgrep with no matches should succeed (exit 1, stderr empty)."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"data": {"type": "string", "required": False, "default": "hello"}},
            "nodes": [
                {
                    "id": "rg-nomatch",
                    "type": "shell",
                    "params": {"stdin": "${data}", "command": "rg notfound || true && rg notfound"},
                }
            ],
            "edges": [],
        }

        # Skip if rg not installed
        import shutil

        if shutil.which("rg") is None:
            return  # Skip test

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

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

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

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
                    "id": "which-sed-fail",
                    "type": "shell",
                    "params": {
                        # which succeeds, sed fails
                        "command": "which ls | sed -E 's/.*?/bad/'",
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

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

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

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
                    "id": "cmdv-sed-fail",
                    "type": "shell",
                    "params": {
                        "command": "command -v ls | sed -E 's/.*?/bad/'",
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "execution failed" in combined


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

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

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

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code == 0

        output = json.loads(result.output)
        steps = output["execution"]["steps"]
        assert len(steps) == 1
        assert "smart_handled" not in steps[0]
