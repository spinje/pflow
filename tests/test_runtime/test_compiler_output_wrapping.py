"""Test that compiler correctly wraps flow.run for output population.

These tests verify the critical behavior that outputs are populated
on success but NOT on failure, and that the wrapping happens correctly.
"""

import tempfile
from pathlib import Path

import pytest

from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine


@pytest.fixture
def registry_with_shell():
    """Create a test registry with shell node registered."""
    # Create a temporary registry file
    registry_dir = tempfile.mkdtemp()
    registry_path = Path(registry_dir) / "test_registry.json"
    registry = Registry(registry_path)

    # Register the shell node
    shell_metadata = {
        "shell": {
            "module": "pflow.nodes.shell.shell",
            "class_name": "ShellNode",
            "file_path": "src/pflow/nodes/shell/shell.py",
            "docstring": "Run shell commands.",
            "interface": {
                "description": "Run shell commands.",
                "inputs": [],
                "outputs": [
                    {"key": "stdout", "type": "str", "description": "Command standard output"},
                    {"key": "stderr", "type": "str", "description": "Command standard error"},
                    {"key": "exit_code", "type": "int", "description": "Command exit code"},
                ],
                "params": [
                    {
                        "name": "command",
                        "type": "str",
                        "description": "Shell command to execute",
                        "required": True,
                    },
                ],
                "actions": ["default", "error"],
            },
        }
    }
    registry.save(shell_metadata)
    return registry


class TestCompilerOutputWrapping:
    """Test compiler's output wrapping behavior."""

    def test_outputs_populated_when_declared(self, registry_with_shell):
        """Verify output declarations are resolved after successful execution.

        FIX HISTORY:
        - Previously checked flow.run.__name__ == "run_with_hooks" (monkey-patch).
        - The shim's .run() IS the run method now; verify output population instead.
        - Migrated from compile_ir_to_flow shim to compile_workflow + WorkflowEngine.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "sh1", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
            "start_node": "sh1",
            "outputs": {"result": {"source": "${sh1.stdout}", "description": "Test output"}},
        }

        workflow = compile_workflow(workflow_ir, registry_with_shell)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        # Output should be populated at root level from declared outputs
        assert "test" in shared["result"]
        assert result == "default"

    def test_run_works_without_outputs(self, registry_with_shell):
        """Verify workflow runs correctly even without output declarations.

        FIX HISTORY:
        - Previously checked flow.run.__name__ == "run_with_hooks" (monkey-patch).
        - The shim's .run() IS the run method now; verify execution works instead.
        - Migrated from compile_ir_to_flow shim to compile_workflow + WorkflowEngine.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "sh1", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
            "start_node": "sh1",
            # No outputs field
        }

        workflow = compile_workflow(workflow_ir, registry_with_shell)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        # Node should have executed and written namespaced output
        assert "sh1" in shared
        assert "test" in shared["sh1"]["stdout"]
        assert result == "default"

    def test_outputs_populated_on_success(self, registry_with_shell):
        """Verify outputs ARE populated when workflow succeeds."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "sh1", "type": "shell", "params": {"command": "echo Hello"}}],
            "edges": [],
            "start_node": "sh1",
            "outputs": {
                "result": {"source": "${sh1.stdout}"},
                "code": {"source": "${sh1.exit_code}"},
            },
        }

        workflow = compile_workflow(workflow_ir, registry_with_shell)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        # Output should be populated at root level
        assert "Hello" in shared["result"]
        assert shared["code"] == 0
        # Result should be "default" (success)
        assert result == "default"

    # Note: We can't easily test error cases without creating custom test nodes
    # The logic in engine.py checks: if not (result and isinstance(result, str) and result.startswith("error"))
    # This means outputs are NOT populated when a node returns an action starting with "error"
    # The implementation follows the same pattern that was previously in the CLI


class TestProgrammaticUsage:
    """Test programmatic usage without CLI."""

    def test_programmatic_workflow_with_outputs(self, registry_with_shell):
        """Verify outputs work when using compile_workflow + WorkflowEngine directly."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "sh1", "type": "shell", "params": {"command": "echo Hello World"}}],
            "edges": [],
            "start_node": "sh1",
            "outputs": {
                "message": {"source": "${sh1.stdout}", "description": "Shell output"},
                "code": {"source": "${sh1.exit_code}"},
            },
        }

        # Use the API directly, no CLI involved
        workflow = compile_workflow(workflow_ir, registry_with_shell)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        # Outputs should be populated at root level
        assert "Hello World" in shared["message"]
        assert shared["code"] == 0
        # Namespaced values should also exist
        assert "Hello World" in shared["sh1"]["stdout"]
        assert result == "default"

    def test_complex_workflow_with_multiple_nodes(self, registry_with_shell):
        """Test outputs from a multi-node workflow."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "sh1", "type": "shell", "params": {"command": "echo First"}},
                {"id": "sh2", "type": "shell", "params": {"command": "echo Second"}},
            ],
            "edges": [{"from": "sh1", "to": "sh2"}],
            "start_node": "sh1",
            "outputs": {
                "first_msg": {"source": "${sh1.stdout}"},
                "second_msg": {"source": "${sh2.stdout}"},
            },
        }

        workflow = compile_workflow(workflow_ir, registry_with_shell)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        # All outputs should be populated
        assert "First" in shared["first_msg"]
        assert "Second" in shared["second_msg"]
        assert result == "default"
