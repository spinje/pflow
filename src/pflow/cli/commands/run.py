"""Workflow execution command for the pflow CLI."""

from __future__ import annotations

import json
import logging
import os
import shlex
import sys
import warnings
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import click

from pflow.cli.param_parsing import parse_workflow_params
from pflow.cli.workflow_output import _create_workflow_metadata
from pflow.cli.workflow_resolution import is_likely_workflow_name
from pflow.core import StdinData
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.exceptions import ReportGenerationError, WorkflowNotFoundError, WorkflowValidationError
from pflow.core.output_controller import OutputController
from pflow.core.shell_integration import (
    read_stdin as read_stdin_content,
)
from pflow.core.shell_integration import (
    read_stdin_enhanced,
)
from pflow.core.stdio_reservation import reserve_stdout
from pflow.core.text_format import count_noun
from pflow.core.validation_utils import is_valid_parameter_name
from pflow.core.workflow.manager import WorkflowManager
from pflow.execution.result import ResolvedWorkflow
from pflow.execution.workflow_resolver import resolve_workflow

if TYPE_CHECKING:
    from pflow.core.param_coercion import InputSource
    from pflow.execution.formatters.run_outcome import RunOutcome

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


def _read_stdin_data() -> str | StdinData | None:
    """Read stdin: text, or ``StdinData`` for binary/oversized input, or None when there is none.

    Unix tries the text read first; win32 reads binary-aware first so binary bytes survive (Task 116).
    """
    if sys.platform == "win32":
        enhanced_stdin = read_stdin_enhanced()
        if enhanced_stdin is None:
            return read_stdin_content()
        if enhanced_stdin.is_text:
            text = enhanced_stdin.text_data or ""
            if text.endswith("\r"):
                text = text[:-1]
            return text.replace("\r\n", "\n").replace("\r", "\n")
        return enhanced_stdin

    stdin_content = read_stdin_content()
    if stdin_content is not None:
        return stdin_content
    return read_stdin_enhanced()


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


def _save_trace_file(ctx: click.Context, workflow_trace: Any) -> Any | None:
    """Finalize the streamed trace once; cache and return its path.

    Task 172: the run-scoped collector streamed one JSONL line per node DURING the
    run; ``finalize()`` writes the ``run.complete`` trailer and closes the file
    (returning its path, or ``None`` when streaming was off — ``--no-trace``).
    Idempotent across its callers — the outcome path in ``_display_execution_result``
    and the ``finally`` block (``--report`` generation) — so the trailer is written
    exactly once (``finalize`` self-guards too). Returns ``None`` on error.
    """
    if "trace_file" not in ctx.obj:
        try:
            ctx.obj["trace_file"] = workflow_trace.finalize()
        except Exception as trace_err:
            logger.error("Failed to save trace: %s", trace_err, exc_info=True)
            ctx.obj["trace_file"] = None
    return ctx.obj["trace_file"]


def _finalize_trace_and_report(ctx: click.Context, workflow_trace: Any) -> None:
    """Save the trace (idempotent — the outcome path usually already did) and generate ``--report``.

    The ``Workflow trace saved`` line is part of the run outcome's stderr summary, not echoed here.
    """
    trace_file = _save_trace_file(ctx, workflow_trace)
    report = ctx.obj.get("report")
    if trace_file and report:
        _generate_and_echo_report(ctx, trace_file, report, workflow_trace)


def _generate_and_echo_report(ctx: click.Context, trace_file: Any, report: Any, workflow_trace: Any) -> None:
    """Generate the report directory and echo its summary to stderr."""
    try:
        from pflow.core.trace_report import generate_report

        only_node = ctx.obj.get("only_node")
        report_dir = generate_report(
            trace_file,
            report,
            only_node=only_node,
            total_nodes=ctx.obj.get("total_nodes") if only_node else None,
        )
        if not report_dir:
            return
        _echo_trace(ctx, f"📋 Execution report: {report_dir}")
        summary_path = report_dir / "summary.md"
        try:
            summary_text = summary_path.read_text(encoding="utf-8")
        except OSError:
            pass
        else:
            _echo_trace(ctx, "")
            _echo_trace(ctx, summary_text)
        if only_node:
            _echo_target_node_path(ctx, report_dir, workflow_trace.events, only_node)
    except ReportGenerationError as report_err:
        click.echo(f"Failed to generate report: {report_err}", err=True)
    except Exception as report_err:
        logger.error("Failed to generate report: %s", report_err, exc_info=True)


