"""End-to-end tests for Task 3: Execute a Hardcoded 'Hello World' Workflow."""

import json
import os
import platform
from pathlib import Path

from click.testing import CliRunner

from pflow.cli.main import main
from tests.shared.registry_utils import ensure_test_registry


def test_hello_workflow_execution(tmp_path):
    """Test executing a simple read-file => write-file workflow."""
    runner = CliRunner()

    # Ensure registry exists BEFORE entering isolated filesystem
    ensure_test_registry()

    with runner.isolated_filesystem():
        # Create input file
        with open("input.txt", "w") as f:
            f.write("Hello\nWorld")

        # Create workflow JSON with namespacing support
        # With namespacing enabled by default, we need to explicitly connect nodes
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
                {
                    "id": "write",
                    "type": "write-file",
                    "params": {
                        "file_path": "output.txt",
                        "content": "${read.content}",  # Explicitly reference read node's output
                    },
                },
            ],
            "edges": [{"from": "read", "to": "write"}],
        }

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run CLI
        result = runner.invoke(main, ["--file", "workflow.json"])

        # Print output for debugging
        if result.exit_code != 0:
            print(f"CLI Output:\n{result.output}")
            print(f"Exception:\n{result.exception}")

        # Verify success
        assert result.exit_code == 0
        assert "Workflow executed successfully" in result.output

        # Verify output file
        assert Path("output.txt").exists()
        content = Path("output.txt").read_text()
        # IMPORTANT: ReadFileNode adds line numbers to content as part of its design
        # This is intentional behavior from the Tutorial-Cursor pattern to support
        # line-by-line processing in future nodes. The format is "N: content" where
        # N is the line number starting from 1.
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
    ensure_test_registry()

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
    ensure_test_registry()

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


def test_node_execution_failure(tmp_path):
    """Test error handling when a node fails during execution."""
    runner = CliRunner()

    # Ensure registry exists
    ensure_test_registry()

    with runner.isolated_filesystem():
        # Create workflow that will fail (missing input file)
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file_path": "nonexistent.txt"}},
            ],
            "edges": [],
        }

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run CLI
        result = runner.invoke(main, ["--file", "workflow.json"])

        # Should report failure
        assert result.exit_code == 1
        assert "Workflow execution failed - Node returned error action" in result.output
        assert "Check node output above for details" in result.output
        # The node error details are logged, not printed to stdout in test environment


def test_verbose_execution_output(tmp_path):
    """Test verbose output during workflow execution."""
    runner = CliRunner()

    # Ensure registry exists
    ensure_test_registry()

    with runner.isolated_filesystem():
        # Create input file
        with open("input.txt", "w") as f:
            f.write("Test content")

        # Create simple workflow with explicit template variable connection
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
                {
                    "id": "write",
                    "type": "write-file",
                    "params": {
                        "file_path": "output.txt",
                        "content": "${read.content}",  # Explicit connection required with namespacing
                    },
                },
            ],
            "edges": [{"from": "read", "to": "write"}],
        }

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run CLI with verbose flag
        result = runner.invoke(main, ["--verbose", "--file", "workflow.json"])

        # Should show verbose execution info
        assert result.exit_code == 0
        assert "Starting workflow execution with 2 node(s)" in result.output
        assert "Workflow execution completed" in result.output
        assert "Workflow executed successfully" in result.output


def test_data_flows_between_nodes(tmp_path):
    """Test that data correctly flows from one node to another through template variables."""
    runner = CliRunner()

    # Ensure registry exists
    ensure_test_registry()

    with runner.isolated_filesystem():
        # Create input file with test data
        with open("input.txt", "w") as f:
            f.write("Test content\nSecond line")

        # Create workflow that passes data between nodes
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
                {
                    "id": "write",
                    "type": "write-file",
                    "params": {
                        "file_path": "output.txt",
                        "content": "${read.content}",  # Template variable references read node's output
                    },
                },
            ],
            "edges": [{"from": "read", "to": "write"}],
        }

        with open("workflow.json", "w") as f:
            json.dump(workflow, f)

        # Run the workflow
        result = runner.invoke(main, ["--file", "workflow.json"])

        # Verify success
        assert result.exit_code == 0
        assert "Workflow executed successfully" in result.output

        # Verify the data was correctly passed and written
        assert Path("output.txt").exists()
        content = Path("output.txt").read_text()
        # ReadFileNode adds line numbers to content
        assert "1: Test content" in content
        assert "2: Second line" in content


def test_permission_error_read(tmp_path):
    """Test error handling when file cannot be read due to permissions."""
    runner = CliRunner()

    # Ensure registry exists
    ensure_test_registry()

    with runner.isolated_filesystem():
        # Create a file and make it unreadable
        with open("protected.txt", "w") as f:
            f.write("Secret content")

        # Make file unreadable (Unix-like systems only)
        if platform.system() != "Windows":
            os.chmod("protected.txt", 0o000)

            # Create workflow that tries to read the protected file
            workflow = {
                "ir_version": "0.1.0",
                "nodes": [
                    {"id": "read", "type": "read-file", "params": {"file_path": "protected.txt"}},
                ],
                "edges": [],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            try:
                # Run CLI
                result = runner.invoke(main, ["--file", "workflow.json"])

                # Should report failure
                assert result.exit_code == 1
                assert "Workflow execution failed" in result.output
            finally:
                # Restore permissions for cleanup
                os.chmod("protected.txt", 0o644)
        else:
            # Skip test on Windows
            pass


def test_permission_error_write(tmp_path):
    """Test error handling when file cannot be written due to permissions."""
    runner = CliRunner()

    # Ensure registry exists
    ensure_test_registry()

    with runner.isolated_filesystem():
        # Create a read-only directory
        os.mkdir("readonly_dir")

        # Make directory read-only (Unix-like systems only)
        if platform.system() != "Windows":
            os.chmod("readonly_dir", 0o555)  # noqa: S103

            # Create workflow that tries to write to the protected directory
            workflow = {
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "write",
                        "type": "write-file",
                        "params": {"file_path": "readonly_dir/output.txt", "content": "Test"},
                    },
                ],
                "edges": [],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            try:
                # Run CLI
                result = runner.invoke(main, ["--file", "workflow.json"])

                # Should report failure
                assert result.exit_code == 1
                assert "Workflow execution failed" in result.output
            finally:
                # Restore permissions for cleanup
                os.chmod("readonly_dir", 0o755)  # noqa: S103
        else:
            # Skip test on Windows
            pass
