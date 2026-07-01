"""Starlette app backing ``pflow ui``.

Endpoints:

- ``GET /api/catalog`` — saved workflows as ``[{name, description, path}]``
  (the registry list with ``ir`` stripped).
- ``GET /api/graph?workflow=<name|path>`` — the React Flow contract
  (``render_react_flow``) for one workflow, as JSON.
- ``GET /api/source?workflow=<name|path>`` — source text for every authored
  ``.pflow.md`` file reachable from the built graph.
- ``GET /api/version?workflow=<name|path>`` — a cheap change-fingerprint over
  the workflow's source files, so the frontend can poll it and re-fetch the
  graph in place (no page reload) when the author edits the ``.pflow.md``.
- ``GET /api/events?workflow=<name|path>`` — SSE commands for each open Viewer.
- ``GET /api/health`` — liveness + identity probe for discovery/reuse; reports the
  live window count when a resolvable ``workflow`` is supplied.
- ``POST /api/command`` — validate and broadcast an agent Point command.
- ``POST /api/interaction`` — record one deliberate Viewer interaction.
- ``POST /api/visibility`` — update a Viewer's visible/backgrounded state.
- ``POST /api/run`` — spawn a detached ``pflow run`` for a resolved workflow +
  inputs (Task 175). The server stays a pure observer; the spawned run writes its
  own streaming trace that the tailer/overlay pick up. No in-process execution.
- ``GET /api/run-inputs?workflow=<name|path>&run=<id>`` — a past run's recorded
  inputs as form-ready token strings, for the Run panel's re-run prefill (Task 175).
  ``meta.inputs`` with sensitive-named keys omitted (server-side redaction).
- ``GET /api/activity`` — read a newest-first snapshot of recent interactions.
- ``/`` (+ assets) — the built frontend bundle, when present. Absent in a
  source checkout (the bundle is gitignored, built by ``make ui-build``); the
  server then serves a clear "not built" message instead of crashing.

Graph data remains **stateless per request**: every ``/api/graph`` call
re-resolves, re-validates and re-builds the graph from disk. The live interaction
hub is ephemeral and per app instance; it holds no workflow run state.

Failure regimes for ``/api/graph`` (kept distinct — do not collapse):

- a missing ``workflow`` query param → **400** (malformed request);
- a resolution / validation failure → **422** with a structured diagnostics
  body (``WorkflowGraphValidationError``);
- a build or render bug on validated IR → **500** (the exception propagates;
  never a 200-with-empty-graph).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from pflow.core.diagnostic import exception_to_diagnostics
from pflow.core.exceptions import PflowError
from pflow.core.workflow.graph import render_react_flow
from pflow.core.workflow.manager import WorkflowManager
from pflow.execution.graph_service import (
    WorkflowGraphValidationError,
    resolve_validate_build,
)
from pflow.execution.workflow_resolver import resolve_workflow
from pflow.registry import Registry
from pflow.ui.run_node import read_run_inputs, run_node_detail
from pflow.ui.run_tailer import RunTailer, TraceCandidate, is_trace_locked, scan_traces
from pflow.ui.targets import resolve_target

logger = logging.getLogger(__name__)

# Sub-workflow expansion depth served to the client. The frontend collapses and
# expands containers client-side, so the server always ships the full tree.
_MAX_DEPTH = 5
_ACTIVITY_MAX = 200
_CONNECTION_QUEUE_MAX = 64
_KEEPALIVE_S = 15.0
# Put on a Viewer's queue to end its SSE stream cleanly on server shutdown (see _Hub.shutdown): the
# generator returns instead of being force-cancelled by uvicorn, which would log a CancelledError per stream.
_SHUTDOWN_SENTINEL: dict[str, object] = {"__shutdown__": True}

_STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class _Conn:
    conn_id: str
    workflow_key: str
    queue: asyncio.Queue[dict[str, object]]
    visibility: str
    # Task 173 (DR-1): which run this Viewer watches — None = the unpinned live overlay (follow newest),
    # a run_id = a pinned replay/live-watch. Run-events are delivered run-scoped (broadcast_run) so a
    # pinned replay and the unpinned overlay of the SAME workflow never cross-feed; Point commands stay
    # workflow-scoped (broadcast) — they apply to every Viewer of the workflow regardless of run.
    run_id: str | None = None
    active: bool = True


# INVARIANT (load-bearing): Every handler that touches the hub MUST be `async
# def`. Starlette runs async handlers on the event loop and sync `def` handlers
# in a threadpool thread. asyncio.Queue is loop-affine and NOT thread-safe — a
# sync handler calling put_nowait or mutating the deque would race the loop with
# no lock. Do NOT add a sync hub-touching handler. The existing sync GET handlers
# never touch it.
class _Hub:
    """Per-app registry of live Viewers and bounded user activity."""

    def __init__(self) -> None:
        self._conns: dict[str, _Conn] = {}
        self._activity: deque[dict[str, object]] = deque(maxlen=_ACTIVITY_MAX)
        self._counter = itertools.count(1)
        # Issue #539 (Point latch): the agent's current Point per workflow_key — the last focus/frame/clear
        # envelope, carrying its epoch — replayed to a Viewer on (re)subscribe so a tab that was HIDDEN when
        # the command fired (its SSE closed to free a connection slot), or a brand-new tab, catches up to the
        # highlight. `boot_id` fences the epoch across a server restart: a fresh process restarts the counter
        # at 1, so the client resets its `lastAppliedEpoch` baseline when this nonce changes on reconnect,
        # else a surviving tab would silently skip the new server's lower-numbered Points. Loop-owned like the
        # rest of the hub (mutated only from command(), on the event loop). Deliberately NEVER evicted (unlike
        # `_conns`/tailers): a brand-new tab minutes after the last one closed must still catch up, so pruning
        # on last-window-close would defeat the feature — bounded by O(#workflows ever pointed at), negligible.
        self._points: dict[str, dict[str, object]] = {}
        self._point_epoch = itertools.count(1)
        self.boot_id = uuid.uuid4().hex
        # Task 173: one live-run tailer per (workflow_key, run_id) — started on first viewer subscribe and
        # stopped when its last viewer leaves (ref-counted via windows_for_run). DR-1: keying on the run_id
        # too (None = the unpinned live overlay) means a pinned replay and the unpinned overlay of the same
        # workflow get SEPARATE tailers and never fight over one file. Lock-free / loop-owned like the rest
        # of the hub — ensure_tailer creates an asyncio task and so MUST run on the event loop.
        self._tailers: dict[tuple[str, str | None], tuple[RunTailer, asyncio.Task[None]]] = {}

    def register(self, workflow_key: str, visibility: str, run_id: str | None = None) -> _Conn:
        conn = _Conn(
            conn_id=f"viewer-{next(self._counter)}",
            workflow_key=workflow_key,
            queue=asyncio.Queue(maxsize=_CONNECTION_QUEUE_MAX),
            visibility=visibility,
            run_id=run_id,
        )
        self._conns[conn.conn_id] = conn
        return conn

    def unregister(self, conn_id: str) -> None:
        self._conns.pop(conn_id, None)

    def shutdown(self) -> None:
        """End every live Viewer stream cleanly on server shutdown: mark each inactive and wake its blocked
        ``queue.get`` with a sentinel so the SSE generator RETURNS (its StreamingResponse completes) instead
        of being force-cancelled by uvicorn — which logs a CancelledError per stream. The generators' own
        ``finally`` then unregisters them and releases their tailers. Loop-owned like the rest of the hub
        (called from uvicorn's signal callback, which runs on the event loop)."""
        for conn in list(self._conns.values()):
            conn.active = False
            with contextlib.suppress(asyncio.QueueFull):
                conn.queue.put_nowait(_SHUTDOWN_SENTINEL)

    def set_visibility(self, conn_id: str, visibility: str) -> None:
        conn = self._conns.get(conn_id)
        if conn is not None:
            conn.visibility = visibility

    def windows_for(self, workflow_key: str) -> list[_Conn]:
        return [conn for conn in self._conns.values() if conn.workflow_key == workflow_key]

    def windows_for_run(self, workflow_key: str, run_id: str | None) -> list[_Conn]:
        """Viewers watching one specific run (Task 173) — ref-counts a run-scoped tailer and scopes its
        run-events. A subset of ``windows_for`` (which spans every run of the workflow, for Point)."""
        return [c for c in self._conns.values() if c.workflow_key == workflow_key and c.run_id == run_id]

    def set_point(self, workflow_key: str, message: dict[str, object]) -> dict[str, object]:
        """Latch the agent's current Point for a workflow and return the broadcast envelope with its epoch.

        Issue #539: focus/frame/clear are transient broadcasts with no snapshot replay, so a tab whose SSE
        was closed while hidden would miss them. We stamp each with a monotonic ``epoch`` and remember the
        latest per workflow_key; ``events()`` replays it to every new/reconnecting Viewer, and the client's
        epoch-dedup applies it only if newer than what it already showed — a returning tab catches up without
        clobbering the user's own navigation. The epoch encodes BROADCAST order, not request-arrival order
        (``clear`` stamps before focus/frame's off-loop build), which matches what live clients already see.

        The returned envelope is stored in ``_points`` AND broadcast to every conn as the SAME dict — it is
        immutable once minted (this method always builds a fresh dict; no consumer mutates it, only
        ``json.dumps``), so sharing the reference between the latch and the broadcast queues is torn-read-free.
        """
        envelope = {**message, "epoch": next(self._point_epoch)}
        self._points[workflow_key] = envelope
        return envelope

    def point_for(self, workflow_key: str) -> dict[str, object] | None:
        return self._points.get(workflow_key)

    def _send_or_evict(self, conn: _Conn, message: dict[str, object]) -> bool:
        """Enqueue one message to one connection; EVICT it if its bounded queue is full. A socket that
        cannot consume 64 messages is no longer a truthful delivery target — drop it rather than leak
        memory or report another message as sent. Returns True iff delivered. Shared by ``broadcast``
        (workflow-scoped, Point) and ``broadcast_run`` (run-scoped, Task 173) so the eviction policy lives
        in ONE place. Callers iterate a fresh ``windows_for*`` list, so the ``unregister`` here can't
        corrupt the caller's iteration."""
        try:
            conn.queue.put_nowait(message)
        except asyncio.QueueFull:
            conn.active = False
            self.unregister(conn.conn_id)
            return False
        return True

    def broadcast(self, workflow_key: str, message: dict[str, object]) -> list[_Conn]:
        return [conn for conn in self.windows_for(workflow_key) if self._send_or_evict(conn, message)]

    def broadcast_run(self, workflow_key: str, run_id: str | None, message: dict[str, object]) -> None:
        """Deliver a tailer's run-event to ONLY the Viewers watching that exact run (Task 173, DR-1) —
        unlike ``broadcast`` (workflow-scoped, for Point)."""
        for conn in self.windows_for_run(workflow_key, run_id):
            self._send_or_evict(conn, message)

    def ensure_tailer(self, workflow_key: str, run_id: str | None = None) -> RunTailer:
        """Start (or reuse) the live-run tailer for this ``(workflow_key, run_id)`` — one per pair, shared
        across its Viewers (DR-1: the unpinned overlay is ``run_id=None``; a pinned replay/live-watch gets
        its own). MUST be called from an async (event-loop) handler: it creates an asyncio task. The tailer
        broadcasts run-scoped (``broadcast_run`` bound to this ``run_id``) so pinned and unpinned Viewers of
        one workflow never cross-feed.

        A TERMINATED task is treated as absent and replaced. A pinned tailer that resolves to no trace
        broadcasts ``run-not-found`` and RETURNS (task done) — but its entry lingers in ``_tailers`` until
        the last viewer disconnects. Reusing that done tailer would hand a second/reconnecting viewer only
        an empty ``snapshot()`` and NO further broadcast — the silent all-pending canvas ``run-not-found``
        exists to prevent. Starting fresh re-resolves and re-broadcasts (also self-heals a tailer that died
        for any other reason). The done task needs no cancel; overwriting the entry drops it."""
        key = (workflow_key, run_id)
        entry = self._tailers.get(key)
        if entry is not None and not entry[1].done():
            return entry[0]
        tailer = RunTailer(workflow_key, lambda k, msg: self.broadcast_run(k, run_id, msg), run_id=run_id)
        task = asyncio.create_task(tailer.run())
        self._tailers[key] = (tailer, task)
        return tailer

    def release_tailer(self, workflow_key: str, run_id: str | None = None) -> None:
        """Stop the ``(workflow_key, run_id)`` tailer once its LAST Viewer has disconnected. Call AFTER
        ``unregister`` so ``windows_for_run`` reflects the departed connection."""
        if self.windows_for_run(workflow_key, run_id):
            return
        entry = self._tailers.pop((workflow_key, run_id), None)
        if entry is not None:
            entry[1].cancel()

    def record(self, event: dict[str, object]) -> None:
        self._activity.append(event)

    def activity(self, workflow_key: str | None = None) -> list[dict[str, object]]:
        events = reversed(self._activity)
        return [dict(event) for event in events if workflow_key is None or event.get("workflow_key") == workflow_key]


def _json(data: Any, *, status_code: int = 200) -> Response:
    """JSON response that tolerates exotic param values (YAML dates, etc.).

    ``default=str`` keeps a stray non-JSON-native value carried in
    ``Node.params`` from turning a successful render into a 500.
    """
    return Response(
        json.dumps(data, default=str),
        media_type="application/json",
        status_code=status_code,
    )


def catalog(request: Request) -> Response:
    """List saved workflows: names + descriptions + entry-point paths (no ``ir``)."""
    manager = WorkflowManager()
    items = [
        {
            "name": workflow["name"],
            "description": workflow.get("description", ""),
            "path": manager.get_path(workflow["name"]),
        }
        for workflow in manager.list_all()
    ]
    return _json(items)


def graph(request: Request) -> Response:
    """Render one workflow's React Flow contract.

    400 on a missing ``workflow`` param, 422 on a resolution/validation
    failure; a build or render bug on validated IR propagates to a 500.
    """
    workflow = request.query_params.get("workflow")
    if not workflow:
        return _json(
            {"errors": [{"message": "Missing required 'workflow' query parameter."}]},
            status_code=400,
        )

    try:
        model = resolve_validate_build(workflow, max_depth=_MAX_DEPTH)
    except WorkflowGraphValidationError as e:
        return _json({"errors": [d.to_dict() for d in e.diagnostics]}, status_code=422)

    # Platform facts joined at the seam: the renderer stays registry-free.
    kind_types = Registry().output_types_by_kind()
    return _json(asdict(render_react_flow(model, kind_output_types=kind_types)))


def source(request: Request) -> Response:
    """Return source text for every file represented in the graph model.

    The file set is derived from ``GraphModel.nodes`` rather than the React Flow
    render because renderer-level batch truncation can omit child files. A
    ``depth_limit``-unexpanded sub-workflow contributes no nodes, and therefore
    no source file, which is the honest boundary for this read-only endpoint.
    """
    workflow = request.query_params.get("workflow")
    if not workflow:
        return _json(
            {"errors": [{"message": "Missing required 'workflow' query parameter."}]},
            status_code=400,
        )

    try:
        model = resolve_validate_build(workflow, max_depth=_MAX_DEPTH)
    except WorkflowGraphValidationError as e:
        return _json({"errors": [d.to_dict() for d in e.diagnostics]}, status_code=422)

    root = next(
        (
            node.source.file
            for node in model.nodes
            if not node.id.ancestor_path and node.source is not None and node.source.file
        ),
        None,
    )
    source_files = sorted({node.source.file for node in model.nodes if node.source and node.source.file})

    files: dict[str, str] = {}
    for file_path in source_files:
        try:
            files[file_path] = Path(file_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Skipping unreadable workflow source file %s: %s", file_path, e)

    return _json({"root": root, "files": files})


def _source_files_for(workflow: str) -> list[str]:
    """The ``.pflow.md`` files a workflow's graph touches — best-effort.

    A full build yields every authored file (the set ``/api/source`` uses). When
    the workflow is **mid-edit invalid** the build fails, so fall back through
    progressively cruder sources so the fingerprint still tracks the file being
    edited:

    1. the built graph's source files (the complete set, the happy path);
    2. the resolvable entry file (validation failed but the reference resolves);
    3. a saved NAME's entry path looked up directly (the file won't PARSE, so
       resolution fails — but the catalog / ``pflow ui <name>`` pass a name, and
       the agent is editing a real file on disk);
    4. the literal ``workflow`` arg if it is an existing file (a parse-broken
       PATH argument).

    Anything still unresolved (an inline-content workflow with no files, or a
    deleted file) yields ``[]`` → a constant fingerprint, and the poll keeps
    running until the file is valid again. The first ``try`` catches **any**
    exception (not just validation) because ``/api/version`` must NEVER 500 —
    a build-stage producer bug on validated IR (the ``/api/graph`` 500 regime)
    must still fall through here rather than break the client's poll loop.
    """
    try:
        files = sorted({
            n.source.file
            for n in resolve_validate_build(workflow, max_depth=_MAX_DEPTH).nodes
            if n.source and n.source.file
        })
    except Exception:
        files = []  # validation OR a build-stage bug — fall through; never 500 the poll
    if files:
        return files
    try:
        entry = resolve_workflow(workflow).file_path
    except Exception:
        entry = None  # resolution itself failed (a parse error) — try the name, then the raw path
    if entry:
        return [entry]
    try:
        name_path = WorkflowManager().get_path(workflow)
    except Exception:
        name_path = None  # not a saved name (or the lookup failed)
    if name_path and Path(name_path).is_file():
        return [name_path]
    return [workflow] if Path(workflow).is_file() else []


def version(request: Request) -> Response:
    """A cheap change-fingerprint over a workflow's source files.

    The frontend polls this; when the fingerprint changes it re-fetches
    ``/api/graph`` and rebuilds the canvas **in place** (no page reload). The
    digest is over each source file's path + mtime, so an edit (or an
    added/removed sub-workflow file) moves it.

    Always ``200`` except ``400`` on a missing ``workflow`` param — a mid-edit
    INVALID workflow must NOT error the poll. Its entry file's mtime still
    changes the fingerprint, so the triggered ``/api/graph`` re-fetch surfaces
    the ``422`` as a banner and recovers when the edit is fixed.
    """
    workflow = request.query_params.get("workflow")
    if not workflow:
        return _json(
            {"errors": [{"message": "Missing required 'workflow' query parameter."}]},
            status_code=400,
        )

    parts: list[str] = []
    for file_path in _source_files_for(workflow):
        try:
            parts.append(f"{file_path}:{Path(file_path).stat().st_mtime_ns}")
        except OSError:
            parts.append(f"{file_path}:missing")
    digest = hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()
    return _json({"fingerprint": digest})


def _workflow_key(value: str) -> str | None:
    """Canonical identity shared by name-opened and path-opened Viewers."""
    path = Path(value)
    try:
        if path.exists():
            return str(path.resolve())
    except OSError:
        return None

    manager = WorkflowManager()
    if not manager.exists(value):
        return None
    return str(Path(manager.get_path(value)).resolve())


def _workflow_not_found(value: str) -> Response:
    from pflow.core.suggestion_utils import find_similar_items

    suggestions = find_similar_items(value, WorkflowManager().list_names(), method="fuzzy")
    return _json(
        {
            "error": f"No workflow {value!r} was found.",
            "suggestions": suggestions,
        },
        status_code=404,
    )


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _host_is_local(host: str) -> bool:
    """True if the ``Host`` header names loopback. A real browser/CLI talking to the loopback server always
    sends ``127.0.0.1``/``localhost``/``::1`` (optionally ``:port``, or an IPv6 literal in brackets). Strip
    the port, unwrap an ``[::1]`` bracket, and membership-check the loopback set; a bare IPv6 like ``::1``
    (multiple colons, no brackets) is kept whole."""
    if host.startswith("["):  # IPv6 literal, e.g. "[::1]:8765" → "::1"
        hostname = host[1:].partition("]")[0]
    else:  # strip a trailing :port only when there's exactly one colon (bare IPv6 like "::1" has more)
        hostname = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return (
        hostname.lower() in _LOOPBACK_HOSTS
    )  # host names are case-insensitive (a non-normalizing client may send "LocalHost")


class _LoopbackOnly:
    """Reject any request whose ``Host`` header isn't loopback — the DNS-rebinding guard, on EVERY route.

    The server binds ``127.0.0.1`` and sends no CORS headers, which blocks a cross-origin page from READING
    responses — but a DNS-rebinding attack points an attacker domain at ``127.0.0.1`` so the browser sends
    same-origin requests the server would otherwise honor (and can READ, defeating the no-CORS defense).
    Pinning ``Host`` to loopback closes that gap. Applied as middleware — a property of the SERVER, not of
    each handler — so it covers reads (``/api/source`` etc.) as well as mutating POSTs, and every future
    endpoint by default; there is no "route it through ``_json_body``" invariant to remember.

    Pure ASGI, NOT ``BaseHTTPMiddleware`` (load-bearing): it must not wrap the long-lived ``/api/events``
    SSE stream. It either short-circuits a non-loopback request with ``403`` or delegates untouched, so the
    stream flows normally."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not _host_is_local(Headers(scope=scope).get("host", "")):
            response = _json(
                {"error": "Refused: this server accepts loopback requests only (non-local Host)."},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


async def _json_body(request: Request) -> dict[str, object] | Response:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/json":
        return _json(
            {"error": "Content-Type: application/json is required."},
            status_code=415,
        )
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return _json({"error": "Request body must be valid JSON."}, status_code=400)
    if not isinstance(body, dict):
        return _json({"error": "Request JSON must be an object."}, status_code=400)
    return body


def _string_field(body: dict[str, object], name: str) -> str | None:
    value = body.get(name)
    return value if isinstance(value, str) and value.strip() else None


def _dispatch_report(workflow_key: str, conns: list[_Conn]) -> dict[str, object]:
    return {
        "sent_to": len(conns),
        "windows": [{"visibility": conn.visibility} for conn in conns],
        "workflow_key": workflow_key,
    }


async def events(request: Request) -> Response:
    """Subscribe one Viewer to Point commands for a canonical workflow key."""
    workflow = request.query_params.get("workflow")
    if not workflow:
        return _json({"error": "Missing required 'workflow' query parameter."}, status_code=400)
    workflow_key = _workflow_key(workflow)
    if workflow_key is None:
        return _workflow_not_found(workflow)
    visibility = request.query_params.get("visibility", "visible")
    if visibility not in {"visible", "hidden"}:
        return _json({"error": "Visibility must be 'visible' or 'hidden'."}, status_code=400)
    # Task 173 (DR-1): `&run=<run_id>` pins this Viewer to one run (replay, or watch one of N concurrent
    # runs); absent = the unpinned live overlay (follow the newest live run). An empty value is treated as
    # absent. The pin is a run_id (meta.execution_id), validated by the tailer's resolve (run-not-found).
    run_id = request.query_params.get("run") or None

    hub: _Hub = request.app.state.hub

    async def stream() -> AsyncIterator[str]:
        conn = hub.register(workflow_key, visibility, run_id)
        try:
            # `boot_id` fences the Point epoch across a server restart (Issue #539): the client resets its
            # dedup baseline when this nonce changes, so a reconnecting tab doesn't skip a fresh process's
            # lower-numbered Points.
            yield f"data: {json.dumps({'type': 'connected', 'conn_id': conn.conn_id, 'boot_id': hub.boot_id})}\n\n"
            # Task 173: attach this Viewer to the (workflow_key, run_id) tailer and hand it the current run
            # state so a viewer that opened mid-run catches up without replaying the file (and the per-conn
            # queue can't overflow on replay). Future deltas arrive as run-scoped `run-events`.
            tailer = hub.ensure_tailer(workflow_key, run_id)
            # A queue already full at subscribe (reconnect storm) — skip the catch-up snapshot rather than
            # abort the stream; streamed deltas re-sync state, and broadcast's own QueueFull eviction
            # governs from here. Mirrors broadcast's graceful degrade (deep-review R7).
            with contextlib.suppress(asyncio.QueueFull):
                conn.queue.put_nowait(tailer.snapshot())
            # Issue #539: catch this Viewer up to the agent's current Point (focus/frame/clear). A tab that
            # was hidden when the command fired closed its SSE and missed the broadcast; a new tab never got
            # it. The epoch-carrying envelope is deduped client-side, so replaying it is idempotent. Unlike
            # the snapshot above there is NO follow-up stream to re-sync this, but the trigger for a dropped
            # replay is near-impossible (the fresh 64-slot queue holds only the snapshot at this point).
            latched = hub.point_for(workflow_key)
            if latched is not None:
                with contextlib.suppress(asyncio.QueueFull):
                    conn.queue.put_nowait(latched)
            while conn.active:
                try:
                    message = await asyncio.wait_for(conn.queue.get(), timeout=_KEEPALIVE_S)
                except asyncio.TimeoutError:
                    # Load-bearing: a periodic send surfaces silently-dead sockets
                    # under ASGI spec >=2.4 and also defeats idle proxy timeouts.
                    yield ": keepalive\n\n"
                    continue
                if message is _SHUTDOWN_SENTINEL:
                    break  # server shutting down — end the stream cleanly (no uvicorn force-cancel)
                yield f"data: {json.dumps(message)}\n\n"
        finally:
            hub.unregister(conn.conn_id)
            hub.release_tailer(workflow_key, run_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def health(request: Request) -> Response:
    """Liveness + identity probe for discovery/reuse. Cheap: no graph build.

    Always reports the service identity (``{"service": "pflow-ui"}``) so a probe can
    tell a pflow viewer from any other process on the port. When a resolvable
    ``workflow`` is supplied, also reports the live window count for that key — the
    cheap readiness signal ``pflow ui focus --open`` polls instead of re-running the
    build-triggering ``/api/command`` on a timer.

    Unknown/unresolvable ``workflow`` reports identity only (no ``windows``): a
    liveness probe must answer regardless, unlike ``events()``/``command()`` which 404.

    ``async def`` is load-bearing: it reads the hub (``windows_for``), so it MUST run
    on the event loop, never the threadpool (see the hub concurrency invariant).

    Note: ``windows`` can transiently over-count by 1 for up to one ``_KEEPALIVE_S``
    cycle after a viewer's ``onerror`` reconnect to *this* server (the dropped
    connection lingers in the hub until its next keepalive write fails). Benign for a
    local single-user viewer; a server restart frees the whole hub, so that path is
    clean.
    """
    hub: _Hub = request.app.state.hub
    body: dict[str, object] = {"service": "pflow-ui"}
    workflow = request.query_params.get("workflow")
    if workflow:
        workflow_key = _workflow_key(workflow)
        if workflow_key is not None:
            body["workflow_key"] = workflow_key
            body["windows"] = len(hub.windows_for(workflow_key))
    return _json(body)


async def command(request: Request) -> Response:
    """Validate and broadcast one agent Point command."""
    body = await _json_body(request)
    if isinstance(body, Response):
        return body

    workflow = _string_field(body, "workflow")
    command_type = _string_field(body, "type")
    if workflow is None or command_type not in {"focus", "frame", "clear", "select-run"}:
        return _json(
            {"error": "Fields 'workflow' and type ('focus', 'frame', 'clear', or 'select-run') are required."},
            status_code=400,
        )
    workflow_key = _workflow_key(workflow)
    if workflow_key is None:
        return _workflow_not_found(workflow)

    hub: _Hub = request.app.state.hub
    if command_type == "clear":
        # Issue #539: latch the cleared state (stamped with its epoch) so a returning/new tab catches up to
        # the clear rather than replaying a stale highlight.
        cleared = hub.set_point(workflow_key, {"type": "clear"})
        return _json(_dispatch_report(workflow_key, hub.broadcast(workflow_key, cleared)))

    target = _string_field(body, "target")
    if target is None:
        return _json({"error": f"Command type {command_type!r} requires a non-empty target."}, status_code=400)

    # select-run (Task 175): the run id rides in `target` and is a PASS-THROUGH — NOT a graph target, so it
    # skips resolve_target entirely (a run isn't a node/edge). The browser's selectRun applies it (honoring
    # its own re-pick guard); a stale/unknown id surfaces the frontend's run-not-found path in the open
    # Viewer, never a server error — so no server-side run validation. Placed AFTER `target` is read (unlike
    # `clear`, which returns before it) since the id lives in `target`.
    if command_type == "select-run":
        conns = hub.broadcast(workflow_key, {"type": "select-run", "run": target})
        return _json(_dispatch_report(workflow_key, conns))

    try:
        # Validation/build can recurse through large nested workflows. Keep it
        # off the hub's event loop so SSE sends, disconnect cleanup, and
        # visibility/activity requests remain responsive. Hub operations stay
        # loop-owned below.
        model = await asyncio.to_thread(resolve_validate_build, workflow, max_depth=_MAX_DEPTH)
    except WorkflowGraphValidationError as exc:
        return _json({"errors": [diagnostic.to_dict() for diagnostic in exc.diagnostics]}, status_code=422)

    resolution = resolve_target(render_react_flow(model), target)
    response = {
        "resolved": resolution.report(),
        **_dispatch_report(workflow_key, []),
    }
    if resolution.matched != 1 or resolution.descriptor is None:
        return _json(response)

    # Issue #539: latch the resolved point (stamped with its epoch) BEFORE broadcasting, so a tab that was
    # hidden when this fired — or a new tab — catches up to it on (re)subscribe. Only a unique match reaches
    # here (the resolution.matched != 1 early-return above), so a zero/ambiguous match never mints an epoch.
    conns = hub.broadcast(
        workflow_key,
        hub.set_point(workflow_key, {"type": command_type, "target": resolution.descriptor}),
    )
    response.update(_dispatch_report(workflow_key, conns))
    return _json(response)


async def interaction(request: Request) -> Response:
    """Record one deliberate Viewer interaction; failures never affect graph state."""
    body = await _json_body(request)
    if isinstance(body, Response):
        return body

    workflow = _string_field(body, "workflow")
    event_type = _string_field(body, "type")
    view_state = body.get("view_state")
    if workflow is None or event_type is None or not isinstance(view_state, dict):
        return _json(
            {"error": "Fields 'workflow', 'type', and object 'view_state' are required."},
            status_code=400,
        )

    # Whitelist the recorded fields so the Watch snapshot the agent reads from
    # /api/activity keeps a predictable shape; arbitrary client keys are dropped.
    event = {key: body[key] for key in ("type", "target", "view_state") if key in body}
    # An unknown workflow records workflow_key=None and still returns 204 — unlike
    # command()/activity() which 404 — because a Watch report is fire-and-forget and
    # must never break the Viewer. Such events surface only in an unfiltered query.
    event.update({"workflow_key": _workflow_key(workflow), "ts": time.time()})
    hub: _Hub = request.app.state.hub
    hub.record(event)
    return Response(status_code=204)


async def visibility(request: Request) -> Response:
    """Update the visibility of a live Viewer connection."""
    body = await _json_body(request)
    if isinstance(body, Response):
        return body

    conn_id = _string_field(body, "conn_id")
    state = _string_field(body, "visibility")
    if conn_id is None or state not in {"visible", "hidden"}:
        return _json(
            {"error": "Fields 'conn_id' and visibility ('visible' or 'hidden') are required."},
            status_code=400,
        )
    hub: _Hub = request.app.state.hub
    hub.set_visibility(conn_id, state)
    return Response(status_code=204)


def _preflight(workflow_key: str, tokens: tuple[str, ...]) -> None:
    """Compile EXACTLY what the spawn will run — off the event loop (run via ``asyncio.to_thread``).

    The whole point: convert the silent *pre-trace-failure class* (a run that dies before it writes its
    ``meta`` line shows nothing on the overlay) into a clean ``400`` at the endpoint. ``compile_workflow``
    runs ``prepare_inputs`` internally (the same 5-tier input resolution + missing-required check the real
    run does) AND instantiates every node, so a missing required input, an unknown node type, or a bad
    param all surface here. We don't reuse the displayed tab's graph — an auto-update may have edited the
    file, or an agent may POST directly — so we re-resolve from disk. A fresh ``Registry`` per compile is
    the project rule (``runner`` does the same). Raises ``PflowError`` on any pre-trace failure; the
    handler maps it to ``400`` with diagnostics."""
    from pflow.cli.param_parsing import parse_workflow_params
    from pflow.runtime import compile_workflow

    resolved = resolve_workflow(workflow_key)
    typed_params = parse_workflow_params(tokens)  # infer_type per token — channel A (form == CLI)
    compile_workflow(resolved.ir, Registry(), initial_params=typed_params)


async def run(request: Request) -> Response:
    """Spawn a DETACHED ``pflow run`` for a resolved workflow + inputs (Task 175).

    The server stays a pure observer (ADR-0008): it spawns the normal CLI as a detached subprocess that
    writes its own streaming trace; the existing tailer discovers it and the overlay lights it up live.
    No in-process execution, no per-run process state. The only new mutation is this one spawn."""
    body = await _json_body(
        request
    )  # content-type + JSON-object enforcement (loopback Host is the _LoopbackOnly middleware)
    if isinstance(body, Response):
        return body

    workflow = _string_field(body, "workflow")
    if workflow is None:
        return _json(
            {"error": "Field 'workflow' (a saved name or .pflow.md path) is required."},
            status_code=400,
        )

    inputs = body.get("inputs", {})
    if not isinstance(inputs, dict) or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in inputs.items()
    ):
        return _json(
            {"error": "Field 'inputs' must be an object mapping input names to string values."},
            status_code=400,
        )

    # Resolve by name/path only — NEVER accept inline workflow content (a POSTed graph would bypass the
    # save/validate path the rest of the server trusts).
    key = _workflow_key(workflow)
    if key is None:
        return _workflow_not_found(workflow)

    # One argv element per input — no shell, so a value with spaces/`;`/`&` is a single unparsed token
    # (injection-safe). This is channel A: the form's token strings ARE the CLI's `name=value` args.
    tokens = [f"{name}={value}" for name, value in inputs.items()]

    # Pre-flight the FULL compile off the event loop (invariant: CPU/disk work never blocks the hub loop).
    try:
        await asyncio.to_thread(_preflight, key, tuple(tokens))
    except PflowError as exc:
        return _json({"errors": [d.to_dict() for d in exception_to_diagnostics(exc)]}, status_code=400)

    # Task 175: mint the run's execution_id HERE and force it onto the spawned run (via PFLOW_EXECUTION_ID),
    # then return it — so the browser can PIN the overlay to the exact run it just spawned instead of
    # follow-newest (which reverts to an older still-live run when this one finishes). The child's CLI pops
    # the env var into RunnerConfig.execution_id (so a node that re-shells `pflow` can't inherit + collide).
    run_id = str(uuid.uuid4())

    # Spawn DETACHED via subprocess.Popen — NOT asyncio.create_subprocess_exec (load-bearing): asyncio's
    # subprocess transport finalizer calls _proc.kill() on a still-running child, so closing `pflow ui`
    # would SIGKILL an in-flight run — the exact coupling ADR-0008 forbids. Popen returns immediately
    # after fork/exec and we retain NO handle: the child reparents to init, finished prior children are
    # reaped by subprocess._cleanup() on the next spawn. `--output-format json` makes the run record its
    # `json_output` result (for Phase 4 output inspection); stdout is DEVNULL'd (nobody reads it). The
    # child inherits the server's CWD + re-injects settings.env at startup, so it resolves exactly like a
    # hand-typed `pflow run` from the shell that launched `pflow ui`. We invoke `-m pflow.cli` (NOT
    # `-m pflow`): `pflow` is a package with no `__main__.py`, so `python -m pflow` errors; `pflow.cli` is
    # the package's documented module entry (`cli/__main__.py` → `cli_main`, same target as the `pflow`
    # console script) and runs against the server's own interpreter.
    subprocess.Popen(  # noqa: S603 — argv list, no shell; tokens are injection-safe (one element each)
        [sys.executable, "-m", "pflow.cli", "run", key, "--output-format", "json", *tokens],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ, "PFLOW_EXECUTION_ID": run_id},
    )
    return _json({"status": "spawned", "run_id": run_id})


async def activity(request: Request) -> Response:
    """Return a newest-first snapshot of recent deliberate interactions."""
    workflow = request.query_params.get("workflow")
    workflow_key = _workflow_key(workflow) if workflow else None
    if workflow and workflow_key is None:
        return _workflow_not_found(workflow)
    hub: _Hub = request.app.state.hub
    events_snapshot = hub.activity(workflow_key)
    now = time.time()
    for event in events_snapshot:
        timestamp = event.get("ts")
        event["age_seconds"] = max(0.0, now - timestamp) if isinstance(timestamp, (int, float)) else None
    return _json({"events": events_snapshot, "workflow_key": workflow_key})


def _run_is_live(candidate: TraceCandidate) -> bool:
    """EXACT liveness (Task 173): a run is live iff it hasn't finished AND its trace is still held by the
    writer's advisory lock (the kernel releases it on any process exit). Finished runs skip the probe.
    No ``fcntl`` (Windows) → ``is_trace_locked`` returns ``None`` → fall back to "incomplete = live"
    (best-effort; the hang-aware staleness backstop is GH #538)."""
    if candidate["complete"]:
        return False
    return is_trace_locked(candidate["path"]) is not False


# Git-root detection for the catalog's per-repo run buckets (Task 173 D6). A workflow's git repo is a property
# of its DIRECTORY (it never moves during a server's lifetime) and runs cluster by directory — so we cache by
# parent dir and the upward `.git` walk runs ~once per distinct folder, NOT per run or per request. A pure
# stat walk (no `git` subprocess). A `git init` mid-session needs a server restart to reflect (the standing
# "restart to refresh" semantics). The cache is unbounded but keyed on distinct dirs (a handful).
_GIT_ROOT_CACHE: dict[str, str | None] = {}
_GIT_ROOT_LOCK = threading.Lock()


def _walk_to_git_root(start: Path) -> str | None:
    """Nearest ancestor of ``start`` (inclusive) containing a ``.git`` entry, else None. ``.git`` is a FILE in
    a worktree/submodule and a DIR in a normal clone, so test ``.exists()`` (not ``.is_dir()``)."""
    cur = start
    while True:
        if (cur / ".git").exists():
            return str(cur)
        if cur == cur.parent:  # filesystem root — no repo above
            return None
        cur = cur.parent


def _git_root(workflow_path: str | None) -> str | None:
    """The git-repo root a file-backed run lives under, or None for an inline (``ir-hash:``) / pathless run or
    a file under no repo. Cached by parent directory; the I/O walk runs outside the lock (idempotent — a race
    just recomputes the same value)."""
    if not workflow_path or workflow_path.startswith("ir-hash:"):
        return None
    try:
        parent = str(Path(workflow_path).resolve().parent)
    except OSError:
        return None
    with _GIT_ROOT_LOCK:
        if parent in _GIT_ROOT_CACHE:
            return _GIT_ROOT_CACHE[parent]
    root = _walk_to_git_root(Path(parent))
    with _GIT_ROOT_LOCK:
        _GIT_ROOT_CACHE[parent] = root
    return root


def _run_entry(candidate: TraceCandidate) -> dict[str, Any]:
    """Project one raw trace candidate to a run-list entry (Task 173 D6). RAW facts only (DR-2): the UI
    composes the badge from ``complete``/``final_status``/``live``/``only_node``. ``live`` is now EXACT (the
    advisory-lock probe), not an mtime heuristic. ``git_root`` buckets ad-hoc runs by repo in the catalog
    (cached — see ``_git_root``). No raw ``node_type`` is involved (run identity, not node payload)."""
    meta = candidate["meta"]
    return {
        "run_id": meta.get("execution_id"),
        "workflow_name": meta.get("workflow_name"),
        "workflow_path": meta.get("workflow_path"),
        "start_time": meta.get("start_time"),
        "complete": candidate["complete"],
        "final_status": candidate["final_status"],
        "live": _run_is_live(candidate),
        "only_node": meta.get("only_node"),
        "trace_file": candidate["path"].name,
        "git_root": _git_root(meta.get("workflow_path")),
    }


def runs(request: Request) -> Response:
    """List runs from the trace dir, newest first (Task 173 D6 — the shared data layer for the catalog
    running-indicator, per-workflow history, and the runs dashboard).

    Bare ``GET /api/runs`` → every run; ``?workflow=X`` → that workflow's history (matched on the recorded
    ``meta.workflow_path`` via the shared ``scan_traces``). ``--only`` runs are LABELLED (``only_node``),
    NOT excluded — that exclusion is the live overlay's policy, not history's (DR-3). Inline / stdin / MCP
    runs (no file path) appear only in the bare listing; ``?workflow=<file>`` can't match them (DR-5).

    Sync handler → Starlette runs it in the threadpool, so the blocking trace-dir scan never stalls the
    event loop (it touches no hub state, so the async-handler invariant doesn't apply). ``scan_traces`` is
    defensive: a missing/empty dir and a single unreadable trace both degrade to a shorter list, never a
    throw — so this returns ``200 + []`` for "no runs". (DR-6's "non-200 on a hard scan error" is softened
    here: the scanner is shared with the live tailer and must stay non-throwing; the dominant case — one
    bad trace among many — is handled by per-file skip.)"""
    workflow = request.query_params.get("workflow")
    workflow_key = _workflow_key(workflow) if workflow else None
    if workflow and workflow_key is None:
        return _workflow_not_found(workflow)
    return _json([_run_entry(candidate) for candidate in scan_traces(workflow_key)])


def run_node(request: Request) -> Response:
    """One node's runtime record for the detail panel (Task 173 — the "This run" section).

    ``GET /api/run-node?workflow=X&ref=<json>[&run=<run_id>]`` → the ``RunNodeDetail`` for the node the
    ``ref`` (a structural ``RFRef``) identifies, read off the pinned run (``&run=``) or — unpinned — the
    newest live trace. The realized input (post-``${...}`` resolution), resolved output, cost, tokens, and
    error, with blobs resolved and secrets redacted (``run_node.run_node_detail``).

    A read-only GET of trace content — the SAME exposure class as ``/api/graph`` (the CORS / file-content
    tripwire in ``create_app`` applies; any future LIVE-RUN or mutating endpoint must revisit it). Sync
    handler → Starlette runs it in the threadpool, so the blocking trace scan never stalls the loop (it
    touches no hub state, so the async-handler invariant doesn't apply). ``404`` on an unresolvable
    ``workflow`` or no matching run/event; ``400`` on a missing/malformed ``ref``."""
    workflow = request.query_params.get("workflow")
    if not workflow:
        return _json({"error": "A 'workflow' query param is required."}, status_code=400)
    workflow_key = _workflow_key(workflow)
    if workflow_key is None:
        return _workflow_not_found(workflow)
    ref_raw = request.query_params.get("ref")
    if not ref_raw:
        return _json({"error": "A 'ref' query param is required."}, status_code=400)
    try:
        ref = json.loads(ref_raw)
    except ValueError:
        return _json({"error": "The 'ref' query param must be valid JSON."}, status_code=400)
    if not isinstance(ref, dict):
        return _json({"error": "The 'ref' query param must be a JSON object."}, status_code=400)
    # An empty ``&run=`` means "not pinned" (follow the newest run), not "match the run with id '' " → 404.
    detail = run_node_detail(workflow_key, request.query_params.get("run") or None, ref)
    if detail is None:
        return _json({"error": "No recorded detail for this node in the selected run."}, status_code=404)
    return _json(detail)


def run_inputs(request: Request) -> Response:
    """A past run's inputs as form-ready token strings, for the Run panel's re-run prefill (Task 175).

    ``GET /api/run-inputs?workflow=X&run=<id>`` → ``{ "<name>": "<token-string>" }`` — the run's
    ``meta.inputs`` with sensitive-named keys OMITTED (server-side redaction: a past run's resolved secret
    never reaches the browser) and each value rendered back to its CLI token. A read-only GET of trace
    content, same exposure class as ``/api/run-node`` (a sync handler — threadpooled, touches no hub state).
    ``400`` on a missing ``workflow``; ``404`` on an unresolvable workflow or no matching run."""
    workflow = request.query_params.get("workflow")
    if not workflow:
        return _json({"error": "A 'workflow' query param is required."}, status_code=400)
    workflow_key = _workflow_key(workflow)
    if workflow_key is None:
        return _workflow_not_found(workflow)
    run_id = request.query_params.get("run") or None
    tokens = read_run_inputs(workflow_key, run_id)
    if tokens is None:
        # None means the run wasn't found (a run that predates meta.inputs resolves to {} at 200), so name
        # the missing RUN — not "no inputs" — else a reader debugging a stale ?run= looks for the wrong cause.
        return _json({"error": f"No run {run_id!r} was found for this workflow."}, status_code=404)
    return _json(tokens)


class _BundleFiles(StaticFiles):
    """StaticFiles that makes ``index.html`` revalidate on every load.

    Vite's assets are content-hashed (immutable — heuristic caching is fine),
    but the HTML entry is not: with no ``Cache-Control`` header browsers
    heuristically reuse a stale ``index.html`` whose asset URLs point at the
    PREVIOUS build — serving a mixed old/new bundle after every rebuild (a
    recurring debugging trap; see web/CLAUDE.md). ``no-cache`` still allows
    conditional requests (304 via ``ETag``/``Last-Modified``), so reloads stay
    cheap — it forbids only *unvalidated* reuse.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        full_path = args[0] if args else kwargs.get("full_path", "")
        if Path(str(full_path)).name == "index.html":
            response.headers["Cache-Control"] = "no-cache"
        return response


def _frontend_not_built(request: Request) -> Response:
    """Fallback for any non-API path when the bundle is absent."""
    return PlainTextResponse(
        "pflow UI frontend bundle not found.\n\n"
        "The API is live at /api/catalog, /api/graph, and /api/source, but the web app has\n"
        "not been built. Build it with `make ui-build` (developers) or install\n"
        "a release wheel that ships the bundle: uv tool install 'pflow-cli[ui]'.\n",
        status_code=503,
    )


def create_app() -> Starlette:
    """Build the Starlette app: API routes, then the frontend bundle when built.

    The API routes are registered before the catch-all so ``/api/*`` is never
    shadowed by the static mount / not-built fallback.
    """
    # INVARIANT (load-bearing): Every handler below that touches the hub MUST be
    # `async def`. Starlette runs sync handlers in a threadpool, but the hub's
    # asyncio queues and deque are intentionally lock-free and event-loop-owned.
    routes: list[BaseRoute] = [
        Route("/api/catalog", catalog),
        Route("/api/graph", graph),
        Route("/api/source", source),
        Route("/api/version", version),
        Route("/api/events", events),
        Route("/api/runs", runs),
        Route("/api/run-node", run_node),
        Route("/api/run-inputs", run_inputs),
        Route("/api/health", health),
        Route("/api/command", command, methods=["POST"]),
        Route("/api/interaction", interaction, methods=["POST"]),
        Route("/api/visibility", visibility, methods=["POST"]),
        Route("/api/run", run, methods=["POST"]),
        Route("/api/activity", activity),
    ]
    if (_STATIC_DIR / "index.html").exists():
        routes.append(Mount("/", app=_BundleFiles(directory=_STATIC_DIR, html=True)))
    else:
        routes.append(Route("/{path:path}", _frontend_not_built))
    # SECURITY (load-bearing — do NOT add CORSMiddleware without re-evaluating):
    # the server binds 127.0.0.1 (cli/commands/ui.py) and sets NO CORS headers.
    # `/api/graph?workflow=<path>` reads arbitrary filesystem paths and `/api/source`
    # returns raw `.pflow.md` text, so responses can carry workflow/file contents.
    # With no `Access-Control-Allow-Origin`, a browser blocks a cross-origin page
    # from READING those responses, and mutating POSTs require `application/json`
    # (a cross-origin preflight that fails without CORS). The one way past both is
    # DNS rebinding (an attacker domain re-pointed at 127.0.0.1 → the browser sends
    # SAME-origin requests it can also read) — CLOSED for reads AND writes by the
    # `_LoopbackOnly` middleware below: a `Host`-header loopback check on EVERY
    # route. Because it's middleware (not a per-handler call), a new endpoint is
    # covered by default — no "must route through `_json_body`" invariant to forget.
    # `/api/run` (Task 175) spawns a detached `pflow run` behind this same posture:
    # a resolvable name/path only (never inline content), the normal CLI spawned, no
    # in-process execution.
    app = Starlette(routes=routes)
    app.add_middleware(_LoopbackOnly)
    app.state.hub = _Hub()
    return app


__all__ = ["create_app"]
