"""Tests for pre-execution validation.

This module tests that full validation (including node type checks) happens
BEFORE any nodes execute, not just schema validation.

The key contract: Unknown node types must be caught at validation time,
not at compilation/runtime, and NO nodes should execute before validation fails.
"""

import json
import sys
from io import StringIO
from pathlib import Path
from typing import Any


def invoke_cli(args: list[str]) -> Any:
    """Helper to invoke CLI with proper routing through main_wrapper.

    Since main_wrapper manipulates sys.argv directly, we need to simulate that behavior.
    """
    from pflow.cli.main_wrapper import cli_main

    # Save original sys.argv and streams
    original_argv = sys.argv[:]
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    original_stdin = sys.stdin

    # Capture output
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    try:
        # Set up sys.argv as if running from command line
        sys.argv = ["pflow", *args]
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        # Mock stdin to prevent reading attempts
        mock_stdin = StringIO("")
        mock_stdin.isatty = lambda: False  # type: ignore[method-assign]
        sys.stdin = mock_stdin

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
        sys.stdin = original_stdin


class TestValidationBeforeExecution:
    """Test that full validation happens before any node execution.

    This is the core contract - validation errors (like unknown node types)
    must be caught BEFORE any nodes execute, not at runtime.
    """

    def test_unknown_node_caught_before_any_execution(self, tmp_path: Path) -> None:
        """Unknown node types must be caught before any nodes execute.

        This test creates a workflow where step1 would create a proof file if executed.
        If the proof file exists after running the workflow, validation failed its job.
        """
        # Create a "proof" file that step1 would create if it executed
        proof_file = tmp_path / "execution_proof.txt"

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "step1",
                    "type": "shell",
                    "params": {"command": f"touch {proof_file}"},
                },
                {
                    "id": "step2",
                    "type": "nonexistent-node-type-xyz",
                    "params": {},
                },
            ],
            "edges": [{"from": "step1", "to": "step2"}],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        result = invoke_cli([str(workflow_path)])

        # Should fail with validation error
        assert result.exit_code != 0

        # Error should mention the unknown node type
        combined_output = result.output + result.stderr
        assert "nonexistent-node-type-xyz" in combined_output.lower() or "unknown node type" in combined_output.lower()

        # CRITICAL: step1 should NOT have executed
        assert not proof_file.exists(), (
            "Validation should happen BEFORE any node executes! "
            "The shell node ran, which means validation happened too late."
        )

    def test_validation_error_has_clean_message(self, tmp_path: Path) -> None:
        """Validation errors should have clean, user-friendly messages.

        Not ugly tracebacks or "Planning failed" messages.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "bad-node",
                    "type": "this-node-does-not-exist",
                    "params": {},
                },
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        result = invoke_cli([str(workflow_path)])

        assert result.exit_code != 0

        combined_output = result.output + result.stderr

        # Should NOT have ugly traceback messages
        assert "Traceback" not in combined_output
        assert "Planning failed" not in combined_output

        # Should have the unknown node type mentioned
        assert "this-node-does-not-exist" in combined_output.lower()

    def test_validation_error_json_format(self, tmp_path: Path) -> None:
        """Validation errors in JSON format should be structured properly."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "bad-node",
                    "type": "fake-node-type",
                    "params": {},
                },
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        result = invoke_cli(["--output-format", "json", str(workflow_path)])

        assert result.exit_code != 0

        # Parse JSON output
        try:
            output_data = json.loads(result.output)
        except json.JSONDecodeError:
            # Try stderr if stdout is empty
            output_data = json.loads(result.stderr) if result.stderr.strip() else None

        assert output_data is not None, "Expected JSON output"
        assert output_data.get("success") is False
        assert "validation_errors" in output_data or "error" in output_data

    def test_valid_workflow_still_executes(self, tmp_path: Path) -> None:
        """Valid workflows should still execute normally after validation passes."""
        output_file = tmp_path / "output.txt"

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "write-test",
                    "type": "write-file",
                    "params": {
                        "file_path": str(output_file),
                        "content": "validation passed",
                    },
                },
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        result = invoke_cli([str(workflow_path)])

        # Should succeed
        assert result.exit_code == 0, f"Expected success but got: {result.stderr}"

        # File should be created (execution happened)
        assert output_file.exists(), "Workflow should have executed and created the file"
        assert output_file.read_text() == "validation passed"


class TestValidationConsistency:
    """Test that validation is consistent between --validate-only and normal execution."""

    def test_validate_only_and_normal_catch_same_errors(self, tmp_path: Path) -> None:
        """Both --validate-only and normal execution should catch the same validation errors."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "bad-node",
                    "type": "unknown-node-type-abc",
                    "params": {},
                },
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        # Run with --validate-only
        validate_result = invoke_cli(["--validate-only", str(workflow_path)])

        # Run normally (without --validate-only)
        normal_result = invoke_cli([str(workflow_path)])

        # Both should fail
        assert validate_result.exit_code != 0
        assert normal_result.exit_code != 0

        # Both should mention the unknown node type
        validate_output = validate_result.output + validate_result.stderr
        normal_output = normal_result.output + normal_result.stderr

        assert "unknown-node-type-abc" in validate_output.lower()
        assert "unknown-node-type-abc" in normal_output.lower()
