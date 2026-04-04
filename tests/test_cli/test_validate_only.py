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
        assert output_data.get("validated_only") is True

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

    def test_validate_only_json_warnings_are_structured(self, tmp_path: Path) -> None:
        """JSON warnings should be serialized as structured dicts, not Diagnostic repr strings."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "shell",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "warning.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", "--output-format", "json", str(workflow_path)])

        assert result.exit_code == 0
        output_data = json.loads(result.output)

        assert output_data["warnings"], "Expected cache lint warning in validate-only JSON"
        warning = output_data["warnings"][0]
        assert isinstance(warning, dict)
        assert warning["severity"] == "warning"
        assert warning["source"] == "validator"
        assert warning["node_id"] == "shell"
        assert warning["suggestions"]


class TestValidationErrorDiagnosticShape:
    """Regression guard for Task 144: validation errors are Diagnostic objects.

    ValidationResult.errors changed from list[str] to list[Diagnostic].
    These tests verify the two main consumers (JSON output and text formatter)
    handle the new type correctly — not just that they don't crash, but that
    they produce the specific structured data that agents depend on.
    """

    def test_json_errors_are_diagnostic_dicts_not_strings(self, tmp_path: Path) -> None:
        """JSON error entries must be Diagnostic.to_display_dict(), not {"message": str, "category": str}.

        Before Task 144, errors were: [{"message": "error text", "category": "validation"}]
        After: [{"severity": "error", "message": "...", "source": "validation", "title": "...", ...}]
        Any agent parsing "severity" or "title" from the JSON would break if this regresses.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "unknown_type", "params": {}}],
            "edges": [],
        }
        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", "--output-format", "json", str(workflow_path)])
        assert result.exit_code != 0

        output_data = json.loads(result.output)
        errors = output_data["errors"]
        assert len(errors) > 0

        err = errors[0]
        # These keys come from Diagnostic.to_display_dict() — NOT from the old string wrapper
        assert "severity" in err, f"Missing 'severity' key — errors may have reverted to string wrapping: {err}"
        assert err["severity"] == "error"
        assert "source" in err, f"Missing 'source' — not a Diagnostic dict: {err}"
        assert "message" in err
        assert "title" in err, f"Missing 'title' — Diagnostic should have title set: {err}"

    def test_text_validation_failure_renders_diagnostic_fields(self, tmp_path: Path) -> None:
        """Text output must render per-error location and suggestions from Diagnostic fields.

        If format_validation_failure() regresses to treating Diagnostics as strings,
        it would render Diagnostic.__repr__() instead of structured output.
        This test uses a workflow with TWO validation errors to verify numbered format.
        """
        # Workflow with two problems: bad type AND unresolvable template
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "bad-type", "type": "nonexistent_type_xyz", "params": {}},
                {"id": "fetch", "type": "shell", "params": {"command": "echo ${bad-type.missing_field}"}},
            ],
            "edges": [{"from": "bad-type", "to": "fetch"}],
        }
        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        result = invoke_cli(["--validate-only", str(workflow_path)])
        assert result.exit_code != 0

        combined = result.output + result.stderr
        # Must use numbered format (from Diagnostic-aware formatter), not bullet format
        assert "1." in combined, f"Expected numbered errors, got:\n{combined}"
        # Must NOT contain Diagnostic repr (the failure mode if treated as string)
        assert "Diagnostic(" not in combined, f"Diagnostic repr leaked into output:\n{combined}"

    """End-to-end regression tests for issue #209: parser warnings silently lost.

    These verify that parser-level diagnostics (section typos, orphaned content)
    actually appear in CLI text and JSON output — the full pipeline from
    parse_markdown() through the runner through display.
    """

    def test_parser_typo_warning_appears_in_validate_text(self, tmp_path: Path) -> None:
        """A '## Input' typo (near-miss for '## Inputs') must appear in validate-only text."""
        workflow_md = (
            "# Test\n\n"
            "## Input\n\n"  # typo — should warn about near-miss for '## Inputs'
            "### api-key\n\n"
            "User API key.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### echo\n\n"
            "Echo a greeting.\n\n"
            "- type: shell\n"
            "- command: echo hello\n"
        )
        workflow_path = tmp_path / "typo.pflow.md"
        workflow_path.write_text(workflow_md)

        result = invoke_cli(["--validate-only", str(workflow_path)])

        assert result.exit_code == 0
        # The parser warning must reach stderr
        assert "Input" in result.stderr, (
            f"Parser typo warning not in CLI text output.\nstdout: {result.output}\nstderr: {result.stderr}"
        )
        assert "Inputs" in result.stderr

    def test_parser_typo_warning_appears_in_validate_json(self, tmp_path: Path) -> None:
        """A '## Input' typo must appear in the diagnostics array of validate-only JSON."""
        workflow_md = (
            "# Test\n\n"
            "## Input\n\n"  # typo — should warn about near-miss for '## Inputs'
            "### api-key\n\n"
            "User API key.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### echo\n\n"
            "Echo a greeting.\n\n"
            "- type: shell\n"
            "- command: echo hello\n"
        )
        workflow_path = tmp_path / "typo.pflow.md"
        workflow_path.write_text(workflow_md)

        result = invoke_cli(["--validate-only", "--output-format", "json", str(workflow_path)])

        assert result.exit_code == 0
        data = json.loads(result.output)
        diagnostics = data.get("diagnostics", [])
        parser_warnings = [d for d in diagnostics if d.get("source") == "parser"]
        assert parser_warnings, (
            f"Parser warning not in validate-only JSON diagnostics.\nFull output: {json.dumps(data, indent=2)}"
        )
        assert any("Input" in w["message"] for w in parser_warnings)

    def test_parser_typo_warning_appears_in_execution_output(self, tmp_path: Path) -> None:
        """A parser warning must survive through execution (not just validate-only)."""
        workflow_md = (
            "# Test\n\n"
            "## Input\n\n"  # typo — should warn about near-miss for '## Inputs'
            "### api-key\n\n"
            "User API key.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### echo\n\n"
            "Echo a greeting.\n\n"
            "- type: shell\n"
            "- command: echo hello\n"
        )
        workflow_path = tmp_path / "typo.pflow.md"
        workflow_path.write_text(workflow_md)

        result = invoke_cli([str(workflow_path)])

        # Workflow should succeed (the ## Input section is just ignored, not an error)
        # Parser warning should appear in output
        combined = result.output + result.stderr
        assert "Input" in combined and "Inputs" in combined, (
            f"Parser typo warning not in execution output.\nstdout: {result.output}\nstderr: {result.stderr}"
        )


