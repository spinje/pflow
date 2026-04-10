"""Unified diagnostic type, exception conversion, and deduplication."""

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
    "template_error": "Template Resolution Failed",
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
        attached = getattr(exception, "_pflow_template_diagnostic", None)
        if isinstance(attached, Diagnostic):
            return attached

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
