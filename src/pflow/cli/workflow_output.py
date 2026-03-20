"""Workflow output handling — detection, display, and formatting."""

from __future__ import annotations

import json
import os
from typing import Any

import click


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


def _output_with_header(value: Any, print_flag: bool, output_controller: Any, description: str | None = None) -> None:
    """Output value with appropriate header and stream routing based on execution mode.

    Three execution modes with different output strategies:

    1. --print mode (print_flag=True):
       - Use case: Piping output to other commands
       - Behavior: ONLY raw output to stdout, no header, no summary
       - Example: pflow --print my-workflow | jq

    2. Interactive terminal (is_interactive()=True):
       - Use case: Normal terminal usage with TTY
       - Behavior: Unix convention - header/summary to stderr, data to stdout
       - Rationale: Separates progress info from pipeable data
       - Example: pflow my-workflow (in terminal)

    3. Non-interactive (is_interactive()=False, print_flag=False):
       - Use case: Claude Code, CI/CD, non-TTY environments
       - Behavior: Everything to stderr for correct ordering
       - Rationale: Tools that capture streams separately may show stdout before stderr,
                    causing output to appear before summary. Keeping everything on stderr
                    preserves the intended order: summary → header → output
       - Example: pflow my-workflow (in Claude Code)

    Args:
        value: The output value to display
        print_flag: Whether --print flag is set
        output_controller: OutputController for interactive detection
        description: Optional description from workflow output declaration
    """
    # Build header with optional description
    header = f"\nWorkflow output ({description}):\n" if description else "\nWorkflow output:\n"

    if print_flag:
        # Mode 1: --print - raw output only (no header)
        safe_output(value)
    elif output_controller and output_controller.is_interactive():
        # Mode 2: Interactive - Unix convention
        click.echo(header, err=True)
        safe_output(value)
    else:
        # Mode 3: Non-interactive - everything on stderr
        click.echo(header, err=True)
        if isinstance(value, str):
            click.echo(value, err=True)
        else:
            click.echo(str(value), err=True)


def _is_valid_output_value(value: Any) -> bool:
    """Check if a value is valid for output.

    Args:
        value: The value to check

    Returns:
        True if the value is non-None and (not a string or non-empty string)
    """
    return value is not None and (not isinstance(value, str) or value.strip() != "")


def _find_in_namespaces(shared_storage: dict[str, Any], key: str) -> Any:
    """Find the last occurrence of a key in namespaced storage.

    Args:
        shared_storage: The shared storage dictionary
        key: The key to search for

    Returns:
        The last valid value found, or None
    """
    last_value = None

    for storage_key, namespace_dict in shared_storage.items():
        # Skip non-dict values and special keys
        if not isinstance(namespace_dict, dict):
            continue
        if storage_key.startswith("__") or storage_key.startswith("_"):
            continue

        # Check if this namespace contains the key
        if key in namespace_dict:
            value = namespace_dict[key]
            if _is_valid_output_value(value):
                last_value = value

    return last_value


def _find_auto_output(shared_storage: dict[str, Any]) -> tuple[str | None, Any]:
    """Find the auto-detectable output with the highest priority.

    In sequential workflows, returns the last occurrence of the highest priority key.
    Priority order: response > output > result > text > stdout

    Args:
        shared_storage: The shared storage dictionary

    Returns:
        Tuple of (key_found, value) or (None, None) if no output found
    """
    # Common output keys in priority order (highest priority first)
    priority_keys = ["response", "output", "result", "text", "stdout"]

    # For each priority level, find the LAST occurrence
    for priority_key in priority_keys:
        # Check namespaced storage first
        last_value = _find_in_namespaces(shared_storage, priority_key)
        if last_value is not None:
            return priority_key, last_value

        # Check direct storage (legacy/non-namespaced)
        if priority_key in shared_storage:
            value = shared_storage[priority_key]
            # Skip special dictionaries that are actually namespaces
            if not isinstance(value, dict) and _is_valid_output_value(value):
                return priority_key, value
            # Handle the case where it might be a dict but not a namespace
            if isinstance(value, dict) and not any(k in priority_keys for k in value) and _is_valid_output_value(value):
                return priority_key, value

    return None, None


