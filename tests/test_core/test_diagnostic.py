"""Tests for the unified Diagnostic model and exception conversion helpers."""

from __future__ import annotations

from pflow.core.diagnostic import (
    Diagnostic,
    Severity,
    coerce_error_diagnostic,
    coerce_warning_diagnostic,
    deduplicate_diagnostics,
    exception_to_diagnostics,
    format_diagnostic,
)
from pflow.core.exceptions import (
    CompilationError,
    MarkdownParseError,
    MaxNodeVisitsError,
    SchemaValidationError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError


def test_diagnostic_identity_ignores_context() -> None:
    """Diagnostics with the same core fields deduplicate even if context differs."""
    first = Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        node_id="fetch",
        message="Nested access requires JSON",
        suggestion="Ensure valid JSON.",
        context={"template": "${fetch.stdout.value}"},
    )
    second = Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        node_id="fetch",
        message="Nested access requires JSON",
        suggestion="Ensure valid JSON.",
        context={"template": "${fetch.stdout.other}"},
    )

    assert first == second
    assert hash(first) == hash(second)
    assert deduplicate_diagnostics([first, second]) == [first]


def test_to_dict_and_to_display_dict_preserve_context_shape() -> None:
    """Structured JSON keeps context nested; display dict flattens context keys."""
    diagnostic = Diagnostic(
        severity=Severity.ERROR,
        source="runtime",
        node_id="send",
        message="HTTP request failed",
        suggestion="Check API credentials.",
        context={"category": "api_validation", "raw_response": {"api_key": "secret", "error": "bad"}},
    )

    structured = diagnostic.to_dict()
    flattened = diagnostic.to_display_dict()

    assert structured == {
        "severity": "error",
        "source": "runtime",
        "node_id": "send",
        "message": "HTTP request failed",
        "suggestion": "Check API credentials.",
        "context": {
            "category": "api_validation",
            "raw_response": {"api_key": "secret", "error": "bad"},
        },
    }
    assert flattened["category"] == "api_validation"
    assert flattened["raw_response"] == {"api_key": "secret", "error": "bad"}

    # Conversion returns copies, not shared mutable references.
    flattened["raw_response"]["api_key"] = "changed"
    assert diagnostic.context == {
        "category": "api_validation",
        "raw_response": {"api_key": "secret", "error": "bad"},
    }


def test_format_diagnostic_renders_warning_with_suggestion() -> None:
    """Warnings render node context and actionable suggestions."""
    diagnostic = Diagnostic(
        severity=Severity.WARNING,
        source="parser",
        message="Line 5: '## Input' looks like a typo for '## Inputs'.",
        suggestion="Rename to '## Inputs'.",
    )

    rendered = format_diagnostic(diagnostic)

    assert "⚠" in rendered
    assert "looks like a typo" in rendered
    assert "Rename to '## Inputs'." in rendered


def test_exception_to_diagnostics_compilation_error() -> None:
    """CompilationError maps to one compilation diagnostic with context."""
    diagnostics = exception_to_diagnostics(
        CompilationError(
            message="Unknown node type",
            phase="node_import",
            node_id="fetch",
            node_type="custom-node",
            details={"sub_workflow_path": "./child.pflow.md"},
            suggestion="Use a registered node type.",
        )
    )

    assert diagnostics == [
        Diagnostic(
            severity=Severity.ERROR,
            source="compilation",
            node_id="fetch",
            message="Unknown node type",
            suggestion="Use a registered node type.",
            context={
                "category": "compilation",
                "phase": "node_import",
                "node_type": "custom-node",
                "sub_workflow_path": "./child.pflow.md",
            },
        )
    ]


