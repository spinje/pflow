"""End-to-end integration test for template variable system."""

import os
import tempfile

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


def test_template_system_with_file_nodes():
    """Test template variables working with real file nodes."""
    # Create test files
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create source file
        source_file = os.path.join(tmpdir, "input.txt")
        with open(source_file, "w") as f:
            f.write("Hello from template test!")

        # Create workflow with templates
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "reader", "type": "read-file", "params": {"file_path": "$input_file", "encoding": "$encoding"}},
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {"file_path": "$output_file", "content": "$content", "encoding": "utf-8"},
                },
            ],
            "edges": [{"from": "reader", "to": "writer"}],
        }

        # Initial parameters from "planner"
        initial_params = {
            "input_file": source_file,
            "output_file": os.path.join(tmpdir, "output.txt"),
            "encoding": "utf-8",
        }

        # Compile with template resolution
        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params=initial_params)

        # Run the workflow
        shared = {}
        flow.run(shared)

        # Verify output file was created with correct content
        assert os.path.exists(initial_params["output_file"])
        with open(initial_params["output_file"]) as f:
            content = f.read()
        # Read-file adds line numbers by default
        assert content == "1: Hello from template test!"


def test_template_with_path_traversal():
    """Test template variables with path traversal (dotted notation)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create workflow that uses path traversal
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": "$paths.output",
                        "content": "$data.message",
                        "encoding": "$config.encoding",
                    },
                }
            ],
            "edges": [],
        }

        # Complex initial parameters
        initial_params = {
            "paths": {"output": os.path.join(tmpdir, "nested_output.txt")},
            "data": {"message": "Nested template test!"},
            "config": {"encoding": "utf-8"},
        }

        # Compile and run
        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params=initial_params)
        shared = {}
        flow.run(shared)

        # Verify
        output_file = initial_params["paths"]["output"]
        assert os.path.exists(output_file)
        with open(output_file) as f:
            content = f.read()
        assert content == "Nested template test!"


def test_template_fallback_to_shared_store():
    """Test that templates can fall back to shared store values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Workflow that expects content from shared store
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": "$output_path",
                        "content": "$dynamic_content",  # This will come from shared store
                    },
                }
            ],
            "edges": [],
        }

        # Only provide output_path in initial params
        initial_params = {"output_path": os.path.join(tmpdir, "dynamic.txt")}

        # Compile (validation disabled since dynamic_content not in initial_params)
        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params=initial_params, validate=False)

        # Run with shared store containing the dynamic content
        shared = {"dynamic_content": "Content from shared store!"}
        flow.run(shared)

        # Verify
        assert os.path.exists(initial_params["output_path"])
        with open(initial_params["output_path"]) as f:
            content = f.read()
        assert content == "Content from shared store!"


def test_template_priority_initial_params_over_shared():
    """Test that initial_params have priority over shared store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {"file_path": os.path.join(tmpdir, "priority.txt"), "content": "$message"},
                }
            ],
            "edges": [],
        }

        # Both initial_params and shared have 'message'
        initial_params = {"message": "From initial params (should win)"}

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params=initial_params)

        # Shared store has different value
        shared = {"message": "From shared store (should lose)"}
        flow.run(shared)

        # Verify initial_params value was used
        with open(os.path.join(tmpdir, "priority.txt")) as f:
            content = f.read()
        assert content == "From initial params (should win)"


def test_workflow_reusability():
    """Test that same workflow can be reused with different parameters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Define reusable workflow
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {"file_path": "$output_file", "content": "User: $user_name, Task: $task_id"},
                }
            ],
            "edges": [],
        }

        registry = Registry()

        # First execution
        flow1 = compile_ir_to_flow(
            workflow_ir,
            registry,
            initial_params={
                "output_file": os.path.join(tmpdir, "user1.txt"),
                "user_name": "Alice",
                "task_id": "TASK-001",
            },
        )
        flow1.run({})

        # Second execution with different params
        flow2 = compile_ir_to_flow(
            workflow_ir,
            registry,
            initial_params={
                "output_file": os.path.join(tmpdir, "user2.txt"),
                "user_name": "Bob",
                "task_id": "TASK-002",
            },
        )
        flow2.run({})

        # Verify both files
        with open(os.path.join(tmpdir, "user1.txt")) as f:
            assert f.read() == "User: Alice, Task: TASK-001"

        with open(os.path.join(tmpdir, "user2.txt")) as f:
            assert f.read() == "User: Bob, Task: TASK-002"
