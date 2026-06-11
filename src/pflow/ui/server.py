"""Starlette app backing ``pflow ui``.

Endpoints:

- ``GET /api/catalog`` — saved workflows as ``[{name, description, path}]``
  (the registry list with ``ir`` stripped).
- ``GET /api/graph?workflow=<name|path>`` — the React Flow contract
  (``render_react_flow``) for one workflow, as JSON.
- ``/`` (+ assets) — the built frontend bundle, when present. Absent in a
  source checkout (the bundle is gitignored, built by ``make ui-build``); the
  server then serves a clear "not built" message instead of crashing.

The server is **stateless per request**: every ``/api/graph`` call re-resolves,
re-validates and re-builds the graph from disk. It runs no workflows and holds
no run state.

Failure regimes for ``/api/graph`` (kept distinct — do not collapse):

- a missing ``workflow`` query param → **400** (malformed request);
- a resolution / validation failure → **422** with a structured diagnostics
  body (``WorkflowGraphValidationError``);
- a build or render bug on validated IR → **500** (the exception propagates;
  never a 200-with-empty-graph).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from pflow.core.workflow.graph import render_react_flow
from pflow.core.workflow.manager import WorkflowManager
from pflow.execution.graph_service import (
    WorkflowGraphValidationError,
    resolve_validate_build,
)
from pflow.registry import Registry

# Sub-workflow expansion depth served to the client. The frontend collapses and
# expands containers client-side, so the server always ships the full tree.
_MAX_DEPTH = 5

_STATIC_DIR = Path(__file__).parent / "static"


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
        "The API is live at /api/catalog and /api/graph, but the web app has\n"
        "not been built. Build it with `make ui-build` (developers) or install\n"
        "a release wheel that ships the bundle: pip install pflow[ui].\n",
        status_code=503,
    )


def create_app() -> Starlette:
    """Build the Starlette app: API routes, then the frontend bundle when built.

    The API routes are registered before the catch-all so ``/api/*`` is never
    shadowed by the static mount / not-built fallback.
    """
    routes: list[BaseRoute] = [
        Route("/api/catalog", catalog),
        Route("/api/graph", graph),
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
    # workflow/file contents via the local user's browser. Every request here is
    # a read-only GET with no side effect; adding CORS, or any mutating/live-run
    # endpoint, must revisit this file-content exposure.
    return Starlette(routes=routes)


__all__ = ["create_app"]
