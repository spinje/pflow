"""Shared compact formatting for batch item failures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MAX_BATCH_ERRORS_SHOWN = 5
MAX_ERROR_MESSAGE_CHARS = 200
MAX_ITEM_SUMMARY_CHARS = 240


def format_batch_errors_section(steps: list[dict[str, Any]]) -> list[str]:
    """Format compact batch error sections for execution step rows."""
    lines: list[str] = []

    for step in steps:
        if not step.get("is_batch") or step.get("batch_errors", 0) == 0:
            continue

        node_id = step.get("node_id", "unknown")
        error_details = step.get("batch_error_details", [])
        truncated = step.get("batch_errors_truncated", 0)

        lines.append(f"\nBatch '{node_id}' errors:")
        for err in error_details[:MAX_BATCH_ERRORS_SHOWN]:
            if not isinstance(err, Mapping):
                continue
            idx = err.get("index", "?")
            msg = _truncate_error_message(str(err.get("error", "Unknown error")))
            lines.append(f"  [{idx}] {msg}")
            item_summary = format_batch_item_summary(err)
            if item_summary:
                lines.append(f"      item: {item_summary}")

        if truncated > 0:
            lines.append(f"  ...and {truncated} more errors")

    return lines


def format_batch_item_summary(error_detail: Mapping[str, Any]) -> str | None:
    """Return the display-safe item summary for one batch error, if present."""
    summary = error_detail.get("item_summary")
    if not isinstance(summary, Mapping):
        return None
    text = summary.get("summary")
    if not isinstance(text, str) or not text:
        return None
    return _truncate_text(text, MAX_ITEM_SUMMARY_CHARS)


def compact_batch_error_detail(error_detail: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON/API-safe batch error detail without raw item data."""
    compact: dict[str, Any] = {
        "index": error_detail.get("index", "?"),
        "error": _truncate_error_message(str(error_detail.get("error", "Unknown error"))),
    }

    summary = error_detail.get("item_summary")
    if isinstance(summary, Mapping):
        compact_summary = dict(summary)
        compact["item_summary"] = compact_summary
        item_ref = compact_summary.get("sha256")
        if isinstance(item_ref, str) and item_ref:
            compact["item_ref"] = item_ref

    if "item" in error_detail:
        compact["has_full_item"] = True

    return compact


def compact_batch_output_value(value: Any) -> Any:
    """Return a display/API-safe copy of a batch aggregate output value.

    Successful ``results[].item`` values remain full-fidelity. Only failed
    ``errors[]`` records are compacted because they are the unbounded failure
    surface that renderers may otherwise dump as workflow output.
    """
    if not isinstance(value, Mapping):
        return value
    errors = value.get("errors")
    if not isinstance(errors, list):
        return value
    if not value.get("batch_metadata") and not all(
        isinstance(error, Mapping) and "index" in error and "error" in error for error in errors
    ):
        return value

    compact = dict(value)
    compact["errors"] = [compact_batch_error_detail(error) if isinstance(error, Mapping) else error for error in errors]
    return compact


def _truncate_error_message(message: str, max_length: int = MAX_ERROR_MESSAGE_CHARS) -> str:
    headline = _error_headline(message)
    if len(headline) <= max_length:
        return headline
    return headline[: max_length - 3] + "..."


def _truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _error_headline(message: str) -> str:
    for line in message.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "Unknown error"
