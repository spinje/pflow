"""Live run tailer — the server-side observer half of the execution overlay (Task 173, ADR-0008).

The UI **observes** runs; it never hosts them. A run (agent / CLI / UI-spawned) streams its JSONL trace
to ``~/.pflow/debug`` regardless of whether the UI is up. This tailer discovers the newest trace for a
watched workflow and follows it, pushing one run-event per node transition onto the SSE hub so the canvas
can light nodes ``running`` → ``success``/``cached``/``failed`` and show a run banner.

Three traps this honors (pinned by ``tests/test_runtime/test_emit_time_trace.py``):
- **Read RAW lines, never ``load_trace_file``** — the post-hoc reader STRIPS ``ancestor_path``/``port``,
  the exact keys the overlay joins on. We parse each line with ``json.loads`` and read them off the raw dict.
- **A truncated final line is NORMAL** (the file is being appended to) — only complete, ``\\n``-terminated
  lines are parsed; the remainder is carried to the next poll.
- **Key on ``id``, last-wins** — a ``node.start`` and the node's completion ``event`` share one ``id``; a
  routing dead-end re-flushes the same ``id`` with a corrected status. The state map is keyed on ``id`` so
  a repeat is an UPDATE, never a duplicate node.

v1 liveness is L1 (per ``node.start`` / completion). Discovery re-runs each poll so a run launched AFTER
the viewer opened is picked up; a switch to a newer file resets state and emits ``run-reset``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_POLL_S = 0.25  # poll cadence; node-paced events make this comfortably fast for a local viewer


def _debug_dir() -> Path:
    return Path.home() / ".pflow" / "debug"


def _same_path(a: str | None, b: str | None) -> bool:
    """Compare two workflow paths tolerantly (the producer's recorded path vs the UI's resolved key)."""
    if not a or not b:
        return False
    if a == b:
        return True
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _read_meta(path: Path) -> dict[str, Any] | None:
    """Read just the first (``meta``) line of a trace — cheap identity probe, tolerant of a growing file."""
    try:
        with open(path, encoding="utf-8") as handle:
            first = handle.readline()
    except OSError:
        return None
    try:
        line = json.loads(first)
    except ValueError:
        return None
    return line if isinstance(line, dict) and line.get("kind") == "meta" else None


def _has_run_complete(path: Path) -> bool:
    """True if the trace's LAST non-empty line is a ``run.complete`` trailer — i.e. the run FINISHED.

    Reads only a bounded tail (``run.complete`` is the small final line) so a multi-MB trace isn't
    loaded to answer "is this run still live?". A truncated/partial final line (a run mid-flush) doesn't
    parse → reported NOT complete (live), which is the safe direction."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            tail = handle.read()
    except OSError:
        return False
    for raw in reversed(tail.split(b"\n")):
        if raw.strip():
            try:
                return isinstance(json.loads(raw), dict) and json.loads(raw).get("kind") == "run.complete"
            except ValueError:
                return False  # last line is a partial flush → run is still live
    return False


