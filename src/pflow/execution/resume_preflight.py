"""The click-free resume pre-flight — every refusal a resume raises, minus the terminal (Task 176).

Extracted from ``cli/commands/resume.py`` when its second consumer appeared (the 171 "extract the
rule when the second consumer appears" pattern): the UI server's ``POST /api/resume`` must apply the
EXACT refusal policy a spawned non-TTY ``pflow resume`` would, in-process, BEFORE spawning — the
spawn is detached with every stream DEVNULL'd, so a refusal that only fired in the child would be a
silent no-op. ``preflight_resume`` runs the CLI's four refusal gates in the CLI's order and returns
a :class:`ResumePreflight`; the CLI keeps only the click shell (arg parsing, the interactive
side-effect confirm, dispatch).

Two deliberate scope boundaries:

- **No settings env-var injection.** ``inject_settings_env_vars()`` stays in the CLI: the in-process
  CLI resume runs the workflow moments later (a resumed tail reaching an LLM node needs the
  settings-stored keys in ``os.environ``); pre-flight makes no LLM call, and the server must not be
  coupled to settings I/O through this seam.
- **No compile.** The server wraps this with the exact compile its spawned child will do (mirroring
  ``/api/run``'s ``_preflight``); the CLI compiles in-process moments later and surfaces the error
  interactively — a compile here would just run it twice there.

Known micro-reorder vs. the pre-extraction CLI: ``_approval_answer``'s contradiction
UsageError (``--approve no`` + ``--auto-approve <same node>``) now fires AFTER the identity gate
instead of before (the CLI primes delivery off the returned source). Both outcomes are refusals and
no test pins the old order; do not contort the seam to preserve it.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any

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

# An execution id is a uuid4 — distinguishable in shape from a workflow name, but
# NOT collision-proof (`validate_workflow_name` accepts uuid4-shaped names), so
# TARGET disambiguation is existence-based (try the run id first, fall back to a
# workflow name) rather than trusting the shape alone (§E step 2).
# The IR types that load as ``WorkflowExecutor`` (``runtime/compilation/node_loader.py``).
_WORKFLOW_EXECUTOR_TYPES = frozenset({"workflow", "pflow.runtime.workflow_executor"})

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclasses.dataclass(frozen=True)
class ResumePreflight:
    """Everything a vetted resume needs to dispatch — or to refuse loudly.

    ``side_effect_refusal`` is the exact refusal a non-TTY resume would raise for a
    side-effecting entry, or ``None`` (paused source / ``force`` / idempotent ``llm`` entry /
    entry removed / entry never started in the source run). A prompting caller (the CLI on a TTY) confirms instead of raising;
    every other caller raises it.
    """

    source: ResumeSource
    resolved: ResolvedWorkflow
    side_effect_refusal: ResumeSideEffectConfirmationError | None


def preflight_resume(
    target: str,
    *,
    gate_answer: dict[str, Any] | None = None,
    force: bool = False,
) -> ResumePreflight:
    """Everything a resume refuses on, in CLI order, with zero click.

    ``load_resume_source`` ladder → workflow-identity gate → between-nodes entry resolution
    (``entry_node_id is None``) → side-effect verdict (constructed, not raised). Raises
    ``ResumeSourceError`` subclasses / ``ResumeStaleWorkflowError`` / ``ResumeNotResumableError``
    exactly as the CLI does today.
    """
    source, resolved = _load_source_and_workflow(target, gate_answer=gate_answer)
    # The identity gate applies to --dry-run too (preview mirrors what a real
    # resume would do), but the side-effect confirmation does NOT: a dry-run
    # never runs K, so nothing can fire.
    _check_workflow_identity(resolved, source, force=force)
    # A between-nodes source — a killed-between-nodes incomplete run (Decision 7)
    # or a paused escalation (Task 171) — has no entry yet: resolve the
    # unambiguous successor against the (identity-checked) workflow.
    if source.entry_node_id is None:
        source = _resolve_between_nodes_entry(resolved, source)
    return ResumePreflight(
        source=source,
        resolved=resolved,
        side_effect_refusal=_side_effect_refusal(resolved, source, force=force),
    )


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


def _load_source_and_workflow(
    target: str, *, gate_answer: dict[str, Any] | None = None
) -> tuple[ResumeSource, ResolvedWorkflow]:
    """Disambiguate TARGET (existence-based) into (source, resolved_workflow) — §E step 2.

    ``gate_answer`` (Task 171) threads to EVERY ``load_resume_source`` call so
    by-exec-id and by-name resumes validate a paused gate's answer identically.
    """
    from pflow.execution.runner import workflow_path_id
    from pflow.execution.workflow_resolver import resolve_workflow
    from pflow.runtime.resume_source import load_resume_source

    if _UUID_RE.match(target):
        try:
            source = load_resume_source(execution_id=target, gate_answer=gate_answer)
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
            return load_resume_source(workflow_path=workflow_path_id(resolved), gate_answer=gate_answer), resolved
        return source, _resolve_from_source(source)

    resolved = resolve_workflow(target)
    return load_resume_source(workflow_path=workflow_path_id(resolved), gate_answer=gate_answer), resolved


def _check_workflow_identity(resolved: ResolvedWorkflow, source: ResumeSource, *, force: bool) -> None:
    """Refuse a resume that an edit since the original run would make wrong, unless --force (§E step 3).

    Resume restores the saved outputs of the steps that ran before its resume point, so it refuses
    when one of them was edited (its definition minus prose), removed, or now leads somewhere else,
    when the workflow now starts at a different step, when the resume point itself is gone, or when a
    paused approval step was edited after its approval (the answer covered what the human saw).
    Everything at or after the resume point is free to change. A trace without per-step identity
    (recorded by an older pflow) falls back to the whole-workflow hash — any edit refuses.
    """
    if force:
        return
    # Where the resume continues: the entry, or a between-nodes loop step's next iteration. A plain
    # between-nodes source has no resume point yet (its successor is resolved after this gate).
    resumes_at = source.entry_node_id
    if resumes_at is None and _node_has_loop(resolved.ir, source.last_completed_node_id):
        resumes_at = source.last_completed_node_id
    if source.step_identity is None:
        from pflow.core.workflow_id import workflow_content_hash

        if workflow_content_hash(resolved.ir) == source.content_hash:
            return
        changes: dict[str, Any] = {}
    else:
        changes = _identity_changes(resolved.ir, source, resumes_at)
        if not changes:
            return
    rerun = _side_effect_refusal(resolved, source, force=False) if resumes_at is not None else None
    raise ResumeStaleWorkflowError(
        hash_known=source.step_identity is not None or source.content_hash is not None,
        entry_node_id=resumes_at,
        entry_iteration=source.entry_iteration,
        after_node_id=source.last_completed_node_id,
        rerun_node_type=rerun.node_type if rerun is not None else None,
        execution_id=source.execution_id,
        trace_path=str(source.path),
        **changes,
    )


def _identity_changes(ir: dict[str, Any], source: ResumeSource, resumes_at: str | None) -> dict[str, Any]:
    """What changed among the steps the resume depends on, as ``ResumeStaleWorkflowError`` kwargs
    (empty = nothing). Fail-closed: a checked step the recorded map lacks counts as edited."""
    from pflow.core.workflow_id import step_identity
    from pflow.runtime.resume_source import restored_node_ids

    recorded: dict[str, Any] = source.step_identity or {}
    current = step_identity(ir)
    now, then = current["steps"], recorded["steps"]
    resume_point = resumes_at or source.last_completed_node_id
    # Checked first, alone: a renamed resume point must not be blamed on its predecessor's `next`.
    if resume_point is not None and resume_point not in now:
        return {"resume_point_missing": True}
    restored = [node_id for node_id in restored_node_ids(source) if node_id != resumes_at]
    # A paused approval step is the resume point, yet checked: `--approve yes` is consent to the
    # version the human saw. Only its definition — where it leads is downstream of the resume.
    approval = source.paused_node_id if source.paused_node_id == source.entry_node_id else None
    changes = _definition_changes(now, then, restored, approval)
    ran = {*restored, resumes_at}
    # A plain between-nodes source resumes at its last step's CURRENT successor, so a new one runs.
    runs_next = source.last_completed_node_id if resumes_at is None else None
    rerouted = {node_id: targets for node_id in restored if (targets := _rerouted(now, then, node_id))}
    skipped = {
        target
        for node_id, (targets, recorded_targets) in rerouted.items()
        if node_id != runs_next
        for target in targets
        if target not in recorded_targets and target not in ran
    }
    if rerouted:
        changes["rerouted"] = rerouted
    if current["start"] != recorded.get("start"):
        changes["new_start"] = (current["start"], recorded.get("start"))
        skipped |= {current["start"]} - ran
    if changes and skipped:
        changes["skipped"] = frozenset(skipped)
    return changes


def _definition_changes(
    now: dict[str, Any], then: dict[str, Any], restored: list[str], approval: str | None
) -> dict[str, Any]:
    """Restored steps removed or edited, and an edited paused approval step (kwargs, empty = none)."""

    def edited(node_id: str) -> bool:
        step = then.get(node_id)
        return not isinstance(step, dict) or step.get("hash") != now[node_id]["hash"]

    changes: dict[str, Any] = {}
    if removed := [node_id for node_id in restored if node_id not in now]:
        changes["removed"] = removed
    if edits := [node_id for node_id in restored if node_id in now and edited(node_id)]:
        changes["edited"] = edits
        recorded = {node_id: then[node_id] for node_id in edits if isinstance(then.get(node_id), dict)}
        if chunk_edits := {n for n, step in recorded.items() if step.get("cache") != now[n].get("cache")}:
            changes["cache_edited"] = frozenset(chunk_edits)
    if approval is not None and edited(approval):
        changes["approved_edited"] = approval
    return changes


def _rerouted(now: dict[str, Any], then: dict[str, Any], node_id: str) -> tuple[list[str], list[str]] | None:
    """``(now, recorded)`` next-step targets when ``node_id``'s recorded ``next`` differs, else ``None``
    (also when it is gone or unrecorded — those count as removed / edited)."""
    step = then.get(node_id)
    if node_id not in now or not isinstance(step, dict) or step.get("next") == now[node_id]["next"]:
        return None
    return _targets(now[node_id]["next"]), _targets(step.get("next"))


def _targets(next_steps: Any) -> list[str]:
    """The target step ids of a recorded/current ``next`` list (``[[action, target], ...]``), in order."""
    if not isinstance(next_steps, list):
        return []
    targets = [pair[1] for pair in next_steps if isinstance(pair, list) and len(pair) == 2]
    return list(dict.fromkeys(target for target in targets if isinstance(target, str)))


def _node_registry_type(ir: dict[str, Any], node_id: str | None) -> str | None:
    """The IR REGISTRY type (``"llm"``/``"shell"``/...) of K — never a trace event's class name."""
    for node in ir.get("nodes", []):
        if node.get("id") == node_id:
            node_type = node.get("type")
            return node_type if isinstance(node_type, str) else None
    return None


