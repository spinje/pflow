"""Resume loader (Task 164): select and vet a prior run's trace as a resume source.

Extracted from ``runtime/workflow_trace.py`` (Task 171) once the resume loader became the
third consumer-shaped growth spurt beside the collector/readers. This module owns the ONE
resume-scoped read (``load_resume_source``), the between-nodes/failed/incomplete entry
resolvers, the raw-JSONL reader for the disk-only ``kind:"gate"`` / ``node.start`` lines,
the attempt-chain consumption policy, the seed-scope guards, and the snapshot seeder
(``seed_snapshot_into_shared``) — which shares the ONE ``_seedable_final_events`` derivation
with the guards so seeding and guarding can never drift.

The general trace helpers it builds on (``_iter_workflow_traces``, ``_trace_recency_key``,
``final_events_by_node``, ``_unrecovered_failed_node_ids``) stay in ``workflow_trace`` — they
are shared with the collector and cache-analysis autoload — and are imported back here. This
module never imports ``ui/`` (the standing ``runtime/`` rule), which is why ``_is_trace_locked``
is duplicated from ``ui.run_tailer`` rather than imported.
"""

import json
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from pflow.core.exceptions import (
    ResumeAnswerRequiredError,
    ResumeFidelityError,
    ResumeGateStoppedError,
    ResumeNothingToResumeError,
    ResumeNotResumableError,
    ResumeSourceMissingError,
    ResumeStillRunningError,
    ResumeSupersededError,
)
from pflow.core.gate import GATE_KIND_APPROVAL, GATE_KIND_ESCALATION, option_labels
from pflow.core.trace_io import load_trace_file
from pflow.runtime.workflow_trace import (
    _iter_workflow_traces,
    _trace_recency_key,
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


def _is_trace_locked(path: Path) -> bool | None:
    """Best-effort advisory-lock liveness probe (local copy of ``ui.run_tailer.is_trace_locked``).

    ``runtime/`` must not import ``ui/``, so this ~15-line probe is duplicated
    (accepted until a third consumer earns a ``core/`` home — Task 164 plan §B).
    Same semantics: a SHARED, non-blocking probe on a SEPARATE fd — ``True`` when a
    live writer holds the producer's EXCLUSIVE lock, ``False`` when free, ``None``
    when liveness can't be determined (no ``fcntl`` / unopenable).
    """
    try:
        import fcntl
    except ImportError:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
    except OSError:
        return None


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


def _read_trace_meta_line(path: Path) -> dict[str, Any] | None:
    """Return the trace's first (``kind:"meta"``) line without parsing the whole file, else ``None``.

    Used by the by-execution-id scan so matching one run doesn't parse every
    file's full content. Any read/parse fault → ``None`` (skip this candidate).
    """
    try:
        with open(path, encoding="utf-8") as handle:
            first = handle.readline()
    except OSError:
        return None
    try:
        line = json.loads(first)
    except ValueError:
        return None
    if isinstance(line, dict) and line.get("kind") == "meta":
        return line
    return None


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


def _find_consuming_attempt(debug_dir: Path, workflow_path: str, execution_id: str) -> str | None:
    """The execution id of a newer attempt that CONSUMED this run's chain, or ``None``.

    THE one consumption policy, two callers — ``load_resume_source`` (raises
    ``ResumeSupersededError``) and ``list_paused_runs`` (filters consumed tokens)
    — so the loader and ``resume list`` can never disagree on whether a token is
    still answerable. An attempt supersedes its source only when it consumed the
    chain (``_attempt_consumed_work``) or is live right now (mid-first-step there
    is no terminal event yet, but its writer lock is held). A DEAD zero-work
    attempt — a refused ``--force`` resume, a crash before the entry — consumed
    nothing; counting it would wedge the chain (the source reads superseded while
    the empty attempt itself refuses with "no resumable failed step").
    """
    for candidate_path, candidate in _iter_workflow_traces(debug_dir, workflow_path):
        if candidate.get("resumed_from") != execution_id:
            continue
        if _attempt_consumed_work(candidate_path, candidate) or _is_trace_locked(candidate_path) is True:
            return str(candidate.get("execution_id") or "")
    return None


def _raise_resume_source_missing(debug_dir: Path, workflow_path: str | None, execution_id: str | None) -> NoReturn:
    if execution_id is not None:
        raise ResumeSourceMissingError(
            f"No run with execution id '{execution_id}' was found in {debug_dir}.",
            execution_id=execution_id,
            suggestions=["Check the execution id, or run the workflow so a trace exists to resume."],
        )
    raise ResumeSourceMissingError(
        f"No resumable run was found for workflow '{workflow_path}' in {debug_dir}.",
        suggestions=["Run the workflow once (without --no-trace) so a failure can be resumed."],
    )


def _select_resume_trace(
    debug_dir: Path, workflow_path: str | None, execution_id: str | None
) -> tuple[Path, dict[str, Any]]:
    """Select the source trace: newest for a workflow, or the exact run by execution id."""
    if not debug_dir.exists():
        _raise_resume_source_missing(debug_dir, workflow_path, execution_id)
    if workflow_path is not None:
        for trace_file, data in _iter_workflow_traces(debug_dir, workflow_path):
            # Skip a DEAD zero-work attempt (a refused --force resume / crash before
            # the first step) so `resume <workflow>` falls through to the older
            # resumable run instead of wedging on it. A killed-mid-step trace is NOT
            # dead (it has a dangling start → still resumable) and a LIVE run is not
            # dead either (selected, then refused as still-running). By-exec-id below
            # never skips — naming an exact attempt gets a verdict about THAT attempt.
            if not _attempt_consumed_work(trace_file, data) and _is_trace_locked(trace_file) is not True:
                continue
            return trace_file, data  # first non-dead = newest resumable
        _raise_resume_source_missing(debug_dir, workflow_path, execution_id)
    for trace_file in sorted(debug_dir.glob("workflow-trace-*.json"), key=_trace_recency_key, reverse=True):
        meta = _read_trace_meta_line(trace_file)
        if meta is None or meta.get("execution_id") != execution_id:
            continue
        # Mirror _iter_workflow_traces's --only exclusion: an --only run records
        # only its target, so resuming its exec id would seed an empty scope.
        if meta.get("only_node") is not None:
            continue
        try:
            return trace_file, load_trace_file(trace_file)
        except (json.JSONDecodeError, OSError):
            # Same skip-corrupt posture as _iter_workflow_traces (the workflow_path
            # arm gets this for free): a matched-but-corrupt trace degrades to a
            # clean "missing" refusal, never an uncaught JSONDecodeError traceback.
            logger.debug("Skipping unparseable resume-source trace %s", trace_file, exc_info=True)
            continue
    _raise_resume_source_missing(debug_dir, workflow_path, execution_id)


def _seedable_final_events(events: list[dict[str, Any]], entry_node_id: str | None) -> dict[str, dict[str, Any]]:
    """THE seedable set: each node's final event BEFORE the entry, minus failed-final-status nodes.

    The single derivation shared by seeding (``seed_snapshot_into_shared``) and
    the loader guards (``_guard_seed_scope``), so they cannot drift: the guards
    scan exactly the values resume will restore — nothing more (a superseded
    earlier loop-iteration event is never seeded, so its contents must not
    refuse a resume) and nothing less. Failed-final-status nodes are excluded
    (seed fidelity — their data lived in ``__failures__``, never the store).
    ``entry_node_id=None`` (incomplete between-nodes resume) scopes to ALL
    events. The slice ends before the entry's FIRST event, so the returned map
    provably never contains the entry itself.
    """
    if entry_node_id is None:
        scope = events
    else:
        idx = next((i for i, e in enumerate(events) if e.get("node_id") == entry_node_id), None)
        scope = events if idx is None else events[:idx]
    return {nid: ev for nid, ev in final_events_by_node(scope).items() if ev.get("status") != "failed"}


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
    ``decision``; string marker becomes ``{"question", "decision"}``). Applied to
    each node's FINAL event in file order, so a looping node's last resolution
    wins — pairing with the final event that seeding restores.
    """
    final = final_events_by_node(events)
    for line in _iter_raw_trace_lines(path):
        if line.get("kind") != "gate" or line.get("phase") != "resolution":
            continue
        decision = line.get("decision")
        if not isinstance(decision, dict):
            continue  # approval/denied/non-interactive resolutions carry no decision
        _fold_decision_into_event(final.get(line.get("node_id")), decision)  # type: ignore[arg-type]


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
        # gated node has NO event in the trace, so `_seedable_final_events`
        # provably excludes it and the seed-scope guards compose unchanged.
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


def _guard_seed_scope(scope: Iterable[dict[str, Any]], execution_id: str, path: Path) -> None:
    """Refuse if any node resume would SEED carries undecided escalation (Decision 8) or lossy binary (Decision 5).

    ``scope`` is the ``_seedable_final_events`` values — exactly what seeding
    restores. Escalation markers were already folded with their recorded
    decisions (``_apply_gate_resolutions``), so an undecided marker here means
    the run genuinely never resolved it (e.g. killed between the node's event
    and the gate resolution) — never a resolved-but-frozen fidelity artifact.
    """
    for event in scope:
        output = event.get("node_output")
        if not isinstance(output, dict):
            continue
        node_id = event.get("node_id")
        node_id_str = node_id if isinstance(node_id, str) else None
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
        for key, value in output.items():
            if _contains_binary_placeholder(value):
                raise ResumeFidelityError(
                    node_id=str(node_id_str or "?"),
                    key=str(key),
                    execution_id=execution_id,
                    trace_path=str(path),
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
    events: list[dict[str, Any]],
    gate_answer: dict[str, Any] | None,
    execution_id: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """The whole Task-171 answer policy in one seam: validate, then fold an escalation's answer.

    Returns ``(paused_node_id, gate_request)`` — ``(None, None)`` for non-paused
    sources. Non-paused + an answer flag → ``not_paused`` refusal (the flag
    answers nothing; refuse rather than ignore it — loader-side so by-exec-id
    and by-name behave identically). Paused → the answer must exist and match
    the gate kind (``_validate_gate_answer``); an escalation's ``chosen`` is then
    folded into the paused node's final event using the identical marker shape
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
        _fold_decision_into_event(final_events_by_node(events).get(paused_node_id), decision)
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
    debug_dir = debug_dir if debug_dir is not None else (Path.home() / ".pflow" / "debug")

    path, data = _select_resume_trace(debug_dir, workflow_path, execution_id)
    source_execution_id = str(data.get("execution_id") or "")
    source_workflow_path = data.get("workflow_path")

    if isinstance(source_workflow_path, str) and source_workflow_path.startswith("ir-hash:"):
        raise ResumeNotResumableError(
            "Inline or piped workflows cannot be resumed — there is no source file to re-resolve.",
            execution_id=source_execution_id,
            trace_path=str(path),
            suggestions=["Save the workflow to a file and re-run it so future failures can be resumed."],
        )

    if _is_trace_locked(path) is True:
        raise ResumeStillRunningError(
            "This run is still in progress.",
            execution_id=source_execution_id,
            trace_path=str(path),
            suggestions=["Wait for the run to finish (or stop it), then resume."],
        )

    if source_execution_id and isinstance(source_workflow_path, str):
        consuming = _find_consuming_attempt(debug_dir, source_workflow_path, source_execution_id)
        if consuming is not None:
            raise ResumeSupersededError(
                consuming,
                execution_id=source_execution_id,
                trace_path=str(path),
            )

    entry_node_id, last_completed_node_id = _resolve_resume_entry(path, data, source_execution_id)

    events = list(data.get("nodes") or [])
    _apply_gate_resolutions(path, events)
    paused_node_id, gate_request = _apply_paused_answer(path, data, events, gate_answer, source_execution_id)
    _guard_seed_scope(_seedable_final_events(events, entry_node_id).values(), source_execution_id, path)

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
    )


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

    NEVER seeds ``exclude`` itself — ``_seedable_final_events``'s slice ends
    before the target's first event, so the target must execute fresh, never
    read a stale copy of itself. Returns that seedable map (failed-final-status
    nodes excluded), so callers derive ``restored_nodes`` — and the resume
    re-record loop — from exactly what was seeded, without a second pass.
    """
    final = _seedable_final_events(events, exclude)
    for nid, ev in final.items():
        output = ev.get("node_output")
        if output is None:
            continue
        shared[nid] = {k: v for k, v in output.items() if k not in _SNAPSHOT_RESERVED}
    return final


# ── Resume list (Task 171) ──────────────────────────────────────────────────
# `pflow resume list` is a STATUS QUERY over the debug dir, not a separate
# registry: a paused trace IS the pending obligation. Cheap by construction —
# a head read (meta line) + a tail read (trailer) per file; the only full
# parses are `_find_consuming_attempt`'s over each candidate's chain (accepted
# v1 inefficiency — "a status query", per spec).


@dataclass(frozen=True)
class PausedRun:
    """One pending paused run — a ``resume list`` row (Task 171).

    ``gate_kind`` is ``gate_request["kind"]`` (the payload stays the one source
    of truth — the row carries only what the list renders); ``paused_at`` is the
    trailer's ``end_time`` ISO string (the moment the run finalized paused).
    """

    execution_id: str
    workflow_name: str | None
    workflow_path: str | None
    paused_node_id: str
    gate_kind: str | None
    paused_at: str | None
    path: Path


def _scan_tail_for_trailer(tail: bytes) -> tuple[dict[str, Any] | None, bool]:
    """Inspect the LAST non-empty line of a byte tail: ``(trailer_dict, parse_ok)``.

    ``(dict, True)`` when it is the ``run.complete`` trailer; ``(None, True)``
    when it parsed but is NOT the trailer (run not finished) or the tail is
    empty; ``(None, False)`` when it FAILED to parse — the caller disambiguates
    a genuine mid-flush from a window that cut a fully-flushed oversized trailer.
    """
    for raw in reversed(tail.split(b"\n")):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except ValueError:
            return None, False
        if isinstance(line, dict) and line.get("kind") == "run.complete":
            return line, True
        return None, True  # a complete-but-non-trailer last line → not finished
    return None, True  # empty tail


def _read_trailer_line(path: Path) -> dict[str, Any] | None:
    """The parsed ``run.complete`` trailer dict of a finalized trace, or ``None`` — a cheap tail read.

    ``resume list`` scans every trace in the debug dir; a full ``load_trace_file``
    per file would make a status query O(total trace bytes). Mirrors
    ``ui.run_tailer.read_run_status``'s mechanics — the SAME accepted
    ``runtime/ ↛ ui/`` duplication as ``_is_trace_locked`` above (importing
    ``ui`` here fails ``test_import_hygiene.py::test_runtime_does_not_import_ui``):
    read a bounded 64 KB tail and inspect the LAST non-empty line. A trailer
    LARGER than the window — a paused trailer carries the full ``gate_request``,
    so many-small-fields previews can exceed it — gets cut mid-line and would
    misread as missing, silently hiding a legitimate paused run from the list.
    So when the last line fails to parse BUT the file exceeds the window AND
    ends with a newline (its last line IS fully flushed), re-read the whole file
    ONCE. A genuine mid-flush has no trailing newline and stays ``None``.
    """
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            tail = handle.read()
            trailer, parse_ok = _scan_tail_for_trailer(tail)
            if not parse_ok and size > 65536 and tail.endswith(b"\n"):
                handle.seek(0)
                trailer, _ = _scan_tail_for_trailer(handle.read())
    except OSError:
        return None
    return trailer


def list_paused_runs(debug_dir: Path | None = None) -> list[PausedRun]:
    """Pending paused runs (paused ∧ not consumed), newest first — ``pflow resume list`` (Task 171).

    Skips, in scan order: unreadable/meta-less files; ``--only`` runs (never
    resume sources); INLINE runs (``ir-hash:`` — the loader's inline refusal
    precedes the paused arm, so their token is unanswerable; listing a row whose
    command always refuses would be a lie. The producer-side pause-promise gap
    for inline gated runs awaits an owner decision — see the Task 171 progress
    log); non-paused trailers; corrupt pause records (no ``paused_node_id`` /
    ``gate_request`` — the loader refuses those too); and CONSUMED tokens via
    ``_find_consuming_attempt`` — the ONE consumption policy shared with the
    loader, so the list and a resume verdict can never disagree on whether a
    token is still answerable. No live-lock probe: a paused trace is finalized,
    so its writer lock is never held.
    """
    debug_dir = debug_dir if debug_dir is not None else (Path.home() / ".pflow" / "debug")
    if not debug_dir.exists():
        return []
    pending: list[PausedRun] = []
    for trace_file in sorted(debug_dir.glob("workflow-trace-*.json"), key=_trace_recency_key, reverse=True):
        meta = _read_trace_meta_line(trace_file)
        if meta is None or meta.get("only_node") is not None:
            continue
        workflow_path = meta.get("workflow_path")
        if not isinstance(workflow_path, str) or workflow_path.startswith("ir-hash:"):
            continue
        trailer = _read_trailer_line(trace_file)
        if trailer is None or trailer.get("final_status") != "paused":
            continue
        paused_node_id = trailer.get("paused_node_id")
        gate_request = trailer.get("gate_request")
        if not isinstance(paused_node_id, str) or not isinstance(gate_request, dict):
            continue
        execution_id = str(meta.get("execution_id") or "")
        if execution_id and _find_consuming_attempt(debug_dir, workflow_path, execution_id) is not None:
            continue
        gate_kind = gate_request.get("kind")
        paused_at = trailer.get("end_time")
        workflow_name = meta.get("workflow_name")
        pending.append(
            PausedRun(
                execution_id=execution_id,
                workflow_name=workflow_name if isinstance(workflow_name, str) else None,
                workflow_path=workflow_path,
                paused_node_id=paused_node_id,
                gate_kind=gate_kind if isinstance(gate_kind, str) else None,
                paused_at=paused_at if isinstance(paused_at, str) else None,
                path=trace_file,
            )
        )
    return pending
