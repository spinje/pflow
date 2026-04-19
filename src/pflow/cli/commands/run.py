"""Workflow execution command for the pflow CLI."""

from __future__ import annotations

import json
import logging
import os
import time
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
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.exceptions import WorkflowNotFoundError, WorkflowValidationError
from pflow.core.output_controller import OutputController
from pflow.core.shell_integration import (
    read_stdin as read_stdin_content,
)
from pflow.core.shell_integration import (
    read_stdin_enhanced,
)
from pflow.core.validation_utils import is_valid_parameter_name
from pflow.core.workflow.manager import WorkflowManager
from pflow.execution.result import ResolvedWorkflow
from pflow.execution.workflow_resolver import resolve_workflow

logger = logging.getLogger(__name__)


def _get_output_controller(ctx: click.Context) -> OutputController:
    """Get the OutputController from context, creating it if needed."""
    if ctx.obj and "output_controller" in ctx.obj:
        return cast(OutputController, ctx.obj["output_controller"])

    return OutputController(
        print_flag=ctx.obj.get("print_flag", False) if ctx.obj else False,
    )


def _echo_trace(ctx: click.Context, message: str) -> None:
    """Output trace file location message."""
    output_controller = _get_output_controller(ctx)
    if output_controller.print_flag:
        return
    click.echo(message, err=True)


def _read_stdin_data() -> tuple[str | None, StdinData | None]:
    """Read stdin data, trying text first then enhanced."""
    stdin_content = read_stdin_content()

    enhanced_stdin = None
    if stdin_content is None:
        enhanced_stdin = read_stdin_enhanced()

    return stdin_content, enhanced_stdin


def _cleanup_temp_files(stdin_data: str | StdinData | None, verbose: bool) -> None:
    """Clean up temporary files if any."""
    if isinstance(stdin_data, StdinData) and stdin_data.is_temp_file and stdin_data.temp_path is not None:
        try:
            os.unlink(stdin_data.temp_path)
            if verbose:
                click.echo(f"cli: Cleaned up temp file: {stdin_data.temp_path}", err=True)
        except OSError:
            if verbose:
                click.echo(f"cli: Warning - could not clean up temp file: {stdin_data.temp_path}", err=True)