def _handle_text_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool = False,
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    output_controller: Any = None,
    status: Any = None,
    warnings: list[dict[str, Any]] | None = None,
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

        _display_execution_summary(formatted, verbose)

    # Now show the actual output
    output_found = False

    # User-specified key takes priority
    if output_key:
        if output_key in shared_storage:
            _output_with_header(shared_storage[output_key], print_flag, output_controller)
            output_found = True
        else:
            # Suppress warnings in -p mode
            if not print_flag:
                click.echo(f"cli: Warning - output key '{output_key}' not found in shared store", err=True)

    # Check workflow-declared outputs
    elif workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]:
        if _try_declared_outputs(
            shared_storage, workflow_ir, verbose and not print_flag, print_flag, output_controller
        ):
            output_found = True

    # Fall back to auto-detect from common keys (using unified function)
    else:
        key_found, value = _find_auto_output(shared_storage)
        if key_found:
            _output_with_header(value, print_flag, output_controller)
            output_found = True

    return output_found


def _emit_declared_output(
    shared_storage: dict[str, Any],
    declared_outputs: dict[str, Any],
    verbose: bool,
    print_flag: bool,
    output_controller: Any = None,
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

            _output_with_header(value, print_flag, output_controller, description)
            return True
    return False


def _try_declared_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    print_flag: bool,
    output_controller: Any = None,
) -> bool:
    """Try to output from workflow-declared outputs.

    Args:
        shared_storage: The shared storage dictionary
        workflow_ir: The workflow IR specification
        verbose: Whether to show verbose output
        print_flag: Whether in non-interactive/print mode
        output_controller: OutputController for interactive detection

    Returns:
        True if a declared output was found and printed, False otherwise
    """
    if not (workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]):
        return False

    declared_outputs = workflow_ir["outputs"]

    # First attempt: use already-populated outputs (preferred path via compiler wrapper)
    if _emit_declared_output(shared_storage, declared_outputs, verbose, print_flag, output_controller):
        return True

    # Populate on-demand if not present
    _populate_declared_outputs_best_effort(shared_storage, workflow_ir)

    # Second attempt after population
    if _emit_declared_output(shared_storage, declared_outputs, verbose, print_flag, output_controller):
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
        click.echo(f"Warning: {e.title}\n{e.explanation}", err=True)
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


def _get_status_indicator(status: str) -> str:
    """Get display indicator for node execution status.

    Args:
        status: Node execution status

    Returns:
        Single character indicator symbol
    """
    indicators = {
        "completed": "✓",
        "failed": "✗",
        "not_executed": "○",
    }
    return indicators.get(status, "?")


def _format_node_timing(duration_ms: int | float) -> str:
    """Format node execution timing for display.

    Args:
        duration_ms: Duration in milliseconds

    Returns:
        Formatted timing string
    """
    return f"({int(duration_ms)}ms)" if duration_ms and duration_ms > 0 else "(<1ms)"


def _format_node_status_line(step: dict[str, Any]) -> str:
    """Format complete node status line for display.

    For batch nodes, shows item success/failure counts.
    For regular nodes, shows standard status line.

    Args:
        step: Execution step dict with node_id, status, duration_ms, cached,
              and optional batch fields (is_batch, batch_total, batch_success, batch_errors)

    Returns:
        Formatted status line
    """
    node_id = step.get("node_id", "unknown")
    status = step.get("status", "unknown")
    duration_ms = step.get("duration_ms", 0)
    cached = step.get("cached", False)

    timing = _format_node_timing(duration_ms)

    # Build additional tags
    tags = []
    if cached:
        tags.append("cached")
    # Add smart handling tag for visibility (grep no-match, which not-found, etc.)
    # Tag mapping for smart handling patterns defined in shell.py _is_safe_non_error().
    # When adding new patterns there, ensure reason contains "no matches" or "not found",
    # OR add a new elif branch here. Fallback shows raw reason to avoid silent mystery.
    if step.get("smart_handled"):
        reason = step.get("smart_handled_reason", "")
        if "no matches" in reason:
            tags.append("no matches")
        elif "not found" in reason:
            tags.append("not found")
        elif reason:
            # Unknown pattern - show actual reason so agent knows what happened
            tags.append(reason)
    tag_str = f" [{', '.join(tags)}]" if tags else ""

    # Check if this is a batch node
    if step.get("is_batch"):
        total = step.get("batch_total", 0)
        success = step.get("batch_success", 0)
        errors = step.get("batch_errors", 0)

        if errors > 0:
            # Partial success - warning indicator
            return f"  ⚠ {node_id} {timing} - {success}/{total} items succeeded, {errors} failed{tag_str}"
        else:
            # Full success - checkmark
            return f"  ✓ {node_id} {timing} - {total}/{total} items succeeded{tag_str}"

    # Regular node
    # Use warning indicator if node produced stderr (has_stderr already implies completed)
    if step.get("has_stderr"):
        return f"  ⚠ {node_id} {timing}{tag_str}"

    indicator = _get_status_indicator(status)
    return f"  {indicator} {node_id} {timing}{tag_str}"


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