def test_exception_to_diagnostics_workflow_validation_error_fans_out() -> None:
    """WorkflowValidationError produces one Diagnostic per validation error tuple."""
    diagnostics = exception_to_diagnostics(
        WorkflowValidationError(
            validation_errors=[
                ("Missing input", "inputs.name", "Declare the input."),
                "Unknown node type",
            ]
        )
    )

    assert len(diagnostics) == 2
    assert diagnostics[0].message == "Missing input"
    assert diagnostics[0].suggestion == "Declare the input."
    assert (diagnostics[0].context or {}).get("path") == "inputs.name"
    assert diagnostics[1].message == "Unknown node type"


def test_exception_to_diagnostics_structured_parser_and_schema_errors() -> None:
    """Markdown and schema validation exceptions preserve source-specific context."""
    parse_diag = exception_to_diagnostics(MarkdownParseError("Bad heading", line=42, suggestion="Use ## Steps."))[0]
    schema_diag = exception_to_diagnostics(
        SchemaValidationError("Bad node type", path="nodes[0].type", suggestion="Use 'shell'.")
    )[0]

    assert parse_diag.source == "parser"
    assert parse_diag.message == "Line 42: Bad heading"
    assert parse_diag.suggestion == "Use ## Steps."
    assert (parse_diag.context or {}).get("category") == "parse_error"
    assert (parse_diag.context or {}).get("line") == 42

    assert schema_diag.source == "validation"
    assert schema_diag.message == "Bad node type"
    assert schema_diag.suggestion == "Use 'shell'."
    assert (schema_diag.context or {}).get("category") == "validation"
    assert (schema_diag.context or {}).get("path") == "nodes[0].type"


def test_exception_to_diagnostics_runtime_and_user_friendly_errors() -> None:
    """Runtime exceptions preserve node annotations and user-facing details."""
    node_error = ValueError("timeout")
    node_error._pflow_node_id = "fetch-data"  # type: ignore[attr-defined]

    cases = [
        (
            WorkflowNotFoundError("my-flow", similar_names=["my-flow-v2"]),
            "runtime",
            "not_found",
            "Did you mean: my-flow-v2",
        ),
        (
            MaxNodeVisitsError("loop", visit_count=101, max_visits=100),
            "runtime",
            "max_visits",
            "Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional.",
        ),
        (
            UserFriendlyError("Bad input", "Value is invalid.", ["Set foo=bar"]),
            "runtime",
            "cli",
            "Set foo=bar",
        ),
        (
            MCPError(title="Missing MCP", explanation="No tool", suggestions=["Sync MCP"]),
            "runtime",
            "mcp",
            "Sync MCP",
        ),
        (
            OutputResolutionError(
                failures=[
                    {
                        "output_name": "result",
                        "source_expr": "${branch_a.stdout}",
                        "diagnostics": ["Node 'branch_a' did not execute"],
                    }
                ]
            ),
            "runtime",
            "runtime",
            "Check that source expressions reference nodes that always execute on this path",
        ),
        (FileNotFoundError("missing"), "runtime", "file_not_found", None),
        (PermissionError("denied"), "runtime", "permission_denied", None),
        (node_error, "runtime", "execution_failure", None),
        (RuntimeError("boom"), "runtime", "execution_failure", None),
    ]

    for exception, source, category, suggestion in cases:
        diagnostic = exception_to_diagnostics(exception)[0]
        assert diagnostic.source == source
        assert (diagnostic.context or {}).get("category") == category
        assert diagnostic.suggestion == suggestion

    node_diagnostic = exception_to_diagnostics(node_error)[0]
    assert node_diagnostic.node_id == "fetch-data"


def test_format_diagnostic_renders_rich_error_context() -> None:
    """Error diagnostics render category, node ID, shell details, and suggestions."""
    diagnostic = Diagnostic(
        severity=Severity.ERROR,
        source="runtime",
        node_id="build",
        message="Shell command failed",
        suggestion="Fix the shell command.",
        context={
            "category": "execution_failure",
            "shell_command": "npm run build",
            "shell_stderr": "Missing dependency",
        },
    )

    rendered = format_diagnostic(diagnostic)

    assert "Error at node 'build':" in rendered
    assert "Category: execution_failure" in rendered
    assert "Message: Shell command failed" in rendered
    assert "Suggestion: Fix the shell command." in rendered
    assert "npm run build" in rendered
    assert "Missing dependency" in rendered