def _handle_workflow_success(
    ctx: click.Context,
    result: Any,
    workflow_trace: Any | None,
    shared_storage: dict[str, Any],
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
) -> None:
    """Handle successful workflow execution."""
    if verbose:
        click.echo("cli: Workflow execution completed", err=True)

    print_flag = ctx.obj.get("print_flag", False)
    workflow_metadata = ctx.obj.get("workflow_metadata")
    status = getattr(result, "status", None)
    result_warnings = [
        diagnostic for diagnostic in getattr(result, "diagnostics", []) if diagnostic.severity == Severity.WARNING
    ]

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
        status=status,
        warnings=result_warnings,
    )

    if not output_produced:
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
    """Save trace to file and generate report if requested."""
    if not workflow_trace:
        return
    if not ctx.obj.get("trace", False):
        return
    try:
        trace_file = workflow_trace.save_to_file()
    except Exception as trace_err:
        logger.error("Failed to save trace: %s", trace_err, exc_info=True)
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
                    if only_node:
                        _echo_target_node_path(ctx, report_dir, workflow_trace.events, only_node)
            except Exception as report_err:
                logger.error("Failed to generate report: %s", report_err, exc_info=True)


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
    workflow: dict[str, Any] | ResolvedWorkflow,
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    output_format: str = "text",
) -> None:
    """Execute a workflow through the shared Runner."""
    from pflow.cli.error_output import output_error
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner

    ir_data = workflow.ir if isinstance(workflow, ResolvedWorkflow) else workflow
    params = dict(execution_params or {})

    if stdin_data:
        _route_stdin_to_params(ctx, stdin_data, ir_data, params)

    source_file_path = ctx.obj.get("source_file_path")
    if source_file_path:
        params["_pflow_workflow_file"] = str(Path(source_file_path).resolve())

    if ctx.obj.get("dry_run"):
        _display_plan_result(ctx, workflow, params, output_format)
        return

    if ctx.obj.get("validate_only"):
        runner = WorkflowRunner()
        vresult = runner.validate(workflow, params, source_file_path=ctx.obj.get("source_file_path"))
        _display_validation_result(ctx, vresult, output_format)
        return

    verbose = ctx.obj.get("verbose", False)
    print_flag = ctx.obj.get("print_flag", False)
    effective_verbose = verbose and not print_flag
    config = RunnerConfig(
        trace_enabled=ctx.obj.get("trace", True),
        cache_enabled=ctx.obj.get("cache", True),
        verbose=effective_verbose,
        only_node=ctx.obj.get("only_node"),
    )

    if not effective_verbose:
        warnings.filterwarnings("ignore", message="Flow ends:.*", module="pflow.core.node")

    ctx.obj["total_nodes"] = len(ir_data.get("nodes", []))

    output_controller = _get_output_controller(ctx)
    progress_enabled = not print_flag

    if effective_verbose:
        click.echo(f"cli: Starting workflow execution with {ctx.obj['total_nodes']} node(s)", err=True)
    if progress_enabled:
        click.echo(f"Executing workflow ({len(ir_data.get('nodes', []))} nodes):", err=True)

    workflow_name = ctx.obj.get("workflow_name")
    result = None

    try:
        runner = WorkflowRunner()
        progress_callback = output_controller.create_progress_callback() if progress_enabled else None
        result = runner.run(
            workflow,
            params,
            config,
            progress_callback=progress_callback,
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
        metrics = result.metrics if result else None
        _emit_failure_tag(ctx, metrics)

        output_error(
            ctx,
            exception=e,
            output_format=output_format,
            verbose=effective_verbose,
            workflow_metadata=ctx.obj.get("workflow_metadata") if ctx.obj else None,
            metrics_collector=metrics,
            shared_storage=result.shared_after if result else {},
        )
        ctx.exit(1)

    finally:
        trace = result.trace if result else None
        if trace and config.trace_enabled:
            _save_trace_and_report(ctx, trace)
        _cleanup_temp_files(stdin_data, effective_verbose)


def _emit_failure_tag(ctx: click.Context, metrics: Any | None) -> None:
    """Emit one-line failure tag to stderr for agent observability."""
    print_flag = ctx.obj.get("print_flag", False) if ctx.obj else False
    if not print_flag and metrics:
        duration_s = time.perf_counter() - metrics.start_time
        click.echo(f"❌ Workflow failed after {duration_s:.3f}s", err=True)


def _display_execution_result(
    ctx: click.Context,
    result: Any,
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    verbose: bool,
) -> None:
    """Display execution result and set exit code."""
    from pflow.cli.error_output import output_error
    from pflow.core.workflow.status import WorkflowStatus

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
        _emit_failure_tag(ctx, result.metrics)

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
    vresult: Any,
    output_format: str,
) -> None:
    """Display validation result and exit with appropriate code."""
    if output_format == "json":
        output = {
            "success": vresult.valid,
            "validated_only": True,
            "errors": [e.to_display_dict() for e in vresult.errors],
            "warnings": [warning.to_display_dict() for warning in vresult.warnings],
            "diagnostics": [d.to_dict() for d in vresult.diagnostics],
        }
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        if vresult.valid:
            from pflow.execution.formatters.validation_formatter import format_validation_success

            click.echo(format_validation_success())
            if vresult.warnings:
                for diagnostic in vresult.warnings:
                    click.echo(format_diagnostic(diagnostic), err=True)
        else:
            from pflow.execution.formatters.validation_formatter import format_validation_failure

            click.echo(format_validation_failure(vresult.errors))
            extra_diagnostics = [d for d in vresult.diagnostics if d.severity in {Severity.WARNING, Severity.INFO}]
            if extra_diagnostics:
                click.echo("", err=True)
                for diagnostic in extra_diagnostics:
                    click.echo(format_diagnostic(diagnostic), err=True)

    ctx.exit(0 if vresult.valid else 1)


