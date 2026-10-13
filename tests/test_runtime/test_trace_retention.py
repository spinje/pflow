"""Retention (Task 185, ADR-0018): ``prune_traces`` removes aged traces and never a Protected one.

Every fixture is a real JSONL trace under the producer's filename (``tests/shared/trace_jsonl``), the clock is
passed in (``now=NOW``), and faults are injected at the open (``tests/shared/open_hooks``) or ``os.stat`` for ONE path —
never at a helper, which a sweep that fails open would pass. Each fault test has a control: an unrelated aged
unprotected trace the SAME sweep removes, so "kept" never means "the sweep aborted".
"""

from __future__ import annotations

import errno
import hashlib
import itertools
import json
import logging
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from pflow.cli.main import cli
from pflow.core.exceptions import ResumeSupersededError
from pflow.core.trace_dir import (
    find_trace,
    list_traces,
    parse_trace_filename,
    paused_marker,
    read_trace_trailer,
    workflow_hash,
)
from pflow.core.trace_io import load_trace_file
from pflow.runtime.resume_source import list_paused_runs, load_resume_source
from pflow.runtime.trace_retention import SweepReport, prune_traces, retention_days, sweep_after_write
from pflow.runtime.workflow_trace import TRACE_FORMAT_VERSION, load_full_run_events
from tests.shared.open_hooks import fault_opens, record_opens
from tests.shared.trace_jsonl import flatten_trace_to_lines, trace_path_for

pytestmark = pytest.mark.trace_files

POSIX = sys.platform != "win32"
# The fixtures' clock. Real "now" (not a fixed date): the sweeps a run triggers read the real clock, and every
# age below is days away from the window's edge, so the seconds between this and theirs never matter.
NOW = datetime.now().replace(microsecond=0)
WINDOW = 14
_APPROVAL = {
    "node_id": "gated",
    "node_type": "ShellNode",
    "kind": "action_approval",
    "preview": {"command": "echo hi"},
    "question": None,
    "options": [],
    "recommendation": None,
}
_DENIED = {"kind": "gate", "phase": "resolution", "node_id": "gated", "resolution": "denied"}
# Production ids are uuid4: their first 8 characters (the `.from-` tag) are distinct. The shared helper's
# time-derived ids share a prefix across a fixture, which would make every Attempt's source look present.
_ids = (hashlib.sha1(f"run-{n}".encode(), usedforsecurity=False).hexdigest() for n in itertools.count())


@pytest.fixture
def debug(tmp_path: Path) -> Path:
    """The trace directory pflow itself uses under the test's HOME (conftest points ``Path.home`` here)."""
    directory = tmp_path / ".pflow" / "debug"
    directory.mkdir(parents=True)
    return directory


def present(tmp_path: Path, name: str) -> str:
    path = tmp_path / "workflows" / f"{name}.pflow.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("# workflow\n", encoding="utf-8")
    return str(path)


def deleted(tmp_path: Path, name: str) -> str:
    return str(tmp_path / "deleted" / f"{name}.pflow.md")


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def run_id(path: Path) -> str:
    parsed = parse_trace_filename(path.name)
    assert parsed is not None and parsed.execution_id is not None
    return parsed.execution_id


def _event(node_id: str, *, status: str = "success", restored: bool = False) -> dict[str, Any]:
    event: dict[str, Any] = {
        "node_id": node_id,
        "node_type": "ShellNode",
        "status": status,
        "node_output": {"stdout": f"{node_id}-{next(_ids)[:6]}"},  # distinct per trace: the agreement oracle
    }
    if restored:
        event.update(cached=True, restored=True)
    return event


def trace(
    debug: Path,
    workflow: str,
    days: float,
    *,
    status: str = "success",
    events: list[dict[str, Any]] | None = None,
    only: bool = False,
    resumed_from: Path | None = None,
    gate_lines: tuple[dict[str, Any], ...] = (),
    finished: bool = True,
    execution_id: str | None = None,
) -> Path:
    """A production-shaped trace started ``days`` before NOW: meta, events, and (``finished``) the trailer the
    collector writes — ``final_status``, ``nodes_executed`` (non-restored events), the pause record."""
    if events is None:
        events = [_event("a", status="failed" if status == "failed" else "success")]
    data: dict[str, Any] = {
        "format_version": TRACE_FORMAT_VERSION,
        "execution_id": execution_id or next(_ids),
        "workflow_name": "wf",
        "workflow_path": workflow,
        "only_node": "a" if only else None,
        "nodes": events,
        "final_status": status,
        "nodes_executed": sum(1 for event in events if not event.get("restored")),
        "failed_node_ids": [event["node_id"] for event in events if event["status"] == "failed"],
    }
    if resumed_from is not None:
        data["resumed_from"] = run_id(resumed_from)
    if status == "paused":
        data.update(paused_node_id="gated", gate_request=_APPROVAL)
    path, data = trace_path_for(debug, data, name="wf", started=ago(days))
    lines = flatten_trace_to_lines(data)
    trailer = lines.pop()
    lines += [*gate_lines, trailer] if finished else list(gate_lines)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    if status == "paused" and finished:
        paused_marker(path).touch()  # the producer writes the marker before the trailer
    return path


def empty_trace(debug: Path, workflow: str, days: float) -> Path:
    """A 0-byte file under a current-grammar name: a run whose meta write hit a full disk."""
    path, _ = trace_path_for(debug, {"workflow_path": workflow, "execution_id": next(_ids)}, started=ago(days))
    path.touch()
    return path


def legacy(debug: Path, prefix: str, days: float, *, micros: bool = False) -> Path:
    """A pre-185 name: ``workflow-trace-{hash8}[-{name}]-{started}.json`` (microseconds optional)."""
    path = debug / f"{prefix}-{ago(days).strftime('%Y%m%d-%H%M%S-%f' if micros else '%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"kind": "meta", "pflow_trace": 1}) + "\n", encoding="utf-8")
    return path


def names(debug: Path) -> set[str]:
    return {path.name for path in debug.iterdir()}