def _echo_target_node_path(ctx: click.Context, report_dir: Path, events: list[dict[str, Any]], only_node: str) -> None:
    """Display the --only target node's report file path."""
    from pflow.core.trace_report import _safe_name
    from pflow.runtime.engine.engine import parse_only_path

    this_only, _ = parse_only_path(only_node)
    if this_only is None:
        return
    # Task 172: the collector store is now FLAT — sub-workflow children are sibling events carrying
    # parent_id != None. Enumerate TOP-LEVEL only (parent_id is None) so the 1-based index matches the
    # report's per-top-level-node prefix and flat children aren't miscounted. And a sub-workflow host
    # carries no stored `sub_workflow_events` in the flat store (those exist only in the reconstructed
    # tree the report is built from), so detect a container by node_type=="WorkflowExecutor" too.
    top_level = [event for event in events if event.get("parent_id") is None]
    for i, event in enumerate(top_level, 1):
        if event.get("node_id") == this_only:
            safe_id = _safe_name(this_only)
            prefix = f"{i:02d}"
            is_container = (
                event.get("batch_items")
                or event.get("sub_workflow_events")
                or event.get("node_type") == "WorkflowExecutor"
            )
            target = (
                report_dir / f"{prefix}-{safe_id}" / "summary.md"
                if is_container
                else report_dir / f"{prefix}-{safe_id}.md"
            )
            if target.exists():
                _echo_trace(ctx, f"   → Target node: {target}")
            break


def execute_json_workflow(
    ctx: click.Context,
    workflow: dict[str, Any] | ResolvedWorkflow,
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    output_format: str = "text",
    input_sources: Mapping[str, InputSource] | None = None,
) -> None:
    """Execute a workflow through the shared Runner.

    ``execution_params`` are the supplied input values (stdin already routed in);
    ``input_sources`` says where each came from (absent key: a CLI argument).
    """
    from pflow.cli.error_output import output_error
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner

    ir_data = workflow.ir if isinstance(workflow, ResolvedWorkflow) else workflow
    params = dict(execution_params or {})

    # `_pflow_workflow_file` is injected by `WorkflowRunner._prepare_workflow`
    # via `setdefault` against the runner's own resolved file_path (canonical
    # absolute path for file/library workflows, or the synthetic `ir-hash:...`
    # identifier for inline workflows). Validate() receives the path
    # explicitly through its `source_file_path` kwarg below.

    if ctx.obj.get("dry_run"):
        _display_plan_result(ctx, workflow, params, output_format, input_sources)
        return

    if ctx.obj.get("validate_only"):
        runner = WorkflowRunner()
        vresult = runner.validate(
            workflow, params, source_file_path=ctx.obj.get("source_file_path"), input_sources=input_sources
        )
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
        # The CLI finalizes the trace itself (after set_json_output mutates it post-run), so the runner
        # must not finalize early — see _save_trace_file / _finalize_trace_and_report.
        finalize_trace=False,
        # A `pflow ui` ▶ launch sets PFLOW_EXECUTION_ID in this spawned process's env so the
        # browser can pin the overlay to the run it just spawned. POP it (not get) so a node that itself
        # shells out to `pflow` doesn't inherit the id and collide. Absent (every hand-typed run) → mint.
        execution_id=os.environ.pop("PFLOW_EXECUTION_ID", None),
    )

    if not effective_verbose:
        warnings.filterwarnings("ignore", message="Flow ends:.*", module="pflow.core.node")

    ctx.obj["total_nodes"] = len(ir_data.get("nodes", []))

    output_controller = _get_output_controller(ctx)
    progress_enabled = not print_flag
    gate_resolver = _prepare_gate_resolver(ctx, ir_data, output_controller)

    workflow_name = ctx.obj.get("workflow_name")
    result = None

    try:
        runner = WorkflowRunner()
        progress_callback = output_controller.create_progress_callback() if progress_enabled else None
        # stdout carries only the result below; stray writes during execution go to stderr.
        with reserve_stdout():
            result = runner.run(
                workflow,
                params,
                config,
                progress_callback=progress_callback,
                gate_resolver=gate_resolver,
                workflow_manager=WorkflowManager() if ctx.obj.get("workflow_source") == "library" else None,
                workflow_name=workflow_name,
                # `pflow resume` sets this before dispatching here; a normal
                # run leaves it absent (None) — the runner then behaves exactly as before.
                resume_source=ctx.obj.get("resume_source"),
                input_sources=input_sources,
                on_engine_start=partial(
                    _announce_start, ctx.obj["total_nodes"], verbose=effective_verbose, progress=progress_enabled
                ),
            )
        _display_execution_result(ctx, result, output_key, ir_data, output_format, effective_verbose)

    except click.exceptions.Exit:
        raise
    except KeyboardInterrupt:
        click.echo("\n✗ Workflow execution interrupted", err=True)
        ctx.exit(130)
    except Exception as e:
        output_error(
            exception=e,
            output_format=output_format,
            verbose=effective_verbose,
            workflow_metadata=ctx.obj.get("workflow_metadata") if ctx.obj else None,
        )
        ctx.exit(1)

    finally:
        trace = result.trace if result else None
        if trace and config.trace_enabled:
            _finalize_trace_and_report(ctx, trace)
        _cleanup_temp_files(stdin_data, effective_verbose)