def _display_plan_result(
    ctx: click.Context,
    workflow: dict[str, Any] | ResolvedWorkflow,
    params: dict[str, Any],
    output_format: str,
) -> None:
    """Display dry-run plan result and exit."""
    from pflow.execution.formatters.plan_formatter import format_plan_json, format_plan_text
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner

    runner = WorkflowRunner()
    plan = runner.plan(
        workflow,
        params,
        RunnerConfig(
            trace_enabled=False,
            cache_enabled=ctx.obj.get("cache", True),
            verbose=False,
            only_node=ctx.obj.get("only_node"),
        ),
    )

    if output_format == "json":
        click.echo(json.dumps(format_plan_json(plan), indent=2, default=str))
    else:
        click.echo(format_plan_text(plan))

    ctx.exit(0)


def _initialize_context(
    ctx: click.Context,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    trace_enabled: bool,
    validate_only: bool,
) -> None:
    """Initialize the click context with run-specific configuration."""
    if ctx.obj is None:
        ctx.obj = {}

    ctx.obj["output_key"] = output_key
    ctx.obj["output_format"] = output_format
    ctx.obj["print_flag"] = print_flag
    ctx.obj["trace"] = trace_enabled
    ctx.obj["validate_only"] = validate_only
    ctx.obj["output_controller"] = OutputController(
        print_flag=print_flag,
    )


def _preprocess_run_prefix(workflow: tuple[str, ...]) -> tuple[str, ...]:
    """Handle a leading 'run' token for UX compatibility."""
    if workflow and workflow[0] == "run":
        if len(workflow) == 1:
            from pflow.core.user_errors import UserFriendlyError

            raise UserFriendlyError(
                title="Need to specify what to run",
                explanation="The 'run' command requires a workflow name.",
                suggestions=["pflow <workflow-name>", "pflow list"],
            )
        return tuple(workflow[1:])
    return workflow


def _validate_workflow_flags(workflow: tuple[str, ...]) -> None:
    """Validate that CLI flags are not misplaced in workflow arguments."""
    misplaced_flags = [
        arg
        for arg in workflow
        if arg
        in (
            "--no-trace",
            "--verbose",
            "-v",
            "--output-key",
            "-o",
            "--output-format",
            "--print",
            "-p",
            "--report",
            "--report-dir",
            "--validate-only",
            "--dry-run",
            "--cache",
            "--no-cache",
            "--only",
        )
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
    """Find the input marked with stdin: true."""
    inputs: dict[str, Any] = workflow_ir.get("inputs", {})
    for name, spec in inputs.items():
        if isinstance(spec, dict) and spec.get("stdin") is True:
            return str(name)
    return None


def _extract_stdin_text(stdin_data: str | StdinData | None) -> str | None:
    """Extract text content from stdin data."""
    if stdin_data is None:
        return None
    if isinstance(stdin_data, str):
        return stdin_data
    if stdin_data.text_data is not None:
        return stdin_data.text_data
    return None


def _route_stdin_to_params(
    ctx: click.Context,
    stdin_data: str | StdinData | None,
    workflow_ir: dict[str, Any],
    params: dict[str, Any],
) -> None:
    """Route stdin content to the appropriate workflow input parameter."""
    stdin_text = _extract_stdin_text(stdin_data)
    if stdin_text is None:
        if isinstance(stdin_data, StdinData) and (stdin_data.binary_data or stdin_data.temp_path):
            click.echo("⚠️  Stdin contains binary or large data", err=True)
            click.echo("   Binary/large data is not automatically routed to workflow inputs.", err=True)
            click.echo("   Consider using a file path parameter instead.", err=True)
            click.echo("", err=True)
        return

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

    if target_input not in params:
        params[target_input] = stdin_text


def _validate_dry_run_flag_combination(
    *,
    dry_run: bool,
    validate_only: bool,
    report_flag: bool,
    report_dir: str | None,
) -> None:
    """Enforce dry-run flag composition rules."""
    if not dry_run:
        return

    from pflow.core.user_errors import UserFriendlyError

    if validate_only:
        raise UserFriendlyError(
            title="Cannot combine --dry-run and --validate-only",
            explanation=(
                "These flags answer different questions: --dry-run shows what "
                "would happen at runtime; --validate-only checks structural "
                "validity. Pick one."
            ),
            suggestions=[
                "pflow <workflow> --dry-run",
                "pflow <workflow> --validate-only",
            ],
        )

    if report_flag or report_dir is not None:
        raise UserFriendlyError(
            title="Cannot combine --dry-run and --report",
            explanation=(
                "--report generates output from execution traces; --dry-run "
                "does not execute anything, so there is nothing to report."
            ),
            suggestions=[
                "pflow <workflow> --dry-run",
                "pflow <workflow> --report",
            ],
        )


def _validate_and_prepare_workflow_params(
    ctx: click.Context,
    workflow_ir: dict[str, Any],
    remaining_args: tuple[str, ...],
    stdin_data: str | StdinData | None = None,
) -> dict[str, Any]:
    """Validate workflow parameters, route stdin, and apply defaults."""
    params = parse_workflow_params(remaining_args)

    invalid_keys = [k for k in params if not is_valid_parameter_name(k)]
    if invalid_keys:
        raise WorkflowValidationError(
            summary="Invalid parameter names",
            validation_errors=[
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    message=f"Invalid parameter name(s): {', '.join(invalid_keys)}",
                    suggestions=[
                        "Parameter names cannot contain shell special characters ($, |, >, <, &, ;, etc.)",
                    ],
                    context={"category": "validation"},
                )
            ],
        )

    _route_stdin_to_params(ctx, stdin_data, workflow_ir, params)

    return params


