"""Tests for ExecutionService.execute_workflow() behavioral contract.

These tests establish a baseline for the execute_workflow() method before
Task 138 rewrites the shared execution pipeline. They verify the public
contract: success returns str, validation errors raise ValueError,
execution errors raise RuntimeError.

Coverage: file workflows, library workflows, not-found, validation failure,
execution failure.
"""

import pytest

from pflow.core.workflow.manager import WorkflowManager
from pflow.mcp_server.services.execution_service import ExecutionService
from tests.shared.markdown_utils import write_workflow_file

# --- IR dicts for test workflows ---

SIMPLE_ECHO_IR = {
    "nodes": [
        {
            "id": "greet",
            "type": "shell",
            "params": {"command": "echo hello"},
            "purpose": "Echo a greeting message",
        }
    ],
}

UNKNOWN_NODE_TYPE_IR = {
    "nodes": [
        {
            "id": "bad",
            "type": "nonexistent-node-type-xyz",
            "params": {},
            "purpose": "This node type does not exist in registry",
        }
    ],
}

FAILING_COMMAND_IR = {
    "nodes": [
        {
            "id": "fail",
            "type": "shell",
            "params": {"command": "exit 1"},
            "purpose": "Command that will fail with exit code 1",
        }
    ],
}


class TestExecuteWorkflowSuccess:
    """Tests for successful workflow execution paths."""

    def test_file_workflow_returns_success_string(self, tmp_path):
        """When given a valid .pflow.md file path, execute_workflow returns
        a success string with completion text and workflow output."""
        workflow_path = tmp_path / "echo.pflow.md"
        write_workflow_file(SIMPLE_ECHO_IR, workflow_path)

        result = ExecutionService.execute_workflow(str(workflow_path))

        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"
        assert "Workflow completed" in result, "Success output should contain completion text"
        assert "Workflow output:" in result, "Success output should include the workflow output header"
        assert "hello" in result, "Success output should include the workflow output value"

    def test_library_workflow_returns_success_string(self, isolate_pflow_config):
        """When given a saved workflow name, execute_workflow resolves it
        from the library and returns a success string."""
        # Save a workflow to the isolated library
        wm = WorkflowManager()
        from tests.shared.markdown_utils import ir_to_markdown

        markdown_content = ir_to_markdown(SIMPLE_ECHO_IR, title="Test Echo")
        wm.save("test-echo-lib", markdown_content)

        result = ExecutionService.execute_workflow("test-echo-lib")

        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"
        assert "Workflow completed" in result, "Success output should contain completion text"
        assert "Workflow output:" in result, "Success output should include the workflow output header"
        assert "hello" in result, "Success output should include the workflow output value"


class TestExecuteWorkflowErrors:
    """Tests for error paths: not found, validation failure, execution failure."""

    def test_nonexistent_workflow_raises_value_error(self):
        """When given a workflow name that does not exist anywhere,
        execute_workflow raises ValueError with 'not found' in the message."""
        with pytest.raises(ValueError, match=r"(?i)not found"):
            ExecutionService.execute_workflow("nonexistent-workflow-xyz")

    def test_unknown_node_type_raises_validation_error(self, tmp_path):
        """When a workflow references an unknown node type,
        execute_workflow raises an error mentioning the invalid type.

        Note: The docstring claims ValueError for validation failures, but
        the implementation wraps it as RuntimeError because the ValueError
        is raised inside a try/except that catches all non-RuntimeError
        exceptions and re-wraps them. This test documents actual behavior.
        """
        workflow_path = tmp_path / "bad-node.pflow.md"
        write_workflow_file(UNKNOWN_NODE_TYPE_IR, workflow_path)

        with pytest.raises(RuntimeError) as exc_info:
            ExecutionService.execute_workflow(str(workflow_path))

        error_text = str(exc_info.value).lower()
        assert "nonexistent-node-type-xyz" in error_text, "Validation error should mention the invalid node type"

    def test_failing_command_raises_runtime_error(self, tmp_path):
        """When a shell node command fails (exit 1), execute_workflow
        raises RuntimeError."""
        workflow_path = tmp_path / "fail.pflow.md"
        write_workflow_file(FAILING_COMMAND_IR, workflow_path)

        with pytest.raises(RuntimeError):
            ExecutionService.execute_workflow(str(workflow_path))
