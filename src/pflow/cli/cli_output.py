"""Click-based implementation of OutputInterface."""

from typing import Callable, Optional

import click

from pflow.core.output_controller import OutputController
from pflow.execution.output_interface import OutputInterface


class CliOutput(OutputInterface):
    """Click-based implementation of OutputInterface.

    This class adapts the existing OutputController and Click functions
    to implement the OutputInterface protocol, allowing the CLI to use
    the display-agnostic execution services.
    """

    def __init__(
        self,
        output_controller: OutputController,
        verbose: bool = False,
        output_format: str = "text",
    ):
        """Initialize the CLI output handler.

        Args:
            output_controller: The OutputController for interactive mode detection
            verbose: Whether to show verbose output
            output_format: The output format ("text" or "json")
        """
        self.output_controller = output_controller
        self.verbose = verbose
        self.output_format = output_format

    def show_progress(self, message: str, is_error: bool = False) -> None:
        """Display a progress message.

        Progress messages are only shown in interactive mode to avoid
        cluttering piped output or JSON responses.
        """
        if self.output_controller.is_interactive():
            click.echo(message, err=is_error)

    def show_result(self, data: str) -> None:
        """Display result data (always to stdout)."""
        click.echo(data)

    def show_error(self, title: str, details: Optional[str] = None) -> None:
        """Display an error message."""
        if self.output_format != "json":
            click.echo(f"❌ {title}", err=True)
            if details and self.verbose:
                click.echo(details, err=True)

    def show_success(self, message: str) -> None:
        """Display a success message."""
        if self.output_format != "json":
            click.echo(f"✅ {message}")

    def create_node_callback(self) -> Optional[Callable[[str, str, Optional[float], int], None]]:
        """Create callback for node execution progress."""
        return self.output_controller.create_progress_callback()

    def is_interactive(self) -> bool:
        """Check if output is interactive (not piped/JSON)."""
        return self.output_controller.is_interactive()
