"""``pflow resume`` — resume a failed or interrupted run from the step that failed (Task 164).

The CLI half of resume: it loads and vets a prior run's trace via
``load_resume_source`` (all refusal policy lives there), re-resolves the
workflow, gates on the workflow-changed hash and the side-effect confirmation
(Decision 4), merges the original inputs with any ``key=value`` overrides, and
then dispatches through ``run.py``'s ``execute_json_workflow`` so a resumed run
reuses the exact same execution + output + trace-finalization pipeline as a
normal run (it only rides a ``resume_source`` on ``ctx.obj``). The engine seeds
upstream from the source trace and re-enters the walk at K — see
``runtime/engine/engine.py:_prepare_resume``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import click

from pflow.core.exceptions import (
    ResumeNotResumableError,
    ResumeSideEffectConfirmationError,
    ResumeSourceMissingError,
    ResumeStaleWorkflowError,
    WorkflowNotFoundError,
)

if TYPE_CHECKING:
    from pflow.execution.result import ResolvedWorkflow
    from pflow.runtime.resume_source import ResumeSource

logger = logging.getLogger(__name__)

# An execution id is a uuid4 — distinguishable in shape from a workflow name, but
# NOT collision-proof (`validate_workflow_name` accepts uuid4-shaped names), so
# TARGET disambiguation is existence-based (try the run id first, fall back to a
# workflow name) rather than trusting the shape alone (§E step 2).
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


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


def _resolve_from_source(source: ResumeSource) -> ResolvedWorkflow:
    """Re-resolve the workflow a by-execution-id source came from, via its recorded path."""
    from pflow.execution.workflow_resolver import resolve_workflow

    wf_path = source.workflow_path
    if not wf_path:
        raise ResumeNotResumableError(
            "The saved run does not record which workflow it came from, so it cannot be re-resolved.",
            execution_id=source.execution_id,
            trace_path=str(source.path),
            suggestions=["Resume by workflow name or path instead of execution id."],
        )
    try:
        return resolve_workflow(wf_path)
    except WorkflowNotFoundError:
        raise ResumeSourceMissingError(
            f"The workflow for this run no longer exists at '{wf_path}'.",
            execution_id=source.execution_id,
            trace_path=str(source.path),
            suggestions=["Restore the workflow file, or re-run it from its current location."],
        ) from None


def _load_source_and_workflow(target: str) -> tuple[ResumeSource, ResolvedWorkflow]:
    """Disambiguate TARGET (existence-based) into (source, resolved_workflow) — §E step 2."""
    from pflow.execution.runner import workflow_path_id
    from pflow.execution.workflow_resolver import resolve_workflow
    from pflow.runtime.resume_source import load_resume_source

    if _UUID_RE.match(target):
        try:
            source = load_resume_source(execution_id=target)
        except ResumeSourceMissingError:
            # No run with that id — maybe it's a workflow whose NAME is uuid-shaped.
            # Fall through to the workflow arm; if THAT also misses, re-raise a
            # combined missing error (never leak resolve_workflow's "did you mean"
            # suggestions, which point at the wrong namespace for a mistyped run id).
            try:
                resolved = resolve_workflow(target)
            except WorkflowNotFoundError:
                raise ResumeSourceMissingError(
                    f"No run with execution id '{target}' was found, and no workflow by that name exists.",
                    execution_id=target,
                    suggestions=[
                        "Check the execution id from the failed run's output, "
                        "or pass the workflow name/path to resume its newest failed run."
                    ],
                ) from None
            return load_resume_source(workflow_path=workflow_path_id(resolved)), resolved
        return source, _resolve_from_source(source)

    resolved = resolve_workflow(target)
    return load_resume_source(workflow_path=workflow_path_id(resolved)), resolved


def _check_content_hash(resolved: ResolvedWorkflow, source: ResumeSource, *, force: bool) -> None:
    """Refuse a resume whose workflow changed since the failed run, unless --force (§E step 3)."""
    if force:
        return
    from pflow.core.workflow_id import workflow_content_hash

    current_hash = workflow_content_hash(resolved.ir)
    # A missing source hash (a run predating Task-173 hash tracking) is treated as
    # a mismatch — we cannot prove the workflow is unchanged — but the error says
    # exactly that, never claiming an edit that may not have happened.
    if current_hash != source.content_hash:
        raise ResumeStaleWorkflowError(
            hash_known=source.content_hash is not None,
            execution_id=source.execution_id,
            trace_path=str(source.path),
        )


def _node_registry_type(ir: dict[str, Any], node_id: str | None) -> str | None:
    """The IR REGISTRY type (``"llm"``/``"shell"``/...) of K — never a trace event's class name."""
    for node in ir.get("nodes", []):
        if node.get("id") == node_id:
            node_type = node.get("type")
            return node_type if isinstance(node_type, str) else None
    return None


