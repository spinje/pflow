"""End-to-end tests for Task 3: Execute a Hardcoded 'Hello World' Workflow."""

import json
from pathlib import Path

from click.testing import CliRunner

from pflow.cli.main import main
from pflow.registry import Registry, scan_for_nodes


def test_hello_workflow_execution(tmp_path):
    """Test executing a simple read-file => write-file workflow."""
    runner = CliRunner()

    # Ensure registry exists for tests
    registry = Registry()
    if not registry.registry_path.exists():
        # Populate registry for tests
        src_path = Path(__file__).parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

    with runner.isolated_filesystem():
        # Create input file
        with open("input.txt", "w") as f:
            f.write("Hello\nWorld")

        # Create workflow JSON
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
                {"id": "write", "type": "write-file", "params": {"file_path": "output.txt"}},
            ],
            "edges": [{"from": "read", "to": "write"}],
        }

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run CLI
        result = runner.invoke(main, ["--file", "workflow.json"])

        # Verify success
        assert result.exit_code == 0
        assert "Workflow executed successfully" in result.output

        # Verify output file
        assert Path("output.txt").exists()
        content = Path("output.txt").read_text()
        # Remember: ReadFileNode adds line numbers!
        assert "1: Hello" in content
        assert "2: World" in content


def test_missing_registry_error(tmp_path, monkeypatch):
    """Test helpful error when registry is missing."""
    runner = CliRunner()

    with runner.isolated_filesystem():
        # Create a workflow file
        workflow = {"ir_version": "0.1.0", "nodes": [{"id": "test", "type": "test", "params": {}}], "edges": []}

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Mock registry to not exist
        def mock_exists(self):
            return False

        monkeypatch.setattr(Path, "exists", mock_exists)

        # Run CLI
        result = runner.invoke(main, ["--file", "workflow.json"])

        # Verify error
        assert result.exit_code == 1
        assert "Node registry not found" in result.output
        assert "python scripts/populate_registry.py" in result.output


def test_invalid_workflow_json(tmp_path):
    """Test error handling for invalid workflow JSON."""
    runner = CliRunner()

    # Ensure registry exists
    registry = Registry()
    if not registry.registry_path.exists():
        src_path = Path(__file__).parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

    with runner.isolated_filesystem():
        # Create invalid workflow (missing ir_version)
        workflow = {"nodes": [{"id": "test", "type": "test"}], "edges": []}

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run CLI
        result = runner.invoke(main, ["--file", "workflow.json"])

        # Should be treated as non-workflow JSON (missing ir_version)
        assert result.exit_code == 0
        assert "Collected workflow from file:" in result.output


def test_invalid_workflow_validation(tmp_path):
    """Test error handling for workflow that fails validation."""
    runner = CliRunner()

    # Ensure registry exists
    registry = Registry()
    if not registry.registry_path.exists():
        src_path = Path(__file__).parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

    with runner.isolated_filesystem():
        # Create workflow with invalid structure (empty nodes array)
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [],  # Invalid - must have at least one node
            "edges": [],
        }

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run CLI
        result = runner.invoke(main, ["--file", "workflow.json"])

        # Verify validation error
        assert result.exit_code == 1
        assert "Invalid workflow" in result.output


def test_plain_text_file_handling(tmp_path):
    """Test that plain text files are handled correctly (not executed)."""
    runner = CliRunner()

    with runner.isolated_filesystem():
        # Create plain text file
        with open("natural.txt", "w") as f:
            f.write("read the file and summarize it")

        # Run CLI
        result = runner.invoke(main, ["--file", "natural.txt"])

        # Should collect as text, not try to execute
        assert result.exit_code == 0
        assert "Collected workflow from file: read the file and summarize it" in result.output
        assert "Workflow executed successfully" not in result.output