def _announce_start(total_nodes: int, *, verbose: bool, progress: bool) -> None:
    """The progress header — printed once the engine starts (``on_engine_start``), so a run refused
    before it (an invalid input, a validation error) never looks like it ran."""
    nodes = count_noun(total_nodes, "node")
    if verbose:
        click.echo(f"cli: Starting workflow execution with {nodes}", err=True)
    if progress:
        click.echo(f"Executing workflow ({nodes}):", err=True)


def _prepare_gate_resolver(
    ctx: click.Context,
    ir_data: dict[str, Any],
    output_controller: OutputController,
) -> Any:
    """Build this run's gate resolver + emit the gate pre-flight warnings.

    Warnings (stderr, suppressed by -p) fire as follows:
    - an ``--auto-approve`` id matching no top-level step (typo guard — child
      gate ids are legitimate but invisible here, hence "top-level" phrasing);
    - declared gates that will fail because this run cannot prompt (fail-at-gate
      is the primary contract; this warning preserves visibility up front).
    Both scans see TOP-LEVEL nodes only — a gate inside a sub-workflow warns
    nowhere and fails at the gate (documented limitation).
    """
    from pflow.core.suggestion_utils import find_similar_items
    from pflow.execution.gate_prompt import build_gate_resolver, can_prompt

    auto_approve = frozenset(ctx.obj.get("auto_approve") or ())
    # Set only by resume's `--approve yes|no` (_dispatch_resume): a single-use answer
    # for the paused gate. Normal runs leave it None — there is no answer flag on `pflow run`.
    approval_answer = ctx.obj.get("approval_answer")
    nodes = ir_data.get("nodes", [])
    fully_answered = _fully_answered_gate_ids(ctx, nodes)
    # Defensive: schema validation (which requires "id" on every node) hasn't
    # run yet at this call site. Filtering falsy ids here (rather than at each
    # sorted() call below) keeps a malformed node dict from raising TypeError
    # on a mixed None/str sort.
    node_ids = {node.get("id") for node in nodes if node.get("id")}
    # Under --only, only the target executes (upstream is snapshot-seeded) — a gate
    # anywhere else cannot fire, so warning about it would be a false alarm.
    only_node = ctx.obj.get("only_node")
    gated = [
        node.get("id")
        for node in nodes
        if node.get("approval") and node.get("id") and (only_node is None or node.get("id") == only_node)
    ]

    if not ctx.obj.get("print_flag", False):
        for flag_id in sorted(auto_approve - node_ids):
            # This scan sees TOP-LEVEL steps only, but the resolver's namespace is
            # flat across the workflow tree — a gate inside a sub-workflow (which
            # the --dry-run footer legitimately names) matches this flag and works.
            # So this must read as a note covering both cases, never as a
            # confident "typo" verdict that contradicts the dry-run footer.
            similar = find_similar_items(flag_id, gated or sorted(node_ids), method="fuzzy", max_results=1)
            hint = f" If it is a typo: closest top-level match is '{similar[0]}'." if similar else ""
            gated_list = f" Top-level gated steps: {', '.join(gated)}." if gated else ""
            click.echo(
                f"Note: --auto-approve={flag_id} does not name a top-level step. A gate inside a "
                f"sub-workflow still matches by name.{hint}{gated_list}",
                err=True,
            )
        unapproved = [gate_id for gate_id in gated if gate_id not in fully_answered]
        if unapproved and not can_prompt(output_controller):
            flags = " ".join(f"--auto-approve={gate_id}" for gate_id in unapproved)
            # A non-interactive gate pauses durably — EXCEPT when the
            # run cannot produce a resumable trace, where it hard-fails instead:
            # --no-trace (no trace at all) and --only (its snapshot trace is not a
            # resume source). Both mirror `_gate_pausable`'s producer refusals, so
            # the pre-flight verb must match the real outcome.
            can_pause = ctx.obj.get("trace", True) and only_node is None
            outcome = "pause at" if can_pause else "fail at"
            click.echo(
                f"Warning: this run is non-interactive and will {outcome} approval "
                f"gate(s) [{', '.join(unapproved)}] unless pre-approved ({flags}).",
                err=True,
            )

    return build_gate_resolver(auto_approve, output_controller, approval_answer=approval_answer)


