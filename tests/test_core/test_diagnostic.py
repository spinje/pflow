"""Tests for the unified Diagnostic model and exception conversion helpers."""

from __future__ import annotations

import pytest

from pflow.core.diagnostic import (
    Diagnostic,
    Severity,
    deduplicate_diagnostics,
    exception_to_diagnostics,
)
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.exceptions import (
    CompilationError,
    MarkdownParseError,
    MaxNodeVisitsError,
    SchemaValidationError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError


def test_suggestions_rejects_bare_string() -> None:
    """Passing a bare string to suggestions raises TypeError (defense-in-depth for rename)."""
    with pytest.raises(TypeError, match="must be list"):
        Diagnostic(severity=Severity.ERROR, message="test", suggestions="bare string")  # type: ignore[arg-type]


def test_to_dict_does_not_leak_suggestions_reference() -> None:
    """Mutating the serialized dict must not corrupt the source Diagnostic."""
    d = Diagnostic(severity=Severity.ERROR, message="m", suggestions=["original"], source="runtime")
    payload = d.to_dict()
    payload["suggestions"].append("injected")
    assert d.suggestions == ["original"], "to_dict() leaked suggestions by reference"


def test_diagnostic_identity_ignores_context() -> None:
    """Diagnostics with the same core fields deduplicate even if context differs."""
    first = Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        node_id="fetch",
        message="Nested access requires JSON",
        title="Template Warning",
        suggestions=["Ensure valid JSON."],
        context={"template": "${fetch.stdout.value}"},
    )
    second = Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        node_id="fetch",
        message="Nested access requires JSON",
        title="Different Title",
        suggestions=["Different suggestion."],
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
        suggestions=["Check API credentials."],
        context={"category": "api_validation", "raw_response": {"api_key": "secret", "error": "bad"}},
    )

    structured = diagnostic.to_dict()
    flattened = diagnostic.to_display_dict()

    assert structured == {
        "severity": "error",
        "source": "runtime",
        "node_id": "send",
        "message": "HTTP request failed",
        "suggestions": ["Check API credentials."],
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
        suggestions=["Rename to '## Inputs'."],
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
            title="Compilation Failed",
            suggestions=["Use a registered node type."],
            context={
                "category": "compilation",
                "phase": "node_import",
                "node_type": "custom-node",
                "sub_workflow_path": "./child.pflow.md",
            },
        )
    ]


def test_exception_to_diagnostics_workflow_validation_error_passes_through() -> None:
    """WorkflowValidationError preserves already-constructed validation Diagnostics."""
    original = [
        Diagnostic(
            severity=Severity.ERROR,
            message="Missing input",
            title="Validation Error",
            suggestions=["Declare the input."],
            source="validation",
            context={"category": "validation", "path": "inputs.name"},
        ),
        Diagnostic(
            severity=Severity.ERROR,
            message="Unknown node type",
            title="Validation Error",
            source="validation",
            context={"category": "validation"},
        ),
    ]
    diagnostics = exception_to_diagnostics(WorkflowValidationError(validation_errors=original))

    assert len(diagnostics) == 2
    assert diagnostics[0].message == "Missing input"
    assert diagnostics[0].suggestions == ["Declare the input."]
    assert (diagnostics[0].context or {}).get("path") == "inputs.name"
    assert diagnostics[1].message == "Unknown node type"


def test_exception_to_diagnostics_structured_parser_and_schema_errors() -> None:
    """Markdown and schema validation exceptions preserve source-specific context."""
    parse_diag = exception_to_diagnostics(MarkdownParseError("Bad heading", line=42, suggestion="Use ## Steps."))[0]
    schema_diag = exception_to_diagnostics(
        SchemaValidationError("Bad node type", path="nodes[0].type", suggestion="Use 'shell'.")
    )[0]

    assert parse_diag.source == "parser"
    assert parse_diag.message == "Bad heading"  # raw_message, line goes to context
    assert parse_diag.suggestions == ["Use ## Steps."]
    assert (parse_diag.context or {}).get("category") == "parse_error"
    assert (parse_diag.context or {}).get("line") == 42

    assert schema_diag.source == "validation"
    assert schema_diag.message == "Bad node type"
    assert schema_diag.suggestions == ["Use 'shell'."]
    assert (schema_diag.context or {}).get("category") == "validation"
    assert (schema_diag.context or {}).get("path") == "nodes[0].type"


