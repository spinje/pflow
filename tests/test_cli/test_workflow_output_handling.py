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

from pflow.cli import main


class MockOutputNode:
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
    """Mock the compile_ir_to_flow function."""
    with patch("pflow.cli.main.compile_ir_to_flow") as mock:
        # Create a mock flow that executes our test node
        mock_flow = Mock()

        def run_flow(shared_storage):
            # Create and run our test node
            node = MockOutputNode()
            # Extract params from the IR if available
            if hasattr(mock, "_last_ir"):
                node_params = mock._last_ir.get("nodes", [{}])[0].get("params", {})
                node.set_params(node_params)
            node.run(shared_storage)
            return "success"

        mock_flow.run = run_flow

        # Store IR for params extraction
        def compile_with_ir(ir_data, registry, initial_params=None):
            mock._last_ir = ir_data
            return mock_flow

        mock.side_effect = compile_with_ir
        yield mock


@pytest.fixture
def mock_validate_ir():
    """Mock IR validation to always pass."""
    with patch("pflow.cli.main.validate_ir") as mock:
        mock.return_value = None
        yield mock


@pytest.fixture
def mock_registry_instance(mock_registry):
    """Mock the Registry class instantiation."""
    with patch("pflow.cli.main.Registry") as MockRegistry:
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            # Run the workflow
            result = runner.invoke(main, ["--file", workflow_file])

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file])

            # Should fall back to hardcoded keys and find "response"
            assert result.exit_code == 0
            assert "This is the response" in result.output
            assert "Workflow executed successfully" not in result.output
        finally:
            Path(workflow_file).unlink()

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            # Use --output-key to override and get custom_key
            result = runner.invoke(main, ["--file", workflow_file, "--output-key", "custom_key"])

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--verbose", "--file", workflow_file])

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file])

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--verbose", "--file", workflow_file])

            assert result.exit_code == 0
            # Should show the output description in verbose mode
            assert "Output 'final_result': The final processed result" in result.output
            # And the actual output
            assert "Processing complete" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_fallback_key_priority_order(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that fallback keys are checked in the correct order."""
        runner = click.testing.CliRunner()

        # Test the priority: response > output > result > text
        test_cases = [
            # (keys_to_add, expected_output)
            ({"text": "Text value", "result": "Result value"}, "Result value"),
            ({"text": "Text value"}, "Text value"),
            ({"result": "Result value", "output": "Output value"}, "Output value"),
            (
                {"response": "Response value", "output": "Output value", "result": "Result", "text": "Text"},
                "Response value",
            ),
        ]

        for keys_to_add, expected_output in test_cases:
            workflow = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "test", "type": "test-node", "params": {"add_keys": keys_to_add}}],
            }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(workflow, f)
                workflow_file = f.name

            try:
                result = runner.invoke(main, ["--file", workflow_file])

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
                        # Node doesn't produce any of the expected keys
                        "output_key": "internal_key",
                        "output_value": "Internal value",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file])

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-key", "nonexistent_key"])

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file])

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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file])

            assert result.exit_code == 0
            # Should fall back to hardcoded keys
            assert "Fallback response" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_complex_output_types(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that various output types are handled correctly."""
        runner = click.testing.CliRunner()

        # Test different data types
        test_cases = [
            {"dict_output": {"key": "value", "nested": {"data": 123}}},
            {"list_output": ["item1", "item2", "item3"]},
            {"number_output": 42.5},
            {"bool_output": True},
            {"null_output": None},
        ]

        for output_data in test_cases:
            output_key = next(iter(output_data.keys()))
            workflow = {
                "ir_version": "0.1.0",
                "outputs": {output_key: {"description": f"Testing {output_key}", "type": "any"}},
                "nodes": [{"id": "test", "type": "test-node", "params": {"add_keys": output_data}}],
            }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(workflow, f)
                workflow_file = f.name

            try:
                result = runner.invoke(main, ["--file", workflow_file])

                assert result.exit_code == 0
                # Output should be in the result (formatted as string/JSON)
                output_value = output_data[output_key]
                if output_value is not None:
                    if isinstance(output_value, (dict, list)):
                        # JSON output should be present
                        assert json.dumps(output_value) in result.output or str(output_value) in result.output
                    else:
                        assert str(output_value) in result.output
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0
            # Parse the JSON output
            output_data = json.loads(result.output)
            assert output_data == {"summary": "Task completed successfully"}
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0
            # Parse the JSON output
            output_data = json.loads(result.output)
            # Should include ALL declared outputs
            assert output_data == {
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            # Request specific key with JSON format
            result = runner.invoke(
                main, ["--file", workflow_file, "--output-format", "json", "--output-key", "custom_key"]
            )

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Should only return the requested key
            assert output_data == {"custom_key": "Custom value"}
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Should return empty JSON object
            assert output_data == {}
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Should return first matching fallback key
            assert output_data == {"response": "Fallback response value"}
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0
            output_data = json.loads(result.output)

            # Verify all complex types are preserved correctly
            assert output_data["metadata"]["author"] == "Test User"
            assert output_data["metadata"]["nested"]["data"] == [1, 2, 3]
            assert output_data["items"][2]["type"] == "orange"
            assert output_data["score"] == 98.5
            assert output_data["is_valid"] is True
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            # Test with explicit --output-format text
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "text"])
            assert result.exit_code == 0
            assert "Plain text output" in result.output

            # Test without format flag (default)
            result = runner.invoke(main, ["--file", workflow_file])
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            # Test "JSON" (uppercase)
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "JSON"])
            assert result.exit_code == 0
            output_data = json.loads(result.output)
            assert output_data == {"data": "Test value"}

            # Test "Json" (mixed case)
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "Json"])
            assert result.exit_code == 0
            output_data = json.loads(result.output)
            assert output_data == {"data": "Test value"}
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--verbose", "--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0

            # The output should contain valid JSON, possibly with verbose messages
            # Try to parse the whole output first
            try:
                # If it's pure JSON, this will work
                json_output = json.loads(result.output)
            except json.JSONDecodeError:
                # If there are verbose messages mixed in, try to find JSON in the output
                # Look for JSON-like structure
                import re

                json_match = re.search(r"\{[^}]*\}", result.output)
                if json_match:
                    json_output = json.loads(json_match.group())
                else:
                    # If still not found, fail with helpful message
                    raise AssertionError(f"Could not find valid JSON in output:\n{result.output}") from None

            assert json_output == {"expected": "Found value"}
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0
            # Should handle binary data without crashing
            output_data = json.loads(result.output)
            assert "binary_output" in output_data
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Both fields should be present
            assert "nullable" in output_data
            assert output_data["nullable"] is None
            assert output_data["present"] == "value"
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--file", workflow_file, "--output-format", "json"])

            assert result.exit_code == 0
            output_data = json.loads(result.output)
            # Should only include found outputs
            assert output_data == {"found1": "Value 1", "found2": 42}
            assert "missing" not in output_data
        finally:
            Path(workflow_file).unlink()
