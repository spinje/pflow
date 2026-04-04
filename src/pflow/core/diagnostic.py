"""Unified diagnostic type for parser, validator, and runtime output."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Severity(Enum):
    """Diagnostic severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Diagnostic:
    """Single type for pflow diagnostics.

    Identity ignores context because context is mutable enrichment data.
    """

    severity: Severity
    message: str
    suggestion: str | None = None
    node_id: str | None = None
    source: str = ""
    context: dict[str, Any] | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Diagnostic):
            return NotImplemented
        return (
            self.severity == other.severity
            and self.source == other.source
            and self.node_id == other.node_id
            and self.message == other.message
        )

    def __hash__(self) -> int:
        return hash((self.severity, self.source, self.node_id, self.message))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the structured JSON shape."""
        result: dict[str, Any] = {
            "severity": self.severity.value,
            "message": self.message,
            "source": self.source,
        }
        if self.suggestion is not None:
            result["suggestion"] = self.suggestion
        if self.node_id is not None:
            result["node_id"] = self.node_id
        if self.context:
            result["context"] = deepcopy(self.context)
        return result

    def to_display_dict(self) -> dict[str, Any]:
        """Serialize with context merged into top-level keys for display consumers."""
        result = self.to_dict()
        if self.context:
            for key, value in self.context.items():
                result.setdefault(key, deepcopy(value))
        return result


def deduplicate_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Remove duplicate diagnostics while preserving first-seen order."""
    seen: set[Diagnostic] = set()
    result: list[Diagnostic] = []
    for diagnostic in diagnostics:
        if diagnostic not in seen:
            seen.add(diagnostic)
            result.append(diagnostic)
    return result


def coerce_warning_diagnostic(warning: Any) -> Diagnostic:
    """Convert a legacy warning payload to ``Diagnostic``."""
    if isinstance(warning, Diagnostic):
        return warning
    if isinstance(warning, dict):
        context = {
            key: value
            for key, value in warning.items()
            if key not in {"severity", "message", "suggestion", "node_id", "source"}
        }
        return Diagnostic(
            severity=Severity.WARNING,
            message=warning.get("message", "No message"),
            suggestion=warning.get("suggestion"),
            node_id=warning.get("node_id"),
            source=str(warning.get("source") or warning.get("type") or "runtime"),
            context=context or None,
        )
    return Diagnostic(severity=Severity.WARNING, message=str(warning), source="runtime")


def coerce_error_diagnostic(error: Any) -> Diagnostic:
    """Convert a legacy error payload to ``Diagnostic``."""
    if isinstance(error, Diagnostic):
        return error
    if isinstance(error, dict):
        context = {
            key: value
            for key, value in error.items()
            if key not in {"severity", "message", "suggestion", "node_id", "source"}
        }
        return Diagnostic(
            severity=Severity.ERROR,
            message=error.get("message", "Unknown error"),
            suggestion=error.get("suggestion"),
            node_id=error.get("node_id"),
            source=str(error.get("source") or "runtime"),
            context=context or None,
        )
    return Diagnostic(severity=Severity.ERROR, message=str(error), source="runtime")


def format_diagnostic(
    diagnostic: Diagnostic,
    verbose: bool = False,
    error_number: int | None = None,
) -> str:
    """Render one diagnostic to text."""
    if diagnostic.severity == Severity.ERROR:
        return _format_error_diagnostic(
            diagnostic,
            verbose=verbose,
            error_number=error_number,
        )
    return _format_warning_or_info_diagnostic(diagnostic)


def _format_warning_or_info_diagnostic(diagnostic: Diagnostic) -> str:
    """Render one WARNING or INFO diagnostic."""
    icon = "⚠" if diagnostic.severity == Severity.WARNING else "\N{INFORMATION SOURCE}"
    if diagnostic.node_id:
        line = f"  {icon} [{diagnostic.node_id}] {diagnostic.message}"
    else:
        line = f"  {icon} {diagnostic.message}"
    if diagnostic.suggestion:
        line += f"\n    → {diagnostic.suggestion}"
    return line


def _format_error_diagnostic(
    diagnostic: Diagnostic,
    verbose: bool,
    error_number: int | None = None,
) -> str:
    """Render one ERROR diagnostic."""
    context = diagnostic.context or {}
    if diagnostic.source == "validation":
        return _format_validation_diagnostic(
            diagnostic,
            context,
            error_number=error_number,
        )
    if context.get("category") == "not_found":
        return _format_not_found_diagnostic(diagnostic, context)
    if context.get("title"):
        return _format_user_friendly_diagnostic(diagnostic, context, verbose=verbose)
    if context.get("category") == "max_visits":
        if error_number is not None:
            return _format_runtime_error_diagnostic(
                diagnostic,
                context,
                error_number=error_number,
            )
        return f"❌ {diagnostic.message}"
    if _is_simple_error_diagnostic(diagnostic, context):
        return _format_simple_error_diagnostic(
            diagnostic,
            context,
            error_number=error_number,
        )
    return _format_runtime_error_diagnostic(
        diagnostic,
        context,
        error_number=error_number,
    )