def test_exception_to_diagnostics_runtime_and_user_friendly_errors() -> None:
    """Runtime exceptions preserve node annotations and user-facing details."""
    node_error = ValueError("timeout")
    node_error._pflow_node_id = "fetch-data"  # type: ignore[attr-defined]

    # Each case: (exception, source, category, suggestions)
    # suggestions is now list[str] | None (was str | None)
    cases: list[tuple[Exception, str, str, list[str] | None]] = [
        (
            WorkflowNotFoundError("my-flow", similar_names=["my-flow-v2"]),
            "runtime",
            "not_found",
            ["Use 'pflow list' to see all available workflows."],
        ),
        (
            MaxNodeVisitsError("loop", visit_count=101, max_visits=100),
            "runtime",
            "max_visits",
            ["Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional."],
        ),
        (
            UserFriendlyError("Bad input", "Value is invalid.", ["Set foo=bar"]),
            "runtime",
            "cli",
            ["Set foo=bar"],
        ),
        (
            MCPError(title="Missing MCP", explanation="No tool", suggestions=["Sync MCP"]),
            "runtime",
            "mcp",
            ["Sync MCP"],
        ),
        (
            OutputResolutionError(
                failures=[
                    {
                        "output_name": "result",
                        "source_expr": "${branch_a.stdout}",
                        "template": "${branch_a.stdout}",
                        "unresolved_references": [
                            {
                                "var": "branch_a.stdout",
                                "root": "branch_a",
                                "status": "absent",
                                "in_coalesce": False,
                                "coalesce_expr": None,
                                "peer_suggestions": [],
                            }
                        ],
                        "available_context_keys": [],
                    }
                ]
            ),
            "runtime",
            "template_error",
            None,  # No canned suggestions — structured renderer emits per-ref fixes
        ),
        (
            FileNotFoundError("missing"),
            "runtime",
            "file_not_found",
            ["Check the file path and ensure the file exists."],
        ),
        (
            PermissionError("denied"),
            "runtime",
            "permission_denied",
            ["Check file permissions and access rights."],
        ),
        (node_error, "runtime", "execution_failure", None),
        (RuntimeError("boom"), "runtime", "execution_failure", None),
    ]

    for exception, source, category, suggestions in cases:
        diagnostic = exception_to_diagnostics(exception)[0]
        assert diagnostic.source == source
        assert (diagnostic.context or {}).get("category") == category
        assert diagnostic.suggestions == suggestions

    node_diagnostic = exception_to_diagnostics(node_error)[0]
    assert node_diagnostic.node_id == "fetch-data"


def test_format_diagnostic_renders_rich_error_context() -> None:
    """Error diagnostics render title, node ID, shell details, and suggestions."""
    diagnostic = Diagnostic(
        severity=Severity.ERROR,
        source="runtime",
        node_id="build",
        message="Shell command failed",
        suggestions=["Fix the shell command."],
        context={
            "category": "execution_failure",
            "shell_command": "npm run build",
            "shell_stderr": "Missing dependency",
        },
    )

    rendered = format_diagnostic(diagnostic)

    # New titled format: "Error: {title}\n\n{message}\n  At: node 'build'\n..."
    assert "Error: Execution Failed" in rendered  # title from _CATEGORY_TITLES
    assert "Shell command failed" in rendered
    assert "node 'build'" in rendered
    assert "Fix the shell command." in rendered
    assert "npm run build" in rendered
    assert "Missing dependency" in rendered


def test_see_also_rejects_bare_string() -> None:
    """Passing a bare string to see_also raises TypeError (defense-in-depth)."""
    with pytest.raises(TypeError, match="must be list"):
        Diagnostic(severity=Severity.ERROR, message="test", see_also="branching")  # type: ignore[arg-type]


def test_see_also_rejects_space_containing_topic() -> None:
    """Topic names must be slug-safe. A space inside any entry would split
    into two topics when the renderer joins with spaces for ``pflow guide``.
    """
    with pytest.raises(TypeError, match="slug-safe"):
        Diagnostic(severity=Severity.ERROR, message="test", see_also=["sub workflows"])


def test_see_also_rejects_empty_topic_string() -> None:
    """Empty string topic would render as trailing whitespace in the command."""
    with pytest.raises(TypeError, match="slug-safe"):
        Diagnostic(severity=Severity.ERROR, message="test", see_also=[""])


def test_see_also_rejects_non_string_entry() -> None:
    """Non-string entries would format unpredictably via ``' '.join``."""
    with pytest.raises(TypeError, match="slug-safe"):
        Diagnostic(severity=Severity.ERROR, message="test", see_also=[123])  # type: ignore[list-item]


def test_see_also_excluded_from_identity() -> None:
    """Two Diagnostics differing only in see_also are equal and dedup to one."""
    first = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        node_id="n1",
        message="same message",
        see_also=["branching"],
    )
    second = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        node_id="n1",
        message="same message",
        see_also=None,
    )

    assert first == second
    assert hash(first) == hash(second)
    assert deduplicate_diagnostics([first, second]) == [first]


