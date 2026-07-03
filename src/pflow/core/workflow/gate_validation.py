"""Shared validation helpers for the ``approval:`` gate field (Task 125)."""

from typing import Any


def check_approval_allowed(node_data: dict[str, Any]) -> str | None:
    """Return an error message when ``approval:`` is declared on a batch step, else ``None``.

    A batch host skips top-level template resolution (per-item resolution happens
    inside the batch executor), so a gate at the engine's pre-exec seam would
    preview unresolved ``${item}`` templates — a misleading approval. Rejected at
    validation instead: gate a step before or after the batch.

    This rule is enforced by both the compiler path and the validate-only/save
    path. Keeping it here prevents those two integration points from drifting.
    """
    if node_data.get("approval") is not None and node_data.get("batch") is not None:
        return (
            "`approval:` is not supported on batch steps — the approval preview cannot "
            "show resolved per-item values. Gate a step before or after the batch instead."
        )
    return None
