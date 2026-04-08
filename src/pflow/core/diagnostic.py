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

    Identity ignores context, title, and suggestions — these are display data, not identity.
    """

    severity: Severity
    message: str
    title: str | None = None
    suggestions: list[str] | None = None
    node_id: str | None = None
    source: str = ""
    context: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.suggestions, str):
            raise TypeError(
                f"Diagnostic.suggestions must be list[str] | None, got str: {self.suggestions!r}. "
                f"Wrap in a list: suggestions=[{self.suggestions!r}]"
            )

    def __eq__(self, other: object) -> bool:
        # Identity is (severity, source, node_id, message) — context, title, and
        # suggestions are deliberately excluded. This is LOAD-BEARING for the
        # dual-propagation-path dedup architecture (Task 143 decision): child
        # workflow diagnostics flow through BOTH the validation path (_add_child_provenance
        # in core/workflow/validator.py) AND the runtime path
        # (_propagate_child_parser_warnings in runtime/workflow_executor.py).
        # Both paths produce semantically-identical diagnostics with potentially-
        # different context enrichment. Dedup must collapse them to one. Adding
        # context/title/suggestions to identity would break that collapse and
        # resurface duplicate warnings users already fixed.
        if not isinstance(other, Diagnostic):
            return NotImplemented
        return (
            self.severity == other.severity
            and self.source == other.source
            and self.node_id == other.node_id
            and self.message == other.message
        )

    def __hash__(self) -> int:
        # Must match __eq__'s identity tuple exactly, for the same dedup reasons
        # documented above. Do NOT add context/title/suggestions here.
        return hash((self.severity, self.source, self.node_id, self.message))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the structured JSON shape."""
        result: dict[str, Any] = {
            "severity": self.severity.value,
            "message": self.message,
            "source": self.source,
        }
        if self.title is not None:
            result["title"] = self.title
        if self.suggestions is not None:
            result["suggestions"] = list(self.suggestions)
        if self.node_id is not None:
            result["node_id"] = self.node_id
        if self.context:
            result["context"] = deepcopy(self.context)
        return result

    def to_display_dict(self) -> dict[str, Any]:
        """Serialize with context merged into top-level keys for display consumers."""
        result = self.to_dict()
        # Reuse the deep copy already made by to_dict() — no second deepcopy.
        ctx = result.get("context")
        if ctx:
            for key, value in ctx.items():
                result.setdefault(key, value)
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


def format_child_provenance(step_id: str, message: str) -> str:
    """Format provenance message for a child sub-workflow diagnostic.

    Used by both validation and runtime propagation paths. Both MUST use this
    function so dedup collapses identical child diagnostics from the two paths.

    **Dedup invariant**: the validation path (``_add_child_provenance`` in
    ``core/workflow/validator.py``) and the runtime path
    (``_propagate_child_parser_warnings`` in ``runtime/workflow_executor.py``)
    produce semantically-identical diagnostics for the same child-workflow
    warning. ``Diagnostic.__hash__`` includes the message string, so those two
    paths MUST produce byte-identical messages or dedup fails and users see
    duplicates. ANY new path that wraps child diagnostics with parent context
    MUST go through this helper, and MUST also use ``node_id=d.node_id or step_id``
    and ``setdefault`` for ``sub_workflow_step`` / ``sub_workflow_path`` context
    keys — see the Task 143 "Dual-Propagation-Path Problem" section for history.
    """
    return f"In step '{step_id}' sub-workflow: {message}"


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
    if diagnostic.suggestions:
        for suggestion in diagnostic.suggestions:
            line += f"\n    → {suggestion}"
    return line