# ---------------------------------------------------------------------------
# coerce_warning_diagnostic / coerce_error_diagnostic
# ---------------------------------------------------------------------------


class TestCoerceWarningDiagnostic:
    """Tests for the legacy-dict-to-Diagnostic bridge used by display consumers."""

    def test_passthrough_for_diagnostic_object(self) -> None:
        original = Diagnostic(severity=Severity.WARNING, message="already ok", source="runtime")
        assert coerce_warning_diagnostic(original) is original

    def test_dict_with_all_known_fields(self) -> None:
        result = coerce_warning_diagnostic({
            "message": "Template issue",
            "suggestion": "Fix it",
            "node_id": "fetch",
            "source": "validator",
        })
        assert result.severity == Severity.WARNING
        assert result.message == "Template issue"
        assert result.suggestion == "Fix it"
        assert result.node_id == "fetch"
        assert result.source == "validator"
        assert result.context is None  # no extra keys → None

    def test_dict_extra_keys_go_to_context(self) -> None:
        result = coerce_warning_diagnostic({
            "message": "Warn",
            "node_id": "n1",
            "template": "${n1.stdout}",
            "unresolved_templates": ["${n1.stdout}"],
        })
        assert result.context is not None
        assert result.context["template"] == "${n1.stdout}"
        assert result.context["unresolved_templates"] == ["${n1.stdout}"]

    def test_type_key_falls_back_to_source(self) -> None:
        """Legacy runtime warning dicts use 'type' not 'source'."""
        result = coerce_warning_diagnostic({
            "message": "API rate limited",
            "node_id": "call-api",
            "type": "api_warning",
        })
        assert result.source == "api_warning"
        # 'type' is not a known Diagnostic field, so it also lands in context
        assert (result.context or {}).get("type") == "api_warning"

    def test_source_takes_priority_over_type(self) -> None:
        result = coerce_warning_diagnostic({
            "message": "Warn",
            "source": "validator",
            "type": "api_warning",
        })
        assert result.source == "validator"

    def test_plain_string_input(self) -> None:
        result = coerce_warning_diagnostic("raw warning string")
        assert result.severity == Severity.WARNING
        assert result.message == "raw warning string"
        assert result.source == "runtime"

    def test_empty_dict_produces_default_message(self) -> None:
        result = coerce_warning_diagnostic({})
        assert result.message == "No message"
        assert result.source == "runtime"


class TestCoerceErrorDiagnostic:
    """Tests for the legacy-error-dict-to-Diagnostic bridge."""

    def test_passthrough_for_diagnostic_object(self) -> None:
        original = Diagnostic(severity=Severity.ERROR, message="already ok", source="runtime")
        assert coerce_error_diagnostic(original) is original

    def test_dict_with_enrichment_context(self) -> None:
        result = coerce_error_diagnostic({
            "message": "HTTP 422",
            "node_id": "create-issue",
            "source": "runtime",
            "category": "api_validation",
            "status_code": 422,
            "raw_response": {"error": "bad request"},
        })
        assert result.severity == Severity.ERROR
        assert result.message == "HTTP 422"
        assert result.node_id == "create-issue"
        assert result.source == "runtime"
        assert result.context is not None
        assert result.context["category"] == "api_validation"
        assert result.context["status_code"] == 422
        assert result.context["raw_response"] == {"error": "bad request"}

    def test_plain_string_input(self) -> None:
        result = coerce_error_diagnostic("unexpected failure")
        assert result.severity == Severity.ERROR
        assert result.message == "unexpected failure"

    def test_empty_dict_produces_default_message(self) -> None:
        result = coerce_error_diagnostic({})
        assert result.message == "Unknown error"
        assert result.source == "runtime"
