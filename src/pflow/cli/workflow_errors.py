"""Workflow error display and formatting.

Text-mode error display for ExecutionResult failures. JSON error output
is now handled by error_output.py.
"""

from __future__ import annotations

from typing import Any

import click

from pflow.core.diagnostic import (
    Diagnostic,
    Severity,
    coerce_error_diagnostic,
    coerce_warning_diagnostic,
    format_diagnostic,
)


def _display_single_error(
    error: Diagnostic | dict[str, Any],
    error_number: int | None,
    verbose: bool = False,
    warning_count: int = 0,
) -> None:
    """Display a single workflow error with all details.

    Shell command details (command, stdout, stderr) are always shown on failure
    for agent diagnosis — not gated by verbose.

    Args:
        error: Error diagnostic or dict from ExecutionResult
        error_number: 1-indexed error number, or 0 for a single unnumbered error.
            None omits the "Error" heading and is reserved for concise exception text.
        verbose: Reserved for future use (shell details are always shown)
        warning_count: Number of warning diagnostics attached to the failed run
    """
    diagnostic = coerce_error_diagnostic(error)
    category = (diagnostic.context or {}).get("category") or "unknown"

    if error_number in {0, 1}:
        if diagnostic.source == "compilation" or category == "compilation":
            header = f"❌ Compilation failed ({warning_count} warnings)" if warning_count else "❌ Compilation failed"
        elif warning_count:
            header = f"❌ Workflow failed ({warning_count} warnings)"
        else:
            header = "❌ Workflow execution failed"
        click.echo(header, err=True)
    click.echo("", err=True)
    click.echo(
        format_diagnostic(
            diagnostic,
            verbose=verbose,
            error_number=error_number,
        ),
        err=True,
    )


def _display_text_error_details(
    result: Any,
    verbose: bool = False,
) -> None:
    """Display detailed text error output.

    Args:
        result: ExecutionResult with error details
        verbose: Reserved for future use (shell details are always shown)
    """
    if not result or not hasattr(result, "errors") or not result.errors:
        # Fallback to generic message
        click.echo("cli: Workflow execution failed - Node returned error action", err=True)
        click.echo("cli: Check node output above for details", err=True)
        return

    warnings = _collect_warning_diagnostics(result)
    show_error_numbers = len(result.errors) > 1
    for i, error in enumerate(result.errors, 1):
        error_number = i if show_error_numbers else 0
        _display_single_error(
            error,
            error_number,
            verbose=verbose,
            warning_count=len(warnings),
        )

    if warnings:
        click.echo("", err=True)
        click.echo("⚠️ Warnings:", err=True)
        for warning in warnings:
            click.echo(format_diagnostic(warning), err=True)


def _collect_warning_diagnostics(result: Any) -> list[Diagnostic]:
    """Collect warning diagnostics from new or legacy result fields."""
    diagnostics = [
        diagnostic
        for diagnostic in getattr(result, "diagnostics", [])
        if isinstance(diagnostic, Diagnostic) and diagnostic.severity == Severity.WARNING
    ]
    if diagnostics:
        return diagnostics

    warnings: list[Diagnostic] = []
    for warning in getattr(result, "warnings", []):
        warnings.append(coerce_warning_diagnostic(warning))
    return warnings