def _fully_answered_gate_ids(ctx: click.Context, nodes: list[dict[str, Any]]) -> frozenset[str]:
    """Gate ids a flag answers for EVERY occurrence this invocation — the pre-flight
    warning and the ``--dry-run`` footer omit these, and only these.

    ``--auto-approve`` always qualifies. Resume's single-use ``--approve`` answer
    covers ONE gate occurrence, so it qualifies unless it is a "yes" on a looping
    step: that step can raise the gate again at its next iteration (a new action —
    the run pauses there again, Task 179), so the step still belongs in the
    "will pause at" note and the ``--dry-run`` ⏸ footer. A "no" ends the run at
    the gate, so it always qualifies.
    """
    answered = frozenset(ctx.obj.get("auto_approve") or ())
    answer = ctx.obj.get("approval_answer")
    if answer is not None:
        node_id, approved = answer
        loops = any(node.get("id") == node_id and node.get("loop") for node in nodes)
        if not (approved and loops):
            answered |= {node_id}
    return answered


def _settled_outcome(
    ctx: click.Context, result: Any, output_key: str | None, ir_data: dict[str, Any], output_format: str
) -> RunOutcome:
    """Build the run's outcome with its trace settled, so its identity names a complete trace file."""
    from pflow.core.workflow.status import WorkflowStatus
    from pflow.execution.formatters.run_outcome import build_run_outcome

    trace = result.trace if ctx.obj.get("trace", True) else None
    if trace is not None and not result.success:
        # Settle identity first: a failure's trace is never mutated after the run, and a failure
        # raised before the engine opened the stream only gets its file (and so its id) here.
        _save_trace_file(ctx, trace)
    build = partial(
        build_run_outcome, result, ir_data, workflow_metadata=ctx.obj.get("workflow_metadata"), output_key=output_key
    )
    outcome = build()
    if trace is None:
        return outcome
    if output_format == "json" and outcome.status in (WorkflowStatus.SUCCESS, WorkflowStatus.DEGRADED):
        trace.set_json_output(outcome.document)  # the trailer snapshots the printed document
    _save_trace_file(ctx, trace)
    if "trace_path" in outcome.document and trace.trace_path is None:
        # Writing the trailer faulted and disabled the stream: no complete file is left to name.
        return build()
    return outcome