def _display_workflow_completion_status(duration_s: float, status: str, has_stderr_warnings: bool) -> None:
    """Display workflow completion status with appropriate indicator.

    Args:
        duration_s: Execution duration in seconds
        status: Workflow status ("success", "degraded", "failed")
        has_stderr_warnings: Whether any shell node produced stderr with exit_code=0
    """
    if status == "degraded":
        click.echo(f"⚠️ Workflow completed with warnings in {duration_s:.3f}s", err=True)
    elif status == "failed":
        click.echo(f"❌ Workflow failed after {duration_s:.3f}s", err=True)
    elif has_stderr_warnings:
        click.echo(f"⚠️ Workflow completed in {duration_s:.3f}s", err=True)
    else:
        click.echo(f"✓ Workflow completed in {duration_s:.3f}s", err=True)


def _display_execution_summary(formatted_result: dict[str, Any], verbose: bool) -> None:
    """Display execution summary with metrics in text mode.

    Always shows:
    - Workflow name and action
    - Total execution time
    - Per-node execution details (timing, cache status)
    - LLM cost and token usage (if > 0)

    Args:
        formatted_result: Formatted result from format_execution_success()
        verbose: Currently unused, kept for compatibility
    """
    duration_ms = formatted_result.get("duration_ms")
    total_cost = formatted_result.get("total_cost_usd")

    # Extract execution details
    execution = formatted_result.get("execution", {})
    steps = execution.get("steps", []) if execution else []

    # Extract workflow metadata
    workflow_metadata = formatted_result.get("workflow", {})
    workflow_name = workflow_metadata.get("name", "workflow")
    workflow_action = workflow_metadata.get("action", "executed")

    # Count nodes
    total_nodes = len(steps)

    # Show workflow name and action (but not for unsaved workflows)
    _display_workflow_action(workflow_name, workflow_action)

    # Show total execution time with status-aware message
    if duration_ms is not None:
        duration_s = duration_ms / 1000.0
        status = formatted_result.get("status", "success")
        has_stderr_warnings = any(step.get("has_stderr") for step in steps)
        _display_workflow_completion_status(duration_s, status, has_stderr_warnings)

    # Show per-node execution details
    if steps:
        click.echo(f"Nodes executed ({total_nodes}):", err=True)
        for step in steps:
            status_line = _format_node_status_line(step)
            click.echo(status_line, err=True)

        # Show batch errors section if any batch nodes had failures
        _display_batch_errors(steps)

        # Show stderr warnings for shell nodes that succeeded but produced stderr
        _display_stderr_warnings(steps)

    # Show cost if > 0
    _display_cost_summary(total_cost, formatted_result)

    # Show warnings if present
    warnings = formatted_result.get("warnings", [])
    if warnings:
        click.echo("", err=True)
        click.echo("⚠️ Warnings:", err=True)
        for warning in warnings:
            node_id = warning.get("node_id", "unknown")
            warning_type = warning.get("type", "warning")
            message = warning.get("message", "No message")

            # Show the full warning message with proper indentation
            click.echo(f"  • {node_id} ({warning_type}):", err=True)
            for line in message.split("\n"):
                if line.strip():  # Skip empty lines
                    click.echo(f"    {line}", err=True)


def _handle_json_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None,
    verbose: bool,
    metrics_collector: Any | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
    status: Any = None,
    warnings: list[dict[str, Any]] | None = None,
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


def _get_default_workflow_metadata() -> dict[str, Any]:
    """Get default workflow metadata when none is provided."""
    return {"action": "unsaved"}


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


def _extract_workflow_node_count(metrics_summary: dict[str, Any]) -> int:
    """Extract workflow node count from metrics summary.

    Only counts workflow nodes.
    """
    workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
    node_count = workflow_metrics.get("nodes_executed", 0)
    return int(node_count)  # Ensure we return an int


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
    output_controller: Any = None,
    status: Any = None,
    warnings: list[dict[str, Any]] | None = None,
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
            output_controller=output_controller,
            status=status,
            warnings=warnings,
        )
