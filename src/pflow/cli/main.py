"""Main CLI entry point for pflow."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import warnings
from pathlib import Path
from typing import Any, cast

import click

from pflow.cli.mcp_sync import _auto_discover_mcp_servers
from pflow.cli.param_parsing import parse_workflow_params
from pflow.cli.workflow_output import (
    _create_workflow_metadata,
    _handle_workflow_output,
)
from pflow.cli.workflow_resolution import is_likely_workflow_name
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
from pflow.execution import DisplayManager
from pflow.execution.workflow_resolver import resolve_workflow

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
    # Merge runtime + validation warnings for unified output (matches MCP behavior)
    result_warnings = getattr(result, "warnings", []) + getattr(result, "validation_warnings", [])

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


def _save_trace_and_report(ctx: click.Context, workflow_trace: Any | None) -> None:
    """Save trace to file and generate report if requested.

    Called from the finally block — survives Ctrl+C (SystemExit triggers finally).
    Only saves to file when --trace is enabled (the collector always exists for cost tracking).
    """
    if not workflow_trace:
        return
    if not ctx.obj.get("trace", False):
        return
    try:
        trace_file = workflow_trace.save_to_file()
    except Exception as trace_err:
        logger.error(f"Failed to save trace: {trace_err}", exc_info=True)
        return

    if trace_file:
        _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")
        report = ctx.obj.get("report")
        if report:
            try:
                from pflow.core.trace_report import generate_report

                only_node = ctx.obj.get("only_node")
                report_dir = generate_report(
                    trace_file,
                    report,
                    only_node=only_node,
                    total_nodes=ctx.obj.get("total_nodes") if only_node else None,
                )
                if report_dir:
                    _echo_trace(ctx, f"📋 Execution report: {report_dir}")
                    # Point the agent to the target node's report file
                    if only_node:
                        _echo_target_node_path(ctx, report_dir, workflow_trace.events, only_node)
            except Exception as report_err:
                logger.error(f"Failed to generate report: {report_err}", exc_info=True)


def _echo_target_node_path(ctx: click.Context, report_dir: Path, events: list[dict[str, Any]], only_node: str) -> None:
    """Display the --only target node's report file path."""
    from pflow.core.trace_report import _safe_name

    for i, event in enumerate(events, 1):
        if event.get("node_id") == only_node:
            safe_id = _safe_name(only_node)
            prefix = f"{i:02d}"
            is_container = event.get("batch_items") or event.get("sub_workflow_events")
            target = (
                report_dir / f"{prefix}-{safe_id}" / "summary.md"
                if is_container
                else report_dir / f"{prefix}-{safe_id}.md"
            )
            if target.exists():
                _echo_trace(ctx, f"   → Target node: {target}")
            break


