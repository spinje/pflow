"""Resume loader (Task 164): select and vet a prior run's trace as a resume source.

Extracted from ``runtime/workflow_trace.py`` (Task 171) once the resume loader became the
third consumer-shaped growth spurt beside the collector/readers. This module owns the ONE
resume-scoped read (``load_resume_source``), the between-nodes/failed/incomplete entry
resolvers, the raw-JSONL reader for the disk-only ``kind:"gate"`` / ``node.start`` lines,
the attempt-chain consumption policy, the seed-scope guards, and the snapshot seeder
(``seed_snapshot_into_shared``) — which shares the ONE ``_seedable_final_events`` derivation
with the guards so seeding and guarding can never drift.

The general trace helpers it builds on (``_iter_workflow_traces``, ``final_events_by_node``,
``_unrecovered_failed_node_ids``) stay in ``workflow_trace`` — they are shared with the collector and
cache-analysis autoload — and are imported back here. Finding a trace, its readers and the writer-lock
probe live in ``core/trace_dir`` (the directory listing is the index — ADR-0018), shared with ``ui/``.
"""

import json
import logging
import re
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NoReturn

from pflow.core.exceptions import (
    ResumeAnswerRequiredError,
    ResumeFidelityError,
    ResumeGateStoppedError,
    ResumeNothingToResumeError,
    ResumeNotResumableError,
    ResumeSourceMissingError,
    ResumeSourceUnreadableError,
    ResumeStillRunningError,
    ResumeSupersededError,
)
from pflow.core.gate import GATE_KIND_APPROVAL, GATE_KIND_ESCALATION, option_labels
from pflow.core.path_state import PathState, path_state
from pflow.core.trace_dir import (
    AGED_OUT_HINT,
    TraceEntry,
    TraceListing,
    TraceUnreadableError,
    find_trace,
    is_trace_locked,
    legacy_note,
    list_traces,
    read_trace_meta_strict,
    read_trace_trailer_strict,
    workflow_hashes,
)
from pflow.core.trace_dir import debug_dir as default_debug_dir
from pflow.core.trace_io import load_trace_file
from pflow.core.trace_tree import normalize_workflow_path_key
from pflow.runtime.workflow_trace import (
    _is_full_run_of,
    _iter_workflow_traces,
    _unrecovered_failed_node_ids,
    final_events_by_node,
)

logger = logging.getLogger(__name__)

# ── Resume loader (Task 164) ────────────────────────────────────────────────
# `load_resume_source` is the ONE resume-scoped read: it selects the source
# trace, applies resume's status/liveness/lineage policy locally (mirroring
# `_collect_candidate_traces`'s "iterate the shared iterator, own your policy"
# shape — `_iter_workflow_traces`'s no-final_status-filter invariant is
# untouched), and returns a `ResumeSource` the engine/planner/CLI consume. It
# carries NO node-type field: a trace event's `node_type` is a Python CLASS name
# (`"LLMNode"`), while the side-effect predicate speaks IR REGISTRY names
# (`"llm"`) — the CLI derives K's type from the resolved IR, never from an event.

_BINARY_PLACEHOLDER_RE = re.compile(r"^<binary data: \d+ bytes>$")


@dataclass(frozen=True)
class ResumeSource:
    """Everything a resume needs from a prior run's trace (Task 164).

    Self-contained so the engine, planner, and CLI never re-read the trace: the
    source workflow's own `workflow_path` (so a resume-by-execution-id can
    re-resolve the workflow without re-opening the trace it just parsed), the
    entry point (`entry_node_id` = the failed step K, or `None` with
    `last_completed_node_id` set for an incomplete between-nodes run the CLI
    resolves post-compile), the full blob-resolved top-level `events` to seed
    upstream from, the original `inputs` (`None` on pre-175 traces), and the
    `content_hash` the CLI compares against the current resolved IR.

    Task 171: a PAUSED source additionally carries `paused_node_id` (the gated
    step) and the `gate_request` payload from the trailer (both `None` for
    failed/incomplete sources). Gate kind is read as `gate_request["kind"]` —
    deliberately no separate kind field (one source of truth; the payload is
    the seam, ADR-0009). A paused approval's entry is the gated node itself
    (`entry_node_id == paused_node_id`); a paused escalation is between-nodes
    (`entry_node_id=None`, `last_completed_node_id == paused_node_id`) so the
    CLI resolves the successor exactly like the incomplete arm.

    Task 179: `entry_iteration` is the loop iteration the resume step (the entry,
    or the last completed step of a between-nodes source) continues at — the
    resume entry is a *(step, iteration)* pair. `1` when the step never ran;
    `None` when its events carry no recorded position (a non-loop step, a trace
    that predates loop position, or a step given `loop:` since the run — a loop
    step then restarts at 1 and says so). Derived by `resume_iteration`, the one reader of the events' field.

    Task 180: `step_identity` is the meta line's per-step identity map
    (`core/workflow_id.step_identity`) — `None` on a trace that predates it or
    carries a malformed one, which keeps the whole-workflow `content_hash` check.
    """

    path: Path
    workflow_path: str | None
    execution_id: str
    entry_node_id: str | None
    last_completed_node_id: str | None
    events: list[dict[str, Any]]
    inputs: dict[str, Any] | None
    content_hash: str | None
    paused_node_id: str | None = None
    gate_request: dict[str, Any] | None = None
    entry_iteration: int | None = 1
    step_identity: dict[str, Any] | None = None