class TestFailurePathShowsWarnings:
    """Regression test: failure output must show warnings alongside errors.

    The spec requires 'Failure path shows warnings (currently doesn't)'.
    Before Task 143, warnings were silently dropped on the failure path.
    This tests the full display pipeline — not just the data model.
    """

    def test_failed_workflow_shows_parser_warning_in_error_output(self, tmp_path: Path) -> None:
        """A workflow that fails must show parser warnings alongside the error.

        Scenario: parent workflow has a parser typo AND calls a child that
        fails due to a missing required input. The error output must show
        both the error AND the parser warning.
        """
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\n"
            "## Inputs\n\n"
            "### required_value\n\n"
            "A required input.\n\n"
            "- type: string\n"
            "- required: true\n\n"
            "## Steps\n\n"
            "### use-it\n\n"
            "Use the input.\n\n"
            "- type: shell\n"
            "- cache: false\n"
            "- command: echo ${required_value}\n",
            encoding="utf-8",
        )

        parent = tmp_path / "parent.pflow.md"
        parent.write_text(
            "# Parent\n\n"
            "## Input\n\n"  # typo — parser warning
            "### unused\n\n"
            "Not used.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### call-child\n\n"
            "Run the child without providing required_value.\n\n"
            f"- type: workflow\n"
            f"- workflow: {child}\n",
            encoding="utf-8",
        )

        result = invoke_cli([str(parent)])

        assert result.exit_code != 0, "Workflow should fail (missing required input)"
        # Error must be present
        assert "failed" in result.stderr.lower() or "error" in result.stderr.lower(), (
            f"Expected error in output.\nstderr: {result.stderr}"
        )
        # Parser warning must ALSO be present — this is the regression guard
        assert "Warning" in result.stderr, f"Expected warnings section in failure output.\nstderr: {result.stderr}"


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