def _display_execution_result(
    ctx: click.Context,
    result: Any,
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    verbose: bool,
) -> None:
    """Render the run's outcome — stderr lines by tier, then its stdout data — and exit with its code."""
    from pflow.cli.workflow_output import _handle_text_output, _serialize_json_result
    from pflow.core.workflow.status import WorkflowStatus
    from pflow.execution.formatters.run_outcome import render_cli_stderr

    outcome = _settled_outcome(ctx, result, output_key, ir_data, output_format)
    succeeded = outcome.status in (WorkflowStatus.SUCCESS, WorkflowStatus.DEGRADED)

    print_flag = ctx.obj.get("print_flag", False)
    text_mode = output_format == "text"
    if text_mode and outcome.status is WorkflowStatus.PAUSED:
        # ONE parseable stdout line — it IS the paused run's data (survives -p), and it announces the
        # pause before the gate content below it.
        node_id = (outcome.document.get("gate") or {}).get("node_id")
        click.echo(f"Paused at '{node_id}'. Resume token: {result.trace.execution_id} (exit 4)")
    if verbose and succeeded:
        click.echo("cli: Workflow execution completed", err=True)
    for line in render_cli_stderr(outcome, text_mode=text_mode, print_flag=print_flag, verbose=verbose):
        click.echo(line, err=True)

    if not text_mode:
        _serialize_json_result(outcome.document, verbose)
    elif succeeded:
        _handle_text_output(result.shared_after, output_key, ir_data, verbose, print_flag, secrets=outcome.secrets)

    if outcome.exit_code:
        ctx.exit(outcome.exit_code)


def _echo_diagnostic_group(diagnostics: list[Any], *, blank_line: bool) -> None:
    """Render a group of diagnostics to stderr, optionally preceded by a blank line.

    Shared by the validation success and failure paths so warnings and INFO
    advisories are grouped and spaced consistently on both.
    """
    if not diagnostics:
        return
    if blank_line:
        click.echo("", err=True)
    for diagnostic in diagnostics:
        click.echo(format_diagnostic(diagnostic), err=True)


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
            "errors": [e.to_output_dict() for e in vresult.errors],
            "warnings": [warning.to_output_dict() for warning in vresult.warnings],
            "diagnostics": [d.to_output_dict() for d in vresult.diagnostics],
        }
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        if vresult.valid:
            from pflow.execution.formatters.validation_formatter import format_validation_success

            click.echo(format_validation_success())
            _echo_diagnostic_group(list(vresult.warnings), blank_line=False)
            _echo_diagnostic_group([d for d in vresult.diagnostics if d.severity is Severity.INFO], blank_line=True)
        else:
            from pflow.execution.formatters.validation_formatter import format_validation_failure

            click.echo(format_validation_failure(vresult.errors))
            # Separate warnings from INFO advisories with a blank line, matching the
            # success branch above (so advisories read consistently on both paths).
            _echo_diagnostic_group([d for d in vresult.diagnostics if d.severity is Severity.WARNING], blank_line=True)
            _echo_diagnostic_group([d for d in vresult.diagnostics if d.severity is Severity.INFO], blank_line=True)

    from pflow.execution.formatters.run_outcome import EXIT_REJECTED

    ctx.exit(0 if vresult.valid else EXIT_REJECTED)


def _display_plan_result(
    ctx: click.Context,
    workflow: dict[str, Any] | ResolvedWorkflow,
    params: dict[str, Any],
    output_format: str,
    input_sources: Mapping[str, InputSource] | None = None,
) -> None:
    """Display dry-run plan result and exit.

    Exit code mirrors `_display_validation_result`'s severity-based convention:
    any ERROR-severity diagnostic (e.g. unresolvable strict-mode template)
    exits ``EXIT_REJECTED`` — the run would be refused. Plans that build with only WARNINGs exit 0.
    """
    from pflow.execution.formatters.plan_formatter import format_plan_json, format_plan_text
    from pflow.execution.formatters.run_outcome import EXIT_REJECTED
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
        # `pflow resume --dry-run` sets this; a normal --dry-run leaves it None.
        resume_source=ctx.obj.get("resume_source"),
        input_sources=input_sources,
    )

    if output_format == "json":
        click.echo(json.dumps(format_plan_json(plan), indent=2, default=str))
    else:
        # Drop gates a flag already answers so the preview doesn't tell the agent to
        # pre-approve a gate it has already answered.
        ir_data = workflow.ir if isinstance(workflow, ResolvedWorkflow) else workflow
        answered_gate_ids = _fully_answered_gate_ids(ctx, ir_data.get("nodes", []))
        click.echo(format_plan_text(plan, answered_gate_ids=answered_gate_ids))

    has_error = any(d.severity == Severity.ERROR for d in plan.diagnostics)
    ctx.exit(EXIT_REJECTED if has_error else 0)


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


