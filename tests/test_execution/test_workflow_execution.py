"""Tests for WorkflowRunner — successor to the old execute_workflow wrapper.

These tests verify the orchestration logic: compilation error wrapping,
failure modes, and correct parameter passing through the Runner.
"""

from unittest.mock import patch

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.result import ExecutionResult, RunnerConfig
from pflow.execution.runner import WorkflowRunner


class TestWorkflowExecution:
    """Test the WorkflowRunner execution pipeline (mocked)."""

    def test_successful_workflow(self):
        """Test that successful workflows return immediately."""
        # Use shell node (real type) to avoid validation rejection
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {"command": "echo ok"}}],
            "edges": [],
        }

        with patch("pflow.execution.runner.WorkflowRunner._compile_and_execute") as mock_exec:
            mock_exec.return_value = ExecutionResult(success=True)
            result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())
            assert result.success is True

    def test_compilation_error_wrapped_in_execution_result(self):
        """Test that CompilationError is caught and wrapped in ExecutionResult.

        The Runner catches CompilationError from the compiler and wraps
        it in ExecutionResult so callers always get the declared return type.
        """
        from pflow.runtime.compilation.compiler import CompilationError

        # Use shell node (real type) to pass validation, then fail at compile
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {"command": "echo ok"}}],
            "edges": [],
        }

        # Patch compile_workflow where it's imported (lazy import in _compile_and_execute)
        with patch("pflow.runtime.compile_workflow") as mock_compile:
            mock_compile.side_effect = CompilationError(
                message="bad template",
                phase="template_validation",
                node_id="node1",
                node_type="shell",
                suggestion="Check your template syntax",
            )

            result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

            # Must return ExecutionResult, not raise
            assert result.success is False
            assert result.status == WorkflowStatus.FAILED
            assert len(result.errors) == 1
            error = result.errors[0]
            assert error.source == "compilation"
            assert (error.context or {}).get("category") == "compilation"
            assert "bad template" in error.message
            assert (error.context or {}).get("phase") == "template_validation"
            assert error.node_id == "node1"
            assert (error.context or {}).get("node_type") == "shell"
            assert error.suggestions == ["Check your template syntax"]

    def test_runtime_failure_returns_error(self):
        """Test that runtime failures are returned without repair."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {"command": "echo ok"}}],
            "edges": [],
        }

        with patch("pflow.execution.runner.WorkflowRunner._compile_and_execute") as mock_exec:
            mock_exec.return_value = ExecutionResult(
                success=False,
                diagnostics=[Diagnostic(severity=Severity.ERROR, message="Error", source="runtime")],
            )
            result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())
            assert result.success is False


class TestCompilationErrorIntegration:
    """Unmocked integration test: compiler → Runner → ExecutionResult.

    Verifies the FULL path without mocks: the compiler raises
    CompilationError, and the Runner wraps it in ExecutionResult.
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

        result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

        assert result.success is False
        assert result.status == WorkflowStatus.FAILED
        # Error could come from validation (data flow check) or compilation
        assert len(result.errors) >= 1
