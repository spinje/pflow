"""``load_resume_source`` — the resume loader's failed-trace arms (Task 164, Phase 1).

Covers selection (newest-for-workflow, by-execution-id), the refusal ladder
(inline source, liveness, superseded, success/denied/gate-stopped status arms,
undecided-escalation + lossy-binary seed-scope guards), the event-order entry
rule for multi-failure traces, the Phase-5 ``incomplete`` arm (Decision 7:
killed-mid-node via a dangling ``node.start``, killed-between-nodes, meta-only,
locked-incomplete), and the happy-path ``ResumeSource`` fields.

Fixtures are written with the shared JSONL serializer (``tests/shared/trace_jsonl``)
so they read back through the exact production reader (``load_trace_file``).
Gate lines are disk-only (never in the nested trace dict), so the gate-stopped
fixture splices them in before the ``run.complete`` trailer by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import (
    ResumeAnswerRequiredError,
    ResumeFidelityError,
    ResumeGateStoppedError,
    ResumeNothingToResumeError,
    ResumeNotResumableError,
    ResumeSideEffectConfirmationError,
    ResumeSourceMissingError,
    ResumeStaleWorkflowError,
    ResumeStillRunningError,
    ResumeSupersededError,
    StepIdentityChanges,
)
from pflow.runtime.resume_source import (
    ResumeSource,
    _iter_raw_trace_lines,
    entry_never_started,
    load_resume_source,
    restored_node_ids,
    seed_snapshot_into_shared,
)
from pflow.runtime.workflow_trace import format_trace_filename
from tests.shared.trace_jsonl import flatten_trace_to_lines, write_trace_jsonl

WF = "/work/project/wf.pflow.md"


def _node(
    node_id: str, *, status: str = "success", output: dict[str, Any] | None = None, iteration: int | None = None
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "node_id": node_id,
        "node_type": "ShellNode",
        "status": status,
        "node_output": output if output is not None else {"stdout": f"{node_id}-out"},
    }
    if iteration is not None:  # trace 2.8.0: loop-node events only, like the producer
        event["iteration"] = iteration
    return event


def _write_trace(
    debug_dir: Path,
    *,
    workflow_path: str = WF,
    execution_id: str,
    timestamp: str,
    final_status: str = "failed",
    nodes: list[dict[str, Any]] | None = None,
    content_hash: str | None = "hash-v1",
    inputs: dict[str, Any] | None = None,
    only_node: str | None = None,
    failed_node_ids: list[str] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    resumed_from: str | None = None,
    name: str = "wf",
    gate_lines: list[dict[str, Any]] | None = None,
    paused_node_id: str | None = None,
    gate_request: dict[str, Any] | None = None,
    format_version: str = "2.5.0",
    step_identity: Any = None,
) -> Path:
    """Write a synthetic resume-source trace the loader can discover, returning its path."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "format_version": format_version,
        "execution_id": execution_id,
        "workflow_name": name,
        "workflow_path": workflow_path,
        "only_node": only_node,
        "content_hash": content_hash,
        "inputs": inputs,
        "final_status": final_status,
        "nodes": nodes if nodes is not None else [_node("k", status="failed", output={})],
    }
    if failed_node_ids is not None:
        data["failed_node_ids"] = failed_node_ids
    if warnings is not None:
        data["warnings"] = warnings
    if resumed_from is not None:
        data["resumed_from"] = resumed_from
    if step_identity is not None:
        data["step_identity"] = step_identity
    # Task 171: the pause record rides the run.complete trailer; the fixture
    # builder routes non-META keys there, matching the producer.
    if paused_node_id is not None:
        data["paused_node_id"] = paused_node_id
    if gate_request is not None:
        data["gate_request"] = gate_request
    path = debug_dir / format_trace_filename(workflow_path, name, timestamp)
    if gate_lines:
        lines = flatten_trace_to_lines(data)
        rc_idx = next(i for i, line in enumerate(lines) if line.get("kind") == "run.complete")
        lines = lines[:rc_idx] + gate_lines + lines[rc_idx:]
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    else:
        write_trace_jsonl(path, data)
    return path


# ── Selection ───────────────────────────────────────────────────────────────


def test_workflow_path_selects_newest_failed(tmp_path: Path) -> None:
    _write_trace(tmp_path, execution_id="old", timestamp="20260101-000000")
    _write_trace(tmp_path, execution_id="new", timestamp="20260102-000000")
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.execution_id == "new"
    assert source.entry_node_id == "k"


def test_by_execution_id_selects_exact_attempt(tmp_path: Path) -> None:
    _write_trace(tmp_path, execution_id="old", timestamp="20260102-000000")  # newer on disk
    _write_trace(tmp_path, execution_id="target", timestamp="20260101-000000")  # older, but requested
    source = load_resume_source(execution_id="target", debug_dir=tmp_path)
    assert source.execution_id == "target"


def test_by_execution_id_skips_only_node_run(tmp_path: Path) -> None:
    """An --only run records only its target; resuming its exec id must not seed an empty scope."""
    _write_trace(tmp_path, execution_id="only-run", timestamp="20260101-000000", only_node="k")
    with pytest.raises(ResumeSourceMissingError):
        load_resume_source(execution_id="only-run", debug_dir=tmp_path)


def test_no_trace_for_workflow_raises_missing(tmp_path: Path) -> None:
    with pytest.raises(ResumeSourceMissingError):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def test_missing_debug_dir_raises_missing(tmp_path: Path) -> None:
    with pytest.raises(ResumeSourceMissingError):
        load_resume_source(execution_id="whatever", debug_dir=tmp_path / "nope")


def test_exactly_one_selector_required() -> None:
    with pytest.raises(ValueError):
        load_resume_source()
    with pytest.raises(ValueError):
        load_resume_source(workflow_path=WF, execution_id="x")


# ── Refusal ladder ────────────────────────────────────────────────────────────


def test_inline_source_refused(tmp_path: Path) -> None:
    inline = "ir-hash:deadbeef"
    _write_trace(tmp_path, workflow_path=inline, execution_id="inline-1", timestamp="20260101-000000")
    with pytest.raises(ResumeNotResumableError, match=r"[Ii]nline"):
        load_resume_source(execution_id="inline-1", debug_dir=tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="advisory flock is POSIX-only")
def test_live_locked_trace_refused(tmp_path: Path) -> None:
    import fcntl

    path = _write_trace(tmp_path, execution_id="live-1", timestamp="20260101-000000")
    with open(path, encoding="utf-8") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ResumeStillRunningError):
            load_resume_source(execution_id="live-1", debug_dir=tmp_path)


def test_superseded_points_at_newer_attempt(tmp_path: Path) -> None:
    _write_trace(tmp_path, execution_id="src", timestamp="20260101-000000")
    _write_trace(
        tmp_path,
        execution_id="resume-2",
        timestamp="20260102-000000",
        final_status="success",
        resumed_from="src",
    )
    with pytest.raises(ResumeSupersededError) as excinfo:
        load_resume_source(execution_id="src", debug_dir=tmp_path)
    assert excinfo.value.newer_execution_id == "resume-2"
    assert "pflow resume resume-2" in " ".join(excinfo.value.suggestions)


def _restored(node_id: str) -> dict[str, Any]:
    """An upstream re-record as _prepare_resume writes it (cached + restored, zero work)."""
    return {
        "node_id": node_id,
        "node_type": "ShellNode",
        "status": "cached",
        "restored": True,
        "node_output": {"stdout": f"{node_id}-out"},
    }


def test_attempt_killed_mid_step_supersedes_its_source(tmp_path: Path) -> None:
    """C1: an attempt SIGKILL'd mid-step (dangling start, side effect may have fired) DID consume
    the chain — resuming the source must refuse as superseded, not silently re-run the started step."""
    _write_trace(tmp_path, execution_id="src", timestamp="20260101-000000")
    _write_incomplete_trace(
        tmp_path,
        execution_id="att",
        timestamp="20260102-000000",  # newer
        completed=[_restored("step1")],  # upstream re-records only...
        killed_node="step2",  # ...then killed mid-step2 (dangling start, no terminal event)
        resumed_from="src",
    )
    with pytest.raises(ResumeSupersededError) as excinfo:
        load_resume_source(execution_id="src", debug_dir=tmp_path)
    assert excinfo.value.newer_execution_id == "att"


