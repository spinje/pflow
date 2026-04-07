"""Workflow output handling — detection, display, and formatting."""

from __future__ import annotations

import json
import os
from typing import Any

import click

from pflow.core.diagnostic import Diagnostic, format_diagnostic


def safe_output(value: Any) -> bool:
    """Safely output a value to stdout, handling broken pipes.

    Returns True if output was successful, False otherwise.
    """
    try:
        if isinstance(value, bytes):
            # Skip binary output with warning
            click.echo("cli: Skipping binary output (use --output-key with text values)", err=True)
            return False
        elif isinstance(value, str):
            click.echo(value)
            return True
        else:
            # Convert other types to string
            click.echo(str(value))
            return True
    except BrokenPipeError:
        # Exit cleanly when pipe is closed
        os._exit(0)
    except OSError as e:
        if hasattr(e, "errno") and e.errno == 32:  # EPIPE
            os._exit(0)
        raise


def _output_with_header(value: Any, print_flag: bool, description: str | None = None) -> None:
    """Output value with Unix-convention routing.

    - `--print` mode: data to stdout, no header.
    - Default mode: header to stderr, data to stdout.

    This is intentionally identical for TTY and non-TTY consumers.
    """
    if print_flag:
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
    # Display execution summary FIRST (if metrics collector provided)
    # Skip summary entirely in --print mode (user wants ONLY raw output)
    if metrics_collector and not print_flag:
        from pflow.execution.formatters.success_formatter import format_execution_success

        formatted = format_execution_success(
            shared_storage=shared_storage,
            workflow_ir=workflow_ir or {},
            metrics_collector=metrics_collector,
            workflow_metadata=workflow_metadata,
            output_key=output_key,
            trace_path=None,  # Text mode doesn't include trace_path
            status=status,
            warnings=warnings,
        )

        # Pass warning Diagnostics directly — don't round-trip through dict
        warning_diags = [w for w in (warnings or []) if isinstance(w, Diagnostic)]
        _display_execution_summary(formatted, verbose, warning_diagnostics=warning_diags or None)

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

    # Check workflow-declared outputs (skip when --only is active — declared outputs
    # reference downstream nodes that didn't execute; use auto-detection instead)
    elif (
        workflow_ir
        and "outputs" in workflow_ir
        and workflow_ir["outputs"]
        and not shared_storage.get("__execution__", {}).get("only_node")
    ):
        if _try_declared_outputs(shared_storage, workflow_ir, verbose and not print_flag, print_flag):
            output_found = True

    # Fall back to auto-detect from common keys (using unified function)
    else:
        from pflow.execution.formatters.output_utils import find_auto_output

        key_found, value = find_auto_output(shared_storage)
        if key_found:
            if not print_flag:
                only_node = shared_storage.get("__execution__", {}).get("only_node")
                has_declared_outputs = workflow_ir and workflow_ir.get("outputs")
                if only_node and has_declared_outputs:
                    msg = f"cli: Declared outputs skipped (--only). Showing auto-detected key '{key_found}'."
                else:
                    msg = (
                        f"cli: No outputs declared — showing auto-detected key '{key_found}'."
                        " Declare outputs for reliable results."
                    )
                click.echo(msg, err=True)
            _output_with_header(value, print_flag)
            output_found = True

    return output_found


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

    # First attempt: use already-populated outputs (preferred path via compiler wrapper)
    if _emit_declared_output(shared_storage, declared_outputs, print_flag):
        return True

    # Populate on-demand if not present
    _populate_declared_outputs_best_effort(shared_storage, workflow_ir)

    # Second attempt after population
    if _emit_declared_output(shared_storage, declared_outputs, print_flag):
        return True

    _warn_missing_declared_outputs(declared_outputs, verbose)
    return False


def _populate_declared_outputs_best_effort(shared_storage: dict[str, Any], workflow_ir: dict[str, Any]) -> None:
    """Best-effort population of declared outputs from source expressions."""
    from pflow.core.user_errors import OutputResolutionError
    from pflow.runtime.output_resolver import populate_declared_outputs

    try:
        populate_declared_outputs(shared_storage, workflow_ir)
    except OutputResolutionError as e:
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

    Args:
        steps: List of execution step dicts (may contain has_stderr and stderr fields)
    """
    stderr_warnings = [
        (step.get("node_id", "unknown"), step.get("stderr", ""))
        for step in steps
        if step.get("has_stderr") and step.get("stderr")
    ]

    if not stderr_warnings:
        return

    click.echo("\n⚠️  Shell stderr (exit code 0):", err=True)
    for node_id, stderr in stderr_warnings:
        # Truncate long stderr to 300 chars
        stderr_preview = stderr[:300]
        if len(stderr) > 300:
            stderr_preview += "..."
        # Indent multiline stderr for readability
        indented = stderr_preview.replace("\n", "\n     ")
        click.echo(f"  • {node_id}: {indented}", err=True)


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
            click.echo(f"⚠️  Cost unavailable — model not in pricing table: {models_str}", err=True)
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

    only_node = execution.get("only_node")
    nodes_skipped = execution.get("nodes_skipped", 0)
    if only_node and nodes_skipped > 0:
        noun = "node" if nodes_skipped == 1 else "nodes"
        click.echo(f"  ⤷ Stopped after '{only_node}' (--only), {nodes_skipped} remaining {noun} skipped", err=True)

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
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
    status: Any = None,
    warnings: list[Any] | None = None,
) -> bool:
    """Handle JSON formatted output.

    Returns all declared outputs or specified key as JSON, optionally with metrics.
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
            metrics_collector,
            workflow_metadata,
            workflow_trace,
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
