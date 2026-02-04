"""Integration tests for workflow outputs with source field (namespaced values).

These tests verify that users can:
1. Create workflows with outputs that have source fields
2. Run the workflow and get the expected output
3. Get JSON format output with all values

FIX HISTORY:
- 2025-02: Migrated from JSON to .pflow.md markdown format (Task 107)
"""

import json
import tempfile
from pathlib import Path

from click.testing import CliRunner

from pflow.cli.main import main as cli
from tests.shared.markdown_utils import write_workflow_file

# Note: Removed autouse fixture that was modifying user's registry.
# The global test isolation in tests/conftest.py now ensures tests use
# temporary registry paths, and nodes are auto-discovered as needed.


class TestWorkflowOutputsNamespaced:
    """Test workflow outputs with source field for accessing namespaced values."""

    def test_workflow_with_namespaced_output_works(self):
        """Test that a workflow with source field in output returns the correct value."""
        # Create a simple workflow with echo node and output with source
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "Hello from echo", "uppercase": True}}],
            "edges": [],
            "outputs": {
                "result": {
                    "description": "The echoed message",
                    "source": "echo1.echo",  # Access namespaced value
                }
            },
        }

        # Save workflow to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            workflow_file = f.name

        try:
            write_workflow_file(workflow_ir, Path(workflow_file))

            # Run the workflow
            runner = CliRunner()
            result = runner.invoke(cli, [workflow_file])

            # Verify execution succeeded
            assert result.exit_code == 0, f"Failed with output: {result.output}"

            # Verify the output contains the echoed message (uppercase)
            assert "HELLO FROM ECHO" in result.output
        finally:
            Path(workflow_file).unlink(missing_ok=True)

    def test_json_output_format_works(self):
        """Test that JSON output format returns the output values correctly."""
        # Create workflow with echo node
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "greeting",
                    "type": "echo",
                    "params": {"message": "Greetings", "prefix": ">>> ", "suffix": " <<<"},
                }
            ],
            "edges": [],
            "outputs": {"formatted_message": {"description": "Formatted greeting", "source": "greeting.echo"}},
        }

        # Save workflow to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            workflow_file = f.name

        try:
            write_workflow_file(workflow_ir, Path(workflow_file))

            # Run with JSON output format
            runner = CliRunner()
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])

            # Verify execution succeeded
            assert result.exit_code == 0, f"Failed with output: {result.output}"

            # Parse JSON output
            output_json = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_json.get("result", output_json)

            # Verify the output contains the expected value
            assert "formatted_message" in actual_result
            # Note: Leading space in suffix " <<<" is lost during markdown parsing
            # because YAML treats "suffix: <<<" (with space after colon) as just "<<<"
            assert actual_result["formatted_message"] == ">>> Greetings<<<"
        finally:
            Path(workflow_file).unlink(missing_ok=True)

    def test_multiple_outputs(self):
        """Test workflow with multiple outputs from different nodes."""
        # Create workflow with multiple echo nodes
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "first", "type": "echo", "params": {"message": "First message", "count": 2}},
                {"id": "second", "type": "echo", "params": {"message": "Second message", "uppercase": True}},
                {"id": "third", "type": "echo", "params": {"message": "Third message", "prefix": "[INFO] "}},
            ],
            "edges": [{"from": "first", "to": "second"}, {"from": "second", "to": "third"}],
            "outputs": {
                "repeated": {"description": "First message repeated", "source": "first.echo"},
                "uppercase": {"description": "Second message in uppercase", "source": "second.echo"},
                "prefixed": {"description": "Third message with prefix", "source": "third.echo"},
            },
        }

        # Save workflow to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            workflow_file = f.name

        try:
            write_workflow_file(workflow_ir, Path(workflow_file))

            # Test 1: Text format returns first output
            runner = CliRunner()
            result = runner.invoke(cli, [workflow_file])

            assert result.exit_code == 0, f"Failed with output: {result.output}"
            # Should return the first output (repeated message)
            assert "First message First message" in result.output

            # Test 2: JSON format returns all outputs
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0, f"Failed with output: {result.output}"

            # Parse JSON and verify all outputs
            output_json = json.loads(result.output)
            # Extract the actual result from the wrapper
            actual_result = output_json.get("result", output_json)

            assert "repeated" in actual_result
            assert actual_result["repeated"] == "First message First message"

            assert "uppercase" in actual_result
            assert actual_result["uppercase"] == "SECOND MESSAGE"

            assert "prefixed" in actual_result
            assert actual_result["prefixed"] == "[INFO] Third message"

        finally:
            Path(workflow_file).unlink(missing_ok=True)
