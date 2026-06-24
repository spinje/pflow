"""Task 173 — RunTailer (the server-side live-overlay observer). Pure-piece unit tests, no event loop:
discovery PREFERS a live run over a finished one (deep-review R2), the raw BYTE buffer never loses a
multibyte char split across a poll read (R4), a poll's deltas coalesce into one batch + last-wins by id,
and run.complete becomes the banner (deltas flushed first)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pflow.ui.run_tailer import RunTailer, discover_live_trace


def _write_trace(path: Path, workflow_path: str, *, complete: bool, only_node: str | None = None) -> None:
    meta: dict = {"kind": "meta", "pflow_trace": "jsonl/1", "workflow_path": workflow_path, "execution_id": "x"}
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
        lines.append({"kind": "run.complete", "final_status": "success", "nodes_executed": 1})
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
