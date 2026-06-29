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
import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, TypedDict

from pflow.core.trace_tree import event_cost

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
    final line (a run mid-flush) doesn't parse → ``(False, None)`` (live), the safe direction. Lets
    ``/api/runs`` report a finished run's status WITHOUT a full ``load_trace_file`` parse."""
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


# Read-through cache of immutable per-file trace facts, shared across polls AND callers (the live tailer's
# `discover_live_trace` and `/api/runs`). A trace's `meta` head is written once and a FINISHED trace's tail
# never changes, so keying on (mtime, size) lets a scan skip the open+parse for every UNCHANGED file —
# turning a poll over a large ~/.pflow/debug from O(N opens) into O(N stats) + a read of only the one growing
# live file. The verdict is cached even when a file has NO valid meta head (None) — a pre-Task-172
# single-object trace or junk — so the bulk of a long-lived debug dir (old-format files) is probed ONCE, not
# re-opened every poll. Without it an idle viewer re-opens+parses every trace 4x/s (Task 173 perf finding).
# (mtime, size) not mtime alone so an append is never missed on a coarse-mtime filesystem. Lock-guarded:
# scan_traces runs in the Starlette threadpool (/api/runs) AND via asyncio.to_thread (the tailer).
# Callers MUST treat a returned candidate's `meta` dict as READ-ONLY — it is shared by reference across
# cache hits, so mutating it would corrupt other callers' results (today none mutate; keep it that way).
_SCAN_CACHE: dict[Path, tuple[float, int, dict[str, Any] | None, bool, str | None]] = {}
_SCAN_CACHE_LOCK = threading.Lock()

# The DIRECTORY LISTING cache (distinct from the per-file content cache above): which trace files EXIST
# changes only when one is created/deleted/renamed, which bumps the directory's mtime. So a scan stats the
# dir ONCE and reuses the prior glob result while that mtime is unchanged — turning a 4 Hz tailer poll from
# a full os.scandir of ~N entries (the profiled hotspot — Task 173) into a single stat. A finished run only
# changes a file's CONTENT (caught by _SCAN_CACHE on (mtime,size)), never the listing, so freshness holds.
_DIR_LIST_CACHE: dict[tuple[Path, str], tuple[float, list[Path]]] = {}


def _list_trace_files(directory: Path, pattern: str) -> list[Path]:
    """The directory scandir, isolated so the (directory, pattern, mtime) gate below can skip it."""
    return list(directory.glob(pattern))


def _stat_sorted_listing(directory: Path, pattern: str) -> list[tuple[Path, float, int]] | None:
    """The matching trace files with their (mtime, size), newest-first — reusing the cached scandir while the
    directory mtime is unchanged (skips the os.scandir on a static dir). None if the dir is unreadable."""
    try:
        dir_mtime = directory.stat().st_mtime
    except OSError:
        return None
    list_key = (directory, pattern)
    with _SCAN_CACHE_LOCK:
        listed = _DIR_LIST_CACHE.get(list_key)
    if listed is not None and listed[0] == dir_mtime:
        entries = listed[1]
    else:
        try:
            entries = _list_trace_files(directory, pattern)
        except OSError:
            return None
        with _SCAN_CACHE_LOCK:
            _DIR_LIST_CACHE[list_key] = (dir_mtime, entries)
    stated: list[tuple[Path, float, int]] = []
    for path in entries:
        try:
            st = path.stat()
        except OSError:
            continue  # vanished between listing and stat — skip
        stated.append((path, st.st_mtime, st.st_size))
    stated.sort(key=lambda t: t[1], reverse=True)  # newest-first by mtime
    return stated