def test_to_dict_emits_see_also_when_present() -> None:
    """Serialized dict includes see_also when populated, omits it when None OR empty."""
    with_link = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        message="rule-class error",
        see_also=["branching", "sub-workflows"],
    )
    without_link = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        message="slip error",
    )
    # Empty list must be omitted (symmetric with renderer, which skips empty)
    # so JSON consumers don't see a useless ``"see_also": []`` key.
    empty_link = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        message="defensively empty",
        see_also=[],
    )

    assert with_link.to_dict()["see_also"] == ["branching", "sub-workflows"]
    assert "see_also" not in without_link.to_dict()
    assert "see_also" not in empty_link.to_dict()


def test_to_dict_does_not_leak_see_also_reference() -> None:
    """Mutating the serialized see_also list must not corrupt the source."""
    diagnostic = Diagnostic(
        severity=Severity.ERROR,
        message="m",
        see_also=["branching"],
        source="validator",
    )
    payload = diagnostic.to_dict()
    payload["see_also"].append("injected")
    assert diagnostic.see_also == ["branching"], "to_dict() leaked see_also by reference"


def test_format_diagnostic_renders_see_also_line_single_topic() -> None:
    """Error diagnostic with one see_also topic renders 'See also: pflow guide X'."""
    diagnostic = Diagnostic(
        severity=Severity.ERROR,
        source="parser",
        message="Node 'x' is a routing target of 'r' but has no '- next:' directive.",
        title="Parse Error",
        suggestions=["Add '- next: end'."],
        see_also=["branching"],
        context={"category": "parse_error"},
    )

    rendered = format_diagnostic(diagnostic)

    assert "See also: pflow guide branching" in rendered


def test_format_diagnostic_renders_see_also_line_multi_topic() -> None:
    """Multiple see_also topics render space-separated (matching pflow guide invocation)."""
    diagnostic = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        message="cross-cutting rule error",
        title="Validation Error",
        see_also=["branching", "sub-workflows"],
        context={"category": "validation"},
    )

    rendered = format_diagnostic(diagnostic)

    assert "See also: pflow guide branching sub-workflows" in rendered


def test_format_diagnostic_omits_see_also_line_when_none() -> None:
    """Diagnostic without see_also does not render the 'See also:' line."""
    diagnostic = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        message="slip error",
        title="Validation Error",
        context={"category": "validation"},
    )

    rendered = format_diagnostic(diagnostic)

    assert "See also" not in rendered


def test_warning_rendering_ignores_see_also() -> None:
    """Warnings render as one-liners — see_also is deliberately unused on the warning path."""
    diagnostic = Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        message="A warning with a guide pointer attached.",
        see_also=["core"],
    )

    rendered = format_diagnostic(diagnostic)

    assert "See also" not in rendered


def test_markdown_parse_error_threads_see_also_through_to_diagnostics() -> None:
    """MarkdownParseError(see_also=...) produces a Diagnostic carrying the same list."""
    err = MarkdownParseError("Bad routing", suggestion="Add '- next:'", see_also=["branching"])

    diagnostic = err.to_diagnostics()[0]

    assert diagnostic.see_also == ["branching"]
    assert diagnostic.source == "parser"
    assert diagnostic.suggestions == ["Add '- next:'"]


def test_markdown_parse_error_without_see_also_produces_none() -> None:
    """MarkdownParseError without see_also produces a Diagnostic with see_also=None."""
    err = MarkdownParseError("Bad heading", line=42)

    diagnostic = err.to_diagnostics()[0]

    assert diagnostic.see_also is None


def test_all_see_also_literals_resolve_to_real_guide_topics() -> None:
    """Every ``see_also=[...]`` literal in src/pflow/ must name a real guide topic.

    Guards against typos in future annotations. Rendering a bogus topic would
    produce a ``pflow guide <typo>`` line that fails with "Unknown topic" when
    the agent runs it — loud failure, but erodes trust in the pointer.
    """
    import re
    from pathlib import Path

    from pflow.guide import list_topics

    known_topics = set(list_topics())
    src_root = Path(__file__).resolve().parents[2] / "src" / "pflow"
    assert src_root.is_dir(), f"src dir not found at {src_root}"

    # Match `see_also=["topic1", "topic2"]` — handles single/double quotes,
    # whitespace variations. We only care about literal lists at producer sites.
    pattern = re.compile(r"see_also\s*=\s*\[([^\]]*)\]")
    topic_re = re.compile(r'["\']([a-zA-Z0-9_-]+)["\']')

    found_any = False
    for py_file in src_root.rglob("*.py"):
        for match in pattern.finditer(py_file.read_text(encoding="utf-8")):
            found_any = True
            for topic_match in topic_re.finditer(match.group(1)):
                topic = topic_match.group(1)
                assert topic in known_topics, (
                    f"see_also literal references unknown topic {topic!r} in "
                    f"{py_file.relative_to(src_root)}; known topics: {sorted(known_topics)}"
                )

    assert found_any, (
        "No see_also=[...] literals found in src/pflow — regex drift or feature regressed. "
        "Expected at least the 8 annotated sites from Issue #311."
    )
