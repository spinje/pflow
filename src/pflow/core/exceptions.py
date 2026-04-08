"""Custom exceptions for pflow."""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity


class PflowError(Exception):
    """Base exception for all pflow errors."""

    def to_diagnostics(self) -> list[Diagnostic]:
        """Convert to diagnostic representation. Override in subclasses for rich output."""
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Error",
                source="runtime",
                context={
                    "category": "execution_failure",
                    "exception_type": type(self).__name__,
                },
            )
        ]


class WorkflowExistsError(PflowError):
    """Raised when attempting to save a workflow that already exists."""

    pass


class WorkflowNotFoundError(PflowError):
    """Raised when a workflow cannot be found or has an unsupported format."""

    def __init__(
        self,
        workflow_name: str,
        similar_names: list[str] | None = None,
        hint: str | None = None,
    ):
        self.workflow_name = workflow_name
        self.similar_names = similar_names or []
        self.hint = hint
        super().__init__(hint or f"Workflow '{workflow_name}' not found")

    def to_diagnostics(self) -> list[Diagnostic]:
        # When hint provides specific guidance (e.g., "convert .json to .pflow.md"),
        # don't dilute it with generic "list workflows" suggestion.
        suggestions = None if self.hint else ["Use 'pflow workflow list' to see all available workflows."]
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Workflow Not Found",
                suggestions=suggestions,
                source="runtime",
                context={
                    "category": "not_found",
                    "workflow_name": self.workflow_name,
                    "similar_names": self.similar_names,
                    "hint": self.hint,
                },
            )
        ]


class WorkflowValidationError(PflowError):
    """Raised when workflow validation fails.

    Carries both the blocking errors (``validation_errors``) and any
    warnings produced during the same validation pass (``validation_warnings``).
    The warnings are legitimate diagnostics that the user should still see
    alongside the errors — they're captured at raise time so downstream
    exception-to-result conversion can surface them without needing access
    to the original shared store.
    """

    def __init__(
        self,
        summary: str = "Workflow validation failed",
        validation_errors: list[Diagnostic] | None = None,
        validation_warnings: list[Diagnostic] | None = None,
    ):
        self.summary = summary
        self.validation_errors = validation_errors or []
        self.validation_warnings = validation_warnings or []
        super().__init__(summary)

    def to_diagnostics(self) -> list[Diagnostic]:
        return self.validation_errors or [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.summary,
                title="Validation Error",
                source="validation",
                context={"category": "validation"},
            )
        ]


class CriticalDiscoveryError(PflowError):
    """Raised when a critical discovery call fails and cannot provide meaningful fallback.

    This error indicates discovery should abort immediately as continuing
    would produce nonsensical or invalid results.
    """

    def __init__(self, node_name: str, reason: str, original_error: Exception | None = None):
        self.node_name = node_name
        self.reason = reason
        self.original_error = original_error

        message = f"{node_name} encountered a critical failure: {reason}"
        if original_error:
            message = f"{message}\nOriginal error: {original_error!s}"

        super().__init__(message)


class SchemaValidationError(PflowError):
    """Validation error for IR schema with helpful messages and field paths.

    Attributes:
        message: The validation error message
        path: Dotted path to the invalid field (e.g., "nodes[0].type")
        suggestion: Optional suggestion for fixing the error
    """

    def __init__(self, message: str, path: str = "", suggestion: str = ""):
        self.message = message
        self.path = path
        self.suggestion = suggestion

        full_message = "Validation error"
        if path:
            full_message += f" at {path}"
        full_message += f": {message}"
        if suggestion:
            full_message += f"\n{suggestion}"

        super().__init__(full_message)

    def to_diagnostics(self) -> list[Diagnostic]:
        ctx: dict[str, Any] = {"category": "validation"}
        if self.path:
            ctx["path"] = self.path
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.message,
                title="Validation Error",
                suggestions=[self.suggestion] if self.suggestion else None,
                source="validation",
                context=ctx,
            )
        ]