def discover_live_trace(workflow_key: str, debug_dir: Path | None = None) -> Path | None:
    """The trace this workflow's overlay should follow, or ``None`` if no run exists.

    Matches on the recorded ``meta.workflow_path`` (robust to filename-hash details / path
    normalization). PREFERS a LIVE run (has ``meta``, NO ``run.complete``) over a finished one, falling
    back to the newest finished trace (for replay) only when none is live. Newest-by-mtime alone is
    WRONG: eager-``meta`` (Task 173 A1) makes every run discoverable from t=0, so a just-finished run can
    have a newer mtime than a still-streaming concurrent run and would shadow it (deep-review R2)."""
    directory = debug_dir or _debug_dir()
    try:
        candidates = sorted(directory.glob("workflow-trace-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    matching = [p for p in candidates if _same_path((_read_meta(p) or {}).get("workflow_path"), workflow_key)]
    if not matching:
        return None
    # Prefer a live run (no run.complete) — newest-first — so a freshly-finished run never shadows a
    # still-streaming one; else fall back to the newest finished run (replay-a-finished-run).
    for path in matching:
        if not _has_run_complete(path):
            return path
    return matching[0]


class RunTailer:
    """Follows the newest trace for one workflow_key and broadcasts run-events to the SSE hub.

    One tailer per watched workflow_key (started on first viewer subscribe, stopped on last unsubscribe).
    ``snapshot()`` lets a newly-subscribed viewer catch up to the current state without replaying the file
    (and bounds the per-connection queue — replaying N lines of a long run could overflow it).
    """

    def __init__(self, workflow_key: str, broadcast: Callable[[str, dict[str, Any]], Any]) -> None:
        self._key = workflow_key
        self._broadcast = broadcast
        self._current: Path | None = None
        self._offset = 0
        self._buf = b""  # RAW byte buffer (deep-review R4): decoding before the line boundary would lose
        self._blob_map: dict[str, str] = {}  # a multibyte char split across a poll read and never recover it
        self._state: dict[Any, dict[str, Any]] = {}  # id -> latest run-event (last-wins)
        self._run: dict[str, Any] | None = None  # the run-complete message, once seen

    def snapshot(self) -> dict[str, Any]:
        """The current run state for a newly-subscribed viewer: all known node states + the run banner.
        Read on the event loop; ``_state``/``_run`` are mutated only on the loop (in ``_consume``/``_switch``)
        — never in the to_thread file-read — so there is no concurrent-mutation race here (deep-review R3)."""
        return {"type": "run-snapshot", "nodes": list(self._state.values()), "run": self._run}

    async def run(self) -> None:
        """Poll loop. Blocking filesystem I/O (discover, read) runs via ``asyncio.to_thread`` so it never
        stalls the event loop (the hub's SSE sends / keepalives / disconnect-cleanup share it — same rule
        ``command()`` follows; deep-review R3). PARSING + state mutation + broadcast stay ON the loop, so
        ``snapshot()`` never races a concurrent mutation. Robust: one bad poll logs and the loop continues."""
        while True:
            try:
                path = await asyncio.to_thread(discover_live_trace, self._key)
                if path is not None:
                    if path != self._current:
                        self._switch(path)  # loop: reset state
                        self._broadcast(self._key, {"type": "run-reset"})  # loop: tell viewers to clear
                    data = await asyncio.to_thread(self._read_bytes, path)  # off-loop I/O
                    for message in self._consume(data):  # loop: parse + mutate state
                        self._broadcast(self._key, message)
            except Exception:
                logger.debug("run tailer poll failed for %s", self._key, exc_info=True)
            await asyncio.sleep(_POLL_S)

    def _switch(self, path: Path) -> None:
        """Follow a newer run: reset all per-file state (on the loop). The caller emits ``run-reset``."""
        self._current = path
        self._offset = 0
        self._buf = b""
        self._blob_map.clear()
        self._state.clear()
        self._run = None

    def _read_bytes(self, path: Path) -> bytes:
        """Read newly-appended bytes from the current offset — BLOCKING I/O, run via ``asyncio.to_thread``.
        Touches only ``self._offset`` (and only here, serialized by the poll loop's ``await``), so it never
        races the loop-owned ``_state``/``_buf``."""
        try:
            with open(path, "rb") as handle:
                handle.seek(self._offset)
                data = handle.read()
                self._offset += len(data)
            return data
        except OSError:
            return b""

    def _consume(self, data: bytes) -> list[dict[str, Any]]:
        """Parse newly-read bytes into broadcast messages — ON the loop (mutates ``_buf``/``_blob_map``/
        ``_state``/``_run``). Splits on the BYTE boundary and decodes only COMPLETE lines (no split-multibyte
        loss). Coalesces a poll's node deltas into ONE ``run-events`` message (a fast run could otherwise
        exceed the hub's 64/conn queue and silently evict the viewer); ``run.complete`` is its own banner."""
        if not data:
            return []
        self._buf += data
        *complete, self._buf = self._buf.split(b"\n")  # trailing element = incomplete remainder (bytes)
        out: list[dict[str, Any]] = []
        deltas: list[dict[str, Any]] = []
        for raw in complete:
            if not raw.strip():
                continue
            result = self._handle(raw.decode("utf-8", errors="replace"))  # complete line → no split multibyte
            if result is None:
                continue
            tag, payload = result
            if tag == "delta":
                deltas.append(payload)
            elif tag == "complete":
                if deltas:  # flush pending node states BEFORE the banner so the canvas is final first
                    out.append({"type": "run-events", "events": deltas})
                    deltas = []
                out.append(payload)
        if deltas:
            out.append({"type": "run-events", "events": deltas})
        return out

    def _handle(self, raw: str) -> tuple[str, dict[str, Any]] | None:
        """Apply one raw line to state; return ``("delta", run_event)`` to batch, ``("complete", banner)``,
        or ``None`` (a blob accumulates silently; a malformed line is skipped — never crash the tail)."""
        try:
            line = json.loads(raw)
        except ValueError:
            return None  # a complete-but-malformed line: skip
        if not isinstance(line, dict):
            return None
        kind = line.get("kind")
        if kind == "blob":
            md5, value = line.get("md5"), line.get("value")
            if isinstance(md5, str) and isinstance(value, str):
                self._blob_map[md5] = value
            return None
        if kind in ("node.start", "event"):
            delta = _run_event(line)
            self._state[line.get("id")] = delta  # last-wins by id (start→done, dead-end re-flush)
            return ("delta", delta)
        if kind == "run.complete":
            self._run = {"type": "run-complete", **{k: v for k, v in line.items() if k != "kind"}}
            return ("complete", self._run)
        return None


def _run_event(line: dict[str, Any]) -> dict[str, Any]:
    """Project a raw ``node.start``/``event`` line to the lightweight run-event the canvas joins on.

    Carries only the structural join key + status (+ cheap cost/duration) — NOT ``node_output`` (which
    may carry large/blob payloads) and NOT the raw ``node_type`` (a Python class name the frontend must
    not surface to agents; the canvas already knows each node's kind from the static graph it joins onto).
    """
    return {
        "type": "run-event",
        "id": line.get("id"),
        "ref": {
            "node_id": line.get("node_id"),
            "ancestor_path": line.get("ancestor_path") or [],
            "port": line.get("port"),
        },
        "status": line.get("status"),
        "duration_ms": line.get("duration_ms"),
        "cost_usd": (line.get("llm_call") or {}).get("cost_usd"),
    }
