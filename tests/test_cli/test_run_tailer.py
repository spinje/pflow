"""Task 173 — RunTailer (the server-side live-overlay observer). Pure-piece unit tests, no event loop:
discovery PREFERS a live run over a finished one (deep-review R2), the raw BYTE buffer never loses a
multibyte char split across a poll read (R4), a poll's deltas coalesce into one batch + last-wins by id,
and run.complete becomes the banner (deltas flushed first)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from pflow.ui.run_tailer import RunTailer, discover_live_trace, read_run_status, scan_traces


def _write_trace(
    path: Path,
    workflow_path: str,
    *,
    complete: bool,
    only_node: str | None = None,
    final_status: str = "success",
    execution_id: str = "x",
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


def test_discover_prefers_live_over_finished(tmp_path):
    """R2: a just-finished run (newer mtime) must NOT shadow a still-streaming one. Eager-meta makes both
    discoverable, so newest-by-mtime alone is wrong — prefer the file with no run.complete."""
    wf = str(tmp_path / "wf.pflow.md")
    debug = tmp_path / "debug"
    debug.mkdir()
    finished = debug / "workflow-trace-aaa-wf-20260101-000000-000001.json"
    live = debug / "workflow-trace-aaa-wf-20260101-000000-000002.json"
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
    older = debug / "workflow-trace-aaa-wf-20260101-000000-000001.json"
    newer = debug / "workflow-trace-aaa-wf-20260101-000000-000002.json"
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
    full = debug / "workflow-trace-aaa-wf-20260101-000000-000001.json"
    only = debug / "workflow-trace-aaa-wf-20260101-000000-000002.json"
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
    full = debug / "workflow-trace-aaa-wf-20260101-000000-000001.json"
    only = debug / "workflow-trace-aaa-wf-20260101-000000-000002.json"
    _write_trace(full, wf, complete=True, final_status="success")
    _write_trace(only, wf, complete=True, final_status="success", only_node="b")
    cands = scan_traces(wf, debug_dir=debug)
    by_only = {c["meta"].get("only_node"): c for c in cands}
    assert set(by_only) == {None, "b"}, "the shared scanner must NOT drop the --only trace (policy is the caller's)"
    assert by_only["b"]["complete"] is True and by_only["b"]["final_status"] == "success"
    # The live-overlay CALLER applies the --only exclude → returns the full run, never the --only one.
    assert discover_live_trace(wf, debug_dir=debug) == full


def test_discover_returns_none_for_unmatched_workflow(tmp_path):
    debug = tmp_path / "debug"
    debug.mkdir()
    _write_trace(debug / "workflow-trace-aaa-other-20260101-000000-000001.json", "/other.pflow.md", complete=True)
    assert discover_live_trace("/nope.pflow.md", debug_dir=debug) is None


def _bytes(*lines: dict) -> bytes:
    return ("\n".join(json.dumps(line) for line in lines) + "\n").encode("utf-8")


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
    full = debug / "workflow-trace-aaa-wf-20260101-000000-000001.json"
    only = debug / "workflow-trace-aaa-wf-20260101-000000-000002.json"
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
