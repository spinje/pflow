"""``load_resume_source`` — the resume loader's failed-trace arms (Task 164, Phase 1).

Covers selection (newest-for-workflow, by-execution-id), the refusal ladder
(inline source, liveness, superseded, success/denied/gate-stopped/incomplete
status arms, undecided-escalation + lossy-binary seed-scope guards), the
event-order entry rule for multi-failure traces, and the happy-path
``ResumeSource`` fields. The ``incomplete`` arm is a Phase-1 stub (refuses);
Phase 5 replaces it.

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
    ResumeFidelityError,
    ResumeGateStoppedError,
    ResumeNothingToResumeError,
    ResumeNotResumableError,
    ResumeSideEffectConfirmationError,
    ResumeSourceMissingError,
    ResumeStaleWorkflowError,
    ResumeStillRunningError,
    ResumeSupersededError,
)
from pflow.runtime.workflow_trace import (
    ResumeSource,
    _iter_raw_trace_lines,
    format_trace_filename,
    load_resume_source,
)
from tests.shared.trace_jsonl import flatten_trace_to_lines, write_trace_jsonl

WF = "/work/project/wf.pflow.md"


def _node(node_id: str, *, status: str = "success", output: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type": "ShellNode",
        "status": status,
        "node_output": output if output is not None else {"stdout": f"{node_id}-out"},
    }


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
) -> Path:
    """Write a synthetic resume-source trace the loader can discover, returning its path."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "format_version": "2.5.0",
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
    path = debug_dir / format_trace_filename(workflow_path, name, timestamp)
    if gate_lines:
        lines = flatten_trace_to_lines(data)
        rc_idx = next(i for i, line in enumerate(lines) if line.get("kind") == "run.complete")
        lines = lines[:rc_idx] + gate_lines + lines[rc_idx:]
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
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


@pytest.mark.parametrize("status", ["success", "degraded"])
def test_succeeded_run_has_nothing_to_resume(tmp_path: Path, status: str) -> None:
    _write_trace(tmp_path, execution_id="ok", timestamp="20260101-000000", final_status=status)
    with pytest.raises(ResumeNothingToResumeError):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def test_denied_run_refused(tmp_path: Path) -> None:
    _write_trace(tmp_path, execution_id="denied-1", timestamp="20260101-000000", final_status="denied")
    with pytest.raises(ResumeNotResumableError):
        load_resume_source(workflow_path=WF, debug_dir=tmp_path)


def test_incomplete_run_refused_stub(tmp_path: Path) -> None:
    """Phase-1 stub: the incomplete arm refuses; Phase 5 replaces it with the killed-node derivation."""
    _write_trace(
        tmp_path,
        execution_id="crash-1",
        timestamp="20260101-000000",
        final_status="incomplete",
        nodes=[_node("a")],
    )
    with pytest.raises(ResumeNotResumableError, match=r"[Ii]nterrupted"):
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


def test_multi_failure_enters_earliest_in_event_order(tmp_path: Path) -> None:
    """K fails, its on-error F also fails: resume enters at K (event order), not alphabetical first.

    'zeta' fails first (index 0), 'alpha' fails second (index 1). The disk
    ``failed_node_ids`` is sorted alphabetically → 'alpha' first, which is WRONG:
    resuming at F when K now succeeds would never run F. Entry must be 'zeta'.
    """
    _write_trace(
        tmp_path,
        execution_id="multi-1",
        timestamp="20260101-000000",
        nodes=[_node("zeta", status="failed", output={}), _node("alpha", status="failed", output={})],
        failed_node_ids=["alpha", "zeta"],  # alphabetical, as save_to_file writes it
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "zeta"


def test_recovered_failure_is_not_an_entry(tmp_path: Path) -> None:
    """A failed node with an on_error_recovery warning is recovered — the later real failure is the entry."""
    _write_trace(
        tmp_path,
        execution_id="rec-1",
        timestamp="20260101-000000",
        nodes=[_node("recovered", status="failed", output={}), _node("real", status="failed", output={})],
        warnings=[{"node_id": "recovered", "type": "on_error_recovery"}],
    )
    source = load_resume_source(workflow_path=WF, debug_dir=tmp_path)
    assert source.entry_node_id == "real"


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
    assert source.final_status == "failed"
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


# ── Corruption tolerance ──────────────────────────────────────────────────────


def test_by_execution_id_skips_corrupt_matched_trace(tmp_path: Path) -> None:
    """A matched-but-corrupt trace degrades to a clean 'missing' refusal, never a raw traceback.

    Mirrors the workflow_path arm's skip-corrupt posture (via _iter_workflow_traces).
    """
    path = _write_trace(tmp_path, execution_id="corrupt-1", timestamp="20260101-000000")
    lines = path.read_text().splitlines()
    lines.insert(1, "{ this is not valid json")  # corrupt an EARLY line (not the tolerated final one)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ResumeSourceMissingError):
        load_resume_source(execution_id="corrupt-1", debug_dir=tmp_path)


def test_iter_raw_trace_lines_tolerates_truncated_final_line(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text('{"kind": "meta"}\n{"kind": "gate", "node_id": "g"}\n{"kind": "even')  # truncated tail
    lines = list(_iter_raw_trace_lines(path))
    assert [line.get("kind") for line in lines] == ["meta", "gate"]  # tail dropped, no raise


def test_iter_raw_trace_lines_raises_on_earlier_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text('{"kind": "meta"}\n{ broken\n{"kind": "run.complete"}\n')  # malformed MIDDLE line
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


def test_stale_workflow_error_has_two_messages() -> None:
    edited = ResumeStaleWorkflowError(hash_known=True)
    unverifiable = ResumeStaleWorkflowError(hash_known=False)
    assert "edited" in str(edited)
    assert "predates" in str(unverifiable) and "edited" not in str(unverifiable)
    for err in (edited, unverifiable):
        assert any("--force" in s for s in err.suggestions)


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
    assert source.final_status == "failed"
    assert source.entry_node_id == "boom"
    # Seeding: the upstream event carries its REAL shell output shape.
    assert [e["node_id"] for e in source.events] == ["prep", "boom"]
    prep_event = next(e for e in source.events if e["node_id"] == "prep")
    assert prep_event["node_output"]["stdout"] == "ready"
    # Replay fingerprint: a REAL content hash rides the meta line (not a test literal),
    # and this trace predates nothing — inputs are an (empty) dict, never a crash.
    assert source.content_hash
    assert source.inputs in ({}, None)
