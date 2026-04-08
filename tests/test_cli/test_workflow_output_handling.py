"""Tests for workflow output handling in the CLI.

This module contains comprehensive tests for verifying that workflow output
handling works correctly with declared outputs, backward compatibility,
and various edge cases.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import click.testing
import pytest

from pflow.cli.main import main
from pflow.core.node import BaseNode
from tests.shared.markdown_utils import ir_to_markdown


class MockOutputNode(BaseNode):
    """Mock node that outputs data to the shared store."""

    def __init__(self):
        self.params = {}

    def set_params(self, params):
        self.params = params

    def run(self, shared):
        """Put test data in the shared store based on params."""
        # Default behavior - put data in test_output
        if "output_key" in self.params:
            shared[self.params["output_key"]] = self.params.get("output_value", "test value")
        else:
            shared["test_output"] = "default test output"

        # If specific keys are requested, add them
        if "add_keys" in self.params:
            for key, value in self.params["add_keys"].items():
                shared[key] = value

        return "success"


@pytest.fixture
def mock_registry():
    """Create a mock registry with test nodes."""
    mock_reg = Mock()

    nodes_data = {
        "test-node": {
            "module": "tests.test_cli.test_workflow_output_handling",
            "class_name": "MockOutputNode",
            "metadata": {"interface": {"inputs": [], "outputs": []}},
        }
    }

    mock_reg.load.return_value = nodes_data
    # Create a mock path object instead of using a real Path
    mock_path = Mock()
    mock_path.exists.return_value = True
    mock_reg.registry_path = mock_path

    def get_nodes_metadata_mock(node_types):
        result = {}
        for node_type in node_types:
            if node_type in nodes_data:
                metadata = nodes_data[node_type].get("metadata", {})
                result[node_type] = {
                    "module": nodes_data[node_type]["module"],
                    "class_name": nodes_data[node_type]["class_name"],
                    "interface": metadata.get("interface", {}),
                }
        return result

    mock_reg.get_nodes_metadata = Mock(side_effect=get_nodes_metadata_mock)

    return mock_reg


@pytest.fixture
def mock_compile():
    """Mock the workflow execution to bypass validation."""
    # Patch at the Runner level to bypass all resolution/validation/compilation
    with patch("pflow.execution.runner.WorkflowRunner.run") as mock_run:
        shared_data = {"last_ir": None}

        def run_mock(workflow, params, config, **kwargs):
            # Store the IR for reference
            shared_data["last_ir"] = workflow
            workflow_ir = workflow.ir if hasattr(workflow, "ir") else workflow

            # Create result with our test node's output
            shared_storage = {}

            # Create and run our test node
            node = MockOutputNode()
            # Extract params from the IR if available
            if isinstance(workflow_ir, dict):
                node_params = workflow_ir.get("nodes", [{}])[0].get("params", {})
                node.set_params(node_params)
            node.run(shared_storage)

            # Create a successful result
            from pflow.execution.result import ExecutionResult

            return ExecutionResult(success=True, diagnostics=[], shared_after=shared_storage)

        mock_run.side_effect = run_mock
        yield mock_run


@pytest.fixture
def mock_validate_ir():
    """Mock IR validation to always pass."""
    with patch("pflow.core.workflow.validator.WorkflowValidator.validate") as mock:
        # Return (errors=[], warnings=[]) to indicate validation passed
        mock.return_value = ([], [])
        yield mock


@pytest.fixture
def mock_registry_instance(mock_registry):
    """Mock the Registry class instantiation."""
    # Patch Registry at the source module
    with patch("pflow.registry.Registry") as MockRegistry:
        MockRegistry.return_value = mock_registry
        yield MockRegistry


class TestWorkflowOutputHandling:
    """Test workflow output handling functionality."""

    def test_workflow_with_declared_outputs(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that workflow-declared outputs are printed."""
        runner = click.testing.CliRunner()

        # Create a workflow with declared outputs
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"analysis_result": {"description": "The analysis output", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "analysis_result", "output_value": "Analysis complete: All tests passed"},
                }
            ],
        }

        # Save workflow to a temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Run the workflow (--file flag removed in Task 22)
            result = runner.invoke(main, [workflow_file])

            # Verify the declared output was printed
            assert result.exit_code == 0
            assert "Analysis complete: All tests passed" in result.output
            # Should NOT print the default success message
            assert "Workflow executed successfully" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_backward_compatibility_without_declared_outputs(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Test that workflows without declared outputs still work with hardcoded keys."""
        runner = click.testing.CliRunner()

        # Create a workflow WITHOUT declared outputs
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"add_keys": {"response": "This is the response", "some_other_key": "ignored"}},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            # Should fall back to hardcoded keys and find "response"
            assert result.exit_code == 0
            assert "This is the response" in result.output
            assert "Workflow executed successfully" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_workflow_data_goes_to_stdout_not_stderr_gh194(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Regression for GH #194: workflow data must go to stdout, not stderr."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"result": {"description": "Test result", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "output_key": "result",
                        "output_value": "HELLO_STDOUT_CANARY_GH194",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0, (
                f"Workflow invocation failed.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )
            assert "HELLO_STDOUT_CANARY_GH194" in result.stdout
            assert "HELLO_STDOUT_CANARY_GH194" not in result.stderr
            assert "Workflow output" in result.stderr
        finally:
            Path(workflow_file).unlink()

    # NOTE: `test_print_mode_suppresses_progress_header_and_summary` and
    # `test_json_mode_suppresses_progress_header_and_summary` were deleted
    # as test theater — both used the `mock_compile` fixture which returns
    # `ExecutionResult(metrics=None)`, and `_emit_summary_or_only_indicator`
    # short-circuits on `if not metrics_collector: return`. The stderr
    # suppression assertions were therefore vacuous — they passed regardless
    # of whether `-p`/JSON mode suppression actually worked.
    #
    # Real coverage lives in `tests/test_cli/test_progress_streaming_subprocess.py`:
    #   - `test_print_mode_without_only_stays_silent` (real subprocess, `-p`)
    #   - `test_print_mode_with_only_emits_indicator` (real subprocess, `-p` + `--only`)
    #   - `test_json_mode_keeps_stderr_silent` (real subprocess, JSON mode)

    def test_output_key_override(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that --output-key flag overrides both declared outputs and hardcoded keys."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"declared_output": {"description": "This should be ignored", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "declared_output": "Declared value",
                            "response": "Response value",
                            "custom_key": "Custom value",
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Use --output-key to override and get custom_key
            result = runner.invoke(main, ["--output-key", "custom_key", workflow_file])

            assert result.exit_code == 0
            assert "Custom value" in result.output
            # Should NOT print declared or hardcoded outputs
            assert "Declared value" not in result.output
            assert "Response value" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_missing_declared_outputs_warning_in_verbose_mode(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Test that verbose mode warns when declared outputs aren't in shared store."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "expected_output": {"description": "This output is expected but missing", "type": "string"},
                "another_output": {"description": "Also missing", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        # Node doesn't produce the declared outputs
                        "output_key": "different_key",
                        "output_value": "Some value",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--verbose", workflow_file])

            assert result.exit_code == 0
            # Should warn about missing declared outputs
            assert "expected_output, another_output" in result.output
            assert "but none could be resolved" in result.output
            # Should show success message since no output was produced
            assert "Workflow executed successfully" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_multiple_declared_outputs_first_matching(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that first matching declared output is printed when multiple are declared."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "primary_output": {"description": "Primary output", "type": "string"},
                "secondary_output": {"description": "Secondary output", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            # Only secondary is present
                            "secondary_output": "Secondary value"
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            # Should print the first available declared output
            assert "Secondary value" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_verbose_mode_shows_output_descriptions(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that verbose mode shows descriptions for declared outputs."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"final_result": {"description": "The final processed result", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "final_result", "output_value": "Processing complete"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--verbose", workflow_file])

            assert result.exit_code == 0
            # Should show the output description in the header
            assert "Workflow output (The final processed result):" in result.output
            # And the actual output
            assert "Processing complete" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_fallback_key_priority_order(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that fallback keys are checked in the correct order."""
        runner = click.testing.CliRunner()

        # Test the priority: result > response > output > text > data > stdout
        test_cases = [
            # (keys_to_add, expected_output)
            ({"text": "Text value", "result": "Result value"}, "Result value"),
            ({"text": "Text value"}, "Text value"),
            ({"result": "Result value", "output": "Output value"}, "Result value"),
            (
                {"response": "Response value", "output": "Output value", "result": "Result", "text": "Text"},
                "Result",
            ),
        ]

        for keys_to_add, expected_output in test_cases:
            workflow = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "test", "type": "test-node", "params": {"add_keys": keys_to_add}}],
            }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
                f.write(ir_to_markdown(workflow))
                workflow_file = f.name

            try:
                result = runner.invoke(main, [workflow_file])

                assert result.exit_code == 0
                assert expected_output in result.output
            finally:
                Path(workflow_file).unlink()

    def test_no_output_shows_success_message(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that workflows with no output show success message."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        # Node writes to _-prefixed key, filtered by auto-detection
                        "output_key": "_internal_key",
                        "output_value": "Internal value",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            # Should show success message when no output is produced
            assert "Workflow executed successfully" in result.output
            # Should not show the internal value
            assert "Internal value" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_output_key_not_found_warning(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test warning when specified --output-key is not found."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "actual_key", "output_value": "Actual value"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-key", "nonexistent_key", workflow_file])

            assert result.exit_code == 0
            # Should warn about missing key
            assert "Warning - output key 'nonexistent_key' not found in shared store" in result.output
            # Should still show success message
            assert "Workflow executed successfully" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_declared_outputs_override_hardcoded_keys(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that declared outputs take precedence over hardcoded fallback keys."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"custom_output": {"description": "Custom output that should be used", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "response": "This is response (fallback)",
                            "custom_output": "This is custom output (declared)",
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            # Should use declared output, not fallback
            assert "This is custom output (declared)" in result.output
            assert "This is response (fallback)" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_empty_outputs_declaration_falls_back(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that empty outputs declaration falls back to hardcoded keys."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {},  # Empty outputs declaration
            "nodes": [{"id": "test", "type": "test-node", "params": {"add_keys": {"response": "Fallback response"}}}],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            # Should fall back to hardcoded keys
            assert "Fallback response" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_complex_output_types(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that various output types are emitted as valid JSON on stdout.

        After the GH #194 fix, `safe_output` JSON-encodes non-string values
        so that `pflow foo | jq` works for dict/list/bool/number/null outputs.
        Strings still pass through verbatim.

        Round-trips each emitted value through ``json.loads`` to verify
        the stdout is *parseable JSON*, not just substring-matchable. This
        catches subtle regressions like trailing whitespace, prefix/suffix
        corruption, or any other byte the substring check would miss.
        """
        runner = click.testing.CliRunner()

        # Each entry: (declared output dict, the Python value we expect
        # to round-trip back from json.loads(stdout)). Strings are tested
        # separately because they pass through verbatim and aren't JSON.
        test_cases: list[tuple[dict, object]] = [
            ({"dict_output": {"key": "value", "nested": {"data": 123}}}, {"key": "value", "nested": {"data": 123}}),
            ({"list_output": ["item1", "item2", "item3"]}, ["item1", "item2", "item3"]),
            ({"number_output": 42.5}, 42.5),
            ({"bool_output": True}, True),
            ({"null_output": None}, None),
        ]

        for output_data, expected_value in test_cases:
            output_key = next(iter(output_data.keys()))
            workflow = {
                "ir_version": "0.1.0",
                "outputs": {output_key: {"description": f"Testing {output_key}", "type": "any"}},
                "nodes": [{"id": "test", "type": "test-node", "params": {"add_keys": output_data}}],
            }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
                f.write(ir_to_markdown(workflow))
                workflow_file = f.name

            try:
                result = runner.invoke(main, [workflow_file])

                assert result.exit_code == 0, f"exit={result.exit_code} for {output_key}\nstderr: {result.stderr!r}"

                # Round-trip-parse the stdout to prove it's valid JSON.
                # Strip whitespace because click.echo adds a trailing newline.
                stdout_stripped = result.stdout.strip()
                try:
                    parsed = json.loads(stdout_stripped)
                except json.JSONDecodeError as e:
                    raise AssertionError(
                        f"stdout for {output_key} (value={output_data[output_key]!r}) "
                        f"is not parseable JSON: {e}\nstdout: {result.stdout!r}"
                    ) from e

                assert parsed == expected_value, (
                    f"Round-trip mismatch for {output_key}: "
                    f"expected {expected_value!r}, got {parsed!r}\nstdout: {result.stdout!r}"
                )
            finally:
                Path(workflow_file).unlink()

    # New tests for --output-format flag functionality

    def test_json_format_single_declared_output(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that JSON format correctly returns a single declared output."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"summary": {"description": "Processing summary", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "summary", "output_value": "Task completed successfully"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            # Parse the JSON output - it's now wrapped in a result structure
            output_data = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            assert actual_result == {"summary": "Task completed successfully"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_multiple_declared_outputs(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that JSON format includes ALL declared outputs."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "summary": {"description": "Summary", "type": "string"},
                "count": {"description": "Count", "type": "number"},
                "tags": {"description": "Tags", "type": "array"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "summary": "Analysis complete",
                            "count": 42,
                            "tags": ["important", "reviewed", "approved"],
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            # Parse the JSON output - it's now wrapped in a result structure
            output_data = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should include ALL declared outputs
            assert actual_result == {
                "summary": "Analysis complete",
                "count": 42,
                "tags": ["important", "reviewed", "approved"],
            }
        finally:
            Path(workflow_file).unlink()

    def test_json_format_with_output_key(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that --output-key works with JSON format."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "primary": {"description": "Primary output", "type": "string"},
                "secondary": {"description": "Secondary output", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "primary": "Primary value",
                            "secondary": "Secondary value",
                            "custom_key": "Custom value",
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Request specific key with JSON format
            result = runner.invoke(main, ["--output-format", "json", "--output-key", "custom_key", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should only return the requested key
            assert actual_result == {"custom_key": "Custom value"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_empty_result(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that no matching outputs returns empty JSON object."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"expected_output": {"description": "Expected but not found", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        # Node doesn't produce the expected output
                        "output_key": "different_key",
                        "output_value": "Some value",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should return empty JSON object
            assert actual_result == {}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_fallback_keys(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that JSON format uses hardcoded fallback keys when no outputs declared."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            # No outputs declared
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {"response": "Fallback response value", "other_key": "Should not be included"}
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should return first matching fallback key
            assert actual_result == {"response": "Fallback response value"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_complex_types(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that JSON format handles arrays, objects, numbers, booleans correctly."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "metadata": {"description": "Metadata object", "type": "object"},
                "items": {"description": "Item list", "type": "array"},
                "score": {"description": "Score", "type": "number"},
                "is_valid": {"description": "Validity flag", "type": "boolean"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "metadata": {
                                "author": "Test User",
                                "created": "2024-01-01",
                                "nested": {"level": 2, "data": [1, 2, 3]},
                            },
                            "items": ["apple", "banana", {"type": "orange", "count": 5}],
                            "score": 98.5,
                            "is_valid": True,
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)

            # Verify all complex types are preserved correctly
            assert actual_result["metadata"]["author"] == "Test User"
            assert actual_result["metadata"]["nested"]["data"] == [1, 2, 3]
            assert actual_result["items"][2]["type"] == "orange"
            assert actual_result["score"] == 98.5
            assert actual_result["is_valid"] is True
        finally:
            Path(workflow_file).unlink()

    def test_text_format_unchanged(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that text format (default) still works as before."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"message": {"description": "Output message", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "message", "output_value": "Plain text output"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Test with explicit --output-format text
            result = runner.invoke(main, ["--output-format", "text", workflow_file])
            assert result.exit_code == 0
            assert "Plain text output" in result.output

            # Test without format flag (default)
            result = runner.invoke(main, [workflow_file])
            assert result.exit_code == 0
            assert "Plain text output" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_format_case_insensitive(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that output format is case-insensitive."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"data": {"description": "Test data", "type": "string"}},
            "nodes": [
                {"id": "test", "type": "test-node", "params": {"output_key": "data", "output_value": "Test value"}}
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Test "JSON" (uppercase)
            result = runner.invoke(main, ["--output-format", "JSON", workflow_file])
            assert result.exit_code == 0
            output_data = json.loads(result.output)
            actual_result = output_data.get("result", output_data)
            assert actual_result == {"data": "Test value"}

            # Test "Json" (mixed case)
            result = runner.invoke(main, ["--output-format", "Json", workflow_file])
            assert result.exit_code == 0
            output_data = json.loads(result.output)
            actual_result = output_data.get("result", output_data)
            assert actual_result == {"data": "Test value"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_with_verbose(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that verbose warnings don't break JSON output."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "expected": {"description": "Expected output", "type": "string"},
                "missing": {"description": "Missing output", "type": "string"},
            },
            "nodes": [
                {"id": "test", "type": "test-node", "params": {"output_key": "expected", "output_value": "Found value"}}
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--verbose", "--output-format", "json", workflow_file])

            assert result.exit_code == 0

            # The output should contain valid JSON, possibly with verbose messages
            # Try to parse the whole output first
            try:
                # If it's pure JSON, this will work
                json_output = json.loads(result.output)
            except json.JSONDecodeError:
                # If there are verbose messages mixed in, try to find JSON in the output
                # Look for JSON-like structure (including nested objects)
                import re

                json_match = re.search(r"\{.*\}", result.output, re.DOTALL)
                if json_match:
                    json_output = json.loads(json_match.group())
                else:
                    # If still not found, fail with helpful message
                    raise AssertionError(f"Could not find valid JSON in output:\n{result.output}") from None

            # Extract the actual result from the wrapper
            actual_result = json_output.get("result", json_output)
            assert actual_result == {"expected": "Found value"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_binary_data(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that binary data is handled gracefully in JSON format."""
        runner = click.testing.CliRunner()

        # Create a mock binary data
        binary_data = b"\x00\x01\x02\x03\xff\xfe\xfd"

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"binary_output": {"description": "Binary data", "type": "any"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "binary_output": binary_data.decode("latin-1")  # Store as latin-1 string
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            # Should handle binary data without crashing
            output_data = json.loads(result.output)
            actual_result = output_data.get("result", output_data)
            assert "binary_output" in actual_result
        finally:
            Path(workflow_file).unlink()

    def test_json_format_null_values(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that null/None values are handled correctly in JSON format."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "nullable": {"description": "Nullable field", "type": "any"},
                "present": {"description": "Present field", "type": "string"},
            },
            "nodes": [
                {"id": "test", "type": "test-node", "params": {"add_keys": {"nullable": None, "present": "value"}}}
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Both fields should be present
            assert "nullable" in actual_result
            assert actual_result["nullable"] is None
            assert actual_result["present"] == "value"
        finally:
            Path(workflow_file).unlink()

    def test_json_format_missing_declared_outputs_partial(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test JSON format when some declared outputs are missing."""
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "found1": {"description": "Found output 1", "type": "string"},
                "missing": {"description": "Missing output", "type": "string"},
                "found2": {"description": "Found output 2", "type": "number"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "found1": "Value 1",
                            "found2": 42,
                            # "missing" is not provided
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should only include found outputs
            assert actual_result == {"found1": "Value 1", "found2": 42}
            assert "missing" not in actual_result
        finally:
            Path(workflow_file).unlink()
