"""Integration tests for workflow outputs with source field (namespaced values).

These tests verify that users can:
1. Create workflows with outputs that have source fields
2. Run the workflow and get the expected output
3. Get JSON format output with all values
"""

import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.main import main as cli
from pflow.registry import Registry, scan_for_nodes


@pytest.fixture(autouse=True)
def ensure_echo_node_registered():
    """Ensure the echo node is registered in the registry.

    The echo node is in the test/ directory which is excluded from auto-discovery,
    so we need to manually register it for these tests.
    """
    registry = Registry()

    # Load current registry
    nodes = registry.load()

    # If echo node is not registered, add it
    if "echo" not in nodes:
        # Find the test nodes directory
        src_path = Path(__file__).parent.parent.parent / "src"
        test_nodes_dir = src_path / "pflow" / "nodes" / "test"

        if test_nodes_dir.exists():
            # Scan the test directory for nodes
            scan_results = scan_for_nodes([test_nodes_dir])

            # Update registry with test nodes
            if scan_results:
                registry.update_from_scanner(scan_results)


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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow_ir, f)
            workflow_file = f.name

        try:
            # Run the workflow
            runner = CliRunner()
            result = runner.invoke(cli, ["--file", workflow_file])

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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow_ir, f)
            workflow_file = f.name

        try:
            # Run with JSON output format
            runner = CliRunner()
            result = runner.invoke(cli, ["--output-format", "json", "--file", workflow_file])

            # Verify execution succeeded
            assert result.exit_code == 0, f"Failed with output: {result.output}"

            # Parse JSON output
            output_json = json.loads(result.output)

            # Verify the output contains the expected value
            assert "formatted_message" in output_json
            assert output_json["formatted_message"] == ">>> Greetings <<<"
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(workflow_ir, f)
            workflow_file = f.name

        try:
            # Test 1: Text format returns first output
            runner = CliRunner()
            result = runner.invoke(cli, ["--file", workflow_file])

            assert result.exit_code == 0, f"Failed with output: {result.output}"
            # Should return the first output (repeated message)
            assert "First message First message" in result.output

            # Test 2: JSON format returns all outputs
            result = runner.invoke(cli, ["--output-format", "json", "--file", workflow_file])

            assert result.exit_code == 0, f"Failed with output: {result.output}"

            # Parse JSON and verify all outputs
            output_json = json.loads(result.output)

            assert "repeated" in output_json
            assert output_json["repeated"] == "First message First message"

            assert "uppercase" in output_json
            assert output_json["uppercase"] == "SECOND MESSAGE"

            assert "prefixed" in output_json
            assert output_json["prefixed"] == "[INFO] Third message"

        finally:
            Path(workflow_file).unlink(missing_ok=True)
