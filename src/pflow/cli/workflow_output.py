"""Workflow output handling — detection, display, and formatting."""

from __future__ import annotations

import json
import os
from typing import Any

import click

from pflow.core.diagnostic import Diagnostic
from pflow.core.diagnostic_render import format_diagnostic


def safe_output(value: Any) -> bool:
    """Safely output a value to stdout, handling broken pipes.

    Strings pass through verbatim. Structured values (dict, list, tuple,
    bool, int, float, None) are emitted as **strict JSON** so consumers
    can parse them with ``jq`` or ``json.loads`` — the GH #194 routing
    fix means agents now actually receive these on stdout, so the format
    must be parseable.

    - ``allow_nan=False``: rejects NaN/Infinity (jq and most strict
      parsers reject these literals).
    - ``default=str``: non-natively-serializable values (datetime, Path,
      set, dataclass, etc.) are coerced to their ``str()`` form INSIDE
      the JSON document, so the value lands as a JSON string and the
      pipeline keeps working.
    - Last-resort fallback: if even ``default=str`` cannot serialize the
      value (e.g. NaN inside an otherwise valid dict), we emit a stderr
      warning so agents can diagnose, then write ``repr(value)`` to
      stdout so something is visible.

    Returns True if output was successful, False otherwise.
    """
    try:
        if isinstance(value, bytes):
            click.echo("cli: Skipping binary output (use --output-key with text values)", err=True)
            return False
        if isinstance(value, str):
            click.echo(value)
            return True
        try:
            click.echo(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
        except (TypeError, ValueError) as exc:
            click.echo(
                f"cli: Output value of type {type(value).__name__} is not JSON-serializable "
                f"({exc}); emitting repr() so the value is still visible. "
                "Convert it in your workflow before output for parseable results.",
                err=True,
            )
            click.echo(repr(value))
        return True
    except BrokenPipeError:
        os._exit(0)
    except OSError as e:
        if hasattr(e, "errno") and e.errno == 32:  # EPIPE
            os._exit(0)
        raise


def _stdout_is_tty() -> bool:
    """Return whether stdout is a TTY, preferring OutputController's captured state.

    Falls back to ``sys.stdout.isatty()`` when no Click context / OutputController
    is available — matches what ``OutputController.__init__`` does itself, so the
    TTY decision stays consistent for any caller of ``_output_with_header``
    (including non-CLI entry points that don't thread through ``_initialize_context``).
    """
    import sys

    try:
        ctx = click.get_current_context(silent=True)
    except RuntimeError:
        ctx = None
    if ctx is not None and ctx.obj and "output_controller" in ctx.obj:
        return bool(ctx.obj["output_controller"].stdout_tty)
    return sys.stdout.isatty() if sys.stdout is not None else False


def _output_with_header(value: Any, print_flag: bool, description: str | None = None) -> None:
    """Output value with Unix-convention routing.

    - ``--print`` mode: data to stdout, no header.
    - Non-TTY stdout (pipe/redirect): data to stdout, no header — the naked
      stderr label would otherwise look like empty output when the terminal
      has nothing to render below it.
    - TTY stdout: header to stderr, data to stdout — the description is
      useful interactive context.
    """
    if print_flag or not _stdout_is_tty():
        safe_output(value)
        return

    header = f"\nWorkflow output ({description}):\n" if description else "\nWorkflow output:\n"
    click.echo(header, err=True)
    safe_output(value)


def _handle_text_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool = False,
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    status: Any = None,
    warnings: list[Any] | None = None,
) -> bool:
    """Handle text formatted output with execution summary.

    Shows execution summary first, then workflow output.

    When print_flag (-p) is True, suppresses all warnings.

    Args:
        shared_storage: The shared store after execution
        output_key: User-specified output key (--output-key flag)
        workflow_ir: The workflow IR (to check declared outputs)
        verbose: Whether to show verbose output
        print_flag: Whether -p flag is set (suppress warnings)
        metrics_collector: Optional MetricsCollector for execution metrics
        workflow_metadata: Optional workflow metadata

    Returns:
        True if output was produced, False otherwise.
    """
    # Display execution summary or --only mode indicator (dispatch in helper)
    _emit_summary_or_only_indicator(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir,
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        status=status,
        warnings=warnings,
        verbose=verbose,
        print_flag=print_flag,
    )

    # Now show the actual output
    output_found = False

    # User-specified key takes priority
    if output_key:
        if output_key in shared_storage:
            _output_with_header(shared_storage[output_key], print_flag)
            output_found = True
        else:
            # Suppress warnings in -p mode
            if not print_flag:
                click.echo(f"cli: Warning - output key '{output_key}' not found in shared store", err=True)

    # --only targets are explicit data-routing requests. Declared workflow
    # outputs describe full runs, so they must not shadow the targeted node.
    elif shared_storage.get("__execution__", {}).get("only_node"):
        output_found = _emit_only_output(shared_storage, print_flag)

    # Check workflow-declared outputs for full runs.
    elif workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]:
        if _try_declared_outputs(shared_storage, workflow_ir, verbose and not print_flag, print_flag):
            output_found = True

    # Fall back to auto-detect from common keys (using unified function)
    else:
        output_found = _emit_auto_detected_output(
            shared_storage,
            print_flag,
            "cli: No outputs declared — showing auto-detected key '{key}'. Declare outputs for reliable results.",
        )

    return output_found


