"""Custom exceptions for pflow."""

from typing import Optional


class PflowError(Exception):
    """Base exception for all pflow errors."""

    pass


class WorkflowExistsError(PflowError):
    """Raised when attempting to save a workflow that already exists."""

    pass


class WorkflowNotFoundError(PflowError):
    """Raised when a workflow cannot be found or has an unsupported format."""

    def __init__(
        self,
        workflow_name: str,
        similar_names: Optional[list[str]] = None,
        hint: str | None = None,
    ):
        self.workflow_name = workflow_name
        self.similar_names = similar_names or []
        self.hint = hint
        super().__init__(hint or f"Workflow '{workflow_name}' not found")

    def format_for_cli(self) -> str:
        """Format for text-mode CLI display."""
        if self.hint:
            return f"\u274c {self.hint}"
        lines = [f"\u274c Workflow '{self.workflow_name}' not found."]
        if self.similar_names:
            lines.append("\nDid you mean one of these?")
            for name in self.similar_names:
                lines.append(f"  - {name}")
        else:
            lines.append("\nUse 'pflow workflow list' to see available workflows.")
        return "\n".join(lines)


class WorkflowValidationError(PflowError):
    """Raised when workflow validation fails."""

    def __init__(
        self,
        summary: str = "Workflow validation failed",
        validation_errors: Optional[list[str | tuple[str, str, str]]] = None,
    ):
        self.summary = summary
        self.validation_errors = validation_errors or []
        super().__init__(summary)

    def format_for_cli(self) -> str:
        """Format for text-mode CLI display."""
        error_strings = []
        for err in self.validation_errors:
            if isinstance(err, tuple):
                msg, path, suggestion = err
                parts = [f"\u274c {msg}"]
                if path and path != "root":
                    parts.append(f"   At: {path}")
                if suggestion:
                    parts.append(f"   \U0001f449 {suggestion}")
                error_strings.append("\n".join(parts))
            else:
                error_strings.append(str(err))

        if error_strings:
            return "\n".join(error_strings)
        return f"\u274c {self.summary}"


class CriticalDiscoveryError(PflowError):
    """Raised when a critical discovery call fails and cannot provide meaningful fallback.

    This error indicates discovery should abort immediately as continuing
    would produce nonsensical or invalid results.
    """

    def __init__(self, node_name: str, reason: str, original_error: Optional[Exception] = None):
        self.node_name = node_name
        self.reason = reason
        self.original_error = original_error

        message = f"{node_name} encountered a critical failure: {reason}"
        if original_error:
            message = f"{message}\nOriginal error: {original_error!s}"

        super().__init__(message)


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

    def format_for_cli(self) -> str:
        """Format for text-mode CLI display."""
        return f"\u274c {self}"
