"""Task 173 — RunTailer (the server-side live-overlay observer). Pure-piece unit tests, no event loop:
discovery PREFERS a live run over a finished one (deep-review R2), the raw BYTE buffer never loses a
multibyte char split across a poll read (R4), a poll's deltas coalesce into one batch + last-wins by id,
and run.complete becomes the banner (deltas flushed first)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path

import pytest

from pflow.core.workflow_id import workflow_content_hash
from pflow.execution import WorkflowRunner
from pflow.execution.result import RunnerConfig
from pflow.execution.workflow_resolver import resolve_workflow
from pflow.runtime.workflow_trace import format_trace_filename
from pflow.ui.run_tailer import RunTailer, discover_live_trace, is_trace_locked, read_run_status, scan_traces

# Exact-liveness (flock) tests are Unix-only — `fcntl` doesn't exist on Windows (the producer + probe
# degrade to a heuristic there; that path isn't what these pin).
_unix_only = pytest.mark.skipif(sys.platform == "win32", reason="advisory-lock liveness needs fcntl (Unix)")


def _write_trace(
    path: Path,
    workflow_path: str,
    *,
    complete: bool,
    only_node: str | None = None,
    final_status: str = "success",
    execution_id: str = "x",
    content_hash: str | None = None,
) -> None:
    # Synthetic, but the CONSUMED keys mirror the producer (meta ← workflow_trace.py `_meta_fields`,
    # run.complete.final_status ← `_aggregates`, node.start/event join keys ← `_emit_node_start`). The join
    # keys are pinned against a real collector in tests/test_runtime/test_emit_time_trace.py — if the
    # producer shape drifts there, this stays green while the tailer breaks (tests/CLAUDE.md pitfall #19).
    meta: dict = {
        "kind": "meta",
        "pflow_trace": "jsonl/1",
        "workflow_path": workflow_path,
        "execution_id": execution_id,
    }
    if only_node is not None:
        meta["only_node"] = only_node
    if content_hash is not None:
        meta["content_hash"] = content_hash
    lines: list[dict] = [
        meta,
        {
            "kind": "node.start",
            "node_id": "a",
            "id": 0,
            "seq": 0,
            "ancestor_path": [],
            "port": None,
            "status": "running",
        },
    ]
    if complete:
        lines.append({
            "kind": "event",
            "node_id": "a",
            "id": 0,
            "seq": 0,
            "ancestor_path": [],
            "port": None,
            "status": "success",
        })
        lines.append({"kind": "run.complete", "final_status": final_status, "nodes_executed": 1})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _tp(debug: Path, workflow_path: str, ts: str, *, name: str = "wf") -> Path:
    """A trace path named EXACTLY as the producer would (via the real format_trace_filename) — so the
    discovery tests exercise the true workflow-hash prefix that the hash-scoped scan_traces globs on, and
    fail loudly if the producer/consumer hash ever drifts. ``ts`` orders files when a test sets mtime."""
    return debug / format_trace_filename(workflow_path, name, ts)


def test_discover_prefers_live_over_finished(tmp_path):
    """R2: a just-finished run (newer mtime) must NOT shadow a still-streaming one. Eager-meta makes both
    discoverable, so newest-by-mtime alone is wrong — prefer the file with no run.complete."""
    wf = str(tmp_path / "wf.pflow.md")
    debug = tmp_path / "debug"
    debug.mkdir()
    finished = _tp(debug, wf, "20260101-000000-000001")
    live = _tp(debug, wf, "20260101-000000-000002")
    _write_trace(finished, wf, complete=True)
    _write_trace(live, wf, complete=False)
    os.utime(live, (1000, 1000))  # live is OLDER by mtime…
    os.utime(finished, (2000, 2000))  # …finished is newer — newest-by-mtime would wrongly pick it
    assert discover_live_trace(wf, debug_dir=debug) == live


def test_discover_falls_back_to_newest_finished_when_none_live(tmp_path):
    """No live run → return the newest FINISHED trace (replay-a-finished-run)."""
    wf = str(tmp_path / "wf.pflow.md")
    debug = tmp_path / "debug"
    debug.mkdir()
    older = _tp(debug, wf, "20260101-000000-000001")
    newer = _tp(debug, wf, "20260101-000000-000002")
    _write_trace(older, wf, complete=True)
    _write_trace(newer, wf, complete=True)
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    assert discover_live_trace(wf, debug_dir=debug) == newer


def test_discover_excludes_only_node_traces(tmp_path):
    """An ``--only`` run records ONLY its target, so it must NOT shadow the last full run in the overlay
    (consistent with ``_iter_workflow_traces``). Discovery returns the FULL run even though the ``--only``
    trace is newer by mtime — else the user iterating with ``--only`` sees a partial, mostly-pending canvas
    instead of their last full run."""
    wf = str(tmp_path / "wf.pflow.md")
    debug = tmp_path / "debug"
    debug.mkdir()
    full = _tp(debug, wf, "20260101-000000-000001")
    only = _tp(debug, wf, "20260101-000000-000002")
    _write_trace(full, wf, complete=True)
    _write_trace(only, wf, complete=True, only_node="b")
    os.utime(full, (1000, 1000))
    os.utime(only, (2000, 2000))  # the --only trace is NEWER — would win without the only_node exclusion
    assert discover_live_trace(wf, debug_dir=debug) == full


def test_read_run_status_extracts_final_status(tmp_path):
    """DR-2: read_run_status returns (complete, final_status) from the cheap tail — the signal /api/runs
    needs and the bool-only _has_run_complete could not give. A live (no run.complete) trace → (False, None)."""
    wf = str(tmp_path / "wf.pflow.md")
    finished = tmp_path / "workflow-trace-aaa-wf-20260101-000000-000001.json"
    failed = tmp_path / "workflow-trace-aaa-wf-20260101-000000-000002.json"
    live = tmp_path / "workflow-trace-aaa-wf-20260101-000000-000003.json"
    _write_trace(finished, wf, complete=True, final_status="success")
    _write_trace(failed, wf, complete=True, final_status="failed")
    _write_trace(live, wf, complete=False)
    assert read_run_status(finished) == (True, "success")
    assert read_run_status(failed) == (True, "failed")
    assert read_run_status(live) == (False, None)  # no run.complete trailer → live/crashed, status unknown


def test_scan_traces_yields_raw_candidates_keeping_only_policy_in_callers(tmp_path):
    """DR-3: the shared scanner yields RAW candidates with NO --only policy — so history (scan_traces)
    INCLUDES an --only run while the live overlay (discover_live_trace) EXCLUDES it. A future refactor that
    pulls the --only filter (or final_status policy) into the shared scanner fails THIS test loudly."""
    wf = str(tmp_path / "wf.pflow.md")
    debug = tmp_path / "debug"
    debug.mkdir()
    full = _tp(debug, wf, "20260101-000000-000001")
    only = _tp(debug, wf, "20260101-000000-000002")
    _write_trace(full, wf, complete=True, final_status="success")
    _write_trace(only, wf, complete=True, final_status="success", only_node="b")
    cands = scan_traces(wf, debug_dir=debug)
    by_only = {c["meta"].get("only_node"): c for c in cands}
    assert set(by_only) == {None, "b"}, "the shared scanner must NOT drop the --only trace (policy is the caller's)"
    assert by_only["b"]["complete"] is True and by_only["b"]["final_status"] == "success"
    # The live-overlay CALLER applies the --only exclude → returns the full run, never the --only one.
    assert discover_live_trace(wf, debug_dir=debug) == full


def test_scan_traces_caches_unchanged_files(tmp_path, monkeypatch):
    """A repeated scan of an UNCHANGED trace is served from the (mtime,size) cache — no second open+parse.
    Task 173 perf fix: an idle viewer polls 4x/s and must NOT re-open every trace in ~/.pflow/debug."""
    import pflow.ui.run_tailer as rt

    rt._SCAN_CACHE.clear()
    debug = tmp_path / "debug"
    debug.mkdir()
    wf = "/wf.pflow.md"
    _write_trace(_tp(debug, wf, "20260101-000000-000001"), wf, complete=True)

    calls = {"n": 0}
    real_read_meta = rt._read_meta

    def counting_read_meta(path):
        calls["n"] += 1
        return real_read_meta(path)

    monkeypatch.setattr(rt, "_read_meta", counting_read_meta)
    assert len(rt.scan_traces(wf, debug_dir=debug)) == 1
    assert calls["n"] == 1, "the finished trace is opened once to populate the cache"
    assert len(rt.scan_traces(wf, debug_dir=debug)) == 1
    assert calls["n"] == 1, "an unchanged trace is served from cache — not re-opened on the next scan"


def test_scan_traces_rereads_a_grown_file(tmp_path):
    """A live trace that grows (size/mtime change) bypasses the cache, so a finishing run is never served
    stale — the (mtime,size) key catches an append even on a coarse-mtime filesystem."""
    import pflow.ui.run_tailer as rt

    rt._SCAN_CACHE.clear()
    debug = tmp_path / "debug"
    debug.mkdir()
    wf = "/wf.pflow.md"
    path = _tp(debug, wf, "20260101-000000-000001")
    _write_trace(path, wf, complete=False)
    cands = rt.scan_traces(wf, debug_dir=debug)
    assert len(cands) == 1 and cands[0]["complete"] is False

    _write_trace(path, wf, complete=True, final_status="success")  # grows: + event + run.complete lines
    cands = rt.scan_traces(wf, debug_dir=debug)
    assert cands[0]["complete"] is True and cands[0]["final_status"] == "success", (
        "a grown file is re-read, not served stale from the (mtime,size) cache"
    )


def test_scan_traces_caches_unreadable_files(tmp_path, monkeypatch):
    """A file with no valid meta head (a pre-Task-172 single-object trace / junk) is the BULK of a long-lived
    ~/.pflow/debug. Its NEGATIVE verdict is cached on (mtime,size) too, so it's opened once — not re-probed
    every poll. (The real-dir gap the valid-trace fixtures missed; surfaced by cold/warm scan timing.)"""
    import pflow.ui.run_tailer as rt

    rt._SCAN_CACHE.clear()
    debug = tmp_path / "debug"
    debug.mkdir()
    # Glob-matching but NOT a jsonl meta head → _read_meta returns None (an old single-object trace).
    (debug / "workflow-trace-old-20250101-000000-000001.json").write_text(
        '{"old": "single-object trace"}', encoding="utf-8"
    )

    calls = {"n": 0}
    real = rt._read_meta

    def counting(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(rt, "_read_meta", counting)
    assert rt.scan_traces(debug_dir=debug) == []
    assert calls["n"] == 1, "the unreadable file is opened once to cache the negative verdict"
    assert rt.scan_traces(debug_dir=debug) == []
    assert calls["n"] == 1, "the negative verdict is served from cache — not re-opened on the next poll"


def test_discover_returns_none_for_unmatched_workflow(tmp_path):
    debug = tmp_path / "debug"
    debug.mkdir()
    _write_trace(
        _tp(debug, "/other.pflow.md", "20260101-000000-000001", name="other"), "/other.pflow.md", complete=True
    )
    assert discover_live_trace("/nope.pflow.md", debug_dir=debug) is None


def _bytes(*lines: dict) -> bytes:
    return ("\n".join(json.dumps(line) for line in lines) + "\n").encode("utf-8")


def test_scan_traces_is_hash_scoped_to_a_workflow(tmp_path, monkeypatch):
    """The over-scan fix (Task 173): scan_traces(workflow_key) globs ONLY this workflow's hash prefix, so
    another workflow's traces are never even listed or opened — the live overlay stops reading unrelated
    history (1251-file scans → this workflow's handful). A bare scan (no key) still lists everything (the
    dashboard's job)."""
    import pflow.ui.run_tailer as rt

    rt._SCAN_CACHE.clear()
    debug = tmp_path / "debug"
    debug.mkdir()
    wf_a = str(tmp_path / "a.pflow.md")
    wf_b = str(tmp_path / "b.pflow.md")
    _write_trace(_tp(debug, wf_a, "20260101-000000-000001", name="a"), wf_a, complete=True)
    b_path = _tp(debug, wf_b, "20260101-000000-000002", name="b")
    _write_trace(b_path, wf_b, complete=True)

    opened: list[str] = []
    real = rt._read_meta

    def spy(path):
        opened.append(path.name)
        return real(path)

    monkeypatch.setattr(rt, "_read_meta", spy)
    cands = rt.scan_traces(wf_a, debug_dir=debug)
    assert [c["meta"]["workflow_path"] for c in cands] == [wf_a], "scoped scan returns only this workflow"
    assert b_path.name not in opened, "B's trace was never opened — the hash-scoped glob excluded it"

    # A bare scan (the dashboard) still sees BOTH workflows' runs.
    rt._SCAN_CACHE.clear()
    assert {c["meta"]["workflow_path"] for c in rt.scan_traces(debug_dir=debug)} == {wf_a, wf_b}


def test_scan_traces_skips_rescandir_when_dir_unchanged(tmp_path, monkeypatch):
    """The os_scandir hotspot fix (Task 173): a poll over an UNCHANGED directory reuses the cached file list
    instead of re-scandir'ing every entry — so an idle tailer at 4 Hz costs one dir stat, not a full listing
    of a large ~/.pflow/debug. A created/removed trace bumps the dir mtime → the listing refreshes."""
    import pflow.ui.run_tailer as rt

    rt._SCAN_CACHE.clear()
    rt._DIR_LIST_CACHE.clear()
    debug = tmp_path / "debug"
    debug.mkdir()
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(_tp(debug, wf, "20260101-000000-000001"), wf, complete=True)

    globs = {"n": 0}
    real = rt._list_trace_files

    def counting(directory, pattern):
        globs["n"] += 1
        return real(directory, pattern)

    monkeypatch.setattr(rt, "_list_trace_files", counting)
    rt.scan_traces(wf, debug_dir=debug)
    rt.scan_traces(wf, debug_dir=debug)
    assert globs["n"] == 1, "an unchanged directory is scandir'd once, then served from the listing cache"
    os.utime(debug, (9_999, 9_999))  # a created/removed trace would bump the dir mtime
    rt.scan_traces(wf, debug_dir=debug)
    assert globs["n"] == 2, "a changed dir mtime re-scandirs (a run appeared/vanished)"


def test_consume_batches_deltas_and_snapshot_is_last_wins_by_id():
    t = RunTailer("k", lambda _key, _msg: None)
    messages = t._consume(
        _bytes(
            {"kind": "node.start", "node_id": "a", "id": 0, "ancestor_path": [], "port": None, "status": "running"},
            {"kind": "event", "node_id": "a", "id": 0, "ancestor_path": [], "port": None, "status": "success"},
            {"kind": "node.start", "node_id": "b", "id": 1, "ancestor_path": [], "port": None, "status": "running"},
        )
    )
    # One coalesced run-events batch — NOT one message per line (queue-overflow safety).
    assert [m["type"] for m in messages] == ["run-events"]
    assert [e["status"] for e in messages[0]["events"]] == ["running", "success", "running"]
    # Snapshot: last-wins by id → a's running (id 0) is superseded by its success; b stays running (id 1).
    states = {n["ref"]["node_id"]: n["status"] for n in t.snapshot()["nodes"]}
    assert states == {"a": "success", "b": "running"}


def test_run_complete_flushes_pending_deltas_then_banner():
    t = RunTailer("k", lambda _key, _msg: None)
    messages = t._consume(
        _bytes(
            {"kind": "event", "node_id": "a", "id": 0, "ancestor_path": [], "port": None, "status": "success"},
            {"kind": "run.complete", "final_status": "success", "nodes_executed": 1},
        )
    )
    # Pending node states flush BEFORE the banner so the canvas is final before "Run success".
    assert [m["type"] for m in messages] == ["run-events", "run-complete"]
    assert t.snapshot()["run"]["final_status"] == "success"


def test_pinned_resolve_matches_execution_id(tmp_path, monkeypatch):
    """DR-1: a pinned tailer resolves its ``run_id`` to a trace by ``meta.execution_id`` (NOT mtime/--only
    policy). Includes an ``--only`` candidate to prove the pin can resolve one (pinning a labelled --only
    run from history is an explicit choice — the exclude is the live overlay's policy, not the pin's)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    debug = tmp_path / ".pflow" / "debug"
    debug.mkdir(parents=True)
    wf = str(tmp_path / "wf.pflow.md")
    full = _tp(debug, wf, "20260101-000000-000001")
    only = _tp(debug, wf, "20260101-000000-000002")
    _write_trace(full, wf, complete=True, execution_id="run-full")
    _write_trace(only, wf, complete=True, only_node="b", execution_id="run-only")
    assert RunTailer(wf, lambda _k, _m: None, run_id="run-full")._resolve_pinned() == full
    assert RunTailer(wf, lambda _k, _m: None, run_id="run-only")._resolve_pinned() == only  # --only resolvable
    assert RunTailer(wf, lambda _k, _m: None, run_id="ghost")._resolve_pinned() is None


def test_pinned_run_not_found_broadcasts_and_stops(tmp_path, monkeypatch):
    """DR-1: a pinned tailer whose ``run_id`` matches no trace broadcasts an explicit ``run-not-found`` and
    RETURNS (the run() loop terminates — no silent all-pending canvas, no endless re-discovery)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)
    messages: list[dict] = []
    tailer = RunTailer("wf", lambda _k, message: messages.append(message), run_id="ghost")
    asyncio.run(tailer.run())  # terminates on the run-not-found path (does not loop)
    assert messages == [{"type": "run-not-found", "run_id": "ghost"}]


