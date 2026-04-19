"""Shared formatters for --dry-run execution plans."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.duration_format import format_duration

if TYPE_CHECKING:
    from pflow.execution.result import Plan, PlanEntry

# Per-entry duration is only rendered in text when >= this threshold. Agents
# parsing JSON always see `last_duration_ms` in full fidelity regardless.
# Rationale: sub-second numbers on 20+ fast nodes pad the view without adding
# signal; the summary total still reflects them.
_TEXT_DURATION_THRESHOLD_MS = 1000.0

_NODE_TYPE_TAGS: dict[str, str] = {
    "LLMNode": "LLM",
    "ClaudeCodeNode": "Claude",
    "HttpNode": "HTTP",
    "ShellNode": "shell",
    "MCPNode": "MCP",
    "PythonCodeNode": "code",
    "ReadFileNode": "read-file",
    "WriteFileNode": "write-file",
    "CopyFileNode": "copy-file",
    "MoveFileNode": "move-file",
    "DeleteFileNode": "delete-file",
    "WorkflowExecutor": "workflow",
}


def format_plan_json(plan: Plan) -> dict[str, Any]:
    """Render a plan as a JSON-serializable dict."""
    return {
        "workflow": plan.workflow,
        "plan": [_entry_to_dict(entry) for entry in plan.entries],
        "summary": _summary_to_dict(plan.summary),
        "diagnostics": [diagnostic.to_dict() for diagnostic in plan.diagnostics],
    }


def format_plan_text(plan: Plan) -> str:
    """Render a plan as human-readable text."""
    lines: list[str] = []
    header_bits = [f"{plan.summary.total} nodes"]
    sub_count = sum(1 for entry in plan.entries if entry.status == "sub_workflow")
    if sub_count:
        header_bits.append(f"{sub_count} sub-workflow{'s' if sub_count != 1 else ''}")
    lines.append(f"Plan for {plan.workflow} ({', '.join(header_bits)}):")
    lines.append("")

    lines.extend(_render_entries(plan.entries, indent_level=0, boundary_shown=[False]))

    lines.append("")
    summary_parts = [f"{plan.summary.cached_count} cached", f"{plan.summary.execute_count} would execute"]
    if plan.summary.execute_by_type:
        types_str = ", ".join(
            f"{count} {node_type}" for node_type, count in sorted(plan.summary.execute_by_type.items())
        )
        summary_parts[-1] += f" ({types_str})"
    if plan.summary.total_including_nested is not None:
        lines.append(f"Summary (including nested): {' · '.join(summary_parts)}")
    else:
        lines.append(f"Summary: {' · '.join(summary_parts)}")

    effective_cost = (
        plan.summary.estimated_cost_usd_including_nested
        if plan.summary.estimated_cost_usd_including_nested is not None
        else plan.summary.estimated_cost_usd
    )
    effective_nwh = (
        plan.summary.nodes_without_history_including_nested
        if plan.summary.nodes_without_history_including_nested is not None
        else plan.summary.nodes_without_history
    )
    if effective_cost > 0:
        basis_label = (
            "upper bound across all branches, historical"
            if plan.summary.cost_basis == "upper_bound"
            else "historical, actual may vary"
        )
        lines.append(f"Estimated cost: ≈ {_format_cost(effective_cost)}  ({basis_label})")
    if effective_nwh > 0:
        lines.append(f"  ({effective_nwh} LLM node{'s' if effective_nwh != 1 else ''} without cost history)")

    effective_duration = (
        plan.summary.estimated_duration_ms_including_nested
        if plan.summary.estimated_duration_ms_including_nested is not None
        else plan.summary.estimated_duration_ms
    )
    effective_nwdh = (
        plan.summary.nodes_without_duration_history_including_nested
        if plan.summary.nodes_without_duration_history_including_nested is not None
        else plan.summary.nodes_without_duration_history
    )
    if effective_duration > 0:
        lines.append(f"Estimated duration: ~{format_duration(effective_duration)}  (historical, actual may vary)")
    if effective_nwdh > 0:
        lines.append(f"  ({effective_nwdh} node{'s' if effective_nwdh != 1 else ''} without duration history)")

    lines.append("No side effects performed.")

    if plan.diagnostics:
        lines.append("")
        for diagnostic in plan.diagnostics:
            lines.append(format_diagnostic(diagnostic))

    return "\n".join(lines)


def _render_entries(entries: list[PlanEntry], indent_level: int, boundary_shown: list[bool]) -> list[str]:
    """Render one plan level with boundary dividers."""
    lines: list[str] = []
    indent = "  " + "    " * indent_level
    all_execute = entries and all(entry.status in ("execute", "opaque") for entry in entries)
    any_cached = any(entry.status == "cached" for entry in entries)

    if all_execute and not any_cached and indent_level == 0:
        lines.append(f"{indent}─── nothing cached — full run ───")

    for entry in entries:
        show_boundary = (
            not boundary_shown[0]
            and entry.status in ("execute", "opaque")
            and entry.cause != "downstream"
            and ((indent_level == 0 and (any_cached or _has_any_cached_above(entries, entry))) or indent_level > 0)
        )
        if show_boundary:
            lines.append(f"{indent}─── cache boundary: '{entry.node_id}' ───")
            boundary_shown[0] = True

        lines.append(_render_entry_line(entry, indent))
        if entry.sub_plan is not None:
            lines.extend(_render_entries(entry.sub_plan.entries, indent_level + 1, boundary_shown=[False]))

    return lines


def _has_any_cached_above(entries: list[PlanEntry], target: PlanEntry) -> bool:
    """Check whether any preceding entry in this level is cached."""
    for entry in entries:
        if entry is target:
            return False
        if entry.status == "cached":
            return True
    return False


def _render_entry_line(entry: PlanEntry, indent: str) -> str:
    """Render one plan entry."""
    if entry.status == "cached":
        age = f"  ({_format_age(entry.age_sec)} ago)" if entry.age_sec is not None else ""
        return f"{indent}{click.style('↻', fg='blue', dim=True)} {entry.node_id}{age}"

    tag = f"  [{_tag_from_entry(entry)}]"
    if entry.status == "sub_workflow":
        ref = entry.sub_plan.workflow if entry.sub_plan else "<unknown>"
        count = entry.sub_plan.summary.total if entry.sub_plan else 0
        suffix = "s" if count != 1 else ""
        return f"{indent}▸ {entry.node_id}  [sub-workflow '{ref}' ({count} node{suffix})]"

    if entry.status == "opaque":
        return f"{indent}▸ {entry.node_id}  [sub-workflow: dynamic, cannot plan]"

    if entry.status == "routing_error":
        return f"{indent}▸ {entry.node_id}{tag}  [routing error]"

    annotation = _format_stats_annotation(entry)
    suffix = f"   {annotation}" if annotation else ""
    return f"{indent}▸ {entry.node_id}{tag}{suffix}"


def _format_stats_annotation(entry: PlanEntry) -> str | None:
    """Build the cost + duration + age annotation for an execute-status entry.

    Returns `None` when nothing would render — caller elides the whitespace.
    Centralizes threshold + precision rules so the policy lives in one place.
    """
    is_llm = _is_llm_entry(entry)
    has_cost = entry.last_cost_usd is not None
    duration_ms = entry.last_duration_ms
    show_duration = duration_ms is not None and duration_ms >= _TEXT_DURATION_THRESHOLD_MS

    # No-history fallback for LLM nodes — preserves the pre-duration contract
    # ("≈ $? (no history)") so agents iterating on a fresh LLM node still see
    # the LLM-specific cost hint. Non-LLM sub-second nodes render blank.
    if not has_cost and not show_duration:
        return "≈ $? (no history)" if is_llm else None

    parts: list[str] = []
    if is_llm:
        if has_cost and entry.last_cost_usd is not None:
            parts.append(f"≈ {_format_cost(entry.last_cost_usd)}")
        else:
            parts.append("≈ $?")
    if show_duration and duration_ms is not None:
        parts.append(f"~{format_duration(duration_ms)}")

    body = " · ".join(parts) if parts else None
    if body is None:
        return None

    if entry.last_run_age_sec is not None:
        body += f" (last run {_format_age(entry.last_run_age_sec)} ago)"
    return body


def _is_llm_entry(entry: PlanEntry) -> bool:
    """Identify LLM-family entries for cost rendering."""
    return entry.node_type in ("LLMNode", "ClaudeCodeNode")


def _tag_from_entry(entry: PlanEntry) -> str:
    """Map node type to short display tag."""
    tag = _NODE_TYPE_TAGS.get(entry.node_type, entry.node_type)
    if entry.cause == "cache_disabled":
        tag = f"{tag}, cache: false"
    return tag


def _format_age(age_sec: float | None) -> str:
    """Short age format for cached entries and historical runs."""
    if age_sec is None:
        return "?"
    if age_sec < 60:
        return f"{int(age_sec)}s"
    if age_sec < 3600:
        return f"{int(age_sec // 60)}m"
    if age_sec < 86400:
        return f"{int(age_sec // 3600)}h"
    return f"{int(age_sec // 86400)}d"


def _format_cost(cost_usd: float) -> str:
    """Format cost with task-specific precision rules."""
    if cost_usd >= 0.01:
        return f"${cost_usd:.2f}"
    return f"${cost_usd:.4f}"


def _entry_to_dict(entry: PlanEntry) -> dict[str, Any]:
    """Serialize a plan entry to dict."""
    result: dict[str, Any] = {
        "node_id": entry.node_id,
        "node_type": entry.node_type,
        "status": entry.status,
        "cause": entry.cause,
    }
    if entry.action is not None:
        result["action"] = entry.action
    if entry.age_sec is not None:
        result["age_sec"] = entry.age_sec
    if entry.last_cost_usd is not None:
        result["last_cost_usd"] = entry.last_cost_usd
    if entry.last_duration_ms is not None:
        result["last_duration_ms"] = entry.last_duration_ms
    if entry.last_run_age_sec is not None:
        result["last_run_age_sec"] = entry.last_run_age_sec
    if entry.sub_plan is not None:
        result["sub_plan"] = format_plan_json(entry.sub_plan)
    if entry.diagnostic is not None:
        result["diagnostic"] = entry.diagnostic.to_dict()
    return result


def _summary_to_dict(summary: Any) -> dict[str, Any]:
    """Serialize a plan summary to dict."""
    result: dict[str, Any] = {
        "total": summary.total,
        "cached_count": summary.cached_count,
        "execute_count": summary.execute_count,
        "cache_boundary": summary.cache_boundary,
        "execute_by_type": dict(summary.execute_by_type),
        "estimated_cost_usd": summary.estimated_cost_usd,
        "nodes_without_history": summary.nodes_without_history,
        "estimated_duration_ms": summary.estimated_duration_ms,
        "nodes_without_duration_history": summary.nodes_without_duration_history,
        "cost_basis": summary.cost_basis,
    }
    if summary.total_including_nested is not None:
        result["total_including_nested"] = summary.total_including_nested
        result["cached_including_nested"] = summary.cached_including_nested
        result["execute_including_nested"] = summary.execute_including_nested
    if summary.estimated_cost_usd_including_nested is not None:
        result["estimated_cost_usd_including_nested"] = summary.estimated_cost_usd_including_nested
        result["nodes_without_history_including_nested"] = summary.nodes_without_history_including_nested
    if summary.estimated_duration_ms_including_nested is not None:
        result["estimated_duration_ms_including_nested"] = summary.estimated_duration_ms_including_nested
        result["nodes_without_duration_history_including_nested"] = (
            summary.nodes_without_duration_history_including_nested
        )
    return result