def _format_validation_diagnostic(
    diagnostic: Diagnostic,
    context: dict[str, Any],
    error_number: int | None = None,
) -> str:
    """Render a validation diagnostic."""
    if error_number is not None:
        lines = _format_runtime_error_header_lines(
            diagnostic,
            context,
            error_number=error_number,
        )
        if (path := context.get("path")) and path != "root":
            lines.append(f"  At: {path}")
        return "\n".join(lines)

    lines = [f"❌ {diagnostic.message}"]
    if (path := context.get("path")) and path != "root":
        lines.append(f"   At: {path}")
    if diagnostic.suggestion:
        lines.append(f"   👉 {diagnostic.suggestion}")
    return "\n".join(lines)


def _is_simple_error_diagnostic(diagnostic: Diagnostic, context: dict[str, Any]) -> bool:
    """Return whether this diagnostic uses the one-line error format."""
    return not diagnostic.node_id and context.get("category") in {
        "execution_failure",
        "file_not_found",
        "parse_error",
        "permission_denied",
        "validation",
    }


def _format_simple_error_diagnostic(
    diagnostic: Diagnostic,
    context: dict[str, Any],
    error_number: int | None = None,
) -> str:
    """Render a simple non-node error."""
    if error_number is not None:
        return "\n".join(
            _format_runtime_error_header_lines(
                diagnostic,
                context,
                error_number=error_number,
            )
        )
    if diagnostic.suggestion:
        return f"✗ {diagnostic.message}\n    → {diagnostic.suggestion}"
    return f"✗ {diagnostic.message}"


def _format_runtime_error_diagnostic(
    diagnostic: Diagnostic,
    context: dict[str, Any],
    error_number: int | None = None,
) -> str:
    """Render a runtime or compilation diagnostic with optional context blocks."""
    lines = _format_runtime_error_header_lines(
        diagnostic,
        context,
        error_number=error_number,
    )
    lines.extend(_format_runtime_error_context_lines(diagnostic, context))
    return "\n".join(lines)


def _format_runtime_error_header_lines(
    diagnostic: Diagnostic,
    context: dict[str, Any],
    error_number: int | None = None,
) -> list[str]:
    """Render the message, category, and suggestion lines for runtime diagnostics."""
    lines: list[str] = []
    if diagnostic.node_id:
        prefix = f"Error {error_number}" if error_number else "Error"
        lines.append(f"{prefix} at node '{diagnostic.node_id}':")
    elif error_number is not None:
        prefix = f"Error {error_number}" if error_number else "Error"
        lines.append(f"{prefix}:")
    if category := context.get("category"):
        lines.append(f"  Category: {category}")
    lines.append(f"  Message: {diagnostic.message}")

    if diagnostic.suggestion:
        lines.append("")
        lines.append(f"  Suggestion: {diagnostic.suggestion}")

    return lines


def _format_runtime_error_context_lines(
    diagnostic: Diagnostic,
    context: dict[str, Any],
) -> list[str]:
    """Render optional structured context blocks for runtime diagnostics."""
    lines: list[str] = []
    if diagnostic.source == "compilation":
        lines.extend(_format_compilation_context_lines(context))

    if (raw := context.get("raw_response")) and isinstance(raw, dict):
        lines.extend(_format_api_response_lines(raw))

    if (mcp_error := context.get("mcp_error")) and isinstance(mcp_error, dict):
        lines.extend(_format_mcp_error_lines(mcp_error))

    if context.get("category") == "template_error":
        lines.extend(_format_template_error_lines(context))

    if "shell_command" in context:
        lines.extend(_format_shell_error_lines(context))

    return lines


def _format_compilation_context_lines(context: dict[str, Any]) -> list[str]:
    """Render compilation-specific context fields."""
    lines: list[str] = []
    if node_type := context.get("node_type"):
        lines.append(f"  Node type: {node_type}")
    if sub_path := context.get("sub_workflow_path"):
        lines.append(f"  Sub-workflow: {sub_path}")
    return lines


def _format_template_error_lines(context: dict[str, Any]) -> list[str]:
    """Render template field suggestions for template errors."""
    available = context.get("available_fields")
    if not available:
        return []

    total = context.get("available_fields_total", len(available))
    lines = [
        "",
        f"  Available fields in node (showing {min(len(available), 5)} of {total}):",
    ]
    for field_name in available[:5]:
        lines.append(f"    - {field_name}")
    if len(available) > 5:
        lines.append(f"    ... and {len(available) - 5} more (in error details)")
    if context.get("available_fields_truncated"):
        lines.append("")
        lines.append("  📁 Complete field list available in trace file")
        lines.append("     ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json")
    return lines


