"""Shared validation helpers for the ``loop:`` modifier."""

from typing import Any


def check_loop_polarity(loop_data: dict[str, Any]) -> str | None:
    """Return an exactly-one-of ``while``/``until`` error message, or ``None``.

    This rule is enforced by both the compiler path and the validate-only/save
    path. Keeping it here prevents those two integration points from drifting.
    """
    has_while = isinstance(loop_data.get("while"), str) and bool(loop_data.get("while", "").strip())
    has_until = isinstance(loop_data.get("until"), str) and bool(loop_data.get("until", "").strip())
    if has_while and has_until:
        return "`loop:` must declare exactly one of `while:` or `until:`, not both."
    if not has_while and not has_until:
        return "`loop:` must declare exactly one of `while:` or `until:`."
    return None
