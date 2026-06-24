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
from typing import Any, Callable, TypedDict

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


def read_run_status(path: Path) -> tuple[bool, str | None]:
    """The cheap-tail terminal state of a streamed trace: ``(complete, final_status)`` (deep-review DR-2).

    ``complete`` is True iff the LAST non-empty line is a ``run.complete`` trailer (the run FINISHED);
    ``final_status`` is that trailer's ``final_status`` (``success``/``degraded``/``failed`` — the
    producer's vocabulary), or ``None`` when the run is not complete (still live, or crashed). Reads only a
    bounded 64 KB tail so a multi-MB trace isn't loaded to answer "is this run live?". A truncated/partial
    final line (a run mid-flush) doesn't parse → ``(False, None)`` (live), the safe direction. Supersedes
    the bool-only ``_has_run_complete`` so ``/api/runs`` reports a finished run's status WITHOUT a full
    ``load_trace_file`` parse."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            tail = handle.read()
    except OSError:
        return (False, None)
    for raw in reversed(tail.split(b"\n")):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except ValueError:
            return (False, None)  # last line is a partial flush → run is still live
        if isinstance(line, dict) and line.get("kind") == "run.complete":
            status = line.get("final_status")
            return (True, status if isinstance(status, str) else None)
        return (False, None)  # a complete-but-non-trailer last line → not finished
    return (False, None)


def _has_run_complete(path: Path) -> bool:
    """True iff the run FINISHED — the bool half of ``read_run_status``, kept for ``discover_live_trace``'s
    readable prefer-live loop."""
    return read_run_status(path)[0]


def is_trace_locked(path: Path) -> bool | None:
    """Is this trace file held by a LIVE writer? (Task 173 — exact liveness.)

    The producer holds an advisory ``flock`` on its trace handle for the run's lifetime; the kernel releases
    it on ANY process exit. So a HELD lock = the run's process is alive; a FREE lock + no ``run.complete`` =
    it crashed/was killed. We probe with a SEPARATE fd and ``LOCK_NB`` so we never block, releasing
    immediately if we acquire. Returns ``True`` (alive) / ``False`` (not held) / ``None`` when liveness can't
    be determined — no ``fcntl`` (Windows) or the file can't be opened — so the caller falls back.

    NOTE: detects DEATH, not HANG — a hung-but-alive process still holds the lock (reads ``True``). The
    staleness backstop for that case is deferred to GH #538."""
    try:
        import fcntl
    except ImportError:
        return None  # Windows: no advisory-lock probe → caller falls back to a heuristic
    try:
        with open(path, encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True  # the writer holds it → the run is alive
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # we acquired it → no writer; release + report free
            return False
    except OSError:
        return None  # can't open (gone/unreadable) → unknown; let the caller decide


class TraceCandidate(TypedDict):
    """One raw trace-dir candidate from ``scan_traces`` — the typed contract shared by ``discover_live_trace``
    (live overlay) and ``/api/runs`` (history). ``meta`` is the head line; ``complete``/``final_status`` the
    cheap-tail terminal state; ``mtime`` for liveness/recency. NO policy applied — callers filter."""

    path: Path
    meta: dict[str, Any]
    complete: bool
    final_status: str | None
    mtime: float


def scan_traces(workflow_key: str | None = None, debug_dir: Path | None = None) -> list[TraceCandidate]:
    """The ONE trace-dir scanner (deep-review DR-3): a RAW candidate per trace, newest-first by mtime, with
    NO ``--only`` / ``final_status`` / coherence policy — each CALLER filters its own (mirroring
    ``_iter_workflow_traces``'s "status policy in callers" invariant).

    Each candidate is ``{"path", "meta", "complete", "final_status", "mtime"}`` — ``meta`` the head line
    (identity: ``workflow_path`` / ``execution_id`` / ``workflow_name`` / ``start_time`` / ``only_node``),
    ``complete`` / ``final_status`` the cheap-tail terminal state. With ``workflow_key`` set, keeps only
    traces whose ``meta.workflow_path`` matches it (``_same_path`` — robust to path normalization). Cheap:
    one head-read + one tail-read per file, never a full parse — so the all-runs dashboard stays light.
    ``discover_live_trace`` applies the ``--only``-exclude + prefer-live; ``/api/runs`` labels ``--only`` —
    neither policy lives here. An unreadable trace is skipped (``meta is None``), never fatal (DR-6)."""
    directory = debug_dir or _debug_dir()
    try:
        paths = sorted(directory.glob("workflow-trace-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    out: list[TraceCandidate] = []
    for path in paths:
        meta = _read_meta(path)
        if meta is None:
            continue
        if workflow_key is not None and not _same_path(meta.get("workflow_path"), workflow_key):
            continue
        complete, final_status = read_run_status(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        out.append({"path": path, "meta": meta, "complete": complete, "final_status": final_status, "mtime": mtime})
    return out


def discover_live_trace(workflow_key: str, debug_dir: Path | None = None) -> Path | None:
    """The trace this workflow's overlay should follow, or ``None`` if no run exists.

    Matches on the recorded ``meta.workflow_path`` (robust to filename-hash details / path
    normalization). PREFERS a LIVE run (has ``meta``, NO ``run.complete``) over a finished one, falling
    back to the newest finished trace (for replay) only when none is live. Newest-by-mtime alone is
    WRONG: eager-``meta`` (Task 173 A1) makes every run discoverable from t=0, so a just-finished run can
    have a newer mtime than a still-streaming concurrent run and would shadow it (deep-review R2).

    EXCLUDES ``--only`` traces (``meta.only_node`` set): an ``--only`` run records ONLY its target node,
    so it is not a coherent full-run overlay — following it would leave every other node falsely
    ``pending`` and shadow the user's last full run. Mirrors ``_iter_workflow_traces`` (report /
    analyze-cache), which excludes ``--only`` traces for exactly this reason."""
    # Caller policy over the shared scanner (DR-3): drop --only traces (a partial run, not a coherent
    # overlay), then prefer a live run (no run.complete) newest-first so a just-finished run never shadows
    # a still-streaming one; else the newest finished run (replay-a-finished-run).
    candidates = [c for c in scan_traces(workflow_key, debug_dir) if c["meta"].get("only_node") is None]
    if not candidates:
        return None
    for cand in candidates:
        if not cand["complete"]:
            return cand["path"]
    return candidates[0]["path"]


class RunTailer:
    """Follows the newest trace for one workflow_key and broadcasts run-events to the SSE hub.

    One tailer per watched workflow_key (started on first viewer subscribe, stopped on last unsubscribe).
    ``snapshot()`` lets a newly-subscribed viewer catch up to the current state without replaying the file
    (and bounds the per-connection queue — replaying N lines of a long run could overflow it).
    """

    def __init__(
        self, workflow_key: str, broadcast: Callable[[str, dict[str, Any]], Any], run_id: str | None = None
    ) -> None:
        self._key = workflow_key
        self._broadcast = broadcast
        self._run_id = run_id  # None = unpinned (follow newest live); set = pinned to one run (DR-1)
        self._current: Path | None = None
        self._offset = 0
        self._buf = b""  # RAW byte buffer (deep-review R4): decoding before the line boundary would lose
        self._blob_map: dict[str, str] = {}  # a multibyte char split across a poll read and never recover it
        self._state: dict[Any, dict[str, Any]] = {}  # id -> latest run-event (last-wins)
        self._run: dict[str, Any] | None = None  # the run-complete message, once seen
        self._stopped = False  # Task 173: broadcast run-stopped once when an incomplete run's lock goes free

    def snapshot(self) -> dict[str, Any]:
        """The current run state for a newly-subscribed viewer: all known node states + the run banner + the
        ``stopped`` flag. Read on the event loop; ``_state``/``_run``/``_stopped`` are mutated only on the
        loop (in ``_consume``/``_switch``/``_check_stopped``) — never in the to_thread file-read — so there is
        no concurrent-mutation race here (deep-review R3).

        ``stopped`` is load-bearing: ``run-stopped`` is broadcast ONCE (latched), so a viewer that subscribes
        AFTER it fires (a reload / 2nd tab reusing this tailer) would otherwise see only node states still
        reading ``running`` and never learn the run died — a silent blue-blink-forever (silent-failures
        review). Carrying the latched flag here lets a late subscriber render ``stopped`` immediately."""
        return {
            "type": "run-snapshot",
            "nodes": list(self._state.values()),
            "run": self._run,
            "stopped": self._stopped,
        }

    async def run(self) -> None:
        """Poll loop. Blocking filesystem I/O (discover, read) runs via ``asyncio.to_thread`` so it never
        stalls the event loop (the hub's SSE sends / keepalives / disconnect-cleanup share it — same rule
        ``command()`` follows; deep-review R3). PARSING + state mutation + broadcast stay ON the loop, so
        ``snapshot()`` never races a concurrent mutation. Robust: one bad poll logs and the loop continues.

        PINNED (``run_id`` set — deep-review DR-1): resolve ``run_id -> Path`` ONCE, then tail that fixed
        file forever — never re-discover, so a newer live run of the same workflow can't yank a pinned
        replay (the whole point of the pin). A stale/unknown ``run_id`` broadcasts ``run-not-found`` and
        stops. UNPINNED (``run_id is None``): follow the newest live trace, re-discovering each poll so a
        run started after the viewer opened is picked up; switching files resets state + emits ``run-reset``.
        """
        if self._run_id is not None:
            pinned = await asyncio.to_thread(self._resolve_pinned)
            if pinned is None:
                self._broadcast(self._key, {"type": "run-not-found", "run_id": self._run_id})
                return
            self._switch(pinned)  # fix the file; snapshot() catches up each subscriber — no run-reset needed
        while True:
            try:
                if self._run_id is None:
                    found = await asyncio.to_thread(discover_live_trace, self._key)
                    if found is None:
                        await asyncio.sleep(_POLL_S)
                        continue
                    if found != self._current:
                        self._switch(found)  # loop: reset state
                        self._broadcast(self._key, {"type": "run-reset"})  # loop: tell viewers to clear
                    current: Path | None = found
                else:
                    current = self._current  # pinned: the fixed file resolved above
                if current is not None:
                    data = await asyncio.to_thread(self._read_bytes, current)  # off-loop I/O
                    for message in self._consume(data):  # loop: parse + mutate state
                        self._broadcast(self._key, message)
                    await self._check_stopped(current)
            except Exception:
                logger.debug("run tailer poll failed for %s", self._key, exc_info=True)
            await asyncio.sleep(_POLL_S)

    async def _check_stopped(self, current: Path) -> None:
        """Task 173 exact death-detection: after consuming all available bytes, if the run is STILL
        incomplete (no ``run.complete``) probe the producer's advisory lock. A FREE lock means the writer's
        process exited without finishing → crashed/killed → broadcast ``run-stopped`` ONCE so the canvas
        flips its dangling ``running`` nodes to ``stopped`` instead of pulsing blue forever. (``is_trace_locked``
        None = no fcntl → don't claim stopped; True = alive. A free lock can ALSO mean streaming was disabled
        by a mid-run I/O fault — a rare degraded path where the trace stopped growing, so "stopped" is
        honest enough.)

        CONFIRM-BEFORE-CLAIM (concurrency review): a CLEAN finish also frees the lock — ``finalize()`` flushes
        ``run.complete`` BEFORE releasing it. This poll's byte-read (which sets ``self._run``) happened a
        couple thread-hops earlier than this probe, and the producer is a SEPARATE process, so a run that
        completes in that read→probe gap would otherwise be seen as free-lock + ``self._run is None`` → a
        FALSE ``run-stopped`` on a successful run. So on a free lock, re-read the tail once: the flush-before-
        release ordering guarantees the trailer is on disk by now, so a still-incomplete tail = a real crash."""
        if self._run is not None or self._stopped:
            return
        if (await asyncio.to_thread(is_trace_locked, current)) is not False:
            return  # held (alive) or None (no fcntl) — never claim stopped
        complete, _ = await asyncio.to_thread(read_run_status, current)
        if complete:
            return  # finished cleanly in the read→probe gap; the next poll's read fires run-complete
        self._stopped = True
        self._broadcast(self._key, {"type": "run-stopped"})

    def _resolve_pinned(self) -> Path | None:
        """Resolve the pinned ``run_id`` to its trace file ONCE (deep-review DR-1) — BLOCKING I/O, run via
        ``asyncio.to_thread``. Matches ``meta.execution_id`` over the shared scanner; does NOT apply the
        ``--only`` exclude — a user pinning a labelled ``--only`` run from history made an explicit choice
        (the exclude is the live overlay's policy, not the pin's; deep-review DR-3)."""
        for candidate in scan_traces(self._key):
            if candidate["meta"].get("execution_id") == self._run_id:
                return candidate["path"]
        return None

    def _switch(self, path: Path) -> None:
        """Follow a newer run: reset all per-file state (on the loop). The caller emits ``run-reset``."""
        self._current = path
        self._offset = 0
        self._buf = b""
        self._blob_map.clear()
        self._state.clear()
        self._run = None
        self._stopped = False

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