def _iter_raw_trace_lines(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each JSONL line of a trace as a dict, for the disk-only kinds ``load_trace_file`` hides.

    The resume loader's ONLY raw reader (gate-stopped detection needs the
    disk-only ``kind:"gate"`` lines, which reconstruct drops). Mirrors
    ``ui.run_node._iter_trace_lines``: skip non-dict lines, tolerate ONE
    truncated final line (a crash mid-flush), raise on an earlier malformed line.
    """
    raw_lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for index, raw in enumerate(raw_lines):
        try:
            line = json.loads(raw)
        except ValueError:
            if index == len(raw_lines) - 1:
                return  # truncated final line — the file is mid-flush; tolerate it
            raise
        if isinstance(line, dict):
            yield line


def _dangling_top_level_starts(path: Path) -> list[tuple[int, str]]:
    """Top-level ``node.start`` lines with no matching terminal ``event`` = nodes killed mid-run.

    Raw-JSONL only: reconstruct drops the disk-only ``node.start`` markers. A leaf's
    terminal ``event`` REUSES its ``node.start``'s ``id`` (``begin_node`` reserves the
    seq), so a TOP-LEVEL start (``parent_id is None``) with no ``kind:"event"`` at the
    same id was killed mid-execution. Top-level scoping is load-bearing — a kill inside
    a sub-workflow dangles a CHILD start whose id is not in the top-level graph. Returns
    ``(seq, node_id)`` pairs (empty when nothing dangles). Shared by the incomplete-entry
    derivation and the chain-consumption check.
    """
    started: dict[int, str] = {}
    completed_ids: set[int] = set()
    for line in _iter_raw_trace_lines(path):
        line_id = line.get("id")
        if not isinstance(line_id, int):
            continue
        kind = line.get("kind")
        if kind == "node.start" and line.get("parent_id") is None:
            node_id = line.get("node_id")
            if isinstance(node_id, str):
                started[line_id] = node_id
        elif kind == "event":
            completed_ids.add(line_id)
    return [(sid, node_id) for sid, node_id in started.items() if sid not in completed_ids]


# Gate resolution lines that carry a HUMAN VERDICT (Task 171 consumption clause (a)).
# `non_interactive` (no human channel — the run re-paused or hard-failed) and `error`
# (a resolver bug) are deliberately excluded: counting them would let a no-verdict
# re-pause or a broken resolver installation wedge the chain as "consumed".
_GATE_VERDICT_RESOLUTIONS = frozenset({"approved", "denied", "choice"})


def _attempt_consumed_work(path: Path, candidate: dict[str, Any]) -> bool:
    """Whether a resume attempt's trace shows it GOT SOMEWHERE (Task 164/171 chain policy).

    "Resume targets the newest attempt in a chain" exists for consumption
    semantics — a newer attempt that ran steps (side effects may have fired) means
    the source is no longer the frontier. An attempt "got somewhere" when ANY of:

    - it recorded a non-``restored`` event (a step completed — its only other
      events are the upstream re-records stamped before the entry would have run);
    - it is PAUSED (Task 171 clause (b)): it reached a gate, so the chain frontier
      moved to it. This is also what makes a run paused at its FIRST node — zero
      events, no dangling start — selectable by workflow name, and what stops a
      restored-only paused attempt (an answered escalation whose successor is
      itself gated) from leaving BOTH itself and its source pending;
    - it left a dangling top-level ``node.start`` (a step was killed mid-execution,
      after its side effect may have fired — itself resumable via the incomplete arm);
    - its trace carries a gate RESOLUTION line with a human VERDICT (Task 171
      clause (a), ``_GATE_VERDICT_RESOLUTIONS``): a decision was delivered through
      it — the case that matters is a DENIED attempt, which executes ZERO nodes
      (the gate fires before ``node.start``) yet must consume the token, or a
      second ``--approve no`` would re-deliver a verdict the human already gave.

    The negation is a DEAD zero-work attempt (a refused ``--force`` resume, a
    crash before the first step): it consumed nothing, so it must neither
    supersede its source (would let the source re-run a started step) nor be
    picked over an older resumable run (would wedge ``resume <workflow>``).
    ``resume list`` shares this predicate via ``_find_consuming_attempt``.

    A ``FileNotFoundError`` from the raw re-read (the trace vanished since it was
    loaded) propagates; each caller decides what a vanished trace means.
    """
    if any(not event.get("restored") for event in candidate.get("nodes") or []):
        return True
    if candidate.get("final_status") == "paused":
        return True  # clause (b): reached a gate — zero extra IO, the dict is loaded
    if _dangling_top_level_starts(path):
        return True
    return any(
        line.get("kind") == "gate"
        and line.get("phase") == "resolution"
        and line.get("resolution") in _GATE_VERDICT_RESOLUTIONS
        for line in _iter_raw_trace_lines(path)
    )


def _find_consuming_attempt(
    workflow_path: str,
    execution_id: str,
    *,
    entries: Sequence[TraceEntry],
    count_live: bool = True,
) -> str | None:
    """The execution id of a newer attempt that CONSUMED this run's chain, or ``None``.

    THE one consumption policy — ``load_resume_source`` (raises ``ResumeSupersededError``),
    ``list_paused_runs`` (filters consumed tokens) and the retention sweep (``count_live=False``) — so the
    loader, ``resume list`` and retention can never disagree on whether a token is still answerable. An
    attempt supersedes its source only when it consumed the chain (``_attempt_consumed_work``) or, with
    ``count_live``, is live right now (mid-first-step there is no terminal event yet, but its writer lock is
    held). A DEAD zero-work attempt — a refused ``--force`` resume, a crash before the entry — consumed
    nothing; counting it would wedge the chain (the source reads superseded while the empty attempt itself
    refuses with "no resumable failed step"). The sweep passes ``count_live=False``: a live attempt that has
    recorded no work is a reservation, and its source must survive if it dies.

    Candidates are the listing's entries tagged ``.from-{execution_id[:8]}`` under the workflow's hashes;
    each is loaded and confirmed (``resumed_from == execution_id``). Reads fail CLOSED, never toward "no
    consumer" (which would let a token be answered twice): an attempt that vanished counts as consuming —
    Retention removes an Attempt only after its source is gone — and one that cannot be read raises
    ``ResumeSourceUnreadableError`` (``_refuse_unreadable`` — over the load AND the raw re-read). A corrupt
    attempt (``JSONDecodeError``) is skipped.
    """
    hashes = workflow_hashes(workflow_path)
    normalized = normalize_workflow_path_key(workflow_path)
    prefix = execution_id[:8]
    for entry in entries:
        if entry.workflow_hash not in hashes or entry.only or entry.resumed_from_prefix != prefix:
            continue
        try:
            with _refuse_unreadable(entry.path, execution_id, "a newer attempt of this run"):
                candidate = load_trace_file(entry.path)
                if not _is_attempt_of(candidate, normalized, execution_id):
                    continue
                consumed = _attempt_consumed_work(entry.path, candidate)
        except FileNotFoundError:
            return entry.execution_id or ""  # gone mid-check: only a gone source loses its attempts
        except ValueError:  # JSONDecodeError / UnicodeDecodeError: a corrupt attempt is skipped
            logger.debug("Skipping unparseable attempt trace %s", entry.path, exc_info=True)
            continue
        if consumed or (count_live and is_trace_locked(entry.path) is True):
            return str(candidate.get("execution_id") or "")
    return None


def _is_attempt_of(candidate: Any, normalized_workflow_path: str, execution_id: str) -> bool:
    """Whether a loaded trace is a full-run attempt resumed from ``execution_id`` of this workflow."""
    return (
        isinstance(candidate, dict)
        and candidate.get("resumed_from") == execution_id
        and _is_full_run_of(candidate, normalized_workflow_path)
    )


@contextmanager
def _refuse_unreadable(path: Path | None, execution_id: str | None, what: str) -> Iterator[None]:
    """Turn a read fault on a trace a resume must read into the typed, retryable refusal.

    The ONE mapping for every resume read (selection, the consumption check, the source's raw re-reads):
    ``FileNotFoundError`` passes through (each caller decides what "gone" means — consumed, skipped, or
    missing); any other ``OSError`` becomes ``ResumeSourceUnreadableError`` — never a crash (a 500 on
    ``/api/resume``), and never read as "no consumer" or "no such run". ``path=None``: the faulting file is
    the one the ``OSError`` names (a read inside an iterator)."""
    try:
        yield
    except FileNotFoundError:
        raise
    except OSError as exc:
        faulted = path if path is not None else exc.filename
        raise ResumeSourceUnreadableError(
            f"Could not read {what} ({faulted}), so this resume cannot be checked: {exc}",
            execution_id=execution_id,
            trace_path=str(faulted) if faulted is not None else None,
            suggestions=["Retry. If it keeps failing, check the trace file's permissions."],
        ) from exc


def _raise_resume_source_missing(
    debug_dir: Path, workflow_path: str | None, execution_id: str | None, *, legacy_count: int
) -> NoReturn:
    note = legacy_note(legacy_count)
    legacy_suggestions = [f"{note} (read one with `pflow report <path>`)."] if note else []
    if execution_id is not None:
        raise ResumeSourceMissingError(
            f"No run with execution id '{execution_id}' was found in {debug_dir}.",
            execution_id=execution_id,
            suggestions=[
                "Check the execution id, or run the workflow so a trace exists to resume.",
                f"If the run is older, {AGED_OUT_HINT}.",
                *legacy_suggestions,
            ],
        )
    raise ResumeSourceMissingError(
        f"No resumable run was found for workflow '{workflow_path}' in {debug_dir}.",
        suggestions=[
            "Run the workflow once (without --no-trace) so a failure can be resumed.",
            *legacy_suggestions,
        ],
    )


def _select_resume_trace(
    debug_dir: Path, workflow_path: str | None, execution_id: str | None, *, listing: TraceListing
) -> tuple[Path, dict[str, Any]]:
    """Select the source trace from one listing: newest for a workflow, or the exact run by execution id."""
    if workflow_path is not None:
        # A candidate that cannot be read is never skipped past (that would resume an OLDER run): the
        # iterator raises it and the one mapping refuses retryably. A vanished one falls through.
        with _refuse_unreadable(None, None, "a run of this workflow"):
            for trace_file, data in _iter_workflow_traces(listing.traces, workflow_path, unreadable="raise"):
                # Skip a DEAD zero-work attempt (a refused --force resume / crash before
                # the first step) so `resume <workflow>` falls through to the older
                # resumable run instead of wedging on it. A killed-mid-step trace is NOT
                # dead (it has a dangling start → still resumable) and a LIVE run is not
                # dead either (selected, then refused as still-running). By-exec-id below
                # never skips — naming an exact attempt gets a verdict about THAT attempt.
                try:
                    dead = not _attempt_consumed_work(trace_file, data) and is_trace_locked(trace_file) is not True
                except FileNotFoundError:
                    continue
                if dead:
                    continue
                return trace_file, data  # first non-dead = newest resumable
        _raise_resume_source_missing(debug_dir, workflow_path, execution_id, legacy_count=listing.legacy_count)
    hit = find_trace(listing.traces, execution_id) if execution_id is not None else None
    # A matched-but-corrupt (or vanished) trace degrades to the clean "missing" refusal; one that exists but
    # cannot be read refuses retryably; an --only run refuses with its own reason (below).
    if hit is not None:
        if hit.only:
            _refuse_only_run(hit.path, execution_id)
        try:
            with _refuse_unreadable(hit.path, execution_id, "this run's trace"):
                data = load_trace_file(hit.path)
        except (json.JSONDecodeError, FileNotFoundError):
            logger.debug("Skipping unparseable resume-source trace %s", hit.path, exc_info=True)
        else:
            if data.get("only_node") is not None:  # a hand-made name without the tag: the meta is the truth
                _refuse_only_run(hit.path, execution_id)
            return hit.path, data
    _raise_resume_source_missing(debug_dir, workflow_path, execution_id, legacy_count=listing.legacy_count)


def _refuse_only_run(path: Path, execution_id: str | None) -> NoReturn:
    """An --only run records only its target step, so resuming it would seed an empty upstream scope."""
    raise ResumeNotResumableError(
        f"Run '{execution_id}' was an --only run: its trace records only the one step it ran, so it cannot be resumed.",
        execution_id=execution_id,
        trace_path=str(path),
        suggestions=["Re-run that step with `--only <step>` (it restores upstream from the last full run)."],
    )


def _seedable_final_events(
    events: list[dict[str, Any]], entry_node_id: str | None, entry_iteration: int = 1
) -> dict[str, dict[str, Any]]:
    """THE seedable set: each node's final event BEFORE the entry, minus failed-final-status nodes.

    The single derivation shared by seeding (``seed_snapshot_into_shared``) and
    the loader guards (``_guard_seed_scope``), so they cannot drift: the guards
    scan exactly the values resume will restore — nothing more (a superseded
    earlier loop-iteration event is never seeded, so its contents must not
    refuse a resume) and nothing less. Failed-final-status nodes are excluded
    (seed fidelity — their data lived in ``__failures__``, never the store).
    ``entry_node_id=None`` (incomplete between-nodes resume) scopes to ALL
    events.

    The entry is a *(step, iteration)* pair (Task 179): the slice ends before the
    entry's first event at ``entry_iteration`` or later (a keyless event counts as
    iteration 1), so the map never holds the iteration about to run — the entry's
    EARLIER iterations are upstream of it and seed like any completed work. ``>=``,
    not ``==``: a resumed attempt holds the entry's restored iteration N-1 and then
    live N.., never an iteration-1 event, so ``--only`` (iteration 1) against it
    must still stop at the entry's first event. No such event → the whole trace.
    """
    if entry_node_id is None:
        scope = events
    else:
        idx = next((i for i, e in enumerate(events) if _resumes_from(e, entry_node_id, entry_iteration)), None)
        scope = events if idx is None else events[:idx]
    return {nid: ev for nid, ev in final_events_by_node(scope).items() if ev.get("status") != "failed"}


def _resumes_from(event: dict[str, Any], entry_node_id: str, entry_iteration: int) -> bool:
    """Whether ``event`` is the entry's at ``entry_iteration`` or later — the first such event is
    where the seed slice ends and where the resume re-runs from (a keyless event is iteration 1)."""
    return event.get("node_id") == entry_node_id and (event.get("iteration") or 1) >= entry_iteration


def lossy_seed(
    events: list[dict[str, Any]], entry_node_id: str | None, entry_iteration: int = 1
) -> tuple[str, list[str]] | None:
    """The first event a resume entering at *(step, iteration)* would seed although the trace
    marked it ``lossy`` — ``(node_id, lossy entries)`` — or ``None``.

    The engine's pause decision asks this BEFORE issuing a token (pause = promise): the same
    seed derivation the loader's ``_guard_seed_scope`` refuses on, never a mirror of it.
    """
    for node_id, event in _seedable_final_events(events, entry_node_id, entry_iteration).items():
        lossy = event.get("lossy")
        if lossy:
            return node_id, [str(entry) for entry in lossy]
    return None


def restored_node_ids(source: ResumeSource) -> list[str]:
    """The steps a resume of ``source`` restores instead of re-running, in run order.

    The loader's own seed derivation (the arguments ``load_resume_source`` scans) minus the entry,
    which runs — the same set the engine counts as "N upstream steps restored".
    """
    seedable = _seedable_final_events(source.events, source.entry_node_id, source.entry_iteration or 1)
    return [node_id for node_id in seedable if node_id != source.entry_node_id]


def entry_never_started(source: ResumeSource) -> bool:
    """Whether the source run PROVES the entry never began on any visit the resume re-runs (#690).

    ``begin_node`` flushes a top-level ``node.start`` before a step's prep/exec, and the step's
    terminal ``event`` reuses that line's ``id``; a failure raised earlier (template resolution, a
    loop-carry error) records a FAILED ``event`` with no ``node.start``. The resume re-runs from the
    entry's first event at ``entry_iteration`` or later (``_resumes_from``, the seed slice's own
    cut), so from there on every line of the entry must be exactly that: a failed, unpaired event.
    A ``node.start`` (a visit that began) or any other event — a ``restored`` re-record or a cache
    hit, which stand for a run that executed earlier, also unpaired — is no proof. Traces without
    ``content_hash`` predate ``node.start`` (both arrived with Task 173) and prove nothing either.
    """
    entry = source.entry_node_id
    if entry is None or source.content_hash is None:
        return False
    try:
        lines = [
            line
            for line in _iter_raw_trace_lines(source.path)
            if line.get("parent_id") is None
            and line.get("node_id") == entry
            and line.get("kind") in ("node.start", "event")
        ]
    except (OSError, ValueError):
        return False
    first_iteration = source.entry_iteration or 1
    cut = next(
        (
            i
            for i, line in enumerate(lines)
            if line.get("kind") == "event" and _resumes_from(line, entry, first_iteration)
        ),
        None,
    )
    if cut is None:
        return False
    started_ids = {line.get("id") for line in lines[:cut] if line.get("kind") == "node.start"}
    return all(
        line.get("kind") == "event"
        and line.get("status") == "failed"
        and isinstance(line.get("id"), int)
        and line["id"] not in started_ids
        for line in lines[cut:]
    )


def _apply_gate_resolutions(path: Path, events: list[dict[str, Any]]) -> None:
    """Fold recorded escalation decisions back into the frozen event markers (in place).

    The trace is event-sourced: a node's event freezes its ``node_output`` at
    record time (engine step 16), while the human's escalation decision — made
    at step 17.7, AFTER the freeze — is persisted only as a separate disk-only
    ``kind:"gate"`` resolution line (``run_escalation_gate`` writes the decision
    into the LIVE store; an already-flushed event line is immutable).
    Reconstructing "the store as it existed at failure time" therefore folds the
    resolution lines over the frozen markers. Without this fold every RESOLVED
    upstream escalation reads as undecided and ``_guard_seed_scope`` false-refuses
    the resume, claiming no human decided when one did. Mirrors
    ``run_escalation_gate``'s write shape exactly (dict marker gains
    ``decision``; string marker becomes ``{"question", "decision"}``).

    A decision folds onto the event of the ITERATION that raised it (the line's
    ``iteration``, trace 2.8.0): a loop step's earlier iterations can be seeded as
    the upstream of a resumed iteration, so iteration 1's answer must decide
    iteration 1's marker — never a later, unanswered one. Lines without the key
    (non-loop steps, pre-2.8.0 traces) pair with the node's final event.
    """
    final = final_events_by_node(events)
    by_iteration = {(e.get("node_id"), e["iteration"]): e for e in events if e.get("iteration") is not None}
    for line in _iter_raw_trace_lines(path):
        if line.get("kind") != "gate" or line.get("phase") != "resolution":
            continue
        decision = line.get("decision")
        if not isinstance(decision, dict):
            continue  # approval/denied/non-interactive resolutions carry no decision
        node_id, iteration = line.get("node_id"), line.get("iteration")
        if not isinstance(node_id, str):
            continue
        target = final.get(node_id) if iteration is None else by_iteration.get((node_id, iteration))
        _fold_decision_into_event(target, decision)


def _fold_decision_into_event(event: dict[str, Any] | None, decision: dict[str, Any]) -> None:
    """Fold one escalation decision into a node's final event marker (in place).

    Mirrors ``run_escalation_gate``'s live-store write shape exactly: a dict
    marker gains ``["decision"]``; a non-empty string marker becomes
    ``{"question": marker, "decision": decision}``. THE one fold shape, two
    callers — ``_apply_gate_resolutions`` (decisions the source run recorded)
    and the paused ``--choose`` answer (Task 171) — so the two can never drift.
    Anything not marker-shaped is left untouched (lenient, like the recorded
    fold: a hand-edited trace must not crash the loader here — the seed-scope
    guard downstream still refuses an undecided marker loudly).
    """
    output = event.get("node_output") if isinstance(event, dict) else None
    result = output.get("result") if isinstance(output, dict) else None
    if not isinstance(result, dict):
        return
    marker = result.get("escalation")
    if isinstance(marker, dict) and marker:
        marker["decision"] = decision
    elif isinstance(marker, str) and marker != "":
        result["escalation"] = {"question": marker, "decision": decision}


def _contains_binary_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_BINARY_PLACEHOLDER_RE.match(value))
    if isinstance(value, dict):
        return any(_contains_binary_placeholder(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_binary_placeholder(v) for v in value)
    return False


def _raise_gate_stopped_or_generic(path: Path, execution_id: str) -> NoReturn:
    """A ``failed`` trace with no unrecovered failed node = gate-stopped (or the defensive fallback)."""
    paused = [
        line for line in _iter_raw_trace_lines(path) if line.get("kind") == "gate" and line.get("phase") == "pause"
    ]
    if paused:
        last = paused[-1]
        raise ResumeGateStoppedError(
            node_id=str(last.get("node_id") or "?"),
            gate_kind=last.get("gate_kind"),
            execution_id=execution_id,
            trace_path=str(path),
        )
    # Defensive: `failed` + no unrecovered node + zero gate lines is not
    # producible today (only gate stops make that combination). Refuse cleanly
    # rather than fall through to an undefined branch.
    raise ResumeNotResumableError(
        "This run is marked failed but has no failed step to resume from.",
        execution_id=execution_id,
        trace_path=str(path),
        suggestions=["Re-run the workflow from the start."],
    )


def _terminal_failure_root(events: list[dict[str, Any]]) -> str | None:
    """The ROOT of the trace's TERMINAL failure region, or None if there isn't one.

    The earliest failed node with no successful/cached node AFTER it in event
    order — the "frontier" of what actually completed (Temporal's replay-frontier
    idea, one pass over the trace). Decision 9 + ADR-0010: a ``K --on-error--> F``
    chain where BOTH fail resumes at K, not F — re-running K re-evaluates its
    branch, so a fixed K follows its SUCCESS edge and F never runs. A failure
    whose recovery genuinely SUCCEEDED (a success sits after it) is excluded —
    the later, separate failure is the root. NEVER the alphabetical
    ``failed_node_ids`` trailer. Returns None when no failure sits after the
    frontier (nothing failed at all, or every failure was followed by a success —
    e.g. a gate-stopped run).

    Used by BOTH the ``failed`` arm and the ``incomplete`` arm — an interrupted
    tail that ends in a failure re-enters at the same root a failed run would.
    Needs no warnings data, which the incomplete arm could never supply (the
    trailer carrying them is exactly what an interrupted run lacks).
    """
    final = final_events_by_node(events)
    last_index: dict[str, int] = {}
    for index, event in enumerate(events):
        nid = event.get("node_id")
        if isinstance(nid, str):
            last_index[nid] = index
    frontier = max(
        (idx for nid, idx in last_index.items() if final[nid].get("status") in ("success", "cached")),
        default=-1,
    )
    candidates = [
        (idx, nid) for nid, idx in last_index.items() if final[nid].get("status") == "failed" and idx > frontier
    ]
    return min(candidates)[1] if candidates else None


def _resolve_resume_entry(path: Path, data: dict[str, Any], execution_id: str) -> tuple[str | None, str | None]:
    """Apply the status arm: return ``(entry_node_id, last_completed_node_id)`` or refuse."""
    final_status = str(data.get("final_status") or "")
    events = data.get("nodes") or []
    if final_status in ("success", "degraded"):
        raise ResumeNothingToResumeError(
            "The most recent run of this workflow already succeeded — there is nothing to resume.",
            execution_id=execution_id,
            trace_path=str(path),
            suggestions=["Run the workflow again if you want a fresh run."],
        )
    if final_status == "denied":
        raise ResumeNotResumableError(
            "This run was stopped by a human denial at an approval gate, not by a failure.",
            execution_id=execution_id,
            trace_path=str(path),
            suggestions=["Re-run the workflow if you want to try again."],
        )
    if final_status == "incomplete":
        return _resolve_incomplete_entry(path, events, execution_id)
    if final_status == "paused":
        # Task 171: a durable gate pause. The trailer's pause record arrives flat
        # on `data` (the reader copies non-`kind` trailer keys verbatim).
        paused_node_id = data.get("paused_node_id")
        gate_request = data.get("gate_request")
        if not isinstance(paused_node_id, str) or not isinstance(gate_request, dict):
            # Corrupt / hand-edited pause: marked paused with no honorable record.
            raise ResumeNotResumableError(
                "This run is marked paused but carries no pause record.",
                execution_id=execution_id,
                trace_path=str(path),
                suggestions=["Re-run the workflow from the start."],
            )
        if gate_request.get("kind") == GATE_KIND_ESCALATION:
            # The escalating step COMPLETED (its success event was recorded at
            # engine step 16, before the 17.7 raise) — resume enters at its
            # successor. Same between-nodes shape as the incomplete arm; the
            # CLI resolves the single default successor post-compile.
            return None, paused_node_id
        # Approval: the gate fires at engine step 7.5, BEFORE node.start — the
        # gated iteration has NO event (a loop step's earlier iterations do), so
        # the (step, iteration) seed slice never holds it.
        return paused_node_id, None
    if final_status != "failed":
        raise ResumeNotResumableError(
            f"This run's status '{final_status or 'unknown'}' is not resumable.",
            execution_id=execution_id,
            trace_path=str(path),
            suggestions=["Re-run the workflow from the start."],
        )
    if not _unrecovered_failed_node_ids(final_events_by_node(events), data.get("warnings")):
        _raise_gate_stopped_or_generic(path, execution_id)
    # This check is NOT redundant with the frontier scan below: a recovered
    # failure can be the trace's LAST event when its on-error handler was
    # gate-stopped before running — the frontier alone would resume at that
    # failure instead of refusing at the gate. Keep this ordering.
    entry = _terminal_failure_root(events)
    if entry is None:
        # Engine-unproducible (an unrecovered failure stops the walk, so it is
        # always the last event) — reachable only from a hand-edited trace.
        # Refuse cleanly rather than crash.
        _raise_gate_stopped_or_generic(path, execution_id)
    return entry, None


def _resolve_incomplete_entry(
    path: Path, events: list[dict[str, Any]], execution_id: str
) -> tuple[str | None, str | None]:
    """Decision 7: derive the resume entry for an interrupted (Ctrl+C/SIGKILL) run.

    Entry-node identification is possible ONLY via the RAW JSONL — reconstruct
    drops the disk-only ``node.start`` running markers. A leaf node's terminal
    ``event`` REUSES its ``node.start``'s ``id`` (``begin_node`` reserves the seq),
    so a TOP-LEVEL ``node.start`` (``parent_id is None``) with no matching
    ``kind:"event"`` line marks the node that was killed MID-execution — that is K.
    Top-level scoping is load-bearing: a kill inside a sub-workflow leaves a
    dangling CHILD start too, whose id is not in the top-level graph. When nothing
    dangles and the tail ENDS in a failure, the run was killed while failing (or
    heading down an on-error edge) — re-enter at the terminal-failure root,
    exactly like the failed arm. Only a SUCCESS-ending tail was killed cleanly
    between nodes — entry is ``None`` and the CLI resolves the unambiguous
    successor of the last completed node post-compile (§E step 4). A meta-only
    file (crashed before step 1) has nothing to resume.
    """
    dangling = _dangling_top_level_starts(path)
    if dangling:
        # A sequential walk has exactly one in-flight top-level node at a kill; if
        # more ever appear, the most-recently-started (highest seq) was running.
        _, killed = max(dangling, key=lambda pair: pair[0])
        return killed, None
    root = _terminal_failure_root(events)
    if root is not None:
        # The tail ends in a FAILURE — the run was failing when it was killed.
        # The successor path below is for success-ending tails ONLY: a failed
        # last node's taken route may have been its ERROR edge, so its single
        # default successor is provably the wrong branch (and continuing past an
        # unrecovered failure would resume as if it had succeeded).
        return root, None
    if events:
        last_completed = events[-1].get("node_id")
        if isinstance(last_completed, str):
            return None, last_completed
    raise ResumeNothingToResumeError(
        "This run was interrupted before its first step completed — there is nothing to resume.",
        execution_id=execution_id,
        trace_path=str(path),
        suggestions=["Run the workflow again from the start."],
    )


def resume_iteration(events: list[dict[str, Any]], node_id: str | None) -> int | None:
    """The iteration a resume of ``node_id`` continues at — the ONE reader of the events' ``iteration``.

    No event for the step → ``1`` (nothing of it ran). Its final event carries no
    ``iteration`` → ``None``: no recorded position (a non-loop step, or a trace
    that predates 2.8.0). A failed final event that nothing after it recovered →
    its own iteration (the failed iteration re-runs); otherwise the next one: an
    approval paused at N or a kill mid-N leaves N-1 as the last completed, an
    answered escalation at N (or a kill before the re-entry decision) continues
    after N, and a step re-entered after its failure was recovered (an on-error
    edge leading back to it) is already past that iteration.
    """
    if node_id is None:
        return 1
    index = next((i for i in range(len(events) - 1, -1, -1) if events[i].get("node_id") == node_id), None)
    if index is None:
        return 1
    final = events[index]
    iteration = final.get("iteration")
    if not isinstance(iteration, int):
        return None
    recovered = any(e.get("status") in ("success", "cached") for e in events[index + 1 :])
    return iteration if final.get("status") == "failed" and not recovered else iteration + 1


def _predates_lossy_marker(data: dict[str, Any]) -> bool:
    """Whether the trace predates the ``lossy`` event marker (2.8.0).

    Such a trace can only say "this value was bytes" through the placeholder string
    itself, so the guard scans for it; a 2.8.0+ trace marks every lossy event, and a
    literal placeholder-shaped string there is just a string.
    """
    version = str(data.get("format_version") or "")
    parts = version.split(".")
    try:
        return (int(parts[0]), int(parts[1])) < (2, 8)
    except (IndexError, ValueError):
        return True


def _guard_seed_scope(
    scope: Iterable[dict[str, Any]], execution_id: str, path: Path, *, legacy_placeholders: bool = False
) -> None:
    """Refuse if any node resume would SEED carries a lossy value (Decision 5) or an undecided escalation (Decision 8).

    ``scope`` is the ``_seedable_final_events`` values — exactly what seeding
    restores. Lossy = the event's ``lossy`` marker (Task 179, written by the
    collector's sanitizer); a pre-2.8.0 trace has no marker, so there
    (``legacy_placeholders``) a binary placeholder string is the only evidence. Escalation markers were already folded with their recorded
    decisions (``_apply_gate_resolutions``), so an undecided marker here means
    the run genuinely never resolved it (e.g. killed between the node's event
    and the gate resolution) — never a resolved-but-frozen fidelity artifact.
    """
    for event in scope:
        node_id = event.get("node_id")
        node_id_str = node_id if isinstance(node_id, str) else None
        output = event.get("node_output")
        lossy = event.get("lossy")
        if not lossy and legacy_placeholders and isinstance(output, dict):
            lossy = [f"{key}: bytes" for key, value in output.items() if _contains_binary_placeholder(value)]
        if lossy:
            raise ResumeFidelityError(
                node_id=str(node_id_str or "?"),
                lossy=[str(entry) for entry in lossy],
                execution_id=execution_id,
                trace_path=str(path),
            )
        if not isinstance(output, dict):
            continue
        result = output.get("result")
        if isinstance(result, dict):
            escalation = result.get("escalation")
            # Mirror engine.gate.detect_escalation EXACTLY: a non-empty dict without
            # a "decision" key, or any non-"" string, is undecided. Do NOT .strip()
            # the string — production pauses on a whitespace-only marker too, so
            # stripping here would seed a marker the run actually paused on.
            undecided = (isinstance(escalation, dict) and escalation and "decision" not in escalation) or (
                isinstance(escalation, str) and escalation != ""
            )
            if undecided:
                raise ResumeNotResumableError(
                    f"Step '{node_id_str}' has an unresolved escalation in the saved run — resuming "
                    "would replay it as if a human had already decided.",
                    execution_id=execution_id,
                    trace_path=str(path),
                    node_id=node_id_str,
                    suggestions=["Re-run the workflow and resolve the escalation."],
                )


def _validate_gate_answer(
    gate_answer: dict[str, Any] | None,
    gate_request: dict[str, Any],
    paused_node_id: str,
    execution_id: str,
    path: Path,
) -> None:
    """Refuse a paused resume whose answer is missing or names the wrong gate kind (Task 171).

    Must run BEFORE ``_guard_seed_scope``: an unanswered paused escalation would
    otherwise hit the guard's "unresolved escalation … re-run the workflow"
    refusal — the WRONG message (the right move is to answer, not re-run). The
    answer shapes are the CLI contract: ``{"approve": bool}`` from
    ``--approve yes|no``, ``{"chosen": str, "notes": str | None}`` from
    ``--choose`` — discriminated by key, one flag per gate kind.
    """
    if gate_answer is None:
        raise ResumeAnswerRequiredError(
            mode="missing_answer",
            gate_request=gate_request,
            execution_id=execution_id,
            trace_path=str(path),
            node_id=paused_node_id,
        )
    is_approval = gate_request.get("kind") == GATE_KIND_APPROVAL
    if is_approval != ("approve" in gate_answer):
        raise ResumeAnswerRequiredError(
            mode="wrong_flag",
            gate_request=gate_request,
            execution_id=execution_id,
            trace_path=str(path),
            node_id=paused_node_id,
        )
    if not is_approval and not str(gate_answer.get("chosen") or "").strip():
        # An empty/whitespace `--choose` would "decide" the escalation with
        # nothing — a shape the blocking prompt cannot produce (click re-prompts
        # on empty input). Treat it as no answer at all.
        raise ResumeAnswerRequiredError(
            mode="missing_answer",
            gate_request=gate_request,
            execution_id=execution_id,
            trace_path=str(path),
            node_id=paused_node_id,
        )


def _apply_paused_answer(
    path: Path,
    data: dict[str, Any],
    seedable: dict[str, dict[str, Any]],
    gate_answer: dict[str, Any] | None,
    execution_id: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """The whole Task-171 answer policy in one seam: validate, then fold an escalation's answer.

    Returns ``(paused_node_id, gate_request)`` — ``(None, None)`` for non-paused
    sources. Non-paused + an answer flag → ``not_paused`` refusal (the flag
    answers nothing; refuse rather than ignore it — loader-side so by-exec-id
    and by-name behave identically). Paused → the answer must exist and match
    the gate kind (``_validate_gate_answer``); an escalation's ``chosen`` is then
    folded into the paused node's SEEDED event (``seedable`` — an escalation
    source is between-nodes, so that is its final event) using the identical marker shape
    the source run would have recorded — so ``_guard_seed_scope`` sees a DECIDED
    marker, seeding restores it, and the engine's re-record loop writes it into
    the attempt trace (self-containment for resume-of-a-resume with zero new
    code). An approval's answer is NOT folded — the gated node never ran;
    delivery is the resume run's resolver (the CLI primes it from this answer).
    Must run AFTER ``_apply_gate_resolutions`` (prior recorded decisions fold
    first) and BEFORE ``_guard_seed_scope`` (see ``_validate_gate_answer``).
    """
    if data.get("final_status") != "paused":
        if gate_answer is not None:
            raise ResumeAnswerRequiredError(mode="not_paused", execution_id=execution_id, trace_path=str(path))
        return None, None
    # `_resolve_resume_entry`'s paused arm already refused a malformed record,
    # so this narrowing never drops a paused source's fields.
    raw_node_id, raw_request = data.get("paused_node_id"), data.get("gate_request")
    paused_node_id = raw_node_id if isinstance(raw_node_id, str) else None
    gate_request = raw_request if isinstance(raw_request, dict) else None
    if paused_node_id is None or gate_request is None:
        return None, None
    _validate_gate_answer(gate_answer, gate_request, paused_node_id, execution_id, path)
    if gate_answer is not None and "chosen" in gate_answer:
        decision = {
            "chosen": _map_choose_answer(str(gate_answer["chosen"]), gate_request),
            "notes": gate_answer.get("notes"),
        }
        _fold_decision_into_event(seedable.get(paused_node_id), decision)
    return paused_node_id, gate_request


def _map_choose_answer(chosen: str, gate_request: dict[str, Any]) -> str:
    """Map a numeric ``--choose`` to its option label, mirroring the blocking prompt exactly.

    Same rule as ``_prompt_escalation`` (gate_prompt.py): strip, then a digit in
    1..len(options) selects that option's label via the shared ``option_labels``
    extraction — never raw indexing into the option dicts. Anything else is the
    free-text answer, stripped like the prompt's.
    """
    answer = chosen.strip()
    options = [option for option in gate_request.get("options") or () if isinstance(option, dict)]
    labels = option_labels(options)
    # isdecimal(), NOT isdigit(): isdigit() is True for numeric-but-non-decimal
    # chars (superscripts like "²") that int() then REJECTS with ValueError —
    # an agent-supplied `--choose "²"` must fold as free text, never crash.
    if answer.isdecimal() and 1 <= int(answer) <= len(labels):
        return labels[int(answer) - 1]
    return answer


def load_resume_source(
    workflow_path: str | None = None,
    execution_id: str | None = None,
    *,
    debug_dir: Path | None = None,
    gate_answer: dict[str, Any] | None = None,
) -> ResumeSource:
    """Load and vet a prior run's trace as a resume source, or raise a typed refusal (Task 164).

    Exactly one of ``workflow_path`` (→ newest reusable run of that workflow) or
    ``execution_id`` (→ that exact attempt) is given. Refusal/derivation policy,
    in order (each a ``ResumeSourceError`` subclass): inline source → not
    resumable; live writer → still running; a newer attempt exists → superseded;
    then the status arm (``success``/``degraded`` → nothing to resume; ``denied``
    → not resumable; ``failed`` → entry is the terminal-failure root, or
    gate-stopped when none; ``incomplete`` → Decision 7 derivation; ``paused`` →
    Task 171: approval enters at the gated node, escalation between-nodes); then
    recorded escalation decisions are folded into the frozen event markers
    (``_apply_gate_resolutions``); finally the seed-scope guards (undecided
    escalation, lossy binary) scan exactly the seedable set. ``content_hash`` is
    RETURNED for the CLI to compare — the loader has no workflow IR to check it.

    ``gate_answer`` (Task 171) is the human's answer to a PAUSED source —
    ``{"approve": bool}`` (from ``--approve yes|no``) or ``{"chosen": str,
    "notes": str | None}`` (from ``--choose``). A paused source REQUIRES a
    kind-matching answer (``ResumeAnswerRequiredError`` otherwise, rendered with
    the pending gate content); a non-paused resumable source REJECTS one (same
    error, ``not_paused`` mode — loader-side so by-exec-id and by-name behave
    identically). An escalation's answer is folded into the paused node's final
    event here (numeric answers map to option labels first), so seeding restores
    the DECIDED marker and the engine's re-record loop makes the attempt trace
    self-contained with zero new code. An approval's answer is NOT folded — the
    gated node never ran; delivery is the resume run's resolver (the CLI primes
    it from the same answer).
    """
    if (workflow_path is None) == (execution_id is None):
        raise ValueError("load_resume_source requires exactly one of workflow_path / execution_id")
    debug_dir = debug_dir if debug_dir is not None else default_debug_dir()
    listing = list_traces(debug_dir)  # the ONE directory enumeration: selection + consumption share it

    path, data = _select_resume_trace(debug_dir, workflow_path, execution_id, listing=listing)
    source_execution_id = str(data.get("execution_id") or "")
    source_workflow_path = data.get("workflow_path")

    if isinstance(source_workflow_path, str) and source_workflow_path.startswith("ir-hash:"):
        raise ResumeNotResumableError(
            "Inline or piped workflows cannot be resumed — there is no source file to re-resolve.",
            execution_id=source_execution_id,
            trace_path=str(path),
            suggestions=["Save the workflow to a file and re-run it so future failures can be resumed."],
        )

    if is_trace_locked(path) is True:
        raise ResumeStillRunningError(
            "This run is still in progress.",
            execution_id=source_execution_id,
            trace_path=str(path),
            suggestions=["Wait for the run to finish (or stop it), then resume."],
        )

    if source_execution_id and isinstance(source_workflow_path, str):
        consuming = _find_consuming_attempt(source_workflow_path, source_execution_id, entries=listing.traces)
        if consuming is not None:
            raise ResumeSupersededError(
                consuming,
                execution_id=source_execution_id,
                trace_path=str(path),
            )

    # The source must still exist AFTER the consumption check: Retention removes a source before its
    # Attempts, so a source still present had no consumer when it was checked; a vanished one refuses.
    try:
        with _refuse_unreadable(path, source_execution_id, "this run's trace"):
            path.stat()  # never ``exists()``: on Python 3.14 it reads a permission fault as "removed"
            entry_node_id, last_completed_node_id = _resolve_resume_entry(path, data, source_execution_id)

            events = list(data.get("nodes") or [])
            entry_iteration = resume_iteration(events, entry_node_id or last_completed_node_id)
            _apply_gate_resolutions(path, events)
            seedable = _seedable_final_events(events, entry_node_id, entry_iteration or 1)
            paused_node_id, gate_request = _apply_paused_answer(path, data, seedable, gate_answer, source_execution_id)
    except FileNotFoundError:
        raise ResumeSourceMissingError(
            f"The trace of run '{source_execution_id}' was removed while it was being resumed.",
            execution_id=source_execution_id,
            trace_path=str(path),
            suggestions=[f"Re-run the workflow — {AGED_OUT_HINT}."],
        ) from None
    _guard_seed_scope(seedable.values(), source_execution_id, path, legacy_placeholders=_predates_lossy_marker(data))

    return ResumeSource(
        path=path,
        workflow_path=source_workflow_path if isinstance(source_workflow_path, str) else None,
        execution_id=source_execution_id,
        entry_node_id=entry_node_id,
        last_completed_node_id=last_completed_node_id,
        events=events,
        inputs=data.get("inputs"),
        content_hash=data.get("content_hash"),
        paused_node_id=paused_node_id,
        gate_request=gate_request,
        entry_iteration=entry_iteration,
        step_identity=_recorded_step_identity(data),
    )


def _recorded_step_identity(data: dict[str, Any]) -> dict[str, Any] | None:
    """The trace's ``step_identity`` when its envelope (a ``steps`` map, a ``start`` id or null) is intact,
    else ``None`` — the preflight then falls back to the whole-workflow hash. Individual step entries are
    not vetted here: the preflight treats a missing or malformed one as edited (fail-closed)."""
    identity = data.get("step_identity")
    if not isinstance(identity, dict) or not isinstance(identity.get("steps"), dict):
        return None
    if not isinstance(identity.get("start"), (str, type(None))):
        return None
    return identity


# The EXACT engine-injected reserved keys that ``apply_memo_hit`` strips when
# restoring a cached blob to ``shared[node_id]`` (instrumentation.py). Using the
# exact set — NOT a broad ``startswith("__")`` — is load-bearing: a fresh run's
# ``shared[node_id]`` keeps ``__metrics__`` (which ``apply_memo_hit`` also keeps),
# so a snapshot restore must keep it too or restored vs fresh state would differ.
_SNAPSHOT_RESERVED = {"__pflow_stats__", "__pflow_warnings__"}


def seed_snapshot_into_shared(
    shared: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    exclude: str,
    exclude_iteration: int = 1,
) -> dict[str, dict[str, Any]]:
    """Seed the target's UPSTREAM outputs from a snapshot into ``shared``.

    Mirrors ``apply_memo_hit``'s restore shape: each in-scope node's terminal
    ``node_output`` is written to ``shared[node_id]`` with the engine-injected
    reserved keys (``_SNAPSHOT_RESERVED``) filtered out.

    Seeding reconstructs the shared store AS IT EXISTED in the source run. A node
    whose final event is ``failed`` is therefore skipped entirely: its data lived
    in ``__failures__``, never in the store, so seeding it would resolve template
    paths (e.g. ``${primary.x ?? fallback.x}``) that the original run — and a
    fresh run — resolve to the fallback instead. This matters whenever a
    RECOVERED failure sits in scope: a resume tail downstream of an on-error
    chain, or an ``--only`` run against a DEGRADED snapshot. Nodes with no
    captured output are also skipped (they genuinely produced nothing).

    Scope = nodes that executed BEFORE ``exclude`` (the ``--only`` target) in the
    snapshot's execution order. pflow templates can only reference EARLIER steps,
    so this slice provably contains every node the target can read — while
    excluding DOWNSTREAM nodes, whose stale output would otherwise be addressable
    via ``-o <downstream>`` / ``shared_after`` despite not having run this
    invocation (PR #459 CODEX-2). Loop-safe: the pre-target slice yields each
    node's value AS OF when the target first ran. If the target is absent from
    the snapshot (it ran on a branch the snapshot didn't take, or was added
    since), fall back to seeding every node so its references still resolve — a
    genuinely missing one then surfaces as the normal loud unresolved-reference
    error.

    NEVER seeds the iteration about to run: the slice ends before the target's
    first event at ``exclude_iteration`` or later (``_seedable_final_events``).
    At the default ``1`` (``--only``, a non-loop resume) that is the target's
    first event, so it executes fresh against no copy of itself; a loop step
    resumed at iteration N is seeded with its iteration N-1 output — the carry
    and condition source the next iteration reads. Returns that seedable map
    (failed-final-status nodes excluded) so callers derive the resume re-record
    loop from exactly what was seeded; ``restored_nodes`` is that map minus the
    target (it runs).
    """
    final = _seedable_final_events(events, exclude, exclude_iteration)
    for nid, ev in final.items():
        output = ev.get("node_output")
        if output is None:
            continue
        shared[nid] = {k: v for k, v in output.items() if k not in _SNAPSHOT_RESERVED}
    return final


# ── Resume list (Task 171) ──────────────────────────────────────────────────
# `pflow resume list` is a STATUS QUERY over the debug dir, not a separate
# registry: a paused trace IS the pending obligation. One listing finds the
# marked traces (`.paused` sidecars, ADR-0018); only those are read (head +
# tail), plus the 0-2 `.from-` attempts the consumption check loads per row.


@dataclass(frozen=True)
class PausedRun:
    """One pending paused run — a ``resume list`` row (Task 171).

    ``gate_kind`` is ``gate_request["kind"]`` (the payload stays the one source
    of truth — the row carries only what the list renders); ``paused_at`` is the
    trailer's ``end_time`` ISO string (the moment the run finalized paused);
    ``iteration`` is ``gate_request["iteration"]`` — the loop iteration that raised
    the gate (``None`` for a non-loop step; Task 179); ``max_iterations`` is
    ``gate_request["max_iterations"]`` — the loop's cap as known at the gate (``None``
    when unknown, and for records written before Task 183).
    """

    execution_id: str
    workflow_name: str | None
    workflow_path: str | None
    paused_node_id: str
    gate_kind: str | None
    paused_at: str | None
    path: Path
    iteration: int | None = None
    max_iterations: int | None = None


@dataclass(frozen=True)
class PausedRunListing:
    """``list_paused_runs``' answer: the pending rows, newest first, and what the list could not show —
    pending pauses hidden because their workflow file no longer exists (each still names its token and
    path), marked traces it could not read (the read errors, each naming its file), and the count of
    pre-185 traces not searched."""

    runs: list[PausedRun]
    hidden_missing_file: list[PausedRun] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    legacy_count: int = 0


def is_pause_record(entry: TraceEntry, meta: dict[str, Any] | None, trailer: dict[str, Any] | None) -> bool:
    """Whether a trace is a well-formed pending-pause record whose token a resume could accept.

    Marker-bearing; not an ``--only`` run (never a resume source); not INLINE (``ir-hash:`` — the loader's
    inline refusal precedes the paused arm); a ``paused`` trailer with the ``paused_node_id`` +
    ``gate_request`` the loader requires. Consumption is a separate check (``_find_consuming_attempt``)."""
    if not entry.paused or entry.only or meta is None or trailer is None:
        return False
    workflow_path = meta.get("workflow_path")
    return (
        meta.get("only_node") is None
        and isinstance(workflow_path, str)
        and not workflow_path.startswith("ir-hash:")
        and trailer.get("final_status") == "paused"
        and isinstance(trailer.get("paused_node_id"), str)
        and isinstance(trailer.get("gate_request"), dict)
    )


def answerable_pause(
    entry: TraceEntry,
    meta: dict[str, Any] | None,
    trailer: dict[str, Any] | None,
    file_state: PathState,
) -> Literal["yes", "no", "unknown"]:
    """Can this trace's Resume token still be answered (consumption aside)? The ONE predicate ``resume
    list`` and Retention's rule 1 share, so the list, the resume verdict and retention agree.

    A well-formed pause record (``is_pause_record``) whose workflow file is ``present`` → ``yes``; its file
    ``absent`` → ``no`` (a by-id resume re-resolves the file and refuses, so the token can never be
    spent); ``unknown`` → ``unknown``. Pure: callers pass the strict reads (a fault is reported by the
    caller, never read as "no pause") and ``path_state.path_state``."""
    if not is_pause_record(entry, meta, trailer) or file_state == "absent":
        return "no"
    return "yes" if file_state == "present" else "unknown"


def list_paused_runs(debug_dir: Path | None = None) -> PausedRunListing:
    """Pending paused runs (answerable ∧ not consumed), newest first — ``pflow resume list`` (Task 171).

    Reads only the marked traces of one listing. A row is shown when ``answerable_pause`` says ``yes`` or
    ``unknown`` (the workflow file's existence could not be determined — the renderer notes it) and
    ``_find_consuming_attempt`` — the ONE consumption policy shared with the loader — finds no consumer, so
    the list and a resume verdict can never disagree. Nothing pending is dropped silently: a valid,
    unconsumed pause whose workflow file is gone is returned in ``hidden_missing_file``, and a marked trace
    that cannot be read (it may be pending) in ``unreadable``. A candidate that vanishes mid-check is
    skipped; a marked trace with no trailer (a crash between the marker and the trailer) is not a pause.
    No live-lock probe: a paused trace is finalized, so its writer lock is never held.
    """
    listing = list_traces(debug_dir)
    pending: list[PausedRun] = []
    hidden: list[PausedRun] = []
    unreadable: list[str] = []
    for entry in listing.traces:
        if not entry.paused:
            continue
        try:
            meta = read_trace_meta_strict(entry.path)
            trailer = read_trace_trailer_strict(entry.path)
        except FileNotFoundError:
            continue
        except TraceUnreadableError as exc:
            unreadable.append(str(exc))
            continue
        if meta is None or trailer is None or not is_pause_record(entry, meta, trailer):
            continue
        workflow_path = str(meta["workflow_path"])
        verdict = answerable_pause(entry, meta, trailer, path_state(workflow_path))
        execution_id = str(meta.get("execution_id") or "")
        if execution_id and _find_consuming_attempt(workflow_path, execution_id, entries=listing.traces) is not None:
            continue
        row = _paused_run_row(entry.path, meta, trailer)
        (hidden if verdict == "no" else pending).append(row)
    return PausedRunListing(
        runs=pending, hidden_missing_file=hidden, unreadable=unreadable, legacy_count=listing.legacy_count
    )


def _paused_run_row(path: Path, meta: dict[str, Any], trailer: dict[str, Any]) -> PausedRun:
    gate_request: dict[str, Any] = trailer["gate_request"]
    gate_kind = gate_request.get("kind")
    iteration = gate_request.get("iteration")
    max_iterations = gate_request.get("max_iterations")
    paused_at = trailer.get("end_time")
    workflow_name = meta.get("workflow_name")
    return PausedRun(
        execution_id=str(meta.get("execution_id") or ""),
        workflow_name=workflow_name if isinstance(workflow_name, str) else None,
        workflow_path=str(meta["workflow_path"]),
        paused_node_id=str(trailer["paused_node_id"]),
        gate_kind=gate_kind if isinstance(gate_kind, str) else None,
        paused_at=paused_at if isinstance(paused_at, str) else None,
        path=path,
        iteration=iteration if isinstance(iteration, int) else None,
        max_iterations=max_iterations if isinstance(max_iterations, int) else None,
    )
