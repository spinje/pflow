"""Unified error output for CLI.

Produces a single JSON shape for ALL error types: pre-execution exceptions,
post-execution failures (ExecutionResult), and unexpected exceptions.
"""

from __future__ import annotations

import logging
from typing import Any

import click

from pflow.core.exceptions import (
    MarkdownParseError,
    MaxNodeVisitsError,
    SchemaValidationError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError

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

    # Errors array
    if "errors" in formatted:
        errors_list = formatted["errors"]
    elif hasattr(result, "errors") and result.errors:
        errors_list = result.errors
    else:
        errors_list = [{"message": "Unknown error", "category": "unknown"}]

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
    summary, errors = _exception_to_errors(exception)

    output: dict[str, Any] = {
        "success": False,
        "status": "failed",
        "error": summary,
        "errors": errors,
        "workflow": workflow_metadata or {"action": "unsaved"},
    }

    # Add metrics if available (exception during execution may still have metrics)
    if metrics_collector is not None:
        try:
            metrics_collector.record_workflow_end()
            trace = shared_storage.get("_trace_collector") if shared_storage else None
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


def _exception_to_errors(exception: Exception) -> tuple[str, list[dict[str, Any]]]:  # noqa: C901
    """Convert any exception to (summary, errors_list) for unified JSON.

    Extracts structured fields from known exception types.
    Unknown exceptions get a generic single-error entry.

    Order matters: subclasses are checked BEFORE parent classes.
    """
    if isinstance(exception, WorkflowValidationError):
        return _workflow_validation_to_errors(exception)
    if isinstance(exception, WorkflowNotFoundError):
        return _workflow_not_found_to_errors(exception)
    if isinstance(exception, MCPError):
        return _mcp_error_to_errors(exception)
    if isinstance(exception, OutputResolutionError):
        return _output_resolution_to_errors(exception)
    if isinstance(exception, UserFriendlyError):
        return _user_friendly_to_errors(exception)
    if isinstance(exception, MaxNodeVisitsError):
        return str(exception), [
            {
                "message": str(exception),
                "category": "max_visits",
                "node_id": exception.node_id,
                "visit_count": exception.visit_count,
                "max_visits": exception.max_visits,
            }
        ]
    if isinstance(exception, MarkdownParseError):
        return _markdown_parse_to_errors(exception)
    if isinstance(exception, SchemaValidationError):
        return _schema_validation_to_errors(exception)
    if isinstance(exception, FileNotFoundError):
        return str(exception), [{"message": str(exception), "category": "file_not_found"}]
    if isinstance(exception, PermissionError):
        return str(exception), [{"message": str(exception), "category": "permission_denied"}]

    return str(exception), [{"message": str(exception), "category": "unknown"}]


def _workflow_validation_to_errors(
    exception: Any,
) -> tuple[str, list[dict[str, Any]]]:
    """Convert WorkflowValidationError to unified errors."""
    errors: list[dict[str, Any]] = []
    for err in exception.validation_errors:
        if isinstance(err, tuple):
            msg, path, suggestion = err
            entry: dict[str, Any] = {"message": msg, "category": "validation"}
            if path and path != "root":
                entry["path"] = path
            if suggestion:
                entry["suggestion"] = suggestion
            errors.append(entry)
        else:
            errors.append({"message": str(err), "category": "validation"})
    return exception.summary, errors if errors else [{"message": str(exception), "category": "validation"}]


def _workflow_not_found_to_errors(exception: Any) -> tuple[str, list[dict[str, Any]]]:
    """Convert WorkflowNotFoundError to unified errors."""
    entry: dict[str, Any] = {"message": str(exception), "category": "not_found"}
    if exception.similar_names:
        entry["suggestion"] = f"Did you mean: {', '.join(exception.similar_names)}"
    return str(exception), [entry]


def _mcp_error_to_errors(exception: Any) -> tuple[str, list[dict[str, Any]]]:
    """Convert MCPError to unified errors."""
    entry: dict[str, Any] = {"message": exception.explanation, "category": "mcp"}
    if exception.suggestions:
        entry["suggestion"] = "; ".join(exception.suggestions)
    return exception.title, [entry]


def _output_resolution_to_errors(exception: Any) -> tuple[str, list[dict[str, Any]]]:
    """Convert OutputResolutionError to unified errors."""
    errors: list[dict[str, Any]] = []
    for failure in exception.failures:
        diag = failure.get("diagnostics", [])
        msg = "; ".join(diag) if diag else str(exception)
        entry: dict[str, Any] = {"message": msg, "category": "runtime"}
        if failure.get("output_name"):
            entry["output_name"] = failure["output_name"]
        if failure.get("source_expr"):
            entry["source_expr"] = failure["source_expr"]
        errors.append(entry)
    if not errors:
        errors = [{"message": exception.explanation, "category": "runtime"}]
    return exception.title, errors


def _user_friendly_to_errors(exception: Any) -> tuple[str, list[dict[str, Any]]]:
    """Convert generic UserFriendlyError to unified errors."""
    entry: dict[str, Any] = {"message": exception.explanation, "category": "cli"}
    if exception.suggestions:
        entry["suggestion"] = "; ".join(exception.suggestions)
    return exception.title, [entry]


def _markdown_parse_to_errors(exception: Any) -> tuple[str, list[dict[str, Any]]]:
    """Convert MarkdownParseError to unified errors."""
    entry: dict[str, Any] = {"message": str(exception), "category": "parse_error"}
    if exception.line is not None:
        entry["line"] = exception.line
    if exception.suggestion:
        entry["suggestion"] = exception.suggestion
    return str(exception), [entry]


def _schema_validation_to_errors(exception: Any) -> tuple[str, list[dict[str, Any]]]:
    """Convert IR schema ValidationError to unified errors."""
    entry: dict[str, Any] = {"message": exception.message, "category": "validation"}
    if exception.path:
        entry["path"] = exception.path
    if exception.suggestion:
        entry["suggestion"] = exception.suggestion
    return str(exception), [entry]


def display_exception_text(exception: Exception, verbose: bool = False) -> None:
    """Display exception in text mode, preserving rich formatting.

    Uses format_for_cli() when available, falls back to generic display.
    """
    if isinstance(exception, UserFriendlyError):
        click.echo(exception.format_for_cli(verbose), err=True)
    elif isinstance(exception, (WorkflowNotFoundError, WorkflowValidationError)) or hasattr(
        exception, "format_for_cli"
    ):
        click.echo(exception.format_for_cli(), err=True)
    elif isinstance(exception, PermissionError):
        msg = str(exception) if str(exception) else "Permission denied"
        click.echo(f"\u2717 {msg}", err=True)
    elif isinstance(exception, (FileNotFoundError, MarkdownParseError)):
        click.echo(f"\u2717 {exception}", err=True)
    elif isinstance(exception, UnicodeDecodeError):
        click.echo("\u2717 File must be valid UTF-8 text.", err=True)
    elif isinstance(exception, RuntimeError) and "registry" in str(exception).lower():
        click.echo(f"cli: Error - Failed to load registry: {exception}", err=True)
        click.echo("cli: Try 'pflow registry list' to see available nodes.", err=True)
        click.echo("cli: Or 'pflow registry scan <path>' to add custom nodes.", err=True)
    else:
        click.echo(f"cli: Workflow execution failed - {exception}", err=True)


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