def _node_has_loop(ir: dict[str, Any], node_id: str | None) -> bool:
    """Whether ``node_id`` is a ``loop:`` node — its next step is condition-determined.

    A loop node re-enters itself until its ``while:``/``until:`` condition flips;
    that re-entry is engine-ephemeral, never a graph edge, so the only DECLARED
    edge out of a loop node is its exit route. After a loop iteration completes,
    the next step is "another iteration" or "the exit successor" — decided by the
    runtime condition, which an interrupted trace never records.
    """
    for node in ir.get("nodes", []):
        if node.get("id") == node_id:
            return node.get("loop") is not None
    return False


def _single_default_successor(ir: dict[str, Any], node_id: str) -> str | None:
    """The one node reached by ``node_id``'s DEFAULT (unconditional) edge, or None if 0/ambiguous.

    Named-action and ``error`` edges are not default routes (they encode branches /
    failure handling, not the success fall-through the killed-between-nodes case
    needs). Zero default edges (terminal / conditional-only) or more than one →
    None (ambiguous). ``from``/``to`` and ``source``/``target`` edge spellings are
    both accepted (the compiler supports both).
    """
    targets: list[str] = []
    for edge in ir.get("edges", []):
        source = edge.get("from") or edge.get("source")
        if source != node_id or edge.get("action", "default") != "default":
            continue
        target = edge.get("to") or edge.get("target")
        if isinstance(target, str):
            targets.append(target)
    unique = list(dict.fromkeys(targets))
    return unique[0] if len(unique) == 1 else None


def _resolve_between_nodes_entry(resolved: ResolvedWorkflow, source: ResumeSource) -> ResumeSource:
    """Resolve the entry for a killed-BETWEEN-nodes incomplete run (§E step 4, Decision 7).

    The run stopped after ``last_completed_node_id`` completed but before the next
    node started, so its successor was never traced. Resume only when that
    successor is UNAMBIGUOUS: refuse a dynamic router (only a ``code`` node routes
    at runtime — its taken route was never recorded, so even a single declared
    edge can be wrong) and refuse zero/multiple default successors. Otherwise pin
    the entry to the single default successor.
    """
    import dataclasses

    last = source.last_completed_node_id
    node_type = _node_registry_type(resolved.ir, last)
    if node_type is None:
        raise ResumeNotResumableError(
            f"The last completed step '{last}' no longer exists in the workflow, so its next step "
            "cannot be determined.",
            execution_id=source.execution_id,
            trace_path=str(source.path),
            suggestions=["Re-run the workflow from the start."],
        )
    if node_type == "code":
        raise ResumeNotResumableError(
            f"The run was interrupted after step '{last}', which routes dynamically — its next step "
            "was never recorded, so resume cannot tell where to continue.",
            execution_id=source.execution_id,
            trace_path=str(source.path),
            node_id=last,
            suggestions=["Re-run the workflow from the start."],
        )
    # A loop node's continuation is condition-determined and untraced. A `code` loop node
    # is already refused above (dynamic router); this arm covers the NON-code loop shapes
    # the code arm misses — notably a `workflow`-type node looping on a child's typed output.
    if _node_has_loop(resolved.ir, last):
        raise ResumeNotResumableError(
            f"The run was interrupted after loop step '{last}', whose next step depends on the loop "
            "condition (another iteration or the exit route) and was never recorded, so resume "
            "cannot tell where to continue.",
            execution_id=source.execution_id,
            trace_path=str(source.path),
            node_id=last,
            suggestions=["Re-run the workflow from the start."],
        )
    successor = _single_default_successor(resolved.ir, str(last))
    if successor is None:
        raise ResumeNotResumableError(
            f"The run was interrupted after step '{last}', and its next step is ambiguous "
            "(no single default route), so resume cannot tell where to continue.",
            execution_id=source.execution_id,
            trace_path=str(source.path),
            node_id=last,
            suggestions=["Re-run the workflow from the start."],
        )
    return dataclasses.replace(source, entry_node_id=successor)