# pflow's own flags. They configure the run; they belong BEFORE the workflow,
# not after it. Click consumes most of these positionally (so they rarely reach
# the workflow tuple), but group-level flags like --verbose/-v land here when
# misplaced — and listing them keeps the "move it before" guidance precise.
_PFLOW_FLAGS = frozenset({
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
    "--auto-approve",
})


def _suggest_key_value(flag: str, workflow: tuple[str, ...]) -> str:
    """Build the canonical ``key=value`` suggestion for a stray ``--flag`` token.

    Pairs the flag with the token that follows it (``--scenario fail-mid`` →
    ``scenario=fail-mid``) when that token looks like a value; otherwise falls
    back to a ``key=<value>`` placeholder.
    """
    key = flag.lstrip("-")
    idx = workflow.index(flag)
    following = workflow[idx + 1] if idx + 1 < len(workflow) else None
    if following is not None and not following.startswith("-") and "=" not in following:
        return f"{key}={following}"
    return f"{key}=<value>"


def _validate_workflow_flags(workflow: tuple[str, ...]) -> None:
    """Reject option-like tokens left after the workflow name.

    After Click parses the run command, the only legal tokens are the workflow
    name/path and ``key=value`` params. Any remaining leading-dash token is an
    error — either a pflow flag placed after the workflow (move it before), or
    an unknown option (agents reflexively type ``--flag``; redirect them to
    ``key=value``). Silent-dropping these is the worst failure for an agent-first
    CLI: a green run on the wrong inputs (GH #454).

    ``--help`` is whitelisted — it routes to per-workflow help downstream
    (``_handle_named_workflow``). ``=``-bearing tokens (e.g. ``--scenario=x``)
    are left alone: those already fail loudly via the undeclared-input validator.
    """
    from pflow.core.user_errors import UserFriendlyError

    stray = [arg for arg in workflow if arg.startswith("-") and "=" not in arg and arg != "--help"]
    if not stray:
        return

    # The name/path the user typed, so suggestions are concrete and copy-pasteable.
    # `<workflow>` only when the name was omitted (workflow[0] is itself a dash).
    # Per-workflow `--help` lists inputs without requiring a separate command.
    # Quote concrete paths so every suggestion remains copy-pasteable.
    target = workflow[0] if workflow and not workflow[0].startswith("-") else "<workflow>"
    quoted_target = target if target == "<workflow>" else shlex.quote(target)

    misplaced = [arg for arg in stray if arg in _PFLOW_FLAGS]
    if misplaced:
        raise UserFriendlyError(
            title="CLI flags must come BEFORE the workflow",
            explanation=(
                f"pflow flags configure the run and must precede the workflow. Found after it: {', '.join(misplaced)}"
            ),
            suggestions=[f"pflow {misplaced[0]} {quoted_target}"],
        )

    bad = stray[0]
    if bad == "-h":
        raise UserFriendlyError(
            title="Unknown option '-h'",
            explanation="pflow uses '--help' to show a workflow's inputs and outputs.",
            suggestions=[f"pflow {quoted_target} --help"],
        )

    raise UserFriendlyError(
        title=f"Unknown option '{bad}'",
        explanation=(
            f"pflow passes workflow inputs as key=value, not --flags. "
            f"'{bad}' was not recognized and would be silently ignored."
        ),
        suggestions=[
            f"Did you mean '{_suggest_key_value(bad, workflow)}'?",
            f"See this workflow's inputs: pflow {quoted_target} --help",
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
    workflow_ir: dict[str, Any],
    params: dict[str, Any],
) -> tuple[str | None, str | StdinData | None]:
    """Read stdin into the input marked ``stdin: true``: ``(routed input name, what was read)``.

    The workflow's only stdin reader. Nothing is read unless an input is marked ``stdin: true``
    and no argument already supplied it, so an open pipe or file a workflow never asked for is
    left untouched — it can neither hang nor fail the run.
    """
    target_input = _find_stdin_input(workflow_ir)
    if target_input is None or target_input in params:
        return None, None

    stdin_data = _read_stdin_data()
    stdin_text = _extract_stdin_text(stdin_data)
    if stdin_text is None:
        if isinstance(stdin_data, StdinData) and (stdin_data.binary_data or stdin_data.temp_path):
            click.echo("⚠️  Stdin contains binary or large data", err=True)
            click.echo("   Binary/large data is not automatically routed to workflow inputs.", err=True)
            click.echo("   Consider using a file path parameter instead.", err=True)
            click.echo("", err=True)
        return None, stdin_data
    params[target_input] = stdin_text
    return target_input, stdin_data


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


def _validate_report_dir_before_execution(report_dir: str | None) -> None:
    """Refuse unsafe explicit report output before running workflow side effects."""
    if report_dir is None:
        return

    from pflow.core.trace_report import validate_report_output_dir

    validate_report_output_dir(report_dir, allow_unmarked_existing=False)


def _validate_and_prepare_workflow_params(
    workflow_ir: dict[str, Any],
    remaining_args: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, InputSource], str | StdinData | None]:
    """Validate parameter names and route stdin: ``(params, input_sources, stdin_data)`` — every
    value is text; the stdin-routed input is labelled ``stdin``, the rest are CLI arguments.
    ``stdin_data`` is what was read from stdin (None when nothing was), kept for temp-file cleanup."""
    params: dict[str, Any] = dict(parse_workflow_params(remaining_args))

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

    stdin_input, stdin_data = _route_stdin_to_params(workflow_ir, params)
    return params, ({stdin_input: "stdin"} if stdin_input is not None else {}), stdin_data


