"""``pflow resume`` — resume a failed, interrupted, or PAUSED run (Tasks 164 + 171).

The CLI half of resume is now a thin click shell: the click-free refusal gates
(target disambiguation → ``load_resume_source`` ladder → workflow-changed hash →
between-nodes entry resolution → side-effect verdict) live in
``execution/resume_preflight.py`` — shared with the UI server's ``POST
/api/resume`` (Task 176). This module keeps what only a terminal can do (the
interactive side-effect confirm) plus flag parsing, merges the original inputs
with any ``key=value`` overrides, and dispatches through ``run.py``'s
``execute_json_workflow`` so a resumed run reuses the exact same execution +
output + trace-finalization pipeline as a normal run (it only rides a
``resume_source`` on ``ctx.obj``). The engine seeds upstream from the source
trace and re-enters the walk at K — see ``runtime/engine/engine.py:_prepare_resume``.

Task 171 made ``resume`` a GROUP (``ResumeGroup``): the hidden ``run``
subcommand is the default form (``pflow resume <target> …`` routes to it
unchanged) and ``list`` shows pending paused runs. A paused source requires the
gate's answer — ``--approve yes|no`` for approvals (delivered by priming the
resume run's resolver: auto-approve set for yes, deny set for no) or
``--choose`` for escalations (folded into the restored marker by the loader;
the escalating step is never re-executed).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from pflow.core.exceptions import ResumeSideEffectConfirmationError
    from pflow.execution.result import ResolvedWorkflow
    from pflow.runtime.resume_source import ResumeSource

logger = logging.getLogger(__name__)


def _split_target_and_params(args: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    """Split the raw arg tuple into (TARGET, params). TARGET is required (§E)."""
    from pflow.cli.param_parsing import parse_workflow_params

    positional = [arg for arg in args if "=" not in arg]
    stray = [arg for arg in positional if arg.startswith("-")]
    if stray:
        raise click.UsageError(f"Unknown option '{stray[0]}'. Workflow inputs are passed as key=value, not --flags.")
    if not positional:
        raise click.UsageError(
            "Missing TARGET. Pass a workflow (name or path) — resumes its newest failed run — "
            "or an execution id — resumes that exact attempt."
        )
    if len(positional) > 1:
        raise click.UsageError(
            f"Unexpected extra argument '{positional[1]}'. Pass exactly one TARGET, then key=value inputs."
        )
    return positional[0], parse_workflow_params(args)


def _prompt_or_raise_side_effect(
    ctx: click.Context,
    refusal: ResumeSideEffectConfirmationError,
    print_flag: bool,
) -> None:
    """The interactive tail of the side-effecting-K policy (Decision 4 / §E step 5).

    The VERDICT (which entries need confirmation) is ``preflight_resume``'s — shared with the UI
    server. This is the one part only a TTY can do: with a real terminal, confirm ``[y/N]``
    (default No); non-interactive (agent/MCP/pipe), raise the pre-built refusal loudly.
    """
    from pflow.core.output_controller import OutputController
    from pflow.execution.gate_prompt import can_prompt

    controller = OutputController(print_flag=print_flag)
    if can_prompt(controller):
        controller.prepare_for_prompt()
        confirmed = click.confirm(
            f"Resuming re-runs step '{refusal.node_id}' (a {refusal.node_type} step) "
            "and its side effects may fire again. Continue?",
            default=False,
            err=True,
        )
        if not confirmed:
            click.echo("Resume cancelled.", err=True)
            ctx.exit(1)
        return
    raise refusal


def _build_gate_answer(approve: str | None, choose: str | None) -> dict[str, Any] | None:
    """The Phase-2 loader answer contract: ``{"approve": bool}`` | ``{"chosen": raw, "notes": None}``.

    The loader validates kind-match against the paused gate and maps numeric
    ``--choose`` values to option labels — the CLI passes the raw string.
    """
    if approve is not None and choose is not None:
        raise click.UsageError(
            "--approve and --choose are mutually exclusive: an approval gate takes "
            "--approve yes|no, an escalation takes --choose."
        )
    if approve is not None:
        return {"approve": approve == "yes"}
    if choose is not None:
        return {"chosen": choose, "notes": None}
    return None


def _prime_approval_delivery(
    approve: str | None, auto_approve: tuple[str, ...], source: ResumeSource
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Turn a validated ``--approve`` answer into resolver priming: ``(auto_approve, gate_deny)``.

    The source is paused-approval iff ``approve`` survived the loader. "yes"
    primes the resolver's auto-approve set with the gated node — the gate
    re-fires in the resume run and resolves via flag, writing an honest approved
    resolution line. "no" primes the deny set → ``GateDenied`` → the EXISTING
    denied machinery (denied attempt trace, exit 3) — which also CONSUMES the
    token (a verdict resolution line supersedes the source).
    """
    if approve is None or source.paused_node_id is None:
        return auto_approve, ()
    if approve == "yes":
        return (*auto_approve, source.paused_node_id), ()
    if source.paused_node_id in auto_approve:
        raise click.UsageError(f"--approve no contradicts --auto-approve={source.paused_node_id} — drop one.")
    return auto_approve, (source.paused_node_id,)