def execute_json_workflow(  # noqa: C901
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    output_format: str = "text",
) -> None:
    """Execute a workflow through the shared Runner."""
    from pflow.cli.error_output import output_error
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner

    params = dict(execution_params or {})

    # Route stdin to params (CLI concern -- Runner never knows about stdin)
    if stdin_data:
        _route_stdin_to_params(ctx, stdin_data, ir_data, params)

    # Inject workflow file path for relative path resolution in nested workflows.
    # The Runner handles this for string inputs (via resolver), but CLI always
    # passes pre-parsed IR dicts, so we must inject it from ctx.obj.
    source_file_path = ctx.obj.get("source_file_path")
    if source_file_path:
        params["_pflow_workflow_file"] = str(Path(source_file_path).resolve())

    # Validate-only mode -- separate method, separate result type
    if ctx.obj.get("validate_only"):
        runner = WorkflowRunner()
        vresult = runner.validate(ir_data, params, source_file_path=ctx.obj.get("source_file_path"))
        _display_validation_result(ctx, vresult, output_format)
        return

    # Build config
    verbose = ctx.obj.get("verbose", False)
    print_flag = ctx.obj.get("print_flag", False)
    effective_verbose = verbose and not print_flag and output_format != "json"
    config = RunnerConfig(
        trace_enabled=ctx.obj.get("trace", True),
        cache_enabled=ctx.obj.get("cache", True),
        verbose=effective_verbose,
        only_node=ctx.obj.get("only_node"),
    )

    # Suppress PocketFlow "Flow ends" warnings in non-verbose mode
    if not effective_verbose:
        warnings.filterwarnings("ignore", message="Flow ends:.*", module="pflow.pocketflow")

    # Suppress logging in JSON mode (except CRITICAL) to keep output clean
    if output_format == "json":
        logging.getLogger().setLevel(logging.CRITICAL)

    # Store total nodes for --report
    ctx.obj["total_nodes"] = len(ir_data.get("nodes", []))

    # Build output interface
    from pflow.cli.cli_output import CliOutput

    output_controller = _get_output_controller(ctx)
    # CliOutput gets raw verbose (not effective_verbose) — it controls its own
    # JSON/interactive suppression internally. effective_verbose is for CLI-level
    # messages (echo) and the Runner's shared store __verbose__ flag.
    cli_output = CliOutput(output_controller, verbose, output_format)

    # Show execution starting
    if effective_verbose:
        click.echo(f"cli: Starting workflow execution with {ctx.obj['total_nodes']} node(s)")
    display = DisplayManager(cli_output)
    display.show_execution_start(len(ir_data.get("nodes", [])))

    workflow_name = ctx.obj.get("workflow_name")
    result = None

    try:
        runner = WorkflowRunner()
        result = runner.run(
            ir_data,
            params,
            config,
            output=cli_output,
            workflow_manager=WorkflowManager() if ctx.obj.get("workflow_source") == "library" else None,
            workflow_name=workflow_name,
        )
        _display_execution_result(ctx, result, output_key, ir_data, output_format, effective_verbose)

    except click.exceptions.Exit:
        raise
    except KeyboardInterrupt:
        click.echo("\n✗ Workflow execution interrupted", err=True)
        ctx.exit(130)
    except Exception as e:
        output_error(
            ctx,
            exception=e,
            output_format=output_format,
            verbose=effective_verbose,
            workflow_metadata=ctx.obj.get("workflow_metadata") if ctx.obj else None,
            metrics_collector=result.metrics if result else None,
            shared_storage=result.shared_after if result else {},
        )
        ctx.exit(1)

    finally:
        trace = result.trace if result else None
        if trace and config.trace_enabled:
            _save_trace_and_report(ctx, trace)
        _cleanup_temp_files(stdin_data, effective_verbose)
        if output_format == "json":
            logging.getLogger().setLevel(logging.WARNING)


def _display_execution_result(
    ctx: click.Context,
    result: Any,  # ExecutionResult
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    verbose: bool,
) -> None:
    """Display execution result and set exit code."""
    from pflow.cli.error_output import output_error
    from pflow.core.workflow.status import WorkflowStatus

    # Surface validation warnings (pre-execution diagnostics from WorkflowValidator)
    if result.validation_warnings and output_format != "json":
        for w in result.validation_warnings:
            node = w.get("node", "?")
            click.echo(f"  ⚠ [{node}] {w.get('template', '?')}: {w.get('message', '')}", err=True)

    if result.success:
        _handle_workflow_success(
            ctx=ctx,
            result=result,
            workflow_trace=result.trace,
            shared_storage=result.shared_after,
            output_key=output_key,
            ir_data=ir_data,
            output_format=output_format,
            metrics_collector=result.metrics,
            verbose=verbose,
        )
        if result.status == WorkflowStatus.DEGRADED:
            ctx.exit(2)
    else:
        output_error(
            ctx,
            result=result,
            output_format=output_format,
            verbose=verbose,
            workflow_metadata=ctx.obj.get("workflow_metadata") if ctx.obj else None,
            metrics_collector=result.metrics,
            shared_storage=result.shared_after,
            ir_data=ir_data,
        )
        ctx.exit(1)


