"""End-to-end integration test for template variable system."""

import os
import tempfile
from typing import Any

from pflow.registry import Registry
from pflow.runtime import WorkflowEngine, compile_workflow


def _compile_and_run(
    workflow_ir: dict[str, Any],
    registry: Registry,
    shared: dict[str, Any],
    initial_params: dict[str, Any] | None = None,
) -> None:
    """Compile workflow and run via WorkflowEngine, seeding shared store."""
    workflow = compile_workflow(workflow_ir, registry, initial_params=initial_params)
    if initial_params:
        shared.update({k: v for k, v in initial_params.items() if not k.startswith("__")})
    shared.update(workflow.resolved_defaults)
    engine = WorkflowEngine()
    engine.run(workflow, shared)


def test_template_system_with_file_nodes():
    """Test template variables working with real file nodes."""
    # Create test files
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create source file
        source_file = os.path.join(tmpdir, "input.txt")
        with open(source_file, "w", encoding="utf-8") as f:
            f.write("Hello from template test!")

        # Create workflow with templates
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "input_file": {"type": "string", "description": "Source file path"},
                "output_file": {"type": "string", "description": "Destination file path"},
                "encoding": {"type": "string", "description": "File encoding"},
            },
            "nodes": [
                {
                    "id": "reader",
                    "type": "read-file",
                    "params": {"file_path": "${input_file}", "encoding": "${encoding}"},
                },
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {"file_path": "${output_file}", "content": "${reader.content}", "encoding": "utf-8"},
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
        shared: dict[str, Any] = {}
        _compile_and_run(workflow_ir, registry, shared, initial_params=initial_params)

        # Verify output file was created with correct content
        assert os.path.exists(initial_params["output_file"])
        with open(initial_params["output_file"], encoding="utf-8") as f:
            content = f.read()
        assert content == "Hello from template test!"


def test_template_with_path_traversal():
    """Test template variables with path traversal (dotted notation)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create workflow that uses path traversal
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "paths": {"type": "object", "description": "Path bundle", "required": True},
                "data": {"type": "object", "description": "Data bundle", "required": True},
                "config": {"type": "object", "description": "Config bundle", "required": True},
            },
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": "${paths.output}",
                        "content": "${data.message}",
                        "encoding": "${config.encoding}",
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
        shared: dict[str, Any] = {}
        _compile_and_run(workflow_ir, registry, shared, initial_params=initial_params)

        # Verify
        output_file = initial_params["paths"]["output"]
        assert os.path.exists(output_file)
        with open(output_file, encoding="utf-8") as f:
            content = f.read()
        assert content == "Nested template test!"


def test_template_fallback_to_shared_store():
    """Test that templates can fall back to shared store values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Workflow that expects content from shared store
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "output_path": {"type": "string", "description": "Output path", "required": True},
            },
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": "${output_path}",
                        "content": "${dynamic_content}",  # This will come from shared store
                    },
                }
            ],
            "edges": [],
        }

        # Only provide output_path in initial params
        initial_params = {"output_path": os.path.join(tmpdir, "dynamic.txt")}

        # Compile and run with shared store containing the dynamic content
        registry = Registry()
        shared: dict[str, Any] = {"dynamic_content": "Content from shared store!"}
        _compile_and_run(workflow_ir, registry, shared, initial_params=initial_params)

        # Verify
        assert os.path.exists(initial_params["output_path"])
        with open(initial_params["output_path"], encoding="utf-8") as f:
            content = f.read()
        assert content == "Content from shared store!"


def test_template_priority_initial_params_over_shared():
    """Test that initial_params have priority over shared store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "message": {"type": "string", "description": "Message body", "required": True},
            },
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {"file_path": os.path.join(tmpdir, "priority.txt"), "content": "${message}"},
                }
            ],
            "edges": [],
        }

        # Both initial_params and shared have 'message'
        initial_params = {"message": "From initial params (should win)"}

        registry = Registry()

        # Shared store has different value
        shared: dict[str, Any] = {"message": "From shared store (should lose)"}
        _compile_and_run(workflow_ir, registry, shared, initial_params=initial_params)

        # Verify initial_params value was used
        with open(os.path.join(tmpdir, "priority.txt"), encoding="utf-8") as f:
            content = f.read()
        assert content == "From initial params (should win)"


def test_workflow_reusability():
    """Test that same workflow can be reused with different parameters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Define reusable workflow
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {
                "output_file": {"type": "string", "description": "Output file path", "required": True},
                "user_name": {"type": "string", "description": "User name", "required": True},
                "task_id": {"type": "string", "description": "Task ID", "required": True},
            },
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {"file_path": "${output_file}", "content": "User: ${user_name}, Task: ${task_id}"},
                }
            ],
            "edges": [],
        }

        registry = Registry()

        # First execution
        params1 = {
            "output_file": os.path.join(tmpdir, "user1.txt"),
            "user_name": "Alice",
            "task_id": "TASK-001",
        }
        shared1: dict[str, Any] = {}
        _compile_and_run(workflow_ir, registry, shared1, initial_params=params1)

        # Second execution with different params
        params2 = {
            "output_file": os.path.join(tmpdir, "user2.txt"),
            "user_name": "Bob",
            "task_id": "TASK-002",
        }
        shared2: dict[str, Any] = {}
        _compile_and_run(workflow_ir, registry, shared2, initial_params=params2)

        # Verify both files
        with open(os.path.join(tmpdir, "user1.txt"), encoding="utf-8") as f:
            assert f.read() == "User: Alice, Task: TASK-001"

        with open(os.path.join(tmpdir, "user2.txt"), encoding="utf-8") as f:
            assert f.read() == "User: Bob, Task: TASK-002"
