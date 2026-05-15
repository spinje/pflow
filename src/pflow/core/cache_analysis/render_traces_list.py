"""Renderers for ``pflow analyze-cache --list-traces``."""

from __future__ import annotations

import json

from .analyze import TraceListEntry
from .render_text import _format_recorded_timestamp


def render_traces_list_text(
    entries: list[TraceListEntry],
    *,
    workflow_path: str,
    disclosure_note: str | None = None,
) -> str:
    if not entries:
        return (
            f"No traces found for {workflow_path}.\n"
            "Looked in ~/.pflow/debug/ for workflow-trace-<hash>-*.json files.\n"
            "Run the workflow once to record a trace."
        )

    lines = [f"{len(entries)} trace(s) found for {workflow_path}", ""]
    for entry in entries:
        marker = "  > " if entry.would_be_autoloaded else "    "
        autoload_tag = "    [would be autoloaded]" if entry.would_be_autoloaded else ""
        lines.append(f"{marker}{entry.path.name}{autoload_tag}")
        lines.append(f"      path: {entry.path}")
        # Reuse the same YYYY-MM-DD HH:MM formatter the ``Trace:`` header uses
        # so timestamps render consistently across analyze-cache surfaces.
        formatted_timestamp = _format_recorded_timestamp(entry.recorded_at)
        metadata = [
            entry.final_status,
            f"recorded {formatted_timestamp}" if formatted_timestamp else "no timestamp",
            f"{entry.llm_call_count} LLM call(s)",
            f"${entry.total_cost_usd:.4f}" if entry.total_cost_usd is not None else "cost unavailable",
            f"{entry.duration_ms / 1000:.1f}s" if entry.duration_ms is not None else "duration unavailable",
        ]
        lines.append(f"      {', '.join(metadata)}")
        if entry.models_used:
            lines.append(f"      models: {', '.join(entry.models_used)}")
        if entry.model_drift_count is None:
            lines.append("      drift: comparison skipped (workflow has heterogeneous-model nodes)")
        elif entry.model_drift_count > 0:
            noun = "difference" if entry.model_drift_count == 1 else "differences"
            lines.append(f"      drift: {entry.model_drift_count} model {noun} from current workflow")
        lines.append("")
    if disclosure_note:
        lines.append(f"Note: {disclosure_note}")
        lines.append("")
    autoloaded = next((entry for entry in entries if entry.would_be_autoloaded), None)
    if autoloaded is not None:
        lines.append(f"Use autoloaded: pflow analyze-cache {workflow_path} --from-trace {autoloaded.path}")
    lines.append(f"Use any trace: pflow analyze-cache {workflow_path} --from-trace <path>")
    return "\n".join(lines)


def render_traces_list_json(
    entries: list[TraceListEntry],
    *,
    workflow_path: str,
    disclosure_note: str | None = None,
) -> str:
    from . import JSON_FORMAT_VERSION

    payload = {
        "format_version": JSON_FORMAT_VERSION,
        "mode": "list_traces",
        "workflow_path": workflow_path,
        "disclosure_note": disclosure_note,
        "traces": [
            {
                "path": str(entry.path),
                "would_be_autoloaded": entry.would_be_autoloaded,
                "final_status": entry.final_status,
                "recorded_at": entry.recorded_at or None,
                "duration_ms": entry.duration_ms,
                "llm_call_count": entry.llm_call_count,
                "total_cost_usd": entry.total_cost_usd,
                "models_used": list(entry.models_used),
                "model_drift_count": entry.model_drift_count,
            }
            for entry in entries
        ],
    }
    return json.dumps(payload, indent=2)
