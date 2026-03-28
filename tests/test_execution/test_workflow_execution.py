"""Tests for unified workflow execution function.

These tests verify the orchestration logic: compilation error wrapping,
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

            result = execute_workflow(
                workflow_ir=workflow_ir,
                execution_params={},
            )

            assert result.success is True

    def test_compilation_error_wrapped_in_execution_result(self):
        """Test that CompilationError is caught and wrapped in ExecutionResult.

        execute_workflow() catches CompilationError from the compiler and wraps
        it in ExecutionResult so callers always get the declared return type.
        """
        from pflow.runtime.compilation.compiler import CompilationError

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_executor.execute_workflow.side_effect = CompilationError(
                message="bad template", phase="template_validation"
            )

            result = execute_workflow(
                workflow_ir=workflow_ir,
                execution_params={},
            )

            # Must return ExecutionResult, not raise
            assert result.success is False
            assert result.status == WorkflowStatus.FAILED
            assert result.action_result == "compilation_failed"
            assert len(result.errors) == 1
            assert result.errors[0]["source"] == "compilation"
            assert "bad template" in result.errors[0]["message"]
            assert result.errors[0]["phase"] == "template_validation"
            assert result.shared_after == {}

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


class TestCompilationErrorIntegration:
    """Unmocked integration test: compiler → executor → execute_workflow wrapper.

    The mocked test above verifies execute_workflow catches CompilationError.
    This test verifies the FULL path without mocks: the compiler raises
    CompilationError, the executor re-raises it, and execute_workflow wraps it.

    If someone changes the executor to stop re-raising CompilationError,
    the mocked test still passes but this one catches the regression.
    """

    def test_structural_cycle_returns_compilation_failed(self):
        """An actionless cycle should produce a clean ExecutionResult, not an exception."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo a"}},
                {"id": "b", "type": "shell", "params": {"command": "echo b"}},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"},  # Actionless backward edge = cycle
            ],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        assert result.success is False
        assert result.status == WorkflowStatus.FAILED
        assert result.action_result == "compilation_failed"
        assert any("data_flow_validation" in str(e.get("phase", "")) for e in result.errors)
        assert result.shared_after == {}