def _show_workflow_help(first_arg: str, resolved: ResolvedWorkflow) -> None:
    """Display the workflow's interface — what ``pflow describe`` shows, plus where it was loaded from."""
    from pflow.cli.workflow_interface import format_workflow_interface_for_cli, resolved_interface_metadata

    library = resolved.source == "library"
    name = os.path.basename(first_arg) if "/" in first_arg else first_arg
    click.echo(
        format_workflow_interface_for_cli(
            name,
            resolved_interface_metadata(resolved),
            example_name=name if library else shlex.quote(first_arg),
            source="Saved workflow" if library else first_arg,
        )
    )


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
        _show_workflow_help(first_arg, resolved_workflow)
        return True

    params, input_sources, stdin_data = _validate_and_prepare_workflow_params(workflow_ir, remaining_args)

    if verbose:
        if source == "library":
            click.echo(f"cli: Loading workflow '{first_arg}' from registry", err=True)
        else:
            click.echo(f"cli: Loading workflow from file: {first_arg}", err=True)
        if params:
            from pflow.core.security_utils import redact_for_display, scrub_secret_values, secret_values

            redacted = {name: redact_for_display([name], value) for name, value in params.items()}
            shown = scrub_secret_values(redacted, secret_values(params))
            click.echo(f"cli: With parameters: {shown}", err=True)

    _setup_workflow_execution(ctx, first_arg, source, output_format)
    execute_json_workflow(ctx, resolved_workflow, stdin_data, output_key, params, output_format, input_sources)
    return True


def _inject_settings_env_vars() -> None:
    """Inject API keys from pflow settings into environment."""
    from pflow.core.llm_config import inject_settings_env_vars

    inject_settings_env_vars()


