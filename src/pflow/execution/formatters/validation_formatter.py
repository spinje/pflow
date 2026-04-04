"""Shared formatters for workflow validation results."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pflow.core.diagnostic import Diagnostic


def format_validation_success() -> str:
    """Format validation success message (minimal, token-efficient).

    Returns concise success message. All 4 validation checks passed:
    1. Schema validation (IR structure compliance)
    2. Data flow validation (execution order, no cycles)
    3. Template structure validation (${variable} references)
    4. Node types validation (registry verification)

    Returns:
        Single-line success message

    Example:
        >>> result = format_validation_success()
        >>> result
        '✓ Workflow is valid'
    """
    return "✓ Workflow is valid"


def format_validation_failure(errors: list[Diagnostic]) -> str:
    """Format validation failure message with per-error locations and suggestions.

    Args:
        errors: Validation error diagnostics

    Returns:
        Multi-line text with numbered error list
    """
    error_count = len(errors)
    lines = [f"✗ Validation failed ({error_count} error{'s' if error_count != 1 else ''}):", ""]

    for i, error in enumerate(errors[:5], 1):
        lines.append(f"  {i}. {error.message}")
        context = error.context or {}
        if (path := context.get("path")) and path != "root":
            lines.append(f"     At: {path}")
        if error.suggestions:
            lines.append(f"     → {error.suggestions[0]}")

    if error_count > 5:
        remaining = error_count - 5
        lines.append("")
        lines.append(f"  ... and {remaining} more error{'s' if remaining != 1 else ''}")

    return "\n".join(lines)
