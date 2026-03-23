"""Generate execution report from trace files.

Reads a tree-structured trace JSON and produces a navigable directory
of markdown files — one file per node, with summaries at each level.
"""

import json
import re
from pathlib import Path
from typing import Any


def _safe_name(name: str) -> str:
    """Sanitize a name for use in file/directory paths."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    return re.sub(r"-+", "-", safe).strip("-") or "unnamed"


def _compute_event_cost(event: dict[str, Any]) -> float | None:
    """Recursively compute total cost for an event (including children).

    Returns None if no cost data exists anywhere in the tree.
    Returns 0.0 if cost data exists but all costs are zero.
    """
    total = 0.0
    found_any = False

    # Direct LLM cost on this event
    llm_call = event.get("llm_call")
    if isinstance(llm_call, dict) and "cost_usd" in llm_call:
        total += llm_call["cost_usd"] or 0.0
        found_any = True

    # Recurse into batch items
    # Invariant (D9): batch items have llm_call XOR events, never both.
    # If both were present, this would double-count. See workflow_trace.py docstring.
    for item in event.get("batch_items", []):
        # Leaf item with direct LLM call
        item_llm = item.get("llm_call")
        if isinstance(item_llm, dict) and "cost_usd" in item_llm:
            total += item_llm["cost_usd"] or 0.0
            found_any = True
        # Sub-workflow item with nested events
        for child_event in item.get("events", []):
            child_cost = _compute_event_cost(child_event)
            if child_cost is not None:
                total += child_cost
                found_any = True

    # Recurse into sub-workflow events
    for child_event in event.get("sub_workflow_events", []):
        child_cost = _compute_event_cost(child_event)
        if child_cost is not None:
            total += child_cost
            found_any = True

    return total if found_any else None


def _format_cost(cost: float | None) -> str:
    """Format cost for display in tables and metadata."""
    if cost is None:
        return "\u2014"
    return f"${cost:.4f}"


def _collect_errors(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect all failed events from the event tree (non-recursive — top level only).

    Only collects top-level failures. If a sub-workflow fails, the parent container
    event has success=false — we show that, not the internal failure.
    """
    return [e for e in events if not e.get("success")]


def _suggest_template_fixes(
    event: dict[str, Any],
    all_events: list[dict[str, Any]],
) -> list[str]:
    """Generate fix suggestions for template resolution errors.

    Cross-references the failing node's error with upstream node outputs
    to suggest correct field paths.

    Args:
        event: The failed event
        all_events: All top-level events (to find upstream node outputs)

    Returns:
        List of suggestion strings, empty if not a template error
    """
    error = event.get("error", "")
    if "Unresolved variables" not in error and "Unresolved template" not in error:
        return []

    suggestions: list[str] = []

    # Extract template variable paths from error message
    var_pattern = re.compile(r"\$\{([^}]+)\}")
    variables = var_pattern.findall(error)

    # Also check template_resolutions for unresolved vars
    for _key, res in event.get("template_resolutions", {}).items():
        template = res.get("template", "")
        resolved = res.get("resolved", "")
        if template == resolved and "${" in str(template):
            variables.extend(var_pattern.findall(str(template)))

    # Build a lookup of node_id → node_output from all events
    output_lookup = _build_output_lookup(all_events)

    for var_path in set(variables):
        suggestion = _check_path_against_upstream(var_path, output_lookup)
        if suggestion:
            suggestions.append(suggestion)

    return suggestions


def _check_path_against_upstream(var_path: str, output_lookup: dict[str, Any]) -> str | None:
    """Check a template variable path against upstream outputs, return suggestion or None."""
    parts = var_path.split(".")
    if len(parts) < 2:
        return None

    upstream_output = output_lookup.get(parts[0])
    if upstream_output is None:
        return None

    # Traverse the path to find where it breaks
    current = upstream_output
    valid_depth = 0
    for part in parts[1:]:
        if isinstance(current, dict) and part in current:
            current = current[part]
            valid_depth += 1
        else:
            if isinstance(current, dict):
                available = [k for k in sorted(current.keys()) if not k.startswith("_")]
                if available:
                    valid_path = ".".join(parts[: 1 + valid_depth])
                    return f"`${{{var_path}}}`: key `{part}` not found at `{valid_path}`. Available keys: " + ", ".join(
                        f"`{k}`" for k in available[:10]
                    )
            break

    return None


