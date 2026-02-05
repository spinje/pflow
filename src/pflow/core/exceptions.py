"""Custom exceptions for pflow."""

from typing import Optional


class PflowError(Exception):
    """Base exception for all pflow errors."""

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


class CriticalPlanningError(PflowError):
    """Raised when a critical planning node fails and cannot provide meaningful fallback.

    This error indicates the planning flow should abort immediately as continuing
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
