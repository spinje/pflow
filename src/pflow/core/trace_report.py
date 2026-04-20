"""Generate execution report from trace files.

Reads a tree-structured trace JSON and produces a navigable directory
of markdown files — one file per node, with summaries at each level.
"""

import json
import logging
import re
import statistics
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Priority keys for extracting a label from a batch item's input data
_LABEL_PRIORITY_KEYS = ("name", "title", "label")


def _safe_name(name: str) -> str:
    """Sanitize a name for use in file/directory paths."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    return re.sub(r"-+", "-", safe).strip("-") or "unnamed"


def _slugify_label(label: str, max_len: int = 40) -> str:
    """Convert a label to a filename-safe slug.

    Lowercase, spaces/special chars to hyphens, collapse consecutive hyphens,
    strip leading/trailing hyphens, truncate to max_len.
    """
    slug = label.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if len(slug) > max_len:
        # Truncate at max_len, but don't cut mid-word if there's a hyphen nearby
        truncated = slug[:max_len]
        last_hyphen = truncated.rfind("-", max_len - 10, max_len)
        if last_hyphen > 0:
            truncated = truncated[:last_hyphen]
        slug = truncated.rstrip("-")
    return slug or "unnamed"


def _extract_item_label(item: dict[str, Any]) -> str | None:
    """Extract a human-readable label from a batch item's input data.

    Priority order:
    1. If item["item"] is a string, use it directly
    2. If item["item"] is a dict, look for name/title/label keys
    3. Fall back to first short string value (< 80 chars, not a URL/path)
    4. Return None if nothing works
    """
    data = item.get("item")
    if data is None:
        return None

    if isinstance(data, str):
        return data if data.strip() else None

    if isinstance(data, dict):
        # Check priority keys first
        for key in _LABEL_PRIORITY_KEYS:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        # Fall back to first short string value that isn't a URL or path
        for val in data.values():
            if isinstance(val, str) and val.strip() and len(val) < 80 and "://" not in val and not val.startswith("/"):
                return val.strip()

    return None


def _item_label_or_index(item: dict[str, Any]) -> str:
    """Return the label for a batch item, or 'Item {index}' as fallback."""
    label = _extract_item_label(item)
    if label:
        return _slugify_label(label)
    return f"Item {item.get('index', '?')}"


def _item_filename(item: dict[str, Any], suffix: str = ".md") -> str:
    """Build the filename (or directory name) for a batch item.

    Format: item-{index}-{slug} when label exists, item-{index} otherwise.
    """
    idx = item.get("index", 0)
    label = _extract_item_label(item)
    if label:
        return f"item-{idx}-{_slugify_label(label)}{suffix}"
    return f"item-{idx}{suffix}"


def _find_notable_items(
    batch_items: list[dict[str, Any]],
    parent_event: dict[str, Any],
) -> list[dict[str, Any]]:
    """Identify batch items worth showing in the summary table.

    Notable items: failures, anomaly warnings, duration outliers, or cost outliers.
    Uses IQR (interquartile range) for outlier detection — items above
    Q3 + 1.5*IQR are flagged (standard box plot whiskers), with 4x-median minimum.
    """
    node_type = parent_event.get("node_type", "")

    # Compute IQR-based outlier thresholds for duration and cost
    durations = [item.get("duration_ms", 0) for item in batch_items]
    duration_outlier = _compute_outlier_threshold(durations)
    median_duration = statistics.median(durations) if durations else 0

    costs = [_compute_event_cost(item) for item in batch_items]
    cost_values = [c for c in costs if c is not None]
    cost_outlier = _compute_outlier_threshold(cost_values)
    median_cost = statistics.median(cost_values) if cost_values else 0

    notable: list[dict[str, Any]] = []
    for item in batch_items:
        # Failed items are always notable
        if not item.get("success"):
            notable.append(item)
            continue

        # Anomaly warnings (aligned with _detect_batch_item_anomalies)
        output = item.get("node_output", {})
        if not output or _check_batch_item_anomaly(output, node_type):
            notable.append(item)
            continue

        # Duration outlier: must exceed both IQR threshold AND 4x median
        dur = item.get("duration_ms", 0)
        if duration_outlier is not None and dur > duration_outlier and dur > 4 * median_duration:
            notable.append(item)
            continue

        # Cost outlier: must exceed both IQR threshold AND 4x median cost
        item_cost = _compute_event_cost(item)
        if (
            cost_outlier is not None
            and item_cost is not None
            and item_cost > cost_outlier
            and item_cost > 4 * median_cost
        ):
            notable.append(item)
            continue

    return notable


def _compute_outlier_threshold(values: list[float]) -> float | None:
    """Compute IQR-based upper outlier threshold.

    Returns Q3 + 1.5*IQR, or None if fewer than 4 values (IQR meaningless).
    """
    if len(values) < 4:
        return None
    sorted_vals = sorted(values)
    q1 = statistics.median(sorted_vals[: len(sorted_vals) // 2])
    q3 = statistics.median(sorted_vals[(len(sorted_vals) + 1) // 2 :])
    iqr = q3 - q1
    return q3 + 1.5 * iqr


def _compute_event_cost(event: dict[str, Any]) -> float | None:
    """Recursively compute total cost for an event (including children).

    Returns None if no cost data exists anywhere in the tree.
    Returns 0.0 if cost data exists but all costs are zero.

    NOTE: This traverses the same tree structure as _collect_llm_summary() in
    workflow_trace.py. If the trace event shape changes, both must be updated.
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

    # Recurse into "events" — used by sub-workflow batch items
    # (batch items store child events under "events", not "sub_workflow_events")
    for child_event in event.get("events", []):
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


