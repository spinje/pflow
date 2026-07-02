"""Central output control for interactive vs non-interactive execution modes."""

import logging
import sys
import weakref
from typing import Callable, Optional

import click


class _ProgressPartialLineFilter(logging.Filter):
    """Closes any open progress partial line before each log record is emitted.

    Without this filter, ``logger.warning``/``logger.error`` calls from a node's
    ``prep``/``exec``/``post`` write directly to ``sys.stderr`` while
    ``OutputController`` has a ``node_id...`` partial line open, producing
    ``node_id...WARNING: ...`` corruption in the live progress stream.

    Architecturally, this is the single coordination point that makes
    ``OutputController._partial_line_open`` an honest abstraction: install
    once, all current and future ``logger.*`` sites in node code are
    automatically protected. Without it, every node that adds a
    ``logger.warning`` re-introduces the same partial-line corruption bug.

    Always returns True (does not filter records). The side effect IS the
    point — Python's ``logging`` machinery runs filters before each handler's
    ``emit``, so this is the canonical place to perform "before each log
    record is written" coordination.

    Holds a ``weakref`` to the controller so installed filters do not pin a
    destroyed ``OutputController`` instance alive (matters in test runs that
    create and discard many controllers).
    """

    def __init__(self, controller: "OutputController") -> None:
        super().__init__()
        self._controller_ref: weakref.ref[OutputController] = weakref.ref(controller)

    def filter(self, record: logging.LogRecord) -> bool:
        controller = self._controller_ref()
        if controller is not None:
            controller._close_partial_line()
        return True