def _show_workflow_help(
    first_arg: str,
    workflow_ir: dict[str, Any],
    source: str | None,
) -> None:
    """Display workflow help information."""
    from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface

    name = os.path.basename(first_arg) if "/" in first_arg else first_arg
    metadata = {"ir": workflow_ir}

    if "description" in workflow_ir:
        metadata["description"] = workflow_ir["description"]

    click.echo(f"\nWorkflow: {name}")
    if source == "library":
        click.echo("Source: Saved workflow")
    else:
        click.echo(f"Source: {first_arg}")
    click.echo()

    formatted = format_workflow_interface(name, metadata)
    click.echo(formatted)


def _setup_workflow_execution(
    ctx: click.Context,
    first_arg: str,
    source: str | None,
    output_format: str,
) -> None:
    """Setup workflow execution context (source, name, file path)."""
    if source == "library":
        ctx.obj["workflow_metadata"] = _create_workflow_metadata(first_arg, "reused")
    else:
        ctx.obj["workflow_metadata"] = _create_workflow_metadata(first_arg, "unsaved")

    ctx.obj["workflow_source"] = source

    if source == "file" and first_arg.endswith(".pflow.md"):
        ctx.obj["source_file_path"] = first_arg
        file_stem = Path(first_arg).stem
        ctx.obj["workflow_name"] = file_stem[:-6] if file_stem.endswith(".pflow") else file_stem
    elif source == "library":
        workflow_name = first_arg[:-9] if first_arg.lower().endswith(".pflow.md") else first_arg
        ctx.obj["workflow_name"] = workflow_name
        try:
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
    resolved_workflow: ResolvedWorkflow | None = None,
) -> bool:
    """Handle execution of a named or file-based workflow."""
    if resolved_workflow is None:
        try:
            resolved_workflow = resolve_workflow(first_arg)
        except WorkflowNotFoundError:
            return False
    workflow_ir = resolved_workflow.ir
    source = resolved_workflow.source
    if not workflow_ir:
        return False

    if remaining_args and "--help" in remaining_args:
        _show_workflow_help(first_arg, workflow_ir, source)
        return True

    params = _validate_and_prepare_workflow_params(ctx, workflow_ir, remaining_args, stdin_data)

    from pflow.cli.rerun_display import filter_user_params

    ctx.obj["execution_params"] = filter_user_params(params)

    if verbose:
        if source == "library":
            click.echo(f"cli: Loading workflow '{first_arg}' from registry", err=True)
        else:
            click.echo(f"cli: Loading workflow from file: {first_arg}", err=True)
        if params:
            click.echo(f"cli: With parameters: {params}", err=True)

    _setup_workflow_execution(ctx, first_arg, source, output_format)
    execute_json_workflow(ctx, resolved_workflow, stdin_data, output_key, params, output_format)
    return True