def _format_error_diagnostic(
    diagnostic: Diagnostic,
    verbose: bool,
    error_number: int | None = None,
) -> str:
    """Render one ERROR diagnostic in the unified titled format."""
    lines: list[str] = []
    context = diagnostic.context or {}

    # 1. Title line
    title = diagnostic.title or _CATEGORY_TITLES.get(context.get("category", ""), "Error")
    prefix = f"Error {error_number}" if error_number is not None else "Error"
    lines.append(f"{prefix}: {title}")
    lines.append("")

    # 2. Message
    lines.append(diagnostic.message)

    # 3. Location (At:)
    location = _format_location(diagnostic, context)
    if location:
        lines.append(f"  At: {location}")

    # 4. Context blocks (universal — called for ALL error types)
    context_lines = _format_all_context_blocks(diagnostic, context)
    if context_lines:
        lines.extend(context_lines)

    # 5. Suggestions
    suggestions = diagnostic.suggestions or []
    if suggestions:
        lines.append("")
        if len(suggestions) == 1:
            lines.append(f"  → {suggestions[0]}")
        else:
            lines.append("To fix this:")
            for i, s in enumerate(suggestions, 1):
                lines.append(f"  {i}. {s}")

    # 6. Verbose hint
    technical_details = context.get("technical_details")
    if verbose and technical_details:
        lines.append("")
        lines.append("Technical details:")
        lines.append(str(technical_details))
    elif technical_details:
        lines.append("")
        lines.append("Run with --verbose for technical details.")

    return "\n".join(lines)


def _format_location(diagnostic: Diagnostic, context: dict[str, Any]) -> str | None:
    """Build the At: location line from node_id, path, and line."""
    parts: list[str] = []
    if diagnostic.node_id:
        parts.append(f"node '{diagnostic.node_id}'")
    if (path := context.get("path")) and path != "root":
        parts.append(path)
    if (line := context.get("line")) is not None:
        parts.append(f"line {line}")
    return ", ".join(parts) if parts else None


def _format_all_context_blocks(diagnostic: Diagnostic, context: dict[str, Any]) -> list[str]:
    """Render all context blocks for any error type."""
    lines: list[str] = []
    lines.extend(_format_compilation_context_lines(context))
    lines.extend(_format_similar_names_block(context))
    lines.extend(_format_exception_type_line(context))

    if (raw := context.get("raw_response")) and isinstance(raw, dict):
        lines.extend(_format_api_response_lines(raw))

    if (mcp_error := context.get("mcp_error")) and isinstance(mcp_error, dict):
        lines.extend(_format_mcp_error_lines(mcp_error))

    lines.extend(_format_available_fields_block(context))

    if "shell_command" in context:
        lines.extend(_format_shell_error_lines(context))

    return lines


def _format_compilation_context_lines(context: dict[str, Any]) -> list[str]:
    """Render compilation-specific context fields."""
    lines: list[str] = []
    if phase := context.get("phase"):
        lines.append(f"  Phase: {phase}")
    if node_type := context.get("node_type"):
        lines.append(f"  Node type: {node_type}")
    if sub_path := context.get("sub_workflow_path"):
        lines.append(f"  Sub-workflow: {sub_path}")
    if source_file := context.get("source_file"):
        lines.append(f"  Loaded from file: {source_file}")
    return lines


def _format_similar_names_block(context: dict[str, Any]) -> list[str]:
    """Render a 'Did you mean' list from similar_names context."""
    similar = context.get("similar_names")
    if not similar:
        return []
    lines = ["", "Did you mean one of these?"]
    for name in similar:
        lines.append(f"  - {name}")
    return lines


def _format_exception_type_line(context: dict[str, Any]) -> list[str]:
    """Render exception type when available (for generic exceptions)."""
    if exc_type := context.get("exception_type"):
        return [f"  Type: {exc_type}"]
    return []


