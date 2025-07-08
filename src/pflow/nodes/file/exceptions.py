"""File operation exceptions."""


class NonRetriableError(Exception):
    """Exception for errors that should not be retried.

    Use this for validation errors or conditions that will not
    change with retries (e.g., wrong file type, invalid parameters).
    """

    pass
