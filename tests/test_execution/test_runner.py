"""Tests for WorkflowRunner — the shared execution pipeline entry point.

Verifies that validation gates compilation (spec 9b) and that a valid
workflow runs through the full pipeline producing structured results.
"""

from unittest.mock import patch

from pflow.core.workflow.validator import WorkflowValidator
from pflow.execution.result import ExecutionResult, RunnerConfig
from pflow.execution.runner import WorkflowRunner


def test_validation_error_prevents_compilation():
    """When a workflow has a cycle, validation should fail and compilation should never be called.

    Spec 9b: validation errors must block the pipeline before compilation.
    The cycle between nodes a and b (mutual data dependency + mutual edges)
    is caught by data flow validation (Kahn's algorithm in build_execution_order).
    """
    workflow_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "echo ${b.stdout}"}},
            {"id": "b", "type": "shell", "params": {"command": "echo ${a.stdout}"}},
        ],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ],
    }

    with patch("pflow.runtime.compile_ir_to_flow") as mock_compile:
        result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert isinstance(result, ExecutionResult)
    assert result.success is False
    assert len(result.errors) > 0

    # The error message should mention the circular dependency.
    # CycleError produces "Circular dependency detected involving nodes: a, b"
    # which is wrapped as "Data flow error: Circular dependency detected..."
    # and then surfaced through WorkflowValidationError → _exception_to_result.
    error_text = str(result.errors).lower()
    assert "circular" in error_text or "cycle" in error_text, f"Expected cycle/circular error, got: {result.errors}"

    # Compilation must NOT have been called — validation blocks it.
    mock_compile.assert_not_called()


def test_successful_workflow_runs_through_full_pipeline():
    """A valid single-node shell workflow should execute and return structured results.

    This is a real integration test — it runs an actual shell command and
    verifies the full pipeline: resolution, validation, compilation, execution.
    """
    workflow_ir = {
        "nodes": [
            {"id": "test", "type": "shell", "params": {"command": "echo runner-test"}},
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert "runner-test" in result.shared_after["test"]["stdout"]
    assert result.trace is not None
    assert result.metrics is not None


def test_validator_called_exactly_once():
    """WorkflowValidator.validate must be called exactly once per runner.run().

    Task 138 eliminated dual validation (CLI + compiler both validating).
    This guards against regression — if validate is called twice, this fails.
    """
    workflow_ir = {
        "nodes": [
            {"id": "test", "type": "shell", "params": {"command": "echo once"}},
        ],
        "edges": [],
    }

    with patch.object(WorkflowValidator, "validate", wraps=WorkflowValidator.validate) as mock_validate:
        result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert result.success is True
    assert mock_validate.call_count == 1, f"Expected exactly 1 validation call, got {mock_validate.call_count}"