def _format_available_fields_block(context: dict[str, Any]) -> list[str]:
    """Render available field suggestions when provided in diagnostic context.

    Producers populate ``available_fields_label`` to describe what the list
    contains (e.g. "outputs", "nodes", "inputs", "parameters"). The fallback
    ``"fields"`` is deliberately generic so it is never technically wrong —
    producers that want accurate wording must set the label explicitly.
    """
    available = context.get("available_fields")
    if not available:
        return []

    label = context.get("available_fields_label", "fields")
    total = context.get("available_fields_total", len(available))
    lines = [
        "",
        f"  Available {label} (showing {min(len(available), 5)} of {total}):",
    ]
    for field_name in available[:5]:
        lines.append(f"    - {field_name}")
    if len(available) > 5:
        lines.append(f"    ... and {len(available) - 5} more (in error details)")
    return lines


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
    command = context.get("shell_command") or ""
    command_display = command[:200] + "..." if len(command) > 200 else command
    lines.append(f"    Command: {command_display}")
    if stdout := context.get("shell_stdout"):
        stdout_preview = stdout[:300] + "..." if len(stdout) > 300 else stdout
        lines.append(f"    Stdout: {stdout_preview}")
    if stderr := context.get("shell_stderr"):
        stderr_preview = stderr[:300] + "..." if len(stderr) > 300 else stderr
        lines.append(f"    Stderr: {stderr_preview}")
    return lines


_CATEGORY_TITLES: dict[str, str] = {
    "compilation": "Compilation Failed",
    "max_visits": "Infinite Loop Detected",
    "validation": "Validation Error",
    "parse_error": "Parse Error",
    "not_found": "Workflow Not Found",
    "file_not_found": "File Not Found",
    "permission_denied": "Permission Denied",
    "execution_failure": "Execution Failed",
    "api_validation": "API Validation Error",
    "template_error": "Template Error",
    "mcp": "MCP Error",
    "cli": "Error",
}


def exception_to_diagnostics(exception: Exception) -> list[Diagnostic]:
    """Convert any exception to one or more diagnostics.

    Dispatches to to_diagnostics() on exceptions that have it, falls back
    to _builtin_exception_diagnostic() for built-in exception types.
    """
    from dataclasses import replace

    annotated_node_id = getattr(exception, "_pflow_node_id", None)

    if hasattr(exception, "to_diagnostics"):
        diagnostics: list[Diagnostic] = exception.to_diagnostics()
    else:
        diagnostics = [_builtin_exception_diagnostic(exception, annotated_node_id)]

    # Apply engine node_id annotation via replace (separation of concerns —
    # to_diagnostics() methods don't read _pflow_node_id)
    if annotated_node_id:
        diagnostics = [replace(d, node_id=annotated_node_id) if not d.node_id else d for d in diagnostics]

    return diagnostics


def _builtin_exception_diagnostic(exception: Exception, annotated_node_id: str | None = None) -> Diagnostic:
    """Convert built-in exceptions (FileNotFoundError, PermissionError, etc.) to Diagnostic."""
    if isinstance(exception, FileNotFoundError):
        return Diagnostic(
            severity=Severity.ERROR,
            message=str(exception),
            title="File Not Found",
            suggestions=["Check the file path and ensure the file exists."],
            source="runtime",
            context={"category": "file_not_found"},
        )

    if isinstance(exception, PermissionError):
        message = str(exception) if str(exception) else "Permission denied"
        return Diagnostic(
            severity=Severity.ERROR,
            message=message,
            title="Permission Denied",
            suggestions=["Check file permissions and access rights."],
            source="runtime",
            context={"category": "permission_denied"},
        )

    if isinstance(exception, UnicodeDecodeError):
        return Diagnostic(
            severity=Severity.ERROR,
            message="File must be valid UTF-8 text.",
            title="Encoding Error",
            suggestions=["Ensure the file is saved as UTF-8."],
            source="runtime",
            context={"category": "validation"},
        )

    if isinstance(exception, ValueError):
        category = "execution_failure" if annotated_node_id else "validation"
        title = "Execution Failed" if annotated_node_id else "Validation Error"
        return Diagnostic(
            severity=Severity.ERROR,
            message=str(exception),
            title=title,
            node_id=annotated_node_id,
            source="runtime",
            context={"category": category},
        )

    return Diagnostic(
        severity=Severity.ERROR,
        message=str(exception),
        title="Execution Failed",
        node_id=annotated_node_id,
        source="runtime",
        context={
            "category": "execution_failure",
            "exception_type": type(exception).__name__,
        },
    )
