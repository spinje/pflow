"""Tests for --validate-only flag.

This module tests the --validate-only flag that validates workflows WITHOUT executing them.
Core contract: Validation must NEVER execute nodes or cause side effects.

Implementation: src/pflow/cli/main.py lines 1842-1867, 1896-1899, 2905-2906
"""

import json
import sys
from io import StringIO
from pathlib import Path
from typing import Any

from tests.shared.markdown_utils import write_workflow_file


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
        # Provide empty stdin with isatty=False to prevent blocking
        mock_stdin = StringIO("")
        mock_stdin.isatty = lambda: False
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


class TestValidateOnlyNoExecution:
    """Test that --validate-only NEVER executes nodes.

    This is the core contract - the most critical behavior to validate.
    """

    def test_validate_only_never_executes_nodes(self, tmp_path: Path) -> None:
        """--validate-only MUST NOT execute any nodes.

        This is the core contract. If this test passes but nodes executed,
        the test has failed its purpose.
        """
        # Create a proof file path that should NOT be created
        proof_file = tmp_path / "validate_only_proof.txt"

        # Create workflow with shell node that would create the file
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": f"touch {proof_file}"}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        # Run with --validate-only
        result = invoke_cli(["--validate-only", str(workflow_path)])

        # CRITICAL: File should NOT exist (proves node didn't execute)
        assert not proof_file.exists(), "Node executed despite --validate-only flag!"

        # Should succeed (valid workflow)
        assert result.exit_code == 0
        assert "valid" in result.output.lower()


class TestValidateOnlyAutoNormalization:
    """Test auto-normalization behavior during validation."""

    def test_validate_only_auto_normalizes_missing_fields(self, tmp_path: Path) -> None:
        """Missing ir_version and edges should be auto-added.

        Real behavior: Agents can omit boilerplate
        Bad test: Just check exit code (doesn't prove normalization happened)
        Good test: Verify validation succeeds for workflow that would fail without normalization
        """
        # Deliberately omit ir_version and edges
        workflow = {"nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}]}
        # NO ir_version, NO edges

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", str(workflow_path)])

        # Should succeed because auto-normalization adds missing fields
        assert result.exit_code == 0, f"Validation failed: {result.output}\n{result.stderr}"
        # Should not error about missing ir_version
        assert "ir_version" not in result.output.lower()
        assert "ir_version" not in result.stderr.lower()


class TestValidateOnlyTemplateValidation:
    """Test template structure validation."""

    def test_validate_only_catches_invalid_template_references(self, tmp_path: Path) -> None:
        """Should catch template references to non-existent nodes.

        Real behavior: Structural validation prevents runtime failures
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "fetch", "type": "shell", "params": {"command": "echo data"}},
                {
                    "id": "process",
                    "type": "shell",
                    "params": {"command": "echo ${wrong_node.result}"},  # References non-existent node
                },
            ],
            "edges": [{"from": "fetch", "to": "process"}],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", str(workflow_path)])

        # Should FAIL validation
        assert result.exit_code != 0, "Should have caught invalid node reference"
        # Check error mentions the problematic reference
        combined_output = result.output + result.stderr
        assert "wrong_node" in combined_output.lower() or "does not exist" in combined_output.lower()


class TestValidateOnlyWithoutInputValues:
    """Test that validation works without providing actual parameter values."""

    def test_validate_only_works_without_input_values(self, tmp_path: Path) -> None:
        """Validation should succeed even when workflow requires inputs.

        Key insight: Structure validation ≠ value validation
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "repo": {"type": "string", "description": "GitHub repo"},
                "pr_number": {"type": "number", "description": "PR number"},
            },
            "nodes": [{"id": "fetch", "type": "shell", "params": {"command": "echo ${repo} ${pr_number}"}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        # Run WITHOUT providing repo=... pr_number=... parameters
        result = invoke_cli(["--validate-only", str(workflow_path)])

        # Should succeed (structural validation uses dummy values)
        assert result.exit_code == 0, f"Failed without inputs: {result.output}\n{result.stderr}"


class TestValidateOnlySkipsPrepareInputs:
    """Test that prepare_inputs is NOT called during validation."""

    def test_validate_only_skips_prepare_inputs(self, tmp_path: Path) -> None:
        """Should NOT call prepare_inputs() which would error on missing params.

        This test validates the fix for the duplicate error message bug.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"required_input": {"type": "string", "description": "Required"}},
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo ${required_input}"}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", str(workflow_path)])

        # Should succeed without errors about missing required_input
        assert result.exit_code == 0, f"Failed: {result.output}\n{result.stderr}"
        # Should NOT show "Workflow requires input 'required_input'" error
        combined = (result.output + result.stderr).lower()
        assert "requires input" not in combined


class TestValidateOnlyEdgeCases:
    """Test edge cases and error handling."""

    def test_validate_only_catches_unknown_node_types(self, tmp_path: Path) -> None:
        """Should catch references to nodes that don't exist in registry."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "non_existent_node_type", "params": {}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", str(workflow_path)])

        assert result.exit_code != 0, "Should have caught unknown node type"
        combined = (result.output + result.stderr).lower()
        assert "non_existent_node_type" in combined or "not found" in combined

    def test_validate_only_handles_malformed_markdown(self, tmp_path: Path) -> None:
        """Should show helpful error for invalid markdown workflow."""
        workflow_path = tmp_path / "bad.pflow.md"
        # Missing ## Steps section — invalid markdown workflow
        workflow_path.write_text("# Bad Workflow\n\nJust some text, no steps.\n")

        result = invoke_cli(["--validate-only", str(workflow_path)])

        assert result.exit_code != 0, "Should have caught malformed workflow"
        combined = (result.output + result.stderr).lower()
        assert "steps" in combined or "syntax" in combined or "parse" in combined

    def test_validate_only_rejects_json_files(self, tmp_path: Path) -> None:
        """Should show helpful error when a .json file is passed."""
        workflow_path = tmp_path / "old.json"
        workflow_path.write_text('{"nodes": []}')

        result = invoke_cli(["--validate-only", str(workflow_path)])

        assert result.exit_code != 0, "Should reject .json files"
        combined = (result.output + result.stderr).lower()
        assert "json" in combined or ".pflow.md" in combined


class TestValidateOnlyJSONOutput:
    """Test JSON output format for --validate-only."""

    def test_validate_only_json_success(self, tmp_path: Path) -> None:
        """JSON output should contain success indicator."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", "--output-format", "json", str(workflow_path)])

        assert result.exit_code == 0
        # Parse JSON output
        output_data = json.loads(result.output)
        assert output_data["success"] is True
        assert "valid" in output_data.get("message", "").lower()

    def test_validate_only_json_failure(self, tmp_path: Path) -> None:
        """JSON output should contain structured errors."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "unknown_type", "params": {}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", "--output-format", "json", str(workflow_path)])

        assert result.exit_code != 0
        # Parse JSON output
        output_data = json.loads(result.output)
        assert output_data["success"] is False
        assert "errors" in output_data
        assert isinstance(output_data["errors"], list)
        assert len(output_data["errors"]) > 0


