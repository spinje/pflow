"""Tests for WorkflowRunner — the shared execution pipeline entry point.

Verifies that validation gates compilation (spec 9b) and that a valid
workflow runs through the full pipeline producing structured results.
"""

from unittest.mock import patch

from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
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

    with patch("pflow.runtime.compile_workflow") as mock_compile:
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


def test_declared_defaults_applied_without_user_params():
    """Workflow with declared input defaults should use them when user provides nothing.

    Tests the full novel pipeline: _fill_declared_defaults (placeholders for validation)
    → _strip_placeholders (clean before compilation) → prepare_inputs (applies real defaults).
    If any step is wrong, the default value won't appear in the output.
    """
    workflow_ir = {
        "inputs": {
            "greeting": {"type": "str", "default": "hello-from-default", "description": "A greeting"},
        },
        "nodes": [
            {"id": "greet", "type": "shell", "params": {"command": "echo ${greeting}"}},
        ],
        "edges": [],
    }

    # Empty params — the default should be applied by the Runner/compiler pipeline
    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert result.success is True, f"Expected success, got errors: {result.errors}"
    assert "hello-from-default" in result.shared_after["greet"]["stdout"]


def test_user_params_override_declared_defaults():
    """User-provided values must not be clobbered by declared defaults.

    _fill_declared_defaults has an `if name not in params` guard. This test
    ensures a user's explicit value survives through the full pipeline.
    """
    workflow_ir = {
        "inputs": {
            "greeting": {"type": "str", "default": "hello-from-default", "description": "A greeting"},
        },
        "nodes": [
            {"id": "greet", "type": "shell", "params": {"command": "echo ${greeting}"}},
        ],
        "edges": [],
    }

    # User provides their own value — should override the default
    result = WorkflowRunner().run(workflow_ir, {"greeting": "user-override"}, RunnerConfig())

    assert result.success is True, f"Expected success, got errors: {result.errors}"
    assert "user-override" in result.shared_after["greet"]["stdout"]
    assert "hello-from-default" not in result.shared_after["greet"]["stdout"]


class TestExceptionToResultCategorization:
    """Regression tests for _exception_to_result error categorization."""

    def _run(self, exception):
        """Helper to call _exception_to_result with minimal args."""
        runner = WorkflowRunner()
        return runner._exception_to_result(exception, 0.0, None)

    def test_valueerror_with_node_annotation_is_execution_failure(self):
        """ValueError from node execution (annotated) -> execution_failure."""
        exc = ValueError("HTTP timeout connecting to api.example.com")
        exc._pflow_node_id = "fetch-data"  # type: ignore[attr-defined]
        result = self._run(exc)
        assert result.errors[0]["category"] == "execution_failure"
        assert result.errors[0]["node_id"] == "fetch-data"

    def test_valueerror_without_annotation_is_validation(self):
        """ValueError from pre-execution (no annotation) -> validation."""
        exc = ValueError("Invalid parameter format")
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert "node_id" not in result.errors[0]

    def test_schema_validation_error_preserves_fields(self):
        """SchemaValidationError (replacing duck-type hack) preserves path and suggestion."""
        exc = SchemaValidationError("bad field", path="nodes[0].type", suggestion="Use 'shell'")
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert result.errors[0]["source"] == "validation"
        assert result.errors[0]["path"] == "nodes[0].type"
        assert result.errors[0]["suggestion"] == "Use 'shell'"

    def test_markdown_parse_error_preserves_line_and_suggestion(self):
        """MarkdownParseError extracts .line and .suggestion into error dict."""
        exc = MarkdownParseError("bad syntax", line=42, suggestion="Add ## Steps")
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert result.errors[0]["line"] == 42
        assert result.errors[0]["suggestion"] == "Add ## Steps"

    def test_markdown_parse_error_with_node_annotation(self):
        """MarkdownParseError from nested workflow propagates node_id."""
        exc = MarkdownParseError("bad syntax", line=5)
        exc._pflow_node_id = "load-sub-workflow"  # type: ignore[attr-defined]
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert result.errors[0]["node_id"] == "load-sub-workflow"
        assert result.errors[0]["line"] == 5

    def test_markdown_parse_error_omits_none_fields(self):
        """MarkdownParseError with None line/suggestion doesn't write None values."""
        exc = MarkdownParseError("bad syntax")
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert "line" not in result.errors[0]
        assert "suggestion" not in result.errors[0]


def test_node_valueerror_categorized_as_execution_failure():
    """E2E: ValueError raised inside a node gets 'execution_failure', not 'validation'.

    This tests the full chain: engine.run() → node raises ValueError →
    engine annotates _pflow_node_id → runner._exception_to_result →
    ExecutionResult with category 'execution_failure'.

    Before Task 141, ALL ValueErrors got category 'validation' — including
    node execution errors like HTTP timeouts and API failures. The fix uses
    _pflow_node_id (set by the engine on any exception from a running node)
    as a discriminator.
    """
    workflow_ir = {
        "nodes": [
            {
                "id": "bad-node",
                "type": "code",
                "params": {
                    "code": 'result: str = ""\nraise ValueError("simulated API failure")',
                },
            },
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert result.success is False
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error["category"] == "execution_failure", (
        f"Expected 'execution_failure' but got '{error['category']}'. "
        f"This means the engine's _pflow_node_id annotation or the "
        f"runner's ValueError dispatch is broken."
    )
    assert error["node_id"] == "bad-node"