def _workflow_display_name(resolved: ResolvedWorkflow) -> str | None:
    """Derive a display/library name from the resolved workflow, mirroring run.py."""
    from pathlib import Path

    if not resolved.file_path:
        return None
    stem = Path(resolved.file_path).stem
    return stem[:-6] if stem.endswith(".pflow") else stem


def _dispatch_resume(
    ctx: click.Context,
    resolved: ResolvedWorkflow,
    source: ResumeSource,
    params: dict[str, Any],
    *,
    output_format: str,
    print_flag: bool,
    no_trace: bool,
    cache: bool,
    auto_approve: tuple[str, ...],
    gate_deny: tuple[str, ...] = (),
    dry_run: bool,
) -> None:
    """Set up ctx.obj like a normal run and dispatch through the shared pipeline (§E step 7)."""
    from pflow.cli.commands.run import execute_json_workflow
    from pflow.cli.workflow_output import _create_workflow_metadata
    from pflow.core.output_controller import OutputController

    if ctx.obj is None:
        ctx.obj = {}

    name = _workflow_display_name(resolved)
    is_library = resolved.source == "library"

    ctx.obj["output_key"] = None
    ctx.obj["output_format"] = output_format
    ctx.obj["print_flag"] = print_flag
    ctx.obj["trace"] = not no_trace
    ctx.obj["validate_only"] = False
    ctx.obj["dry_run"] = dry_run
    ctx.obj["report"] = None
    ctx.obj["cache"] = cache
    ctx.obj["only_node"] = None
    ctx.obj["auto_approve"] = auto_approve
    # Task 171: non-empty only for `--approve no` — pre-denies the paused gate so it
    # re-fires denied in the resume run (→ denied attempt trace, exit 3).
    ctx.obj["gate_deny"] = gate_deny
    ctx.obj["output_controller"] = OutputController(print_flag=print_flag)
    ctx.obj["workflow_source"] = resolved.source
    ctx.obj["workflow_name"] = name
    ctx.obj["source_file_path"] = resolved.file_path
    ctx.obj["workflow_metadata"] = _create_workflow_metadata(name, "reused" if is_library else "unsaved")
    # The one thing that makes this a resume: the runner threads it to the engine.
    ctx.obj["resume_source"] = source

    execute_json_workflow(ctx, resolved, None, None, params, output_format)


class ResumeGroup(click.Group):
    """Group that routes anything but a known subcommand to the hidden ``run`` default.

    ``pflow resume <target> …`` (the overwhelmingly common form) must keep working
    unchanged, so an unknown first arg — a workflow name, path, or execution id —
    forwards the WHOLE arg vector to ``run``. Same pattern as the root ``PflowCLI``.
    """

    # LOAD-BEARING: lets option tokens that precede the TARGET (`resume --approve
    # yes <id>`) survive the group's own parser and reach the run subcommand.
    # Consequence (same GH#454 tradeoff as the root group): an unknown flag is
    # forwarded rather than erroring here — `_split_target_and_params` rejects it
    # one layer down. `allow_interspersed_args` lives on the SUBCOMMAND, not here
    # (verified: a group-level setting is inert for this routing shape).
    ignore_unknown_options = True

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if args and args[0] in self.commands:
            return super().resolve_command(ctx, args)
        return "run", self.get_command(ctx, "run"), args


