"""End-to-end tests for Task 3: Execute a Hardcoded 'Hello World' Workflow."""

import json
import os
import platform
from pathlib import Path

from click.testing import CliRunner

import pocketflow
from pflow.cli.main import main
from pflow.registry import Registry, scan_for_nodes
from pflow.runtime import compile_ir_to_flow


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


def test_node_execution_failure(tmp_path):
    """Test error handling when a node fails during execution."""
    runner = CliRunner()

    # Ensure registry exists
    registry = Registry()
    if not registry.registry_path.exists():
        src_path = Path(__file__).parent.parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

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
    registry = Registry()
    if not registry.registry_path.exists():
        src_path = Path(__file__).parent.parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

    with runner.isolated_filesystem():
        # Create input file
        with open("input.txt", "w") as f:
            f.write("Test content")

        # Create simple workflow
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

        # Run CLI with verbose flag
        result = runner.invoke(main, ["--verbose", "--file", "workflow.json"])

        # Should show verbose execution info
        assert result.exit_code == 0
        assert "Starting workflow execution with 2 node(s)" in result.output
        assert "Workflow execution completed" in result.output
        assert "Workflow executed successfully" in result.output


def test_shared_store_verification(tmp_path):
    """Test that shared store properly passes data between nodes."""
    # Ensure registry exists
    registry = Registry()
    if not registry.registry_path.exists():
        src_path = Path(__file__).parent.parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

    # Change to temp directory
    os.chdir(tmp_path)

    # Create input file
    with open("input.txt", "w") as f:
        f.write("Test content\nSecond line")

    # Create workflow IR
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
            {"id": "write", "type": "write-file", "params": {"file_path": "output.txt"}},
        ],
        "edges": [{"from": "read", "to": "write"}],
    }

    # Compile and execute directly (not through CLI)
    flow = compile_ir_to_flow(workflow, registry)
    shared_storage = {}
    result = flow.run(shared_storage)

    # Verify shared store contents
    assert "content" in shared_storage, "ReadFileNode should put content in shared store"
    assert "1: Test content" in shared_storage["content"], "Content should have line numbers"
    assert "2: Second line" in shared_storage["content"], "All lines should be numbered"
    assert "written" in shared_storage, "WriteFileNode should mark success in shared store"
    assert "Successfully wrote to" in shared_storage["written"], "Written message should indicate success"

    # Verify the flow succeeded
    assert result == "default", "Flow should return default action on success"

    # Verify file was actually written
    assert Path("output.txt").exists()
    with open("output.txt") as f:
        content = f.read()
        assert "1: Test content" in content
        assert "2: Second line" in content


def test_node_execution_order(tmp_path):
    """Test that nodes execute in the order specified by edges."""

    # Create custom test nodes that track execution order
    class OrderTrackingNode(pocketflow.Node):
        """Node that records its execution order in shared store."""

        def __init__(self, node_id):
            super().__init__()
            self.node_id = node_id

        def prep(self, shared_storage):
            if "execution_order" not in shared_storage:
                shared_storage["execution_order"] = []
            shared_storage["execution_order"].append(f"{self.node_id}_prep")

        def exec(self, prep_res):
            return {"node_id": self.node_id}

        def post(self, shared_storage, prep_res, exec_res):
            shared_storage["execution_order"].append(f"{self.node_id}_post")
            return "default"

    # Create a flow with specific order: A -> B -> C
    flow = pocketflow.Flow()
    node_a = OrderTrackingNode("A")
    node_b = OrderTrackingNode("B")
    node_c = OrderTrackingNode("C")

    # Chain them together
    flow.start(node_a) >> node_b >> node_c

    # Execute and verify order
    shared_storage = {}
    result = flow.run(shared_storage)

    assert result == "default"
    assert "execution_order" in shared_storage
    expected_order = ["A_prep", "A_post", "B_prep", "B_post", "C_prep", "C_post"]
    assert shared_storage["execution_order"] == expected_order, (
        f"Expected {expected_order}, got {shared_storage['execution_order']}"
    )


def test_permission_error_read(tmp_path):
    """Test error handling when file cannot be read due to permissions."""
    runner = CliRunner()

    # Ensure registry exists
    registry = Registry()
    if not registry.registry_path.exists():
        src_path = Path(__file__).parent.parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

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
    registry = Registry()
    if not registry.registry_path.exists():
        src_path = Path(__file__).parent.parent.parent / "src"
        nodes_dir = src_path / "pflow" / "nodes"
        if nodes_dir.exists():
            scan_results = scan_for_nodes([nodes_dir])
            registry.update_from_scanner(scan_results)

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
