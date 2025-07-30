"""Custom exceptions for pflow."""

from typing import Optional


class PflowError(Exception):
    """Base exception for all pflow errors."""

    pass


class WorkflowExecutionError(PflowError):
    """Error during nested workflow execution."""

    def __init__(
        self, message: str, workflow_path: Optional[list[str]] = None, original_error: Optional[Exception] = None
    ):
        self.workflow_path = workflow_path or []
        self.original_error = original_error

        # Build detailed message
        if workflow_path:
            path_str = " -> ".join(workflow_path)
            message = f"{message}\nWorkflow path: {path_str}"
        if original_error:
            message = f"{message}\nOriginal error: {original_error!s}"

        super().__init__(message)


class CircularWorkflowReferenceError(WorkflowExecutionError):
    """Circular reference detected in workflow execution."""

    pass


class WorkflowExistsError(PflowError):
    """Raised when attempting to save a workflow that already exists."""

    pass


class WorkflowNotFoundError(PflowError):
    """Raised when a workflow cannot be found."""

    pass


class WorkflowValidationError(PflowError):
    """Raised when workflow validation fails."""

    pass