@click.group(cls=ResumeGroup, name="resume")
def resume() -> None:
    """Resume a paused or failed run.

    \b
    Forms:
      pflow resume <TARGET> [KEY=VALUE]... [FLAGS]   resume a run (default form)
      pflow resume list                              pending paused runs

    TARGET is a workflow (name or path) — resumes its newest resumable run — or
    an execution id — resumes that exact attempt. KEY=VALUE overrides the
    original run's inputs.

    \b
    Flags on the default form:
      --approve yes|no        answer a paused approval gate ("no" denies cleanly, exit 3)
      --choose "ANSWER"       answer a paused escalation (option number or free text)
      --force                 bypass the side-effect confirm + edited-workflow check
      --dry-run               preview the resumed tail without executing
      --auto-approve NODE_ID  pre-approve ONE downstream approval gate (repeatable)
      --output-format text|json / -p / --no-trace / --cache/--no-cache

    \b
    Answering a paused gate:
      pflow my-workflow                # exits 4: Paused at 'deploy'. Resume token: <id>
      pflow resume <id> --approve yes  # runs the gated step and continues

    A workflow literally named "run" or "list" collides with the subcommands —
    resume it by path or execution id instead.
    """


@resume.command(
    name="run",
    hidden=True,
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": True},
)
@click.pass_context
@click.option(
    "--force",
    is_flag=True,
    help="Bypass the side-effect confirmation and the edited-workflow check.",
)
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format: text (default) or json.",
)
@click.option(
    "-p",
    "--print",
    "print_flag",
    is_flag=True,
    help="Minimal output: suppress header, summary, and warnings on stderr.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Preview the resumed tail (cost + cache plan from the failed step onward) without executing.",
)
@click.option("--no-trace", is_flag=True, help="Disable trace saving for the resumed attempt.")
@click.option(
    "--cache/--no-cache",
    default=True,
    help="Enable/disable pflow's local memoization layer for the resumed tail (default: enabled).",
)
@click.option(
    "--auto-approve",
    "auto_approve",
    multiple=True,
    metavar="NODE_ID",
    help="Pre-approve ONE downstream approval gate by step name (repeatable). Resume does not inherit prior approvals.",
)
@click.option(
    "--approve",
    type=click.Choice(["yes", "no"], case_sensitive=False),
    default=None,
    help='Answer a paused APPROVAL gate: "yes" runs the gated step, "no" denies it cleanly (exit 3).',
)
@click.option(
    "--choose",
    "choose",
    default=None,
    metavar="ANSWER",
    help="Answer a paused ESCALATION: an option number (as shown at pause time) or free text.",
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def resume_run(
    ctx: click.Context,
    force: bool,
    output_format: str,
    print_flag: bool,
    dry_run: bool,
    no_trace: bool,
    cache: bool,
    auto_approve: tuple[str, ...],
    approve: str | None,
    choose: str | None,
    args: tuple[str, ...],
) -> None:
    """Resume a paused or failed run from where it stopped (the group's default form).

    Hidden — ``pflow resume <target>`` routes here; the user-facing help lives on
    the group. The entry's upstream outputs are restored from the saved run (not
    re-executed) and execution continues from the entry onward. A PAUSED source
    additionally requires the gate's answer (--approve / --choose).
    """
    from pflow.cli.error_output import output_error

    try:
        from pflow.core.llm_config import inject_settings_env_vars

        inject_settings_env_vars()

        from pflow.execution.resume_preflight import preflight_resume

        gate_answer = _build_gate_answer(approve, choose)
        target, cli_params = _split_target_and_params(args)
        # Every click-free refusal gate (load ladder → hash gate → between-nodes entry →
        # side-effect verdict) lives in preflight_resume — shared with the UI server's
        # POST /api/resume (Task 176), which must refuse exactly as this command does.
        pf = preflight_resume(target, gate_answer=gate_answer, force=force)
        auto_approve, gate_deny = _prime_approval_delivery(approve, auto_approve, pf.source)

        # A --dry-run never runs K, so nothing can fire — the verdict is ignored.
        # (The stale-workflow gate DID apply above: preview mirrors a real resume.)
        if not dry_run and pf.side_effect_refusal is not None:
            _prompt_or_raise_side_effect(ctx, pf.side_effect_refusal, print_flag)

        # CLI overrides win over the original run's recorded inputs (Decision 9).
        params = {**(pf.source.inputs or {}), **cli_params}
        _dispatch_resume(
            ctx,
            pf.resolved,
            pf.source,
            params,
            output_format=output_format,
            print_flag=print_flag,
            no_trace=no_trace,
            cache=cache,
            auto_approve=auto_approve,
            gate_deny=gate_deny,
            dry_run=dry_run,
        )
    except click.exceptions.Exit:
        raise
    except click.exceptions.UsageError:
        raise
    except Exception as exc:
        of = ctx.obj.get("output_format", output_format) if ctx.obj else output_format
        vb = ctx.obj.get("verbose", False) if ctx.obj else False
        output_error(ctx, exception=exc, output_format=of, verbose=vb)
        ctx.exit(1)


def _format_age(seconds: float) -> str:
    """Compact age buckets for the list's AGE column: ``42s`` / ``5m`` / ``3h`` / ``2d``.

    Local to this renderer — no shared relative-time helper exists (verified;
    ``core/duration_format.format_duration`` speaks milliseconds-of-duration,
    not age). Promote if a second consumer appears.
    """
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def _age_of(paused_at: str | None) -> str:
    """Render a trailer ``end_time`` ISO stamp as an age, ``?`` when absent/unparseable."""
    from datetime import datetime

    if not paused_at:
        return "?"
    try:
        then = datetime.fromisoformat(paused_at)
    except ValueError:
        return "?"
    return _format_age((datetime.now() - then).total_seconds())


def _gate_kind_label(kind: str | None) -> str:
    """Human word for a gate kind constant; an unknown kind renders verbatim, never hides."""
    from pflow.core.gate import GATE_KIND_APPROVAL, GATE_KIND_ESCALATION

    if kind == GATE_KIND_APPROVAL:
        return "approval"
    if kind == GATE_KIND_ESCALATION:
        return "escalation"
    return kind or "?"


@resume.command(name="list")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format: text (default) or json.",
)
def resume_list(output_format: str) -> None:
    """Show pending paused runs — gates awaiting a human answer.

    Each row is a live obligation: a run that stopped at an approval or
    escalation gate and has not been answered (or superseded by a newer
    attempt). Answer with the footer's kind-correct command.
    """
    import json

    from pflow.execution.gate_prompt import format_resume_answer_command
    from pflow.runtime.resume_source import list_paused_runs

    runs = list_paused_runs()

    if output_format.lower() == "json":
        document = [
            {
                "execution_id": run.execution_id,
                "workflow_name": run.workflow_name,
                "workflow_path": run.workflow_path,
                "paused_node_id": run.paused_node_id,
                "gate_kind": run.gate_kind,
                "paused_at": run.paused_at,
                "path": str(run.path),
                "resume_command": format_resume_answer_command(run.execution_id, {"kind": run.gate_kind}),
            }
            for run in runs
        ]
        click.echo(json.dumps(document, indent=2))
        return

    if not runs:
        click.echo("No paused runs.")
        return

    headers = ("TOKEN", "WORKFLOW", "PAUSED AT", "GATE", "AGE")
    rows = [
        (
            run.execution_id,
            run.workflow_name or "?",
            run.paused_node_id,
            _gate_kind_label(run.gate_kind),
            _age_of(run.paused_at),
        )
        for run in runs
    ]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    click.echo("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip())
    for row in rows:
        click.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    click.echo("")
    # A single footer template would be WRONG for a mixed list (approvals take
    # --approve, escalations take --choose) — one line per kind present, verb
    # pairing from the ONE home (format_resume_answer_command).
    for kind in dict.fromkeys(run.gate_kind for run in runs):
        click.echo(f"To answer: {format_resume_answer_command('<TOKEN>', {'kind': kind})}")