@_unix_only
def test_is_trace_locked_reflects_a_held_advisory_lock(tmp_path):
    """The exact-liveness primitive: `is_trace_locked` is True while a writer holds the flock, False once
    released. (flock conflicts across open-file-descriptions even within one process, so this is testable
    in-process without spawning.)"""
    import fcntl

    path = tmp_path / "workflow-trace-aaa-wf-20260101-000000-000001.json"
    path.write_text("{}\n", encoding="utf-8")
    assert is_trace_locked(path) is False  # nobody holds it
    with open(path, encoding="utf-8") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX)
        assert is_trace_locked(path) is True  # a writer holds it → the run is alive
    assert is_trace_locked(path) is False  # released on close → free again


@_unix_only
@pytest.mark.trace_files
def test_collector_holds_advisory_lock_while_streaming(tmp_path, monkeypatch):
    """The producer holds the flock for the run's lifetime: the trace reads LOCKED while the stream is open
    and FREE after `finalize` closes the handle — so the server's probe (`is_trace_locked`) tells a running
    run from a finished/crashed one exactly."""
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    collector = WorkflowTraceCollector("wf", workflow_path="wf", is_run_scoped=True, stream_to_disk=True)
    collector.record_node_execution("a", "ShellNode", 1.0, True)  # opens the stream + acquires the lock
    assert collector._stream_path is not None
    assert is_trace_locked(collector._stream_path) is True  # held while streaming
    collector.finalize()  # closes the handle → releases the lock
    assert is_trace_locked(collector._stream_path) is False


