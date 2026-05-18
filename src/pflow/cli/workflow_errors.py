"""Workflow error display and formatting.

Text-mode error display for ExecutionResult failures. JSON error output
is now handled by error_output.py.
"""

from __future__ import annotations

from typing import Any

import click

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.diagnostic_render import format_diagnostic


def _display_single_error(
    error: Diagnostic,
    error_number: int | None,
    verbose: bool = False,
) -> None:
    """Display a single workflow error via format_diagnostic.

    Args:
        error: Error diagnostic from ExecutionResult
        error_number: 1-indexed error number for multi-error display, None for single error.
        verbose: Whether to show technical details
    """
    click.echo(
        format_diagnostic(
            error,
            verbose=verbose,
            error_number=error_number,
        ),
        err=True,
    )


def _display_text_error_details(
    result: Any,
    verbose: bool = False,
    *,
    shared_storage: dict[str, Any] | None = None,
    ir_data: dict[str, Any] | None = None,
    metrics_collector: Any | None = None,
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

    # Include INFO advisories alongside WARNING on the surface — INFO
    # diagnostics surface in reports per the severity-aware status contract
    # (see `_is_degrading_warning` in `execution/runner.py`). The
    # `result.warnings` property filters to WARNING-only by name; pull from
    # diagnostics directly to include INFO too. Matches the parallel filter
    # in `cli/commands/run.py` on the success path.
    warnings = [
        diagnostic
        for diagnostic in getattr(result, "diagnostics", [])
        if diagnostic.severity in {Severity.WARNING, Severity.INFO}
    ]
    errors = result.errors

    if len(errors) > 1:
        # Multi-error: summary header, then numbered diagnostics
        warning_suffix = f", {len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else ""
        click.echo(f"❌ Workflow execution failed ({len(errors)} errors{warning_suffix})", err=True)
        for i, error in enumerate(errors, 1):
            click.echo("", err=True)
            _display_single_error(error, error_number=i, verbose=verbose)
    else:
        # Single error: format_diagnostic provides the complete titled output
        click.echo("", err=True)
        _display_single_error(errors[0], error_number=None, verbose=verbose)

    if shared_storage is not None and ir_data is not None:
        from pflow.execution.execution_state import build_execution_steps
        from pflow.execution.formatters.batch_errors import format_batch_errors_section

        steps = build_execution_steps(ir_data, shared_storage, metrics_summary=None)
        for line in format_batch_errors_section(steps):
            click.echo(line, err=True)

    if warnings:
        click.echo("", err=True)
        click.echo("⚠️ Warnings:", err=True)
        for warning in warnings:
            click.echo(format_diagnostic(warning), err=True)