class MarkdownParseError(PflowError):
    """Error raised when markdown workflow content cannot be parsed.

    Attributes:
        line: Source line number where the error occurred (1-based).
        suggestion: Optional human-readable fix suggestion.
    """

    def __init__(
        self,
        message: str,
        line: int | None = None,
        suggestion: str | None = None,
    ):
        self.raw_message = message
        self.line = line
        self.suggestion = suggestion
        prefix = f"Line {line}: " if line is not None else ""
        full = f"{prefix}{message}"
        if suggestion:
            full += f"\n\n{suggestion}"
        super().__init__(full)

    def to_diagnostics(self) -> list[Diagnostic]:
        ctx: dict[str, Any] = {"category": "parse_error"}
        if self.line is not None:
            ctx["line"] = self.line
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.raw_message,
                title="Parse Error",
                suggestions=[self.suggestion] if self.suggestion else None,
                source="parser",
                context=ctx,
            )
        ]


class CompilationError(PflowError):
    """Error during IR compilation with rich context.

    Attributes:
        phase: The compilation phase where the error occurred
        node_id: ID of the node being compiled (if applicable)
        node_type: Type of the node being compiled (if applicable)
        details: Additional context about the error
        suggestion: Helpful suggestion for fixing the error
        wrapped_diagnostics: Structured diagnostics collected by a sub-validator
            before this exception was raised. When present, ``to_diagnostics()``
            returns them directly so the compile-time path preserves the same
            rich structure (paths, suggestions, similar_names, available_fields)
            that the pre-execution validator produces. Used by
            ``compile_validation.py`` to carry the ``validate_data_flow()`` list
            through the compiler boundary without flattening it to a string.
    """

    def __init__(
        self,
        message: str,
        phase: str = "unknown",
        node_id: str | None = None,
        node_type: str | None = None,
        details: dict[str, Any] | None = None,
        suggestion: str | None = None,
        wrapped_diagnostics: list[Diagnostic] | None = None,
    ):
        self.raw_message = message
        self.phase = phase
        self.node_id = node_id
        self.node_type = node_type
        self.details = details or {}
        self.suggestion = suggestion
        self.wrapped_diagnostics = wrapped_diagnostics

        parts = [f"compiler: {message}"]
        if phase != "unknown":
            parts.append(f"Phase: {phase}")
        if node_id:
            parts.append(f"Node ID: {node_id}")
        if node_type:
            parts.append(f"Node Type: {node_type}")
        if suggestion:
            parts.append(f"Suggestion: {suggestion}")

        super().__init__("\n".join(parts))

    def to_diagnostics(self) -> list[Diagnostic]:
        if self.wrapped_diagnostics:
            return list(self.wrapped_diagnostics)
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.raw_message,
                title="Compilation Failed",
                suggestions=[self.suggestion] if self.suggestion else None,
                node_id=self.node_id,
                source="compilation",
                context={
                    "category": "compilation",
                    "phase": self.phase,
                    "node_type": self.node_type,
                    "sub_workflow_path": self.details.get("sub_workflow_path"),
                },
            )
        ]


class MaxNodeVisitsError(RuntimeError):
    """Raised when a node exceeds the maximum allowed visits (loop guard)."""

    def __init__(self, node_id: str, visit_count: int, max_visits: int):
        self.node_id = node_id
        self.visit_count = visit_count
        self.max_visits = max_visits
        super().__init__(
            f"Node '{node_id}' exceeded maximum visits ({visit_count}/{max_visits}). "
            f"This likely indicates an infinite loop in the workflow. "
            f"Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional."
        )

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=(
                    f"Node '{self.node_id}' exceeded maximum visits "
                    f"({self.visit_count}/{self.max_visits}). "
                    f"This likely indicates an infinite loop in the workflow."
                ),
                title="Infinite Loop Detected",
                suggestions=["Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional."],
                node_id=self.node_id,
                source="runtime",
                context={
                    "category": "max_visits",
                    "visit_count": self.visit_count,
                    "max_visits": self.max_visits,
                },
            )
        ]
