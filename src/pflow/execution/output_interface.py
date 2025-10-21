"""Abstract interface for all output display operations."""

from typing import Callable, Optional, Protocol


class OutputInterface(Protocol):
    """Abstract interface for all output display operations.

    This protocol defines the contract for output display implementations,
    allowing different frontends (CLI, web, REPL) to provide their own
    display logic while the execution services remain display-agnostic.
    """

    def show_progress(self, message: str, is_error: bool = False) -> None:
        """Display a progress message.

        Args:
            message: The progress message to display
            is_error: Whether this is an error message (affects output stream)
        """
        ...

    def show_result(self, data: str) -> None:
        """Display result data (always to stdout).

        Args:
            data: The result data to display
        """
        ...

    def show_error(self, title: str, details: Optional[str] = None) -> None:
        """Display an error message.

        Args:
            title: The main error message
            details: Optional additional error details
        """
        ...

    def show_success(self, message: str) -> None:
        """Display a success message.

        Args:
            message: The success message to display
        """
        ...

    def show_warning(self, message: str) -> None:
        """Display a warning message.

        Args:
            message: The warning message to display
        """
        ...

    def create_node_callback(self) -> Optional[Callable]:
        """Create callback for node execution progress.

        Returns:
            Optional callback function for progress tracking, or None if
            not in interactive mode.
        """
        ...

    def is_interactive(self) -> bool:
        """Check if output is interactive (not piped/JSON).

        Returns:
            True if output is interactive, False otherwise
        """
        ...
