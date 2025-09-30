"""Central output control for interactive vs non-interactive execution modes."""

import sys
from typing import Callable, Optional

import click


class OutputController:
    """Central output control based on execution mode.

    Determines whether pflow is running interactively (terminal) or
    non-interactively (piped/automated) and controls output accordingly.

    Rules for interactive mode detection:
    1. If print_flag is True then is_interactive returns False
    2. If output_format equals "json" then is_interactive returns False
    3. If stdin_tty is False then is_interactive returns False
    4. If stdout_tty is False then is_interactive returns False
    5. Only if all conditions pass is the mode considered interactive
    """

    def __init__(
        self,
        print_flag: bool = False,
        output_format: str = "text",
        stdin_tty: Optional[bool] = None,
        stdout_tty: Optional[bool] = None,
    ):
        """Initialize output controller with execution mode parameters.

        Args:
            print_flag: CLI flag -p/--print to force non-interactive mode
            output_format: Output format (text/json), json implies non-interactive
            stdin_tty: Override for sys.stdin.isatty() (for testing)
            stdout_tty: Override for sys.stdout.isatty() (for testing)
        """
        self.print_flag = print_flag
        self.output_format = output_format

        # Handle Windows edge case where sys.stdin can be None
        if stdin_tty is not None:
            self.stdin_tty = stdin_tty
        elif sys.stdin is None:
            self.stdin_tty = False
        else:
            self.stdin_tty = sys.stdin.isatty()

        if stdout_tty is not None:
            self.stdout_tty = stdout_tty
        elif sys.stdout is None:
            self.stdout_tty = False
        else:
            self.stdout_tty = sys.stdout.isatty()

    def is_interactive(self) -> bool:
        """Determine if running in interactive mode.

        Returns:
            True if running in interactive terminal mode, False otherwise
        """
        # Rule 1: -p flag forces non-interactive
        if self.print_flag:
            return False

        # Rule 2: JSON output format implies non-interactive
        if self.output_format == "json":
            return False

        # Rules 3 & 4: Both stdin AND stdout must be TTY for interactive
        return self.stdin_tty and self.stdout_tty

    def _handle_node_start(self, node_id: str, indent: str) -> None:
        """Handle node_start event display.

        Args:
            node_id: The node identifier
            indent: Indentation string based on depth
        """
        click.echo(f"{indent}  {node_id}...", err=True, nl=False)

    def _handle_node_complete(
        self,
        duration_ms: Optional[float],
        error_message: Optional[str],
        ignore_errors: bool,
        is_modified: bool,
        is_error: bool,
    ) -> None:
        """Handle node_complete event display.

        Args:
            duration_ms: Execution duration in milliseconds
            error_message: Error message for failed nodes
            ignore_errors: Whether errors are being ignored
            is_modified: Whether node was modified during repair
            is_error: Whether this is a fatal error
        """
        if is_error:
            # Fatal error - the shell node already logged the error message
            # Don't print anything else as the line is already broken
            return

        if error_message and ignore_errors:
            # Warning - command failed but continuing
            warning_text = click.style(f" ⚠️  {error_message} but continuing", fg="yellow")
            if duration_ms is not None:
                success_text = click.style(f" | ✓ {duration_ms / 1000:.1f}s", fg="green")
                click.echo(f"{warning_text}{success_text}", err=True)
            else:
                click.echo(warning_text, err=True)
        elif is_modified and duration_ms is not None:
            # Modified node during repair
            success_text = click.style(f" ✓ {duration_ms / 1000:.1f}s", fg="green")
            mod_text = click.style(" [repaired]", fg="cyan")
            click.echo(f"{success_text}{mod_text}", err=True)
        elif duration_ms is not None:
            # Normal success
            click.echo(click.style(f" ✓ {duration_ms / 1000:.1f}s", fg="green"), err=True)
        else:
            click.echo(click.style(" ✓", fg="green"), err=True)

    def _handle_node_cached(self) -> None:
        """Handle node_cached event display."""
        click.echo(click.style(" ↻ cached", fg="blue", dim=True), err=True)

    def _handle_node_warning(self, duration_ms: Optional[float]) -> None:
        """Handle node_warning event display.

        Args:
            duration_ms: Contains warning message when event is node_warning
        """
        warning_msg = duration_ms if isinstance(duration_ms, str) else "API warning"
        warning_text = click.style(f" ⚠️  {warning_msg}", fg="yellow")
        click.echo(warning_text, err=True)

    def _handle_workflow_start(self, node_id: str, indent: str) -> None:
        """Handle workflow_start event display.

        Args:
            node_id: Contains node count for workflow_start
            indent: Indentation string based on depth
        """
        click.echo(f"{indent}Executing workflow ({node_id} nodes):", err=True)

    def create_progress_callback(self) -> Optional[Callable]:
        """Create progress callback for workflow execution.

        Returns:
            Callback function if interactive, None if non-interactive
        """
        if not self.is_interactive():
            return None

        def progress_callback(
            node_id: str,
            event: str,
            duration_ms: Optional[float] = None,
            depth: int = 0,
            error_message: Optional[str] = None,
            ignore_errors: bool = False,
            is_modified: bool = False,
            is_error: bool = False,
        ) -> None:
            """Display progress for node execution.

            Args:
                node_id: The node identifier or count for workflow_start
                event: Event type (node_start, node_complete, node_cached, workflow_start, node_error)
                duration_ms: Execution duration in milliseconds (for complete events)
                depth: Nesting depth for indentation
                error_message: Error message for failed nodes
                ignore_errors: Whether errors are being ignored (warning vs error)
                is_modified: Whether node was modified during repair
                is_error: Whether this is a fatal error
            """
            indent = "  " * depth

            # Dispatch to appropriate handler based on event type
            if event == "node_start":
                self._handle_node_start(node_id, indent)
            elif event == "node_complete":
                self._handle_node_complete(duration_ms, error_message, ignore_errors, is_modified, is_error)
            elif event == "node_cached":
                self._handle_node_cached()
            elif event == "node_warning":
                self._handle_node_warning(duration_ms)
            elif event == "workflow_start":
                self._handle_workflow_start(node_id, indent)

        return progress_callback

    def echo_progress(self, message: str) -> None:
        """Output progress message if interactive.

        Args:
            message: Progress message to display
        """
        if self.is_interactive():
            click.echo(message, err=True)

    def echo_result(self, data: str) -> None:
        """Output result data to stdout.

        Always outputs to stdout regardless of mode.

        Args:
            data: Result data to output
        """
        click.echo(data)

    def should_show_prompts(self) -> bool:
        """Check if interactive prompts should be shown.

        Returns:
            True if prompts should be displayed, False otherwise
        """
        return self.is_interactive()
