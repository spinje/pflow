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
        ) -> None:
            """Display progress for node execution.

            Args:
                node_id: The node identifier or count for workflow_start
                event: Event type (node_start, node_complete, workflow_start)
                duration_ms: Execution duration in milliseconds (for complete events)
                depth: Nesting depth for indentation
            """
            indent = "  " * depth

            if event == "node_start":
                # Display node start with indentation
                click.echo(f"{indent}  {node_id}...", err=True, nl=False)
            elif event == "node_complete":
                # Display completion checkmark and duration
                if duration_ms is not None:
                    click.echo(f" ✓ {duration_ms / 1000:.1f}s", err=True)
                else:
                    click.echo(" ✓", err=True)
            elif event == "workflow_start":
                # Display workflow execution header with node count
                click.echo(f"{indent}Executing workflow ({node_id} nodes):", err=True)

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
