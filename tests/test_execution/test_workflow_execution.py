"""Tests for unified workflow execution function.

These tests verify the orchestration logic: validation before execution,
failure modes, and correct parameter passing.
"""

from unittest.mock import MagicMock, patch

from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.workflow_execution import execute_workflow


class TestWorkflowExecution:
    """Test the unified workflow execution function."""

    def test_successful_workflow(self):
        """Test that successful workflows return immediately."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.errors = []
            mock_executor.execute_workflow.return_value = mock_result

            with patch("pflow.core.workflow.validator.WorkflowValidator") as MockValidator:
                MockValidator.validate.return_value = ([], [])

                result = execute_workflow(
                    workflow_ir=workflow_ir,
                    execution_params={},
                )

                assert result.success is True

    def test_validation_failure_returns_error(self):
        """Test that validation errors prevent execution and return failure."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "echo-hello", "type": "shell", "params": {"command": "echo", "args": ["hello"]}},
                {
                    "id": "bad-ref",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${fake-node.stdout}"]},
                },
            ],
            "edges": [{"from": "echo-hello", "to": "bad-ref", "action": "default"}],
        }

        result = execute_workflow(
            workflow_ir=workflow_ir,
            execution_params={},
        )

        # Must fail at validation, not runtime
        assert result.success is False
        assert result.status == WorkflowStatus.FAILED
        assert result.action_result == "validation_failed"

        # No nodes should have executed (no side effects)
        assert result.shared_after == {}

        # Error should mention the bad template reference
        assert len(result.errors) > 0
        assert any("fake-node" in err["message"] for err in result.errors)

    def test_runtime_failure_returns_error(self):
        """Test that runtime failures are returned without repair."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.errors = [{"message": "Error"}]
            mock_executor.execute_workflow.return_value = mock_result

            with patch("pflow.core.workflow.validator.WorkflowValidator") as MockValidator:
                MockValidator.validate.return_value = ([], [])

                result = execute_workflow(
                    workflow_ir=workflow_ir,
                    execution_params={},
                )

                assert result.success is False

    def test_executor_receives_correct_params(self):
        """Test that execution parameters are passed through to the executor."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_result = MagicMock()
            mock_result.success = True
            mock_executor.execute_workflow.return_value = mock_result

            with patch("pflow.core.workflow.validator.WorkflowValidator") as MockValidator:
                MockValidator.validate.return_value = ([], [])

                execute_workflow(
                    workflow_ir=workflow_ir,
                    execution_params={"key": "value"},
                    workflow_name="test-workflow",
                    stdin_data="input",
                    output_key="result",
                )

                mock_executor.execute_workflow.assert_called_once()
                _args, kwargs = mock_executor.execute_workflow.call_args
                assert kwargs["workflow_ir"] == workflow_ir
                assert kwargs["execution_params"] == {"key": "value"}
                assert kwargs["shared_store"] == {}
                assert kwargs["workflow_name"] == "test-workflow"
                assert kwargs["stdin_data"] == "input"
                assert kwargs["output_key"] == "result"
                assert kwargs["validate"] is True