@_unix_only
def test_tailer_broadcasts_run_stopped_when_incomplete_and_unlocked(tmp_path, monkeypatch):
    """Exact death-detection: an incomplete trace whose writer lock is FREE (the run crashed / was killed)
    makes the tailer broadcast `run-stopped` ONCE — so the canvas flips its dangling `running` nodes to
    `stopped` instead of pulsing blue forever. A finished run (has `run.complete`) never triggers it."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    debug = tmp_path / ".pflow" / "debug"
    debug.mkdir(parents=True)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(_tp(debug, wf, "20260101-000000-000001"), wf, complete=False)  # incomplete, UNLOCKED

    messages: list[dict] = []

    async def scenario() -> None:
        tailer = RunTailer(wf, lambda _k, message: messages.append(message))
        task = asyncio.create_task(tailer.run())
        for _ in range(40):  # poll up to ~0.8s for the run-stopped broadcast (poll cadence is 0.25s)
            if any(m.get("type") == "run-stopped" for m in messages):
                break
            await asyncio.sleep(0.02)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert sum(1 for m in messages if m.get("type") == "run-stopped") == 1, "incomplete + unlocked → run-stopped once"


@_unix_only
def test_check_stopped_does_not_false_fire_on_a_completed_run(tmp_path):
    """Critical race guard (concurrency review): a run that wrote `run.complete` + released its lock in the
    poll's read→probe gap must NOT get a false `run-stopped`. `_check_stopped` re-confirms via
    `read_run_status` (the producer flushes the trailer BEFORE freeing the lock), so an unlocked-but-COMPLETE
    trace broadcasts nothing even though `self._run` is still None (the trailer wasn't consumed yet)."""
    wf = str(tmp_path / "wf.pflow.md")
    path = tmp_path / "workflow-trace-aaa-wf-20260101-000000-000001.json"
    _write_trace(path, wf, complete=True)  # has run.complete on disk; NOT locked (no writer process)
    messages: list[dict] = []
    tailer = RunTailer(wf, lambda _k, message: messages.append(message))
    tailer._current = path
    assert tailer._run is None  # the race: trailer on disk but not yet consumed by this tailer
    asyncio.run(tailer._check_stopped(path))
    assert not any(m["type"] == "run-stopped" for m in messages), "a completed run (lock free) must NOT false-stop"


def test_snapshot_carries_stopped_for_a_late_subscriber():
    """Warning-1 fix (silent-failures review): `run-stopped` is one-shot, so `snapshot()` must carry the
    latched `stopped` flag — else a viewer subscribing AFTER the broadcast (reload / 2nd tab) never learns
    the run died and blue-blinks forever."""
    tailer = RunTailer("k", lambda _k, _m: None)
    assert tailer.snapshot()["stopped"] is False
    tailer._stopped = True
    assert tailer.snapshot()["stopped"] is True


def test_byte_split_multibyte_char_is_not_lost():
    """R4: the tailer buffers RAW BYTES and decodes only complete lines, so a multibyte UTF-8 char split
    across two poll reads survives. The old ``self._buf += data.decode(errors="ignore")`` dropped the
    partial bytes and — since the byte offset advanced past them — never recovered them. (Today's producer
    writes ASCII-only via ``json.dumps`` default ``ensure_ascii=True``, so this guards the tailer's
    robustness against any UTF-8 input rather than a current producer bug — hence ``ensure_ascii=False``
    here to construct genuine multibyte bytes.)"""
    t = RunTailer("k", lambda _key, _msg: None)
    event = {"kind": "event", "node_id": "café", "id": 0, "ancestor_path": [], "port": None, "status": "success"}
    line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
    split = line.index("café".encode()) + 4  # mid-'é' (b"\xc3\xa9"): after 0xc3, before 0xa9
    assert t._consume(line[:split]) == []  # incomplete line → nothing emitted; partial bytes buffered
    messages = t._consume(line[split:])  # completes the line
    assert messages[0]["events"][0]["ref"]["node_id"] == "café"  # reconstructed intact, not lost/corrupted


# --- Task 173 replay version-detection: content_hash compare + the run-stale broadcast/snapshot delivery ---


def _write_wf(path: Path, node_id: str = "greet", *, command: str = "echo hi") -> Path:
    """A one-node shell workflow (real, resolvable) for `_is_stale` to hash via `resolve_workflow`."""
    path.write_text(
        f"# WF\n\nA one-node shell workflow for version detection.\n\n## Steps\n\n"
        f"### {node_id}\n\nEcho a greeting.\n\n- type: shell\n- command: {command}\n",
        encoding="utf-8",
    )
    return path


def _write_declared_defaults_wf(path: Path, node_id: str = "greet") -> Path:
    """A workflow whose declared input gets a DEFAULT filled — the exact case where a future
    `_fill_declared_defaults` regression could pollute the stamped IR. The round-trip test runs this through
    the REAL runner to guard the pristine-IR stamp."""
    path.write_text(
        "# Round Trip\n\nGuards the pristine-IR stamp via a defaulted input.\n\n"
        "## Inputs\n\n### name\n\nThe name to greet.\n\n- type: string\n- default: world\n\n"
        "## Steps\n\n"
        f"### {node_id}\n\nEcho a greeting using the defaulted input.\n\n- type: shell\n- command: echo hi ${{name}}\n",
        encoding="utf-8",
    )
    return path


def test_is_stale_compares_run_hash_to_the_current_file_digest(tmp_path):
    """`_is_stale` is True iff the run's stamped `content_hash` differs from the current file's resolved
    digest. Cannot-verify cases (None hash = old trace; an `ir-hash:` inline key) return False — no banner."""
    wf = _write_wf(tmp_path / "wf.pflow.md")
    digest = workflow_content_hash(resolve_workflow(str(wf)).ir)
    file_tailer = RunTailer(str(wf), lambda _k, _m: None)
    assert file_tailer._is_stale(digest) is False  # same version → not stale
    assert file_tailer._is_stale("deadbeefdeadbeefdeadbeefdeadbeef") is True  # different version → stale
    assert file_tailer._is_stale(None) is False  # old trace, no fingerprint → can't verify
    # An `ir-hash:` inline key short-circuits WITHOUT touching the filesystem (defense-in-depth — never
    # reached via the UI, which 404s ir-hash: before any tailer).
    assert RunTailer("ir-hash:abc123", lambda _k, _m: None)._is_stale("any") is False


def test_is_stale_false_when_the_entry_file_is_deleted(tmp_path):
    """A deleted entry file makes the workflow unrenderable → `/api/graph` owns the 422; `_is_stale` swallows
    the resolve raise and returns False (no misleading overlay to warn about). Pins the blanket-catch."""
    wf = _write_wf(tmp_path / "wf.pflow.md")
    run_hash = workflow_content_hash(resolve_workflow(str(wf)).ir)
    wf.unlink()
    assert RunTailer(str(wf), lambda _k, _m: None)._is_stale(run_hash) is False


def test_is_stale_false_when_a_referenced_file_is_deleted(tmp_path):
    """A deleted *referenced* file (prompt/code) raises `CompilationError` at resolution → caught → not stale
    (same degraded path as a deleted entry file). The graph itself is unrenderable, so `/api/graph` owns it."""
    (tmp_path / "prompt.txt").write_text("Generate a greeting.", encoding="utf-8")
    wf = tmp_path / "wf.pflow.md"
    wf.write_text(
        "# Ref\n\nReferences an external prompt file.\n\n## Steps\n\n"
        "### gen\n\nGenerate from an external prompt.\n\n- type: llm\n- model: anthropic/claude-sonnet-4-5\n"
        "- prompt: ./prompt.txt\n",
        encoding="utf-8",
    )
    run_hash = workflow_content_hash(resolve_workflow(str(wf)).ir)  # resolves the ref while the file exists
    (tmp_path / "prompt.txt").unlink()
    with pytest.raises(Exception):  # noqa: B017 — confirm the catch is actually exercised (documented behavior)
        resolve_workflow(str(wf))
    assert RunTailer(str(wf), lambda _k, _m: None)._is_stale(run_hash) is False


def test_resolve_pinned_latches_stale_version(tmp_path, monkeypatch):
    """`_resolve_pinned` latches `_stale_version` as a side effect: True when the matched run's `content_hash`
    differs from the current file, False when equal, False when the run has no `content_hash`."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    debug = tmp_path / ".pflow" / "debug"
    debug.mkdir(parents=True)
    wf = _write_wf(tmp_path / "wf.pflow.md")
    digest = workflow_content_hash(resolve_workflow(str(wf)).ir)
    _write_trace(
        _tp(debug, str(wf), "20260101-000000-000001"), str(wf), complete=True, execution_id="match", content_hash=digest
    )
    _write_trace(
        _tp(debug, str(wf), "20260101-000000-000002"),
        str(wf),
        complete=True,
        execution_id="stale",
        content_hash="deadbeef",
    )
    _write_trace(
        _tp(debug, str(wf), "20260101-000000-000003"), str(wf), complete=True, execution_id="old"
    )  # no content_hash

    def _latched(run_id: str) -> bool:
        t = RunTailer(str(wf), lambda _k, _m: None, run_id=run_id)
        t._resolve_pinned()
        return t._stale_version

    assert _latched("match") is False
    assert _latched("stale") is True
    assert _latched("old") is False  # old trace (no fingerprint) → can't verify → not stale


def test_snapshot_carries_stale_version_for_a_late_subscriber():
    """`run-stale` is a one-shot broadcast (reaches the present subscriber), so `snapshot()` must carry the
    latched flag for a late subscriber (reload / 2nd tab) — mirrors the `stopped` snapshot field."""
    tailer = RunTailer("k", lambda _k, _m: None)
    assert tailer.snapshot()["stale_version"] is False
    tailer._stale_version = True
    assert tailer.snapshot()["stale_version"] is True


def test_start_pinned_broadcasts_run_stale_only_when_the_version_differs(tmp_path, monkeypatch):
    """The present subscriber's snapshot was taken BEFORE the tailer task ran (stale=False), so a stale run
    must BROADCAST `run-stale` to reach it (snapshot-only would miss it). A matching version broadcasts none."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    debug = tmp_path / ".pflow" / "debug"
    debug.mkdir(parents=True)
    wf = _write_wf(tmp_path / "wf.pflow.md")
    digest = workflow_content_hash(resolve_workflow(str(wf)).ir)
    _write_trace(
        _tp(debug, str(wf), "20260101-000000-000001"),
        str(wf),
        complete=True,
        execution_id="stale",
        content_hash="deadbeef",
    )
    _write_trace(
        _tp(debug, str(wf), "20260101-000000-000002"), str(wf), complete=True, execution_id="fresh", content_hash=digest
    )

    def _messages(run_id: str) -> list[dict]:
        out: list[dict] = []
        tailer = RunTailer(str(wf), lambda _k, message: out.append(message), run_id=run_id)
        assert asyncio.run(tailer._start_pinned()) is True  # file resolved (not run-not-found)
        return out

    assert {"type": "run-stale"} in _messages("stale")
    assert all(m.get("type") != "run-stale" for m in _messages("fresh"))


@pytest.mark.trace_files
def test_round_trip_real_runner_unedited_not_stale_edited_stale(tmp_path, monkeypatch):
    """The KEY consistency pin (drive the REAL runner, not a resolver shortcut): the producer stamp and the
    replay-compare hash the SAME resolved IR, so an UNEDITED file round-trips to an identical digest → not
    stale. Uses a declared-defaults workflow (where `_fill_declared_defaults` could one day pollute the stamp
    — this is what guards the pristine-IR invariant). Editing the file (rename the node) → digests differ →
    stale."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    wf = _write_declared_defaults_wf(tmp_path / "wf.pflow.md", "greet")
    result = WorkflowRunner().run(str(wf), {}, config=RunnerConfig())
    assert result.success
    run_id = result.trace.execution_id

    candidate = next(c for c in scan_traces(str(wf)) if c["meta"].get("execution_id") == run_id)
    assert candidate["meta"]["content_hash"] == workflow_content_hash(resolve_workflow(str(wf)).ir)

    fresh = RunTailer(str(wf), lambda _k, _m: None, run_id=run_id)
    assert fresh._resolve_pinned() == candidate["path"]
    assert fresh._stale_version is False  # unedited → producer stamp == replay digest

    _write_declared_defaults_wf(wf, "greet2")  # rename the node — same trace file, different current digest
    edited = RunTailer(str(wf), lambda _k, _m: None, run_id=run_id)
    assert edited._resolve_pinned() == candidate["path"]  # the trace is still found (filename hash = path)
    assert edited._stale_version is True
