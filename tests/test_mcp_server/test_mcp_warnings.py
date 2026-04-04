"""Tests for validation warning propagation through ExecutionResult.

MCP (and CLI) now receive validation warnings via ExecutionResult.warnings.
These tests verify the plumbing: warnings produced by WorkflowValidator flow through
WorkflowRunner into the result object with the correct structure.

Two strategies:
1. Real warnings — a shell node's stdout is typed as str, so nested access like
   ${fetch.stdout.nested_field} triggers a Diagnostic warning about JSON auto-parsing.
   The fetch node must produce valid JSON so the runtime template resolution succeeds
   and the result is returned (not an exception path that drops warnings).
2. Mock plumbing — mock WorkflowValidator.validate to inject synthetic warnings,
   verifying they propagate regardless of what triggers them.
"""

from unittest.mock import patch

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner

# --- Workflow IR that triggers a real validation warning ---
# The fetch node produces valid JSON via printf so that:
# 1. The validator warns about nested access on str-typed stdout
# 2. The runtime succeeds because the JSON auto-parsing resolves the path
# Using printf with %s avoids shell quoting issues with echo and JSON.

NESTED_ACCESS_IR = {
    "nodes": [
        {
            "id": "fetch",
            "type": "shell",
            "params": {"command": """printf '%s' '{"nested_field": "hello"}'"""},
            "purpose": "Produce JSON string on stdout (typed as str by shell node)",
        },
        {
            "id": "process",
            "type": "shell",
            "params": {"command": "echo ${fetch.stdout.nested_field}"},
            "purpose": "Access nested field on str output to trigger warning",
        },
    ],
    "edges": [{"from": "fetch", "to": "process"}],
}


class TestValidationWarningsPropagateToResult:
    """Validation warnings from WorkflowValidator reach ExecutionResult.warnings."""

    def test_real_nested_str_access_produces_validation_warning(self):
        """When a template accesses a nested field on a str-typed output,
        the validator emits a warning and it appears in result.warnings.

        Shell stdout is typed as str. Accessing ${fetch.stdout.nested_field}
        triggers a warning because nested access on str requires JSON auto-parsing.
        The fetch node produces valid JSON so the workflow succeeds at runtime.
        """
        runner = WorkflowRunner()
        result = runner.run(NESTED_ACCESS_IR, {}, RunnerConfig())

        # Filter for template warnings (not lint warnings like cache advisory)
        template_warnings = [w for w in result.warnings if (w.context or {}).get("template")]

        assert len(template_warnings) == 1, (
            f"Expected exactly 1 template validation warning for nested access on str output, "
            f"got {len(template_warnings)}: {template_warnings}"
        )

        warning = template_warnings[0]

        # Verify the warning diagnostic has the expected structure
        assert warning.node_id, f"Warning missing node_id: {warning}"
        assert warning.message, f"Warning missing message: {warning}"
        assert (warning.context or {}).get("template"), f"Warning missing template context: {warning}"

        # Verify values are populated (not None or empty)
        assert warning.node_id, f"'node_id' should have a value, got: {warning.node_id}"
        assert warning.message, f"'message' should have a value, got: {warning.message}"

        # The template should reference the nested access
        template = (warning.context or {}).get("template", "")
        assert "${fetch.stdout.nested_field}" in template, (
            f"Warning template should contain the nested access, got: {template}"
        )

    def test_warning_dict_has_correct_node_metadata(self):
        """Warning dict should identify the source node correctly."""
        runner = WorkflowRunner()
        result = runner.run(NESTED_ACCESS_IR, {}, RunnerConfig())

        assert result.warnings, "Expected validation warnings"

        # Filter for template warning (not cache lint warning)
        template_warnings = [w for w in result.warnings if (w.context or {}).get("template")]
        assert template_warnings, "Expected at least one template validation warning"
        warning = template_warnings[0]
        assert warning.node_id == "fetch", f"Warning should identify 'fetch' as the source node, got: {warning.node_id}"

    def test_mocked_warnings_propagate_through_runner(self):
        """When WorkflowValidator.validate returns warnings, they appear in
        result.warnings. Tests the plumbing independently of
        what specific validation logic triggers warnings."""
        synthetic_warning = Diagnostic(
            severity=Severity.WARNING,
            source="validator",
            node_id="api",
            message="Cannot verify nested access on 'any' type at validation time",
            suggestion="Inspect this runtime value before relying on nested access.",
            context={"template": "${api.result.data.items}"},
        )

        original_validate = WorkflowRunner._validate

        def patched_validate(self_runner, ir, params):
            # Call the real validator to catch any real errors
            real_warnings = original_validate(self_runner, ir, params)
            # Inject our synthetic warning
            return [*real_warnings, synthetic_warning]

        # Use a simple workflow that passes validation and executes
        simple_ir = {
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                    "purpose": "Simple shell command for testing",
                }
            ],
        }

        with patch.object(WorkflowRunner, "_validate", patched_validate):
            runner = WorkflowRunner()
            result = runner.run(simple_ir, {}, RunnerConfig())

        # The synthetic warning should appear in the result
        assert len(result.warnings) >= 1, f"Expected at least 1 validation warning, got: {result.warnings}"

        # Find our synthetic warning by template
        matching = [w for w in result.warnings if (w.context or {}).get("template") == "${api.result.data.items}"]
        assert len(matching) == 1, (
            f"Expected exactly 1 warning with our synthetic template, got {len(matching)} in {result.warnings}"
        )

        warning = matching[0]
        assert warning.node_id == "api"
        assert warning.message == "Cannot verify nested access on 'any' type at validation time"
        assert (warning.context or {}).get("template") == "${api.result.data.items}"

    def test_validation_warnings_empty_when_no_nested_access(self):
        """When there are no nested accesses on str outputs, template-related
        warnings should be empty. (Cache lint warnings may still appear.)"""
        simple_ir = {
            "nodes": [
                {
                    "id": "greet",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                    "purpose": "Simple echo command with no nested template access",
                }
            ],
        }

        runner = WorkflowRunner()
        result = runner.run(simple_ir, {}, RunnerConfig())

        # Filter for template warnings only (exclude lint warnings like cache advisory)
        template_warnings = [w for w in result.warnings if (w.context or {}).get("template")]
        assert template_warnings == [], (
            f"Expected no template validation warnings for simple workflow, got: {template_warnings}"
        )