def _collect_errors(
    events: list[dict[str, Any]],
    failed_node_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the latest failed event per failed node (non-recursive — top level only).

    When the trace carries ``failed_node_ids`` (added as part of the GH #240 fix),
    use it as the authoritative failed-node set. Otherwise derive per-node final
    state from events directly (for backward compat with traces generated before
    this fix).

    Returns one event per failed node — under loop recovery, only the last
    (recovered) event would be returned, but since the node's final state was
    success, it wouldn't be in ``failed_node_ids`` at all. If a node fails on
    both visits, only the latest (still-failed) event is returned.

    Only collects top-level failures. If a sub-workflow fails, the parent
    container event has success=false — we show that, not the internal failure.
    """
    if failed_node_ids is not None:
        failed_set = set(failed_node_ids)
        latest: dict[str, dict[str, Any]] = {}
        for e in events:
            nid = e.get("node_id")
            if nid in failed_set:
                latest[nid] = e
        return list(latest.values())

    # Fallback: derive per-node final state from events directly. Matches the
    # aggregation rule in workflow_trace._final_events_by_node so new-format
    # traces written without failed_node_ids (e.g. by hand in tests) still
    # produce the correct Errors section.
    fallback_latest: dict[str, dict[str, Any]] = {}
    for e in events:
        nid = e.get("node_id")
        if nid:
            fallback_latest[nid] = e
    return [e for e in fallback_latest.values() if not e.get("success")]


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
    from pflow.runtime.template_resolver import TemplateResolver

    variables = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall(error)

    # Also check template_resolutions for unresolved vars
    for _key, res in event.get("template_resolutions", {}).items():
        template = res.get("template", "")
        resolved = res.get("resolved", "")
        if template == resolved and "${" in str(template):
            variables.extend(TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall(str(template)))

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


def generate_report(
    trace_path: str | Path,
    output_path: str | None = None,
    only_node: str | None = None,
    total_nodes: int | None = None,
) -> Path | None:
    """Generate report directory from a trace file.

    Args:
        trace_path: Path to the trace JSON file
        output_path: Output directory. "auto" or None = ~/.pflow/reports/{name}/
        only_node: If set, the --only target node (adds context to summary)
        total_nodes: Total workflow nodes (used with only_node to show skipped count)

    Returns:
        Path to the report directory, or None on error
    """
    trace_path = Path(trace_path)
    if not trace_path.exists():
        return None

    try:
        with open(trace_path) as f:
            trace = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read trace file %s", trace_path)
        return None

    # Require trace format 2.0.0+ (has node_output, template_resolutions)
    version = trace.get("format_version", "unknown")
    if not version.startswith("2."):
        logger.error(
            "Trace format %s not supported. Report generation requires format 2.0.0+. "
            "Re-run the workflow to generate a new trace.",
            version,
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
    summary = _build_summary(trace, source_path=str(trace_path), only_node=only_node, total_nodes=total_nodes)
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
                    item_events = item.get("events", [])
                    if item_events:
                        # Sub-workflow batch item — create item directory
                        item_dir = node_dir / _item_filename(item, suffix="")
                        item_dir.mkdir(exist_ok=True)
                        (item_dir / "summary.md").write_text(_build_batch_item_summary(item))
                        _write_node_files(item_events, item_dir, node_index=1)
                    else:
                        # Simple batch item — single file
                        (node_dir / _item_filename(item)).write_text(_build_batch_item_file(item, event))

            if sub_events:
                _write_node_files(sub_events, node_dir, node_index=1)
        else:
            # Leaf node — single file
            (parent_dir / f"{prefix}-{safe_id}.md").write_text(_build_node_file(event))

        idx += 1
    return idx


def _build_summary(
    trace: dict[str, Any],
    source_path: str = "N/A",
    only_node: str | None = None,
    total_nodes: int | None = None,
) -> str:
    """Build top-level summary.md content."""
    lines = [f"# Execution Report: {trace.get('workflow_name', 'workflow')}", ""]
    lines.append(f"- Status: {trace.get('final_status', 'unknown')}")
    lines.append(f"- Duration: {trace.get('duration_ms', 0) / 1000:.1f}s")
    executed = trace.get("nodes_executed", 0)
    if only_node and total_nodes:
        skipped = total_nodes - executed
        lines.append(f"- Nodes: {executed}/{total_nodes} (--only '{only_node}', {skipped} skipped)")
    else:
        lines.append(f"- Nodes: {executed}")

    llm = trace.get("llm_summary")
    if llm and llm.get("total_calls", 0) > 0:
        lines.append(f"- LLM calls: {llm.get('total_calls', 0)}")
        tokens_in = llm.get("total_input_tokens", 0)
        tokens_out = llm.get("total_output_tokens", 0)
        if tokens_in or tokens_out:
            lines.append(f"- Tokens: {tokens_in:,} in / {tokens_out:,} out")
        elif llm.get("total_tokens", 0):
            # Fallback for traces generated before input/output breakdown was added
            lines.append(f"- Tokens: {llm['total_tokens']:,}")
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
        status = _format_event_status(event)
        lines.append(f"| {i} | {node_id} | {node_type} | {duration:.0f}ms | {cost} | {status} |")

    lines.append("")

    # Error and warning sections
    _append_error_section(trace, lines)
    _append_runtime_warnings(trace.get("warnings", []), lines)
    _append_warning_section(all_events, lines)

    lines.append(f"*Full trace: {source_path}*")
    return "\n".join(lines)


def _append_error_section(trace: dict[str, Any], lines: list[str]) -> None:
    """Append ## Errors section if there are failed nodes.

    Consumes ``trace["failed_node_ids"]`` when present (authoritative per-node
    failure list) and falls back to per-node derivation from ``trace["nodes"]``
    when absent (backward compat). Under loop recovery a node that failed on
    visit 1 and succeeded on visit 2 is NOT in ``failed_node_ids`` and does not
    appear here — see GH #240.
    """
    events = trace.get("nodes", [])
    errors = _collect_errors(events, failed_node_ids=trace.get("failed_node_ids"))
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
        # events (not just errors) is needed for upstream-output lookup
        for s in _suggest_template_fixes(event, events):
            lines.append(f"  - Suggestion: {s}")
    lines.append("")


def _append_runtime_warnings(warnings: list[dict[str, Any]], lines: list[str]) -> None:
    """Append runtime warnings from execution (API warnings, batch degradation, etc.).

    These come from the trace file's top-level 'warnings' field, which mirrors
    the __warnings__ shared store key captured during execution.
    """
    if not warnings:
        return
    lines.append("## Runtime Warnings")
    lines.append("")
    for w in warnings:
        node_id = w.get("node_id", "?")
        message = w.get("message", "Unknown warning")
        lines.append(f"- **{node_id}**: {message}")
    lines.append("")


def _append_warning_section(events: list[dict[str, Any]], lines: list[str]) -> None:
    """Append ## Warnings section if there are anomalies.

    Checks both top-level events and batch items within container events,
    so the top-level summary surfaces silent failures from batch items.
    """
    anomalies = _detect_anomalies(events)

    # Also surface batch item anomalies at the top level
    for event in events:
        if not event.get("success"):
            continue
        batch_items = event.get("batch_items", [])
        if not batch_items:
            continue
        node_id = event.get("node_id", "?")
        item_warnings = _detect_batch_item_anomalies(batch_items, event)
        for w in item_warnings:
            anomalies.append(f"**{node_id}**: {w}")

    if not anomalies:
        return
    lines.append("## Warnings")
    lines.append("")
    for warning in anomalies:
        lines.append(f"- {warning}")
    lines.append("")


def _format_event_status(event: dict[str, Any]) -> str:
    """Format the status column for a trace event.

    For batch/sub-workflow events, includes item counts (e.g., 'ok (4/4)').
    Cached nodes show '[cached]' suffix.
    """
    base = "ok" if event.get("success") else "**FAILED**"
    if event.get("cached"):
        base += " [cached]"
    batch_items = event.get("batch_items")
    if batch_items:
        total = len(batch_items)
        succeeded = sum(1 for i in batch_items if i.get("success"))
        return f"{base} ({succeeded}/{total})"
    return base


def _format_llm_params(node_params: dict[str, Any], lines: list[str]) -> None:
    """Append user-configured LLM parameters when explicitly set.

    Only shows params the user wrote in the workflow file — not defaults.
    Params like prompt/command/code are shown elsewhere in the report.
    """
    # Params that have dedicated rendering elsewhere in the report
    _skip = {"prompt", "command", "code", "inputs", "model", "batch", "timeout"}

    for key in ("temperature", "reasoning_effort", "reasoning_max_tokens", "max_tokens"):
        if key in node_params and key not in _skip:
            lines.append(f"- {key}: {node_params[key]}")

    if "system" in node_params:
        system = str(node_params["system"])
        if len(system) > 80:
            system = system[:77] + "..."
        lines.append(f"- system: {system}")

    if "output_schema" in node_params:
        lines.append("- output: structured (schema)")


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

    # Show user-configured LLM parameters (only when explicitly set in workflow)
    node_params = event.get("node_params", {})
    _format_llm_params(node_params, lines)

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
        status = _format_event_status(event)
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
        # Render primary output: "result" for code nodes, "response" for HTTP nodes
        for key in ("result", "response"):
            if key in output:
                val = output[key]
                heading = "## Result" if key == "result" else "## Response"
                lines.append(heading)
                lines.append("")
                if isinstance(val, (dict, list)):
                    lines.append(f"```json\n{json.dumps(val, indent=2, default=str)}\n```")
                elif val is not None and str(val).strip():
                    lines.append(str(val))
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
            "llm_usage",
            "response",
        }
        remaining = {
            k: v for k, v in output.items() if k not in shown_keys and not (isinstance(k, str) and k.startswith("_"))
        }
        if remaining:
            lines.append("## Output")
            lines.append("")
            lines.append(f"```json\n{json.dumps(remaining, indent=2, default=str)}\n```")
            lines.append("")


def _format_resolutions(event: dict[str, Any], lines: list[str]) -> None:
    """Render template resolutions and static params as markdown sections.

    Handles all node types: prompt (LLM), command (Shell), code+inputs (Python),
    and a catch-all for any other resolved parameters (HTTP headers, file paths, etc.).
    """
    resolutions = event.get("template_resolutions", {})
    shown: set[str] = set()

    if "prompt" in resolutions:
        lines.extend(["## Prompt", "", str(resolutions["prompt"].get("resolved", "")), ""])
        shown.add("prompt")
    elif event.get("llm_prompt"):
        lines.extend(["## Prompt", "", event["llm_prompt"], ""])

    if "command" in resolutions:
        lines.extend(["## Command", "", f"```bash\n{resolutions['command'].get('resolved', '')}\n```", ""])
        shown.add("command")

    # Code nodes: source code from node_params (static, not in template_resolutions)
    node_params = event.get("node_params", {})
    if "code" in node_params and not isinstance(node_params["code"], dict):
        lines.extend(["## Code", "", f"```python\n{node_params['code']}\n```", ""])

    # Code/other nodes: resolved input variables
    if "inputs" in resolutions:
        resolved_inputs = resolutions["inputs"].get("resolved", {})
        if resolved_inputs:
            lines.extend(["## Inputs", ""])
            if isinstance(resolved_inputs, dict):
                lines.append(f"```json\n{json.dumps(resolved_inputs, indent=2, default=str)}\n```")
            else:
                lines.append(f"```\n{resolved_inputs}\n```")
            lines.append("")
        shown.add("inputs")

    # Catch-all: any remaining template resolutions
    remaining = {k: v.get("resolved", v) for k, v in resolutions.items() if k not in shown}
    if remaining:
        lines.extend(["## Resolved Parameters", ""])
        lines.append(f"```json\n{json.dumps(remaining, indent=2, default=str)}\n```")
        lines.append("")


def _build_node_file(event: dict[str, Any]) -> str:
    """Build a single node's markdown file."""
    lines = [f"# {event.get('node_id', 'unknown')}", ""]

    _format_node_metadata(event, lines)
    lines.append("")

    _format_resolutions(event, lines)
    _format_node_output(event, lines)

    return "\n".join(lines)


def _check_batch_item_anomaly(output: dict[str, Any], node_type: str) -> str | None:
    """Check a single batch item's output for anomalies. Returns warning suffix or None."""
    # Type-aware checks — same logic as _check_event_anomaly
    if "LLM" in node_type:
        response = output.get("response")
        if response is not None and (response == "" or response == {}):
            return "LLM response is empty"

    if "Shell" in node_type:
        stdout = output.get("stdout")
        exit_code = output.get("exit_code")
        if exit_code == 0 and stdout is not None and str(stdout).strip() == "":
            return "stdout is empty (exit code 0)"

    if "Python" in node_type or "Code" in node_type:
        result = output.get("result")
        if "result" in output and result is None:
            return "result is None"

    # Generic check for empty list in common keys
    for key in ("response", "result", "stdout"):
        val = output.get(key)
        if isinstance(val, list) and len(val) == 0:
            return f"`{key}` is empty list (0 items)"

    return None


def _detect_batch_item_anomalies(batch_items: list[dict[str, Any]], parent_event: dict[str, Any]) -> list[str]:
    """Detect suspicious output from successful batch items.

    Uses the same type-aware logic as _check_event_anomaly for consistency.
    Returns warning strings like "Item 0: LLM response is empty".
    """
    node_type = parent_event.get("node_type", "")
    item_warnings: list[str] = []
    for item in batch_items:
        if not item.get("success"):
            continue
        idx = item.get("index", "?")
        output = item.get("node_output", {})
        if not output:
            item_warnings.append(f"Item {idx}: produced no output")
            continue
        warning = _check_batch_item_anomaly(output, node_type)
        if warning:
            item_warnings.append(f"Item {idx}: {warning}")
    return item_warnings


def _append_batch_item_warnings(
    batch_items: list[dict[str, Any]],
    lines: list[str],
    parent_event: dict[str, Any] | None = None,
) -> None:
    """Append ## Warnings section for batch items with suspicious output."""
    # Use parent_event for type-aware detection when available
    if parent_event is None:
        parent_event = {}
    item_warnings = _detect_batch_item_anomalies(batch_items, parent_event)
    if item_warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in item_warnings:
            lines.append(f"- {w}")
        lines.append("")


def _build_node_summary(event: dict[str, Any]) -> str:
    """Build summary for a container node (batch or sub-workflow).

    Uses compact format: only shows notable items (failures, warnings,
    duration outliers) in the table. When all items succeed without
    anomalies, just shows the count.
    """
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

        notable = _find_notable_items(batch_items, event)
        has_labels = any(_extract_item_label(item) for item in batch_items)

        if notable:
            _build_items_table(notable, has_labels, lines)
            hidden = len(batch_items) - len(notable)
            if hidden > 0:
                lines.append(f"*... and {hidden} more succeeded*")
                lines.append("")
        else:
            # All items normal — show aggregate stats for quick orientation
            _append_batch_stats(batch_items, lines)

        _append_batch_item_warnings(batch_items, lines, parent_event=event)

    sub_events = event.get("sub_workflow_events", [])
    _format_pipeline_table(sub_events, lines)

    return "\n".join(lines)


def _build_items_table(
    items: list[dict[str, Any]],
    has_labels: bool,
    lines: list[str],
) -> None:
    """Append a markdown table for a list of batch items."""
    lines.append("## Items")
    lines.append("")
    if has_labels:
        lines.append("| # | Label | Time | Cost | Status |")
        lines.append("|---|-------|------|------|--------|")
    else:
        lines.append("| # | Time | Cost | Status |")
        lines.append("|---|------|------|--------|")
    for item in items:
        idx = item.get("index", "?")
        dur = item.get("duration_ms", 0)
        cost = _format_cost(_compute_event_cost(item))
        status = _format_event_status(item)
        if has_labels:
            label = _item_label_or_index(item)
            lines.append(f"| {idx} | {label} | {dur:.0f}ms | {cost} | {status} |")
        else:
            lines.append(f"| {idx} | {dur:.0f}ms | {cost} | {status} |")
    lines.append("")


def _append_batch_stats(batch_items: list[dict[str, Any]], lines: list[str]) -> None:
    """Append aggregate stats (median time, total cost) for a clean batch.

    Shown when all items are normal (no table rendered). Gives a sense of
    per-item behavior without listing everything.
    """
    durations = [item.get("duration_ms", 0) for item in batch_items]
    if durations:
        median_dur = statistics.median(durations)
        if median_dur >= 1000:
            lines.append(f"- Median time: {median_dur / 1000:.1f}s")
        else:
            lines.append(f"- Median time: {median_dur:.0f}ms")

    costs = [_compute_event_cost(item) for item in batch_items]
    total_cost = sum(c for c in costs if c is not None)
    if total_cost > 0:
        lines.append(f"- Total cost: ${total_cost:.4f}")

    lines.append("")


def _build_batch_item_file(item: dict[str, Any], parent_event: dict[str, Any]) -> str:
    """Build file for a simple batch item (no sub-workflow)."""
    node_id = parent_event.get("node_id", "?")
    label = _item_label_or_index(item)
    lines = [f"# {node_id} — {label}", ""]
    lines.append(f"- Time: {item.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if item.get('success') else 'failed'}")

    llm_call = item.get("llm_call")
    if llm_call:
        lines.append(f"- Model: {llm_call.get('model', '?')}")
        tokens_in = llm_call.get("input_tokens", llm_call.get("prompt_tokens", 0))
        tokens_out = llm_call.get("output_tokens", llm_call.get("completion_tokens", 0))
        lines.append(f"- Tokens: {tokens_in:,} in / {tokens_out:,} out")
        cost = llm_call.get("cost_usd")
        if cost is not None:
            lines.append(f"- Cost: ${cost:.4f}")

    error = item.get("error")
    if error:
        lines.append(f"- Error: {error}")
    lines.append("")

    _format_resolutions(item, lines)
    _format_node_output(item, lines)

    return "\n".join(lines)


def _build_batch_item_summary(item: dict[str, Any]) -> str:
    """Build summary for a batch item that contains sub-workflow events."""
    label = _item_label_or_index(item)
    lines = [f"# {label}", ""]
    lines.append(f"- Time: {item.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if item.get('success') else 'failed'}")
    lines.append("")

    child_events = item.get("events", [])
    _format_pipeline_table(child_events, lines)

    return "\n".join(lines)