def _try_execute_named_workflow(
    ctx: click.Context,
    workflow: tuple[str, ...],
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
    if _handle_named_workflow(ctx, first_arg, workflow[1:], output_key, output_format, verbose, resolved):
        return True
    raise WorkflowNotFoundError(first_arg, similar_names=[])


# Verbs that mean `--validate-only`. Other CLIs spell validation as a subcommand
# (`terraform validate`, `cargo check`), so `pflow validate <wf>` is the natural
# guess. pflow has no such subcommand — validation is a run-mode flag — so these
# words are reserved: a bare `pflow validate` redirects rather than running a
# workflow named "validate" (run that via its file path). `lint` is intentionally
# excluded — it's reserved for the planned linting feature (Task 118).
_VALIDATION_VERBS = frozenset({"validate", "check"})


def _redirect_validation_verb(workflow: tuple[str, ...]) -> None:
    """Redirect `pflow validate <wf>` to `pflow <wf> --validate-only`.

    No-op unless the first token is a validation verb. Reconstructs the user's
    intended target (and any params) from the remaining tokens so the suggestion
    is copy-pasteable.
    """
    from pflow.core.user_errors import UserFriendlyError

    if not workflow or workflow[0].lower() not in _VALIDATION_VERBS:
        return

    verb = workflow[0]
    target = " ".join(workflow[1:]) if len(workflow) > 1 else "<workflow>"
    raise UserFriendlyError(
        title=f"pflow has no '{verb}' command — use the --validate-only flag",
        explanation=(
            "Validation is a flag on the workflow you want to check, not a "
            "subcommand. Pass --validate-only (params are still accepted)."
        ),
        suggestions=[
            f"pflow {target} --validate-only",
        ],
    )


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
@click.option(
    "--cache/--no-cache",
    default=True,
    help=(
        "Enable/disable pflow's local memoization layer (default: enabled). "
        "Does NOT disable LLM provider prompt caching declared via "
        "`prompt_cache:` / `## Cache` (those fire regardless). "
        "See `pflow guide prompt-caching` for the two-layer model."
    ),
)
@click.option(
    "--only",
    "only_node",
    default=None,
    help="Re-run just this node against a snapshot of the most recent full run — upstream is restored, not re-executed, so side-effecting upstream does not re-fire. Requires a prior full run (errors otherwise). Targeting a node inside a sub-workflow is not supported. A loop node runs one iteration.",
)
@click.option(
    "--auto-approve",
    "auto_approve",
    multiple=True,
    metavar="NODE_ID",
    help=(
        "Pre-approve ONE approval gate by step name (repeatable; no blanket form). "
        "For AI agents: ask your human before passing this — the gate exists so a "
        "person reviews the action. Escalations cannot be pre-approved."
    ),
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
    auto_approve: tuple[str, ...],
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
        _validate_report_dir_before_execution(report_dir)
        ctx.obj["dry_run"] = dry_run
        ctx.obj["report"] = report_dir or ("auto" if report_enabled else None)
        ctx.obj["cache"] = cache
        ctx.obj["only_node"] = only_node
        ctx.obj["auto_approve"] = auto_approve
        # Only resume's `--approve yes|no` populates this (no answer flag on run).
        ctx.obj["approval_answer"] = None

        output_format = ctx.obj.get("output_format", "text")
        verbose = ctx.obj.get("verbose", False)

        # Normalize the optional leading "run" token first so the flag guard
        # sees the real workflow name at workflow[0] (concrete suggestions).
        workflow = _preprocess_run_prefix(workflow)
        _validate_workflow_flags(workflow)

        raw_input = " ".join(workflow) if workflow else ""
        ctx.obj["workflow_text"] = raw_input

        # `pflow validate <wf>` is a guessed command, not a real one — redirect to
        # the --validate-only flag before we try to resolve it as a workflow name.
        _redirect_validation_verb(workflow)

        if _try_execute_named_workflow(ctx, workflow, output_key, output_format, verbose):
            return

        _handle_invalid_workflow_input(workflow)
    except click.exceptions.Exit:
        raise
    except Exception as e:
        # Every exception reaching here was raised before a run existed (a run's own ending,
        # and anything escaping it, exits inside execute_json_workflow): a wrong call.
        from pflow.cli.error_output import output_error
        from pflow.execution.formatters.run_outcome import EXIT_REJECTED

        of = ctx.obj.get("output_format", "text") if ctx.obj else output_format
        vb = ctx.obj.get("verbose", False) if ctx.obj else False
        wm = ctx.obj.get("workflow_metadata") if ctx.obj else None
        output_error(exception=e, output_format=of, verbose=vb, workflow_metadata=wm)
        ctx.exit(EXIT_REJECTED)