def _build_output_lookup(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a dict mapping node_id → node_output from all events.

    Only indexes top-level events and one level of sub-workflow children.
    Deeper recursion wouldn't help: pflow templates are scoped, so a node
    can only reference outputs from its own workflow level. Sub-workflow
    internal nodes are invisible to parent-scope templates.
    """
    lookup: dict[str, Any] = {}
    for event in events:
        node_id = event.get("node_id")
        if node_id and event.get("node_output"):
            lookup[node_id] = event["node_output"]
        for child in event.get("sub_workflow_events", []):
            child_id = child.get("node_id")
            if child_id and child.get("node_output"):
                lookup[child_id] = child["node_output"]
    return lookup


def _detect_anomalies(events: list[dict[str, Any]]) -> list[str]:
    """Detect suspicious outputs from successful nodes.

    Returns human-readable warning strings. Only checks top-level events.
    These are navigation aids — flagging where to look, not diagnosing bugs.
    """
    warnings: list[str] = []
    for event in events:
        if not event.get("success"):
            continue  # Failed nodes already shown in Errors section
        warning = _check_event_anomaly(event)
        if warning:
            warnings.append(warning)
    return warnings


def _check_event_anomaly(event: dict[str, Any]) -> str | None:
    """Check a single successful event for suspicious output. Returns warning or None."""
    node_id = event.get("node_id", "?")
    node_type = event.get("node_type", "")
    output = event.get("node_output", {})

    if not output:
        return f"**{node_id}**: produced no output"

    # LLM nodes: check for empty response
    if "LLM" in node_type:
        response = output.get("response")
        if response is not None and (response == "" or response == {}):
            return f"**{node_id}**: LLM response is empty"

    # Shell nodes: check for empty stdout (when exit_code == 0)
    if "Shell" in node_type:
        stdout = output.get("stdout")
        exit_code = output.get("exit_code")
        if exit_code == 0 and stdout is not None and str(stdout).strip() == "":
            return f"**{node_id}**: stdout is empty (exit code 0)"

    # Code nodes: check for None result
    if "Python" in node_type or "Code" in node_type:
        result = output.get("result")
        if "result" in output and result is None:
            return f"**{node_id}**: result is None"

    # Any node: check for empty list in common output keys
    for key in ("response", "result", "stdout"):
        val = output.get(key)
        if isinstance(val, list) and len(val) == 0:
            return f"**{node_id}**: `{key}` is empty list (0 items)"

    return None


def generate_report(trace_path: str | Path, output_path: str | None = None) -> Path | None:
    """Generate report directory from a trace file.

    Args:
        trace_path: Path to the trace JSON file
        output_path: Output directory. "auto" or None = ~/.pflow/reports/{name}/

    Returns:
        Path to the report directory, or None on error
    """
    trace_path = Path(trace_path)
    if not trace_path.exists():
        return None

    with open(trace_path) as f:
        trace = json.load(f)

    # Require trace format 2.0.0+ (has node_output, template_resolutions)
    version = trace.get("format_version", "unknown")
    if not version.startswith("2."):
        import logging

        logging.getLogger(__name__).error(
            f"Trace format {version} not supported. Report generation requires format 2.0.0+. "
            f"Re-run the workflow to generate a new trace."
        )
        return None

    # Determine output directory
    if output_path is None or output_path == "auto":
        name = _safe_name(str(trace.get("workflow_name", "workflow")))
        report_dir = Path.home() / ".pflow" / "reports" / name
    else:
        report_dir = Path(output_path)

    report_dir.mkdir(parents=True, exist_ok=True)

    # Generate summary.md (pass source path without mutating loaded trace)
    summary = _build_summary(trace, source_path=str(trace_path))
    (report_dir / "summary.md").write_text(summary)

    # Generate per-node files
    events = trace.get("nodes", [])
    _write_node_files(events, report_dir, node_index=1)

    return report_dir


def _write_node_files(events: list[dict[str, Any]], parent_dir: Path, node_index: int) -> int:
    """Recursively write node files. Returns next available index."""
    idx = node_index
    for event in events:
        node_id = event.get("node_id", f"node-{idx}")
        safe_id = _safe_name(node_id)
        prefix = f"{idx:02d}"

        batch_items = event.get("batch_items")
        sub_events = event.get("sub_workflow_events")

        if batch_items or sub_events:
            # This is a container node — create a directory
            node_dir = parent_dir / f"{prefix}-{safe_id}"
            node_dir.mkdir(exist_ok=True)

            # Write container summary
            (node_dir / "summary.md").write_text(_build_node_summary(event))

            if batch_items:
                for item in batch_items:
                    item_idx = item.get("index", 0)
                    item_events = item.get("events", [])
                    if item_events:
                        # Sub-workflow batch item — create item directory
                        item_dir = node_dir / f"item-{item_idx}"
                        item_dir.mkdir(exist_ok=True)
                        (item_dir / "summary.md").write_text(_build_batch_item_summary(item))
                        _write_node_files(item_events, item_dir, node_index=1)
                    else:
                        # Simple batch item — single file
                        (node_dir / f"item-{item_idx}.md").write_text(_build_batch_item_file(item, event))

            if sub_events:
                _write_node_files(sub_events, node_dir, node_index=1)
        else:
            # Leaf node — single file
            (parent_dir / f"{prefix}-{safe_id}.md").write_text(_build_node_file(event))

        idx += 1
    return idx


def _build_summary(trace: dict[str, Any], source_path: str = "N/A") -> str:
    """Build top-level summary.md content."""
    lines = [f"# Execution Report: {trace.get('workflow_name', 'workflow')}", ""]
    lines.append(f"- Status: {trace.get('final_status', 'unknown')}")
    lines.append(f"- Duration: {trace.get('duration_ms', 0) / 1000:.1f}s")
    lines.append(f"- Nodes: {trace.get('nodes_executed', 0)}")

    llm = trace.get("llm_summary")
    if llm and llm.get("total_calls", 0) > 0:
        lines.append(f"- LLM calls: {llm.get('total_calls', 0)}")
        tokens = llm.get("total_tokens", 0)
        if tokens:
            lines.append(f"- Tokens: {tokens:,}")
        cost = llm.get("total_cost_usd", 0)
        if cost is not None and cost > 0:
            lines.append(f"- Total cost: ${cost:.4f}")
        models = llm.get("models_used", [])
        if models:
            lines.append(f"- Models: {', '.join(models)}")

    lines.append(f"- Generated: {trace.get('end_time', '')}")
    lines.append("")

    # Pipeline table
    lines.append("## Pipeline")
    lines.append("")
    lines.append("| # | Node | Type | Time | Cost | Status |")
    lines.append("|---|------|------|------|------|--------|")
    all_events = trace.get("nodes", [])
    for i, event in enumerate(all_events, 1):
        node_id = event.get("node_id", "?")
        node_type = event.get("node_type", "?")
        duration = event.get("duration_ms", 0)
        cost = _format_cost(_compute_event_cost(event))
        status = "ok" if event.get("success") else "**FAILED**"
        lines.append(f"| {i} | {node_id} | {node_type} | {duration:.0f}ms | {cost} | {status} |")

    lines.append("")

    # Error and warning sections
    _append_error_section(all_events, lines)
    _append_warning_section(all_events, lines)

    lines.append(f"*Full trace: {source_path}*")
    return "\n".join(lines)


def _append_error_section(events: list[dict[str, Any]], lines: list[str]) -> None:
    """Append ## Errors section if there are failed events."""
    errors = _collect_errors(events)
    if not errors:
        return
    lines.append("## Errors")
    lines.append("")
    for event in errors:
        node_id = event.get("node_id", "?")
        node_type = event.get("node_type", "?")
        error_msg = event.get("error", "Unknown error")
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        lines.append(f"- **{node_id}** ({node_type}): {error_msg}")
        for s in _suggest_template_fixes(event, events):
            lines.append(f"  - Suggestion: {s}")
    lines.append("")


def _append_warning_section(events: list[dict[str, Any]], lines: list[str]) -> None:
    """Append ## Warnings section if there are anomalies."""
    anomalies = _detect_anomalies(events)
    if not anomalies:
        return
    lines.append("## Warnings")
    lines.append("")
    for warning in anomalies:
        lines.append(f"- {warning}")
    lines.append("")


def _format_node_metadata(event: dict[str, Any], lines: list[str]) -> None:
    """Append metadata lines for a node event."""
    lines.append(f"- Type: {event.get('node_type', 'unknown')}")
    lines.append(f"- Time: {event.get('duration_ms', 0):.0f}ms")
    status = "success" if event.get("success") else "failed"
    if event.get("cached"):
        status += " [cached]"
    lines.append(f"- Status: {status}")

    llm_call = event.get("llm_call")
    if llm_call:
        lines.append(f"- Model: {llm_call.get('model', '?')}")
        tokens_in = llm_call.get("input_tokens", llm_call.get("prompt_tokens", 0))
        tokens_out = llm_call.get("output_tokens", llm_call.get("completion_tokens", 0))
        lines.append(f"- Tokens: {tokens_in:,} in / {tokens_out:,} out")
        cost = llm_call.get("cost_usd")
        if cost is not None:
            lines.append(f"- Cost: ${cost:.4f}")

    error = event.get("error")
    if error:
        lines.append(f"- Error: {error}")


def _format_pipeline_table(events: list[dict[str, Any]], lines: list[str]) -> None:
    """Append a pipeline summary table for a list of node events."""
    if not events:
        return
    lines.append("## Pipeline")
    lines.append("")
    lines.append("| # | Node | Type | Time | Cost | Status |")
    lines.append("|---|------|------|------|------|--------|")
    for i, event in enumerate(events, 1):
        node_id = event.get("node_id", "?")
        node_type = event.get("node_type", "?")
        duration = event.get("duration_ms", 0)
        cost = _format_cost(_compute_event_cost(event))
        status = "ok" if event.get("success") else "**FAILED**"
        lines.append(f"| {i} | {node_id} | {node_type} | {duration:.0f}ms | {cost} | {status} |")
    lines.append("")


def _format_node_output(event: dict[str, Any], lines: list[str]) -> None:
    """Append response/output sections for a node event."""
    if event.get("llm_response"):
        lines.append("## Response")
        lines.append("")
        lines.append(event["llm_response"])
        lines.append("")
    elif event.get("node_output"):
        output = event["node_output"]
        for key, heading in [("stdout", "## stdout"), ("stderr", "## stderr")]:
            if key in output and str(output[key]).strip():
                lines.extend([heading, "", f"```\n{output[key]}\n```", ""])
        if "result" in output:
            lines.append("## Result")
            lines.append("")
            result = output["result"]
            if isinstance(result, (dict, list)):
                lines.append(f"```json\n{json.dumps(result, indent=2, default=str)}\n```")
            else:
                lines.append(str(result))
            lines.append("")
        # Catch-all: render remaining keys not already shown
        shown_keys = {
            "stdout",
            "stderr",
            "result",
            "item",
            "exit_code",
            "command",
            "stdout_is_binary",
            "stderr_is_binary",
        }
        remaining = {k: v for k, v in output.items() if k not in shown_keys}
        if remaining:
            lines.append("## Output")
            lines.append("")
            lines.append(f"```json\n{json.dumps(remaining, indent=2, default=str)}\n```")
            lines.append("")


def _build_node_file(event: dict[str, Any]) -> str:
    """Build a single node's markdown file."""
    lines = [f"# {event.get('node_id', 'unknown')}", ""]

    _format_node_metadata(event, lines)
    lines.append("")

    # Template resolutions — show rendered prompt/command
    resolutions = event.get("template_resolutions", {})
    if "prompt" in resolutions:
        lines.extend(["## Prompt", "", str(resolutions["prompt"].get("resolved", "")), ""])
    elif event.get("llm_prompt"):
        lines.extend(["## Prompt", "", event["llm_prompt"], ""])

    if "command" in resolutions:
        lines.extend(["## Command", "", f"```bash\n{resolutions['command'].get('resolved', '')}\n```", ""])

    _format_node_output(event, lines)

    return "\n".join(lines)


def _append_batch_item_warnings(batch_items: list[dict[str, Any]], lines: list[str]) -> None:
    """Append ## Warnings section for batch items with suspicious output."""
    item_warnings: list[str] = []
    for item in batch_items:
        if not item.get("success"):
            continue
        idx = item.get("index", "?")
        output = item.get("node_output", {})
        if not output:
            item_warnings.append(f"**Item {idx}**: produced no output")
        else:
            for key in ("response", "result", "stdout"):
                val = output.get(key)
                if val is not None and (val == "" or val == []):
                    item_warnings.append(f"**Item {idx}**: `{key}` is empty")
                    break
    if item_warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in item_warnings:
            lines.append(f"- {w}")
        lines.append("")


def _build_node_summary(event: dict[str, Any]) -> str:
    """Build summary for a container node (batch or sub-workflow)."""
    node_id = event.get("node_id", "unknown")
    lines = [f"# {node_id}", ""]
    lines.append(f"- Type: {event.get('node_type', '?')}")
    lines.append(f"- Time: {event.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if event.get('success') else 'failed'}")
    container_cost = _compute_event_cost(event)
    if container_cost is not None:
        lines.append(f"- Cost: ${container_cost:.4f}")

    batch_items = event.get("batch_items", [])
    if batch_items:
        succeeded = sum(1 for i in batch_items if i.get("success"))
        lines.append(f"- Items: {len(batch_items)} ({succeeded}/{len(batch_items)} succeeded)")
        lines.append("")
        lines.append("## Items")
        lines.append("")
        lines.append("| # | Time | Cost | Status |")
        lines.append("|---|------|------|--------|")
        for item in batch_items:
            idx = item.get("index", "?")
            dur = item.get("duration_ms", 0)
            cost = _format_cost(_compute_event_cost(item))
            status = "ok" if item.get("success") else "**FAILED**"
            lines.append(f"| {idx} | {dur:.0f}ms | {cost} | {status} |")
        lines.append("")

        _append_batch_item_warnings(batch_items, lines)

    sub_events = event.get("sub_workflow_events", [])
    _format_pipeline_table(sub_events, lines)

    return "\n".join(lines)


def _build_batch_item_file(item: dict[str, Any], parent_event: dict[str, Any]) -> str:
    """Build file for a simple batch item (no sub-workflow)."""
    idx = item.get("index", "?")
    lines = [f"# {parent_event.get('node_id', '?')} — Item {idx}", ""]
    lines.append(f"- Time: {item.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if item.get('success') else 'failed'}")

    llm_call = item.get("llm_call")
    if llm_call:
        lines.append(f"- Model: {llm_call.get('model', '?')}")
        cost = llm_call.get("cost_usd")
        if cost is not None:
            lines.append(f"- Cost: ${cost:.4f}")

    error = item.get("error")
    if error:
        lines.append(f"- Error: {error}")
    lines.append("")

    # Show rendered prompt/command (same logic as _build_node_file)
    resolutions = item.get("template_resolutions", {})
    if "prompt" in resolutions:
        lines.extend(["## Prompt", "", str(resolutions["prompt"].get("resolved", "")), ""])
    elif item.get("llm_prompt"):
        lines.extend(["## Prompt", "", item["llm_prompt"], ""])

    if "command" in resolutions:
        lines.extend(["## Command", "", f"```bash\n{resolutions['command'].get('resolved', '')}\n```", ""])

    _format_node_output(item, lines)

    return "\n".join(lines)


def _build_batch_item_summary(item: dict[str, Any]) -> str:
    """Build summary for a batch item that contains sub-workflow events."""
    idx = item.get("index", "?")
    lines = [f"# Item {idx}", ""]
    lines.append(f"- Time: {item.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if item.get('success') else 'failed'}")
    lines.append("")

    child_events = item.get("events", [])
    _format_pipeline_table(child_events, lines)

    return "\n".join(lines)