def _display_validation_result(
    ctx: click.Context,
    vresult: Any,  # ValidationResult
    output_format: str,
) -> None:
    """Display validation result and exit with appropriate code."""
    if output_format == "json":
        output = {
            "success": vresult.valid,
            "validated_only": True,
            "errors": [{"message": e, "category": "validation"} for e in vresult.errors],
            "warnings": vresult.warnings,
        }
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        if vresult.valid:
            from pflow.execution.formatters.validation_formatter import format_validation_success

            click.echo(format_validation_success())
            if vresult.warnings:
                for w in vresult.warnings:
                    click.echo(f"  ⚠ {w.get('template', '?')}: {w.get('message', '')}", err=True)
        else:
            from pflow.execution.formatters.validation_formatter import format_validation_failure

            click.echo(format_validation_failure(vresult.errors))

    ctx.exit(0 if vresult.valid else 1)


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


def _preprocess_run_prefix(workflow: tuple[str, ...]) -> tuple[str, ...]:
    """Handle a leading 'run' token for UX compatibility."""
    if workflow and workflow[0] == "run":
        if len(workflow) == 1:
            from pflow.core.user_errors import UserFriendlyError

            raise UserFriendlyError(
                title="Need to specify what to run",
                explanation="The 'run' command requires a workflow name.",
                suggestions=["pflow <workflow-name>", "pflow workflow list"],
            )
        return tuple(workflow[1:])
    return workflow


def _validate_workflow_flags(workflow: tuple[str, ...]) -> None:
    """Validate that CLI flags are not misplaced in workflow arguments."""
    misplaced_flags = [
        arg for arg in workflow if arg in ("--no-trace", "--verbose", "-v", "--output-key", "-o", "--output-format")
    ]
    if misplaced_flags:
        from pflow.core.user_errors import UserFriendlyError

        raise UserFriendlyError(
            title="CLI flags must come BEFORE the workflow text",
            explanation=f"Found misplaced flags: {', '.join(misplaced_flags)}",
            suggestions=[
                'pflow --verbose "analyze this data"',
                'pflow --no-trace "run without tracing"',
            ],
        )


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
        from pflow.core.user_errors import UserFriendlyError

        raise UserFriendlyError(
            title="Piped input cannot be routed to workflow",
            explanation=(
                'This workflow has no input marked with "stdin": true.\n'
                'To accept piped data, add "stdin": true to one input declaration.\n\n'
                "Example (.pflow.md format):\n"
                "  ### data\n\n"
                "  Input data piped via stdin.\n\n"
                "  - type: string\n"
                "  - required: true\n"
                "  - stdin: true"
            ),
            suggestions=['Add "stdin": true to the input that should receive piped data'],
        )

    # Route stdin to target input (unless CLI override exists)
    if target_input not in params:
        params[target_input] = stdin_text


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
        from pflow.core.exceptions import WorkflowValidationError

        raise WorkflowValidationError(
            summary="Invalid parameter names",
            validation_errors=[
                (
                    f"Invalid parameter name(s): {', '.join(invalid_keys)}",
                    "",
                    "Parameter names cannot contain shell special characters ($, |, >, <, &, ;, etc.)",
                )
            ],
        )

    # Route stdin to workflow input marked with stdin: true
    _route_stdin_to_params(ctx, stdin_data, workflow_ir, params)

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
        source: Workflow source ("library", "file", etc.)
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
    if source == "library":
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
) -> None:
    """Setup workflow execution context (source, name, file path).

    Args:
        ctx: Click context
        first_arg: First workflow argument (name or path)
        source: Workflow source ("library", "file", etc.)
        output_format: Output format
    """
    # Set workflow metadata based on source
    # This ensures proper action field in JSON output
    if source == "library":
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
    elif source == "library":
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
    if workflow_ir is None:
        from pflow.core.exceptions import WorkflowNotFoundError as _WNF

        try:
            resolved = resolve_workflow(first_arg)
        except _WNF:
            return False
        workflow_ir, source = resolved.ir, resolved.source
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
        if source == "library":
            click.echo(f"cli: Loading workflow '{first_arg}' from registry")
        else:
            click.echo(f"cli: Loading workflow from file: {first_arg}")
        if params:
            click.echo(f"cli: With parameters: {params}")

    # Setup workflow execution context
    _setup_workflow_execution(ctx, first_arg, source, output_format)

    # Execute workflow
    execute_json_workflow(ctx, workflow_ir, stdin_data, output_key, params, output_format)
    return True


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

    # Resolve once to avoid duplicate calls — raises WorkflowNotFoundError if not found
    resolved = resolve_workflow(first_arg)
    workflow_ir, source = resolved.ir, resolved.source
    # Try to execute as named workflow
    if _handle_named_workflow(
        ctx, first_arg, workflow[1:], stdin_data, output_key, output_format, verbose, workflow_ir, source
    ):
        return True
    # Should not reach here — resolve_workflow raises if not found
    from pflow.core.exceptions import WorkflowNotFoundError

    raise WorkflowNotFoundError(first_arg, similar_names=[])