def _emit_only_output(shared_storage: dict[str, Any], print_flag: bool) -> bool:
    """Emit target-scoped output for an active ``--only`` run."""
    from pflow.execution.formatters.output_utils import find_only_output

    only_node = shared_storage.get("__execution__", {}).get("only_node")
    if not isinstance(only_node, str) or not only_node:
        return False

    key_found, value = find_only_output(shared_storage, only_node)
    if not key_found:
        if not print_flag:
            # Surface concrete ``-o`` candidates so the agent's suggested next
            # action is actionable — without enumeration the agent must either
            # introspect the trace or guess key names.
            available = _list_routable_keys_for_only_target(shared_storage)
            keys_hint = f" Available shared-store keys: {', '.join(available)}." if available else ""
            click.echo(
                f"cli: --only target '{only_node}' produced no output. "
                f"Pass -o <key> to select a specific shared-store key.{keys_hint}",
                err=True,
            )
        return False

    if not print_flag:
        click.echo(
            f"cli: --only active — streaming auto-detected key '{key_found}' from target '{only_node}' to stdout.",
            err=True,
        )
    _output_with_header(value, print_flag)
    return True


def _list_routable_keys_for_only_target(shared_storage: dict[str, Any]) -> list[str]:
    """Return top-level shared-storage keys that ``-o <key>`` can select.

    Used by the ``--only`` no-output error path so the agent sees concrete
    ``-o`` candidates rather than abstract advice. Filters internal keys
    (leading ``_``) since those are never user-routable. The ``-o`` flag
    operates on the whole shared storage, not within a specific namespace —
    so the candidates are top-level node-id keys, not sub-keys of the target.
    Returns ``[]`` if no routable keys exist; caller decides how to render
    absence.
    """
    return sorted(k for k in shared_storage if isinstance(k, str) and not k.startswith("_"))


def _emit_auto_detected_output(
    shared_storage: dict[str, Any],
    print_flag: bool,
    message_template: str | None,
) -> bool:
    """Auto-detect output from shared storage and emit it.

    ``message_template`` (optional) must contain ``{key}`` for the detected
    key name. Returns True if output was emitted.
    """
    from pflow.execution.formatters.output_utils import find_auto_output

    key_found, value = find_auto_output(shared_storage)
    if not key_found:
        return False
    if message_template and not print_flag:
        click.echo(message_template.format(key=key_found), err=True)
    _output_with_header(value, print_flag)
    return True


def _emit_declared_output(
    shared_storage: dict[str, Any],
    declared_outputs: dict[str, Any],
    print_flag: bool,
) -> bool:
    """Emit the first available declared output and return True.

    This helper reduces complexity in `_try_declared_outputs` by encapsulating
    the loop and verbose description printing.
    """
    for output_name, output_config in declared_outputs.items():
        if output_name in shared_storage:
            value = shared_storage[output_name]

            # Extract description from output config
            description = None
            if isinstance(output_config, dict):
                description = output_config.get("description")

            _output_with_header(value, print_flag, description)
            return True
    return False