@contextmanager
def held_lock(path: Path) -> Iterator[None]:
    """A live writer: the exclusive ``flock`` the collector holds for the run's life (POSIX)."""
    import fcntl

    with open(path, "rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def recording_opens(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every file the code under test opens, in order (``tests/shared/open_hooks``)."""
    with monkeypatch.context() as patched:
        yield record_opens(patched)


@contextmanager
def faulted_opens(
    monkeypatch: pytest.MonkeyPatch, path: Path, error: Callable[[], OSError], *, nth: int | None = None
) -> Iterator[None]:
    """Every open of ``path`` (or only its ``nth``) raises ``error()``; every other file opens normally."""
    with monkeypatch.context() as patched:
        fault_opens(patched, path, error, nth=nth)
        yield


def emfile() -> OSError:
    return OSError(errno.EMFILE, "Too many open files")


def colliding_workflows(tmp_path: Path, pairs: int) -> list[tuple[str, str]]:
    """``pairs`` disjoint pairs of real workflow paths under ``tmp_path`` whose ``md5[:8]`` collides."""
    seen: dict[str, str] = {}
    found: list[tuple[str, str]] = []
    for n in itertools.count():
        path = str(tmp_path / "collide" / f"w{n}.pflow.md")
        key = workflow_hash(path)
        if key in seen:
            found.append((seen.pop(key), path))
            if len(found) == pairs:
                break
        else:
            seen[key] = path
    for pair in found:
        for path in pair:
            Path(path).parent.mkdir(exist_ok=True)
            Path(path).write_text("# collide\n", encoding="utf-8")
    return found


def prune(debug: Path) -> SweepReport:
    return prune_traces(debug, keep_days=WINDOW, now=NOW)


# ── The protected set ────────────────────────────────────────────────────────────────────────────────


def test_a_sweep_keeps_exactly_the_protected_traces(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every fixture is older than the window. Each row: the ONE rule that explains its outcome."""
    survivors: list[Path] = []
    gone: list[Path] = []

    # Rule 1 — a pending pause; a NEWER unrelated run of the same workflow is its newest run (rule 3) and
    # its Snapshot (rule 2), so only rule 1 explains the pause's survival.
    w1 = present(tmp_path, "w1")
    pending = trace(debug, w1, 40, status="paused")
    survivors += [pending, paused_marker(pending), trace(debug, w1, 30)]
    # Rules 1-3 need the workflow file: a pause of a deleted workflow can never be answered.
    deleted_pause = trace(debug, deleted(tmp_path, "w2"), 40, status="paused")
    gone += [deleted_pause, paused_marker(deleted_pause)]
    # A consumed pause: its Attempt ran a step. Neither is the newest run; no Snapshot exists. Both go —
    # the source first, then (rule 4) the Attempt.
    w3 = present(tmp_path, "w3")
    consumed = trace(debug, w3, 40, status="paused")
    gone += [
        consumed,
        paused_marker(consumed),
        trace(debug, w3, 35, status="failed", resumed_from=consumed),
    ]
    survivors.append(trace(debug, w3, 30, status="failed"))  # rule 3
    # Rule 2: the newest Snapshot survives, an older success goes.
    w5 = present(tmp_path, "w5")
    gone.append(trace(debug, w5, 40))
    survivors.append(trace(debug, w5, 30))
    # Rule 3 keeps a failed newest run, rule 2 the older success behind it; an `--only` success between
    # them is never the Snapshot; a denied and an incomplete run go.
    w6 = present(tmp_path, "w6")
    gone.append(trace(debug, w6, 50, finished=False))
    gone.append(trace(debug, w6, 45, status="denied", events=[]))
    survivors.append(trace(debug, w6, 40))  # rule 2
    gone.append(trace(debug, w6, 35, only=True))
    survivors.append(trace(debug, w6, 30, status="failed"))  # rule 3
    # A 0-byte file as the group's NEWEST name: not a run, so the newest real run and the Snapshot stay.
    w7 = present(tmp_path, "w7")
    survivors.append(trace(debug, w7, 40))  # rule 2
    survivors.append(trace(debug, w7, 30, status="failed"))  # rule 3
    gone.append(empty_trace(debug, w7, 20))
    # md5[:8] collisions — one rule per path: each colliding workflow keeps its newest run and Snapshot.
    (a1, b1), (a2, b2) = colliding_workflows(tmp_path, 2)
    # The collider's Snapshot is NEWER than the identity's (the identity's rule-2 walk passes over it).
    gone.append(trace(debug, a1, 40))
    survivors.append(trace(debug, b1, 35))  # B1's Snapshot
    survivors.append(trace(debug, a1, 30))  # A1's Snapshot
    survivors.append(trace(debug, a1, 28, status="failed"))  # A1's newest run
    survivors.append(trace(debug, b1, 25, status="failed"))  # B1's newest run: the group's identity
    # The collider's success is OLDER than the identity's Snapshot (found by the removal probe).
    gone.append(trace(debug, b2, 40))
    survivors.append(trace(debug, a2, 35))  # A2's only run
    survivors.append(trace(debug, b2, 25))  # B2's newest run and Snapshot
    # Nothing to protect: a lone 0-byte file, an orphan marker, legacy names (age alone, never read).
    gone.append(empty_trace(debug, present(tmp_path, "w9"), 30))
    orphan = debug / "workflow-trace-0badf00d-gone.deadbeef-20260101-000000-000000.json.paused"
    orphan.touch()
    gone.append(orphan)
    legacy_names = [
        legacy(debug, "workflow-trace-1a2b3c4d-old-wf", 300),
        legacy(debug, "workflow-trace-1a2b3c4d-old-wf", 200, micros=True),
        legacy(debug, "workflow-trace-5e6f7a8b", 100),
        legacy(debug, "workflow-trace-5e6f7a8b-x", 50),
        legacy(debug, "workflow-trace-9c0d1e2f-name_with-dash", 15, micros=True),
    ]
    gone += legacy_names
    survivors.append(legacy(debug, "workflow-trace-9c0d1e2f-young", 13))  # age alone keeps it
    # A name no grammar reads is not a trace: never removed, never read.
    unrecognised = debug / "workflow-trace-0123abcd-x.id.1bad-20250101-000000-000000.json"
    unrecognised.write_text("{}\n", encoding="utf-8")
    survivors.append(unrecognised)

    with ExitStack() as stack:
        if POSIX:
            # Rule 1 with count_live=False — a live zero-work Attempt is a reservation, not consumption: its
            # source stays. A newer unrelated run is the newest run and the Snapshot. The Attempt itself is
            # live (rule 5).
            w4 = present(tmp_path, "w4")
            source = trace(debug, w4, 40, status="paused")
            live_attempt = trace(debug, w4, 35, status="incomplete", events=[], resumed_from=source, finished=False)
            survivors += [source, paused_marker(source), live_attempt, trace(debug, w4, 30)]
            # Rule 5 — a locked incomplete trace, older than its workflow's newest run.
            w8 = present(tmp_path, "w8")
            locked = trace(debug, w8, 30, status="incomplete", finished=False)
            survivors += [locked, trace(debug, w8, 20)]
            stack.enter_context(held_lock(live_attempt))
            stack.enter_context(held_lock(locked))
        before = names(debug)
        assert {path.name for path in survivors + gone} == before, "every fixture is in exactly one column"
        opened = stack.enter_context(recording_opens(monkeypatch))
        report = prune(debug)

    assert names(debug) == {path.name for path in survivors}
    legacy_paths = {str(path) for path in legacy_names}
    assert not legacy_paths & set(opened), "a legacy name is removed on its age alone, never read"
    assert str(unrecognised) not in opened
    assert len(report.unreadable) == 0
    assert report.removed == len([path for path in gone if not path.name.endswith(".paused")])

    # The features the protected set exists for still work on the pruned directory.
    snapshot = load_full_run_events(w5, debug_dir=debug)
    assert snapshot is not None and snapshot[1] == "success"
    paused = list_paused_runs(debug)
    assert {run.execution_id for run in paused.runs} == {run_id(pending)} | ({run_id(source)} if POSIX else set())
    assert paused.hidden_missing_file == []
    resumed = load_resume_source(execution_id=run_id(pending), debug_dir=debug, gate_answer={"approve": True})
    assert resumed.entry_node_id == "gated"
    reported = CliRunner().invoke(cli, ["report", "-o", str(tmp_path / "report")])
    assert reported.exit_code == 0, reported.output


def test_the_snapshot_survives_where_the_loader_finds_it(tmp_path: Path, debug: Path) -> None:
    """Agreement with the oracle: ``load_full_run_events`` returns the same trace before and after a sweep
    — across young/aged successes, ``--only``, failed, degraded, and a success over zero executed steps."""
    shapes: dict[str, list[tuple[float, dict[str, Any]]]] = {
        "aged degraded behind a failure": [(50, {}), (40, {"status": "degraded"}), (30, {"status": "failed"})],
        "an empty success is skipped": [(50, {}), (40, {"events": []}), (30, {"status": "failed"})],
        "an --only success is skipped": [(50, {}), (40, {"only": True}), (30, {"status": "failed"})],
        "the pick is young": [(50, {}), (40, {}), (5, {}), (2, {"status": "failed"})],
        "only failures are young": [(50, {}), (40, {}), (5, {"status": "failed"}), (2, {"status": "failed"})],
    }
    for label, rows in shapes.items():
        workflow = present(tmp_path, f"shape-{len(label)}-{label.split()[1]}")
        written = {trace(debug, workflow, days, **kwargs): days for days, kwargs in rows}
        before = load_full_run_events(workflow, debug_dir=debug)
        assert before is not None, label
        [pick] = [path for path in written if load_trace_file(path)["nodes"] == before[0]]
        prune(debug)
        assert load_full_run_events(workflow, debug_dir=debug) == before, label
        # Over-protection is bounded: an aged usable success other than the loader's pick survives only when
        # the pick is young (the walk's aged pick), and then at most one.
        extras = [
            path
            for path, days in written.items()
            if days > WINDOW and path.exists() and path != pick and _is_usable_success(path)
        ]
        assert len(extras) <= (1 if written[pick] < WINDOW else 0), (label, extras)


def _is_usable_success(path: Path) -> bool:
    data = load_trace_file(path)
    return data.get("final_status") in ("success", "degraded") and bool(data.get("nodes")) and not data.get("only_node")


def test_a_window_of_zero_removes_nothing_and_young_traces_are_never_candidates(tmp_path: Path, debug: Path) -> None:
    gone_workflow = deleted(tmp_path, "w")
    aged = trace(debug, gone_workflow, 30)
    young = [trace(debug, gone_workflow, days, status="failed") for days in (13.9, 5, 1)]

    assert prune_traces(debug, keep_days=0, now=NOW) == SweepReport()
    assert prune_traces(debug, keep_days=10**9, now=NOW) == SweepReport()  # "forever" typed as a big number
    assert aged.exists()

    report = prune(debug)
    assert not aged.exists()
    assert all(path.exists() for path in young)
    assert report.removed == 1


def test_aged_failures_of_a_busy_workflow_go_and_one_aged_snapshot_may_stay(tmp_path: Path, debug: Path) -> None:
    """Rule 3 is satisfied by a young run; the rule-2 walk keeps at most the newest aged success."""
    workflow = present(tmp_path, "busy")
    older_success = trace(debug, workflow, 60)
    aged_snapshot = trace(debug, workflow, 50)
    aged_failures = [trace(debug, workflow, days, status="failed") for days in (40, 30, 20)]
    young = trace(debug, workflow, 1)

    prune(debug)

    assert young.exists() and aged_snapshot.exists()
    assert not older_success.exists()
    assert not any(path.exists() for path in aged_failures)


# ── Rule 4: consumption evidence outlives its source ──────────────────────────────────────────────────


@contextmanager
def unlink_refused(monkeypatch: pytest.MonkeyPatch, *refused: Path, winerror: int | None = None) -> Iterator[None]:
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self in refused:
            error = PermissionError(errno.EACCES, "Access is denied", str(self))
            if winerror is not None:
                error.winerror = winerror  # type: ignore[attr-defined]  # set by Windows only; the sweep reads it
            raise error
        real_unlink(self, missing_ok=missing_ok)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "unlink", unlink)
        yield


def _denied_attempt(debug: Path, workflow: str, days: float, source: Path) -> Path:
    """A denied answer to ``source``: zero executed steps, a human verdict line — it consumed the token."""
    return trace(
        debug,
        workflow,
        days,
        status="denied",
        events=[_event("prep", restored=True)],
        resumed_from=source,
        gate_lines=(_DENIED,),
    )


@pytest.mark.parametrize("fault", [True, False], ids=["source-unlink-refused", "no-fault"])
def test_an_attempt_outlives_its_source(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, fault: bool
) -> None:
    workflow = present(tmp_path, "w")
    source = trace(debug, workflow, 40, status="paused")
    attempt = _denied_attempt(debug, workflow, 35, source)
    newest = trace(debug, workflow, 30, status="failed")

    with unlink_refused(monkeypatch, *([source] if fault else [])):
        report = prune(debug)

    assert newest.exists()
    if not fault:
        assert not source.exists() and not attempt.exists() and not paused_marker(source).exists()
        return
    assert (len(report.skipped), source.exists(), paused_marker(source).exists(), attempt.exists()) == (
        1,
        True,
        True,
        True,
    )
    # The answer is still on disk, so the token stays spent: not listed, and refused as superseded.
    assert list_paused_runs(debug).runs == []
    with pytest.raises(ResumeSupersededError):
        load_resume_source(execution_id=run_id(source), debug_dir=debug, gate_answer={"approve": True})


@pytest.mark.parametrize("fault", [True, False], ids=["middle-unlink-refused", "no-fault"])
def test_an_attempt_chain_unwinds_root_first(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, fault: bool
) -> None:
    """P ← A1 ← A2: one sweep removes the chain in waves; a refused A1 keeps A2."""
    workflow = present(tmp_path, "w")
    root = trace(debug, workflow, 50, status="failed")
    first = trace(debug, workflow, 45, status="failed", resumed_from=root)
    second = trace(debug, workflow, 40, status="failed", resumed_from=first)
    newest = trace(debug, workflow, 30, status="failed")

    with unlink_refused(monkeypatch, *([first] if fault else [])):
        prune(debug)

    assert newest.exists() and not root.exists()
    assert (first.exists(), second.exists()) == ((True, True) if fault else (False, False))


def test_a_pause_whose_id_prefix_another_consumed_pause_shares_stays_listed_resumable_and_protected(
    tmp_path: Path, debug: Path
) -> None:
    """Two pending sources share their first 8 id characters (the `.from-` tag), one consumed: the other is
    still protected (a newer success is the newest run and the Snapshot, so only rule 1 keeps it), listed
    and resumable — the tag narrows, the Attempt's ``resumed_from`` decides."""
    workflow = present(tmp_path, "w")
    consumed = trace(debug, workflow, 50, status="paused", execution_id="pause-aaaa1")
    pending = trace(debug, workflow, 45, status="paused", execution_id="pause-aaaa2")
    attempt = _denied_attempt(debug, workflow, 40, consumed)
    assert ".from-pause-aa-" in attempt.name
    trace(debug, workflow, 30)

    prune(debug)

    assert pending.exists() and paused_marker(pending).exists()
    assert not consumed.exists()
    assert [run.execution_id for run in list_paused_runs(debug).runs] == ["pause-aaaa2"]
    resumed = load_resume_source(execution_id="pause-aaaa2", debug_dir=debug, gate_answer={"approve": True})
    assert resumed.entry_node_id == "gated"


def test_the_newest_run_being_an_attempt_keeps_its_source(tmp_path: Path, debug: Path) -> None:
    """A dead zero-work Attempt as the newest run must not move 'the newest run' off a resumable source."""
    workflow = present(tmp_path, "w")
    source = trace(debug, workflow, 40, status="failed")
    dead = trace(debug, workflow, 30, status="failed", events=[], resumed_from=source)
    control = trace(debug, deleted(tmp_path, "other"), 30)

    prune(debug)

    assert source.exists() and dead.exists()
    assert not control.exists()


# ── Fail-closed reads ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("nth", [None, 2], ids=["every-read", "the-trailer-read"])
def test_an_unreadable_pending_pause_is_kept_with_one_warning(
    tmp_path: Path,
    debug: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    nth: int | None,
) -> None:
    workflow = present(tmp_path, "w")
    pause = trace(debug, workflow, 40, status="paused")
    trace(debug, workflow, 30)  # the newest run and Snapshot: only rule 1 could keep the pause
    control = trace(debug, deleted(tmp_path, "other"), 30)
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", str(WINDOW))

    with faulted_opens(monkeypatch, pause, emfile, nth=nth), caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert pause.exists() and paused_marker(pause).exists()
    assert not control.exists()
    warnings = [record for record in caplog.records if record.name == "pflow.runtime.trace_retention"]
    assert len(warnings) == 1
    assert "kept 1 unreadable trace(s)" in warnings[0].getMessage()
    assert str(pause) in warnings[0].getMessage()


def test_an_attempt_the_pause_rule_cannot_read_keeps_the_pause_and_is_named(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Rule 1's consumption check cannot load the pause's Attempt (one fault, at that load only — the removal
    probe of the Attempt later reads fine): it may have answered the token or not, so the pause and its marker
    stay and the one warning names the Attempt. A newer success is the workflow's newest run and Snapshot, so
    only rule 1 could keep the pause."""
    workflow = present(tmp_path, "w")
    pause = trace(debug, workflow, 40, status="paused")
    attempt = trace(debug, workflow, 35, status="failed", events=[], resumed_from=pause)  # dead, zero work
    trace(debug, workflow, 30)
    control = trace(debug, deleted(tmp_path, "other"), 30)
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", str(WINDOW))

    with faulted_opens(monkeypatch, attempt, emfile, nth=1), caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert pause.exists() and paused_marker(pause).exists() and attempt.exists()
    assert not control.exists()
    warnings = [record.getMessage() for record in caplog.records if record.name == "pflow.runtime.trace_retention"]
    assert len(warnings) == 1 and "kept 1 unreadable trace(s)" in warnings[0] and str(attempt) in warnings[0]


def test_an_unreadable_newest_trace_keeps_its_whole_group_even_without_a_snapshot(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The identity read fails: the file could be the workflow's newest run, so nothing of its group goes."""
    workflow = present(tmp_path, "w")
    group = [trace(debug, workflow, days, status="failed") for days in (50, 40, 30)]
    control = trace(debug, deleted(tmp_path, "other"), 30)

    with faulted_opens(monkeypatch, group[-1], emfile):
        report = prune(debug)

    assert all(path.exists() for path in group)
    assert not control.exists()
    assert len(report.unreadable) == 1


@pytest.mark.parametrize("nth", [None, 2], ids=["every-read", "the-trailer-read"])
def test_an_unreadable_newest_success_keeps_its_whole_group(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, nth: int | None
) -> None:
    workflow = present(tmp_path, "w")
    older_success = trace(debug, workflow, 50)
    failure = trace(debug, workflow, 40, status="failed")
    newest_success = trace(debug, workflow, 30)
    control = trace(debug, deleted(tmp_path, "other"), 30)

    with faulted_opens(monkeypatch, newest_success, emfile, nth=nth):
        report = prune(debug)

    assert older_success.exists() and failure.exists() and newest_success.exists()
    assert not control.exists()
    assert len(report.unreadable) == 1


def test_an_unreadable_removal_candidate_is_kept(tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The one open that reads the head AND probes the lock fails: kept (and only it — it is older than the
    Snapshot and carries no marker or lineage)."""
    workflow = present(tmp_path, "w")
    candidate = trace(debug, workflow, 50, status="failed")
    removable = trace(debug, workflow, 45, status="failed")
    trace(debug, workflow, 30)
    control = trace(debug, deleted(tmp_path, "other"), 30)

    with faulted_opens(monkeypatch, candidate, emfile):
        report = prune(debug)

    assert candidate.exists()
    assert not removable.exists() and not control.exists()
    assert len(report.unreadable) == 1


def test_an_unreadable_trailer_on_an_older_trace_keeps_that_trace(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Snapshot walk cannot read a trailer and finds no Snapshot after it: that file is kept (it may be the
    Snapshot), though its head reads fine on the removal probe; the rest of the group still goes."""
    workflow = present(tmp_path, "w")
    older = trace(debug, workflow, 50, status="failed")
    unreadable_tail = trace(debug, workflow, 40)
    trace(debug, workflow, 30, status="failed")

    with faulted_opens(monkeypatch, unreadable_tail, emfile, nth=1):  # its first open is the walk's tail read
        report = prune(debug)

    assert len(report.unreadable) == 1, "the fault hit the tail read"
    assert unreadable_tail.exists()
    assert not older.exists()


def test_an_unreadable_attempt_or_a_trace_newer_than_the_snapshot_keeps_its_group(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The removal probe cannot read a trace that could protect others — an Attempt, or a run newer than the
    Snapshot the walk picked: the whole group stays this sweep."""
    workflow = present(tmp_path, "w")
    oldest = trace(debug, workflow, 70, status="failed")
    source = trace(debug, workflow, 60, status="failed")
    attempt = trace(debug, workflow, 55, status="failed", resumed_from=source)
    snapshot = trace(debug, workflow, 50)
    newer_than_snapshot = trace(debug, workflow, 40, status="failed")
    trace(debug, workflow, 30, status="failed")
    control = trace(debug, deleted(tmp_path, "other"), 30)

    # The attempt's first open is the probe; the newer run's first is the walk's tail read, its second the probe.
    with faulted_opens(monkeypatch, attempt, emfile):
        report = prune(debug)
    assert (len(report.unreadable), oldest.exists(), source.exists(), control.exists()) == (1, True, True, False)

    attempt.unlink()
    with faulted_opens(monkeypatch, newer_than_snapshot, emfile, nth=2):
        report = prune(debug)
    assert (len(report.unreadable), oldest.exists(), source.exists(), snapshot.exists()) == (1, True, True, True)


def test_a_workflow_file_that_cannot_be_checked_keeps_its_group(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    workflow = present(tmp_path, "w")
    group = [trace(debug, workflow, days, status="failed") for days in (50, 40, 30)]
    control = trace(debug, deleted(tmp_path, "other"), 30)
    real_stat = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if str(path) == workflow:
            raise PermissionError(errno.EACCES, "Operation not permitted", workflow)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", str(WINDOW))
    with monkeypatch.context() as patched, caplog.at_level(logging.WARNING):
        patched.setattr(os, "stat", stat)
        sweep_after_write(debug)

    assert all(path.exists() for path in group)
    assert not control.exists()
    # Never silent: the one warning names the workflow whose file could not be checked.
    warnings = [record.getMessage() for record in caplog.records if record.name == "pflow.runtime.trace_retention"]
    assert len(warnings) == 1 and "1 workflow(s) whose file could not be checked" in warnings[0], warnings
    assert workflow in warnings[0]


def test_a_trace_that_vanishes_mid_sweep_is_not_counted_and_exposes_nothing(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The newest run reads as gone: the next one becomes the newest run — nothing else is removed."""
    workflow = present(tmp_path, "w")
    snapshot = trace(debug, workflow, 50)
    next_newest = trace(debug, workflow, 40, status="failed")
    vanishing = trace(debug, workflow, 30, status="failed")
    control = trace(debug, deleted(tmp_path, "other"), 30)

    with faulted_opens(monkeypatch, vanishing, lambda: FileNotFoundError(errno.ENOENT, "gone")):
        report = prune(debug)

    assert snapshot.exists() and next_newest.exists() and vanishing.exists()
    assert not control.exists()
    assert len(report.unreadable) == 0


@pytest.mark.skipif(not POSIX, reason="advisory flock is POSIX-only")
def test_an_aged_trace_held_by_a_live_writer_is_kept(tmp_path: Path, debug: Path) -> None:
    workflow = deleted(tmp_path, "w")
    live = trace(debug, workflow, 40, status="incomplete", finished=False)
    control = trace(debug, deleted(tmp_path, "other"), 30)

    with held_lock(live):
        prune(debug)

    assert live.exists()
    assert not control.exists()


def test_unknown_facts_are_kept_and_still_found(tmp_path: Path, debug: Path) -> None:
    """A later pflow's tag or sidecar is a "keep this" an older sweep must honour; lookups ignore it."""
    workflow = present(tmp_path, "w")
    plain = trace(debug, workflow, 50, status="failed")
    tagged_original = trace(debug, workflow, 45, status="failed")
    cut = len(tagged_original.name) - len("-YYYYMMDD-HHMMSS-ffffff.json")
    tagged = tagged_original.with_name(f"{tagged_original.name[:cut]}.recording{tagged_original.name[cut:]}")
    tagged_original.rename(tagged)
    claimed = trace(debug, workflow, 40, status="failed")
    claim = claimed.with_name(claimed.name + ".claim")
    claim.touch()
    trace(debug, workflow, 30)

    prune(debug)

    assert not plain.exists()
    assert tagged.exists() and claimed.exists() and claim.exists()
    entries = list_traces(debug).traces
    assert find_trace(entries, run_id(tagged)) is not None
    assert find_trace(entries, run_id(claimed)) is not None


# ── Fault isolation and Windows handles ───────────────────────────────────────────────────────────────


def test_a_windows_sharing_violation_retries_once_then_skips_and_continues(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    held = trace(debug, deleted(tmp_path, "a"), 40)
    other = trace(debug, deleted(tmp_path, "b"), 40)
    attempts: list[Path] = []
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self == held:
            attempts.append(self)
            error = PermissionError(errno.EACCES, "The process cannot access the file", str(self))
            error.winerror = 32  # type: ignore[attr-defined]  # set by Windows only; the sweep reads it
            raise error
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")
    with monkeypatch.context() as patched, caplog.at_level(logging.WARNING):
        patched.setattr(Path, "unlink", unlink)
        patched.setattr("pflow.runtime.trace_retention._WINDOWS_UNLINK_RETRY_DELAY", 0)
        sweep_after_write(debug)

    assert attempts == [held, held]
    assert held.exists() and not other.exists()
    [warning] = [record.getMessage() for record in caplog.records if record.name == "pflow.runtime.trace_retention"]
    # Actionable: which file, why, and what to check if the next run's retry fails too.
    assert f"could not remove 1 trace(s) ({held}: The process cannot access the file)" in warning
    assert "check the permissions of the trace directory and those files" in warning


def test_a_sweep_that_raises_never_escapes(
    debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> SweepReport:
        raise RuntimeError("sweep bug")

    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")
    monkeypatch.setattr("pflow.runtime.trace_retention.prune_traces", boom)
    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)
    assert any(
        "trace retention failed" in record.getMessage() and "sweep bug" in record.getMessage()
        for record in caplog.records
    )


# ── Lifecycle races, made deterministic ──────────────────────────────────────────────────────────────


@pytest.mark.skipif(not POSIX, reason="advisory flock is POSIX-only")
def test_a_live_attempt_that_exits_without_consuming_leaves_its_source_resumable(tmp_path: Path, debug: Path) -> None:
    """start → sweep → exit: the sweep saw a live zero-work Attempt (a reservation); once it dies without
    recording work, its source is still answerable."""
    workflow = present(tmp_path, "w")
    source = trace(debug, workflow, 40, status="paused")
    attempt = trace(debug, workflow, 35, status="incomplete", events=[], resumed_from=source, finished=False)
    trace(debug, workflow, 30)

    with held_lock(attempt):
        prune(debug)
    prune(debug)  # the Attempt has exited: a dead zero-work Attempt never consumes

    assert source.exists() and paused_marker(source).exists()
    assert [run.execution_id for run in list_paused_runs(debug).runs] == [run_id(source)]
    resumed = load_resume_source(execution_id=run_id(source), debug_dir=debug, gate_answer={"approve": True})
    assert resumed.entry_node_id == "gated"


def test_two_interleaved_sweeps_leave_exactly_the_protected_set(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sweep X lists; sweep Y then removes a consumed pause and its Attempt; X resumes on its stale listing."""
    import pflow.runtime.trace_retention as retention

    workflow = present(tmp_path, "w")
    consumed = trace(debug, workflow, 50, status="paused")
    attempt = _denied_attempt(debug, workflow, 45, consumed)
    pending = trace(debug, workflow, 40, status="paused")
    newest = trace(debug, workflow, 30, status="failed")
    stale_listing = list_traces(debug, include_legacy=True)

    prune(debug)  # sweep Y runs to completion between X's listing and X's reads
    assert not consumed.exists() and not attempt.exists()

    monkeypatch.setattr(retention, "list_traces", lambda *_args, **_kwargs: stale_listing)
    report = prune(debug)  # sweep X, on the listing it took before Y

    assert names(debug) == {pending.name, paused_marker(pending).name, newest.name}
    assert len(report.unreadable) == 0


# ── The cost model ────────────────────────────────────────────────────────────────────────────────────


def test_the_second_sweep_reads_only_what_it_must(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """2,000 idle workflows (one aged Snapshot each), 50 aged removable traces, and one workflow with 1,000
    young failures behind an aged Snapshot. The bound per examined group: the identity head (the newest
    trace — the one young read), the Snapshot pick's tail + head, and one open per removal candidate."""
    idle = [present(tmp_path, f"idle-{n}") for n in range(2000)]
    aged_snapshots = {trace(debug, workflow, 30) for workflow in idle}
    removable = {trace(debug, workflow, 40, status="failed") for workflow in idle[:25]}
    removable |= {trace(debug, deleted(tmp_path, f"gone-{n}"), 40) for n in range(25)}
    busy = present(tmp_path, "busy")
    busy_snapshot = trace(debug, busy, 30)
    young = [trace(debug, busy, 1 + n / 10_000, status="failed") for n in range(1000)]
    newest_young = young[0]
    young_paths = {str(path) for path in young}

    with recording_opens(monkeypatch) as first_opens:
        started = time.perf_counter()
        first = prune(debug)
        first_seconds = time.perf_counter() - started
    with recording_opens(monkeypatch) as second_opens:
        started = time.perf_counter()
        second = prune(debug)
        second_seconds = time.perf_counter() - started

    assert first.removed == 50 and not any(path.exists() for path in removable)
    assert second.removed == 0
    groups = len(idle) + 1
    for opens in (first_opens, second_opens):
        assert set(opens) & young_paths == {str(newest_young)}, "the busy workflow's young runs are never read"
    assert len(first_opens) <= 3 * (groups + 25) + 50
    assert set(second_opens) == {str(path) for path in aged_snapshots | {busy_snapshot, newest_young}}
    assert len(second_opens) <= 3 * groups
    assert second_seconds < 10, second_seconds  # recorded below; ~10x margin
    with capsys.disabled():
        print(
            f"\n[retention cost] first sweep: {len(first_opens)} opens, {first_seconds:.3f}s; "
            f"second sweep: {len(second_opens)} opens, {second_seconds:.3f}s"
        )


# ── Settings: the window, the env override, and a setting that cannot be trusted ──────────────────────


def _settings_file(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / ".pflow" / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "settings",
    [
        None,
        {"llm": {"foo": True}, "registry": {"nodes": {"bar": 1}}},
        # The user's own variables, retention-flavoured ones included: only a name that also says `trace` or
        # starts with `PFLOW_` is a suspect.
        {"env": {"S3_RETENTION_DAYS": "1", "API_TOKEN": "x", "LOG_RETAIN": "7"}},
    ],
    ids=["no-file", "unrelated-unknown-keys", "env-names-that-are-not-misspellings"],
)
def test_no_env_prunes_at_the_default(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, settings: dict[str, Any] | None
) -> None:
    """The default most users hit — and unknown keys that do not look like retention leave it on."""
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    if settings is not None:
        _settings_file(tmp_path, settings)
    aged = trace(debug, deleted(tmp_path, "w"), 15)
    young = trace(debug, deleted(tmp_path, "w"), 13)

    assert retention_days() == 14
    sweep_after_write(debug)

    assert not aged.exists() and young.exists()


@pytest.mark.parametrize(
    ("env", "settings", "expected"),
    [
        ("3", {"runtime": {"trace_retention_days": 0}}, 3),
        ("0", {"runtime": {"trace_retention_days": 30}}, 0),
        (None, {"runtime": {"trace_retention_days": 30}}, 30),
        (None, {"runtime": {"trace_retention_days": 0}}, 0),
        (None, {"runtime": {"foo": True}}, 14),  # a newer pflow's future key never switches retention off
    ],
)
def test_the_env_override_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str | None, settings: dict[str, Any], expected: int
) -> None:
    if env is None:
        monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    else:
        monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", env)
    _settings_file(tmp_path, settings)
    assert retention_days() == expected


@pytest.mark.parametrize(
    ("env", "settings", "says"),
    [
        ("never", None, "PFLOW_TRACE_RETENTION_DAYS='never'"),
        ("-1", None, "PFLOW_TRACE_RETENTION_DAYS='-1'"),
        (None, {"runtime": {"trace_retention_days": 0, "template_resolution_mode": "bogus"}}, "could not be loaded"),
        (None, {"runtime": {"trace_retention_days": True}}, "could not be loaded"),
        (None, {"runtime": {"trace_retention_day": 0}}, "runtime.trace_retention_day"),
        (None, {"runtime": {"traceRetentionDays": 0}}, "runtime.traceRetentionDays"),
        (None, {"trace_retention_days": 0}, "sets trace_retention_days"),
        (None, {"llm": {"trace_retention_days": 0}}, "sets llm.trace_retention_days"),
        (None, {"registry": {"trace_retention_days": 0}}, "sets registry.trace_retention_days"),
        (None, {"registry": {"nodes": {"trace_retention_days": 0}}}, "sets registry.nodes.trace_retention_days"),
        (None, {"runtime_settings": {"trace_retention_days": 0}}, "sets runtime_settings"),
        (None, {"runtime_settings": [{"trace_retention_days": 0}]}, "sets runtime_settings"),
        (None, {"env": {"PFLOW_TRACE_RETENTION_DAY": "0"}}, "sets env.PFLOW_TRACE_RETENTION_DAY"),
        (None, {"env": {"pflow_trace_retention_days": "0"}}, "sets env.pflow_trace_retention_days"),
        (None, {"runtime": {"trace_retension_days": 0}}, "runtime.trace_retension_days"),
        (None, {"runtime": {"trace_retain_days": 0}}, "runtime.trace_retain_days"),
        (None, {"env": {"PFLOW_TRACE_RETENTON_DAYS": "0"}}, "sets env.PFLOW_TRACE_RETENTON_DAYS"),
    ],
    ids=[
        "env-word",
        "env-negative",
        "file-fails-to-load",
        "a-bool-is-not-a-number-of-days",
        "misspelled",
        "camel-case",
        "misplaced-at-root",
        "misplaced-in-llm",
        "misplaced-in-registry",
        "misplaced-in-registry-nodes",
        "inside-an-unknown-section",
        "inside-an-array",
        "misspelled-in-env",
        "wrong-case-in-env",
        "typo-inside-the-word",
        "retain-not-retention",
        "typo-inside-the-word-in-env",
    ],
)
def test_a_setting_that_cannot_be_trusted_prunes_nothing_with_a_warning(
    tmp_path: Path,
    debug: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    env: str | None,
    settings: dict[str, Any] | None,
    says: str,
) -> None:
    if env is None:
        monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    else:
        monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", env)
    if settings is not None:
        _settings_file(tmp_path, settings)
    aged = trace(debug, deleted(tmp_path, "w"), 400)

    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert aged.exists()
    warnings = [record.getMessage() for record in caplog.records if record.name == "pflow.runtime.trace_retention"]
    assert len(warnings) == 1 and "trace retention skipped" in warnings[0] and says in warnings[0], warnings


@pytest.mark.parametrize(
    ("stored", "expected"), [("0", 0), ("3", 3), ("", None), ("never", None)], ids=["zero", "three", "empty", "word"]
)
def test_the_override_stored_in_settings_env_is_read_directly(
    tmp_path: Path,
    debug: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stored: str,
    expected: int | None,
) -> None:
    """``settings.env.PFLOW_TRACE_RETENTION_DAYS`` counts even when startup injection never copied it into the
    process environment (it skips an empty value and aborts on an entry it cannot set, like ``BAD=KEY``): a
    valid value wins over ``runtime.trace_retention_days``; an invalid one prunes nothing, with a warning."""
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    _settings_file(
        tmp_path,
        {"runtime": {"trace_retention_days": 30}, "env": {"BAD=KEY": "x", "PFLOW_TRACE_RETENTION_DAYS": stored}},
    )
    aged = trace(debug, deleted(tmp_path, "w"), 400)

    assert retention_days() == expected
    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert aged.exists() == (expected != 3)
    warnings = [record.getMessage() for record in caplog.records if record.name == "pflow.runtime.trace_retention"]
    if expected is None:
        assert any(f"env.PFLOW_TRACE_RETENTION_DAYS in {tmp_path}" in warning for warning in warnings), warnings
    else:
        assert warnings == []


def test_the_process_override_wins_over_the_stored_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "5")
    _settings_file(tmp_path, {"env": {"PFLOW_TRACE_RETENTION_DAYS": "0"}})
    assert retention_days() == 5


def test_a_settings_file_that_repeats_a_key_prunes_nothing_and_is_never_overwritten(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A hand edit that repeats ``runtime``: JSON would keep the last block and drop the opt-out silently."""
    from pflow.core.settings import SettingsManager
    from pflow.core.user_errors import UserFriendlyError

    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    path = tmp_path / ".pflow" / "settings.json"
    path.write_text(
        '{"runtime": {"trace_retention_days": 0}, "env": {"K": "v"}, "runtime": {"template_resolution_mode": "strict"}}',
        encoding="utf-8",
    )
    original = path.read_bytes()
    aged = trace(debug, deleted(tmp_path, "w"), 400)

    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert aged.exists()
    assert any("duplicate key(s) in one object: runtime" in warning for warning in _retention_warnings(caplog))
    with pytest.raises(UserFriendlyError, match="Settings file not saved"):
        SettingsManager().set_env("OTHER", "x")
    assert path.read_bytes() == original


def test_a_quoted_number_of_days_loads_and_keeps_the_env_keys(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``"0"`` is a reasonable hand edit: it coerces to 0 — no failed load, so the user's env keys still load."""
    from pflow.core.settings import SettingsManager

    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    _settings_file(tmp_path, {"runtime": {"trace_retention_days": "0"}, "env": {"API_TOKEN": "s3cret"}})
    aged = trace(debug, deleted(tmp_path, "w"), 400)

    manager = SettingsManager()
    assert manager.get_env("API_TOKEN") == "s3cret" and manager.load_error is None
    assert retention_days() == 0
    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)
    assert aged.exists()
    assert _retention_warnings(caplog) == []


def _retention_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == "pflow.runtime.trace_retention"]


@pytest.mark.parametrize(
    "name",
    [
        "PFLOW_TRACE_RETENTION_DAY",
        pytest.param(
            "pflow_trace_retention_days",
            marks=pytest.mark.skipif(
                sys.platform == "win32",
                reason="Windows environment names are case-insensitive: there this IS the override "
                "(test_on_windows_the_lowercase_name_is_the_override)",
            ),
        ),
        "PFLOW_RETENTION_DAYS",
        "PFLOW_TRACE_RETENTON_DAYS",
    ],
)
def test_a_misspelled_override_in_the_environment_prunes_nothing_with_one_warning(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str
) -> None:
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    monkeypatch.setenv(name, "0")
    aged = trace(debug, deleted(tmp_path, "w"), 400)

    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert aged.exists()
    [warning] = _retention_warnings(caplog)
    assert f"trace retention skipped: the environment sets {name}" in warning


@pytest.mark.skipif(sys.platform != "win32", reason="POSIX environment names are case-sensitive")
def test_on_windows_the_lowercase_name_is_the_override(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Windows ``os.environ`` ignores case, so ``pflow_trace_retention_days`` is the override itself, not a
    misspelling: its value applies, with no warning (on POSIX it is a misspelling — the test above)."""
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    monkeypatch.setenv("pflow_trace_retention_days", "3")
    aged = trace(debug, deleted(tmp_path, "w"), 5)

    assert retention_days() == 3
    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)
    assert not aged.exists()
    assert _retention_warnings(caplog) == []


def test_a_settings_env_typo_exported_at_startup_is_reported_once(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Startup copies settings.env into os.environ, so the same typo is in both places: one warning, not two."""
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    _settings_file(tmp_path, {"env": {"PFLOW_TRACE_RETENTION_DAY": "0"}})
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAY", "0")  # what settings-env injection does in a real process
    aged = trace(debug, deleted(tmp_path, "w"), 400)

    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert aged.exists()
    [warning] = _retention_warnings(caplog)
    assert "PFLOW_TRACE_RETENTION_DAY (directly or through settings.env)" in warning


def test_other_tools_retention_variables_never_switch_retention_off(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    monkeypatch.setenv("OTEL_TRACE_RETENTION_DAYS", "0")
    monkeypatch.setenv("TEMPO_RETENTION", "1h")
    aged = trace(debug, deleted(tmp_path, "w"), 15)

    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert not aged.exists()
    assert _retention_warnings(caplog) == []


@pytest.mark.parametrize("value", ["0", "3"])
def test_the_exact_override_wins_over_a_misspelled_one(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", value)
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAY", "0")
    assert retention_days() == int(value)


@pytest.mark.parametrize("section", ["runtime", "llm"])
def test_a_misspelled_opt_out_survives_a_settings_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, section: str
) -> None:
    """``extra="allow"`` keeps the typo through ``set_env`` — erasing it would switch deletion on silently —
    and the user's stored keys still load."""
    from pflow.core.settings import SettingsManager

    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    path = _settings_file(tmp_path, {section: {"trace_retention_day": 0}, "env": {"API_TOKEN": "s3cret"}})

    manager = SettingsManager()
    assert manager.get_env("API_TOKEN") == "s3cret"
    manager.set_env("OTHER", "x")

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[section]["trace_retention_day"] == 0
    assert saved["env"] == {"API_TOKEN": "s3cret", "OTHER": "x"}
    assert retention_days() is None


def test_the_env_override_is_never_written_to_the_settings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pflow.core.settings import SettingsManager

    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")
    path = _settings_file(tmp_path, {"runtime": {"trace_retention_days": 30}})

    assert retention_days() == 1
    SettingsManager().set_env("KEY", "value")

    assert json.loads(path.read_text(encoding="utf-8"))["runtime"]["trace_retention_days"] == 30


# ── The one call site: a trace finishing its write ────────────────────────────────────────────────────

_GATE = """# Gate

Two steps; the second needs a human approval.

## Steps

### one

First.

- type: shell

```shell command
echo one-value
```

### two

Second, gated.

- type: shell
- approval: required

```shell command
echo two-value
```
"""

_OK = """# Ok

One step.

## Steps

### one

First.

- type: shell

```shell command
echo one-value
```
"""


def _invoke(*args: str | Path) -> Any:
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _workflow(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / f"{name}.pflow.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_real_paused_run_sweeps_and_its_token_still_resumes(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aged = trace(debug, deleted(tmp_path, "w"), 30)
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")

    paused = _invoke(_workflow(tmp_path, "gate", _GATE))

    assert paused.exit_code == 4, paused.output
    assert not aged.exists()
    [own] = [entry for entry in list_traces(debug).traces if entry.paused]
    assert own.path.exists() and paused_marker(own.path).exists()
    assert own.execution_id is not None and own.execution_id in paused.output
    answered = _invoke("resume", own.execution_id, "--approve", "yes")
    assert answered.exit_code == 0, answered.output


def test_a_stream_fault_mid_run_still_sweeps(tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    aged = trace(debug, deleted(tmp_path, "w"), 30)
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")
    flush_line = WorkflowTraceCollector._flush_line

    def full_disk_on_events(self: WorkflowTraceCollector, line: dict[str, Any], *, intern: bool = True) -> None:
        if line.get("kind") != "meta":
            self._disable_streaming(OSError(errno.ENOSPC, "No space left on device"))
            return
        flush_line(self, line, intern=intern)

    monkeypatch.setattr(WorkflowTraceCollector, "_flush_line", full_disk_on_events)
    result = _invoke(_workflow(tmp_path, "ok", _OK))

    assert result.exit_code == 0, result.output
    assert "Workflow trace saved:" not in result.output
    assert not aged.exists()


def test_a_meta_write_on_a_full_disk_sweeps_without_touching_the_workflows_protected_traces(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run leaves a 0-byte file as its workflow's newest name; the sweep walks past it."""
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    workflow = _workflow(tmp_path, "ok", _OK).resolve()  # the identity the run records
    snapshot = trace(debug, str(workflow), 40)
    newest_run = trace(debug, str(workflow), 30, status="failed")
    removable = trace(debug, str(workflow), 35, status="failed")
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")

    def full_disk(self: WorkflowTraceCollector, line: dict[str, Any], *, intern: bool = True) -> None:
        self._disable_streaming(OSError(errno.ENOSPC, "No space left on device"))

    monkeypatch.setattr(WorkflowTraceCollector, "_flush_line", full_disk)
    result = _invoke(workflow)

    assert result.exit_code == 0, result.output
    [zero_byte] = [path for path in debug.iterdir() if path.stat().st_size == 0]
    assert zero_byte.name.startswith(snapshot.name[:24]), "the 0-byte file is the same workflow's newest name"
    assert snapshot.exists() and newest_run.exists()
    assert not removable.exists()


def test_a_sweep_fault_never_changes_the_run_outcome(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> SweepReport:
        raise RuntimeError("sweep bug")

    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")
    monkeypatch.setattr("pflow.runtime.trace_retention.prune_traces", boom)
    result = _invoke(_workflow(tmp_path, "ok", _OK))

    assert result.exit_code == 0, result.output
    [entry] = list_traces(debug).traces
    assert f"Workflow trace saved: {entry.path}" in result.output
    # The sweep runs after the trailer: the run's own trace is complete whatever the sweep does.
    trailer = read_trace_trailer(entry.path)
    assert trailer is not None and trailer["final_status"] == "success"


@pytest.mark.parametrize(
    "command",
    [("report",), ("resume", "list"), ("{workflow}", "--dry-run")],
    ids=["report", "resume-list", "dry-run"],
)
def test_a_read_only_command_never_sweeps(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, command: tuple[str, ...]
) -> None:
    workflow = _workflow(tmp_path, "ok", _OK)
    aged = trace(debug, deleted(tmp_path, "w"), 30)
    complete = trace(debug, str(workflow), 30)
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")

    result = _invoke(*(part.format(workflow=workflow) for part in command))

    assert result.exit_code == 0, result.output
    assert aged.exists() and complete.exists()
    # The same environment DOES sweep on a write — this directory is prunable.
    _invoke(workflow)
    assert not aged.exists()


def test_the_viewer_starting_never_sweeps(tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.testclient import TestClient

    from pflow.ui.server import create_app

    aged = trace(debug, deleted(tmp_path, "w"), 30)
    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "1")

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        assert client.get("/api/runs").status_code == 200

    assert aged.exists()
    assert prune(debug).removed == 1  # the same file IS prunable


@pytest.mark.skipif(not POSIX, reason="the permission check is a no-op on Windows")
def test_a_run_that_sweeps_warns_about_insecure_settings_exactly_once(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The sweep reads the settings file once more per run; the permission warning must still print once."""
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")  # retention on, read from the settings file
    settings = _settings_file(tmp_path, {"env": {"MY_SECRET": "s3cret"}})
    settings.chmod(0o644)
    aged = trace(debug, deleted(tmp_path, "w"), 30)

    with caplog.at_level(logging.WARNING):
        result = _invoke(_workflow(tmp_path, "ok", _OK))

    assert result.exit_code == 0, result.output
    assert not aged.exists(), "the sweep ran and read the settings file"
    insecure = [record for record in caplog.records if "insecure permissions" in record.getMessage()]
    assert len(insecure) == 1, [record.getMessage() for record in insecure]


@pytest.mark.parametrize("injected", [True, False], ids=["run-after-startup-injection", "injection-skipped"])
def test_settings_show_and_a_run_resolve_the_same_window(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, injected: bool
) -> None:
    """A typo'd file key beside a stored exact override of 3: a run sees the override (startup injection
    exports it, or retention reads it from settings.env) and `settings show` must say the same — 3 days —
    never "removes no trace" while the run deletes."""
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    _settings_file(tmp_path, {"runtime": {"trace_retension_days": 0}, "env": {"PFLOW_TRACE_RETENTION_DAYS": "3"}})
    aged = trace(debug, deleted(tmp_path, "w"), 5)  # older than 3 days, younger than the default 14

    shown = CliRunner().invoke(cli, ["settings", "show"])
    assert shown.exit_code == 0, shown.output
    assert "Trace retention in effect: 3 days" in shown.output

    if injected:
        monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", "3")  # what settings-env injection does at run start
    result = _invoke(_workflow(tmp_path, "ok", _OK))
    assert result.exit_code == 0, result.output
    assert not aged.exists(), "the run applied the same 3-day window show reported"


def test_a_run_over_a_broken_settings_file_says_so_exactly_once(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Every settings load of a run fails the same way: "Failed to load settings" prints once (it printed once
    per load), and the sweep still refuses to prune."""
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    (tmp_path / ".pflow" / "settings.json").write_text("{not json", encoding="utf-8")
    aged = trace(debug, deleted(tmp_path, "w"), 30)

    with caplog.at_level(logging.WARNING):
        result = _invoke(_workflow(tmp_path, "ok", _OK))

    assert result.exit_code == 0, result.output
    assert aged.exists()
    failed = [record for record in caplog.records if "Failed to load settings" in record.getMessage()]
    assert len(failed) == 1, [record.getMessage() for record in failed]


# ── A writer finishing between the listing and the unlink ────────────────────────────────────────────


def _finalize(path: Path, *, status: str) -> None:
    """What the collector's ``finalize`` does to a trace: the marker first (a pause), then the trailer."""
    if status == "paused":
        paused_marker(path).touch()
    trailer: dict[str, Any] = {"kind": "run.complete", "final_status": status, "nodes_executed": 1}
    if status == "paused":
        trailer.update(paused_node_id="gated", gate_request=_APPROVAL)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(trailer) + "\n")


@contextmanager
def finished_before_the_probe(
    monkeypatch: pytest.MonkeyPatch, running: Path, finish: Callable[[], None] | None
) -> Iterator[None]:
    """The writer of ``running`` holds its lock (POSIX) through the listing and the classification, then —
    just before the sweep's removal probe opens it — ``finish`` runs and the lock is released: the
    deterministic version of a run that finalizes mid-sweep. ``finish=None``: the writer dies unfinished."""
    import pflow.runtime.trace_retention as retention

    real_probe = retention.read_trace_meta_and_lock_strict
    with ExitStack() as stack:
        release = stack.enter_context(ExitStack())
        if POSIX:
            release.enter_context(held_lock(running))

        def probe(path: Path) -> tuple[dict[str, Any] | None, bool | None]:
            if path == running:
                if finish is not None:
                    finish()
                release.close()  # the writer closed its handle
            return real_probe(path)

        monkeypatch.setattr(retention, "read_trace_meta_and_lock_strict", probe)
        yield


@pytest.mark.parametrize("finishes", [True, False], ids=["finalizes-paused", "dies-unfinished"])
def test_a_trace_that_finalizes_paused_after_the_listing_is_kept(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, finishes: bool
) -> None:
    """Listed with no marker; becomes an answerable pause before the unlink. The newer run is the workflow's
    newest run and Snapshot, so only the pause could keep it."""
    workflow = present(tmp_path, "w")
    running = trace(debug, workflow, 40, status="incomplete", events=[_event("prep")], finished=False)
    trace(debug, workflow, 30)

    with finished_before_the_probe(
        monkeypatch, running, (lambda: _finalize(running, status="paused")) if finishes else None
    ):
        prune(debug)

    if finishes:
        assert running.exists() and paused_marker(running).exists()
        assert [run.path for run in list_paused_runs(debug).runs] == [running]
    else:
        assert not running.exists(), "the control: an unfinished trace whose writer died IS removed"


@pytest.mark.parametrize("finishes", [True, False], ids=["finalizes-success", "dies-unfinished"])
def test_a_trace_that_finalizes_as_the_newest_snapshot_after_its_tail_read_is_kept(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, finishes: bool
) -> None:
    """The Snapshot walk read this trace's tail while it ran (no trailer) and picked an older success; it then
    finishes successful — the workflow's real Snapshot — before the unlink."""
    workflow = present(tmp_path, "w")
    older_snapshot = trace(debug, workflow, 50)
    running = trace(debug, workflow, 40, status="incomplete", finished=False)
    trace(debug, workflow, 30, status="failed")

    with finished_before_the_probe(
        monkeypatch, running, (lambda: _finalize(running, status="success")) if finishes else None
    ):
        prune(debug)

    assert older_snapshot.exists()
    assert running.exists() is finishes
    if finishes:
        loaded = load_full_run_events(workflow, debug_dir=debug)
        assert loaded is not None and loaded[0] == load_trace_file(running)["nodes"]


@pytest.mark.parametrize("finishes", [True, False], ids=["finalizes-between-attempts", "stays-unfinished"])
def test_a_windows_retry_rechecks_a_trace_that_finalized_meanwhile(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, finishes: bool
) -> None:
    """Windows has no lock probe; the writer's open handle fails the first unlink. If it finalizes Paused
    before the retry, the retry must not delete it."""
    workflow = present(tmp_path, "w")
    running = trace(debug, workflow, 40, status="incomplete", events=[_event("prep")], finished=False)
    trace(debug, workflow, 30)
    real_unlink = Path.unlink
    attempts: list[Path] = []

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self == running and not attempts:
            attempts.append(self)
            if finishes:
                _finalize(running, status="paused")
            error = PermissionError(errno.EACCES, "The process cannot access the file", str(self))
            error.winerror = 32  # type: ignore[attr-defined]  # set by Windows only; the sweep reads it
            raise error
        real_unlink(self, missing_ok=missing_ok)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "unlink", unlink)
        patched.setattr("pflow.runtime.trace_retention._WINDOWS_UNLINK_RETRY_DELAY", 0)
        prune(debug)

    assert attempts == [running]
    assert running.exists() is finishes


def test_a_pause_listed_between_its_marker_and_its_trailer_is_kept(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer is inside ``finalize``: the marker is written, the trailer not yet, so the pause rule reads
    "not a pause". With no lock to probe (Windows) the writer's open handle fails the first unlink; the
    trailer lands before the retry — an answerable pause, kept. (On POSIX the held lock keeps it: rule 5.)"""
    import pflow.runtime.trace_retention as retention

    workflow = present(tmp_path, "w")
    running = trace(debug, workflow, 40, status="incomplete", events=[_event("prep")], finished=False)
    paused_marker(running).touch()
    trace(debug, workflow, 30)
    real_probe = retention.read_trace_meta_and_lock_strict
    real_unlink = Path.unlink

    def no_lock_probe(path: Path) -> tuple[dict[str, Any] | None, bool | None]:
        return real_probe(path)[0], None  # what Windows reports

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self == running and running.read_text(encoding="utf-8").count("run.complete") == 0:
            with open(running, "a", encoding="utf-8") as handle:  # the writer's trailer, then its close
                handle.write(
                    json.dumps({
                        "kind": "run.complete",
                        "final_status": "paused",
                        "nodes_executed": 1,
                        "paused_node_id": "gated",
                        "gate_request": _APPROVAL,
                    })
                    + "\n"
                )
            error = PermissionError(errno.EACCES, "The process cannot access the file", str(self))
            error.winerror = 32  # type: ignore[attr-defined]  # set by Windows only; the sweep reads it
            raise error
        real_unlink(self, missing_ok=missing_ok)

    with monkeypatch.context() as patched:
        patched.setattr(retention, "read_trace_meta_and_lock_strict", no_lock_probe)
        patched.setattr(Path, "unlink", unlink)
        patched.setattr(retention, "_WINDOWS_UNLINK_RETRY_DELAY", 0)
        prune(debug)

    assert running.exists() and paused_marker(running).exists()
    assert [run.path for run in list_paused_runs(debug).runs] == [running]


# ── A settings file that cannot be read never reads as "absent" ──────────────────────────────────────


def test_a_stat_fault_on_the_settings_file_still_honours_its_opt_out(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Path.exists()`` reads a stat fault as "no file" on Python 3.14 — which meant defaults, i.e. 14 days,
    over a file that says 0. The load opens the file instead; only a missing file means defaults."""
    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    settings = _settings_file(tmp_path, {"runtime": {"trace_retention_days": 0}})
    aged = trace(debug, deleted(tmp_path, "w"), 400)
    real_stat = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if str(path) == str(settings):
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(os, "stat", stat)
        assert retention_days() == 0
        sweep_after_write(debug)

    assert aged.exists()


def test_a_settings_file_that_cannot_be_opened_prunes_nothing_and_is_never_overwritten(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from pflow.core.settings import SettingsManager
    from pflow.core.user_errors import UserFriendlyError

    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    settings = _settings_file(tmp_path, {"runtime": {"trace_retention_days": 0}, "env": {"K": "v"}})
    original = settings.read_bytes()
    aged = trace(debug, deleted(tmp_path, "w"), 400)

    with faulted_opens(monkeypatch, settings, lambda: PermissionError(errno.EACCES, "Permission denied")):
        with caplog.at_level(logging.WARNING):
            sweep_after_write(debug)
        manager = SettingsManager()
        manager.load()
        assert manager.load_error is not None and "Permission denied" in manager.load_error
        with pytest.raises(UserFriendlyError):
            manager.set_env("NEW", "x")

    assert aged.exists()
    assert settings.read_bytes() == original
    warnings = [record.getMessage() for record in caplog.records if record.name == "pflow.runtime.trace_retention"]
    assert len(warnings) == 1 and "could not be loaded" in warnings[0], warnings


@pytest.mark.parametrize("link", [True, False], ids=["dangling-symlink", "no-file-control"])
def test_a_settings_link_whose_target_is_unavailable_is_not_an_absent_file(
    tmp_path: Path, debug: Path, monkeypatch: pytest.MonkeyPatch, link: bool
) -> None:
    """``settings.json`` linked to a file on a volume that is not mounted: that is settings unavailable, not
    settings absent — no default 14 days, no save over the link. The control: genuinely no file → defaults."""
    from pflow.core.settings import SettingsManager
    from pflow.core.user_errors import UserFriendlyError

    monkeypatch.delenv("PFLOW_TRACE_RETENTION_DAYS")
    settings = tmp_path / ".pflow" / "settings.json"
    if link:
        settings.symlink_to(tmp_path / "unmounted-volume" / "settings.json")
    aged = trace(debug, deleted(tmp_path, "w"), 400)

    sweep_after_write(debug)
    manager = SettingsManager()
    manager.load()

    if link:
        assert aged.exists() and manager.load_error is not None
        with pytest.raises(UserFriendlyError):
            manager.set_env("NEW", "x")
        assert settings.is_symlink()
    else:
        assert not aged.exists() and manager.load_error is None
        manager.set_env("NEW", "x")
        assert settings.is_file()


def test_a_workflow_link_whose_target_is_unavailable_keeps_its_group(tmp_path: Path, debug: Path) -> None:
    """A pending pause of a workflow reached through a link to an unmounted volume is not a deleted workflow:
    its group is kept (and reported), not treated as absent. The control: a truly deleted workflow's pause goes."""
    linked = tmp_path / "workflows" / "linked.pflow.md"
    linked.parent.mkdir()
    linked.symlink_to(tmp_path / "unmounted-volume" / "wf.pflow.md")
    pause = trace(debug, str(linked), 40, status="paused")
    gone_pause = trace(debug, deleted(tmp_path, "w"), 40, status="paused")

    report = prune(debug)

    assert pause.exists() and paused_marker(pause).exists()
    assert not gone_pause.exists()
    assert report.unchecked_workflows == (str(linked),)


@pytest.mark.parametrize("fault_at", ["marker-lstat", "trailer-open"])
def test_a_recheck_fault_keeps_the_trace_and_is_reported(
    tmp_path: Path,
    debug: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fault_at: str,
) -> None:
    """The pre-unlink re-check cannot read the trace: kept, counted unreadable with its path, one warning."""
    import pflow.runtime.trace_retention as retention

    workflow = present(tmp_path, "w")
    unfinished = trace(debug, workflow, 40, status="incomplete", finished=False)  # its tail read records it
    trace(debug, workflow, 50)  # the Snapshot behind it, so the walk reads the unfinished trace first
    trace(debug, workflow, 30, status="failed")
    control = trace(debug, deleted(tmp_path, "other"), 30)
    marker = paused_marker(unfinished)
    real_lstat = os.lstat
    real_remove = retention._Sweep._remove

    def lstat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if str(path) == str(marker):
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real_lstat(path, *args, **kwargs)

    def remove(self: Any, entry: Any) -> str:
        if entry.path != unfinished:
            return real_remove(self, entry)
        with monkeypatch.context() as patched:  # the fault exists only at the re-check
            if fault_at == "marker-lstat":
                patched.setattr(os, "lstat", lstat)
            else:
                fault_opens(patched, unfinished, emfile)
            return real_remove(self, entry)

    monkeypatch.setenv("PFLOW_TRACE_RETENTION_DAYS", str(WINDOW))
    monkeypatch.setattr(retention._Sweep, "_remove", remove)
    with caplog.at_level(logging.WARNING):
        sweep_after_write(debug)

    assert unfinished.exists() and not control.exists()
    warnings = [record.getMessage() for record in caplog.records if record.name == "pflow.runtime.trace_retention"]
    assert len(warnings) == 1 and "kept 1 unreadable trace(s)" in warnings[0] and str(unfinished) in warnings[0]
