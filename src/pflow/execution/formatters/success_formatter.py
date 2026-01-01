"""Success output formatter for workflow execution.

This module provides a shared formatter for successful workflow execution results,
ensuring CLI and MCP return identical output structures.
"""

from typing import Any, Optional

from pflow.core.workflow_status import WorkflowStatus


def format_execution_success(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any],
    metrics_collector: Any,
    workflow_metadata: Optional[dict[str, Any]] = None,
    output_key: Optional[str] = None,
    trace_path: Optional[str] = None,
    status: Optional[WorkflowStatus] = None,
    warnings: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Format successful workflow execution output.

    Args:
        shared_storage: Shared storage dictionary from execution
        workflow_ir: Workflow IR specification
        metrics_collector: MetricsCollector instance with execution metrics
        workflow_metadata: Optional workflow metadata (action, name)
        output_key: Optional specific output key to return
        trace_path: Optional path to execution trace file
        status: Optional tri-state workflow status (SUCCESS/DEGRADED/FAILED)
        warnings: Optional list of warning dictionaries

    Returns:
        Dictionary with formatted execution results matching CLI structure
    """
    # Collect outputs from shared storage
    outputs = _collect_outputs(shared_storage, workflow_ir, output_key)

    # Build base result structure
    result = {
        "success": True,
        "result": outputs,
    }

    # Add tri-state status (if provided, otherwise infer from success)
    if status:
        result["status"] = status.value
    else:
        result["status"] = "success"  # Backward compatibility default

    # Add workflow metadata (default to unsaved if not provided)
    result["workflow"] = workflow_metadata if workflow_metadata else {"action": "unsaved"}

    # Add warnings if present
    if warnings:
        result["warnings"] = warnings

    # Add metrics from collector
    if metrics_collector:
        llm_calls = shared_storage.get("__llm_calls__", [])
        metrics_summary = metrics_collector.get_summary(llm_calls)

        # Add top-level metrics (CLI structure)
        result["duration_ms"] = metrics_summary.get("duration_ms")
        result["total_cost_usd"] = metrics_summary.get("total_cost_usd")

        # Extract workflow node count (not planner nodes)
        workflow_metrics = metrics_summary.get("metrics", {}).get("workflow", {})
        result["nodes_executed"] = int(workflow_metrics.get("nodes_executed", 0))

        # Add detailed metrics structure
        result["metrics"] = metrics_summary.get("metrics", {})

        # Add execution state with per-node details
        if workflow_ir and shared_storage:
            from pflow.execution.execution_state import build_execution_steps

            steps = build_execution_steps(workflow_ir, shared_storage, metrics_summary)
            if steps:
                # Count nodes by status
                completed_count = sum(1 for s in steps if s["status"] == "completed")
                nodes_total = len(steps)

                result["execution"] = {
                    "duration_ms": metrics_summary.get("duration_ms"),
                    "nodes_executed": completed_count,
                    "nodes_total": nodes_total,
                    "steps": steps,
                }

                # Add repaired flag if any nodes were modified
                modified_nodes = shared_storage.get("__modified_nodes__", [])
                if modified_nodes:
                    result["repaired"] = True

    # Add trace_path if provided (MCP bonus feature)
    if trace_path:
        result["trace_path"] = trace_path

    return result


def _collect_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any],
    output_key: Optional[str] = None,
) -> dict[str, Any]:
    """Collect outputs from shared storage for JSON formatting.

    Args:
        shared_storage: Shared storage dictionary
        workflow_ir: Workflow IR specification
        output_key: Optional specific key to output

    Returns:
        Dictionary of outputs to include in result
    """

    from pflow.core.json_utils import parse_json_or_original

    result = {}

    if output_key:
        # Specific key requested
        if output_key in shared_storage:
            result[output_key] = parse_json_or_original(shared_storage[output_key])

    elif workflow_ir and "outputs" in workflow_ir and workflow_ir["outputs"]:
        # Collect ALL declared outputs
        declared = workflow_ir["outputs"]

        for output_name in declared:
            if output_name in shared_storage:
                result[output_name] = parse_json_or_original(shared_storage[output_name])

    else:
        # Fallback: Use auto-detection
        key_found, value = _find_auto_output(shared_storage)
        if key_found:
            result[key_found] = parse_json_or_original(value)

    return result


def _find_auto_output(shared: dict[str, Any]) -> tuple[Optional[str], Any]:
    """Find output automatically from shared storage.

    Tries common output patterns to find the most likely output value.

    Args:
        shared: Shared storage dictionary

    Returns:
        Tuple of (key, value) if found, otherwise (None, None)
    """
    # Filter out internal keys
    user_keys = {k: v for k, v in shared.items() if not k.startswith("__")}

    if not user_keys:
        return None, None

    # Try common output keys first
    common_keys = ["result", "output", "response", "text", "data"]
    for key in common_keys:
        if key in user_keys:
            return key, user_keys[key]

    # Try last node's output (heuristic: likely to be final result)
    # Get the last key that was set (most recent)
    if user_keys:
        last_key = list(user_keys.keys())[-1]
        return last_key, user_keys[last_key]

    return None, None


def format_success_as_text(success_dict: dict[str, Any]) -> str:  # noqa: C901
    """Convert success dictionary to human-readable text (matches CLI format exactly).

    Args:
        success_dict: Dictionary from format_execution_success()

    Returns:
        Formatted text string matching CLI output
    """
    lines = []

    # Extract data
    duration_ms = success_dict.get("duration_ms", 0)
    duration_sec = duration_ms / 1000 if duration_ms else 0
    total_cost = success_dict.get("total_cost_usd")
    workflow_metadata = success_dict.get("workflow", {})
    workflow_name = workflow_metadata.get("name", "workflow")
    workflow_action = workflow_metadata.get("action", "executed")
    status = success_dict.get("status", "success")

    # Show workflow name and action (matches CLI)
    if workflow_action == "reused":
        lines.append(f"{workflow_name} was executed")
    elif workflow_action == "created":
        lines.append(f"{workflow_name} was created and executed")
    # Skip for "unsaved" workflows

    # Success header with tri-state status
    if status == "degraded":
        lines.append(f"⚠️ Workflow completed with warnings in {duration_sec:.3f}s")
    elif status == "failed":
        lines.append(f"❌ Workflow failed after {duration_sec:.3f}s")
    else:
        lines.append(f"✓ Workflow completed in {duration_sec:.3f}s")

    # Show node execution details (matches CLI lines 646-655)
    _append_execution_steps(lines, success_dict.get("execution", {}))

    # Show cost if > 0 (matches CLI lines 604-606)
    if total_cost and total_cost > 0:
        metrics = success_dict.get("metrics", {})
        workflow_metrics = metrics.get("workflow", {})
        total_tokens = workflow_metrics.get("total_tokens", 0)

        if total_tokens > 0:
            lines.append(f"💰 Cost: ${total_cost:.4f} ({total_tokens:,} tokens)")
        else:
            lines.append(f"💰 Cost: ${total_cost:.4f}")

    # Show warnings if present (matches CLI format with proper indentation)
    warnings = success_dict.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("⚠️ Warnings:")
        for warning in warnings:
            node_id = warning.get("node_id", "unknown")
            warning_type = warning.get("type", "warning")
            message = warning.get("message", "No message")

            # Header line (matches CLI)
            lines.append(f"  • {node_id} ({warning_type}):")

            # Multi-line message with proper indentation (matches CLI)
            for line in message.split("\n"):
                if line.strip():  # Skip empty lines
                    lines.append(f"    {line}")

    # Show outputs if present (matches CLI "Workflow output:" section)
    result = success_dict.get("result", {})
    if result:
        lines.append("")
        lines.append("Workflow output:")
        lines.append("")
        _append_outputs(lines, result)

    # Note: Trace path not shown in CLI text mode, only in MCP for debugging
    # Agents can use trace_path from the dict if needed

    return "\n".join(lines)


def _append_outputs(lines: list[str], result: dict[str, Any]) -> None:
    """Append formatted outputs to lines list (matches CLI behavior).

    CLI outputs the FIRST output's value directly (not key: value format).
    """
    if not result:
        return

    # Get the first output value (matches CLI behavior)
    first_value = next(iter(result.values()))

    # Output the value directly as string (matches CLI safe_output())
    if isinstance(first_value, str):
        lines.append(first_value)
    else:
        lines.append(str(first_value))


def _append_execution_steps(lines: list[str], execution: dict[str, Any]) -> None:
    """Append execution step details to lines list.

    For batch nodes with errors, also appends a batch errors section
    showing failed item indices and error messages.
    """
    if not execution or "steps" not in execution:
        return

    steps = execution["steps"]
    nodes_executed = execution.get("nodes_executed", 0)

    lines.append(f"Nodes executed ({nodes_executed}):")
    for step in steps:
        formatted_step = _format_execution_step(step)
        lines.append(formatted_step)

    # Add batch errors section if any batch nodes had failures
    batch_error_lines = _format_batch_errors_section(steps)
    if batch_error_lines:
        lines.extend(batch_error_lines)


def _truncate_error_message(message: str, max_length: int = 200) -> str:
    """Truncate error message to max length with ellipsis.

    Args:
        message: Error message to truncate
        max_length: Maximum characters (default 200)

    Returns:
        Truncated message with "..." if over limit
    """
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


def _format_batch_node_line(step: dict[str, Any]) -> str:
    """Format a batch node's status line with summary.

    Examples:
        "  ✓ process (31ms) - 10/10 items succeeded"
        "  ⚠ process (31ms) - 8/10 items succeeded, 2 failed"

    Args:
        step: Execution step dict with batch metadata

    Returns:
        Formatted status line string
    """
    node_id = step.get("node_id", "unknown")
    duration = step.get("duration_ms") or 0
    total = step.get("batch_total", 0)
    success = step.get("batch_success", 0)
    errors = step.get("batch_errors", 0)
    cached = step.get("cached", False)
    repaired = step.get("repaired", False)

    # Build timing string
    timing = f"({int(duration)}ms)"

    # Build additional tags
    tags = []
    if cached:
        tags.append("cached")
    if repaired:
        tags.append("repaired")
    tag_str = f" [{', '.join(tags)}]" if tags else ""

    if errors > 0:
        # Partial success - warning indicator
        return f"  ⚠ {node_id} {timing} - {success}/{total} items succeeded, {errors} failed{tag_str}"
    else:
        # Full success - checkmark
        return f"  ✓ {node_id} {timing} - {total}/{total} items succeeded{tag_str}"


def _format_batch_errors_section(steps: list[dict[str, Any]]) -> list[str]:
    """Format batch errors section for all batch nodes with failures.

    Example output:
        Batch 'process' errors:
          [1] Command failed with exit code 1
          [4] Connection timeout after 30s
          ...and 3 more errors

    Args:
        steps: List of execution step dicts

    Returns:
        List of formatted lines (empty if no batch errors)
    """
    lines: list[str] = []

    for step in steps:
        if not step.get("is_batch") or step.get("batch_errors", 0) == 0:
            continue

        node_id = step.get("node_id", "unknown")
        error_details = step.get("batch_error_details", [])
        truncated = step.get("batch_errors_truncated", 0)

        lines.append(f"\nBatch '{node_id}' errors:")
        for err in error_details:
            idx = err.get("index", "?")
            msg = _truncate_error_message(str(err.get("error", "Unknown error")))
            lines.append(f"  [{idx}] {msg}")

        if truncated > 0:
            lines.append(f"  ...and {truncated} more errors")

    return lines


def _format_execution_step(step: dict[str, Any]) -> str:
    """Format a single execution step.

    For batch nodes, delegates to _format_batch_node_line() for enhanced display.
    For regular nodes, shows standard status line.
    """
    # Check if this is a batch node
    if step.get("is_batch"):
        return _format_batch_node_line(step)

    # Regular node formatting
    node_id = step.get("node_id", "unknown")
    status = step.get("status", "unknown")
    duration = step.get("duration_ms") or 0  # Handle explicit None
    cached = step.get("cached", False)
    repaired = step.get("repaired", False)

    # Build status indicator
    indicator_map = {"completed": "✓", "failed": "❌"}
    indicator = indicator_map.get(status, "⚠️")

    # Build additional tags
    tags = []
    if cached:
        tags.append("cached")
    if repaired:
        tags.append("repaired")

    tag_str = f" [{', '.join(tags)}]" if tags else ""
    # Round duration to integer for readability (matches CLI format)
    return f"  {indicator} {node_id} ({int(duration)}ms){tag_str}"


def _append_footer(lines: list[str], cost: Optional[float], trace_path: Optional[str]) -> None:
    """Append cost and trace footer to lines list."""
    if not cost and not trace_path:
        return

    parts = []
    if cost:
        parts.append(f"Cost: ${cost:.4f}")
    if trace_path:
        parts.append(f"Trace: {trace_path}")

    lines.append("")
    lines.append(" | ".join(parts))
