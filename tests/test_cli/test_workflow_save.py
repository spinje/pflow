"""Tests for workflow save functionality in CLI."""

import json
from pathlib import Path

import click.testing
import pytest

from pflow.cli.main import main
from pflow.registry import Registry, scan_for_nodes


@pytest.fixture(autouse=True)
def ensure_write_file_node_registered() -> None:
    """Ensure the write-file node is registered in the registry.

    The tests use write-file node which needs to be available in the registry.
    This fixture ensures it's registered before running tests.
    """
    registry = Registry()

    # Load current registry
    nodes = registry.load()

    # If write-file node is not registered, add it
    if "write-file" not in nodes:
        # Find the file nodes directory
        src_path = Path(__file__).parent.parent.parent / "src"
        file_nodes_dir = src_path / "pflow" / "nodes" / "file"

        if file_nodes_dir.exists():
            # Scan the file directory for nodes
            scan_results = scan_for_nodes([file_nodes_dir])

            # Update registry with file nodes
            if scan_results:
                registry.update_from_scanner(scan_results)


class TestWorkflowSaveCLI:
    """Test suite for workflow save functionality in CLI context."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return click.testing.CliRunner()

    @pytest.fixture
    def sample_workflow(self, tmp_path):
        """Create a sample workflow IR."""
        output_file = tmp_path / "test_output.txt"
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": str(output_file),
                        "content": "Test content",
                    },
                }
            ],
            "edges": [],
            "start_node": "writer",
        }

    def test_save_prompt_not_shown_for_file_input(self, runner, sample_workflow, tmp_path):
        """Test that save prompt is not shown when workflow comes from file."""
        # Create a workflow file
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(sample_workflow))

        # Run with file input
        result = runner.invoke(main, ["--file", str(workflow_file)])

        assert result.exit_code == 0
        assert "Save this workflow?" not in result.output

    def test_save_prompt_not_shown_in_non_interactive_mode(self, runner, sample_workflow):
        """Test that save prompt is not shown in non-interactive mode (piped input)."""
        # Simulate non-interactive mode (stdin is not a TTY in tests)
        result = runner.invoke(main, [], input=json.dumps(sample_workflow))

        assert result.exit_code == 0
        assert "Save this workflow?" not in result.output

    def test_natural_language_workflow_placeholder(self, runner):
        """Test natural language workflow collection (before Task 17 implementation)."""
        # For now, workflows from args just show collection message
        # When Task 17 is implemented, this will process and save workflows
        result = runner.invoke(main, ["create", "a", "backup", "workflow"])

        assert result.exit_code == 0
        assert "Collected workflow from args: create a backup workflow" in result.output
        # Save prompt will be added when natural language planner is implemented
        assert "Save this workflow?" not in result.output

    def test_save_prompt_not_shown_after_execution_failure(self, runner):
        """Test that save prompt is not shown after execution failure."""
        # Create an invalid workflow that will fail
        invalid_workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "invalid",
                    "type": "non-existent-node",
                    "params": {},
                }
            ],
            "edges": [],
            "start_node": "invalid",
        }

        result = runner.invoke(main, [], input=json.dumps(invalid_workflow))

        assert result.exit_code == 1
        assert "Save this workflow?" not in result.output
        assert "cli: Compilation failed" in result.output