def _select_stdout_target(declared_outputs: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Choose which declared outputs to stream to stdout in text mode.

    Pure selector — returns ``(target, dropped)`` and never writes to stderr.
    The caller decides whether to emit the multi-output warning (see
    ``_warn_multi_output_ambiguity``).

    Precedence:
    - Any output marked ``stdout: true`` → return only that output, no drops.
      Validator guarantees at most one marker, so this always yields a
      single-entry dict.
    - Exactly one declared output → return it (implicit, unambiguous case).
    - Multiple declared outputs with no marker → return the first, with the
      remaining names as ``dropped``.

    Schema (``additionalProperties: false`` on outputs) guarantees dict
    values by the time we run, so no defensive type checks.
    """
    marked = {name: config for name, config in declared_outputs.items() if config.get("stdout") is True}
    if marked:
        return marked, []
    if len(declared_outputs) <= 1:
        return declared_outputs, []

    names = list(declared_outputs.keys())
    first_name = names[0]
    return {first_name: declared_outputs[first_name]}, names[1:]


def _warn_multi_output_ambiguity(chosen: str, dropped: list[str]) -> None:
    """Emit the stderr warning when multiple declared outputs have no ``stdout: true``.

    Sibling of ``_warn_missing_declared_outputs``. Named so the selector stays
    pure; caller gates on ``print_flag``.
    """
    total = 1 + len(dropped)
    names = ", ".join([chosen, *dropped])
    click.echo(
        f"cli: Workflow declares {total} outputs ({names}). "
        f"Streaming '{chosen}' to stdout. Mark one output with `- stdout: true`, "
        "pass `-o <name>`, or use `--output-format json` to emit all.",
        err=True,
    )


def _try_declared_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool,
) -> bool:
    """Try to output from workflow-declared outputs.

    Args:
        shared_storage: The shared storage dictionary
        workflow_ir: The workflow IR specification
        verbose: Whether to show verbose output
        print_flag: Whether in non-interactive/print mode
    Returns:
        True if a declared output was found and printed, False otherwise
    """
    if not (workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]):
        return False

    declared_outputs = workflow_ir["outputs"]
    target, dropped = _select_stdout_target(declared_outputs)
    if dropped and not print_flag:
        _warn_multi_output_ambiguity(next(iter(target)), dropped)

    # First attempt: use already-populated outputs (preferred path via compiler wrapper)
    if _emit_declared_output(shared_storage, target, print_flag):
        return True

    # Populate on-demand if not present
    _populate_declared_outputs_best_effort(shared_storage, workflow_ir)

    # Second attempt after population
    if _emit_declared_output(shared_storage, target, print_flag):
        return True

    _warn_missing_declared_outputs(target, verbose)
    return False


def _populate_declared_outputs_best_effort(shared_storage: dict[str, Any], workflow_ir: dict[str, Any]) -> None:
    """Best-effort population of declared outputs from source expressions.

    Redundant with ``engine._populate_outputs`` for normal CLI runs (engine
    populates first), but kept as a safety net for callers that bypass the
    engine path. The second call is idempotent — resolvable outputs already
    in ``shared_storage`` are overwritten with the same values.
    """
    from pflow.core.user_errors import OutputResolutionError
    from pflow.runtime.output_resolver import populate_declared_outputs

    try:
        populate_declared_outputs(shared_storage, workflow_ir)
    except OutputResolutionError as e:
        only_node = shared_storage.get("__execution__", {}).get("only_node")
        if not only_node:
            from pflow.core.diagnostic import exception_to_diagnostics

            for d in exception_to_diagnostics(e):
                click.echo(format_diagnostic(d), err=True)
    except Exception:  # noqa: S110
        pass  # Best-effort: non-diagnostic errors silently ignored


def _warn_missing_declared_outputs(declared_outputs: dict[str, Any], verbose: bool) -> None:
    """Warn when declared outputs are present but none were resolved."""
    if not verbose:
        return
    expected = ", ".join(declared_outputs.keys())
    click.echo(
        f"cli: Warning - workflow declares outputs [{expected}] but none could be resolved",
        err=True,
    )


def _truncate_error_message(message: str, max_length: int = 200) -> str:
    """Truncate error message to max length with ellipsis."""
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


def _display_batch_errors(steps: list[dict[str, Any]]) -> None:
    """Display batch errors section for all batch nodes with failures.

    Args:
        steps: List of execution step dicts
    """
    for step in steps:
        if not step.get("is_batch") or step.get("batch_errors", 0) == 0:
            continue

        node_id = step.get("node_id", "unknown")
        error_details = step.get("batch_error_details", [])
        truncated = step.get("batch_errors_truncated", 0)

        click.echo(f"\nBatch '{node_id}' errors:", err=True)
        for err in error_details:
            idx = err.get("index", "?")
            msg = _truncate_error_message(str(err.get("error", "Unknown error")))
            click.echo(f"  [{idx}] {msg}", err=True)

        if truncated > 0:
            click.echo(f"  ...and {truncated} more errors", err=True)


def _display_stderr_warnings(steps: list[dict[str, Any]]) -> None:
    """Display stderr warnings for shell nodes that succeeded but produced stderr.

    This helps surface hidden errors from shell pipeline failures where
    intermediate commands fail but the overall exit code is 0.

    Delegates to ``format_stderr_warnings`` in ``success_formatter.py`` so CLI
    and MCP text output stay in lockstep (same bullet shape, same truncation,
    same ⚠️ header). MCP consumers of this block are in
    ``success_formatter.format_success_as_text``; any change to the block
    shape must be made in the shared helper, not here.

    Args:
        steps: List of execution step dicts (may contain has_stderr and stderr fields)
    """
    from pflow.execution.formatters.success_formatter import format_stderr_warnings

    for line in format_stderr_warnings(steps):
        click.echo(line, err=True)


def _display_workflow_action(workflow_name: str, workflow_action: str) -> None:
    """Display workflow name and action message.

    Args:
        workflow_name: Name of the workflow
        workflow_action: Action type (reused, created, unsaved)
    """
    click.echo("", err=True)
    if workflow_action == "reused":
        click.echo(f"{workflow_name} was executed", err=True)
    elif workflow_action == "created":
        click.echo(f"{workflow_name} was created and executed", err=True)
    # Skip showing workflow line for "unsaved" workflows


def _display_cost_summary(total_cost: float | None, formatted_result: dict[str, Any]) -> None:
    """Display LLM cost and token usage summary.

    Args:
        total_cost: Total cost in USD
        formatted_result: Full formatted result containing metrics
    """
    metrics = formatted_result.get("metrics", {})
    total_metrics = metrics.get("total", {})

    # Warn about models with unavailable pricing
    if not total_metrics.get("pricing_available", True):
        unavailable = total_metrics.get("unavailable_models", [])
        models_str = ", ".join(unavailable)
        partial = total_metrics.get("partial_cost_usd")
        if partial is not None:
            click.echo(
                f"💰 Cost: ${partial:.4f}+ (partial — pricing unavailable for: {models_str})",
                err=True,
            )
        else:
            click.echo(f"⚠️  Cost unavailable — pricing data missing for: {models_str}", err=True)
        return

    if total_cost is None or total_cost <= 0:
        return

    # Get token count for context
    workflow_metrics = metrics.get("workflow", {})
    total_tokens = workflow_metrics.get("total_tokens", 0)

    if total_tokens > 0:
        click.echo(f"💰 Cost: ${total_cost:.4f} ({total_tokens:,} tokens)", err=True)
    else:
        click.echo(f"💰 Cost: ${total_cost:.4f}", err=True)


def _display_workflow_completion_status(
    duration_s: float,
    status: str,
    has_stderr_warnings: bool,
    cache_hits: int = 0,
    nodes_executed: int = 0,
    warning_count: int = 0,
) -> None:
    """Display workflow completion status with appropriate indicator.

    Args:
        duration_s: Execution duration in seconds
        status: Workflow status ("success", "degraded", "failed")
        has_stderr_warnings: Whether any shell node produced stderr with exit_code=0
        cache_hits: Number of nodes served from cache (0 = no cache stats shown)
        nodes_executed: Total completed nodes (used to compute fresh executions)
        warning_count: Number of diagnostics warnings surfaced in the summary
    """
    cache_suffix = ""
    if cache_hits > 0:
        executed_fresh = nodes_executed - cache_hits
        cache_suffix = f" ({cache_hits} cached, {executed_fresh} executed)"

    if status == "degraded":
        click.echo(f"⚠️ Workflow completed with warnings in {duration_s:.3f}s{cache_suffix}", err=True)
    elif status == "failed":
        if warning_count:
            click.echo(f"❌ Workflow failed ({warning_count} warnings) after {duration_s:.3f}s{cache_suffix}", err=True)
        else:
            click.echo(f"❌ Workflow failed after {duration_s:.3f}s{cache_suffix}", err=True)
    elif warning_count:
        click.echo(f"⚠️ Workflow completed with {warning_count} warnings in {duration_s:.3f}s{cache_suffix}", err=True)
    elif has_stderr_warnings:
        click.echo(f"⚠️ Workflow completed in {duration_s:.3f}s{cache_suffix}", err=True)
    else:
        click.echo(f"✓ Workflow completed in {duration_s:.3f}s{cache_suffix}", err=True)


def _emit_summary_or_only_indicator(
    *,
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any] | None,
    metrics_collector: Any | None,
    workflow_metadata: dict[str, Any] | None,
    output_key: str | None,
    status: Any,
    warnings: list[Any] | None,
    verbose: bool,
    print_flag: bool,
) -> None:
    """Dispatch between full summary, --only-only emission, or nothing.

    The full summary (workflow action + completion tag + batch errors +
    cost + warnings + --only line) is suppressed in ``-p`` mode because
    the user explicitly asked for minimal stderr. The ``--only`` mode
    confirmation is a mode signal (not a suppressible detail) and is
    emitted even in ``-p`` mode when ``--only`` is active. Verbosity
    flags hide details; mode flags survive verbosity. Matches the
    convention of ``make -k``, ``pytest --maxfail``, ``rsync --dry-run``,
    ``apt-get --simulate``, ``kubectl --dry-run``, etc.

    No-op when there's no metrics collector OR when neither path applies.
    """
    if not metrics_collector:
        return

    only_node = shared_storage.get("__execution__", {}).get("only_node") if shared_storage else None
    if print_flag and not only_node:
        return  # -p mode without --only: nothing to emit

    from pflow.execution.formatters.success_formatter import format_execution_success

    formatted = format_execution_success(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir or {},
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        trace_path=None,
        status=status,
        warnings=warnings,
    )

    if print_flag:
        # -p + --only: emit just the mode confirmation, nothing else
        _emit_only_indicator(formatted)
        return

    # Default mode: full summary (which already includes the --only line
    # internally via the shared format_only_indicator helper)
    warning_diags = [w for w in (warnings or []) if isinstance(w, Diagnostic)]
    _display_execution_summary(formatted, verbose, warning_diagnostics=warning_diags or None)


def _emit_only_indicator(formatted_result: dict[str, Any]) -> None:
    """Emit the ``--only`` mode confirmation line to stderr.

    Used by ``_handle_text_output`` in ``-p`` mode (where the full summary
    is suppressed). The full default-mode summary path
    (``_display_execution_summary``) emits the same line via the same
    shared formatter — see ``format_only_indicator`` in
    ``success_formatter.py``.

    Why this exists: ``--only`` is a mode signal, not a summary detail.
    Without this emission, ``pflow -p foo --only target`` produces zero
    bytes on stderr, leaving agents unable to disambiguate constrained
    runs from full runs. Verbosity flags hide details; mode flags
    survive verbosity (matches ``make -k``, ``pytest --maxfail``,
    ``rsync --dry-run``, ``apt-get --simulate``, ``kubectl --dry-run``,
    etc.).
    """
    from pflow.execution.formatters.success_formatter import format_only_indicator

    execution = formatted_result.get("execution", {})
    only_node = execution.get("only_node")
    if not only_node:
        return
    nodes_skipped = execution.get("nodes_skipped", 0)
    click.echo(format_only_indicator(only_node, nodes_skipped), err=True)


def _display_execution_summary(
    formatted_result: dict[str, Any],
    verbose: bool,
    warning_diagnostics: list[Diagnostic] | None = None,
) -> None:
    """Display one-line execution summary with supplementary info."""
    duration_ms = formatted_result.get("duration_ms")
    total_cost = formatted_result.get("total_cost_usd")
    execution = formatted_result.get("execution", {})
    steps = execution.get("steps", []) if execution else []
    workflow_metadata = formatted_result.get("workflow", {})
    workflow_name = workflow_metadata.get("name", "workflow")
    workflow_action = workflow_metadata.get("action", "executed")
    _display_workflow_action(workflow_name, workflow_action)

    if duration_ms is not None:
        duration_s = duration_ms / 1000.0
        status = formatted_result.get("status", "success")
        has_stderr_warnings = any(step.get("has_stderr") for step in steps)
        cache_hits = execution.get("cache_hits", 0)
        completed_count = execution.get("nodes_executed", 0)
        warning_count = len(formatted_result.get("warnings", []))
        _display_workflow_completion_status(
            duration_s,
            status,
            has_stderr_warnings,
            cache_hits=cache_hits,
            nodes_executed=completed_count,
            warning_count=warning_count,
        )

    # --only mode confirmation: always emit when --only is active, even
    # when no downstream nodes were skipped (e.g., --only targeted the
    # last node). Delegated to _emit_only_indicator so there's ONE call
    # site for the indicator — the -p path (_emit_summary_or_only_indicator)
    # and the default path (here) share this function, preventing drift.
    _emit_only_indicator(formatted_result)

    if steps:
        _display_batch_errors(steps)
        _display_stderr_warnings(steps)

    _display_cost_summary(total_cost, formatted_result)

    if warning_diagnostics:
        click.echo("", err=True)
        click.echo("⚠️ Warnings:", err=True)
        for warning in warning_diagnostics:
            click.echo(format_diagnostic(warning), err=True)


def _handle_json_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool = False,
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
    status: Any = None,
    warnings: list[Any] | None = None,
) -> bool:
    """Handle JSON formatted output.

    Returns all declared outputs or specified key as JSON, optionally with metrics.
    Emits execution summary to stderr (same as text mode) — ``--output-format``
    controls stdout format, ``-p`` controls stderr verbosity.
    """
    # Use shared formatter for consistency with MCP
    from pflow.execution.formatters.success_formatter import format_execution_success

    result = format_execution_success(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir or {},
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        trace_path=None,  # CLI doesn't include trace_path in output
        status=status,
        warnings=warnings,
    )

    # Save JSON output to trace if available
    if workflow_trace and hasattr(workflow_trace, "set_json_output"):
        workflow_trace.set_json_output(result)

    # Emit execution summary to stderr (same as text mode)
    _emit_summary_or_only_indicator(
        shared_storage=shared_storage,
        workflow_ir=workflow_ir,
        metrics_collector=metrics_collector,
        workflow_metadata=workflow_metadata,
        output_key=output_key,
        status=status,
        warnings=warnings,
        verbose=verbose,
        print_flag=print_flag,
    )

    return _serialize_json_result(result, verbose)


def _create_workflow_metadata(name: str | None, action: str) -> dict[str, Any]:
    """Create workflow metadata with name and action.

    Args:
        name: Workflow name (optional)
        action: Workflow action ("created", "reused", "unsaved")

    Returns:
        Workflow metadata dictionary

    Raises:
        ValueError: If action is not one of the allowed values
    """
    allowed_actions = {"created", "reused", "unsaved"}
    if action not in allowed_actions:
        raise ValueError(f"Invalid workflow action: {action}. Must be one of {allowed_actions}")

    metadata = {"action": action}
    if name:
        metadata["name"] = name
    return metadata


def _serialize_json_result(result: dict[str, Any], verbose: bool) -> bool:
    """Serialize result dictionary to JSON and output it.

    Args:
        result: Dictionary to serialize
        verbose: Whether to show verbose output

    Returns:
        True if output was successful, False otherwise
    """
    try:
        # Handle special types
        def json_serializer(obj: Any) -> Any:
            """Custom JSON serializer for non-standard types."""
            if isinstance(obj, bytes):
                return {"_type": "binary", "size": len(obj), "note": "Binary data not included in JSON output"}
            return str(obj)

        output = json.dumps(result, indent=2, ensure_ascii=False, default=json_serializer)
        return safe_output(output)
    except (TypeError, ValueError) as e:
        if verbose:
            click.echo(f"cli: Warning - JSON encoding error: {e}", err=True)
        # Fallback to error message
        error_output = json.dumps({"error": "JSON encoding failed", "message": str(e)})
        return safe_output(error_output)


def _handle_workflow_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None = None,
    verbose: bool = False,
    output_format: str = "text",
    metrics_collector: Any | None = None,
    print_flag: bool = False,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
    status: Any = None,
    warnings: list[Any] | None = None,
) -> bool:
    """Handle output from workflow execution.

    Args:
        shared_storage: The shared store after execution
        output_key: User-specified output key (--output-key flag)
        workflow_ir: The workflow IR (to check declared outputs)
        verbose: Whether to show verbose output
        output_format: Output format - "text" or "json"
        metrics_collector: Optional MetricsCollector for including metrics in JSON output
        print_flag: Whether -p flag is set (suppress warnings)
        workflow_metadata: Optional workflow metadata for JSON output
        workflow_trace: Optional workflow trace collector for saving JSON output

    Returns:
        True if output was produced, False otherwise.
    """
    if output_format == "json":
        return _handle_json_output(
            shared_storage,
            output_key,
            workflow_ir,
            verbose,
            print_flag=print_flag,
            metrics_collector=metrics_collector,
            workflow_metadata=workflow_metadata,
            workflow_trace=workflow_trace,
            status=status,
            warnings=warnings,
        )
    else:  # text format (default)
        return _handle_text_output(
            shared_storage,
            output_key,
            workflow_ir,
            verbose,
            print_flag,
            metrics_collector,
            workflow_metadata,
            status=status,
            warnings=warnings,
        )
