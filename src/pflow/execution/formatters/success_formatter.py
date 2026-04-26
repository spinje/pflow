"""Success output formatter for workflow execution.

This module provides a shared formatter for successful workflow execution results,
ensuring CLI and MCP return identical output structures.
"""

import json
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.workflow.status import WorkflowStatus


def format_execution_success(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any],
    metrics_collector: Any,
    workflow_metadata: Optional[dict[str, Any]] = None,
    output_key: Optional[str] = None,
    trace_path: Optional[str] = None,
    status: Optional[WorkflowStatus] = None,
    warnings: Optional[list[Any]] = None,
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

    warning_diagnostics = warnings or []
    result["warnings"] = [warning.to_display_dict() for warning in warning_diagnostics]
    result["diagnostics"] = [warning.to_dict() for warning in warning_diagnostics]

    # Add metrics from collector
    if metrics_collector:
        trace = shared_storage.get("__trace_collector__") if shared_storage else None
        llm_calls = trace.collect_llm_calls() if trace else []
        metrics_summary = metrics_collector.get_summary(llm_calls)

        # Add top-level metrics (CLI structure). When pricing is unavailable
        # for any LLM call (LiteLLM doesn't recognize the model — Ollama,
        # custom endpoints, brand-new releases), surface the tri-state
        # discriminators alongside the bare null cost so JSON consumers can
        # distinguish "no LLM calls" from "LLM calls happened but pricing
        # data missing."
        result["duration_ms"] = metrics_summary.get("duration_ms")
        result["total_cost_usd"] = metrics_summary.get("total_cost_usd")
        _mirror_pricing_tri_state(result, metrics_summary)

        # Extract workflow node count
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

                execution_dict: dict[str, Any] = {
                    "duration_ms": metrics_summary.get("duration_ms"),
                    "nodes_executed": completed_count,
                    "nodes_total": nodes_total,
                    "steps": steps,
                }

                # --only metadata (from __execution__ state)
                exec_state = shared_storage.get("__execution__", {})
                only_node_val = exec_state.get("only_node")
                if only_node_val:
                    execution_dict["only_node"] = only_node_val
                    not_executed_count = sum(1 for s in steps if s["status"] == "not_executed")
                    execution_dict["nodes_skipped"] = not_executed_count

                # Aggregate cache stats
                cache_hit_count = sum(1 for s in steps if s.get("cached"))
                if cache_hit_count > 0:
                    execution_dict["cache_hits"] = cache_hit_count

                result["execution"] = execution_dict

    # Add trace_path if provided (MCP bonus feature)
    if trace_path:
        result["trace_path"] = trace_path

    return result


def _mirror_pricing_tri_state(result: dict[str, Any], metrics_summary: dict[str, Any]) -> None:
    """Mirror the pricing tri-state (partial_cost_usd / pricing_available /
    unavailable_models) from metrics_summary to top-level result keys.

    When pricing is unavailable for any LLM call, the bare top-level
    ``total_cost_usd: null`` is ambiguous — agents can't tell "no LLM calls"
    from "calls happened but pricing data missing." Mirroring the
    discriminators alongside makes the cause obvious without drilling into
    ``result["metrics"]["total"]``.
    """
    if metrics_summary.get("pricing_available") is not False:
        return
    result["pricing_available"] = False
    partial_cost = metrics_summary.get("partial_cost_usd")
    if partial_cost is not None:
        result["partial_cost_usd"] = partial_cost
    unavailable = metrics_summary.get("unavailable_models")
    if unavailable:
        result["unavailable_models"] = list(unavailable)


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

    elif (
        workflow_ir
        and "outputs" in workflow_ir
        and workflow_ir["outputs"]
        and not shared_storage.get("__execution__", {}).get("only_node")
    ):
        # Collect ALL declared outputs (skip when --only is active — declared outputs
        # reference downstream nodes that didn't execute; use auto-detection instead)
        declared = workflow_ir["outputs"]

        for output_name in declared:
            if output_name in shared_storage:
                result[output_name] = parse_json_or_original(shared_storage[output_name])

    else:
        # Auto-detect output (handles both --only and no-declared-outputs cases).
        # find_auto_output is namespace-aware: looks inside node namespace dicts
        # for common output keys, so it finds the target node's stdout/result/response.
        # Under --only, pass the target's root segment as preferred_key so the
        # user's explicit target wins over unrelated resolved declared outputs
        # at root (GH #344).
        from pflow.execution.formatters.output_utils import find_auto_output

        # Only dotted --only passes preferred_key — flat --only relies on
        # priority-key unwrap for clean scalar output from leaf nodes.
        only_node = shared_storage.get("__execution__", {}).get("only_node")
        preferred_key = only_node.split(".", 1)[0] if isinstance(only_node, str) and "." in only_node else None
        key_found, value = find_auto_output(shared_storage, preferred_key=preferred_key)
        if key_found:
            result[key_found] = parse_json_or_original(value)

    return result


