"""Workflow error display and formatting."""

from __future__ import annotations

from typing import Any

import click

from pflow.cli.workflow_output import (
    _extract_workflow_node_count,
    _get_default_workflow_metadata,
    _serialize_json_result,
)


def _create_json_error_output(
    exception: Exception,
    metrics_collector: Any | None = None,
    shared_storage: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create unified JSON error structure.

    Args:
        exception: The exception that occurred
        metrics_collector: Optional metrics collector
        shared_storage: Optional shared storage for LLM calls
        workflow_metadata: Optional workflow metadata

    Returns:
        Dictionary with unified error structure
    """
    from pflow.core.user_errors import UserFriendlyError

    # Determine error type
    suggestion: str | None
    if isinstance(exception, UserFriendlyError):
        error_type = exception.__class__.__name__
        # Extract components from UserFriendlyError
        message = exception.title
        details = exception.explanation
        # Join suggestions list into a single string
        suggestion = " ".join(exception.suggestions) if exception.suggestions else None
    else:
        error_type = exception.__class__.__name__
        message = str(exception)
        details = None
        suggestion = None

    # Build error structure
    error_dict: dict[str, Any] = {
        "type": error_type,
        "message": message,
    }

    # Add optional error fields
    if details:
        error_dict["details"] = details
    if suggestion:
        error_dict["suggestion"] = suggestion

    result = {
        "success": False,
        "error": error_dict,
    }

    # Add workflow metadata if available
    result["workflow"] = workflow_metadata if workflow_metadata else _get_default_workflow_metadata()

    # Add metrics if available
    if metrics_collector:
        metrics_collector.record_workflow_end()
        trace = shared_storage.get("_trace_collector") if shared_storage else None
        llm_calls = trace.collect_llm_calls() if trace else []
        metrics_summary = metrics_collector.get_summary(llm_calls)

        # Add top-level metrics (matching success structure)
        result["duration_ms"] = metrics_summary.get("duration_ms")
        result["total_cost_usd"] = metrics_summary.get("total_cost_usd")

        # For nodes_executed, only count workflow nodes
        result["nodes_executed"] = _extract_workflow_node_count(metrics_summary)

        # Include detailed metrics
        result["metrics"] = metrics_summary.get("metrics", {})

        # Add execution state if available
        if shared_storage and "__execution__" in shared_storage:
            exec_state = shared_storage["__execution__"]
            completed = exec_state.get("completed_nodes", [])
            failed = exec_state.get("failed_node")
            cache_hits = shared_storage.get("__cache_hits__", [])

            # Get node timings if available
            workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
            node_timings = workflow_metrics.get("node_timings", {})

            # Build simplified steps for completed/failed nodes only
            # (we don't have workflow_ir here to know all nodes)
            steps = []
            for node_id in completed:
                steps.append({
                    "node_id": node_id,
                    "status": "completed",
                    "duration_ms": node_timings.get(node_id),
                    "cached": node_id in cache_hits,
                })

            if failed and failed not in completed:
                steps.append({
                    "node_id": failed,
                    "status": "failed",
                    "duration_ms": node_timings.get(failed),
                    "cached": False,
                })

            if steps:
                result["execution"] = {
                    "duration_ms": metrics_summary.get("duration_ms"),
                    "nodes_executed": len(completed),
                    "steps": steps,
                }

    return result


def _build_json_error_response(
    result: Any,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    ir_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build structured JSON error response.

    Args:
        result: ExecutionResult from workflow execution
        metrics_collector: Metrics collector instance
        shared_storage: Shared store with execution data
        ir_data: Optional workflow IR for complete execution state

    Returns:
        Structured error response dict
    """
    error_output: dict[str, Any] = {
        "success": False,
        "status": "failed",  # Add tri-state status for failures
        "error": "Workflow execution failed",
        "is_error": True,
    }

    # Use shared error formatter (SECURITY FIX: adds sanitization)
    if result and hasattr(result, "errors") and result.errors:
        from pflow.execution.formatters.error_formatter import format_execution_errors

        formatted = format_execution_errors(
            result,
            shared_storage=shared_storage,
            ir_data=ir_data,
            metrics_collector=metrics_collector,
            sanitize=True,  # SECURITY FIX: Sanitize sensitive data in JSON output
        )

        # Add formatted errors (sanitized)
        error_output["errors"] = formatted["errors"]
        if formatted["errors"]:
            error_output["failed_node"] = formatted["errors"][0].get("node_id")

        # Add execution state if available
        if formatted.get("execution"):
            error_output["execution"] = formatted["execution"]

        # Add metrics if available
        if formatted.get("metrics"):
            error_output.update(formatted["metrics"])

    return error_output


def _display_api_error_response(raw_response: dict[str, Any]) -> None:
    """Display API error response details.

    Args:
        raw_response: Raw API response dict
    """
    click.echo("\n  API Response:", err=True)

    # GitHub/API errors often have 'errors' array
    if errors_list := raw_response.get("errors"):
        for api_err in errors_list[:3]:
            field = api_err.get("field", "unknown")
            msg = api_err.get("message", api_err.get("code", "error"))
            click.echo(f"    - Field '{field}': {msg}", err=True)
    elif msg := raw_response.get("message"):
        click.echo(f"    {msg}", err=True)

    if doc_url := raw_response.get("documentation_url"):
        click.echo(f"\n  Documentation: {doc_url}", err=True)


def _display_mcp_error_details(mcp_error: dict[str, Any]) -> None:
    """Display MCP tool error details.

    Args:
        mcp_error: MCP error dict
    """
    click.echo("\n  MCP Tool Error:", err=True)

    if details := mcp_error.get("details"):
        click.echo(f"    Field: {details.get('field')}", err=True)
        click.echo(f"    Expected: {details.get('expected')}", err=True)
        click.echo(f"    Received: {details.get('received')}", err=True)
    elif msg := mcp_error.get("message"):
        click.echo(f"    {msg}", err=True)


def _display_single_error(
    error: dict[str, Any],
    error_number: int,
    verbose: bool = False,
) -> None:
    """Display a single workflow error with all details.

    Args:
        error: Error dict from ExecutionResult
        error_number: Error number for display (1-indexed)
        verbose: Whether to show extended details (command, stdout, etc.)
    """
    if error_number == 1:
        click.echo("❌ Workflow execution failed", err=True)

    node_id = error.get("node_id", "unknown")
    category = error.get("category", "unknown")
    message = error.get("message", "Unknown error")

    click.echo(f"\nError {error_number} at node '{node_id}':", err=True)
    click.echo(f"  Category: {category}", err=True)
    click.echo(f"  Message: {message}", err=True)

    # Show raw API response if available (SECURITY FIX: Sanitize before display)
    if (raw := error.get("raw_response")) and isinstance(raw, dict):
        from pflow.mcp_server.utils.errors import sanitize_parameters

        sanitized_raw = sanitize_parameters(raw)
        _display_api_error_response(sanitized_raw)

    # Show MCP error details (SECURITY FIX: Sanitize before display)
    if (mcp := error.get("mcp_error")) and isinstance(mcp, dict):
        from pflow.mcp_server.utils.errors import sanitize_parameters

        sanitized_mcp = sanitize_parameters(mcp)
        _display_mcp_error_details(sanitized_mcp)

    # Show available fields for template errors
    if category == "template_error" and (available := error.get("available_fields")):
        total = error.get("available_fields_total", len(available))
        click.echo(f"\n  Available fields in node (showing {min(len(available), 5)} of {total}):", err=True)
        for field in available[:5]:
            click.echo(f"    - {field}", err=True)
        if len(available) > 5:
            click.echo(f"    ... and {len(available) - 5} more (in error details)", err=True)

        # Show trace file hint if fields were truncated
        if error.get("available_fields_truncated"):
            click.echo("\n  📁 Complete field list available in trace file", err=True)
            click.echo("     ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json", err=True)

    # Show shell command details in verbose mode
    if verbose and "shell_command" in error:
        _display_shell_error_details(error)


def _display_shell_error_details(error: dict[str, Any]) -> None:
    """Display shell command details for a failed shell node.

    Args:
        error: Error dict containing shell_command, shell_stdout, shell_stderr
    """
    click.echo("\n  Shell details:", err=True)
    cmd = error.get("shell_command", "")
    # Truncate very long commands
    cmd_display = cmd[:200] + "..." if len(cmd) > 200 else cmd
    click.echo(f"    Command: {cmd_display}", err=True)
    if stdout := error.get("shell_stdout"):
        stdout_preview = stdout[:300] + "..." if len(stdout) > 300 else stdout
        click.echo(f"    Stdout: {stdout_preview}", err=True)
    if stderr := error.get("shell_stderr"):
        stderr_preview = stderr[:300] + "..." if len(stderr) > 300 else stderr
        click.echo(f"    Stderr: {stderr_preview}", err=True)


def _display_text_error_details(
    result: Any,
    verbose: bool = False,
) -> None:
    """Display detailed text error output.

    Args:
        result: ExecutionResult with error details
        verbose: Whether to show extended details (command, stdout, etc.)
    """
    if not result or not hasattr(result, "errors") or not result.errors:
        # Fallback to generic message
        click.echo("cli: Workflow execution failed - Node returned error action", err=True)
        click.echo("cli: Check node output above for details", err=True)
        return

    for i, error in enumerate(result.errors, 1):
        _display_single_error(error, i, verbose=verbose)


def _format_compilation_error_text(e: Exception, verbose: bool) -> None:
    """Format and display compilation error in text mode.

    Args:
        e: The exception to format
        verbose: Whether to show verbose output
    """
    from pflow.core.user_errors import UserFriendlyError
    from pflow.runtime import CompilationError as CompilerCompilationError

    if isinstance(e, UserFriendlyError):
        # Use the formatted user-friendly error
        error_message = e.format_for_cli(verbose=verbose)
        click.echo(error_message, err=True)
    elif isinstance(e, CompilerCompilationError):
        click.echo(f"❌ Compilation failed: {e}", err=True)
        if hasattr(e, "suggestion") and e.suggestion:
            click.echo(f"\n{e.suggestion}", err=True)
        if verbose:
            click.echo(f"\ncli: Error details: {e}", err=True)
    else:
        # Fallback for other exceptions
        click.echo(f"❌ Compilation failed: {e}", err=True)
        if verbose:
            click.echo(f"cli: Error details: {e}", err=True)


def _handle_compilation_error_json(
    ctx: Any,
    e: Exception,
    metrics_collector: Any | None,
) -> None:
    """Handle compilation error in JSON output mode.

    Args:
        ctx: Click context
        e: The exception to handle
        metrics_collector: Optional metrics collector
    """
    verbose = ctx.obj.get("verbose", False)
    workflow_metadata = ctx.obj.get("workflow_metadata")
    error_output = _create_json_error_output(
        e,
        metrics_collector,
        None,  # No shared_storage at compilation time
        workflow_metadata,
    )
    _serialize_json_result(error_output, verbose)
