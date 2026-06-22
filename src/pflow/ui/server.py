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
- ``POST /api/command`` — validate and broadcast an agent Point command.
- ``POST /api/interaction`` — record one deliberate Viewer interaction.
- ``POST /api/visibility`` — update a Viewer's visible/backgrounded state.
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
import hashlib
import itertools
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from pflow.core.workflow.graph import render_react_flow
from pflow.core.workflow.manager import WorkflowManager
from pflow.execution.graph_service import (
    WorkflowGraphValidationError,
    resolve_validate_build,
)
from pflow.execution.workflow_resolver import resolve_workflow
from pflow.registry import Registry
from pflow.ui.targets import resolve_target

logger = logging.getLogger(__name__)

# Sub-workflow expansion depth served to the client. The frontend collapses and
# expands containers client-side, so the server always ships the full tree.
_MAX_DEPTH = 5
_ACTIVITY_MAX = 200
_CONNECTION_QUEUE_MAX = 64
_KEEPALIVE_S = 15.0

_STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class _Conn:
    conn_id: str
    workflow_key: str
    queue: asyncio.Queue[dict[str, object]]
    visibility: str
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

    def register(self, workflow_key: str, visibility: str) -> _Conn:
        conn = _Conn(
            conn_id=f"viewer-{next(self._counter)}",
            workflow_key=workflow_key,
            queue=asyncio.Queue(maxsize=_CONNECTION_QUEUE_MAX),
            visibility=visibility,
        )
        self._conns[conn.conn_id] = conn
        return conn

    def unregister(self, conn_id: str) -> None:
        self._conns.pop(conn_id, None)

    def set_visibility(self, conn_id: str, visibility: str) -> None:
        conn = self._conns.get(conn_id)
        if conn is not None:
            conn.visibility = visibility

    def windows_for(self, workflow_key: str) -> list[_Conn]:
        return [conn for conn in self._conns.values() if conn.workflow_key == workflow_key]

    def broadcast(self, workflow_key: str, message: dict[str, object]) -> list[_Conn]:
        conns = self.windows_for(workflow_key)
        sent: list[_Conn] = []
        for conn in conns:
            try:
                conn.queue.put_nowait(message)
            except asyncio.QueueFull:
                # A socket that cannot consume 64 human-paced UI commands is
                # no longer a truthful delivery target. Evict it rather than
                # leak memory or report another command as sent.
                conn.active = False
                self.unregister(conn.conn_id)
            else:
                sent.append(conn)
        return sent

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

    hub: _Hub = request.app.state.hub

    async def stream() -> AsyncIterator[str]:
        conn = hub.register(workflow_key, visibility)
        try:
            yield f"data: {json.dumps({'type': 'connected', 'conn_id': conn.conn_id})}\n\n"
            while conn.active:
                try:
                    message = await asyncio.wait_for(conn.queue.get(), timeout=_KEEPALIVE_S)
                    yield f"data: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    # Load-bearing: a periodic send surfaces silently-dead sockets
                    # under ASGI spec >=2.4 and also defeats idle proxy timeouts.
                    yield ": keepalive\n\n"
        finally:
            hub.unregister(conn.conn_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def command(request: Request) -> Response:
    """Validate and broadcast one agent Point command."""
    body = await _json_body(request)
    if isinstance(body, Response):
        return body

    workflow = _string_field(body, "workflow")
    command_type = _string_field(body, "type")
    if workflow is None or command_type not in {"focus", "frame", "clear"}:
        return _json(
            {"error": "Fields 'workflow' and type ('focus', 'frame', or 'clear') are required."},
            status_code=400,
        )
    workflow_key = _workflow_key(workflow)
    if workflow_key is None:
        return _workflow_not_found(workflow)

    hub: _Hub = request.app.state.hub
    if command_type == "clear":
        return _json(_dispatch_report(workflow_key, hub.broadcast(workflow_key, {"type": "clear"})))

    target = _string_field(body, "target")
    if target is None:
        return _json({"error": f"Command type {command_type!r} requires a non-empty target."}, status_code=400)
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

    conns = hub.broadcast(
        workflow_key,
        {"type": command_type, "target": resolution.descriptor},
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
        Route("/api/command", command, methods=["POST"]),
        Route("/api/interaction", interaction, methods=["POST"]),
        Route("/api/visibility", visibility, methods=["POST"]),
        Route("/api/activity", activity),
    ]
    if (_STATIC_DIR / "index.html").exists():
        routes.append(Mount("/", app=_BundleFiles(directory=_STATIC_DIR, html=True)))
    else:
        routes.append(Route("/{path:path}", _frontend_not_built))
    # SECURITY (load-bearing — do NOT add CORSMiddleware without re-evaluating):
    # the server binds 127.0.0.1 (cli/commands/ui.py) and sets NO CORS headers.
    # `/api/graph?workflow=<path>` reads arbitrary filesystem paths, and a
    # resolution failure returns a 422 whose diagnostics may echo a source line.
    # With no `Access-Control-Allow-Origin`, a browser blocks any cross-origin
    # page from READING that response — so a malicious site can't exfiltrate
    # workflow/file contents via the local user's browser. Mutating POSTs require
    # `Content-Type: application/json`, forcing a cross-origin preflight that
    # fails without CORS; EventSource likewise cannot read commands cross-origin.
    # The worst write is benign UI state (focus/frame/clear in the user's own
    # Viewer), never a file/system mutation. Any future mutating or live-run
    # endpoint must revisit this exposure.
    app = Starlette(routes=routes)
    app.state.hub = _Hub()
    return app


__all__ = ["create_app"]
