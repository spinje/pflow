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

        # Tracks whether _handle_node_start left a partial line open (nl=False).
        # Required so that anything else writing to stderr — nested-workflow
        # progress callbacks, logger.warning from a node's prep/exec/post —
        # can terminate the partial line first instead of concatenating onto
        # it. Without this, captured stderr in non-TTY mode shows
        # `node_id...WARNING: ...` style corruption.
        self._partial_line_open = False

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

    def _close_partial_line_if_open(self) -> None:
        """Terminate any open partial line so the next write starts fresh.

        Called by every event handler that emits a fresh line so nested
        progress events (sub-workflow children, batch completions) don't
        concatenate onto a parent's `node_id...` partial line.
        """
        if self._partial_line_open:
            click.echo("", err=True)  # bare newline
            self._partial_line_open = False

    def _handle_node_start(self, node_id: str, indent: str) -> None:
        """Handle node_start event display.

        Args:
            node_id: The node identifier
            indent: Indentation string based on depth
        """
        self._close_partial_line_if_open()
        click.echo(f"{indent}  {node_id}...", err=True, nl=False)
        self._partial_line_open = True

    def _handle_batch_progress(
        self,
        node_id: str,
        indent: str,
        batch_current: int,
        batch_total: int,
        batch_success: bool,
    ) -> None:
        """Handle batch_progress event - update line in place (TTY only)."""
        if not sys.stderr.isatty():
            return

        status = click.style("✓", fg="green") if batch_success else click.style("✗", fg="red")
        click.echo(f"\r{indent}  {node_id}... {batch_current}/{batch_total} {status}", err=True, nl=False)

    def _build_smart_handled_tag(self, smart_handled: bool, smart_handled_reason: Optional[str]) -> str:
        """Build display suffix for smart-handled shell outcomes."""
        if not smart_handled:
            return ""

        reason = smart_handled_reason or ""
        if "no matches" in reason:
            return click.style(" [no matches]", fg="yellow")
        if "not found" in reason:
            return click.style(" [not found]", fg="yellow")
        if reason:
            return click.style(f" [{reason}]", fg="yellow")
        return ""

    def _ensure_node_line_open(self, node_id: str, indent: str) -> None:
        """Ensure there is a partial `node_id...` line to append a completion to.

        If a previous handler call (or external write) closed the line, re-emit
        a fresh `  node_id` lead-in so the appended completion text isn't
        orphaned on its own line. Used by every non-batch completion path.
        """
        if not self._partial_line_open:
            click.echo(f"{indent}  {node_id}", err=True, nl=False)
            self._partial_line_open = True

    def _emit_non_batch_completion(
        self,
        duration_ms: Optional[float],
        error_message: Optional[str],
        ignore_errors: bool,
        tag_suffix: str,
    ) -> None:
        """Emit completion text for non-batch success/warning cases.

        Always closes the line with a newline; the caller is responsible
        for clearing `_partial_line_open`.
        """
        if error_message and ignore_errors:
            warning_text = click.style(f" ⚠️  {error_message} but continuing", fg="yellow")
            if duration_ms is not None:
                success_text = click.style(f" | ✓ {duration_ms / 1000:.1f}s", fg="green")
                click.echo(f"{warning_text}{success_text}{tag_suffix}", err=True)
                return
            click.echo(f"{warning_text}{tag_suffix}", err=True)
            return

        if duration_ms is not None:
            click.echo(click.style(f" ✓ {duration_ms / 1000:.1f}s", fg="green") + tag_suffix, err=True)
            return

        click.echo(click.style(" ✓", fg="green") + tag_suffix, err=True)

    def _handle_node_complete(
        self,
        node_id: str,
        indent: str,
        duration_ms: Optional[float],
        error_message: Optional[str],
        ignore_errors: bool,
        is_error: bool,
        is_batch: bool = False,
        batch_total: Optional[int] = None,
        batch_success_count: Optional[int] = None,
        smart_handled: bool = False,
        smart_handled_reason: Optional[str] = None,
    ) -> None:
        """Handle node_complete event display.

        Re-emits the lead-in `  node_id` if the partial line from
        `_handle_node_start` was closed by an interleaved write — for example,
        a sub-workflow's nested progress events or a `logger.warning` from a
        node's `prep`/`exec`/`post` method. Without this re-emission, the
        completion text would float on its own line orphaned from the node id.
        """
        self._ensure_node_line_open(node_id, indent)

        if is_error:
            if is_batch:
                click.echo(click.style(" FAILED", fg="red"), err=True)
            else:
                click.echo(click.style(" ✗ Failed", fg="red"), err=True)
            self._partial_line_open = False
            return

        if is_batch:
            if duration_ms is not None:
                timing_text = click.style(f" {duration_ms / 1000:.1f}s", fg="green")
                click.echo(timing_text, err=True)
            else:
                click.echo("", err=True)
            self._partial_line_open = False
            return

        tag_suffix = self._build_smart_handled_tag(smart_handled, smart_handled_reason)
        self._emit_non_batch_completion(duration_ms, error_message, ignore_errors, tag_suffix)
        self._partial_line_open = False

    def _handle_node_cached(self, node_id: str, indent: str) -> None:
        """Handle node_cached event display."""
        self._ensure_node_line_open(node_id, indent)
        click.echo(click.style(" ↻ cached", fg="blue", dim=True), err=True)
        self._partial_line_open = False

    def _handle_node_warning(self, node_id: str, indent: str, duration_ms: Optional[float]) -> None:
        """Handle node_warning event display.

        Args:
            node_id: The node identifier
            indent: Indentation string based on depth
            duration_ms: Contains warning message when event is node_warning
        """
        self._ensure_node_line_open(node_id, indent)
        warning_msg = duration_ms if isinstance(duration_ms, str) else "API warning"
        warning_text = click.style(f" ⚠️  {warning_msg}", fg="yellow")
        click.echo(warning_text, err=True)
        self._partial_line_open = False

    def create_progress_callback(self) -> Callable:
        """Create progress callback for workflow execution.

        Returns:
            Callback function for streaming progress to stderr
        """

        def progress_callback(
            node_id: str,
            event: str,
            duration_ms: Optional[float] = None,
            depth: int = 0,
            error_message: Optional[str] = None,
            ignore_errors: bool = False,
            is_error: bool = False,
            # Batch progress parameters
            batch_current: Optional[int] = None,
            batch_total: Optional[int] = None,
            batch_success: Optional[bool] = None,
            is_batch: bool = False,
            batch_success_count: Optional[int] = None,
            smart_handled: bool = False,
            smart_handled_reason: Optional[str] = None,
        ) -> None:
            """Display progress for node execution.

            Args:
                node_id: The node identifier
                event: Event type (node_start, node_complete, node_cached, batch_progress)
                duration_ms: Execution duration in milliseconds (for complete events)
                depth: Nesting depth for indentation
                error_message: Error message for failed nodes
                ignore_errors: Whether errors are being ignored (warning vs error)
                is_error: Whether this is a fatal error
                batch_current: Items completed so far (for batch_progress)
                batch_total: Total items in batch (for batch_progress and node_complete)
                batch_success: Whether just-completed item succeeded (for batch_progress)
                is_batch: Whether this is a batch node (for node_complete)
                batch_success_count: Number of successful items (for node_complete)
                smart_handled: Whether shell node was treated as a safe non-error
                smart_handled_reason: Display tag reason for smart-handled shell nodes
            """
            indent = "  " * depth

            if event == "node_start":
                self._handle_node_start(node_id, indent)
            elif event == "node_complete":
                self._handle_node_complete(
                    node_id,
                    indent,
                    duration_ms,
                    error_message,
                    ignore_errors,
                    is_error,
                    is_batch=is_batch,
                    batch_total=batch_total,
                    batch_success_count=batch_success_count,
                    smart_handled=smart_handled,
                    smart_handled_reason=smart_handled_reason,
                )
            elif event == "batch_progress":
                if batch_current is not None and batch_total is not None and batch_success is not None:
                    self._handle_batch_progress(node_id, indent, batch_current, batch_total, batch_success)
            elif event == "node_cached":
                self._handle_node_cached(node_id, indent)
            elif event == "node_warning":
                self._handle_node_warning(node_id, indent, duration_ms)

        return progress_callback