class OutputController:
    """Central output control based on execution mode.

    Determines whether pflow is running interactively (terminal) or
    non-interactively (piped/automated) and controls output accordingly.

    Rules for interactive mode detection:
    1. If print_flag is True then is_interactive returns False
    2. If stdin_tty is False then is_interactive returns False
    3. If stdout_tty is False then is_interactive returns False
    4. Only if all conditions pass is the mode considered interactive
    """

    def __init__(
        self,
        print_flag: bool = False,
        stdin_tty: Optional[bool] = None,
        stdout_tty: Optional[bool] = None,
        stderr_tty: Optional[bool] = None,
    ):
        """Initialize output controller with execution mode parameters.

        Args:
            print_flag: CLI flag -p/--print to force non-interactive mode
            stdin_tty: Override for sys.stdin.isatty() (for testing)
            stdout_tty: Override for sys.stdout.isatty() (for testing)
            stderr_tty: Override for sys.stderr.isatty() (for testing)
        """
        self.print_flag = print_flag

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

        # Whether stderr is a terminal. Distinguishes the agent case (stderr
        # captured/piped → non-TTY) from the human-redirect case (stderr is a
        # terminal while stdout is a file). The ``Workflow output:`` label is
        # suppressed ONLY in the latter — see ``_show_output_header`` in
        # ``cli/workflow_output.py``.
        if stderr_tty is not None:
            self.stderr_tty = stderr_tty
        elif sys.stderr is None:
            self.stderr_tty = False
        else:
            self.stderr_tty = sys.stderr.isatty()

        # Tracks whether _handle_node_start left a partial line open (nl=False).
        # Required so that anything else writing to stderr — nested-workflow
        # progress callbacks, logger.warning from a node's prep/exec/post —
        # can terminate the partial line first instead of concatenating onto
        # it. Without this, captured stderr in non-TTY mode shows
        # `node_id...WARNING: ...` style corruption.
        #
        # **Invariant**: only ``_handle_node_start`` and ``_ensure_node_line_open``
        # may set this flag to ``True``. Any new subsystem that writes a
        # ``node_id...`` style partial line to stderr MUST route through one
        # of those methods (or call ``_close_partial_line()`` before writing)
        # or the state machine desyncs silently — subsequent ``_close_partial_line()``
        # calls will be no-ops while real partial lines remain open. Bypass paths
        # include direct ``click.echo(..., nl=False, err=True)`` calls or
        # ``sys.stderr.write`` calls from inside a node lifecycle method; the
        # ``_ProgressPartialLineFilter`` catches the ``logger.*`` case but not
        # these direct-write cases. Adding such a writer is a design smell —
        # prefer emitting a new progress event instead.
        self._partial_line_open = False

        # Tracks whether the partial-line-aware logging filter has been
        # installed on the root logger's stderr handlers. Set by
        # _install_log_partial_line_guard() the first time
        # create_progress_callback() is invoked. Idempotent — repeated
        # installs are no-ops.
        self._log_filter_installed = False

    def is_interactive(self) -> bool:
        """Determine if running in interactive mode.

        Returns:
            True if running in interactive terminal mode, False otherwise
        """
        # Rule 1: -p flag forces non-interactive
        if self.print_flag:
            return False

        # Rules 2 & 3: Both stdin AND stdout must be TTY for interactive
        return self.stdin_tty and self.stdout_tty

    def prepare_for_prompt(self) -> None:
        """Public seam for interactive prompts (Task 125 gate prompt).

        Terminates any open ``node_id...`` partial line (which also carries the
        batch ``\\r`` counter rewrites — they ride the same physical line) so a
        prompt renders on a fresh line instead of concatenating onto progress
        output. Safe to call when no line is open.
        """
        self._close_partial_line()

    def _close_partial_line(self) -> None:
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
        self._close_partial_line()
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
        """Build display suffix for smart-handled shell outcomes.

        Reason-string matching is pinned by the ``shell.py:200`` contract:
        reason strings MUST contain either ``"no matches"`` or ``"not found"``
        so one of the two named branches always fires. The final ``if reason:``
        branch is therefore **unreachable today** — it's a safety net for
        future reason-string additions that might forget to update this tag
        mapping. If that happens, the user sees a graceful ``[raw reason]``
        yellow tag instead of silently dropping the signal, which makes the
        contract violation immediately visible in the live progress stream.
        Cheap to keep; removing it would trade graceful degradation for
        silent signal loss on future breakage.
        """
        if not smart_handled:
            return ""

        reason = smart_handled_reason or ""
        if "no matches" in reason:
            return click.style(" [no matches]", fg="yellow")
        if "not found" in reason:
            return click.style(" [not found]", fg="yellow")
        if reason:
            # Safety-net fallback — unreachable today (see docstring); kept
            # so a future shell.py reason string that forgets this tag
            # mapping renders a visible tag instead of silently dropping.
            return click.style(f" [{reason}]", fg="yellow")
        return ""

    def _ensure_node_line_open(self, node_id: str, indent: str) -> None:
        """Ensure there is a partial `node_id...` line to append a completion to.

        If a previous handler call (or external write) closed the line, re-emit
        a fresh `  node_id...` lead-in so the appended completion text isn't
        orphaned on its own line. Used by every non-batch completion path.
        Re-emits with the same trailing ``...`` shape as ``_handle_node_start``
        so structured stderr parsers see one canonical format for completed
        node lines, regardless of whether interleaving forced a re-emit.
        """
        if not self._partial_line_open:
            click.echo(f"{indent}  {node_id}...", err=True, nl=False)
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
            # Render success/failure counts on the live line so partial-failure
            # batches don't look like full successes during the live stream.
            # The supplementary "Batch 'X' errors:" block still carries the
            # per-item details after execution finishes.
            count_tag = ""
            if batch_total is not None and batch_success_count is not None:
                if batch_success_count < batch_total:
                    count_tag = click.style(f" {batch_success_count}/{batch_total} ⚠️", fg="yellow")
                else:
                    count_tag = click.style(f" {batch_total}/{batch_total}", fg="green")
            if duration_ms is not None:
                timing_text = click.style(f" {duration_ms / 1000:.1f}s", fg="green")
                click.echo(f"{count_tag}{timing_text}", err=True)
            else:
                click.echo(count_tag, err=True)
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

    def _handle_node_warning(self, node_id: str, indent: str, warning_message: Optional[str]) -> None:
        """Handle node_warning event display.

        Renders a yellow ⚠️ marker on the live progress line and closes
        the partial. The warning message comes from
        ``handle_api_warning`` in ``runtime/engine/instrumentation.py`` —
        typically an API response classification (HTTP 401, Slack
        ``ok=False``, GraphQL ``errors``) or an LLM response error.

        Args:
            node_id: The node identifier
            indent: Indentation string based on depth
            warning_message: The warning text to display (None falls back
                to a generic "API warning" label)
        """
        self._ensure_node_line_open(node_id, indent)
        warning_text = click.style(f" ⚠️  {warning_message or 'API warning'}", fg="yellow")
        click.echo(warning_text, err=True)
        self._partial_line_open = False

    def _install_log_partial_line_guard(self) -> None:
        """Install a logging filter that closes any open progress partial line
        before each log record is emitted.

        Idempotent. Attaches a ``_ProgressPartialLineFilter`` to every
        ``StreamHandler`` on the root logger whose stream is ``sys.stderr``,
        which (after ``cli/logging_config.py::configure_logging`` runs at
        startup) is the single handler pflow installs.

        This is the architectural answer to the partial-line corruption bug
        whose first symptom was Finding #3 (``shell.py:713``). Without this,
        every ``logger.warning``/``logger.error`` call in a node's
        ``prep``/``exec``/``post`` writes directly to stderr while a
        ``node_id...`` partial progress line is open and produces
        ``node_id...WARNING: ...`` corruption. With this filter installed,
        all 28 current ``logger.*`` sites in node files — and any future
        sites added by any future node — are automatically protected by
        Python's logging machinery running the filter before each emit.

        Only called from ``create_progress_callback`` so non-progress modes
        (``-p``, MCP server) never install the filter and never pay its
        (negligible) cost.
        """
        if self._log_filter_installed:
            return
        filt = _ProgressPartialLineFilter(self)
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.StreamHandler) and getattr(handler, "stream", None) is sys.stderr:
                handler.addFilter(filt)
        self._log_filter_installed = True

    def create_progress_callback(self) -> Callable:
        """Create progress callback for workflow execution.

        Side effect: installs a logging filter on root-logger stderr handlers
        so ``logger.warning``/``logger.error`` calls from a node's
        ``prep``/``exec``/``post`` cannot corrupt open progress partial
        lines. See ``_install_log_partial_line_guard`` for the rationale.

        Returns:
            Callback function for streaming progress to stderr
        """
        self._install_log_partial_line_guard()

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
                # Warning text comes via the properly-named `error_message`
                # kwarg from instrumentation.py::handle_api_warning. The
                # earlier convention abused `duration_ms` as a string slot.
                self._handle_node_warning(node_id, indent, error_message)

        return progress_callback