def format_success_as_text(  # noqa: C901
    success_dict: dict[str, Any],
    warning_diagnostics: list[Diagnostic] | None = None,
) -> str:
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
    warning_count = len(success_dict.get("warnings", []))

    # Show workflow name and action (matches CLI)
    if workflow_action == "reused":
        lines.append(f"{workflow_name} was executed")
    elif workflow_action == "created":
        lines.append(f"{workflow_name} was created and executed")
    # Skip for "unsaved" workflows

    # Success header with tri-state status and optional cache stats
    execution_data = success_dict.get("execution", {})
    cache_hits = execution_data.get("cache_hits", 0)
    completed_count = execution_data.get("nodes_executed", 0)
    steps = execution_data.get("steps", [])
    has_stderr_warnings = any(step.get("has_stderr") for step in steps)
    cache_suffix = ""
    if cache_hits > 0:
        executed_fresh = completed_count - cache_hits
        cache_suffix = f" ({cache_hits} cached, {executed_fresh} executed)"

    if status == "degraded":
        lines.append(f"⚠️ Workflow completed with warnings in {duration_sec:.3f}s{cache_suffix}")
    elif status == "failed":
        if warning_count:
            lines.append(f"❌ Workflow failed ({warning_count} warnings) after {duration_sec:.3f}s{cache_suffix}")
        else:
            lines.append(f"❌ Workflow failed after {duration_sec:.3f}s{cache_suffix}")
    elif warning_count:
        lines.append(f"⚠️ Workflow completed with {warning_count} warnings in {duration_sec:.3f}s{cache_suffix}")
    elif has_stderr_warnings:
        # Shell node(s) exited 0 but wrote to stderr — upgrade glyph to ⚠️
        # so MCP consumers see the same signal CLI users do. The per-node
        # stderr block is rendered below via format_stderr_warnings().
        lines.append(f"⚠️ Workflow completed in {duration_sec:.3f}s{cache_suffix}")
    else:
        lines.append(f"✓ Workflow completed in {duration_sec:.3f}s{cache_suffix}")

    # Show node execution details (matches CLI lines 646-655)
    _append_execution_steps(lines, execution_data)

    # Shell-stderr warnings (CLI/MCP parity — mirrors CLI _display_stderr_warnings)
    lines.extend(format_stderr_warnings(steps))

    # Show cost (matches CLI _display_cost_summary)
    metrics = success_dict.get("metrics", {})
    total_metrics = metrics.get("total", {})

    if not total_metrics.get("pricing_available", True):
        unavailable = total_metrics.get("unavailable_models", [])
        models_str = ", ".join(unavailable)
        partial = total_metrics.get("partial_cost_usd")
        if partial is not None:
            lines.append(f"💰 Cost: ${partial:.4f}+ (partial — pricing unavailable for: {models_str})")
        else:
            lines.append(f"⚠️  Cost unavailable — pricing data missing for: {models_str}")
    elif total_cost and total_cost > 0:
        workflow_metrics = metrics.get("workflow", {})
        total_tokens = workflow_metrics.get("total_tokens", 0)

        if total_tokens > 0:
            lines.append(f"💰 Cost: ${total_cost:.4f} ({total_tokens:,} tokens)")
        else:
            lines.append(f"💰 Cost: ${total_cost:.4f}")

    # Show warnings if present (matches CLI format with proper indentation)
    if warning_diagnostics:
        lines.append("")
        lines.append("⚠️ Warnings:")
        for warning in warning_diagnostics:
            lines.append(format_diagnostic(warning))

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
    Mirrors ``cli/workflow_output.py::safe_output``: strings pass through
    verbatim, structured values are JSON-encoded so MCP consumers can parse
    them with ``jq`` or ``json.loads``.

    On serialization failure (e.g., NaN/Infinity inside an otherwise-valid
    structure, or a custom class whose ``__str__`` raises inside ``default=str``),
    falls back to ``repr(first_value)`` — **not** ``str(first_value)`` — to match
    CLI ``safe_output``'s fallback. The CLI also emits a stderr diagnostic in
    this case; MCP returns strings so it cannot do that, and the divergence on
    warning emission is accepted as a documented gap (see the Task 149 review).
    """
    if not result:
        return

    first_value = next(iter(result.values()))

    if isinstance(first_value, str):
        lines.append(first_value)
        return

    try:
        lines.append(json.dumps(first_value, ensure_ascii=False, allow_nan=False, default=str))
    except (TypeError, ValueError):
        # CLI safe_output falls back to repr(); match it for parity.
        lines.append(repr(first_value))


def format_only_indicator(only_node: str, nodes_skipped: int) -> str:
    """Format the ``--only`` mode confirmation line.

    Single source of truth for the ``--only`` indicator text. Used by:
    - CLI text summary (``cli/workflow_output.py::_display_execution_summary``)
    - CLI ``-p`` mode emission (``cli/workflow_output.py::_emit_only_indicator``)
    - MCP text summary (``_append_execution_steps`` below)

    Architecturally, ``--only`` is a **mode signal**, not a summary detail.
    Mode flags (which change what the workflow does) are always announced
    regardless of verbosity flags (which hide details). This matches the
    convention of ``make -k``, ``pytest --maxfail``, ``rsync --dry-run``,
    ``apt-get --simulate``, ``kubectl --dry-run``, etc.

    Two forms:
    - Some downstream nodes were skipped: ``Stopped after 'X' (--only), N remaining nodes skipped``
    - No nodes were skipped (``--only`` targeted the last node): ``Stopped after 'X' (--only)``
    The shorter form is the fix for the case where the rendered output
    was previously indistinguishable from a full run (sub-issue 8a in
    Task 149's code review).
    """
    if nodes_skipped > 0:
        noun = "node" if nodes_skipped == 1 else "nodes"
        return f"  ⤷ Stopped after '{only_node}' (--only), {nodes_skipped} remaining {noun} skipped"
    return f"  ⤷ Stopped after '{only_node}' (--only)"


def format_stderr_warnings(steps: list[dict[str, Any]]) -> list[str]:
    """Format shell-stderr warning block for nodes that exited 0 with non-empty stderr.

    Single source of truth used by both:
    - CLI ``cli/workflow_output.py::_display_stderr_warnings`` (emits via ``click.echo`` in a loop)
    - MCP ``format_success_as_text`` below (extends the lines list)

    Mirrors the CLI/MCP parity pattern established by ``format_only_indicator`` and
    ``_append_outputs``. Without this helper, MCP text output would silently omit
    shell-stderr warnings for workflows where a shell node wrote to stderr but
    exited 0 — agents calling the MCP ``workflow_execute`` tool would get a
    misleading ``✓ Workflow completed`` summary with no visibility into the
    hidden shell pipeline failures.

    Args:
        steps: List of execution step dicts (may contain ``has_stderr`` and ``stderr`` fields)

    Returns:
        Lines to append to output. Empty list when no step has stderr warnings.
        First line is a blank (to separate from preceding content); second is the
        ``⚠️  Shell stderr (exit code 0):`` header; remaining lines are per-node
        bullets with stderr previews truncated to 300 chars and multiline stderr
        indented for readability.
    """
    stderr_warnings = [
        (step.get("node_id", "unknown"), step.get("stderr", ""))
        for step in steps
        if step.get("has_stderr") and step.get("stderr")
    ]

    if not stderr_warnings:
        return []

    lines = ["", "⚠️  Shell stderr (exit code 0):"]
    for node_id, stderr in stderr_warnings:
        # Truncate long stderr to 300 chars
        stderr_preview = stderr[:300]
        if len(stderr) > 300:
            stderr_preview += "..."
        # Indent multiline stderr for readability
        indented = stderr_preview.replace("\n", "\n     ")
        lines.append(f"  • {node_id}: {indented}")

    return lines


def _append_execution_steps(lines: list[str], execution: dict[str, Any]) -> None:
    """Append supplementary execution details: --only summary line + batch errors."""
    if not execution or "steps" not in execution:
        return

    steps = execution["steps"]
    only_node_val = execution.get("only_node")
    nodes_skipped = execution.get("nodes_skipped", 0)

    # Emit the --only mode confirmation whenever --only is active, even
    # when no downstream nodes were skipped (e.g., --only targeted the
    # last node). Without this, the rendered output is byte-identical to
    # a full run and agents doing iterative debugging cannot disambiguate.
    if only_node_val:
        lines.append(format_only_indicator(only_node_val, nodes_skipped))

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