class TestValidateOnlyWithComplexWorkflows:
    """Test validation with more complex workflow patterns."""

    def test_validate_only_with_multiple_nodes_and_edges(self, tmp_path: Path) -> None:
        """Should validate multi-node workflows with edges."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "shell", "params": {"command": "echo start"}},
                {"id": "node2", "type": "shell", "params": {"command": "echo ${node1.stdout}"}},
                {"id": "node3", "type": "shell", "params": {"command": "echo ${node2.stdout}"}},
            ],
            "edges": [{"from": "node1", "to": "node2"}, {"from": "node2", "to": "node3"}],
        }

        workflow_path = tmp_path / "complex.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", str(workflow_path)])

        # Should succeed - valid structure
        assert result.exit_code == 0, f"Failed: {result.output}\n{result.stderr}"

    def test_validate_only_catches_forward_references(self, tmp_path: Path) -> None:
        """Should catch forward node references (node referencing one that hasn't executed yet).

        In the markdown format, edges are always linear (from document order), so
        circular edges can't occur. But forward references (node1 referencing node2's
        output when node2 comes later) are still caught by validation.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "shell", "params": {"command": "echo ${node2.stdout}"}},
                {"id": "node2", "type": "shell", "params": {"command": "echo ${node1.stdout}"}},
            ],
            "edges": [{"from": "node1", "to": "node2"}],
        }

        workflow_path = tmp_path / "forward-ref.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", str(workflow_path)])

        # Should fail - forward reference
        assert result.exit_code != 0, "Should have caught forward reference"
        combined = (result.output + result.stderr).lower()
        assert "node1" in combined or "execution order" in combined or "reference" in combined