def _format_not_found_diagnostic(diagnostic: Diagnostic, context: dict[str, Any]) -> str:
    """Render a not-found diagnostic."""
    if hint := context.get("hint"):
        return f"❌ {hint}"

    workflow_name = context.get("workflow_name", "unknown")
    lines = [f"❌ Workflow '{workflow_name}' not found."]

    similar_names = context.get("similar_names") or []
    if similar_names:
        lines.append("\nDid you mean one of these?")
        for name in similar_names:
            lines.append(f"  - {name}")
    elif diagnostic.suggestion:
        lines.append(f"\n{diagnostic.suggestion}")
    else:
        lines.append("\nUse 'pflow workflow list' to see available workflows.")

    return "\n".join(lines)


def _format_user_friendly_diagnostic(
    diagnostic: Diagnostic,
    context: dict[str, Any],
    verbose: bool,
) -> str:
    """Render UserFriendlyError-style diagnostics."""
    lines = [f"Error: {context['title']}", ""]

    if explanation := context.get("explanation"):
        lines.append(str(explanation))
        lines.append("")

    suggestions = context.get("suggestions") or []
    if not suggestions and diagnostic.suggestion:
        suggestions = [diagnostic.suggestion]

    if suggestions:
        lines.append("To fix this:")
        if len(suggestions) == 1:
            lines.append(f"  {suggestions[0]}")
        else:
            for index, suggestion in enumerate(suggestions, 1):
                lines.append(f"  {index}. {suggestion}")
        lines.append("")

    technical_details = context.get("technical_details")
    if verbose and technical_details:
        lines.append("Technical details:")
        lines.append(str(technical_details))
        lines.append("")
    elif technical_details:
        lines.append("Run with --verbose for technical details.")

    return "\n".join(lines).strip()


def _format_api_response_lines(raw_response: dict[str, Any]) -> list[str]:
    """Render HTTP API response details."""
    from pflow.core.security_utils import sanitize_parameters

    sanitized_raw = sanitize_parameters(raw_response)
    lines = ["", "  API Response:"]

    if errors_list := sanitized_raw.get("errors"):
        for api_error in errors_list[:3]:
            field = api_error.get("field", "unknown")
            message = api_error.get("message", api_error.get("code", "error"))
            lines.append(f"    - Field '{field}': {message}")
    elif message := sanitized_raw.get("message"):
        lines.append(f"    {message}")

    if doc_url := sanitized_raw.get("documentation_url"):
        lines.append("")
        lines.append(f"  Documentation: {doc_url}")

    return lines


def _format_mcp_error_lines(mcp_error: dict[str, Any]) -> list[str]:
    """Render MCP tool error details."""
    from pflow.core.security_utils import sanitize_parameters

    sanitized_mcp = sanitize_parameters(mcp_error)
    lines = ["", "  MCP Tool Error:"]

    if details := sanitized_mcp.get("details"):
        lines.append(f"    Field: {details.get('field')}")
        lines.append(f"    Expected: {details.get('expected')}")
        lines.append(f"    Received: {details.get('received')}")
    elif message := sanitized_mcp.get("message"):
        lines.append(f"    {message}")

    return lines


def _format_shell_error_lines(context: dict[str, Any]) -> list[str]:
    """Render shell command failure details."""
    lines = ["", "  Shell details:"]
    command = context.get("shell_command", "")
    command_display = command[:200] + "..." if len(command) > 200 else command
    lines.append(f"    Command: {command_display}")
    if stdout := context.get("shell_stdout"):
        stdout_preview = stdout[:300] + "..." if len(stdout) > 300 else stdout
        lines.append(f"    Stdout: {stdout_preview}")
    if stderr := context.get("shell_stderr"):
        stderr_preview = stderr[:300] + "..." if len(stderr) > 300 else stderr
        lines.append(f"    Stderr: {stderr_preview}")
    return lines


