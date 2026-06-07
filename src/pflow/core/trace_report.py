"""Generate execution report from trace files.

Reads a tree-structured trace JSON and produces a navigable directory
of markdown files — one file per node, with summaries at each level.
"""

import json
import logging
import re
import shutil
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pflow.core.duration_format import format_duration
from pflow.core.exceptions import ReportGenerationError
from pflow.core.node_type_display import node_type_tag
from pflow.core.trace_io import load_trace_file
from pflow.runtime.workflow_trace import final_events_by_node

logger = logging.getLogger(__name__)

# Priority keys for extracting a label from a batch item's input data
_LABEL_PRIORITY_KEYS = ("name", "title", "label")
_REPORT_MARKER = ".pflow-report.json"
_REPORT_MARKER_FORMAT = "pflow.report"
_REPORT_MARKER_VERSION = 1


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


def _is_warmup_item(item: dict[str, Any]) -> bool:
    """Return True if ``item`` is the synthetic batch-warmup item.

    Centralises the ``llm_call.is_warmup`` check so callers don't reimplement
    the ``(item.get("llm_call") or {}).get("is_warmup")`` pattern — which
    raises ``AttributeError`` if ``llm_call`` is a non-dict truthy value.
    """
    llm_call = item.get("llm_call")
    if not isinstance(llm_call, dict):
        return False
    return bool(llm_call.get("is_warmup"))


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


def validate_report_output_dir(report_dir: str | Path, *, allow_unmarked_existing: bool = False) -> None:
    """Raise if ``report_dir`` is not safe for report snapshot replacement."""
    path = Path(report_dir)
    if path.is_symlink():
        raise ReportGenerationError(
            f"Refusing to replace symlink report directory: {path}",
            report_path=str(path),
            suggestions=["Choose an empty directory or an existing pflow report directory."],
            reason="symlink_target",
        )
    if path.exists() and not path.is_dir():
        raise ReportGenerationError(
            f"Report output path exists and is not a directory: {path}",
            report_path=str(path),
            suggestions=["Choose an empty directory or an existing pflow report directory."],
            reason="not_directory",
        )
    try:
        is_empty = not path.exists() or not any(path.iterdir())
    except OSError as exc:
        raise ReportGenerationError(
            f"Failed to inspect report directory: {path}",
            report_path=str(path),
            suggestions=["Check directory permissions and try again."],
            reason="inspect_failed",
        ) from exc
    if is_empty:
        return

    marker_path = path / _REPORT_MARKER
    if marker_path.exists():
        if _is_valid_report_marker(marker_path):
            return
        raise ReportGenerationError(
            f"Refusing to replace report directory with invalid {_REPORT_MARKER}: {path}",
            report_path=str(path),
            suggestions=[
                "Choose an empty directory.",
                "Remove the invalid marker after verifying the directory is safe to replace.",
            ],
            reason="invalid_marker",
        )

    if allow_unmarked_existing:
        return

    raise ReportGenerationError(
        f"Refusing to replace non-empty report directory without {_REPORT_MARKER}: {path}",
        report_path=str(path),
        suggestions=["Choose an empty directory or an existing pflow report directory."],
        reason="unmarked_non_empty_directory",
    )


