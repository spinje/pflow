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

    def _handle_batch_progress(
        self,
        node_id: str,
        indent: str,
        batch_current: int,
        batch_total: int,
        batch_success: bool,
    ) -> None:
        """Handle batch_progress event - update line in place.

        Uses carriage return to overwrite the current line with updated progress.
        Shows per-item success/failure status.

        Args:
            node_id: The node identifier
            indent: Indentation string based on depth
            batch_current: Number of items completed so far
            batch_total: Total number of items to process
            batch_success: Whether the just-completed item succeeded
        """
        status = click.style("✓", fg="green") if batch_success else click.style("✗", fg="red")
        # Use \r to return to line start and overwrite
        click.echo(f"\r{indent}  {node_id}... {batch_current}/{batch_total} {status}", err=True, nl=False)

    def _handle_node_complete(
        self,
        duration_ms: Optional[float],
        error_message: Optional[str],
        ignore_errors: bool,
        is_modified: bool,
        is_error: bool,
        is_batch: bool = False,
        batch_total: Optional[int] = None,
        batch_success_count: Optional[int] = None,
    ) -> None:
        """Handle node_complete event display.

        Args:
            duration_ms: Execution duration in milliseconds
            error_message: Error message for failed nodes
            ignore_errors: Whether errors are being ignored
            is_modified: Whether node was modified during repair
            is_error: Whether this is a fatal error
            is_batch: Whether this is a batch node completion
            batch_total: Total items in batch (for batch nodes)
            batch_success_count: Number of successful items (for batch nodes)
        """
        if is_error:
            if is_batch:
                # For batch errors, complete the line with error indicator
                click.echo(click.style(" FAILED", fg="red"), err=True)
            # For non-batch errors, shell node already logged - return to avoid double output
            return

        if is_batch:
            # Batch node: progress already showed count/status, just add timing
            if duration_ms is not None:
                timing_text = click.style(f" {duration_ms / 1000:.1f}s", fg="green")
                if is_modified:
                    mod_text = click.style(" [repaired]", fg="cyan")
                    click.echo(f"{timing_text}{mod_text}", err=True)
                else:
                    click.echo(timing_text, err=True)
            else:
                click.echo("", err=True)  # Just newline to complete the line
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
            # Batch progress parameters
            batch_current: Optional[int] = None,
            batch_total: Optional[int] = None,
            batch_success: Optional[bool] = None,
            is_batch: bool = False,
            batch_success_count: Optional[int] = None,
        ) -> None:
            """Display progress for node execution.

            Args:
                node_id: The node identifier or count for workflow_start
                event: Event type (node_start, node_complete, node_cached, workflow_start, batch_progress)
                duration_ms: Execution duration in milliseconds (for complete events)
                depth: Nesting depth for indentation
                error_message: Error message for failed nodes
                ignore_errors: Whether errors are being ignored (warning vs error)
                is_modified: Whether node was modified during repair
                is_error: Whether this is a fatal error
                batch_current: Items completed so far (for batch_progress)
                batch_total: Total items in batch (for batch_progress and node_complete)
                batch_success: Whether just-completed item succeeded (for batch_progress)
                is_batch: Whether this is a batch node (for node_complete)
                batch_success_count: Number of successful items (for node_complete)
            """
            indent = "  " * depth

            # Dispatch to appropriate handler based on event type
            if event == "node_start":
                self._handle_node_start(node_id, indent)
            elif event == "node_complete":
                self._handle_node_complete(
                    duration_ms,
                    error_message,
                    ignore_errors,
                    is_modified,
                    is_error,
                    is_batch=is_batch,
                    batch_total=batch_total,
                    batch_success_count=batch_success_count,
                )
            elif event == "batch_progress":
                if batch_current is not None and batch_total is not None and batch_success is not None:
                    self._handle_batch_progress(node_id, indent, batch_current, batch_total, batch_success)
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
