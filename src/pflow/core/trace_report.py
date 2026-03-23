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
    if llm:
        lines.append(f"- LLM calls: {llm.get('total_calls', 0)}")
        lines.append(f"- Tokens: {llm.get('total_tokens', 0):,}")
        lines.append(f"- Models: {', '.join(llm.get('models_used', []))}")

    lines.append(f"- Generated: {trace.get('end_time', '')}")
    lines.append("")

    # Pipeline table
    lines.append("## Pipeline")
    lines.append("")
    lines.append("| # | Node | Type | Time | Status |")
    lines.append("|---|------|------|------|--------|")
    for i, event in enumerate(trace.get("nodes", []), 1):
        node_id = event.get("node_id", "?")
        node_type = event.get("node_type", "?")
        duration = event.get("duration_ms", 0)
        status = "ok" if event.get("success") else "FAILED"
        lines.append(f"| {i} | {node_id} | {node_type} | {duration:.0f}ms | {status} |")

    lines.append("")
    lines.append(f"*Full trace: {source_path}*")
    return "\n".join(lines)


def _format_node_metadata(event: dict[str, Any], lines: list[str]) -> None:
    """Append metadata lines for a node event."""
    lines.append(f"- Type: {event.get('node_type', 'unknown')}")
    lines.append(f"- Time: {event.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if event.get('success') else 'failed'}")

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
            if key in output:
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


def _build_node_summary(event: dict[str, Any]) -> str:
    """Build summary for a container node (batch or sub-workflow)."""
    node_id = event.get("node_id", "unknown")
    lines = [f"# {node_id}", ""]
    lines.append(f"- Type: {event.get('node_type', '?')}")
    lines.append(f"- Time: {event.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if event.get('success') else 'failed'}")

    batch_items = event.get("batch_items", [])
    if batch_items:
        succeeded = sum(1 for i in batch_items if i.get("success"))
        lines.append(f"- Items: {len(batch_items)} ({succeeded}/{len(batch_items)} succeeded)")
        lines.append("")
        lines.append("## Items")
        lines.append("")
        lines.append("| # | Time | Status |")
        lines.append("|---|------|--------|")
        for item in batch_items:
            idx = item.get("index", "?")
            dur = item.get("duration_ms", 0)
            status = "ok" if item.get("success") else "FAILED"
            lines.append(f"| {idx} | {dur:.0f}ms | {status} |")

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

    # Show rendered prompt if available
    resolutions = item.get("template_resolutions", {})
    if "prompt" in resolutions:
        lines.append("## Prompt")
        lines.append("")
        lines.append(str(resolutions["prompt"].get("resolved", "")))
        lines.append("")
    elif item.get("llm_prompt"):
        lines.append("## Prompt")
        lines.append("")
        lines.append(item["llm_prompt"])
        lines.append("")

    if item.get("llm_response"):
        lines.append("## Response")
        lines.append("")
        lines.append(item["llm_response"])
        lines.append("")

    node_output = item.get("node_output", {})
    if node_output and not item.get("llm_response"):
        lines.append("## Output")
        lines.append("")
        lines.append(f"```json\n{json.dumps(node_output, indent=2, default=str)}\n```")
        lines.append("")

    return "\n".join(lines)


def _build_batch_item_summary(item: dict[str, Any]) -> str:
    """Build summary for a batch item that contains sub-workflow events."""
    idx = item.get("index", "?")
    lines = [f"# Item {idx}", ""]
    lines.append(f"- Time: {item.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if item.get('success') else 'failed'}")
    lines.append("")
    return "\n".join(lines)