def _inject_settings_env_vars() -> None:
    """Inject API keys from pflow settings into environment."""
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
    """Try to execute workflow as a named/file workflow."""
    if not workflow:
        return False

    first_arg = workflow[0]
    if not is_likely_workflow_name(first_arg, workflow[1:]):
        return False

    resolved = resolve_workflow(first_arg)
    if _handle_named_workflow(ctx, first_arg, workflow[1:], stdin_data, output_key, output_format, verbose, resolved):
        return True
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
                "pflow list",
            ],
        )

    if len(workflow) == 1:
        raise UserFriendlyError(
            title=f"'{workflow[0]}' is not a known workflow or command",
            explanation="The input was not recognized as a workflow name or file path.",
            suggestions=[
                "pflow list",
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


@click.command(
    name="run",
    hidden=True,
    add_help_option=False,
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": True},
)
@click.pass_context
@click.option("--output-key", "-o", "output_key", help="Shared store key to output to stdout (default: auto-detect)")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format: text (default) or json",
)
@click.option(
    "-p",
    "--print",
    "print_flag",
    is_flag=True,
    help="Minimal output: suppress header, summary, and warnings on stderr. Data still goes to stdout.",
)
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
@click.option("--dry-run", "dry_run", is_flag=True, help="Build execution plan without invoking side effects")
@click.option("--cache/--no-cache", default=True, help="Enable/disable memoization cache (default: enabled)")
@click.option(
    "--only", "only_node", default=None, help="Run workflow through this node then stop (caching still applies)"
)
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def run(
    ctx: click.Context,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    no_trace: bool,
    report_flag: bool,
    report_dir: str | None,
    validate_only: bool,
    dry_run: bool,
    cache: bool,
    only_node: str | None,
    workflow: tuple[str, ...],
) -> None:
    """Execute a workflow file or saved workflow."""
    try:
        _inject_settings_env_vars()

        report_enabled = report_flag or report_dir is not None
        trace_enabled = not no_trace or report_enabled
        _initialize_context(
            ctx,
            output_key,
            output_format,
            print_flag,
            trace_enabled,
            validate_only,
        )
        _validate_dry_run_flag_combination(
            dry_run=dry_run,
            validate_only=validate_only,
            report_flag=report_flag,
            report_dir=report_dir,
        )
        ctx.obj["dry_run"] = dry_run
        ctx.obj["report"] = report_dir or ("auto" if report_enabled else None)
        ctx.obj["cache"] = cache
        ctx.obj["only_node"] = only_node

        print_flag = ctx.obj.get("print_flag", False)
        output_format = ctx.obj.get("output_format", "text")
        verbose = ctx.obj.get("verbose", False)
        effective_verbose = verbose and not print_flag
        _auto_discover_mcp_servers(ctx, effective_verbose)

        stdin_content, enhanced_stdin = _read_stdin_data()
        stdin_data = enhanced_stdin if enhanced_stdin else stdin_content

        _validate_workflow_flags(workflow)
        workflow = _preprocess_run_prefix(workflow)

        raw_input = " ".join(workflow) if workflow else ""
        ctx.obj["workflow_text"] = raw_input

        if _try_execute_named_workflow(ctx, workflow, stdin_data, output_key, output_format, verbose):
            return

        _handle_invalid_workflow_input(workflow)
    except click.exceptions.Exit:
        raise
    except Exception as e:
        from pflow.cli.error_output import output_error

        of = ctx.obj.get("output_format", "text") if ctx.obj else output_format
        vb = ctx.obj.get("verbose", False) if ctx.obj else False
        wm = ctx.obj.get("workflow_metadata") if ctx.obj else None
        output_error(ctx, exception=e, output_format=of, verbose=vb, workflow_metadata=wm)
        ctx.exit(1)
