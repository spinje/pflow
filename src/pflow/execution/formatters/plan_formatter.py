"""Shared formatters for --dry-run execution plans."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.duration_format import format_duration
from pflow.core.node_type_display import node_type_tag

if TYPE_CHECKING:
    from pflow.execution.result import Plan, PlanEntry

# Per-entry duration is only rendered in text when >= this threshold. Agents
# parsing JSON always see `last_duration_ms` in full fidelity regardless.
# Rationale: sub-second numbers on 20+ fast nodes pad the view without adding
# signal; the summary total still reflects them.
_TEXT_DURATION_THRESHOLD_MS = 1000.0


def format_plan_json(plan: Plan) -> dict[str, Any]:
    """Render a plan as a JSON-serializable dict."""
    result: dict[str, Any] = {
        "workflow": plan.workflow,
        "plan": [_entry_to_dict(entry) for entry in plan.entries],
        "summary": _summary_to_dict(plan.summary),
        "diagnostics": [diagnostic.to_dict() for diagnostic in plan.diagnostics],
    }
    # Task 164: a resumed plan covers the tail from K onward only; expose the
    # resume context so a programmatic consumer knows the cost is not whole-run.
    if plan.resume is not None:
        result["resume"] = {
            "entry_node": plan.resume.entry_node,
            "restored_nodes": list(plan.resume.restored_nodes),
            "execution_id": plan.resume.execution_id,
        }
    return result


def _resume_header_line(plan: Plan) -> str | None:
    """The resume honesty line (Task 164): a resumed plan starts AT K, so entries + cost cover the tail only."""
    if plan.resume is None:
        return None
    count = len(plan.resume.restored_nodes)
    noun = "step" if count == 1 else "steps"
    src = f" from {plan.resume.execution_id}" if plan.resume.execution_id else ""
    return (
        f"Resuming from '{plan.resume.entry_node}': {count} upstream {noun} restored{src} "
        f"(plan + cost cover this step onward)."
    )


def format_plan_text(plan: Plan) -> str:
    """Render a plan as human-readable text."""
    lines: list[str] = []
    header_bits = [f"{plan.summary.total} nodes"]
    sub_count = sum(1 for entry in plan.entries if entry.status == "sub_workflow")
    if sub_count:
        header_bits.append(f"{sub_count} sub-workflow{'s' if sub_count != 1 else ''}")
    # Base name only for readability — JSON keeps the full `plan.workflow` value
    # as a stable agent contract.
    workflow_label = Path(plan.workflow).name if plan.workflow else plan.workflow
    header = f"Dry-run for {workflow_label}: {', '.join(header_bits)}"
    # filter(None, ...) drops the resume line when absent WITHOUT a branch here
    # (keeps this function under the C901 budget; the resume detail is folded away).
    lines.extend(filter(None, (header, _resume_header_line(plan))))
    lines.append("")

    lines.extend(_render_entries(plan.entries, indent_level=0, boundary_shown=[False]))

    lines.append("")
    has_nested = plan.summary.total_including_nested is not None
    cached = (
        plan.summary.cached_including_nested
        if has_nested and plan.summary.cached_including_nested is not None
        else plan.summary.cached_count
    )
    execute = (
        plan.summary.execute_including_nested
        if has_nested and plan.summary.execute_including_nested is not None
        else plan.summary.execute_count
    )
    type_breakdown = (
        plan.summary.execute_by_type_including_nested
        if has_nested and plan.summary.execute_by_type_including_nested is not None
        else plan.summary.execute_by_type
    )
    summary_parts = [f"{cached} cached", f"{execute} would execute"]
    if type_breakdown:
        types_str = ", ".join(
            f"{count} {node_type_tag(node_type)}" for node_type, count in sorted(type_breakdown.items())
        )
        summary_parts[-1] += f" ({types_str})"
    label = "Summary (including nested)" if has_nested else "Summary"
    lines.append(f"{label}: {' · '.join(summary_parts)}")

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

    # Agent-facing caution: the totals above exclude any sub-workflow the
    # planner couldn't resolve (`workflow: ${var}`). Cost-gating must know
    # the number is an under-estimate so it can refuse to proceed.
    effective_opaque = (
        plan.summary.opaque_count_including_nested
        if plan.summary.opaque_count_including_nested is not None
        else plan.summary.opaque_count
    )
    if effective_opaque > 0:
        lines.append(
            f"  ⚠ {effective_opaque} opaque sub-workflow{'s' if effective_opaque != 1 else ''} — "
            "totals above exclude their cost/duration"
        )

    _append_gate_footer(lines, plan.entries)

    if plan.diagnostics:
        lines.append("")
        for diagnostic in plan.diagnostics:
            lines.append(format_diagnostic(diagnostic))

    return "\n".join(lines)


def _render_entries(entries: list[PlanEntry], indent_level: int, boundary_shown: list[bool]) -> list[str]:
    """Render one plan level with boundary dividers."""
    lines: list[str] = []
    indent = "  " + "    " * indent_level
    any_cached = any(entry.status == "cached" for entry in entries)

    if entries and indent_level == 0 and not _has_any_cached_recursive(entries):
        lines.append(f"{indent}─── nothing cached — full run ───")

    for entry in entries:
        show_boundary = (
            not boundary_shown[0]
            and entry.status in ("execute", "opaque")
            and entry.cause not in ("downstream", "downstream_batch")
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


def _has_any_cached_recursive(entries: list[PlanEntry]) -> bool:
    """Whether any entry at this level or in any sub_plan is cached.

    Required for the "nothing cached — full run" divider: a plan where every
    top-level entry is a `sub_workflow` whose children are fully cached
    should NOT render "nothing cached" at the top. The divider promises a
    full run with zero cache hits anywhere.
    """
    for entry in entries:
        if entry.status == "cached":
            return True
        if entry.batch_items_cached is not None and entry.batch_items_cached > 0:
            return True
        if entry.sub_plan is not None and _has_any_cached_recursive(entry.sub_plan.entries):
            return True
    return False


def _render_entry_line(entry: PlanEntry, indent: str) -> str:
    """Render one plan entry."""
    if entry.status == "sub_workflow" and entry.batch_count is not None:
        ref = entry.sub_plan.workflow if entry.sub_plan else "<unknown>"
        has_work = True
        if entry.sub_plan is not None:
            child = entry.sub_plan.summary
            has_work = child.execute_count > 0 or (child.execute_including_nested or 0) > 0
        symbol = "▸" if has_work else click.style("↻", fg="blue", dim=True)
        parallel_tag = ", parallel" if entry.batch_parallel else ""
        return f"{indent}{symbol} {entry.node_id}  [workflow '{ref}' \u00d7 {entry.batch_count} items{parallel_tag}]"

    if entry.batch_items_total is not None:
        cached = entry.batch_items_cached or 0
        total = entry.batch_items_total
        if cached == total:
            age = f"  ({_format_age(entry.age_sec)} ago)" if entry.age_sec is not None else ""
            return f"{indent}{click.style('↻', fg='blue', dim=True)} {entry.node_id}{age}"

        tag = f"  [{_tag_from_entry(entry)}]"
        execute_count = total - cached
        if cached > 0:
            stats = _format_batch_node_stats(entry)
            return f"{indent}▸ {entry.node_id}{tag}  {execute_count}/{total} would execute{stats}"

        annotation = _format_stats_annotation(entry)
        suffix = f"   {annotation}" if annotation else ""
        return f"{indent}▸ {entry.node_id}{tag}{suffix}"

    if entry.status == "cached":
        age = f"  ({_format_age(entry.age_sec)} ago)" if entry.age_sec is not None else ""
        return f"{indent}{click.style('↻', fg='blue', dim=True)} {entry.node_id}{age}"

    tag = f"  [{_tag_from_entry(entry)}]"
    approval_tag = ", approval" if entry.approval else ""
    if entry.status == "sub_workflow":
        ref = entry.sub_plan.workflow if entry.sub_plan else "<unknown>"
        count = entry.sub_plan.summary.total if entry.sub_plan else 0
        suffix = "s" if count != 1 else ""
        return f"{indent}▸ {entry.node_id}  [sub-workflow '{ref}' ({count} node{suffix}){approval_tag}]"

    if entry.status == "opaque":
        reason = (
            "batch downstream, item count unreliable" if entry.cause == "downstream_batch" else "dynamic, cannot plan"
        )
        return f"{indent}▸ {entry.node_id}  [sub-workflow: {reason}{approval_tag}]"

    if entry.status == "routing_error":
        return f"{indent}▸ {entry.node_id}{tag}  [routing error]"

    annotation = _format_stats_annotation(entry)
    suffix = f"   {annotation}" if annotation else ""
    return f"{indent}▸ {entry.node_id}{tag}{suffix}"


def _format_batch_node_stats(entry: PlanEntry) -> str:
    """Build the average-cost / average-duration suffix for partial batch nodes."""
    is_llm = _is_llm_entry(entry)
    has_cost = entry.last_cost_usd is not None
    duration_ms = entry.last_duration_ms
    show_duration = duration_ms is not None and duration_ms >= _TEXT_DURATION_THRESHOLD_MS

    if not has_cost and not show_duration:
        return "  ≈ $? (no history)" if is_llm else ""

    parts: list[str] = []
    if is_llm:
        if has_cost and entry.last_cost_usd is not None:
            parts.append(f"≈ {_format_cost(entry.last_cost_usd)}")
        else:
            parts.append("≈ $?")
    if show_duration and duration_ms is not None:
        parts.append(f"~{format_duration(duration_ms)}")
    if not parts:
        return ""
    return f"  {' · '.join(parts)}"


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


def _append_gate_footer(lines: list[str], entries: list[PlanEntry]) -> None:
    """Task 125: one footer line naming every gated step + its pre-approve flag.

    Makes the agent-operator playbook self-discoverable — the plan is where an
    agent learns a run will pause, BEFORE side effects fire. No-op when nothing
    is gated.
    """
    gated = _collect_gated_node_ids(entries)
    if not gated:
        return
    flags = " ".join(f"--auto-approve={node_id}" for node_id in gated)
    plural = "s" if len(gated) != 1 else ""
    lines.append(
        f"⏸ {len(gated)} step{plural} pause{'' if plural else 's'} for approval at run time "
        f"({', '.join(gated)}); non-interactive runs need {flags}"
    )


def _collect_gated_node_ids(entries: list[PlanEntry]) -> list[str]:
    """All gated node ids in plan order, including inside nested sub-plans.

    First-seen dedup: a child workflow planned per batch item (or reached via
    several paths) must not repeat its gate in the footer.
    """
    seen: list[str] = []
    for entry in entries:
        if entry.approval and entry.node_id not in seen:
            seen.append(entry.node_id)
        if entry.sub_plan is not None:
            for child_id in _collect_gated_node_ids(entry.sub_plan.entries):
                if child_id not in seen:
                    seen.append(child_id)
    return seen


def _is_llm_entry(entry: PlanEntry) -> bool:
    """Identify LLM-family entries for cost rendering."""
    return entry.node_type in ("LLMNode", "ClaudeCodeNode")


def _tag_from_entry(entry: PlanEntry) -> str:
    """Map node type to short display tag.

    Only `llm` nodes cache by default, so `cache: false` is notable solely on an
    LLMNode (an explicit opt-out of the default-on behavior). For every other
    node type, cache-disabled is the silent default — tagging it would label
    every shell/code/http node as `cache: false`, which is pure noise.
    """
    tag = node_type_tag(entry.node_type)
    if entry.cause == "cache_disabled" and entry.node_type == "LLMNode":
        tag = f"{tag}, cache: false"
    if entry.approval:
        # Task 125: dry-run must show gated nodes as would-pause — a plan that
        # renders a gated node as plain execute is a parity lie (the cached
        # path correctly skips this: a cache hit never gates).
        tag = f"{tag}, approval"
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


_OPTIONAL_SCALAR_FIELDS: tuple[str, ...] = (
    # Predicted cache_key from the planner. Useful for cache-debugging
    # agents and consumed by ``analyze-cache --from-trace`` to detect
    # discrepancies. Omitted when None (routing errors, opaque
    # sub-workflows, BFS-downstream entries).
    "cache_key",
    "action",
    "age_sec",
    "last_cost_usd",
    "last_duration_ms",
    "last_run_age_sec",
)


def _entry_to_dict(entry: PlanEntry) -> dict[str, Any]:
    """Serialize a plan entry to dict."""
    result: dict[str, Any] = {
        "node_id": entry.node_id,
        "node_type": entry.node_type,
        "status": entry.status,
        "cause": entry.cause,
    }
    for field in _OPTIONAL_SCALAR_FIELDS:
        value = getattr(entry, field)
        if value is not None:
            result[field] = value
    if entry.batch_count is not None:
        result["batch_count"] = entry.batch_count
        result["batch_parallel"] = entry.batch_parallel
    if entry.batch_items_total is not None:
        result["batch_items_cached"] = entry.batch_items_cached
        result["batch_items_total"] = entry.batch_items_total
    if entry.sub_plan is not None:
        result["sub_plan"] = format_plan_json(entry.sub_plan)
    if entry.diagnostic is not None:
        result["diagnostic"] = entry.diagnostic.to_dict()
    if entry.approval:
        # Task 125: JSON dry-run is the gate-discovery surface for agent
        # operators (discover gates → ask your human → --auto-approve).
        result["approval"] = True
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
        "opaque_count": summary.opaque_count,
        "cost_basis": summary.cost_basis,
    }
    if summary.total_including_nested is not None:
        result["total_including_nested"] = summary.total_including_nested
        result["cached_including_nested"] = summary.cached_including_nested
        result["execute_including_nested"] = summary.execute_including_nested
        if summary.execute_by_type_including_nested is not None:
            result["execute_by_type_including_nested"] = dict(summary.execute_by_type_including_nested)
    if summary.estimated_cost_usd_including_nested is not None:
        result["estimated_cost_usd_including_nested"] = summary.estimated_cost_usd_including_nested
        result["nodes_without_history_including_nested"] = summary.nodes_without_history_including_nested
    if summary.estimated_duration_ms_including_nested is not None:
        result["estimated_duration_ms_including_nested"] = summary.estimated_duration_ms_including_nested
        result["nodes_without_duration_history_including_nested"] = (
            summary.nodes_without_duration_history_including_nested
        )
    if summary.opaque_count_including_nested is not None:
        result["opaque_count_including_nested"] = summary.opaque_count_including_nested
    return result