def _node_has_loop(ir: dict[str, Any], node_id: str | None) -> bool:
    """Whether ``node_id`` is a ``loop:`` node — its next step is the engine's to decide.

    A loop node re-enters itself until its ``while:``/``until:`` condition flips;
    re-entry is not a graph edge, so after a completed iteration the next step is
    "another iteration" or "the exit successor". That is the router of who decides
    a between-nodes resume: the preflight pins a plain step's single successor; a
    positioned loop step's continuation is the engine's re-entry decision
    (``WorkflowEngine(resume_after=)``).
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
    """Resolve the entry for a BETWEEN-nodes source (§E step 4, Decision 7; paused since Task 171).

    Two source shapes land here with the same entry problem: a killed-between-nodes
    INCOMPLETE run, and a PAUSED escalation (the escalating step completed; its
    answer's continuation is the successor). Either way the next node was never
    traced — resume only when it is UNAMBIGUOUS: refuse a dynamic router (only a
    ``code`` node routes at runtime — its taken route was never recorded, so even a
    single declared edge can be wrong) and refuse zero/multiple default successors.
    Otherwise pin the entry to the single default successor — except for a loop
    step (Task 179), whose continuation (another iteration or that exit) is the
    engine's re-entry decision: its source passes through unchanged, provided the
    saved run recorded the step's position.

    Task 171: for honestly-issued paused tokens these refusals are UNREACHABLE by
    construction — the engine's ``_gate_pausable`` never stamps ``paused`` for
    code/terminal escalations. They stay as belt-and-braces for the one path
    that can still reach them: the workflow was EDITED between pause and resume
    (identity gate bypassed with ``--force``, or the edit is to a loop step that is
    itself the resume point, which the gate leaves free). The message speaks the source's real
    state ("is paused" vs "was interrupted") so an edited-workflow refusal never
    misdescribes a pause as a crash.
    """
    last = source.last_completed_node_id
    paused = source.paused_node_id is not None
    state = "is paused" if paused else "was interrupted"
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
            f"The run {state} after step '{last}', which routes dynamically — its next step "
            "was never recorded, so resume cannot tell where to continue.",
            execution_id=source.execution_id,
            trace_path=str(source.path),
            node_id=last,
            suggestions=["Re-run the workflow from the start."],
        )
    successor = _single_default_successor(resolved.ir, str(last))
    if successor is None:
        if paused:
            # v1 refuses a final-step escalation answer (no fold-and-complete
            # machinery); producers never emit this token — edited-workflow only.
            raise ResumeNotResumableError(
                f"The run is paused after step '{last}', which was the final step — its answer has "
                "nothing left to run.",
                execution_id=source.execution_id,
                trace_path=str(source.path),
                node_id=last,
                suggestions=["Re-run the workflow if the decision should change its outputs."],
            )
        raise ResumeNotResumableError(
            f"The run was interrupted after step '{last}', and its next step is ambiguous "
            "(no single default route), so resume cannot tell where to continue.",
            execution_id=source.execution_id,
            trace_path=str(source.path),
            node_id=last,
            suggestions=["Re-run the workflow from the start."],
        )
    if _node_has_loop(resolved.ir, last):
        if source.entry_iteration is None:
            raise ResumeNotResumableError(
                f"The run {state} after loop step '{last}', and the saved run recorded no loop position "
                "for this step (it predates loop position, or the step had no `loop:` then), so the next "
                "step — another iteration or the exit — cannot be known.",
                execution_id=source.execution_id,
                trace_path=str(source.path),
                node_id=last,
                suggestions=["Re-run the workflow from the start."],
            )
        return source
    from pflow.runtime.resume_source import resume_iteration

    # `entry_iteration` described `last`; the successor's own position is 1 unless it already
    # ran (a backward edge into a loop step continues that step's count, as the live walk does).
    return dataclasses.replace(
        source, entry_node_id=successor, entry_iteration=resume_iteration(source.events, successor)
    )


def _side_effect_refusal(
    resolved: ResolvedWorkflow, source: ResumeSource, *, force: bool
) -> ResumeSideEffectConfirmationError | None:
    """The side-effecting-K verdict (Decision 4 / §E step 5) — constructed, never raised here.

    Idempotent K (``llm``) resumes silently (``None``). ``--force`` bypasses (``None``). Paused
    sources skip it entirely (``None``): the entry never ran in the source run (approval gates fire
    before node.start; an escalation's entry is its never-run successor), so there is no re-fire
    risk — and the answer flag is itself the human's consent. A failed K the source run proves never
    started (``entry_never_started`` — e.g. a template typo) skips it too (#690): nothing fired —
    except a sub-workflow K on a trace without ``step_identity``, which predates every host writing
    ``node.start``. K's type is read from the CURRENT
    resolved IR (registry vocabulary), never from a trace event; ``None`` type means K was
    removed/renamed since the run (only reachable if the identity gate was bypassed) — the engine
    refuses with a K-removed error before any node runs, so no side effect fires.
    """
    if force or source.paused_node_id is not None:
        return None
    from pflow.runtime.compilation import is_side_effecting

    # A loop step passed through between-nodes may re-run (its next iteration): check it.
    entry = source.entry_node_id or source.last_completed_node_id
    node_type = _node_registry_type(resolved.ir, entry)
    if node_type is None or not is_side_effecting(node_type):
        return None
    from pflow.runtime.resume_source import entry_never_started

    # A batched sub-workflow host wrote no node.start before the trace recorded step_identity.
    predates_host_start = source.step_identity is None and node_type in _WORKFLOW_EXECUTOR_TYPES
    if not predates_host_start and entry_never_started(source):
        return None
    return ResumeSideEffectConfirmationError(
        str(entry),
        node_type,
        execution_id=source.execution_id,
        trace_path=str(source.path),
    )
