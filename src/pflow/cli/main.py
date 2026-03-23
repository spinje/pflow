"""Main CLI entry point for pflow."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import warnings
from pathlib import Path
from typing import Any, NoReturn, cast

import click

from pflow.cli.mcp_sync import _auto_discover_mcp_servers
from pflow.cli.param_parsing import parse_workflow_params
from pflow.cli.workflow_errors import (
    _build_json_error_response,
    _create_json_error_output,
    _display_text_error_details,
    _format_compilation_error_text,
    _handle_compilation_error_json,
)
from pflow.cli.workflow_output import (
    _create_workflow_metadata,
    _handle_workflow_output,
    _serialize_json_result,
)
from pflow.cli.workflow_resolution import (
    find_similar_workflows,
    is_likely_workflow_name,
    resolve_workflow,
)
from pflow.core import StdinData
from pflow.core.output_controller import OutputController
from pflow.core.shell_integration import (
    read_stdin as read_stdin_content,
)
from pflow.core.shell_integration import (
    read_stdin_enhanced,
)
from pflow.core.validation_utils import is_valid_parameter_name
from pflow.core.workflow.manager import WorkflowManager
from pflow.execution import DisplayManager, ExecutionResult
from pflow.runtime.compilation import display_validation_warnings

# Import MCP CLI commands

logger = logging.getLogger(__name__)


# NOTE: Logging configuration moved to logging_config.py
# It's now configured centrally in main_wrapper.py before any command routing.
# This ensures all command groups (workflow, registry, mcp, etc.) respect the verbose flag.


def handle_sigint(signum: int, frame: object) -> None:
    """Handle Ctrl+C gracefully."""
    click.echo("\ncli: Interrupted by user", err=True)
    sys.exit(130)  # Standard Unix exit code for SIGINT


def _get_output_controller(ctx: click.Context) -> OutputController:
    """Get the OutputController from context, creating it if needed.

    Args:
        ctx: Click context

    Returns:
        OutputController instance
    """
    if ctx.obj and "output_controller" in ctx.obj:
        return cast(OutputController, ctx.obj["output_controller"])

    # Fallback: create one if not in context (shouldn't happen normally)
    return OutputController(
        print_flag=ctx.obj.get("print_flag", False) if ctx.obj else False,
        output_format=ctx.obj.get("output_format", "text") if ctx.obj else "text",
    )


def _echo_trace(ctx: click.Context, message: str) -> None:
    """Output trace file location message.

    Shown in all modes EXCEPT:
    - -p (print) mode: user explicitly wants only raw output
    - JSON output mode: structured output only

    Trace files are valuable for debugging in non-interactive contexts
    like CI/CD, agents, and scripts.

    Args:
        ctx: Click context
        message: Trace message to display
    """
    output_controller = _get_output_controller(ctx)
    # Suppress in -p (print) or JSON modes - user wants only structured output
    if output_controller.print_flag or output_controller.output_format == "json":
        return
    click.echo(message, err=True)


def _read_stdin_data() -> tuple[str | None, StdinData | None]:
    """Read stdin data, trying text first then enhanced.

    Returns:
        Tuple of (text_content, enhanced_stdin)
    """
    # For backward compatibility, try simple text reading first
    stdin_content = read_stdin_content()

    # Only try enhanced reading if simple reading failed (binary/large data)
    enhanced_stdin = None
    if stdin_content is None:  # Only when actually None, not empty string
        enhanced_stdin = read_stdin_enhanced()

    return stdin_content, enhanced_stdin


def _cleanup_temp_files(stdin_data: str | StdinData | None, verbose: bool) -> None:
    """Clean up temporary files if any."""
    if isinstance(stdin_data, StdinData) and stdin_data.is_temp_file and stdin_data.temp_path is not None:
        try:
            import os

            os.unlink(stdin_data.temp_path)
            if verbose:
                click.echo(f"cli: Cleaned up temp file: {stdin_data.temp_path}")
        except OSError:
            # Log warning but don't fail
            if verbose:
                click.echo(f"cli: Warning - could not clean up temp file: {stdin_data.temp_path}", err=True)


def _prepare_execution_environment(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_format: str,
    verbose: bool,
    execution_params: dict[str, Any] | None,
    seeded_llm_calls: list[dict[str, Any]] | None,
    cache_chunks: list[dict[str, Any]] | None = None,
) -> tuple[Any, Any, Any, dict[str, Any], bool]:
    """Prepare the execution environment for workflow execution.

    Returns:
        Tuple of (cli_output, display, workflow_trace, enhanced_params, effective_verbose)
    """
    from pflow.cli.cli_output import CliOutput

    # Extract context values
    print_flag = ctx.obj.get("print_flag", False)

    # Determine effective verbose flag for nodes
    # MCP server output should only show when -v is set AND not in print mode or JSON output
    effective_verbose = verbose and not print_flag and output_format != "json"

    # Create output interface
    cli_output = CliOutput(
        output_controller=_get_output_controller(ctx),
        verbose=verbose,
        output_format=output_format,
    )

    # Create display manager
    display = DisplayManager(output=cli_output)

    # Get workflow trace if requested
    workflow_trace = None
    if ctx.obj.get("trace", False):
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        workflow_trace = WorkflowTraceCollector(ctx.obj.get("workflow_name", "workflow"))
        ctx.obj["workflow_trace"] = workflow_trace

    # Prepare execution params with verbose flag and LLM calls
    enhanced_params = execution_params or {}
    enhanced_params["__verbose__"] = effective_verbose
    if seeded_llm_calls:
        enhanced_params["__llm_calls__"] = seeded_llm_calls
    if cache_chunks:
        enhanced_params["__cache_chunks__"] = cache_chunks

    # Set workflow file path for relative path resolution in nested workflows
    source_file_path = ctx.obj.get("source_file_path")
    if source_file_path:
        enhanced_params["_pflow_workflow_file"] = str(Path(source_file_path).resolve())

    return cli_output, display, workflow_trace, enhanced_params, effective_verbose


def _handle_compilation_error(
    ctx: click.Context,
    error: Exception,
    output_format: str,
    verbose: bool,
    workflow_trace: Any | None,
    metrics_collector: Any | None,
) -> None:
    """Handle compilation errors specially.

    Args:
        ctx: Click context
        error: Compilation error
        output_format: Output format (json or text)
        verbose: Verbose flag
        workflow_trace: Optional workflow trace
        metrics_collector: Optional metrics collector
    """
    if output_format == "json":
        _handle_compilation_error_json(ctx, error, metrics_collector)
    else:
        _format_compilation_error_text(error, verbose)

    ctx.exit(1)


def _handle_workflow_error(
    ctx: click.Context,
    result: Any,  # ExecutionResult
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
    ir_data: dict[str, Any] | None = None,
) -> None:
    """Handle workflow execution error with rich error context."""
    # Display rich error details
    if output_format == "json":
        # JSON mode: Include structured errors
        error_output = _build_json_error_response(result, metrics_collector, shared_storage, ir_data)
        _serialize_json_result(error_output, verbose)
    else:
        # Text mode: Show detailed rich error context
        _display_text_error_details(result, verbose=verbose)

    ctx.exit(1)


def _handle_workflow_success(
    ctx: click.Context,
    result: Any,  # ExecutionResult
    workflow_trace: Any | None,
    shared_storage: dict[str, Any],
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
) -> None:
    """Handle successful workflow execution."""
    if verbose and output_format != "json":
        click.echo("cli: Workflow execution completed")

    # Check for output from shared store (now with metrics)
    # NOTE: We handle output BEFORE saving trace so the JSON output can be included in the trace
    print_flag = ctx.obj.get("print_flag", False)
    workflow_metadata = ctx.obj.get("workflow_metadata")

    # Extract status and warnings from ExecutionResult (Phase 2-5 integration)
    status = getattr(result, "status", None)
    result_warnings = getattr(result, "warnings", [])

    output_produced = _handle_workflow_output(
        shared_storage,
        output_key,
        ir_data,
        verbose,
        output_format,
        metrics_collector=metrics_collector,
        print_flag=print_flag,
        workflow_metadata=workflow_metadata,
        workflow_trace=workflow_trace,
        output_controller=ctx.obj.get("output_controller"),
        status=status,
        warnings=result_warnings,
    )

    # Only show success message if we didn't produce output
    # Use status from result if available
    if not output_produced:
        status = getattr(result, "status", None)
        if status and hasattr(status, "value"):
            status_str = status.value
            if status_str == "degraded":
                click.echo("⚠️ Workflow completed with warnings")
            elif status_str == "failed":
                click.echo("❌ Workflow execution failed")
            else:
                click.echo("Workflow executed successfully")
        else:
            click.echo("Workflow executed successfully")


def _execute_workflow_and_handle_result(
    ctx: click.Context,
    result: ExecutionResult,  # NEW: Accept ExecutionResult
    shared_storage: dict[str, Any],
    workflow_trace: Any | None,
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
    display: DisplayManager,  # NEW: Accept DisplayManager
) -> None:
    """Intermediate function that routes to appropriate handlers.

    This MUST be preserved for compatibility.

    Args:
        ctx: Click context
        result: ExecutionResult from workflow execution
        shared_storage: Shared storage dictionary after execution
        workflow_trace: Optional workflow trace
        output_key: Optional output key
        ir_data: Workflow IR data
        output_format: Output format
        metrics_collector: Optional metrics collector
        verbose: Verbose flag
        display: DisplayManager for output
    """

    # Note: Display output is handled by the handlers below, not here
    # This preserves the existing behavior where output format and
    # interactive mode determine what gets displayed

    # Clean up LLM interception after successful run
    if workflow_trace and hasattr(workflow_trace, "cleanup_llm_interception"):
        workflow_trace.cleanup_llm_interception()

    # Route based on result to display output data
    if result.success:
        _handle_workflow_success(
            ctx=ctx,
            result=result,
            workflow_trace=workflow_trace,
            shared_storage=shared_storage,
            output_key=output_key,
            ir_data=ir_data,
            output_format=output_format,
            metrics_collector=metrics_collector,
            verbose=verbose,
        )
    else:
        _handle_workflow_error(
            ctx=ctx,
            result=result,
            workflow_trace=workflow_trace,
            output_format=output_format,
            metrics_collector=metrics_collector,
            shared_storage=shared_storage,
            verbose=verbose,
            ir_data=ir_data,
        )


def _cleanup_workflow_resources(
    workflow_trace: Any | None,
    stdin_data: str | StdinData | None,
    verbose: bool,
) -> None:
    """Clean up workflow resources with robust error handling.

    Args:
        workflow_trace: Optional workflow trace collector
        stdin_data: Optional stdin data that may have temp files
        verbose: Whether to show verbose output
    """
    cleanup_errors = []

    # Ensure LLM interception is cleaned up
    if workflow_trace:
        try:
            if hasattr(workflow_trace, "cleanup_llm_interception"):
                workflow_trace.cleanup_llm_interception()
                if verbose:
                    logger.debug("LLM interception cleaned up successfully")
            else:
                logger.warning(
                    f"WorkflowTrace object missing cleanup_llm_interception method: {type(workflow_trace).__name__}"
                )
        except Exception as e:
            cleanup_errors.append(f"LLM cleanup failed: {e}")
            logger.error(f"Failed to cleanup LLM interception: {e}", exc_info=True)

    # Clean up temp files
    try:
        _cleanup_temp_files(stdin_data, verbose)
        if verbose and stdin_data:
            logger.debug("Temporary files cleaned up successfully")
    except Exception as e:
        cleanup_errors.append(f"Temp file cleanup failed: {e}")
        logger.error(f"Failed to cleanup temp files: {e}", exc_info=True)

    # Report any cleanup failures to user in verbose mode
    if cleanup_errors and verbose:
        click.echo("⚠️  Some cleanup operations failed:", err=True)
        for error in cleanup_errors:
            click.echo(f"   - {error}", err=True)


def _handle_workflow_exception(
    ctx: click.Context,
    e: Exception,
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
) -> None:
    """Handle exceptions during workflow execution with proper cleanup.

    Args:
        ctx: Click context
        e: The exception that occurred
        workflow_trace: Optional workflow trace collector
        output_format: Output format - "text" or "json"
        metrics_collector: Optional metrics collector
        shared_storage: Shared storage dictionary
        verbose: Whether to show verbose output
    """
    # Only show traceback if verbose mode enabled
    if verbose:
        logger.error(f"Workflow execution failed: {e}", exc_info=True)
    else:
        logger.error(f"Workflow execution failed: {e}")

    # Clean up LLM interception on error - robust handling
    if workflow_trace:
        try:
            if hasattr(workflow_trace, "cleanup_llm_interception"):
                workflow_trace.cleanup_llm_interception()
                logger.debug("LLM interception cleaned up after error")
            else:
                logger.warning("WorkflowTrace missing cleanup method during exception handling")
        except Exception as cleanup_error:
            logger.error(f"Failed to cleanup during exception: {cleanup_error}", exc_info=True)

    # Check if this is a user-friendly error
    from pflow.core.user_errors import UserFriendlyError

    # In JSON mode, output error as JSON
    if output_format == "json":
        # Get workflow metadata from context if available
        workflow_metadata = ctx.obj.get("workflow_metadata")
        error_output = _create_json_error_output(e, metrics_collector, shared_storage, workflow_metadata)
        _serialize_json_result(error_output, verbose)
    else:
        # Format error based on type
        if isinstance(e, UserFriendlyError):
            # Use the formatted user-friendly error
            error_message = e.format_for_cli(verbose=verbose)
            click.echo(error_message, err=True)
        else:
            # Check if this is a registry load error
            error_str = str(e)
            if isinstance(e, RuntimeError) and "registry" in error_str.lower():
                click.echo(f"cli: Error - Failed to load registry: {e}", err=True)
                click.echo("cli: Try 'pflow registry list' to see available nodes.", err=True)
                click.echo("cli: Or 'pflow registry scan <path>' to add custom nodes.", err=True)
            else:
                # Fallback to generic error message
                click.echo(f"cli: Workflow execution failed - {e}", err=True)
                click.echo("cli: This may indicate a bug in the workflow or nodes", err=True)

    ctx.exit(1)


def _setup_execution_context(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
) -> tuple[bool, Any | None]:
    """Setup execution context and return configuration values.

    Args:
        ctx: Click context
        ir_data: Workflow IR data
        output_format: Output format
        metrics_collector: Optional metrics collector

    Returns:
        Tuple of (verbose, metrics_collector)
    """
    verbose = ctx.obj.get("verbose", False)

    # Set up metrics collector if not provided (for both text and JSON mode)
    if not metrics_collector:
        from pflow.core.metrics import MetricsCollector

        metrics_collector = MetricsCollector()

    # Note: Validation now happens after _prepare_execution_environment()
    # with real enhanced_params, in execute_json_workflow()

    return verbose, metrics_collector


def _perform_validation(
    ir_data: dict[str, Any],
    output_format: str,
) -> tuple[list[str], list[Any]]:
    """Perform static workflow validation.

    Args:
        ir_data: Workflow IR data
        output_format: Output format for error display

    Returns:
        Tuple of (errors, warnings):
        - errors: List of validation errors (empty if valid)
        - warnings: List of ValidationWarning objects

    Raises:
        SystemExit: If validation raises an exception
    """
    from pflow.core.workflow.validator import WorkflowValidator
    from pflow.registry.registry import Registry

    registry = Registry()

    # Generate dummy values for declared inputs to enable structural template validation
    dummy_params = {}
    declared_inputs = ir_data.get("inputs", {})
    for input_name in declared_inputs:
        dummy_params[input_name] = "__validation_placeholder__"

    try:
        errors, warnings = WorkflowValidator.validate(
            workflow_ir=ir_data,
            extracted_params=dummy_params,  # Dummy values enable structural validation
            registry=registry,  # Pass Registry object, not metadata dict
            skip_node_types=False,
        )
    except Exception as e:
        if output_format == "json":
            click.echo(json.dumps({"success": False, "error": f"Validation error: {e}"}))
        else:
            click.echo(f"✗ Validation error: {e}", err=True)
        import sys

        sys.exit(1)

    return (errors, warnings)


def _display_validation_results(
    errors: list[str],
    warnings: list[Any],
    output_format: str,
) -> None:
    """Display validation results and exit.

    Args:
        errors: List of validation errors (empty if valid)
        warnings: List of ValidationWarning objects
        output_format: Output format (text or json)

    Note:
        This function calls sys.exit() and never returns
    """
    import sys

    # Use shared formatter for validation display
    from pflow.execution.formatters.validation_formatter import (
        format_validation_failure,
        format_validation_success,
    )

    if not errors:
        if output_format == "json":
            click.echo(json.dumps({"success": True, "message": "Workflow structure is valid"}))
        else:
            # Use formatter for success display
            success_text = format_validation_success()
            click.echo(success_text)

            # Display warnings if present (complex, CLI-specific)
            if warnings:
                display_validation_warnings(warnings)
        sys.exit(0)
    else:
        # Display validation errors
        if output_format == "json":
            click.echo(json.dumps({"success": False, "errors": errors}))
        else:
            # Use formatter for error display (auto-generates suggestions)
            error_text = format_validation_failure(errors)
            click.echo(error_text, err=True)
        sys.exit(1)


def _handle_validate_only_mode(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_format: str,
) -> None:
    """Handle --validate-only flag by performing static validation and exiting.

    Args:
        ctx: Click context
        ir_data: Workflow IR data (will be normalized in-place)
        output_format: Output format (text or json)

    Note:
        This function calls sys.exit() and never returns
    """
    if output_format != "json":
        click.echo("Validating workflow (static validation)...")

    # Note: Normalization already happened in _try_load_workflow_from_file()
    # No need to normalize again here

    # Resolve external file references before validation
    _resolve_file_refs_or_exit(ctx, ir_data, output_format)

    # Perform static validation
    errors, warnings = _perform_validation(ir_data, output_format)

    # Display results and exit
    _display_validation_results(errors, warnings, output_format)


def _resolve_file_refs_or_exit(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_format: str,
) -> None:
    """Resolve external file references in workflow IR before validation/execution."""
    import yaml

    from pflow.core.file_resolver import resolve_file_references

    source_file = ctx.obj.get("source_file_path")
    if source_file:
        base_dir = Path(source_file).resolve().parent
        try:
            resolve_file_references(ir_data, base_dir)
        except (FileNotFoundError, yaml.YAMLError) as e:
            if output_format == "json":
                click.echo(json.dumps({"success": False, "error": str(e)}))
            else:
                click.echo(f"✗ {e}", err=True)
            ctx.exit(1)


def _validate_before_execution(
    ctx: click.Context,
    ir_data: dict[str, Any],
    execution_params: dict[str, Any],
    output_format: str,
    verbose: bool,
) -> None:
    """Validate workflow before execution using full WorkflowValidator.

    This uses real execution params (not dummy) for complete template validation.
    Exits on validation failure.

    Args:
        ctx: Click context
        ir_data: Workflow IR data
        execution_params: Real execution parameters for template validation
        output_format: Output format (text or json)
        verbose: Verbose flag
    """
    from pflow.core.workflow.validator import WorkflowValidator
    from pflow.execution.formatters.validation_formatter import format_validation_failure
    from pflow.registry.registry import Registry

    registry = Registry()

    errors, warnings = WorkflowValidator.validate(
        workflow_ir=ir_data,
        extracted_params=execution_params,  # Real params for full validation
        registry=registry,
        skip_node_types=False,
    )

    if errors:
        if output_format == "json":
            workflow_metadata = ctx.obj.get("workflow_metadata")
            error_output: dict[str, Any] = {
                "success": False,
                "error": "Workflow validation failed",
                "validation_errors": errors,
            }
            if workflow_metadata:
                error_output["metadata"] = workflow_metadata
            # Note: Not including metrics since validation fails before execution starts
            click.echo(json.dumps(error_output, indent=2 if verbose else None))
        else:
            click.echo(format_validation_failure(errors), err=True)
        ctx.exit(1)

    # Warnings are non-blocking, just display them in verbose mode
    if warnings and output_format != "json" and verbose:
        for warning in warnings:
            click.echo(f"⚠️  {warning}", err=True)


def _save_trace_and_report(ctx: click.Context, workflow_trace: Any | None) -> None:
    """Save trace to file and generate report if requested.

    Called from the finally block — survives Ctrl+C (SystemExit triggers finally).
    """
    if not workflow_trace:
        return
    try:
        trace_file = workflow_trace.save_to_file()
        if trace_file:
            _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")
            report = ctx.obj.get("report")
            if report:
                from pflow.core.trace_report import generate_report

                report_dir = generate_report(trace_file, report)
                if report_dir:
                    _echo_trace(ctx, f"📋 Execution report: {report_dir}")
    except Exception as trace_err:
        logger.error(f"Failed to save trace: {trace_err}", exc_info=True)


def execute_json_workflow(
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    seeded_llm_calls: list[dict[str, Any]] | None = None,
    output_format: str = "text",
    metrics_collector: Any | None = None,
    cache_chunks: list[dict[str, Any]] | None = None,
) -> None:
    """Thin CLI wrapper for workflow execution.

    All logic delegated to WorkflowExecutorService.
    """
    from pflow.core.workflow.manager import WorkflowManager
    from pflow.execution.workflow_execution import execute_workflow

    # Setup execution context
    verbose, metrics_collector = _setup_execution_context(ctx, ir_data, output_format, metrics_collector)

    # Suppress logging in JSON mode (except CRITICAL) to keep output clean
    if output_format == "json":
        logging.getLogger().setLevel(logging.CRITICAL)

    # Check for validate-only flag
    validate_only = ctx.obj.get("validate_only", False)
    if validate_only:
        _handle_validate_only_mode(ctx, ir_data, output_format)
        # Never reaches here - _handle_validate_only_mode calls ctx.exit()

    # Extract additional context values
    workflow_name = ctx.obj.get("workflow_name")

    # Prepare execution environment
    cli_output, display, workflow_trace, enhanced_params, effective_verbose = _prepare_execution_environment(
        ctx, ir_data, output_format, verbose, execution_params, seeded_llm_calls, cache_chunks
    )

    _resolve_file_refs_or_exit(ctx, ir_data, output_format)
    _validate_before_execution(ctx, ir_data, enhanced_params, output_format, verbose)

    # Show execution starting
    node_count = len(ir_data.get("nodes", []))
    if verbose and output_format != "json":
        click.echo(f"cli: Starting workflow execution with {node_count} node(s)")
    display.show_execution_start(node_count)

    # Hide PocketFlow warnings in non-verbose mode
    if not verbose:
        warnings.filterwarnings("ignore", message="Flow ends:*", module="pflow.pocketflow")

    try:
        # Execute workflow with unified function
        result = execute_workflow(
            workflow_ir=ir_data,
            execution_params=enhanced_params,
            output=cli_output,
            workflow_manager=WorkflowManager() if ctx.obj.get("workflow_source") == "saved" else None,
            workflow_name=workflow_name,
            stdin_data=stdin_data,
            output_key=output_key,
            metrics_collector=metrics_collector,
            trace_collector=workflow_trace,
        )

        # Handle result
        _execute_workflow_and_handle_result(
            ctx=ctx,
            result=result,
            shared_storage=result.shared_after,
            workflow_trace=workflow_trace,
            output_key=output_key,
            ir_data=ir_data,
            output_format=output_format,
            metrics_collector=metrics_collector,
            verbose=verbose,
            display=display,
        )

    except Exception as e:
        from pflow.runtime import CompilationError

        # Re-raise Click exceptions (Exit, Abort) - don't handle them
        if isinstance(e, click.exceptions.Exit):
            raise

        # Handle compilation errors specially
        if isinstance(e, CompilationError):
            _handle_compilation_error(ctx, e, output_format, verbose, workflow_trace, metrics_collector)

        # Handle other exceptions
        _handle_workflow_exception(
            ctx,
            e,
            workflow_trace,
            output_format,
            metrics_collector,
            result.shared_after if "result" in locals() else {},
            verbose,
        )

    finally:
        _save_trace_and_report(ctx, workflow_trace)
        _cleanup_workflow_resources(workflow_trace, stdin_data, verbose)


def _setup_signals() -> None:
    """Setup signal handlers for the application."""
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, handle_sigint)

    # Handle broken pipe gracefully
    # NOTE: Using SIG_IGN instead of SIG_DFL to prevent subprocess SIGPIPE from killing
    # the parent process. When a subprocess doesn't consume all stdin (e.g., shell command
    # that uses 'echo' instead of reading from pipe), SIG_DFL would terminate Python with
    # exit code 141. SIG_IGN allows subprocess.run() to handle this gracefully.
    # See: https://github.com/spinje/pflow/issues/25
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)


def _initialize_context(
    ctx: click.Context,
    verbose: bool,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    trace_enabled: bool,
    validate_only: bool,
) -> None:
    """Initialize the click context with configuration.

    Args:
        ctx: Click context to initialize
        verbose: Verbose mode flag
        output_key: Optional output key
        output_format: Output format (text/json)
        print_flag: Force non-interactive output flag
        trace_enabled: Trace execution flag (enabled by default)
        validate_only: Validate workflow without executing
    """
    if ctx.obj is None:
        ctx.obj = {}

    ctx.obj["verbose"] = verbose
    ctx.obj["output_key"] = output_key
    ctx.obj["output_format"] = output_format
    ctx.obj["print_flag"] = print_flag
    ctx.obj["trace"] = trace_enabled
    ctx.obj["validate_only"] = validate_only

    # Create OutputController once and store it for reuse
    ctx.obj["output_controller"] = OutputController(
        print_flag=print_flag,
        output_format=output_format,
    )


def _preprocess_run_prefix(ctx: click.Context, workflow: tuple[str, ...]) -> tuple[str, ...]:
    """Handle a leading 'run' token for UX compatibility.

    Returns the possibly modified workflow tuple. Exits on 'run' alone.
    """
    if workflow and workflow[0] == "run":
        if len(workflow) == 1:
            click.echo("cli: Need to specify what to run.", err=True)
            click.echo("cli: Usage: pflow <workflow-name>", err=True)
            click.echo("cli: List workflows: pflow workflow list", err=True)
            ctx.exit(1)
        return tuple(workflow[1:])
    return workflow


def _validate_workflow_flags(workflow: tuple[str, ...], ctx: click.Context) -> None:
    """Validate that CLI flags are not misplaced in workflow arguments.

    Args:
        workflow: Workflow arguments tuple
        ctx: Click context

    Raises:
        SystemExit: If misplaced flags are found
    """
    misplaced_flags = [
        arg for arg in workflow if arg in ("--no-trace", "--verbose", "-v", "--output-key", "-o", "--output-format")
    ]
    if misplaced_flags:
        click.echo("cli: Error - CLI flags must come BEFORE the workflow text", err=True)
        click.echo(f"cli: Found misplaced flags: {', '.join(misplaced_flags)}", err=True)
        click.echo("cli: Correct usage examples:", err=True)
        click.echo('cli:   pflow --verbose "analyze this data"', err=True)
        click.echo('cli:   pflow --no-trace "run without tracing"', err=True)
        click.echo('cli: NOT: pflow "create a story" --no-trace', err=True)
        ctx.exit(1)


def _find_stdin_input(workflow_ir: dict[str, Any]) -> str | None:
    """Find the input marked with stdin: true.

    Args:
        workflow_ir: Workflow IR data

    Returns:
        Name of input with stdin: true, or None if no such input exists
    """
    inputs: dict[str, Any] = workflow_ir.get("inputs", {})
    for name, spec in inputs.items():
        if isinstance(spec, dict) and spec.get("stdin") is True:
            return str(name)
    return None


def _extract_stdin_text(stdin_data: str | StdinData | None) -> str | None:
    """Extract text content from stdin data.

    Args:
        stdin_data: Stdin data (string, StdinData, or None)

    Returns:
        Text content if available, None otherwise (for binary/large file/None cases)
    """
    if stdin_data is None:
        return None
    if isinstance(stdin_data, str):
        return stdin_data
    # StdinData object - only extract text_data, not binary or temp file
    if stdin_data.text_data is not None:
        return stdin_data.text_data
    # Binary data or temp file path - do not route
    return None


def _show_stdin_routing_error(ctx: click.Context) -> NoReturn:
    """Display error when stdin cannot be routed to workflow.

    Args:
        ctx: Click context (for exit and output_format)

    Raises:
        SystemExit: Always exits with code 1
    """
    output_format = ctx.obj.get("output_format", "text")
    verbose = ctx.obj.get("verbose", False)

    if output_format == "json":
        workflow_metadata = ctx.obj.get("workflow_metadata")
        error_output: dict[str, Any] = {
            "success": False,
            "error": "Piped input cannot be routed to workflow",
            "validation_errors": [
                'This workflow has no input marked with "stdin": true. '
                'To accept piped data, add "stdin": true to one input declaration.'
            ],
        }
        if workflow_metadata:
            error_output["metadata"] = workflow_metadata
        click.echo(json.dumps(error_output, indent=2 if verbose else None))
    else:
        click.echo("❌ Piped input cannot be routed to workflow", err=True)
        click.echo("", err=True)
        click.echo('   This workflow has no input marked with "stdin": true.', err=True)
        click.echo('   To accept piped data, add "stdin": true to one input declaration.', err=True)
        click.echo("", err=True)
        click.echo("   Example (.pflow.md format):", err=True)
        click.echo("     ### data", err=True)
        click.echo("", err=True)
        click.echo("     Input data piped via stdin.", err=True)
        click.echo("", err=True)
        click.echo("     - type: string", err=True)
        click.echo("     - required: true", err=True)
        click.echo("     - stdin: true", err=True)
        click.echo("", err=True)
        click.echo('   👉 Add "stdin": true to the input that should receive piped data', err=True)
    ctx.exit(1)


def _output_validation_errors(
    ctx: click.Context,
    errors: list[tuple[str, str, str]],
    error_summary: str = "Validation failed",
) -> NoReturn:
    """Output validation errors respecting output_format.

    Args:
        ctx: Click context (for output_format, verbose, workflow_metadata)
        errors: List of (message, path, suggestion) tuples from prepare_inputs()
        error_summary: High-level error description for JSON mode

    Raises:
        SystemExit: Always exits with code 1
    """
    output_format = ctx.obj.get("output_format", "text")
    verbose = ctx.obj.get("verbose", False)

    if output_format == "json":
        workflow_metadata = ctx.obj.get("workflow_metadata")
        # Convert tuple errors to structured format
        validation_errors = []
        for msg, path, suggestion in errors:
            error_entry: dict[str, str] = {"message": msg}
            if path and path != "root":
                error_entry["path"] = path
            if suggestion:
                error_entry["suggestion"] = suggestion
            validation_errors.append(error_entry)

        error_output: dict[str, Any] = {
            "success": False,
            "error": error_summary,
            "validation_errors": validation_errors,
        }
        if workflow_metadata:
            error_output["metadata"] = workflow_metadata
        click.echo(json.dumps(error_output, indent=2 if verbose else None))
    else:
        for msg, path, suggestion in errors:
            click.echo(f"❌ {msg}", err=True)
            if path and path != "root":
                click.echo(f"   At: {path}", err=True)
            if suggestion:
                click.echo(f"   👉 {suggestion}", err=True)
    ctx.exit(1)


def _route_stdin_to_params(
    ctx: click.Context,
    stdin_data: str | StdinData | None,
    workflow_ir: dict[str, Any],
    params: dict[str, Any],
) -> None:
    """Route stdin content to the appropriate workflow input parameter.

    Args:
        ctx: Click context (for exit on error)
        stdin_data: Stdin data (string, StdinData, or None)
        workflow_ir: Workflow IR data
        params: Parameters dict to modify in place

    Side Effects:
        Modifies params dict if stdin should be routed.
        Calls ctx.exit(1) if stdin is piped but no target input exists.
    """
    stdin_text = _extract_stdin_text(stdin_data)
    if stdin_text is None:
        # Check if stdin was binary/large file (detected but not routable)
        if isinstance(stdin_data, StdinData) and (stdin_data.binary_data or stdin_data.temp_path):
            click.echo("⚠️  Stdin contains binary or large data", err=True)
            click.echo("   Binary/large data is not automatically routed to workflow inputs.", err=True)
            click.echo("   Consider using a file path parameter instead.", err=True)
            click.echo("", err=True)
        return

    # Stdin has text content - try to route it
    target_input = _find_stdin_input(workflow_ir)

    if target_input is None:
        # No stdin: true input - error if stdin is piped
        _show_stdin_routing_error(ctx)

    # Route stdin to target input (unless CLI override exists)
    if target_input not in params:
        params[target_input] = stdin_text


def _load_settings_env() -> dict[str, str]:
    """Load environment variables from settings.

    Returns:
        Dict of environment variables from settings, empty dict on error
    """
    try:
        from pflow.core.settings import SettingsManager

        manager = SettingsManager()
        settings = manager.load()
        return settings.env
    except Exception as e:
        # Non-fatal - continue with empty settings
        logger.warning(f"Failed to load settings.env: {e}")
        return {}


def _validate_and_prepare_workflow_params(
    ctx: click.Context,
    workflow_ir: dict[str, Any],
    remaining_args: tuple[str, ...],
    stdin_data: str | StdinData | None = None,
) -> dict[str, Any]:
    """Validate workflow parameters, route stdin, and apply defaults.

    Args:
        ctx: Click context
        workflow_ir: Workflow IR data
        remaining_args: Command line arguments for parameters
        stdin_data: Optional stdin data (string, StdinData, or None)

    Returns:
        Validated and prepared parameters dictionary

    Raises:
        SystemExit: If validation errors occur (including stdin routing errors)
    """
    # Parse parameters
    params = parse_workflow_params(remaining_args)

    # Validate parameter keys (now more permissive than Python identifiers)
    invalid_keys = [k for k in params if not is_valid_parameter_name(k)]
    if invalid_keys:
        click.echo(f"❌ Invalid parameter name(s): {', '.join(invalid_keys)}", err=True)
        click.echo("   👉 Parameter names cannot contain shell special characters ($, |, >, <, &, ;, etc.)", err=True)
        ctx.exit(1)

    # Route stdin to workflow input marked with stdin: true
    _route_stdin_to_params(ctx, stdin_data, workflow_ir, params)

    # Skip input validation if --validate-only (handled separately with dummy values)
    validate_only = ctx.obj.get("validate_only", False)
    if not validate_only:
        from pflow.runtime.compilation import prepare_inputs

        settings_env = _load_settings_env()
        errors, defaults, env_param_names = prepare_inputs(workflow_ir, params, settings_env=settings_env)
        if errors:
            _output_validation_errors(ctx, errors, "Input validation failed")

        # Apply defaults
        if defaults:
            params.update(defaults)

        # Store env param names as internal param (for consistency with compiler.py)
        if env_param_names:
            params["__env_param_names__"] = list(env_param_names)

    return params


def _show_workflow_help(
    first_arg: str,
    workflow_ir: dict[str, Any],
    source: str | None,
) -> None:
    """Display workflow help information.

    Args:
        first_arg: First workflow argument (name or path)
        workflow_ir: Workflow IR data
        source: Workflow source ("saved", "file", etc.)
    """
    # Use shared formatter (same as workflow describe command)
    from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface

    # Build metadata structure expected by formatter
    name = os.path.basename(first_arg) if "/" in first_arg else first_arg
    metadata = {"ir": workflow_ir}

    # Add description if present
    if "description" in workflow_ir:
        metadata["description"] = workflow_ir["description"]

    # Display workflow information header
    click.echo(f"\nWorkflow: {name}")
    if source == "saved":
        click.echo("Source: Saved workflow")
    else:
        click.echo(f"Source: {first_arg}")
    click.echo()  # Empty line before formatted output

    # Use formatter for consistent display
    formatted = format_workflow_interface(name, metadata)
    click.echo(formatted)


def _setup_workflow_execution(
    ctx: click.Context,
    first_arg: str,
    source: str | None,
    output_format: str,
) -> Any | None:
    """Setup workflow execution context and metrics.

    Args:
        ctx: Click context
        first_arg: First workflow argument (name or path)
        source: Workflow source ("saved", "file", etc.)
        output_format: Output format

    Returns:
        Metrics collector if JSON output, otherwise None
    """
    # Create metrics collector if needed
    metrics_collector = None
    if output_format == "json":
        from pflow.core.metrics import MetricsCollector

        metrics_collector = MetricsCollector()

    # Set workflow metadata based on source
    # This ensures proper action field in JSON output
    if source == "saved":
        # Workflow from registry - it's being reused
        ctx.obj["workflow_metadata"] = _create_workflow_metadata(first_arg, "reused")
    else:
        # Workflow from file - it's unsaved
        ctx.obj["workflow_metadata"] = _create_workflow_metadata(first_arg, "unsaved")

    # Store workflow source and name for execution metadata
    ctx.obj["workflow_source"] = source

    if source == "file" and first_arg.endswith(".pflow.md"):
        ctx.obj["source_file_path"] = first_arg
        # Derive workflow name from filename for traces/display
        file_stem = Path(first_arg).stem
        ctx.obj["workflow_name"] = file_stem[:-6] if file_stem.endswith(".pflow") else file_stem
    elif source == "saved":
        # Extract clean workflow name (strip file extension if present)
        workflow_name = first_arg[:-9] if first_arg.lower().endswith(".pflow.md") else first_arg
        ctx.obj["workflow_name"] = workflow_name
        # Set source_file_path for saved workflows — needed for relative path
        # resolution in nested workflows (so ./child.pflow.md resolves from
        # the saved workflow's directory, not CWD)
        try:
            from pflow.core.workflow.manager import WorkflowManager

            wm = WorkflowManager()
            ctx.obj["source_file_path"] = wm.get_path(workflow_name)
        except Exception:
            logger.debug("Could not resolve saved workflow path for '%s'", workflow_name, exc_info=True)

    return metrics_collector


def _handle_named_workflow(
    ctx: click.Context,
    first_arg: str,
    remaining_args: tuple[str, ...],
    stdin_data: str | StdinData | None,
    output_key: str | None,
    output_format: str,
    verbose: bool,
    workflow_ir: dict[str, Any] | None = None,
    source: str | None = None,
) -> bool:
    """Handle execution of a named or file-based workflow.

    Args:
        ctx: Click context
        first_arg: First workflow argument (name or path)
        remaining_args: Remaining workflow arguments
        stdin_data: Optional stdin data
        output_key: Optional output key
        output_format: Output format
        verbose: Verbose mode flag

    Returns:
        True if workflow was executed, False otherwise
    """
    if workflow_ir is None and source != "parse_error":
        workflow_ir, source = resolve_workflow(first_arg)
    if not workflow_ir:
        return False

    # Check for --help request
    if remaining_args and "--help" in remaining_args:
        _show_workflow_help(first_arg, workflow_ir, source)
        return True

    # Validate and prepare parameters (including stdin routing)
    params = _validate_and_prepare_workflow_params(ctx, workflow_ir, remaining_args, stdin_data)

    # Store execution params for rerun hints (strip internal params)
    from .rerun_display import filter_user_params

    ctx.obj["execution_params"] = filter_user_params(params)

    # Show what we're doing if verbose (but not in JSON mode)
    if verbose and output_format != "json":
        if source == "saved":
            click.echo(f"cli: Loading workflow '{first_arg}' from registry")
        else:
            click.echo(f"cli: Loading workflow from file: {first_arg}")
        if params:
            click.echo(f"cli: With parameters: {params}")

    # Setup workflow execution context
    metrics_collector = _setup_workflow_execution(ctx, first_arg, source, output_format)

    # Execute workflow
    execute_json_workflow(ctx, workflow_ir, stdin_data, output_key, params, None, output_format, metrics_collector)
    return True


def _handle_workflow_not_found(ctx: click.Context, workflow_name: str, source: str | None) -> None:
    """Handle workflow not found error with helpful suggestions.

    Args:
        ctx: Click context
        workflow_name: Name of the workflow that wasn't found
        source: Source type from resolve_workflow

    Raises:
        SystemExit: Always exits with error
    """
    # Check if it was a parse error (already displayed)
    if source == "parse_error":
        ctx.exit(1)

    # Workflow not found - show helpful error
    wm = WorkflowManager()
    lower_name = workflow_name.lower()

    # Extension-specific hints
    if lower_name.endswith(".json"):
        click.echo(
            f"❌ JSON workflow format is no longer supported: {workflow_name}\n"
            "Workflow files use .pflow.md format.\n"
            "Example: pflow ./my-workflow.pflow.md",
            err=True,
        )
        ctx.exit(1)
    if lower_name.endswith(".md") and not lower_name.endswith(".pflow.md"):
        suggested = workflow_name.rsplit(".md", 1)[0] + ".pflow.md"
        click.echo(
            f"❌ Wrong file extension: {workflow_name}\n"
            f"Workflow files use .pflow.md extension.\n"
            f"Rename to: {suggested}",
            err=True,
        )
        ctx.exit(1)

    similar = find_similar_workflows(workflow_name, wm)
    click.echo(f"❌ Workflow '{workflow_name}' not found.", err=True)

    if similar:
        click.echo("\nDid you mean one of these?", err=True)
        for name in similar:
            click.echo(f"  - {name}", err=True)
    else:
        click.echo("\nUse 'pflow workflow list' to see available workflows.", err=True)

    ctx.exit(1)


def _inject_settings_env_vars() -> None:
    """Inject API keys from pflow settings into environment.

    This allows API keys stored via 'pflow settings set-env' to be available
    to the llm library and other tools that read from os.environ.

    Called early in CLI startup, before any LLM operations.
    Skipped in test environment to avoid test pollution.
    """
    from pflow.core.llm_config import inject_settings_env_vars

    inject_settings_env_vars()


def _try_execute_named_workflow(
    ctx: click.Context,
    workflow: tuple[str, ...],
    stdin_data: StdinData | str | None,
    output_key: str | None,
    output_format: str,
    verbose: bool,
) -> bool:
    """Try to execute workflow as a named/file workflow.

    Returns True if workflow was handled (either executed or error shown), False otherwise.
    """
    if not workflow:
        return False

    first_arg = workflow[0]
    if not is_likely_workflow_name(first_arg, workflow[1:]):
        return False

    # Resolve once to avoid duplicate calls
    workflow_ir, source = resolve_workflow(first_arg)
    # Try to execute as named workflow
    if _handle_named_workflow(
        ctx, first_arg, workflow[1:], stdin_data, output_key, output_format, verbose, workflow_ir, source
    ):
        return True
    # If not found, handle the error
    _handle_workflow_not_found(ctx, first_arg, source or "unknown")
    return True  # We handled it by showing an error


def _handle_invalid_workflow_input(ctx: click.Context, workflow: tuple[str, ...]) -> None:
    """Emit user guidance for input that is not a known workflow or command."""
    if not workflow:
        click.echo("❌ No workflow specified.", err=True)
        click.echo("", err=True)
        click.echo("Usage:", err=True)
        click.echo("  pflow workflow.pflow.md             # Run workflow from file", err=True)
        click.echo("  pflow my-workflow                   # Run saved workflow", err=True)
        click.echo("  pflow workflow list                 # List saved workflows", err=True)
        click.echo("  pflow instructions usage            # Instructions for AI agents", err=True)
        ctx.exit(1)

    if len(workflow) == 1:
        word = workflow[0]
        click.echo(f"❌ '{word}' is not a known workflow or command.", err=True)
        click.echo("", err=True)
        click.echo("Did you mean:", err=True)
        click.echo("  pflow workflow list                 # List saved workflows", err=True)
        click.echo("  pflow workflow.pflow.md             # Run workflow from file", err=True)
        ctx.exit(1)

    click.echo(f"❌ Invalid input: {workflow[0]} {workflow[1]} ...", err=True)
    click.echo("", err=True)
    click.echo("Usage:", err=True)
    click.echo("  pflow workflow.pflow.md             # Run workflow from file", err=True)
    click.echo("  pflow my-workflow param=value        # Run saved workflow", err=True)
    ctx.exit(1)


# NOTE: This MUST be @click.command, not @click.group with catch-all argument.
# Click groups consume ALL positional args when using @click.argument("workflow", nargs=-1),
# preventing subcommands from being recognized. The wrapper (main_wrapper.py) handles routing.
# allow_interspersed_args=True: flags like --report work after the workflow path.
# Safe because workflow params use key=value syntax (no -- prefix), not Click-style options.
@click.command(context_settings={"allow_interspersed_args": True})
@click.pass_context
@click.option("--version", is_flag=True, help="Show the pflow version")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution output")
@click.option("--output-key", "-o", "output_key", help="Shared store key to output to stdout (default: auto-detect)")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format: text (default) or json",
)
@click.option("-p", "--print", "print_flag", is_flag=True, help="Force non-interactive output (print mode)")
@click.option(
    "--no-trace",
    is_flag=True,
    help="Disable workflow execution trace saving (enabled by default)",
)
@click.option(
    "--report",
    "report_flag",
    is_flag=True,
    default=False,
    help="Generate execution report (directory of .md files) in ~/.pflow/reports/",
)
@click.option(
    "--report-dir",
    "report_dir",
    default=None,
    help="Custom output directory for execution report (implies --report)",
)
@click.option("--validate-only", is_flag=True, help="Validate workflow without executing")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def workflow_command(
    ctx: click.Context,
    version: bool,
    verbose: bool,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    no_trace: bool,
    report_flag: bool,
    report_dir: str | None,
    validate_only: bool,
    workflow: tuple[str, ...],
) -> None:
    """Reusable CLI workflows from shell, LLM, HTTP, code, and MCP nodes.

    \b
    Usage:
      pflow [OPTIONS] [WORKFLOW]...
      pflow workflow.pflow.md
      pflow my-workflow param=value
      command | pflow

    \b
    Commands:
      registry      Manage node registry (list, search, add custom nodes)
      workflow      Manage saved workflows (list, describe, history)
      skill         Publish workflows as AI agent skills
      mcp           Manage MCP server connections
      instructions  AI agents: Start here for usage guide and workflow discovery

    \b
    Examples:
      pflow my-workflow input=data.txt      Run saved workflow
      pflow ./workflow.pflow.md             Run workflow from file
      cat data.txt | pflow my-workflow      Pipe data to workflow
      pflow workflow list                   List saved workflows
      pflow workflow describe my-workflow   Show workflow interface
      pflow skill save my-workflow          Publish as AI skill
      pflow skill list                      List published skills
      pflow registry list                   List available nodes

    \b
    Notes:
      - Workflows can be specified by name or file path
      - Use key=value syntax to pass parameters to workflows
      - AI agents: Always run 'pflow instructions usage' FIRST for agent-optimized guidance
      - Run 'pflow COMMAND --help' for more information on a command
    """
    # Handle version flag
    if version:
        from importlib.metadata import version as pkg_version

        try:
            ver = pkg_version("pflow-cli")
        except Exception:
            ver = "0.10.0"
        click.echo(f"pflow version {ver}")
        ctx.exit(0)

    # Setup signal handlers
    _setup_signals()

    # NOTE: Logging already configured in main_wrapper.py before routing
    # No need to configure again here

    # Suppress WARNING logs in JSON mode to prevent stdout contamination
    # Only ERROR and CRITICAL logs will be shown
    original_log_levels = {}
    if output_format == "json":
        # Save and update root logger level
        root_logger = logging.getLogger()
        original_log_levels["root"] = root_logger.level
        root_logger.setLevel(logging.ERROR)

        # Also update pflow logger level (child loggers inherit from this)
        pflow_logger = logging.getLogger("pflow")
        original_log_levels["pflow"] = pflow_logger.level
        pflow_logger.setLevel(logging.ERROR)

    try:
        # Inject API keys from pflow settings into environment
        # This must happen early, before any LLM operations
        _inject_settings_env_vars()

        # Initialize context with configuration
        # --report / --report-dir implies tracing (can't generate report without a trace)
        report_enabled = report_flag or report_dir is not None
        trace_enabled = not no_trace or report_enabled
        _initialize_context(
            ctx,
            verbose,
            output_key,
            output_format,
            print_flag,
            trace_enabled,
            validate_only,
        )
        ctx.obj["report"] = report_dir or ("auto" if report_enabled else None)

        # Auto-discover and sync MCP servers
        # Only show MCP output if verbose AND not in print mode or JSON output
        print_flag = ctx.obj.get("print_flag", False)
        output_format = ctx.obj.get("output_format", "text")
        effective_verbose = verbose and not print_flag and output_format != "json"
        _auto_discover_mcp_servers(ctx, effective_verbose)

        # Handle stdin data
        stdin_content, enhanced_stdin = _read_stdin_data()
        stdin_data = enhanced_stdin if enhanced_stdin else stdin_content

        # Validate CLI flags are not misplaced
        _validate_workflow_flags(workflow, ctx)

        # Preprocess: transparently handle `run` prefix
        workflow = _preprocess_run_prefix(ctx, workflow)

        # Store workflow text in context for MCP check
        raw_input = " ".join(workflow) if workflow else ""
        ctx.obj["workflow_text"] = raw_input

        # Check MCP setup and provide guidance if needed
        # Temporarily disabled for debugging

        # Try to handle as named/file workflow first
        if _try_execute_named_workflow(ctx, workflow, stdin_data, output_key, output_format, verbose):
            return

        _handle_invalid_workflow_input(ctx, workflow)
    finally:
        # Restore original logging levels if we changed them
        if "root" in original_log_levels:
            logging.getLogger().setLevel(original_log_levels["root"])
        if "pflow" in original_log_levels:
            logging.getLogger("pflow").setLevel(original_log_levels["pflow"])


# Alias for backward compatibility with tests that import main directly
# Tests use: from pflow.cli.main import main
# This avoids breaking existing test infrastructure
main = workflow_command