def _confirm_or_refuse_side_effect(
    ctx: click.Context,
    resolved: ResolvedWorkflow,
    source: ResumeSource,
    *,
    force: bool,
    print_flag: bool,
) -> None:
    """Apply the side-effecting-K policy (Decision 4 / §E step 5).

    Idempotent K (``llm``) resumes silently. A side-effecting K re-runs with
    at-least-once semantics, so: with a real terminal, confirm ``[y/N]`` (default
    No); non-interactive (agent/MCP/pipe), refuse loudly with an actionable error
    naming K + its type. ``--force`` bypasses both. K's type is read from the
    CURRENT resolved IR (registry vocabulary), never from a trace event.
    """
    if force:
        return
    from pflow.execution.gate_prompt import can_prompt
    from pflow.runtime.compilation import is_side_effecting

    entry = source.entry_node_id
    node_type = _node_registry_type(resolved.ir, entry)
    # None => K was removed/renamed since the run (only reachable if the hash gate
    # was bypassed) — the engine refuses with a K-removed error before any node
    # runs, so no side effect fires; nothing to confirm here.
    if node_type is None or not is_side_effecting(node_type):
        return

    from pflow.core.output_controller import OutputController

    controller = OutputController(print_flag=print_flag)
    if can_prompt(controller):
        controller.prepare_for_prompt()
        confirmed = click.confirm(
            f"Resuming re-runs step '{entry}' (a {node_type} step) and its side effects may fire again. Continue?",
            default=False,
            err=True,
        )
        if not confirmed:
            click.echo("Resume cancelled.", err=True)
            ctx.exit(1)
        return
    raise ResumeSideEffectConfirmationError(
        str(entry),
        node_type,
        execution_id=source.execution_id,
        trace_path=str(source.path),
    )


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
    ctx.obj["output_controller"] = OutputController(print_flag=print_flag)
    ctx.obj["workflow_source"] = resolved.source
    ctx.obj["workflow_name"] = name
    ctx.obj["source_file_path"] = resolved.file_path
    ctx.obj["workflow_metadata"] = _create_workflow_metadata(name, "reused" if is_library else "unsaved")
    # The one thing that makes this a resume: the runner threads it to the engine.
    ctx.obj["resume_source"] = source

    execute_json_workflow(ctx, resolved, None, None, params, output_format)


@click.command(
    name="resume",
    context_settings={"allow_interspersed_args": True},
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
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def resume_cmd(
    ctx: click.Context,
    force: bool,
    output_format: str,
    print_flag: bool,
    dry_run: bool,
    no_trace: bool,
    cache: bool,
    auto_approve: tuple[str, ...],
    args: tuple[str, ...],
) -> None:
    """Resume a failed or interrupted run from the step that failed.

    TARGET is a workflow (name or path) — resumes its newest failed run — or an
    execution id — resumes that exact attempt. KEY=VALUE overrides the original
    run's inputs. --force bypasses the side-effect confirmation and the
    edited-workflow check.

    The failed step's upstream outputs are restored from the saved run (not
    re-executed) and execution continues from the failed step onward.
    """
    from pflow.cli.error_output import output_error

    try:
        from pflow.core.llm_config import inject_settings_env_vars

        inject_settings_env_vars()

        target, cli_params = _split_target_and_params(args)
        source, resolved = _load_source_and_workflow(target)

        # The stale-workflow gate applies to --dry-run too (preview mirrors what a
        # real resume would do), but the side-effect confirmation does NOT: a
        # dry-run never runs K, so nothing can fire.
        _check_content_hash(resolved, source, force=force)
        # A killed-BETWEEN-nodes incomplete run (Decision 7) has no failed step K —
        # resolve its unambiguous successor against the (hash-checked) workflow.
        if source.entry_node_id is None:
            source = _resolve_between_nodes_entry(resolved, source)
        if not dry_run:
            _confirm_or_refuse_side_effect(ctx, resolved, source, force=force, print_flag=print_flag)

        # CLI overrides win over the original run's recorded inputs (Decision 9).
        params = {**(source.inputs or {}), **cli_params}
        _dispatch_resume(
            ctx,
            resolved,
            source,
            params,
            output_format=output_format,
            print_flag=print_flag,
            no_trace=no_trace,
            cache=cache,
            auto_approve=auto_approve,
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
