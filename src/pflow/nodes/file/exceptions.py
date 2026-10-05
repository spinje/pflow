"""File operation exceptions."""

from pflow.core.exceptions import PflowError


class NonRetriableError(PflowError):
    """Exception for errors that should not be retried.

    Use this for validation errors or conditions that will not
    change with retries (e.g., wrong file type, invalid parameters).
    """

    retriable = False