def test_dead_zero_work_attempt_does_not_wedge_workflow_resume(tmp_path: Path) -> None:
    """C4: a DEAD zero-work attempt (crash before the first step) is newest, but `resume <workflow>`
    must skip it and fall through to the older resumable source, not refuse 'nothing to resume'."""
    _write_trace(tmp_path, execution_id="src", timestamp="20260101-000000")  # resumable, older
    _write_trace(
        tmp_path,
        execution_id="dead",
        timestamp="20260102-000000",  # newest, but did nothing
        nodes=[],
        failed_node_ids=[],
        resumed_from="src",
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.execution_id == "src"
    assert source.entry_node_id == "k"


def test_workflow_resume_does_not_skip_a_resumable_interrupted_run(tmp_path: Path) -> None:
    """C4 over-skip guard: a killed-mid-step run (dangling start, zero completed events) is NOT dead —
    it is the newest resumable attempt and must be selected, not skipped for an older failed run."""
    _write_trace(tmp_path, execution_id="src", timestamp="20260101-000000")  # older failed run
    _write_incomplete_trace(
        tmp_path,
        execution_id="killed",
        timestamp="20260102-000000",  # newest, killed mid-first-step
        completed=[],
        killed_node="step1",
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.execution_id == "killed"
    assert source.entry_node_id == "step1"


@pytest.mark.skipif(sys.platform == "win32", reason="advisory flock is POSIX-only")
def test_workflow_resume_does_not_skip_a_live_zero_work_run(tmp_path: Path) -> None:
    """C4 race guard: a live run with no steps yet (meta only, lock held) must NOT be skipped for an
    older run — it is selected and refused as still-running, closing a double-resume window."""
    import fcntl

    _write_trace(tmp_path, execution_id="src", timestamp="20260101-000000")  # older resumable
    live = _write_incomplete_trace(
        tmp_path,
        execution_id="live",
        timestamp="20260102-000000",  # newest, live, no events yet
        completed=[],
    )
    with open(live, encoding="utf-8") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ResumeStillRunningError):
            load_resume_source(workflow_path=WF, debug_dir=tmp_path)


@pytest.mark.parametrize("status", ["success", "degraded"])
def test_succeeded_run_has_nothing_to_resume(tmp_path: Path, status: str) -> None:
    _write_trace(tmp_path, execution_id="ok", timestamp="20260101-000000", final_status=status)
    with pytest.raises(ResumeNothingToResumeError):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def test_denied_run_refused(tmp_path: Path) -> None:
    _write_trace(tmp_path, execution_id="denied-1", timestamp="20260101-000000", final_status="denied")
    with pytest.raises(ResumeNotResumableError):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def _write_incomplete_trace(
    debug_dir: Path,
    *,
    execution_id: str,
    timestamp: str,
    completed: list[dict[str, Any]],
    killed_node: str | None = None,
    workflow_path: str = WF,
    name: str = "wf",
    resumed_from: str | None = None,
    gate_lines: list[dict[str, Any]] | None = None,
) -> Path:
    """Write a production-faithful incomplete (interrupted) trace, returning its path.

    Meta + one ``event`` line per completed node + an optional dangling
    ``node.start`` (``parent_id=None``, an ``id`` beyond the completed events) for
    a node killed mid-execution — and NO ``run.complete`` trailer, so the reader
    synthesizes ``final_status="incomplete"`` exactly as a real Ctrl+C/SIGKILL run.
    """
    debug_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "format_version": "2.5.0",
        "execution_id": execution_id,
        "workflow_name": name,
        "workflow_path": workflow_path,
        "only_node": None,
        "content_hash": "hash-v1",
        "inputs": None,
        "nodes": completed,
    }
    if resumed_from is not None:
        data["resumed_from"] = resumed_from
    lines = [line for line in flatten_trace_to_lines(data) if line.get("kind") != "run.complete"]
    if killed_node is not None:
        next_id = max((line["id"] for line in lines if line.get("kind") == "event"), default=-1) + 1
        lines.append({
            "kind": "node.start",
            "id": next_id,
            "seq": next_id,
            "parent_id": None,
            "node_id": killed_node,
            "node_type": "ShellNode",
            "run_id": execution_id,
        })
    lines.extend(gate_lines or [])
    path = debug_dir / format_trace_filename(workflow_path, name, timestamp)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def test_incomplete_killed_mid_node_enters_at_dangling_start(tmp_path: Path) -> None:
    """A top-level node.start with no matching terminal event = the killed-mid-node K (Decision 7)."""
    _write_incomplete_trace(
        tmp_path,
        execution_id="crash-mid",
        timestamp="20260101-000000",
        completed=[_node("a"), _node("b")],
        killed_node="c",
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "c"
    assert source.last_completed_node_id is None


def test_incomplete_killed_between_nodes_returns_last_completed(tmp_path: Path) -> None:
    """No dangling start, ≥1 event → entry None + last_completed (the CLI resolves the successor)."""
    _write_incomplete_trace(
        tmp_path,
        execution_id="crash-between",
        timestamp="20260101-000000",
        completed=[_node("a"), _node("b")],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id is None
    assert source.last_completed_node_id == "b"


def test_incomplete_meta_only_has_nothing_to_resume(tmp_path: Path) -> None:
    """Crashed before the first step completed (no events, no dangling start) → nothing to resume.

    Addressed by execution id: the by-exec-id selector never skips, so it reaches the incomplete
    arm's specific message. (Via `resume <workflow>` this same dead trace is skipped as zero-work
    and surfaces the generic 'no resumable run' — see the C4 selection tests.)
    """
    _write_incomplete_trace(
        tmp_path,
        execution_id="crash-empty",
        timestamp="20260101-000000",
        completed=[],
    )
    with pytest.raises(ResumeNothingToResumeError, match=r"before its first step"):
        load_resume_source(execution_id="crash-empty", debug_dir=tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="advisory flock is POSIX-only")
def test_incomplete_locked_trace_refused_before_status_arm(tmp_path: Path) -> None:
    """Liveness runs FIRST: a flock-held incomplete trace is a live run, not a crash — refuse."""
    import fcntl

    path = _write_incomplete_trace(
        tmp_path,
        execution_id="live-incomplete",
        timestamp="20260101-000000",
        completed=[_node("a")],
        killed_node="b",
    )
    with open(path, encoding="utf-8") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ResumeStillRunningError):
            load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def test_gate_stopped_run_names_the_gate(tmp_path: Path) -> None:
    """A failed run with NO unrecovered failed node = gate-stopped (recovered from disk-only gate lines)."""
    _write_trace(
        tmp_path,
        execution_id="gate-1",
        timestamp="20260101-000000",
        final_status="failed",
        nodes=[_node("upstream")],  # no failed node
        gate_lines=[
            {"kind": "gate", "node_id": "approve-deploy", "phase": "pause", "gate_kind": "approval"},
            {"kind": "gate", "node_id": "approve-deploy", "phase": "resolution", "resolution": "non_interactive"},
        ],
    )
    with pytest.raises(ResumeGateStoppedError) as excinfo:
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert excinfo.value.node_id == "approve-deploy"
    assert "approval" in str(excinfo.value)


def test_failed_with_no_failed_node_and_no_gate_refuses_generically(tmp_path: Path) -> None:
    """Defensive arm: failed + no unrecovered node + zero gate lines → clean refusal, never an undefined branch."""
    _write_trace(
        tmp_path,
        execution_id="weird-1",
        timestamp="20260101-000000",
        final_status="failed",
        nodes=[_node("upstream")],
    )
    with pytest.raises(ResumeNotResumableError):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


# ── Entry derivation + seed-scope guards ──────────────────────────────────────


def test_both_primary_and_fallback_failed_enters_at_the_root(tmp_path: Path) -> None:
    """PRODUCTION shape: K (primary) fails → on-error → F (fallback) also fails (Decision 9 / ADR-0010).

    Real on-error routing tags the recovered primary K with an ``on_error_recovery``
    warning (this is the shape a live run writes — the earlier fictional fixture
    OMITTED it). No node succeeded after K, so the terminal-failure region starts
    at K: resume enters at K (the root), NOT the fallback F. Fixing K's cause then
    bypasses F entirely on the walk. Names chosen so alphabetical (F='alpha') would
    disagree with the correct answer (K='zeta')."""
    _write_trace(
        tmp_path,
        execution_id="both-fail",
        timestamp="20260101-000000",
        nodes=[_node("zeta", status="failed", output={}), _node("alpha", status="failed", output={})],
        warnings=[{"node_id": "zeta", "type": "on_error_recovery"}],  # zeta routed to its on-error F
        failed_node_ids=["alpha"],  # only the unrecovered F, as save_to_file writes it
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "zeta"


def test_recovery_that_succeeded_is_not_the_entry(tmp_path: Path) -> None:
    """PRODUCTION shape: K fails → recovery SUCCEEDS → a later, separate node fails.

    The success between the recovered K and the later failure is what makes K's
    recovery genuinely 'done' — so resume must NOT re-run the recovered K, it
    enters at the later real failure (Temporal's frontier). The earlier fictional
    fixture omitted that success, making it indistinguishable from the both-fail
    case above."""
    _write_trace(
        tmp_path,
        execution_id="rec-ok",
        timestamp="20260101-000000",
        nodes=[
            _node("recovered", status="failed", output={}),
            _node("handler", status="success"),  # the recovery SUCCEEDED — the run progressed
            _node("real", status="failed", output={}),
        ],
        warnings=[{"node_id": "recovered", "type": "on_error_recovery"}],
        failed_node_ids=["real"],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "real"


def test_gate_stop_at_the_on_error_handler_refuses_naming_the_gate(tmp_path: Path) -> None:
    """K fails → its on-error HANDLER is gated and the gate stops the run non-interactively.

    K is then a failed event with nothing successful after it — inside the frontier
    scan's selection — but it is recovery-tagged. The unrecovered-set check must route
    this to the gate refusal, never resume at K. This is the case that makes that check
    load-bearing alongside the frontier rule (a frontier-only 'simplification' regresses it)."""
    _write_trace(
        tmp_path,
        execution_id="gate-after-recovered",
        timestamp="20260101-000000",
        nodes=[_node("k", status="failed", output={})],
        warnings=[{"node_id": "k", "type": "on_error_recovery"}],
        failed_node_ids=[],
        gate_lines=[
            {"kind": "gate", "node_id": "handler", "phase": "pause", "gate_kind": "approval"},
        ],
    )
    with pytest.raises(ResumeGateStoppedError) as excinfo:
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert excinfo.value.node_id == "handler"


def test_crafted_failure_before_a_success_refuses_instead_of_crashing(tmp_path: Path) -> None:
    """Engine-unproducible shape (an unrecovered failure always stops the walk, so it is the
    last event): a failed event FOLLOWED by a success leaves no failure after the frontier.
    The loader must refuse with a typed error, never crash on min() of an empty selection."""
    _write_trace(
        tmp_path,
        execution_id="crafted-1",
        timestamp="20260101-000000",
        nodes=[_node("k", status="failed", output={}), _node("s", status="success")],
        failed_node_ids=["k"],
    )
    with pytest.raises(ResumeNotResumableError):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def test_undecided_escalation_in_seed_scope_refused(tmp_path: Path) -> None:
    _write_trace(
        tmp_path,
        execution_id="esc-1",
        timestamp="20260101-000000",
        nodes=[
            _node("review", output={"result": {"escalation": {"reason": "needs a human"}}}),
            _node("k", status="failed", output={}),
        ],
    )
    with pytest.raises(ResumeNotResumableError, match="escalation"):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def test_whitespace_only_escalation_string_refused(tmp_path: Path) -> None:
    """A whitespace-only escalation STRING pauses in production (engine.gate.detect_escalation only
    filters ``marker == ""``), so the loader must refuse to seed it — NOT .strip() it away."""
    _write_trace(
        tmp_path,
        execution_id="ws-esc",
        timestamp="20260101-000000",
        nodes=[
            _node("review", output={"result": {"escalation": "   "}}),
            _node("k", status="failed", output={}),
        ],
    )
    with pytest.raises(ResumeNotResumableError, match="escalation"):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def test_decided_escalation_in_seed_scope_is_fine(tmp_path: Path) -> None:
    """A marker already carrying ``decision`` passes the guard. This shape appears in a
    RESUMED attempt's trace (the re-record loop persists the folded, decided marker) —
    a live run's own trace freezes the undecided shape and relies on the fold below."""
    _write_trace(
        tmp_path,
        execution_id="esc-ok",
        timestamp="20260101-000000",
        nodes=[
            _node("review", output={"result": {"escalation": {"decision": {"chosen": "yes", "notes": ""}}}}),
            _node("k", status="failed", output={}),
        ],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "k"


def _escalation_resolution(node_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    """A ``kind:"gate"`` escalation-resolution line, shaped as ``record_gate`` writes it."""
    return {
        "kind": "gate",
        "node_id": node_id,
        "phase": "resolution",
        "gate_kind": "escalation",
        "resolution": "choice",
        "resolved_via": "prompt",
        "decision": decision,
    }


def test_resolved_escalation_dict_marker_is_folded_and_resumable(tmp_path: Path) -> None:
    """Escalation false-refusal fix (review 2026-07-04): the node's event freezes the marker
    UNDECIDED (recorded at engine step 16, before step 17.7 writes the decision into the
    LIVE store only), and the decision is persisted as a disk-only gate resolution line.
    The loader folds it back — a RESOLVED upstream escalation must never refuse the resume."""
    _write_trace(
        tmp_path,
        execution_id="esc-folded",
        timestamp="20260101-000000",
        nodes=[
            _node("review", output={"result": {"escalation": {"question": "merge?"}, "work": "partial"}}),
            _node("k", status="failed", output={}),
        ],
        gate_lines=[
            {"kind": "gate", "node_id": "review", "phase": "pause", "gate_kind": "escalation"},
            _escalation_resolution("review", {"chosen": "merge", "notes": None}),
        ],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "k"
    review = next(e for e in source.events if e["node_id"] == "review")
    assert review["node_output"]["result"]["escalation"] == {
        "question": "merge?",
        "decision": {"chosen": "merge", "notes": None},
    }
    # The rest of the frozen work product is untouched by the fold.
    assert review["node_output"]["result"]["work"] == "partial"


def test_resolved_escalation_string_marker_is_folded(tmp_path: Path) -> None:
    """A string marker folds to the same ``{question, decision}`` shape ``run_escalation_gate``
    writes into the live store."""
    _write_trace(
        tmp_path,
        execution_id="esc-str",
        timestamp="20260101-000000",
        nodes=[
            _node("review", output={"result": {"escalation": "which db?"}}),
            _node("k", status="failed", output={}),
        ],
        gate_lines=[_escalation_resolution("review", {"chosen": "postgres", "notes": None})],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "k"
    review = next(e for e in source.events if e["node_id"] == "review")
    assert review["node_output"]["result"]["escalation"] == {
        "question": "which db?",
        "decision": {"chosen": "postgres", "notes": None},
    }


def test_looping_escalation_last_resolution_wins(tmp_path: Path) -> None:
    """A looping node escalates once per iteration, each with its own resolution line. The
    fold pairs the node's FINAL event (what seeding restores) with the LAST resolution —
    an early-wins fold would seed iteration 1's decision as iteration 2's."""
    _write_trace(
        tmp_path,
        execution_id="esc-loop",
        timestamp="20260101-000000",
        nodes=[
            _node("review", output={"result": {"escalation": {"question": "round 1?"}}}),
            _node("review", output={"result": {"escalation": {"question": "round 2?"}}}),
            _node("k", status="failed", output={}),
        ],
        gate_lines=[
            _escalation_resolution("review", {"chosen": "first", "notes": None}),
            _escalation_resolution("review", {"chosen": "second", "notes": None}),
        ],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    final_review = [e for e in source.events if e["node_id"] == "review"][-1]
    assert final_review["node_output"]["result"]["escalation"]["decision"] == {
        "chosen": "second",
        "notes": None,
    }


def test_superseded_iteration_escalation_does_not_refuse(tmp_path: Path) -> None:
    """The guards scan the SEEDABLE set — final events only. An undecided marker frozen in an
    earlier loop iteration's event is never seeded (only the final event is), so it must not
    refuse the resume even with no resolution recorded for it."""
    _write_trace(
        tmp_path,
        execution_id="esc-superseded",
        timestamp="20260101-000000",
        nodes=[
            _node("review", output={"result": {"escalation": {"question": "iteration 1?"}}}),
            _node("review", output={"result": {"done": True}}),
            _node("k", status="failed", output={}),
        ],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "k"


def test_binary_placeholder_in_seed_scope_refused(tmp_path: Path) -> None:
    _write_trace(
        tmp_path,
        execution_id="bin-1",
        timestamp="20260101-000000",
        nodes=[
            _node("makebytes", output={"data": "<binary data: 42 bytes>"}),
            _node("k", status="failed", output={}),
        ],
    )
    with pytest.raises(ResumeFidelityError) as excinfo:
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert excinfo.value.node_id == "makebytes"


def test_lossy_marker_refuses_and_a_bare_placeholder_string_does_not_since_2_8_0(tmp_path: Path) -> None:
    """Task 179: a 2.8.0 trace marks every lossy event, so the guard reads the marker; a string
    that merely looks like a binary placeholder is the author's string there (the placeholder scan
    is the evidence only for traces that predate the marker — the test above)."""
    _write_trace(
        tmp_path / "plain",
        execution_id="looks-like-bytes",
        timestamp="20260101-000000",
        format_version="2.8.0",
        nodes=[_node("text", output={"data": "<binary data: 42 bytes>"}), _node("k", status="failed", output={})],
    )
    assert load_resume_source(workflow_path=WF, debug_dir=tmp_path / "plain").entry_node_id == "k"
    marked = {**_node("makebytes", output={"data": "<binary data: 42 bytes>"}), "lossy": ["data: bytes"]}
    _write_trace(
        tmp_path / "marked",
        execution_id="marked-bytes",
        timestamp="20260101-000000",
        format_version="2.8.0",
        nodes=[marked, _node("k", status="failed", output={})],
    )
    with pytest.raises(ResumeFidelityError) as excinfo:
        load_resume_source(workflow_path=WF, debug_dir=tmp_path / "marked")
    assert (excinfo.value.node_id, excinfo.value.lossy) == ("makebytes", ["data: bytes"])


def test_binary_placeholder_in_unseeded_failed_node_is_ignored(tmp_path: Path) -> None:
    """Seed fidelity alignment (review 2026-07-04): a FAILED-recovered node is never seeded,
    so a binary placeholder inside ITS output must not refuse the resume — the guard scope
    mirrors the seedable set, not the raw pre-K slice."""
    _write_trace(
        tmp_path,
        execution_id="bin-recovered",
        timestamp="20260101-000000",
        nodes=[
            _node("brokenbytes", status="failed", output={"data": "<binary data: 42 bytes>"}),
            _node("handler", status="success"),
            _node("k", status="failed", output={}),
        ],
        warnings=[{"node_id": "brokenbytes", "type": "on_error_recovery"}],
        failed_node_ids=["k"],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "k"


def test_binary_placeholder_downstream_of_entry_is_ignored(tmp_path: Path) -> None:
    """The fidelity guard scans only the SEED scope (before K) — a binary value at/after K is never seeded."""
    _write_trace(
        tmp_path,
        execution_id="bin-ds",
        timestamp="20260101-000000",
        nodes=[
            _node("upstream", output={"stdout": "fine"}),
            _node("k", status="failed", output={"data": "<binary data: 9 bytes>"}),
        ],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "k"


# ── Happy-path ResumeSource fields ────────────────────────────────────────────


def test_resume_source_fields_populated(tmp_path: Path) -> None:
    path = _write_trace(
        tmp_path,
        execution_id="happy-1",
        timestamp="20260101-000000",
        content_hash="hash-abc",
        inputs={"repo": "acme/widgets"},
        nodes=[_node("clone", output={"stdout": "cloned"}), _node("build", status="failed", output={})],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert isinstance(source, ResumeSource)
    assert source.path == path
    assert source.execution_id == "happy-1"
    assert source.entry_node_id == "build"
    assert source.last_completed_node_id is None
    assert source.content_hash == "hash-abc"
    assert source.inputs == {"repo": "acme/widgets"}
    assert [e["node_id"] for e in source.events] == ["clone", "build"]


def test_null_meta_inputs_survives(tmp_path: Path) -> None:
    """A pre-175 trace has meta.inputs == null; ResumeSource.inputs is None, not a crash."""
    _write_trace(tmp_path, execution_id="pre175", timestamp="20260101-000000", inputs=None)
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.inputs is None


def test_missing_content_hash_returned_as_none(tmp_path: Path) -> None:
    _write_trace(tmp_path, execution_id="nohash", timestamp="20260101-000000", content_hash=None)
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.content_hash is None


_IDENTITY = {
    "start": "clone",
    "steps": {
        "clone": {"hash": "a" * 32, "next": [["default", "build"]]},
        "build": {"hash": "b" * 32, "next": []},
    },
}


def test_step_identity_round_trips_from_the_meta_line(tmp_path: Path) -> None:
    path = _write_trace(
        tmp_path, execution_id="ident", timestamp="20260101-000000", format_version="2.9.0", step_identity=_IDENTITY
    )
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["step_identity"] == _IDENTITY
    assert load_resume_source(workflow_path=WF, debug_dir=tmp_path).step_identity == _IDENTITY


@pytest.mark.parametrize(
    "recorded",
    [None, "not-a-map", {"start": "clone"}, {"start": 3, "steps": {}}, {"start": "clone", "steps": ["clone"]}],
    ids=["absent", "string", "no-steps", "start-not-a-step-id", "steps-not-a-map"],
)
def test_absent_or_malformed_step_identity_loads_as_none(tmp_path: Path, recorded: Any) -> None:
    """A 2.8.0 trace has no map; a malformed one must not reach the preflight as half a check — both load
    as ``None``, which keeps the whole-workflow hash compare."""
    _write_trace(
        tmp_path, execution_id="old", timestamp="20260101-000000", format_version="2.8.0", step_identity=recorded
    )
    assert load_resume_source(workflow_path=WF, debug_dir=tmp_path).step_identity is None


@pytest.mark.parametrize(
    ("version", "predates"), [("2.7.0", True), ("2.8.0", False), ("2.9.0", False), ("2.10.0", False)]
)
def test_lossy_marker_era_reads_later_minors_correctly(version: str, predates: bool) -> None:
    from pflow.runtime.resume_source import _predates_lossy_marker

    assert _predates_lossy_marker({"format_version": version}) is predates


# ── Paused arm + answer fold (Task 171, Phase 2) ──────────────────────────────
# Real-collector keystones live beside the producers: approval in
# test_resume_engine.py (WorkflowRunner e2e), escalation in test_gate_pause.py
# (engine-level round-trip). These synthetic fixtures pin the loader's arms.

_APPROVAL_REQUEST: dict[str, Any] = {
    "node_id": "gated",
    "node_type": "ShellNode",
    "kind": "action_approval",
    "preview": {"command": "echo hi"},
    "question": None,
    "options": [],
    "recommendation": None,
}

_ESCALATION_REQUEST: dict[str, Any] = {
    "node_id": "esc",
    "node_type": "EscalatingNode",
    "kind": "decision_escalation",
    "preview": {},
    "question": "which db?",
    # The third, label-less option pins the shared `option_labels` fallback
    # ("option 3") — numbering must match what the pause output rendered.
    "options": [{"label": "keep"}, {"label": "drop", "description": "destructive"}, {}],
    "recommendation": "keep",
}


def _write_paused_approval(debug_dir: Path, *, execution_id: str = "paused-appr") -> Path:
    # The gated node has NO event (the gate fires before node.start).
    return _write_trace(
        debug_dir,
        execution_id=execution_id,
        timestamp="20260101-000000",
        final_status="paused",
        nodes=[_node("prep")],
        failed_node_ids=[],
        paused_node_id="gated",
        gate_request=_APPROVAL_REQUEST,
    )


def _write_paused_escalation(debug_dir: Path, *, execution_id: str = "paused-esc") -> Path:
    # The escalating node COMPLETED — its final event carries the UNDECIDED marker.
    marker = {"question": "which db?", "options": [{"label": "keep"}, {"label": "drop"}, {}]}
    return _write_trace(
        debug_dir,
        execution_id=execution_id,
        timestamp="20260101-000000",
        final_status="paused",
        nodes=[_node("prep"), _node("esc", output={"result": {"escalation": marker}})],
        failed_node_ids=[],
        paused_node_id="esc",
        gate_request=_ESCALATION_REQUEST,
    )


def test_paused_approval_entry_is_the_gated_node(tmp_path: Path) -> None:
    _write_paused_approval(tmp_path)
    source = load_resume_source(execution_id="paused-appr", debug_dir=tmp_path, gate_answer={"approve": True})
    assert source.entry_node_id == "gated"
    assert source.last_completed_node_id is None
    assert source.paused_node_id == "gated"
    assert source.gate_request == _APPROVAL_REQUEST


def test_paused_approval_deny_answer_loads_identically(tmp_path: Path) -> None:
    """The loader validates the answer's SHAPE, not its verdict — deny delivery is the
    resume run's resolver (Phase 3 primes it), so {"approve": False} loads the same."""
    _write_paused_approval(tmp_path)
    source = load_resume_source(execution_id="paused-appr", debug_dir=tmp_path, gate_answer={"approve": False})
    assert source.entry_node_id == "gated"


def test_paused_escalation_entry_is_between_nodes(tmp_path: Path) -> None:
    _write_paused_escalation(tmp_path)
    source = load_resume_source(
        execution_id="paused-esc", debug_dir=tmp_path, gate_answer={"chosen": "keep", "notes": None}
    )
    # Between-nodes shape: the escalating step completed; the CLI resolves its
    # single default successor post-compile, exactly like the incomplete arm.
    assert source.entry_node_id is None
    assert source.last_completed_node_id == "esc"
    assert source.paused_node_id == "esc"
    assert source.gate_request is not None
    assert source.gate_request["kind"] == "decision_escalation"


def test_paused_without_pause_record_refuses(tmp_path: Path) -> None:
    """A hand-edited/corrupt trace marked paused with no pause record: typed refusal."""
    _write_trace(
        tmp_path,
        execution_id="corrupt-pause",
        timestamp="20260101-000000",
        final_status="paused",
        nodes=[_node("prep")],
    )
    with pytest.raises(ResumeNotResumableError, match="no pause record"):
        load_resume_source(execution_id="corrupt-pause", debug_dir=tmp_path, gate_answer={"approve": True})


def test_paused_without_answer_refuses_with_gate_content_not_the_guard(tmp_path: Path) -> None:
    """Fold-order pin: an unanswered paused ESCALATION must raise ResumeAnswerRequiredError
    — whose message renders the pending question + numbered options + exact command — and
    NEVER fall through to `_guard_seed_scope`'s "unresolved escalation … Re-run" refusal
    (the escalating node's undecided marker IS in the seed scope; answer validation runs
    first by design)."""
    _write_paused_escalation(tmp_path)
    with pytest.raises(ResumeAnswerRequiredError) as exc:
        load_resume_source(execution_id="paused-esc", debug_dir=tmp_path)
    assert exc.value.mode == "missing_answer"
    message = str(exc.value)
    assert "which db?" in message
    assert "1. keep (rec)" in message
    assert "2. drop — destructive" in message
    assert "unresolved escalation" not in message
    assert any('--choose "<answer or option number>"' in s for s in exc.value.suggestions)
    assert any("paused-esc" in s for s in exc.value.suggestions)  # the REAL id, not a placeholder


def test_choose_on_approval_refuses_naming_the_right_flag(tmp_path: Path) -> None:
    _write_paused_approval(tmp_path)
    with pytest.raises(ResumeAnswerRequiredError) as exc:
        load_resume_source(execution_id="paused-appr", debug_dir=tmp_path, gate_answer={"chosen": "yes", "notes": None})
    assert exc.value.mode == "wrong_flag"
    assert "--approve yes|no" in str(exc.value)


def test_approve_on_escalation_refuses_naming_the_right_flag(tmp_path: Path) -> None:
    _write_paused_escalation(tmp_path)
    with pytest.raises(ResumeAnswerRequiredError) as exc:
        load_resume_source(execution_id="paused-esc", debug_dir=tmp_path, gate_answer={"approve": True})
    assert exc.value.mode == "wrong_flag"
    assert "--choose" in str(exc.value)


def test_answer_flag_on_non_paused_source_refuses(tmp_path: Path) -> None:
    """A resumable FAILED source rejects an answer flag — it answers nothing there."""
    _write_trace(tmp_path, execution_id="plain-fail", timestamp="20260101-000000")
    with pytest.raises(ResumeAnswerRequiredError) as exc:
        load_resume_source(execution_id="plain-fail", debug_dir=tmp_path, gate_answer={"approve": True})
    assert exc.value.mode == "not_paused"


@pytest.mark.parametrize(
    ("chosen", "expected"),
    [
        ("2", "drop"),  # digit → that option's label
        (" 1 ", "keep"),  # stripped first, like the blocking prompt
        ("3", "option 3"),  # label-less option → the shared fallback label
        ("4", "4"),  # out of range → free text
        ("postgres", "postgres"),  # free text passes through
        ("²", "²"),  # unicode-numeric: isdigit() True but int() rejects → free text, never a crash
    ],
)
def test_choose_answer_maps_numbers_to_labels(tmp_path: Path, chosen: str, expected: str) -> None:
    _write_paused_escalation(tmp_path)
    source = load_resume_source(
        execution_id="paused-esc", debug_dir=tmp_path, gate_answer={"chosen": chosen, "notes": None}
    )
    final = {e["node_id"]: e for e in source.events}
    decision = final["esc"]["node_output"]["result"]["escalation"]["decision"]
    assert decision == {"chosen": expected, "notes": None}


@pytest.mark.parametrize("chosen", ["", "   "])
def test_empty_choose_answer_is_treated_as_missing(tmp_path: Path, chosen: str) -> None:
    """An empty/whitespace --choose must not "decide" the escalation with nothing —
    the blocking prompt can't produce an empty answer (click re-prompts), so the
    durable path must not accept a shape the interactive path forbids."""
    _write_paused_escalation(tmp_path)
    with pytest.raises(ResumeAnswerRequiredError) as exc:
        load_resume_source(execution_id="paused-esc", debug_dir=tmp_path, gate_answer={"chosen": chosen, "notes": None})
    assert exc.value.mode == "missing_answer"


def test_choose_fold_decides_the_marker_and_passes_the_guard(tmp_path: Path) -> None:
    """The answered marker rides `source.events` DECIDED — seeding restores it and the
    engine's re-record loop writes it into the attempt trace (self-containment). The
    guard passing at all proves the fold ran before it."""
    _write_paused_escalation(tmp_path)
    source = load_resume_source(
        execution_id="paused-esc", debug_dir=tmp_path, gate_answer={"chosen": "drop", "notes": None}
    )
    marker = source.events[-1]["node_output"]["result"]["escalation"]
    assert marker["decision"] == {"chosen": "drop", "notes": None}
    assert marker["question"] == "which db?"  # the original marker survives around the fold


def test_superseded_paused_token_refuses_even_with_an_answer(tmp_path: Path) -> None:
    """Chain policy precedes answer validation: a consumed paused token refuses
    SUPERSEDED (naming the newer attempt), never re-answers."""
    _write_paused_escalation(tmp_path)
    _write_trace(
        tmp_path,
        execution_id="attempt-2",
        timestamp="20260102-000000",
        resumed_from="paused-esc",
        nodes=[_node("prep"), _node("after")],  # a non-restored event = the attempt consumed the chain
    )
    with pytest.raises(ResumeSupersededError):
        load_resume_source(execution_id="paused-esc", debug_dir=tmp_path, gate_answer={"chosen": "keep", "notes": None})


# ── Corruption tolerance ──────────────────────────────────────────────────────


def test_by_execution_id_skips_corrupt_matched_trace(tmp_path: Path) -> None:
    """A matched-but-corrupt trace degrades to a clean 'missing' refusal, never a raw traceback.

    Mirrors the workflow_path arm's skip-corrupt posture (via _iter_workflow_traces).
    """
    path = _write_trace(tmp_path, execution_id="corrupt-1", timestamp="20260101-000000")
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(1, "{ this is not valid json")  # corrupt an EARLY line (not the tolerated final one)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ResumeSourceMissingError):
        load_resume_source(execution_id="corrupt-1", debug_dir=tmp_path)


def test_iter_raw_trace_lines_tolerates_truncated_final_line(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        '{"kind": "meta"}\n{"kind": "gate", "node_id": "g"}\n{"kind": "even', encoding="utf-8"
    )  # truncated tail
    lines = list(_iter_raw_trace_lines(path))
    assert [line.get("kind") for line in lines] == ["meta", "gate"]  # tail dropped, no raise


def test_iter_raw_trace_lines_raises_on_earlier_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text('{"kind": "meta"}\n{ broken\n{"kind": "run.complete"}\n', encoding="utf-8")  # malformed MIDDLE line
    with pytest.raises(json.JSONDecodeError):
        list(_iter_raw_trace_lines(path))


# ── Exception smoke tests (built in Phase 1, consumed by the Phase-3 CLI) ──────


def test_side_effect_confirmation_error_is_agent_first() -> None:
    err = ResumeSideEffectConfirmationError("deploy", "shell", execution_id="e1", trace_path="/t.json")
    diag = err.to_diagnostics()[0]
    assert diag.node_id == "deploy"
    assert "shell" in diag.message and "side effects may fire again" in diag.message
    assert any("--force" in s for s in (diag.suggestions or []))
    assert diag.context.get("execution_id") == "e1"


def _stale(
    *,
    entry_node_id: str | None = "save",
    entry_iteration: int | None = None,
    after_node_id: str | None = None,
    rerun_node_type: str | None = None,
    **changes: Any,
) -> ResumeStaleWorkflowError:
    """The error for the given ``StepIdentityChanges`` fields (none = the no-identity fallback)."""
    return ResumeStaleWorkflowError(
        hash_known=True,
        entry_node_id=entry_node_id,
        entry_iteration=entry_iteration,
        after_node_id=after_node_id,
        rerun_node_type=rerun_node_type,
        changes=StepIdentityChanges(**changes) if changes else None,
    )


def _to(*targets: str) -> list[tuple[str, str]]:
    return [("default", target) for target in targets]


def test_stale_workflow_error_names_the_edited_step_and_what_force_accepts() -> None:
    """The ruled text (show-before-code, row 3): the lead names the edited step; the body says what
    resume re-runs; re-running is the first remedy and --force the second, saying what it keeps —
    with no "(… is skipped)" claim when nothing was inserted."""
    err = _stale(edited=["produce"])
    assert str(err) == (
        "'produce' was edited. Resume re-runs nothing before 'save' — it restores the saved outputs of the "
        "steps that ran — so that edit would not take effect."
    )
    assert err.suggestions == [
        "Re-run the workflow from the start so the edit takes effect.",
        "Pass --force to resume anyway: steps before 'save' keep their saved outputs and are not re-run.",
    ]


def test_stale_workflow_error_names_each_skipped_step_in_the_force_line() -> None:
    err = _stale(rerouted={"shape": (_to("prepare"), _to("save"))}, skipped=frozenset({"prepare"}))
    assert err.suggestions[1] == (
        "Pass --force to resume anyway: steps before 'save' keep their saved outputs and are not re-run "
        "('prepare' is skipped)."
    )
    two = _stale(
        new_start=("banner", "produce"),
        rerouted={"shape": (_to("prep"), _to("save"))},
        skipped=frozenset({"banner", "prep"}),
    )
    assert "('prep', 'banner' are skipped)." in two.suggestions[1]


def test_stale_workflow_error_leads_come_in_the_ruled_order() -> None:
    err = _stale(
        new_start=("banner", "produce"),
        rerouted={"shape": (_to("prepare"), _to("save"))},
        approved_edited="save",
        edited=["shape"],
        removed=["old"],
        skipped=frozenset({"banner", "prepare"}),
    )
    assert str(err).startswith(
        "'old' is no longer in the workflow (resume would still restore its saved output). 'shape' was edited. "
        "'save' was edited after it was approved — the approval covered the earlier version. 'shape' now "
        "continues to 'prepare', which never ran — resume would skip it. The workflow now starts at 'banner', "
        "which never ran — resume would skip it. Resume re-runs nothing before 'save'"
    )
    assert "so those edits would not take effect." in str(err)


def test_stale_workflow_error_reroute_says_never_ran_only_for_a_skipped_step() -> None:
    skipped = _stale(rerouted={"shape": (_to("prepare"), _to("save"))}, skipped=frozenset({"prepare"}))
    instead = _stale(rerouted={"produce": (_to("save"), _to("shape"))})
    ends = _stale(rerouted={"produce": ([], _to("shape"))})
    assert str(skipped).startswith("'shape' now continues to 'prepare', which never ran — resume would skip it.")
    assert str(instead).startswith("'produce' now continues to 'save' instead of 'shape'.")
    assert str(ends).startswith("'produce' now ends the workflow instead of continuing to 'shape'.")
    restart = _stale(new_start=("shape", "produce"))
    assert str(restart).startswith("The workflow now starts at 'shape' instead of 'produce'.")


def test_stale_workflow_error_reroute_names_the_routes_action() -> None:
    """An added error route to the same target must not read "continues to 'shape' instead of 'shape'"."""
    err = _stale(rerouted={"produce": ([("default", "shape"), ("error", "shape")], _to("shape"))})
    assert str(err).startswith("'produce' now continues to 'shape', 'shape' on error instead of 'shape'.")
    # The skipped form names the action too: a router's named route is not its main flow.
    named = _stale(rerouted={"route": ([("x", "b")], _to("a"))}, skipped=frozenset({"b"}))
    assert str(named).startswith("'route' now continues to 'b' on 'x', which never ran — resume would skip it.")


def test_stale_workflow_error_for_a_missing_resume_point_offers_no_force() -> None:
    """--force cannot resume at a step that is gone (the engine refuses K-removed) — never offer it."""
    err = _stale(resume_point_missing=True)
    assert str(err) == "The resume point 'save' is no longer in the workflow."
    assert err.suggestions == ["Re-run the workflow from the start.", "Or restore the step 'save' and resume again."]
    assert err.node_id == "save"


def test_stale_workflow_error_between_nodes_and_loop_scopes() -> None:
    between = _stale(entry_node_id=None, after_node_id="esc", edited=["esc"])
    assert "Resume re-runs nothing up to and including 'esc' — it restores" in str(between)
    assert between.suggestions[1].startswith("Pass --force to resume anyway: steps up to and including 'esc' keep")
    loop = _stale(entry_node_id="count", entry_iteration=3, edited=["prep"])
    assert "Resume re-runs nothing before 'count' (iteration 3) — it restores" in str(loop)
    assert "Its iterations before 3 are restored too, so an edit to 'count' applies from iteration 3 on." in str(loop)
    first = _stale(entry_node_id="count", entry_iteration=1, edited=["prep"])
    assert "iteration" not in str(first)


def test_stale_workflow_error_between_nodes_new_route_says_resume_would_run_it() -> None:
    """A plain between-nodes source continues at its last step's CURRENT route — the new step runs, so
    neither "would skip it" nor "would not take effect" may appear."""
    err = _stale(entry_node_id=None, after_node_id="esc", rerouted={"esc": (_to("check"), _to("after"))})
    assert str(err) == (
        "'esc' now continues to 'check' instead of 'after'. Resume would continue at 'check' with the saved "
        "outputs up to and including 'esc'."
    )
    assert err.suggestions[0] == "Re-run the workflow from the start."
    assert "skipped" not in err.suggestions[1]


def test_stale_workflow_error_for_an_approval_says_the_edited_step_would_run() -> None:
    """The approval step is the resume point: --force RUNS its edited version — never "would not take effect"."""
    err = _stale(entry_node_id="deploy", approved_edited="deploy")
    assert str(err) == (
        "'deploy' was edited after it was approved — the approval covered the earlier version. Resuming would "
        "run the edited 'deploy' under that earlier approval."
    )
    assert err.suggestions == [
        "Re-run the workflow from the start so 'deploy' asks for approval again.",
        "Pass --force to resume anyway: steps before 'deploy' keep their saved outputs and are not re-run, and "
        "the edited 'deploy' runs under the earlier approval.",
    ]


def test_stale_workflow_error_says_force_also_refires_a_started_side_effecting_entry() -> None:
    """--force waives the side-effect confirmation too — the stale refusal is the only place the
    agent learns that, so it must say so when the entry already started."""
    err = _stale(entry_node_id="append", edited=["a"], rerun_node_type="shell")
    assert err.suggestions[1].endswith(
        "--force also re-runs 'append' (a shell step that already started in the original run), so its side "
        "effects may fire again — if you are an AI agent, confirm that with your human first."
    )
    assert "fire again" not in " ".join(_stale(edited=["a"]).suggestions)


def test_stale_workflow_error_fallback_texts_never_name_a_change() -> None:
    """No per-step identity on the trace: an older pflow (hash known) vs. pre-hash tracking (unknown)."""
    older = _stale()
    unverifiable = ResumeStaleWorkflowError(hash_known=False, entry_node_id="save")
    assert str(older).startswith(
        "This run was recorded by an older pflow version that did not record each step's definition, so resume "
        "cannot tell which step changed. Resume re-runs nothing before 'save'"
    )
    assert str(older).endswith("so an edit to them would not take effect.")
    assert older.suggestions[0] == "Re-run the workflow from the start so the edit takes effect."
    assert str(unverifiable).startswith("Cannot verify the workflow is unchanged — this run predates")
    assert str(unverifiable).endswith("so an edit to them, if any, would not take effect.")
    assert unverifiable.suggestions[0] == "Re-run the workflow from the start."  # no definite "edit"
    for err in (older, unverifiable):
        assert err.suggestions[1].endswith("(a step inserted among them is skipped).")
        assert err.to_diagnostics()[0].context["changed_steps"] is None  # unknown, never "nothing changed"


def test_stale_workflow_error_carries_structured_fields_for_agents() -> None:
    err = _stale(edited=["produce"], new_start=("banner", "produce"), skipped=frozenset({"banner"}))
    context = err.to_diagnostics()[0].context
    assert context is not None
    assert (context["changed_steps"], context["new_start"], context["resume_point"]) == (["produce"], "banner", "save")
    assert context["resume_point_missing"] is False
    assert context["category"] == "execution_failure"
    assert err.to_diagnostics()[0].node_id == "produce"
    two = _stale(edited=["a"], rerouted={"b": (_to("c"), _to("d"))}).to_diagnostics()[0]
    assert (two.context or {})["changed_steps"] == ["a", "b"] and two.node_id is None
    start_only = _stale(new_start=("banner", "produce"), skipped=frozenset({"banner"})).to_diagnostics()[0]
    assert (start_only.context or {})["changed_steps"] == []  # known: no step changed, only the start


# ── entry_never_started / restored_node_ids (#690) ─────────────────────────────
# `node.start` is a disk-only line, so these write the raw JSONL a streamed run produces: a leaf's
# `node.start` and its terminal `event` share one `id`; a failure raised before `begin_node`
# (template resolution, loop carry) has an `event` and no `node.start`.


def _start(node_id: str, line_id: int, parent_id: int | None = None) -> dict[str, Any]:
    return {"kind": "node.start", "node_id": node_id, "id": line_id, "parent_id": parent_id, "status": "running"}


def _event(node_id: str, line_id: int, status: str, parent_id: int | None = None, **extra: Any) -> dict[str, Any]:
    return {"kind": "event", "node_id": node_id, "id": line_id, "parent_id": parent_id, "status": status, **extra}


def _raw_source(
    tmp_path: Path,
    lines: list[dict[str, Any]],
    entry: str | None = "save",
    *,
    entry_iteration: int | None = 1,
    content_hash: str | None = "h",
) -> ResumeSource:
    path = tmp_path / "trace.json"
    meta = {"kind": "meta", "pflow_trace": "jsonl/1", "format_version": "2.8.0", "execution_id": "e1"}
    path.write_text("\n".join(json.dumps(line) for line in [meta, *lines]) + "\n", encoding="utf-8")
    return ResumeSource(
        path=path,
        workflow_path="/x/wf.pflow.md",
        execution_id="e1",
        entry_node_id=entry,
        last_completed_node_id=None,
        events=[],
        inputs=None,
        content_hash=content_hash,
        entry_iteration=entry_iteration,
    )


def test_entry_failed_before_its_start_marker_never_started(tmp_path: Path) -> None:
    lines = [_start("produce", 0), _event("produce", 0, "success"), _event("save", 1, "failed")]
    assert entry_never_started(_raw_source(tmp_path, lines)) is True


def test_entry_with_a_paired_start_marker_started(tmp_path: Path) -> None:
    lines = [_start("produce", 0), _event("produce", 0, "success"), _start("save", 1), _event("save", 1, "failed")]
    assert entry_never_started(_raw_source(tmp_path, lines)) is False


def test_a_later_dangling_start_defeats_an_earlier_pre_exec_failure(tmp_path: Path) -> None:
    """K failed before starting, an on-error back edge re-entered it, and it was killed mid-step:
    the interrupted attempt (the loader's entry) began, whatever the earlier event says."""
    lines = [_event("save", 1, "failed"), _start("fix", 2), _event("fix", 2, "success"), _start("save", 3)]
    assert entry_never_started(_raw_source(tmp_path, lines)) is False


def test_a_loop_entry_is_judged_from_the_iteration_resume_re_runs(tmp_path: Path) -> None:
    """Iteration 1 started (and fired); iteration 2 failed resolving its carry. Resume re-runs
    iteration 2 only, which never began. With no recorded position (a pre-2.8.0 trace: no
    `iteration` keys, entry_iteration None) resume restarts at iteration 1, which DID begin."""
    lines = [
        _start("count", 0),
        _event("count", 0, "success", iteration=1),
        _event("count", 1, "failed", iteration=2),
    ]
    assert entry_never_started(_raw_source(tmp_path, lines, entry="count", entry_iteration=2)) is True
    keyless = [_start("count", 0), _event("count", 0, "success"), _event("count", 1, "failed")]
    assert entry_never_started(_raw_source(tmp_path, keyless, entry="count", entry_iteration=None)) is False


def test_an_earlier_visit_that_began_is_re_run_too(tmp_path: Path) -> None:
    """Falsifier C1: an on-error back edge re-entered K — visit 1 started (and fired), visit 2
    failed before starting. A non-loop resume re-runs from K's FIRST event, so K began."""
    lines = [
        _start("save", 1),
        _event("save", 1, "failed"),
        _start("router", 2),
        _event("router", 2, "success"),
        _event("save", 3, "failed"),
    ]
    assert entry_never_started(_raw_source(tmp_path, lines)) is False


def test_a_restored_visit_of_the_entry_is_no_proof(tmp_path: Path) -> None:
    """Re-falsification: in a resumed attempt the entry's restored re-record (it ran and fired in
    the earlier attempt) has no node.start either. A back edge then fails the entry again before
    starting; the next resume re-runs from the restored visit, so the entry began."""
    lines = [
        _event("x", 0, "cached", restored=True),
        _event("k", 1, "cached", restored=True),
        _start("m", 2),
        _event("m", 2, "failed"),
        _start("x", 3),
        _event("x", 3, "success"),
        _event("k", 4, "failed"),
    ]
    assert entry_never_started(_raw_source(tmp_path, lines, entry="k")) is False


def test_a_trace_predating_node_start_proves_nothing(tmp_path: Path) -> None:
    """`node.start` and the meta `content_hash` arrived together (Task 173): no hash, no markers."""
    assert entry_never_started(_raw_source(tmp_path, [_event("save", 1, "failed")], content_hash=None)) is False


def test_a_child_start_with_the_same_id_never_pairs_with_a_top_level_event(tmp_path: Path) -> None:
    lines = [_start("inner", 1, parent_id=0), _event("save", 1, "failed")]
    assert entry_never_started(_raw_source(tmp_path, lines)) is True


@pytest.mark.parametrize(
    "lines, entry",
    [
        ([_event("save", 1, "failed")], None),  # between-nodes source: no entry to prove anything about
        ([_start("produce", 0), _event("produce", 0, "success")], "save"),  # entry never recorded
        ([{"kind": "event", "node_id": "save", "parent_id": None, "status": "failed"}], "save"),  # no id
        ([_event("save", 1, "cached")], "save"),  # a cache hit stands for an earlier execution
    ],
)
def test_anything_short_of_proof_reads_as_started(
    tmp_path: Path, lines: list[dict[str, Any]], entry: str | None
) -> None:
    assert entry_never_started(_raw_source(tmp_path, lines, entry=entry)) is False


def test_unreadable_trace_reads_as_started(tmp_path: Path) -> None:
    source = _raw_source(tmp_path, [_event("save", 1, "failed")])
    source.path.unlink()
    assert entry_never_started(source) is False


def test_restored_node_ids_is_the_seed_set_minus_the_entry() -> None:
    """Same derivation the loader guards and the engine seeds: completed steps before the entry,
    a failed (recovered) step excluded, and a loop entry's own earlier iteration not listed."""
    events = [
        {"node_id": "fetch", "status": "success"},
        {"node_id": "flaky", "status": "failed"},
        {"node_id": "count", "status": "success", "iteration": 1},
        {"node_id": "count", "status": "failed", "iteration": 2},
        {"node_id": "later", "status": "success"},
    ]
    source = ResumeSource(
        path=Path("t.json"),
        workflow_path=None,
        execution_id="e1",
        entry_node_id="count",
        last_completed_node_id=None,
        events=events,
        inputs=None,
        content_hash=None,
        entry_iteration=2,
    )
    assert restored_node_ids(source) == ["fetch"]


# ── Keystone: a REAL failed run, not a synthetic fixture ──────────────────────


@pytest.mark.trace_files
def test_real_failed_run_is_resumable_end_to_end(tmp_path: Path) -> None:
    """A REAL failing ``WorkflowRunner`` run → ``load_resume_source`` (pitfall #19 + #20).

    Every other test in this file hand-builds its trace, so all of them would stay
    GREEN if the loader read a field a real run never writes. This one runs a real
    2-step workflow to failure, saves the trace the production collector produces,
    and loads it — validating against reality: the failed-event ``status`` key
    (entry detection), the real ``node_output`` shape (seeding), the real
    ``content_hash`` on the meta line (the synthetic tests use literal strings),
    ``meta.inputs``, execution order, and trace-file discovery from a real filename.
    """
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner
    from tests.shared.markdown_utils import write_workflow_file

    ir = {
        "nodes": [
            {"id": "prep", "type": "shell", "params": {"command": "printf ready"}},
            {"id": "boom", "type": "shell", "params": {"command": "exit 1"}},
        ],
        "edges": [{"from": "prep", "to": "boom"}],
    }
    wf = tmp_path / "wf.pflow.md"
    write_workflow_file(ir, wf)

    result = WorkflowRunner().run(str(wf), {}, RunnerConfig())
    assert not result.success, "the workflow was supposed to fail at 'boom'"
    assert result.trace is not None
    saved = result.trace.save_to_file()
    assert saved is not None

    source = load_resume_source(execution_id=result.trace.execution_id, debug_dir=saved.parent)

    # Entry: real failed-event status detection (proves the on-disk key is `status`,
    # not `success: bool` — a wrong assumption would find zero failed nodes and refuse).
    assert source.entry_node_id == "boom"
    # Seeding: the upstream event carries its REAL shell output shape.
    assert [e["node_id"] for e in source.events] == ["prep", "boom"]
    prep_event = next(e for e in source.events if e["node_id"] == "prep")
    assert prep_event["node_output"]["stdout"] == "ready"
    # Replay fingerprint: a REAL content hash rides the meta line (not a test literal),
    # and this trace predates nothing — inputs are an (empty) dict, never a crash.
    assert source.content_hash
    assert source.inputs in ({}, None)
    # Task 180: the per-step identity the preflight checks is the resolved IR's, recorded at run start.
    from pflow.core.workflow_id import step_identity
    from pflow.execution.workflow_resolver import resolve_workflow

    assert source.step_identity == step_identity(resolve_workflow(str(wf)).ir)
    assert list(source.step_identity["steps"]) == ["prep", "boom"]


# --- Task 179: the resume entry is a (step, iteration) pair ----------------------


def _k_iterations(*iterations: int, failed_last: bool = False) -> list[dict[str, Any]]:
    events = [_node("k", iteration=n, output={"result": {"n": n}}) for n in iterations]
    if failed_last:
        events[-1] = _node("k", status="failed", output={}, iteration=iterations[-1])
    return events


def test_killed_mid_iteration_continues_at_that_iteration(tmp_path: Path) -> None:
    """A dangling top-level node.start for K after iterations 1..2 = killed mid-iteration 3."""
    _write_incomplete_trace(
        tmp_path,
        execution_id="killed-mid-loop",
        timestamp="20260101-000000",
        completed=[_node("prep"), *_k_iterations(1, 2)],
        killed_node="k",
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert (source.entry_node_id, source.entry_iteration) == ("k", 3)


def test_failed_iteration_reruns_at_that_iteration_and_seeds_the_previous_one(tmp_path: Path) -> None:
    _write_trace(
        tmp_path,
        execution_id="failed-at-3",
        timestamp="20260101-000000",
        nodes=[_node("prep"), *_k_iterations(1, 2, 3, failed_last=True)],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert (source.entry_node_id, source.entry_iteration) == ("k", 3)
    shared: dict[str, Any] = {}
    seeded = seed_snapshot_into_shared(shared, source.events, exclude="k", exclude_iteration=3)
    assert list(seeded) == ["prep", "k"]
    assert shared["k"] == {"result": {"n": 2}}  # the iteration before the one about to run


def test_step_without_recorded_position_has_no_entry_iteration(tmp_path: Path) -> None:
    """Keyless final event → ``None`` ("no recorded position"): a non-loop step, or a loop
    step from a trace that predates 2.8.0 — the engine tells them apart by the step's config
    (a loop step then restarts at 1 with an advisory)."""
    _write_trace(
        tmp_path,
        execution_id="keyless",
        timestamp="20260101-000000",
        nodes=[_node("prep"), _node("k", status="failed", output={})],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert (source.entry_node_id, source.entry_iteration) == ("k", None)


def test_step_that_never_ran_starts_at_iteration_one(tmp_path: Path) -> None:
    """An approval paused at a step's first iteration: no event for it → exactly 1, never None."""
    _write_paused_approval(tmp_path)
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path, gate_answer={"approve": True})
    assert (source.entry_node_id, source.entry_iteration) == ("gated", 1)


def test_seed_guard_scans_the_entry_previous_iteration(tmp_path: Path) -> None:
    """Q2: what resume would restore from K's own iteration 2 is guarded like any upstream —
    a lossy binary placeholder refuses rather than seeding silently."""
    _write_trace(
        tmp_path,
        execution_id="lossy-k",
        timestamp="20260101-000000",
        nodes=[
            _node("prep"),
            _node("k", iteration=1, output={"data": "ok"}),
            _node("k", iteration=2, output={"data": "<binary data: 9 bytes>"}),
            _node("k", status="failed", output={}, iteration=3),
        ],
    )
    with pytest.raises(ResumeFidelityError) as exc_info:
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert exc_info.value.node_id == "k"


def _iteration_escalation(n: int, *, decision: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Gate lines for an escalation raised at iteration ``n`` (pause, plus resolution when answered)."""
    lines: list[dict[str, Any]] = [
        {"kind": "gate", "node_id": "k", "phase": "pause", "gate_kind": "escalation", "iteration": n}
    ]
    if decision is not None:
        lines.append({**_escalation_resolution("k", decision), "iteration": n})
    return lines


def test_earlier_iteration_answer_never_decides_a_later_unanswered_escalation(tmp_path: Path) -> None:
    """D2b (2): K escalated at iteration 1 (answered A) and again at 2 with a NEW question;
    the run was killed at the prompt. Folding A onto iteration 2's marker would continue with
    an answer to a different question — the fold pairs by iteration, so the resume refuses."""
    _write_incomplete_trace(
        tmp_path,
        execution_id="killed-at-prompt",
        timestamp="20260101-000000",
        completed=[
            _node("k", iteration=1, output={"result": {"escalation": {"question": "q1?"}}}),
            _node("k", iteration=2, output={"result": {"escalation": {"question": "q2?"}}}),
        ],
        gate_lines=[*_iteration_escalation(1, decision={"chosen": "A", "notes": None}), *_iteration_escalation(2)],
    )
    with pytest.raises(ResumeNotResumableError, match="unresolved escalation") as exc_info:
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert exc_info.value.node_id == "k"


def test_answer_folds_onto_the_iteration_that_raised_it(tmp_path: Path) -> None:
    """D2b (1), loader half: iteration 1's answer decides iteration 1's marker — the one the
    seed restores when iteration 2 failed — so a decided escalation never false-refuses."""
    _write_trace(
        tmp_path,
        execution_id="answered-then-failed",
        timestamp="20260101-000000",
        nodes=[
            _node("k", iteration=1, output={"result": {"escalation": {"question": "q1?"}}}),
            _node("k", status="failed", output={}, iteration=2),
        ],
        gate_lines=_iteration_escalation(1, decision={"chosen": "A", "notes": None}),
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert (source.entry_node_id, source.entry_iteration) == ("k", 2)
    first = next(e for e in source.events if e["node_id"] == "k" and e.get("iteration") == 1)
    assert first["node_output"]["result"]["escalation"]["decision"] == {"chosen": "A", "notes": None}


def test_unrecovered_failure_reruns_its_iteration_even_with_a_failed_handler_after(tmp_path: Path) -> None:
    """K fails at 3 and its on-error handler F fails too: the terminal failure root is K and
    nothing recovered it, so iteration 3 re-runs (a later FAILED event is not a recovery)."""
    _write_trace(
        tmp_path,
        execution_id="both-fail",
        timestamp="20260101-000000",
        nodes=[*_k_iterations(1, 2, 3, failed_last=True), _node("f", status="failed", output={})],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert (source.entry_node_id, source.entry_iteration) == ("k", 3)


def test_kill_after_a_recovered_failure_continues_past_the_failed_iteration(tmp_path: Path) -> None:
    """K failed at 3, its on-error handler H recovered and routed back, and the run was killed
    mid-iteration 4 (dangling K start): the walk was past iteration 3, so the entry is K at 4."""
    _write_incomplete_trace(
        tmp_path,
        execution_id="killed-after-recovery",
        timestamp="20260101-000000",
        completed=[*_k_iterations(1, 2, 3, failed_last=True), _node("h")],
        killed_node="k",
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert (source.entry_node_id, source.entry_iteration) == ("k", 4)