def _file_facts(path: Path, mtime: float, size: int) -> tuple[dict[str, Any] | None, bool, str | None]:
    """The (meta, complete, final_status) for one trace, served from _SCAN_CACHE on an unchanged
    (mtime, size) or read fresh — caching a None-meta NEGATIVE verdict too so an old-format file isn't
    re-opened every poll. Callers must treat the returned `meta` as read-only (it's the cached object)."""
    with _SCAN_CACHE_LOCK:
        hit = _SCAN_CACHE.get(path)
    if hit is not None and hit[0] == mtime and hit[1] == size:
        return hit[2], hit[3], hit[4]
    meta = _read_meta(path)  # I/O OUTSIDE the lock
    complete, final_status = read_run_status(path) if meta is not None else (False, None)
    with _SCAN_CACHE_LOCK:
        _SCAN_CACHE[path] = (mtime, size, meta, complete, final_status)
    return meta, complete, final_status


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
    neither policy lives here. An unreadable trace is skipped (``meta is None``), never fatal (DR-6).
    Per-file results are cached on ``(mtime, size)`` (``_SCAN_CACHE``) so repeated polls re-open only files
    that grew — a finished trace is read once."""
    directory = debug_dir or _debug_dir()
    # Scope the glob to THIS workflow's hash prefix when we know it (the live overlay + per-workflow
    # history) — the producer encodes md5(workflow_path)[:8] into every filename (format_trace_filename),
    # so we never list/stat/open OTHER workflows' traces or unrelated history. A bare scan (the dashboard,
    # workflow_key=None) lists all runs, as it must. The 8-char prefix can collide → the _same_path
    # contents guard below is the discriminator (mirrors _iter_workflow_traces). The hash MUST match
    # format_trace_filename's; the discovery tests name their fixtures via it, so a drift fails loudly.
    if workflow_key is None:
        pattern = "workflow-trace-*.json"
    else:
        wf_hash = hashlib.md5(workflow_key.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        pattern = f"workflow-trace-{wf_hash}-*.json"
    stated = _stat_sorted_listing(directory, pattern)
    if stated is None:
        return []
    out: list[TraceCandidate] = []
    seen: set[Path] = set()
    for path, mtime, size in stated:
        seen.add(path)
        meta, complete, final_status = _file_facts(path, mtime, size)
        # meta is None for an unreadable / pre-172 single-object trace (its negative verdict is cached too).
        if meta is None or (workflow_key is not None and not _same_path(meta.get("workflow_path"), workflow_key)):
            continue
        out.append({"path": path, "meta": meta, "complete": complete, "final_status": final_status, "mtime": mtime})
    # Bound memory: forget per-file cache entries for files removed from THIS directory (leave others' alone).
    with _SCAN_CACHE_LOCK:
        for stale in [p for p in _SCAN_CACHE if p.parent == directory and p not in seen]:
            _SCAN_CACHE.pop(stale, None)
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
        # Task 173 replay version-detection: latched ONCE in `_resolve_pinned` (the pinned path's only file
        # resolve) and never flips after — unpinned tailers never compute it; pinned ones never re-discover.
        # So it is delivered BOTH ways (mirroring `_stopped`): a `run-stale` broadcast reaches the subscriber
        # present at resolve time, and `snapshot()` carries it for any late subscriber. Deliberately NOT reset
        # in `_switch` (the pinned path calls `_switch` immediately AFTER this latch — resetting would wipe it).
        self._stale_version = False

    def snapshot(self) -> dict[str, Any]:
        """The current run state for a newly-subscribed viewer: all known node states + the run banner + the
        ``stopped`` flag. Read on the event loop; ``_state``/``_run``/``_stopped`` are mutated only on the
        loop (in ``_consume``/``_switch``/``_check_stopped``) — never in the to_thread file-read — so there is
        no concurrent-mutation race here (deep-review R3).

        ``stopped`` is load-bearing: ``run-stopped`` is broadcast ONCE (latched), so a viewer that subscribes
        AFTER it fires (a reload / 2nd tab reusing this tailer) would otherwise see only node states still
        reading ``running`` and never learn the run died — a silent blue-blink-forever (silent-failures
        review). Carrying the latched flag here lets a late subscriber render ``stopped`` immediately.
        ``stale_version`` rides the same way (Task 173 replay version-detection) — the ``run-stale`` broadcast
        only reaches the subscriber present when ``_resolve_pinned`` latched it, so a late subscriber learns
        the version mismatch from this snapshot."""
        return {
            "type": "run-snapshot",
            "nodes": list(self._state.values()),
            "run": self._run,
            "stopped": self._stopped,
            "stale_version": self._stale_version,
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
        if self._run_id is not None and not await self._start_pinned():
            return  # pinned run_id matched no trace (run-not-found broadcast) — don't loop
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

    async def _start_pinned(self) -> bool:
        """Pinned setup (deep-review DR-1): resolve ``run_id -> Path`` ONCE and fix the file. Returns False
        (stop the run() loop) when the id matched no trace — broadcasting ``run-not-found`` so the canvas
        isn't left silently all-pending; True once the file is fixed. ``_resolve_pinned`` also latches
        ``self._stale_version`` (Task 173); if stale, broadcast ``run-stale`` HERE — the present subscriber's
        snapshot was already taken (before this task ran) with stale=False, so snapshot-only would miss it.
        Late subscribers get it from ``snapshot()`` instead. Mirrors run-stopped's dual delivery."""
        pinned = await asyncio.to_thread(self._resolve_pinned)  # also latches self._stale_version
        if pinned is None:
            self._broadcast(self._key, {"type": "run-not-found", "run_id": self._run_id})
            return False
        self._switch(pinned)  # fix the file; snapshot() catches up each subscriber — no run-reset needed
        if self._stale_version:
            self._broadcast(self._key, {"type": "run-stale"})
        return True

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
        (the exclude is the live overlay's policy, not the pin's; deep-review DR-3).

        Side effect (Task 173): on a match, latches ``self._stale_version`` from the run's recorded
        ``content_hash`` vs the current file's digest. Safe to write here from the worker thread — it's read
        only after this ``to_thread`` call joins (the loop resumes), never concurrently."""
        for candidate in scan_traces(self._key):
            if candidate["meta"].get("execution_id") == self._run_id:
                self._stale_version = self._is_stale(candidate["meta"].get("content_hash"))
                return candidate["path"]
        return None

    def _is_stale(self, run_hash: str | None) -> bool:
        """Was this run recorded against a DIFFERENT version of the workflow than the file on disk now?
        (Task 173 — version DETECTION, not faithful old-graph rendering.) Compares the run's stamped
        ``content_hash`` to the current file's ``workflow_content_hash``; both hash the RESOLVED IR (logical
        only — source-line provenance stripped) via the same ``resolve_workflow`` path the runner used, so an
        unedited file round-trips to an identical digest and a comment/whitespace edit does NOT read as stale.

        Returns ``False`` (cannot verify → no banner, replay as-is) in three cases:
        - ``run_hash`` is ``None`` — an old trace pre-dating the fingerprint.
        - ``self._key`` is an ``ir-hash:`` inline identity — its id already encodes content, so an inline
          replay is never "a different version". DEFENSE-IN-DEPTH ONLY: an ``ir-hash:`` key never reaches a
          tailer (``server._workflow_key`` 404s it before any tailer is built), so this never fires via the UI.
        - resolving the current file RAISES — a deleted entry file or a deleted *referenced* file makes the
          workflow unrenderable, so ``/api/graph`` already owns that case with its 422 "could not be rendered"
          banner; there is no misleading overlay to warn about. Fail-closed-to-not-stale is correct here. The
          blanket ``except Exception`` is intentional (the missing-entry-file failure is a ``raise`` from
          ``resolve_workflow``, not just a digest error) — pinned by the deleted-referenced-file test."""
        if run_hash is None or self._key.startswith("ir-hash:"):
            return False
        # Lazy import: keeps run_tailer's module import light at server startup, and resolve_workflow pulls
        # in the markdown/resolver stack the tailer otherwise never needs.
        from pflow.core.workflow_id import workflow_content_hash
        from pflow.execution.workflow_resolver import resolve_workflow

        try:
            current_digest = workflow_content_hash(resolve_workflow(self._key).ir)
        except Exception:
            return False
        return current_digest != run_hash

    def _switch(self, path: Path) -> None:
        """Follow a newer run: reset all per-file state (on the loop). The caller emits ``run-reset``.

        Resets PER-FILE state only. ``_stale_version`` is deliberately NOT reset here — it is per-RUN, latched
        once in ``_resolve_pinned`` which runs IMMEDIATELY before the pinned path's single ``_switch`` call, so
        resetting it would wipe the just-latched value. (Unpinned tailers never set it, so omitting it is
        safe there too.)"""
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

    ``cost_usd`` is this run's PAID cost via :func:`event_cost` (the one shared cost policy), NOT the raw
    ``llm_call.cost_usd``: a cached node paid nothing this run, so it reports ``0`` and the hover chip
    agrees with ``pflow report`` + the detail panel instead of showing the historical source-call cost.
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
        "cost_usd": event_cost(line),
    }