def _is_valid_report_marker(marker_path: Path) -> bool:
    try:
        data = json.loads(marker_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return data.get("format") == _REPORT_MARKER_FORMAT and data.get("format_version") == _REPORT_MARKER_VERSION


def _build_report_marker(trace: dict[str, Any], trace_path: Path) -> str:
    data = {
        "format": _REPORT_MARKER_FORMAT,
        "format_version": _REPORT_MARKER_VERSION,
        "workflow_name": str(trace.get("workflow_name", "workflow")),
        "trace_path": str(trace_path),
        "trace_format_version": str(trace.get("format_version", "unknown")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _render_report_snapshot(
    trace: dict[str, Any],
    trace_path: Path,
    report_dir: Path,
    *,
    only_node: str | None,
    total_nodes: int | None,
) -> None:
    summary = _build_summary(trace, source_path=str(trace_path), only_node=only_node, total_nodes=total_nodes)
    (report_dir / "summary.md").write_text(summary)
    (report_dir / _REPORT_MARKER).write_text(_build_report_marker(trace, trace_path))
    _write_node_files(trace.get("nodes", []), report_dir, node_index=1)


def _replace_report_dir(report_dir: Path, temp_dir: Path) -> None:
    backup_dir = report_dir.with_name(f".{report_dir.name}.old-{uuid4().hex}")
    try:
        if report_dir.exists():
            report_dir.rename(backup_dir)
        temp_dir.rename(report_dir)
    except OSError as exc:
        if backup_dir.exists() and not report_dir.exists():
            try:
                backup_dir.rename(report_dir)
            except OSError:
                logger.exception("Failed to restore previous report directory %s", report_dir)
        raise ReportGenerationError(
            f"Failed to replace report directory: {report_dir}",
            report_path=str(report_dir),
            suggestions=["Check directory permissions and try again."],
            reason="replace_failed",
        ) from exc
    if backup_dir.exists():
        try:
            shutil.rmtree(backup_dir)
        except OSError:
            logger.warning("Generated report %s, but failed to remove old backup %s", report_dir, backup_dir)


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

    costs = [_compute_batch_item_cost(item) for item in batch_items]
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
        item_cost = _compute_batch_item_cost(item)
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
    """Total cost for a real trace event (top-level or sub-workflow descendant).

    Returns None when no cost data exists anywhere in the subtree OR when any
    leaf has ``cost_usd: None`` (unpriced model — Ollama, custom endpoints).
    The unpriced case propagates as None so the report renders "—" rather
    than silently dropping the unpriced contribution.

    Returns 0.0 only when every leaf is explicitly priced at zero.

    For batch items (which lack ``node_id`` and store children under
    ``events`` rather than ``sub_workflow_events``), use
    :func:`_compute_batch_item_cost` instead.
    """
    from pflow.core.trace_tree import TraceTree

    tree = TraceTree(events=(event,), format_version="2.1")
    cost, source = tree.cost_for_event(event)
    if source in {"trace_partial", "unavailable"}:
        return None
    return cost


def _compute_batch_item_cost(item: dict[str, Any]) -> float | None:
    """Total cost for one batch item dict.

    Batch items have a different shape from real events (no top-level
    ``node_id``; sub-events under ``events`` not ``sub_workflow_events``).
    See :meth:`TraceTree.cost_for_batch_item`.
    """
    from pflow.core.trace_tree import TraceTree

    tree = TraceTree(events=(), format_version="2.1")
    cost, source = tree.cost_for_batch_item(item)
    if source in {"trace_partial", "unavailable"}:
        return None
    return cost


def _format_cost(cost: float | None) -> str:
    """Format cost for display in tables and metadata."""
    if cost is None:
        return "\u2014"
    return f"${cost:.4f}"


def _input_token_total(llm_call: dict[str, Any]) -> tuple[int, int]:
    """Return ``(input_tokens, cache_read_tokens)`` for one LLM call.

    ``input_tokens`` is pflow's cache-INCLUSIVE input total (see
    ``core/llm_usage.py``) \u2014 every producer (LLMNode and ClaudeCodeNode) emits it
    that way, so the report headlines it directly with no render-time cache
    arithmetic. ``cache_read`` is returned only for the cache-hit % display.
    """
    total_in = llm_call.get("input_tokens", llm_call.get("prompt_tokens", 0)) or 0
    cache_read = llm_call.get("cache_read_input_tokens", 0) or 0
    return total_in, cache_read


def _format_tokens(total_in: int, tokens_out: int, cache_read: int, *, with_cache_pct: bool) -> str:
    """``<total_in> in / <out> out`` with an optional ``\u00b7 N% of input cached``."""
    cell = f"{total_in:,} in / {tokens_out:,} out"
    if with_cache_pct and cache_read > 0 and total_in > 0:
        cell += f"  \u00b7  {round(cache_read / total_in * 100)}% of input cached"
    return cell


def _format_call_count_line(total_calls: int, agent_calls: int, total_turns: int) -> str:
    """Summary line for LLM/agent invocations.

    ``claude-code`` nodes are agentic \u2014 one invocation spans many internal
    turns \u2014 so they're labelled "Agent calls" with the turn total, distinct
    from single-shot "LLM calls". A mixed run surfaces both counts.
    """
    turns = f" ({total_turns:,} turns)" if total_turns else ""
    llm_calls = total_calls - agent_calls
    if agent_calls and llm_calls:
        return f"- Agent calls: {agent_calls}{turns} \u00b7 LLM calls: {llm_calls}"
    if agent_calls:
        return f"- Agent calls: {agent_calls}{turns}"
    return f"- LLM calls: {total_calls}"


def _format_llm_call_metadata(
    llm_call: dict[str, Any],
    lines: list[str],
    *,
    paid_cost: float | None,
    cached: bool,
) -> None:
    """Append LLM metadata with explicit current-run cost semantics.

    ``llm_call`` is retained provider-call metadata. On cached events it
    describes the source call that produced the reused result, not work paid
    for by this event. ``paid_cost`` must come from ``TraceTree`` via the
    report cost helpers so the display uses the same current-run contract as
    summary tables.
    """
    model_label = "Source model" if cached else "Model"
    tokens_label = "Source tokens" if cached else "Tokens"
    thinking_label = "Source thinking" if cached else "Thinking"
    turns_label = "Source turns" if cached else "Turns"
    session_label = "Source session" if cached else "Session"
    lines.append(f"- {model_label}: {llm_call.get('model', '?')}")
    total_in, cache_read = _input_token_total(llm_call)
    tokens_out = llm_call.get("output_tokens", llm_call.get("completion_tokens", 0)) or 0
    lines.append(f"- {tokens_label}: {_format_tokens(total_in, tokens_out, cache_read, with_cache_pct=True)}")
    thinking_tokens = llm_call.get("thinking_tokens")
    if isinstance(thinking_tokens, int) and thinking_tokens > 0:
        lines.append(f"- {thinking_label}: {thinking_tokens:,} tokens")
    # num_turns / session_id are claude-code-only; llm-node calls omit them and
    # the guards skip the lines. num_turns counts the main agent's loop only —
    # subagent turns are not included (a lens-deploying review node can show a
    # low count despite heavy subagent work).
    num_turns = llm_call.get("num_turns")
    if isinstance(num_turns, int) and num_turns > 0:
        lines.append(f"- {turns_label}: {num_turns:,}")
    session_id = llm_call.get("session_id")
    if isinstance(session_id, str) and session_id:
        lines.append(f"- {session_label}: {session_id}")
    lines.append(f"- Paid this run: {_format_cost(paid_cost)}")

    historical_cost = llm_call.get("cost_usd")
    if cached and historical_cost is not None and historical_cost != paid_cost:
        source_cost_label = "Historical source cost" if llm_call.get("cache_source") == "memo" else "Source call cost"
        lines.append(f"- {source_cost_label}: ${historical_cost:.4f}")


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
    latest = final_events_by_node(events)
    if failed_node_ids is not None:
        failed_set = set(failed_node_ids)
        return [e for nid, e in latest.items() if nid in failed_set]
    # Legacy fallback: derive from per-event success flag directly (pre-fix traces).
    return [e for e in latest.values() if not e.get("success")]


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
        trace = load_trace_file(trace_path)
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
    is_auto_output = output_path is None or output_path == "auto"
    if output_path is None or output_path == "auto":
        name = _safe_name(str(trace.get("workflow_name", "workflow")))
        report_dir = Path.home() / ".pflow" / "reports" / name
    else:
        report_dir = Path(output_path)

    validate_report_output_dir(report_dir, allow_unmarked_existing=is_auto_output)

    try:
        report_dir.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = report_dir.with_name(f".{report_dir.name}.tmp-{uuid4().hex}")
        temp_dir.mkdir()
        try:
            _render_report_snapshot(trace, trace_path, temp_dir, only_node=only_node, total_nodes=total_nodes)
            _replace_report_dir(report_dir, temp_dir)
        except Exception:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise
    except ReportGenerationError:
        raise
    except OSError as exc:
        raise ReportGenerationError(
            f"Failed to generate report directory: {report_dir}",
            report_path=str(report_dir),
            suggestions=["Check directory permissions and try again."],
            reason="write_failed",
        ) from exc

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


def _resolve_final_status(trace: dict[str, Any]) -> str:
    """Return the workflow-level final status, recomputing for legacy traces.

    New traces (post-GH #240 fix) carry ``failed_node_ids``; their
    ``final_status`` was written using the per-node-last-event rule and we
    trust it. Legacy traces (pre-fix) carry a ``final_status`` written with
    the old per-event rule — for a loop-recovery run that would incorrectly
    read "failed". ``_collect_errors`` already applies the corrected per-node
    rule to old traces via its fallback; recomputing status here keeps the
    Status line and Errors section in sync. Without this, a legacy trace
    renders "Status: failed" with zero entries under "## Errors".
    """
    if "failed_node_ids" in trace:
        return str(trace.get("final_status", "unknown"))

    # Legacy fallback: apply the canonical per-node-last-event rule and
    # override the JSON's stored value when the old rule was wrong. Preserve
    # non-"failed" legacy values ("success"/"degraded") because the fallback
    # can't reconstruct the degraded vs success distinction on its own.
    latest = final_events_by_node(trace.get("nodes", []))
    has_failure = any(not e.get("success", True) for e in latest.values())
    if has_failure:
        return "failed"
    legacy = str(trace.get("final_status", "success"))
    # Old code wrote "failed" for recovered loops; replace with "success"
    # since no per-node failures remain. Leave "degraded" and other values alone.
    return "success" if legacy == "failed" else legacy


def _halt_node_id(trace: dict[str, Any]) -> str | None:
    """Return the node_id of the event that ended a failed run, or None.

    The trace records no explicit halt ordering. We approximate by walking
    ``trace["nodes"]`` in recorded order and returning the last event with
    ``success is False`` — the chronological "this is where the run stopped"
    that matches reader intuition. Returns None when the run did not halt
    (``final_status`` other than ``"failed"``).
    """
    if trace.get("final_status") != "failed":
        return None
    for event in reversed(trace.get("nodes", []) or []):
        if event.get("success") is False:
            node_id = event.get("node_id")
            if isinstance(node_id, str):
                return node_id
    return None


def _build_summary(
    trace: dict[str, Any],
    source_path: str = "N/A",
    only_node: str | None = None,
    total_nodes: int | None = None,
) -> str:
    """Build top-level summary.md content."""
    lines = [f"# Execution Report: {trace.get('workflow_name', 'workflow')}", ""]
    lines.append(f"- Status: {_resolve_final_status(trace)}")
    halt = _halt_node_id(trace)
    if halt:
        lines.append(f"- Halted at: {halt}")
    lines.append(f"- Duration: {format_duration(trace.get('duration_ms', 0))}")
    executed = trace.get("nodes_executed", 0)
    if only_node and total_nodes:
        skipped = total_nodes - executed
        lines.append(f"- Nodes: {executed}/{total_nodes} (--only '{only_node}', {skipped} skipped)")
    else:
        lines.append(f"- Nodes: {executed}")

    llm = trace.get("llm_summary")
    if llm and llm.get("total_calls", 0) > 0:
        lines.append(
            _format_call_count_line(
                llm.get("total_calls", 0),
                llm.get("agent_calls", 0),
                llm.get("total_num_turns", 0),
            )
        )
        # total_input_tokens is the cache-INCLUSIVE input total (every producer
        # emits inclusive input_tokens; see core/llm_usage.py). cache_read is read
        # only for the cache-% suffix, NOT added back into the input total.
        cache_read = llm.get("total_cache_read_tokens", 0)
        total_in = llm.get("total_input_tokens", 0)
        tokens_out = llm.get("total_output_tokens", 0)
        if total_in or tokens_out:
            lines.append(f"- Tokens: {_format_tokens(total_in, tokens_out, cache_read, with_cache_pct=True)}")
        cost = llm.get("total_cost_usd")
        if cost is not None and cost > 0:
            lines.append(f"- Total cost: ${cost:.4f}")
        elif llm.get("pricing_available") is False:
            from pflow.core.metrics import format_unavailable_models_phrase, unavailable_models_to_counts

            partial = llm.get("partial_cost_usd")
            unavailable_counts = unavailable_models_to_counts(llm.get("unavailable_models", []))
            unavailable_unnamed_count = llm.get("unavailable_models_unnamed_count", 0)
            models_phrase = format_unavailable_models_phrase(unavailable_counts, unavailable_unnamed_count)
            if partial is not None and partial > 0:
                lines.append(f"- Total cost: — (pricing unavailable for {models_phrase}; partial cost ${partial:.4f})")
            else:
                lines.append(f"- Total cost: — (pricing unavailable for {models_phrase})")
        models = llm.get("models_used", [])
        if models:
            lines.append(f"- Models: {', '.join(models)}")

    lines.append(f"- Generated: {trace.get('end_time', '')}")
    lines.append("")

    all_events = trace.get("nodes", [])
    _format_pipeline_table(all_events, lines)

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
        warning_id = w.get("id")
        suggestions = w.get("suggestions") or []
        prefix = f"[{warning_id}] " if warning_id else ""
        lines.append(f"- {prefix}**{node_id}**: {message}")
        for suggestion in suggestions:
            lines.append(f"  - {suggestion}")
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
    lines.append(f"- Time: {format_duration(event.get('duration_ms', 0))}")
    status = "success" if event.get("success") else "failed"
    if event.get("cached"):
        status += " [cached]"
    lines.append(f"- Status: {status}")

    llm_call = event.get("llm_call")
    if isinstance(llm_call, dict):
        _format_llm_call_metadata(
            llm_call,
            lines,
            paid_cost=_compute_event_cost(event),
            cached=bool(event.get("cached")),
        )

    # Show retry metadata for claude-code schema retries
    node_output = event.get("node_output", {})
    if isinstance(node_output, dict):
        llm_usage = node_output.get("llm_usage")
        if isinstance(llm_usage, dict):
            retries = llm_usage.get("retries", [])
            if retries:
                # Show retry count
                retry_count = len(retries)
                lines.append(f"- Schema retries: {retry_count}")
                # Note: soft-fail status is already rendered by _append_runtime_warnings()
                # from trace-level warnings. No need to duplicate here.

    # Show user-configured LLM parameters (only when explicitly set in workflow)
    node_params = event.get("node_params", {})
    _format_llm_params(node_params, lines)

    error = event.get("error")
    if error:
        lines.append(f"- Error: {error}")


def _row_batch_item_label(node_id: str, item: dict[str, Any]) -> str:
    """Return ``node_id[index] (model-or-label)`` for an exploded batch-item row.

    Model tail uses the last path segment of ``llm_call.model`` so
    ``anthropic/claude-sonnet-4-5`` renders as ``claude-sonnet-4-5``. Non-LLM
    items fall back to the existing label-extraction helper.

    Known limitation: for nested provider paths (e.g.
    ``openrouter/anthropic/claude-3-sonnet``) only the last segment is shown
    — the reader sees ``(claude-3-sonnet)`` and loses the intermediate
    ``anthropic`` context. Today's LiteLLM convention is ``provider/model``
    (two segments), so this fires only for OpenRouter-style routes. The
    per-node file still carries the full model id.
    """
    idx = item.get("index", "?")
    llm_call = item.get("llm_call")
    # Defensive isinstance — matches the same guard in ``_row_tokens`` below.
    # Producer always writes a dict, but a synthetic/adversarial trace with a
    # non-dict ``llm_call`` would otherwise raise AttributeError here.
    model = llm_call.get("model") if isinstance(llm_call, dict) else None
    if isinstance(model, str) and model:
        tail = model.rsplit("/", 1)[-1]
        return f"{node_id}[{idx}] ({tail})"
    label = _extract_item_label(item)
    if label:
        return f"{node_id}[{idx}] ({label})"
    return f"{node_id}[{idx}]"


def _row_status(event_or_item: dict[str, Any]) -> str:
    """Lowercase status for the summary table: ``success``/``failed``/``cached``.

    Failure is checked BEFORE ``cached`` so the failure signal survives the
    rare ``(cached=True, success=False)`` shape. Cache hits in normal pflow
    flow imply success, so the cached branch wins for the common case.
    """
    if not event_or_item.get("success"):
        return "failed"
    return "cached" if event_or_item.get("cached") else "success"


def _row_tokens(event_or_item: dict[str, Any]) -> str:
    """``<in> in / <out> out`` for LLM rows; ``—`` otherwise.

    The trailing ``or 0`` guards against legacy cached entries where
    ``input_tokens``/``output_tokens`` is explicitly ``None`` instead of absent;
    ``f"{None:,}"`` raises ``TypeError``.
    """
    llm_call = event_or_item.get("llm_call")
    if not isinstance(llm_call, dict):
        return "—"
    total_in, cache_read = _input_token_total(llm_call)
    tokens_out = llm_call.get("output_tokens", llm_call.get("completion_tokens", 0)) or 0
    # Compact table cell: total in/out, no cache-% (that lives on the per-node line).
    return _format_tokens(total_in, tokens_out, cache_read, with_cache_pct=False)


def _format_pipeline_table(events: list[dict[str, Any]], lines: list[str]) -> None:
    """Append the pipeline summary table for a list of node events.

    Batch items are exploded into per-item rows (synthetic ``is_warmup`` items
    are filtered out per the runtime convention). Sub-workflow children stay
    collapsed under their parent row; their detail lives in the nested
    container ``summary.md``.

    ``#`` semantic is "node index in the workflow", not "row index in the
    table" — exploded batch items intentionally share their parent's number
    so a reader scanning the column sees workflow steps, not row positions.

    Rows are buffered and the header is only emitted when at least one row
    survives the warmup-item filter. Guards against the warmup-only batch
    edge case where every item is filtered out and only headers would print.
    """
    if not events:
        return
    rows: list[str] = []
    for i, event in enumerate(events, 1):
        type_tag = node_type_tag(event.get("node_type", "?"))
        batch_items = event.get("batch_items") or []
        # Explode batch hosts into one row per item. Sub-workflow containers
        # (which carry sub_workflow_events) keep their single aggregated row.
        if batch_items and not event.get("sub_workflow_events"):
            node_id = event.get("node_id", "?")
            for item in batch_items:
                if _is_warmup_item(item):
                    continue
                rows.append(
                    f"| {i} | {_row_batch_item_label(node_id, item)} | {type_tag} | "
                    f"{_row_status(item)} | {format_duration(item.get('duration_ms', 0))} | "
                    f"{_row_tokens(item)} | {_format_cost(_compute_batch_item_cost(item))} |"
                )
        else:
            rows.append(
                f"| {i} | {event.get('node_id', '?')} | {type_tag} | "
                f"{_row_status(event)} | {format_duration(event.get('duration_ms', 0))} | "
                f"{_row_tokens(event)} | {_format_cost(_compute_event_cost(event))} |"
            )
    if not rows:
        return
    lines.append("## Pipeline")
    lines.append("")
    lines.append("| # | Node | Type | Status | Time | Tokens | Cost |")
    lines.append("|---|------|------|--------|------|--------|------|")
    lines.extend(rows)
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
        _format_batch_errors_output(output, lines)
        _format_remaining_node_output(output, lines)


def _format_remaining_node_output(output: dict[str, Any], lines: list[str]) -> None:
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
    if _has_batch_error_output(output):
        shown_keys.update({"errors", "count", "success_count", "error_count", "batch_metadata"})
        if output.get("results") == []:
            shown_keys.add("results")
    remaining = {
        k: v for k, v in output.items() if k not in shown_keys and not (isinstance(k, str) and k.startswith("_"))
    }
    if remaining:
        lines.append("## Output")
        lines.append("")
        lines.append(f"```json\n{json.dumps(remaining, indent=2, default=str)}\n```")
        lines.append("")


def _has_batch_error_output(output: dict[str, Any]) -> bool:
    errors = output.get("errors")
    if output.get("batch_metadata") and isinstance(errors, list) and errors:
        return True
    return _looks_like_batch_error_list(errors)


def _looks_like_batch_error_list(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(item, dict) and "index" in item and "error" in item for item in value)


def _format_batch_errors_output(output: dict[str, Any], lines: list[str]) -> None:
    if not _has_batch_error_output(output):
        return
    errors = output.get("errors") or []
    if not isinstance(errors, list) or not errors:
        return

    from pflow.execution.formatters.batch_errors import compact_batch_error_detail, format_batch_item_summary

    lines.append("## Batch Errors")
    lines.append("")
    for error in errors[:5]:
        if not isinstance(error, dict):
            continue
        detail = compact_batch_error_detail(error)
        lines.append(f"- [{detail.get('index', '?')}] {detail.get('error', 'Unknown error')}")
        item_summary = format_batch_item_summary(detail)
        if item_summary:
            lines.append(f"  item: {item_summary}")
    if len(errors) > 5:
        lines.append(f"- ...and {len(errors) - 5} more errors")
    lines.append("")


def _format_cached_system(event: dict[str, Any], lines: list[str]) -> None:
    """Render the ``## Cached System`` section for trace 2.2.0 events.

    Plain string is rendered verbatim; ``list[dict]`` (cache-rendered blocks)
    emits a fenced JSON block so provider-specific ``cache_control`` markers
    stay visible to agents reading the report. No-op when the field is absent.
    """
    llm_system = event.get("llm_system")
    if llm_system is None:
        return

    lines.append("## Cached System")
    lines.append("")
    _append_str_or_blocks(llm_system, lines)
    skipped = (event.get("llm_call") or {}).get("cache_chunks_skipped") or []
    if skipped:
        lines.append("")
        lines.append(f"> Skipped chunks (resolved as ABSENT): {', '.join(skipped)}")
    lines.append("")


def _append_str_or_blocks(value: str | list[Any], lines: list[str]) -> None:
    if isinstance(value, str):
        lines.append(value)
        return

    lines.append("```json")
    lines.append(json.dumps(value, indent=2, default=str))
    lines.append("```")


def _format_cache_telemetry(event: dict[str, Any], lines: list[str]) -> None:
    """Render per-call cache observations from ``llm_call`` trace data."""
    llm_call = event.get("llm_call") or {}
    if not isinstance(llm_call, dict):
        return

    cache_creation = llm_call.get("cache_creation_input_tokens")
    cache_read = llm_call.get("cache_read_input_tokens")
    cache_key = llm_call.get("cache_key")
    cache_age_sec = llm_call.get("cache_age_sec")
    chunks_skipped = llm_call.get("cache_chunks_skipped") or []
    is_cached_replay = bool(llm_call.get("cache_source"))
    # llm nodes that opted into prompt caching carry the effective system in
    # `llm_system`; claude-code's prompt-cache tiers come from the SDK and have
    # no `llm_system`.
    declared_cache = bool(event.get("llm_system"))

    # Live prompt-cache tiers (write/read) are now folded into the "- Tokens:"
    # line as the input total + "% of input cached". This section remains ONLY
    # for what that line can't carry: a memo/result REPLAY (cache_key + age), or
    # an llm node that DECLARED caching — so "declared but didn't fire" stays
    # visible even at zero tokens. A live claude-code call (cache fired, no
    # declaration, not a replay) no longer emits a divorced section.
    has_signal = is_cached_replay or declared_cache or bool(chunks_skipped)
    if not has_signal:
        return

    if llm_call.get("cache_source") == "memo":
        lines.append("## Cache telemetry (cached result reused from prior run)")
    elif is_cached_replay:
        lines.append("## Cache telemetry (cached result reused)")
    else:
        lines.append("## Cache telemetry")
    lines.append("")

    # Token tiers only answer "did the DECLARED cache fire?" — show them for the
    # declared/replay cases; for live claude-code they're already on the Tokens line.
    if declared_cache or is_cached_replay:
        if isinstance(cache_creation, int):
            lines.append(f"- Cache write: {cache_creation:,} tokens")
        if isinstance(cache_read, int):
            lines.append(f"- Cache read: {cache_read:,} tokens")
    if cache_key:
        lines.append(f"- Cache key: {cache_key}")
    if is_cached_replay and isinstance(cache_age_sec, (int, float)):
        lines.append(f"- Result age: {cache_age_sec:.0f}s")
    lines.append("")


def _format_resolutions(event: dict[str, Any], lines: list[str]) -> None:
    """Render template resolutions and static params as markdown sections.

    Handles all node types: prompt (LLM), command (Shell), code+inputs (Python),
    and a catch-all for any other resolved parameters (HTTP headers, file paths, etc.).
    """
    resolutions = event.get("template_resolutions", {})
    shown: set[str] = set()

    # 2.2.0: cached system prefix — rendered before ## Prompt to match the
    # API call order (system → user).
    _format_cached_system(event, lines)
    _format_cache_telemetry(event, lines)

    if "prompt" in resolutions:
        lines.extend(["## Prompt", "", str(resolutions["prompt"].get("resolved", "")), ""])
        shown.add("prompt")
    elif llm_prompt := event.get("llm_prompt"):
        lines.extend(["## Prompt", ""])
        _append_str_or_blocks(llm_prompt, lines)
        lines.append("")

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
        if _is_warmup_item(item):
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
    lines.append(f"- Time: {format_duration(event.get('duration_ms', 0))}")
    lines.append(f"- Status: {'success' if event.get('success') else 'failed'}")
    container_cost = _compute_event_cost(event)
    if container_cost is not None:
        lines.append(f"- Cost: ${container_cost:.4f}")

    batch_items = event.get("batch_items", [])
    real_batch_items = [i for i in batch_items if not _is_warmup_item(i)]
    if batch_items:
        succeeded = sum(1 for i in real_batch_items if i.get("success"))
        lines.append(f"- Items: {len(real_batch_items)} ({succeeded}/{len(real_batch_items)} succeeded)")
        lines.append("")

        notable = _find_notable_items(real_batch_items, event)
        has_labels = any(_extract_item_label(item) for item in real_batch_items)

        if notable:
            _build_items_table(notable, has_labels, lines)
            hidden = len(real_batch_items) - len(notable)
            if hidden > 0:
                lines.append(f"*... and {hidden} more succeeded*")
                lines.append("")
        else:
            # All items normal — show aggregate stats for quick orientation
            _append_batch_stats(real_batch_items, lines)

        _append_batch_item_warnings(real_batch_items, lines, parent_event=event)

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
        dur = format_duration(item.get("duration_ms", 0))
        cost = _format_cost(_compute_batch_item_cost(item))
        status = _row_status(item)
        if has_labels:
            label = _item_label_or_index(item)
            lines.append(f"| {idx} | {label} | {dur} | {cost} | {status} |")
        else:
            lines.append(f"| {idx} | {dur} | {cost} | {status} |")
    lines.append("")


def _append_batch_stats(batch_items: list[dict[str, Any]], lines: list[str]) -> None:
    """Append aggregate stats (median time, total cost) for a clean batch.

    Shown when all items are normal (no table rendered). Gives a sense of
    per-item behavior without listing everything.
    """
    durations = [item.get("duration_ms", 0) for item in batch_items]
    if durations:
        median_dur = statistics.median(durations)
        lines.append(f"- Median time: {format_duration(median_dur)}")

    costs = [_compute_batch_item_cost(item) for item in batch_items]
    total_cost = sum(c for c in costs if c is not None)
    if total_cost > 0:
        lines.append(f"- Total cost: ${total_cost:.4f}")

    lines.append("")


def _build_batch_item_file(item: dict[str, Any], parent_event: dict[str, Any]) -> str:
    """Build file for a simple batch item (no sub-workflow)."""
    node_id = parent_event.get("node_id", "?")
    label = _item_label_or_index(item)
    lines = [f"# {node_id} — {label}", ""]
    lines.append(f"- Time: {format_duration(item.get('duration_ms', 0))}")
    status = "success" if item.get("success") else "failed"
    if item.get("cached"):
        status += " [cached]"
    lines.append(f"- Status: {status}")

    llm_call = item.get("llm_call")
    if isinstance(llm_call, dict):
        _format_llm_call_metadata(
            llm_call,
            lines,
            paid_cost=_compute_batch_item_cost(item),
            cached=bool(item.get("cached")),
        )

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
    lines.append(f"- Time: {format_duration(item.get('duration_ms', 0))}")
    lines.append(f"- Status: {'success' if item.get('success') else 'failed'}")
    lines.append("")

    child_events = item.get("events", [])
    _format_pipeline_table(child_events, lines)

    return "\n".join(lines)
