"""Unified error output for CLI.

Produces a single JSON shape for ALL error types: pre-execution exceptions,
post-execution failures (ExecutionResult), and unexpected exceptions.
"""

from __future__ import annotations

import logging
from typing import Any

import click

from pflow.core.diagnostic import Diagnostic, exception_to_diagnostics
from pflow.core.diagnostic_render import format_diagnostic

logger = logging.getLogger(__name__)


def format_error_json(
    *,
    exception: Exception | None = None,
    result: Any = None,
    workflow_metadata: dict[str, Any] | None = None,
    metrics_collector: Any = None,
    shared_storage: dict[str, Any] | None = None,
    ir_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build unified error JSON from either an exception or an ExecutionResult.

    Exactly one of ``exception`` or ``result`` must be provided.

    Returns a dict conforming to the unified error shape:
    {success, status, error, errors, workflow, [duration_ms, metrics, execution]}
    """
    if result is not None:
        return _format_from_result(result, workflow_metadata, metrics_collector, shared_storage, ir_data)
    if exception is not None:
        return _format_from_exception(exception, workflow_metadata, metrics_collector, shared_storage)
    raise ValueError("Either exception or result must be provided")


def _format_from_result(
    result: Any,
    workflow_metadata: dict[str, Any] | None,
    metrics_collector: Any,
    shared_storage: dict[str, Any] | None,
    ir_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Format error from ExecutionResult (post-execution failure)."""
    from pflow.execution.formatters.error_formatter import format_execution_errors

    status = getattr(result, "status", None)
    status_str = status.value if status else "failed"

    # Use existing error formatter for sanitization and execution steps
    formatted = format_execution_errors(
        result,
        shared_storage=shared_storage,
        ir_data=ir_data,
        metrics_collector=metrics_collector,
        sanitize=True,
    )

    errors_list = formatted["errors"]

    # Derive summary from actual errors
    if len(errors_list) == 1:
        summary = errors_list[0].get("message", "Unknown error")
    else:
        summary = f"Workflow execution failed ({len(errors_list)} errors)"

    output: dict[str, Any] = {
        "success": False,
        "status": status_str,
        "error": summary,
        "errors": errors_list,
        "diagnostics": [
            diagnostic.to_dict()
            for diagnostic in getattr(result, "diagnostics", [])
            if isinstance(diagnostic, Diagnostic)
        ],
    }

    # Workflow metadata
    output["workflow"] = workflow_metadata or {"action": "unsaved"}

    # Execution state (from formatter)
    if "execution" in formatted:
        output["execution"] = formatted["execution"]

    # Metrics (flatten to top-level, matching success shape)
    if "metrics" in formatted:
        metrics_data = formatted["metrics"]
        if "duration_ms" in metrics_data:
            output["duration_ms"] = metrics_data["duration_ms"]
        if "total_cost_usd" in metrics_data:
            output["total_cost_usd"] = metrics_data["total_cost_usd"]
        if "nodes_executed" in metrics_data:
            output["nodes_executed"] = metrics_data["nodes_executed"]
        if "metrics" in metrics_data:
            output["metrics"] = metrics_data["metrics"]

    return output


def _format_from_exception(
    exception: Exception,
    workflow_metadata: dict[str, Any] | None,
    metrics_collector: Any,
    shared_storage: dict[str, Any] | None,
) -> dict[str, Any]:
    """Format error from a pre-execution or unexpected exception."""
    diagnostics = exception_to_diagnostics(exception)
    errors = [d.to_display_dict() for d in diagnostics]
    if len(errors) == 1:
        summary = errors[0].get("title") or errors[0].get("message") or str(exception)
    else:
        summary = getattr(exception, "summary", None) or f"Workflow execution failed ({len(errors)} errors)"

    output: dict[str, Any] = {
        "success": False,
        "status": "failed",
        "error": summary,
        "errors": errors,
        "diagnostics": [d.to_dict() for d in diagnostics],
        "workflow": workflow_metadata or {"action": "unsaved"},
    }

    # Add metrics if available (exception during execution may still have metrics)
    if metrics_collector is not None:
        try:
            metrics_collector.record_workflow_end()
            trace = shared_storage.get("__trace_collector__") if shared_storage else None
            llm_calls = trace.collect_llm_calls() if trace else []
            summary_data = metrics_collector.get_summary(llm_calls)
            if summary_data:
                if "duration_ms" in summary_data:
                    output["duration_ms"] = summary_data["duration_ms"]
                if "total_cost_usd" in summary_data:
                    output["total_cost_usd"] = summary_data["total_cost_usd"]
                if "metrics" in summary_data:
                    output["metrics"] = summary_data["metrics"]
        except Exception:
            logger.debug("Metrics collection failed during error output", exc_info=True)

    return output


def display_exception_text(exception: Exception, verbose: bool = False) -> None:
    """Display exception in text mode using the diagnostic pipeline."""
    diagnostics = exception_to_diagnostics(exception)
    for diagnostic in diagnostics:
        click.echo(format_diagnostic(diagnostic, verbose=verbose), err=True)


def output_error(
    ctx: click.Context | None,
    exception: Exception | None = None,
    result: Any = None,
    output_format: str = "text",
    verbose: bool = False,
    workflow_metadata: dict[str, Any] | None = None,
    metrics_collector: Any = None,
    shared_storage: dict[str, Any] | None = None,
    ir_data: dict[str, Any] | None = None,
) -> None:
    """Output an error in the appropriate format (JSON or text).

    This is the SINGLE error output function for the entire CLI.
    """
    if output_format == "json":
        from pflow.cli.workflow_output import _serialize_json_result

        error_dict = format_error_json(
            exception=exception,
            result=result,
            workflow_metadata=workflow_metadata,
            metrics_collector=metrics_collector,
            shared_storage=shared_storage,
            ir_data=ir_data,
        )
        _serialize_json_result(error_dict, verbose)
    else:
        if exception is not None:
            display_exception_text(exception, verbose)
        elif result is not None:
            from pflow.cli.workflow_errors import _display_text_error_details

            _display_text_error_details(result, verbose)
        else:
            click.echo("cli: Unknown error", err=True)