def exception_to_diagnostics(exception: Exception) -> list[Diagnostic]:  # noqa: C901
    """Convert any exception to one or more diagnostics."""
    from pflow.core.exceptions import (
        CompilationError,
        MarkdownParseError,
        MaxNodeVisitsError,
        SchemaValidationError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    )
    from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError

    annotated_node_id = getattr(exception, "_pflow_node_id", None)

    if isinstance(exception, CompilationError):
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=getattr(exception, "raw_message", str(exception)),
                suggestion=exception.suggestion,
                node_id=exception.node_id,
                source="compilation",
                context={
                    "category": "compilation",
                    "phase": exception.phase,
                    "node_type": exception.node_type,
                    "sub_workflow_path": (exception.details or {}).get("sub_workflow_path"),
                },
            )
        ]

    if isinstance(exception, MaxNodeVisitsError):
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(exception),
                suggestion="Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional.",
                node_id=exception.node_id,
                source="runtime",
                context={
                    "category": "max_visits",
                    "visit_count": exception.visit_count,
                    "max_visits": exception.max_visits,
                },
            )
        ]

    if isinstance(exception, WorkflowValidationError):
        diagnostics: list[Diagnostic] = []
        for error in exception.validation_errors:
            if isinstance(error, tuple):
                message = error[0] if len(error) >= 1 else str(exception)
                path = error[1] if len(error) >= 2 else ""
                suggestion = error[2] or None if len(error) >= 3 else None
                validation_context: dict[str, Any] = {"category": "validation"}
                if path:
                    validation_context["path"] = path
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        message=message,
                        suggestion=suggestion,
                        source="validation",
                        context=validation_context,
                    )
                )
            else:
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        message=str(error),
                        source="validation",
                        context={"category": "validation"},
                    )
                )
        return diagnostics or [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(exception),
                source="validation",
                context={"category": "validation"},
            )
        ]

    if isinstance(exception, SchemaValidationError):
        schema_context: dict[str, Any] = {"category": "validation"}
        if exception.path:
            schema_context["path"] = exception.path
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=exception.message,
                suggestion=exception.suggestion or None,
                source="validation",
                context=schema_context,
            )
        ]

    if isinstance(exception, MarkdownParseError):
        parser_context: dict[str, Any] = {"category": "parse_error"}
        if exception.line is not None:
            parser_context["line"] = exception.line
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(exception).split("\n\n", 1)[0],
                suggestion=exception.suggestion,
                node_id=annotated_node_id,
                source="parser",
                context=parser_context,
            )
        ]

    if isinstance(exception, WorkflowNotFoundError):
        suggestion = None
        if exception.similar_names:
            suggestion = f"Did you mean: {', '.join(exception.similar_names)}"
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(exception),
                suggestion=suggestion,
                source="runtime",
                context={
                    "category": "not_found",
                    "workflow_name": exception.workflow_name,
                    "similar_names": exception.similar_names,
                    "hint": exception.hint,
                },
            )
        ]

    if isinstance(exception, OutputResolutionError):
        suggestion = "; ".join(exception.suggestions) if exception.suggestions else None
        output_context: dict[str, Any] = {
            "category": "runtime",
            "title": exception.title,
            "explanation": exception.explanation,
            "suggestions": exception.suggestions,
            "technical_details": exception.technical_details,
            "failures": exception.failures,
        }
        if exception.failures:
            first_failure = exception.failures[0]
            if first_failure.get("output_name"):
                output_context["output_name"] = first_failure["output_name"]
            if first_failure.get("source_expr"):
                output_context["source_expr"] = first_failure["source_expr"]
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=exception.explanation,
                suggestion=suggestion,
                source="runtime",
                context=output_context,
            )
        ]

    if isinstance(exception, MCPError):
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=exception.explanation,
                suggestion="; ".join(exception.suggestions) if exception.suggestions else None,
                source="runtime",
                context={
                    "category": "mcp",
                    "title": exception.title,
                    "explanation": exception.explanation,
                    "suggestions": exception.suggestions,
                    "technical_details": exception.technical_details,
                },
            )
        ]

    if isinstance(exception, UserFriendlyError):
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=exception.explanation,
                suggestion="; ".join(exception.suggestions) if exception.suggestions else None,
                source="runtime",
                context={
                    "category": "cli",
                    "title": exception.title,
                    "explanation": exception.explanation,
                    "suggestions": exception.suggestions,
                    "technical_details": exception.technical_details,
                },
            )
        ]

    if isinstance(exception, FileNotFoundError):
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(exception),
                source="runtime",
                context={"category": "file_not_found"},
            )
        ]

    if isinstance(exception, PermissionError):
        message = str(exception) if str(exception) else "Permission denied"
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=message,
                source="runtime",
                context={"category": "permission_denied"},
            )
        ]

    if isinstance(exception, ValueError):
        context = {"category": "execution_failure" if annotated_node_id else "validation"}
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(exception),
                node_id=annotated_node_id,
                source="runtime",
                context=context,
            )
        ]

    return [
        Diagnostic(
            severity=Severity.ERROR,
            message=str(exception),
            node_id=annotated_node_id,
            source="runtime",
            context={
                "category": "execution_failure",
                "exception_type": type(exception).__name__,
            },
        )
    ]