def _handle_invalid_workflow_input(workflow: tuple[str, ...]) -> None:
    """Emit user guidance for input that is not a known workflow or command."""
    from pflow.core.user_errors import UserFriendlyError

    if not workflow:
        raise UserFriendlyError(
            title="No workflow specified",
            explanation="Provide a workflow file or saved workflow name.",
            suggestions=[
                "pflow workflow.pflow.md",
                "pflow my-workflow",
                "pflow workflow list",
            ],
        )

    if len(workflow) == 1:
        raise UserFriendlyError(
            title=f"'{workflow[0]}' is not a known workflow or command",
            explanation="The input was not recognized as a workflow name or file path.",
            suggestions=[
                "pflow workflow list",
                "pflow workflow.pflow.md",
            ],
        )

    raise UserFriendlyError(
        title=f"Invalid input: {workflow[0]} {workflow[1]} ...",
        explanation="The input was not recognized as a valid workflow invocation.",
        suggestions=[
            "pflow workflow.pflow.md",
            "pflow my-workflow param=value",
        ],
    )


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
@click.option("--cache/--no-cache", default=True, help="Enable/disable memoization cache (default: enabled)")
@click.option(
    "--only", "only_node", default=None, help="Run workflow through this node then stop (caching still applies)"
)
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
    cache: bool,
    only_node: str | None,
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
        ctx.obj["cache"] = cache
        ctx.obj["only_node"] = only_node

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
        _validate_workflow_flags(workflow)

        # Preprocess: transparently handle `run` prefix
        workflow = _preprocess_run_prefix(workflow)

        # Store workflow text in context for MCP check
        raw_input = " ".join(workflow) if workflow else ""
        ctx.obj["workflow_text"] = raw_input

        # Check MCP setup and provide guidance if needed
        # Temporarily disabled for debugging

        # Try to handle as named/file workflow first
        if _try_execute_named_workflow(ctx, workflow, stdin_data, output_key, output_format, verbose):
            return

        _handle_invalid_workflow_input(workflow)
    except click.exceptions.Exit:
        raise
    except Exception as e:
        from pflow.cli.error_output import output_error

        of = ctx.obj.get("output_format", "text") if ctx.obj else output_format
        vb = ctx.obj.get("verbose", False) if ctx.obj else verbose
        wm = ctx.obj.get("workflow_metadata") if ctx.obj else None
        output_error(ctx, exception=e, output_format=of, verbose=vb, workflow_metadata=wm)
        ctx.exit(1)
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
