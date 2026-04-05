"""Tests for WorkflowRunner — the shared execution pipeline entry point.

Verifies that validation gates compilation (spec 9b) and that a valid
workflow runs through the full pipeline producing structured results.
"""

from pathlib import Path
from unittest.mock import patch

from pflow.core.diagnostic import Severity
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
        assert (result.errors[0].context or {}).get("category") == "execution_failure"
        assert result.errors[0].node_id == "fetch-data"

    def test_valueerror_without_annotation_is_validation(self):
        """ValueError from pre-execution (no annotation) -> validation."""
        exc = ValueError("Invalid parameter format")
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "validation"
        assert result.errors[0].node_id is None

    def test_schema_validation_error_preserves_fields(self):
        """SchemaValidationError (replacing duck-type hack) preserves path and suggestions."""
        exc = SchemaValidationError("bad field", path="nodes[0].type", suggestion="Use 'shell'")
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "validation"
        assert result.errors[0].source == "validation"
        assert (result.errors[0].context or {}).get("path") == "nodes[0].type"
        assert result.errors[0].suggestions == ["Use 'shell'"]

    def test_markdown_parse_error_preserves_line_and_suggestions(self):
        """MarkdownParseError extracts .line and .suggestions into error dict."""
        exc = MarkdownParseError("bad syntax", line=42, suggestion="Add ## Steps")
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "parse_error"
        assert (result.errors[0].context or {}).get("line") == 42
        assert result.errors[0].suggestions == ["Add ## Steps"]

    def test_markdown_parse_error_with_node_annotation(self):
        """MarkdownParseError from nested workflow propagates node_id."""
        exc = MarkdownParseError("bad syntax", line=5)
        exc._pflow_node_id = "load-sub-workflow"  # type: ignore[attr-defined]
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "parse_error"
        assert result.errors[0].node_id == "load-sub-workflow"
        assert (result.errors[0].context or {}).get("line") == 5

    def test_markdown_parse_error_omits_none_fields(self):
        """MarkdownParseError with None line/suggestions doesn't write None values."""
        exc = MarkdownParseError("bad syntax")
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "parse_error"
        assert "line" not in (result.errors[0].context or {})
        assert result.errors[0].suggestions is None


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
    category = (error.context or {}).get("category")
    assert category == "execution_failure", (
        f"Expected 'execution_failure' but got '{category}'. "
        f"This means the engine's _pflow_node_id annotation or the "
        f"runner's ValueError dispatch is broken."
    )
    assert error.node_id == "bad-node"


def test_child_parser_warning_survives_prep_failure(tmp_path: Path):
    """Child parser warnings should survive child prep failures and reach the result."""
    child_workflow = tmp_path / "child.pflow.md"
    child_workflow.write_text(
        "# Child\n\n"
        "## Input\n\n"
        "Typo section heading.\n\n"
        "## Inputs\n\n"
        "### required_value\n\n"
        "Required input.\n\n"
        "- type: string\n"
        "- required: true\n\n"
        "## Steps\n\n"
        "### run\n\n"
        "Use the input.\n\n"
        "- type: shell\n"
        "- cache: false\n"
        "- command: echo ${required_value}\n",
        encoding="utf-8",
    )

    parent_workflow = tmp_path / "parent.pflow.md"
    parent_workflow.write_text(
        f"# Parent\n\n## Steps\n\n### child\n\nRun child.\n\n- type: workflow\n- workflow: {child_workflow}\n",
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(parent_workflow), {}, RunnerConfig())

    assert result.success is False
    assert any(diagnostic.severity == Severity.ERROR for diagnostic in result.diagnostics)
    parser_warnings = [
        diagnostic
        for diagnostic in result.diagnostics
        if diagnostic.severity == Severity.WARNING and diagnostic.source == "parser"
    ]
    assert len(parser_warnings) == 1
    assert "## Input" in parser_warnings[0].message


def test_sibling_child_parser_warnings_not_collapsed_by_dedup(tmp_path: Path):
    """Two children with identical parser warnings must both survive deduplication.

    Regression test for: parser warnings from sibling sub-workflows had the same
    (severity, source, node_id, message) hash when node_id was None and the typo
    appeared on the same line number, causing deduplicate_diagnostics() to drop one.
    Fix: _propagate_child_parser_warnings adds parent node_id and workflow path
    as provenance, making the two diagnostics distinguishable.
    """
    for name in ("child_a", "child_b"):
        (tmp_path / f"{name}.pflow.md").write_text(
            f"# {name}\n\n"
            "## Input\n\n"  # same typo, same line number in both
            "Typo section.\n\n"
            "## Steps\n\n"
            f"### run-{name}\n\n"
            "Does a thing.\n\n"
            "- type: shell\n"
            "- cache: false\n"
            "- command: echo hello\n",
            encoding="utf-8",
        )

    parent = tmp_path / "parent.pflow.md"
    parent.write_text(
        "# Parent\n\n## Steps\n\n"
        f"### step-a\n\nRun child A.\n\n- type: workflow\n- workflow: {tmp_path / 'child_a.pflow.md'}\n\n"
        f"### step-b\n\nRun child B.\n\n- type: workflow\n- workflow: {tmp_path / 'child_b.pflow.md'}\n",
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(parent), {}, RunnerConfig())

    parser_warnings = [d for d in result.diagnostics if d.severity == Severity.WARNING and d.source == "parser"]
    # Both children's parser warnings must survive — not collapsed by dedup
    assert len(parser_warnings) == 2, (
        f"Expected 2 parser warnings (one per child), got {len(parser_warnings)}: "
        f"{[w.message for w in parser_warnings]}"
    )
    # Each should identify its parent step via provenance
    messages = [w.message for w in parser_warnings]
    assert any("step-a" in m for m in messages)
    assert any("step-b" in m for m in messages)


def test_child_cache_lint_warning_propagates_to_parent_validation(tmp_path: Path):
    """Cache-lint warnings from child workflows must reach parent validate-only output.

    Regression test for: _validate_sub_workflows() discarded _child_warnings from
    recursive WorkflowValidator.validate() calls, so cache-lint warnings from children
    never reached the parent.
    """
    child = tmp_path / "child.pflow.md"
    child.write_text(
        "# Child\n\n## Steps\n\n"
        "### static-shell\n\n"
        "Runs a command with no template inputs.\n\n"
        "- type: shell\n"
        "- command: git branch --show-current\n",  # no templates, no cache:false → lint warning
        encoding="utf-8",
    )

    parent = tmp_path / "parent.pflow.md"
    parent.write_text(
        f"# Parent\n\n## Steps\n\n### child-step\n\nRun child.\n\n- type: workflow\n- workflow: {child}\n",
        encoding="utf-8",
    )

    vresult = WorkflowRunner().validate(str(parent), {})

    assert vresult.valid is True
    warnings = vresult.warnings
    cache_warnings = [w for w in warnings if "cache" in w.message.lower() or "template inputs" in w.message.lower()]
    assert cache_warnings, (
        f"Expected child cache-lint warning in parent validation, got warnings: {[w.message for w in warnings]}"
    )
    # Should include provenance about which sub-workflow produced it
    assert any("child" in w.message.lower() or "child-step" in (w.node_id or "") for w in cache_warnings)
