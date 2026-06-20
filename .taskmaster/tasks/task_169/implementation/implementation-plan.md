# Task 169 — Agent↔Browser Interaction Channel (Point & Watch)

> Implementation plan for an agent executing in isolation. Every file:line anchor was verified by
> codebase search (2026-06-18/19) and hardened by a 4-agent deep-review (plan / concurrency /
> agent-ux / feature-interactions) — see "Review hardening" at the end for what each fix traces to.
> Re-confirm a line number if a file has moved. Vocabulary is fixed in `context/CONTEXT.md`
> (**Viewer, Point, Watch, Auto-update**).

## Context — why this exists

The `pflow ui` viewer (Task 168) is one-way: the server answers read-only GETs, and an AI agent can
only *see* the user's canvas via its own headless-browser screenshots — it cannot act in the
**user's** window. Observed trigger: while discussing the UI, the user said *"I can't find it"* about
a node the agent was describing, with no way to point at it.

This adds a bidirectional channel: the agent can **Point** (focus/frame/clear a target in every open
Viewer showing a workflow, reusing the exact selection a user click produces) and **Watch** (read a
snapshot of the user's recent deliberate interactions). It also builds the **SSE push transport** the
deferred live-run overlay (Task 133) will ride — this task owns the *channel + a vocabulary-agnostic
envelope*, NOT any run-event schema.

Outcome: with a workflow open in a real browser, `pflow ui focus <wf> <target>` focuses/reveals it
without a reload; the command reports how many windows received it and whether each is visible or
backgrounded; `pflow ui user-activity <wf>` shows what the user just clicked, newest-first, with
relative ages.

## Scope (decided with the user)

**v1 Point targets:** node, container (sub-workflow / batch box), workflow/sub-workflow IO port, and
**data edge** (`from -> to`). **Watch** covers deliberate interactions only.

**Deferred (documented fast-follows):** standalone body-row targets (pointing at `gen.response`
*alone*, not as an edge endpoint — `RFRef` has no field-level identity); control/branch edges
(no `${ref}` to name them by); a `--follow` activity livestream; replacing the Auto-update poll with
an SSE push.

---

## Architecture overview

```
CLI verb (httpx)  --POST /api/command-->  Server hub  --SSE /api/events-->  Browser (events.ts)
                                              |                                    |
Browser  --POST /api/interaction / /api/visibility-->  hub ring + conn registry    |
CLI verb (httpx)  --GET /api/activity-->  hub ring                          GraphView focus/camera
```

- **Transport:** SSE (server→browser commands) + plain JSON POST/GET. No WebSocket.
- **Envelope (the overlay's seam — keep generic):** every SSE frame is
  `data: {"type": "<str>", ...payload}\n\n`. v1 defines `connected`, `focus`, `frame`, `clear`. The
  future overlay adds run-event `type`s over the same pipe; do NOT define any run-event schema here.
- **The server resolves; the browser is a dumb display; flat ids never cross the wire.** The server
  parses the agent's target string, resolves it against the freshly-built `RFGraph` to a **structural**
  identity (`RFRef = {node_id, ancestor_path, port}`; an edge = a pair of those + `input_name`), and
  broadcasts that. The browser maps the structural identity to its *own* current flat id via the
  existing `sameRef` machinery. Flat ids (`n3`/`g2`/`e7`) are positional, unstable across rebuilds, and
  the server's render won't match the browser's — only structural identity is valid between two
  independent renders. **One parser (Python, fully unit-testable).**

---

## Server (`src/pflow/ui/server.py`)

### The hub (first stateful, in-memory, per-app-instance)

Add a `_Hub` class; attach one instance to `app.state.hub` in `create_app()`. Handlers read
`request.app.state.hub`.

```python
_ACTIVITY_MAX = 200
_KEEPALIVE_S = 15

# INVARIANT (load-bearing — keep this exact comment at _Hub AND at the route list):
# Every handler that touches the hub MUST be `async def`. Starlette runs async handlers on the
# event loop and sync `def` handlers in a threadpool thread. asyncio.Queue is loop-affine and NOT
# thread-safe — a sync handler calling put_nowait / mutating the deque would race the loop with no
# lock. Do NOT add a sync hub-touching handler. (The 4 existing sync GET handlers never touch it.)

@dataclass
class _Conn:
    conn_id: str
    workflow_key: str
    queue: asyncio.Queue          # of dict (envelopes)
    visibility: str               # "visible" | "hidden"

class _Hub:
    def __init__(self) -> None:
        self._conns: dict[str, _Conn] = {}
        self._activity: deque[dict] = deque(maxlen=_ACTIVITY_MAX)
        self._counter = itertools.count(1)        # conn-id source (deterministic for tests)
    def register(self, workflow_key, visibility) -> _Conn: ...   # mints conn_id + Queue
    def unregister(self, conn_id) -> None: ...
    def set_visibility(self, conn_id, visibility) -> None: ...
    def windows_for(self, workflow_key) -> list[_Conn]: ...
    def broadcast(self, workflow_key, message) -> list[_Conn]:   # put_nowait each match; ret delivered
    def record(self, event) -> None: ...
    def activity(self, workflow_key=None) -> list[dict]: ...      # filtered, newest-first
```

`create_app()` (`server.py:263-288`): build `app = Starlette(routes=...)`, set `app.state.hub = _Hub()`,
`return app`. Add the five new `Route(...)` **before** the static `Mount`/catch-all (the
`/api/*`-before-catch-all rule, `server.py:266-278`). The hub is **per-app-instance**: the 28
`TestClient(create_app())` sites get isolated hubs automatically; the single `uvicorn.run(app)`
process has exactly one. Do NOT use a module-level singleton.

### Workflow-key normalization (groups name-opened and path-opened Viewers together)

```python
def _workflow_key(value: str) -> str | None:
    p = Path(value)
    if p.suffix == ".pflow.md" or p.exists():
        return str(p.resolve())
    wm = WorkflowManager()
    if wm.exists(value):                                  # manager.py:366 — REAL fs check
        return str(Path(wm.get_path(value)).resolve())    # .resolve() so a symlinked library path
                                                          # matches the catalog's resolved path
    return None                                           # unknown name → caller reports actionably
```

`get_path` does NOT raise — it returns a phantom path for any string (`manager.py:304/62`), so the
prior `try/except` was dead code and a typo'd name silently mapped to a never-matching key. The
`exists()` gate is load-bearing. On `None`, the command handler returns an actionable not-found:
`find_similar_items(value, WorkflowManager().list_names(), method="fuzzy")` → "no workflow 'X'; did
you mean: …". The command response also **echoes the resolved key** so a residual name-vs-path
mismatch is visible to the agent.

### Endpoints (all `async def` — see the hub INVARIANT; all new; before the static mount)

1. **`GET /api/events?workflow=<name|path>&visibility=<visible|hidden>`** — SSE subscribe.
   `async def` → `StreamingResponse(gen(), media_type="text/event-stream")`:
   ```python
   async def gen():
       conn = hub.register(key, visibility)
       try:
           yield f'data: {json.dumps({"type":"connected","conn_id":conn.conn_id})}\n\n'
           while True:
               try:
                   msg = await asyncio.wait_for(conn.queue.get(), timeout=_KEEPALIVE_S)
                   yield f"data: {json.dumps(msg)}\n\n"
               except asyncio.TimeoutError:
                   yield ": keepalive\n\n"      # forces a periodic send() → see below
       finally:
           hub.unregister(conn.conn_id)
   ```
   **The periodic keepalive yield is load-bearing for disconnect cleanup, not optional.** A generator
   blocked forever on `queue.get()` is NOT woken on a silently-dropped tab when `StreamingResponse`
   runs under ASGI `spec_version >= 2.4` (httptools / `uvicorn[standard]` / a uvicorn bump) — it only
   notices a dead socket when it next `send()`s. The keepalive `yield` forces a periodic `send()`, so
   a dead socket surfaces (`ClientDisconnect`/`OSError`) on EITHER ASGI version, firing `finally`. Do
   NOT substitute `request.is_disconnected()`: on the spec<2.4 path `StreamingResponse` already
   consumes `receive()` via its own disconnect listener, and a second `receive()` consumer is
   undefined. (Today's stack — uvicorn 0.35 h11 = spec 2.3 — works either way; the keepalive makes it
   version-independent and also defeats idle-proxy timeouts.)

2. **`POST /api/command`** — the agent's Point. **Require `Content-Type: application/json`** (else 415
   with a body naming the required header). Body `{workflow, type: "focus"|"frame"|"clear", target?}`.
   - Normalize the workflow → `_workflow_key`. If `None` (unknown name) → 404-style actionable
     not-found with fuzzy `list_names()` suggestions (do not broadcast).
   - `type=="clear"`: `hub.broadcast(key, {"type":"clear"})`; return delivery report.
   - `type in ("focus","frame")`: build the graph + resolve the target (below). On
     `WorkflowGraphValidationError` → 422 with diagnostics (mirror `graph` handler `server.py:106`).
     - **0 matches** → `{"resolved":{"matched":0,"suggestions":[...fuzzy node-ids...]}, "delivered":0}`
       (no broadcast).
     - **>1 match** → `{"resolved":{"matched":N,"qualify":[<fully-qualified addrs>]}, "delivered":0}`
       (no broadcast — never point at a guess; the agent re-points with a qualified address).
       **Each `qualify` entry MUST resolve to exactly 1 element** (test it — the self-correcting loop
       must converge).
     - **1 match** → `hub.broadcast(key, {"type":type, "target":<descriptor>})`; return
       `{"resolved":{"matched":1,"address":<addr>}, "delivered":len(conns),
       "windows":[{"visibility":c.visibility} for c in conns], "workflow_key":key}`.

3. **`POST /api/interaction`** — Watch report (fire-and-forget). Require JSON. Body
   `{workflow, type, target?, view_state}`. `hub.record({..., "workflow_key":_workflow_key(workflow),
   "ts": time.time()})`; return `204`.

4. **`POST /api/visibility`** — Require JSON. Body `{conn_id, visibility}`. `hub.set_visibility(...)`;
   return `204`.

5. **`GET /api/activity?workflow=<name|path optional>`** — Watch read (a **snapshot**, not a stream).
   Return `{"events": [...], "workflow_key": <resolved or null>}`, newest-first, each event annotated
   with `age_seconds = time.time() - ev["ts"]` (single clock — CLI + server share localhost).

### Target resolution (`src/pflow/ui/targets.py` — new module, pure, unit-tested)

Generate the canonical address(es) of every addressable element and match the target against them —
this sidesteps parse ambiguity (the server *generates* from real metadata, so it knows which dotted
segment is a field vs a scope host). **The agent-facing address string MUST carry everything `RFRef`
carries — it drops nothing — or two in-scope target classes become un-disambiguatable (an input
`data` and output `data` both stringify to `data`; batch items 0 and 1 both stringify to `fanout.gen`,
yielding a useless qualify list of identical strings).**

```python
def resolve_target(rf: RFGraph, target: str) -> TargetResolution:
    # Build (canonical_addresses: set[str], descriptor) for every addressable element.
    # scope_prefix(ancestor_path) = "".join(step.node_id + (f"[{i}]" if step.batch_index==i else "") + "."
    #                                        for step in ancestor_path)
    #  - node (port=None):  bare = node_id ; scoped = scope_prefix + node_id   (e.g. "fanout[0].gen")
    #                       descriptor = {"kind":"node","ref": ref_dict}
    #  - IO port (port in {"in","out"}):  PREFIX THE SIDE -> "in:" + addr / "out:" + addr
    #                       (so input "data" and output "data" are DISTINCT addresses)
    #                       descriptor = {"kind":"node","ref": ref_dict}
    #  - container:  via its host node (RFGroup.host -> RFNode.id -> .ref); same addrs as host node.
    #  - data edge (kind=="data_flow" only):  f"{src_ep} -> {tgt_ep}"
    #        src_ep = <src node addr> + ("."+output_field) + ("."+".".join(output_path) if any)
    #        tgt_ep = <tgt node addr> + ("."+input_name)
    #        descriptor = {"kind":"edge","source":src_ref,"source_field":output_field,
    #                      "target":tgt_ref,"input_name":input_name}
    # RFEdge.source/target are FLAT node ids (react_flow.py:339) -> first build {flat_id: RFNode} to
    # recover each endpoint's .ref. Restrict to kind=="data_flow".
    # Match (normalize whitespace around "->"): matched = [e for e in elements if target in e.addresses]
    #   0  -> suggestions = find_similar_items(target, bare_node_ids, method="fuzzy")   # NOT substring
    #   1  -> resolve + broadcast
    #   >1 -> qualify = [most-qualified (scoped) addr of each match]  (each resolves to exactly 1)
```

Match against the **`RFGraph`** (what's on the canvas — batch truncation keeps ≤2 representatives, so
hidden items aren't addressable, which is correct). The broadcast **descriptor is the full `RFRef`**
(already carries `port` + `ancestor_path[batch_index]`); only the agent-facing STRING needed the
port/batch_index fix. Reused: `resolve_validate_build(workflow, max_depth=_MAX_DEPTH)`
(`graph_service.py:50`) → `render_react_flow(model)` (`react_flow.py:172`); `find_similar_items(...,
method="fuzzy")` + `format_did_you_mean` (`suggestion_utils.py:14/77`).

### Security (extend the comment at `server.py:279-287`)

Keep binding `127.0.0.1`, keep **no CORS**. Extend to cover the new endpoints: the mutating POSTs
**require `Content-Type: application/json`** → a cross-origin page is forced into a CORS preflight
that fails → unreachable cross-origin (do NOT use `navigator.sendBeacon` for the interaction report —
it sends a CORS-safelisted type and bypasses this). `GET /api/events` streams commands; a cross-origin
`EventSource` can't read the body without CORS headers. Worst case if a write lands: focusing a node in
the user's own Viewer — no file/system effect.

---

## Frontend (`web/`)

### New: `web/src/api/events.ts` (mirror `client.ts` — relative paths, `ApiError` shape)

- `subscribe(workflow, handlers)`: `new EventSource("/api/events?workflow=…&visibility="+document.visibilityState)`.
  Store `conn_id` from the `connected` message; dispatch others by `msg.type`; add a
  `visibilitychange` listener POSTing `/api/visibility {conn_id, visibility}`. Return an unsubscribe
  that closes the source + removes the listener. **Validate** each message shape before dispatch
  (`client.ts:60-68` discipline).
- `reportInteraction(workflow, event)`: `fetch("/api/interaction", {method:"POST", keepalive:true,
  headers:{"Content-Type":"application/json"}, body: JSON.stringify({workflow, ...event})}).catch(()=>{})`
  — fire-and-forget; never throws into the UI.

### New helper in `web/src/graph/remap.ts`: `flatIdForRef`

```ts
export function flatIdForRef(graph: RFGraph, ref: RFRef): string | null {
  return graph.nodes.find((n) => sameRef(n.ref, ref))?.id ?? null;   // sameRef exists, remap.ts:16
}
```

### Edge-by-endpoints lookup (the one substantial new mapping; code marks it "deferred", `useCameraNavigation.ts:78`)

Resolve `{source, source_field, target, input_name}`: `flatIdForRef` each ref, then find the FlowEdge
by its **`data.from`/`data.to`** (the original contract endpoints the focus-reveal styling keys on,
`GraphView.tsx:288`, `flow.ts:1075-1076`) — **NOT** `edge.source`/`edge.target` (renderAnchor-resolved;
they differ exactly when an endpoint is suppressed/re-anchored). Pin the chosen mapping with a
`flow.test.ts` assertion. Collapsed endpoint → re-anchored, discrete edge absent → return an explicit
"endpoint collapsed; focus an endpoint node instead" outcome (no silent no-op).

### `web/src/views/GraphView.tsx` wiring

On mount `subscribe(workflow, handlers)` (unsubscribe on unmount / workflow change). Map a
server-resolved descriptor onto the **existing** entry points — no new focus mechanics:
- `focus` + node: `flatIdForRef` → `RFNode` → **`onSelectNode(node)`** (`GraphView.tsx:390` — already
  expands collapsed ancestors + focus + select + pan).
- `focus` + edge: edge-by-endpoints lookup → `setFocus(edgeId)` + `setSelectedId(edgeId)` (mirrors
  `onEdgeClick`, `:237`). **Must reveal a default-hidden data edge in beautiful** — a data edge is
  `hidden:true` in compact density (`flow.ts:1090`), revealed only on incident focus. Verify
  `onEdgeClick`/`applyFocus` un-hides a directly-focused edge; if it doesn't, the handler clears
  `hidden` on that edge, else `focus "a.x -> b.y"` delivers-but-shows-nothing in the default density.
- `frame` + node/edge: resolve to the **visible on-canvas representative** via
  `resolveEndpointFlatId`/`nodeRepresentativeId` (`viewParams.ts:111/132` — returns the nearest visible
  ancestor when the target is collapsed), then `useReactFlow().fitView({nodes:[{id}], padding:0.45,
  maxZoom:1.2, duration:300})` (recipe `useCameraNavigation.ts:102/143`; expose a focus-free variant).
  **Never `fitView` a flat id that exists structurally but is hidden in a collapsed container** (large
  workflows >60 nodes open fully collapsed → `fitView` on an off-canvas id is a silent no-op while the
  command falsely reports `delivered>0`). If unresolvable to anything on-canvas, the browser reports it.
- `clear`: `onPaneClick()` (`:261`).

Wire `reportInteraction` into the deliberate handlers ONLY (never hover/pan/zoom): `onNodeClick`,
`onEdgeClick`, `focusPort`, the clear in `onPaneClick`, `changeDensity`, `changeDirection`, and the
workflow open/switch in `App.tsx`. Report the **structural** target
(`graph.nodes.find(n=>n.id===flatId)?.ref` → `{node_id, ancestor_path}`; for an edge, both endpoint
identities) + `view_state = {density: DENSITY_TO_PARAM[density], direction, focus:<current focus →
node_id|null>}`. **Export `DENSITY_TO_PARAM`** (`viewParams.ts:43`, currently unexported) so events
carry agent-facing words (`advanced`/`beautiful`), not code words (`detailed`/`compact`).

---

## CLI (`src/pflow/cli/commands/ui.py`)

### Restructure: a CUSTOM `UiGroup(click.Group)` — NOT a plain `@click.group`

A plain `@click.group(invoke_without_command=True)` with a positional `WORKFLOW` **cannot coexist with
subcommands** in Click (reproduced: `pflow ui focus <wf> <target>` → "No such command 'my-wf'";
`pflow ui <wf> --no-open` → "No such command '--no-open'"). The working idiom is the repo's own
`PflowCLI` (`main.py:18-49`, documented in `cli/CLAUDE.md` "How routing works"): a `click.Group`
subclass with `ignore_unknown_options = True` and a custom `resolve_command` that routes a
non-subcommand first arg to a hidden default command.

Mirror it exactly:
- `class UiGroup(click.Group): ignore_unknown_options = True`, and `resolve_command(ctx, args)`: if
  `not args` OR `args[0]` is not a known subcommand → route to the hidden `serve` command
  (`return "serve", self.get_command(ctx,"serve"), args`); else normal dispatch.
- `ui_cmd = @click.group(cls=UiGroup, name="ui", invoke_without_command=True)`; registration unchanged
  (`main.py:151/168`, `cli.add_command(ui_cmd)`).
- Hidden `@ui_cmd.command(name="serve", hidden=True, context_settings={"ignore_unknown_options": True})`
  with the `WORKFLOW` arg + `--port`/`--no-open`/`--no-auto-update`, holding **today's serve body
  verbatim** (`ui.py:89-142`). **Keep the `create_app`/`uvicorn`/`starlette` imports INSIDE `serve`**
  (the lazy-import boundary test `test_ui.py:664` asserts `pflow.ui.server` isn't imported by importing
  the command module). New subcommands import only `httpx` (core dep) — safe to import eagerly.

Result: `pflow ui` / `pflow ui <wf>` / `pflow ui <wf> --no-open --port N` all reach `serve` (so the
existing tests `test_ui.py:593/628` pass unchanged); `pflow ui focus|frame|clear-focus|user-activity`
dispatch to subcommands. Name-collision: a saved workflow named `focus`/`frame`/`clear-focus`/
`user-activity` is reachable via the path form `pflow ui ./focus.pflow.md` (document in `--help`).
**Add a test for subcommand dispatch AND for the preserved bare-serve forms.**

### Four thin-client subcommands (`@ui_cmd.command()`), all `httpx`, all with a `--json` flag

Shared helper handles BOTH connection and HTTP-status errors (neither pattern exists in the repo yet):
```python
def _request(ctx, port, method, path, **kw):
    import httpx
    try:
        r = httpx.request(method, f"http://127.0.0.1:{port}{path}", timeout=5, **kw)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        click.echo(f"No pflow ui server on port {port}.\n→ start one: pflow ui {workflow}", err=True)
        ctx.exit(1)
    except httpx.HTTPStatusError as e:
        body = e.response.json() if "json" in e.response.headers.get("content-type","") else {}
        if e.response.status_code == 422:                 # mid-edit-invalid source
            for d in body.get("errors", []):
                click.echo(format_diagnostic(d), err=True)   # the diagnostic the CLI already renders
        elif e.response.status_code == 415:
            click.echo("Server requires Content-Type: application/json (client bug).", err=True)
        else:
            click.echo(f"Server error {e.response.status_code}: {body}", err=True)
        ctx.exit(1)
```
Each subcommand: `--json` boolean flag (the `list.py` idiom — there is no `--output-format` convention
for subcommands); when set, `click.echo(json.dumps(payload, indent=2))` of the server's structured
body and return; else the text render below. **JSON mode exposes the per-window `visibility` array**,
not just an aggregate, so an agent can reason "all backgrounded → tell the user to switch tabs".

- **`pflow ui focus <workflow> <target> [--open] [--json] [--port]`** → `POST /api/command` `focus`.
  `--open` when `delivered==0`: non-edge target → open `?workflow=<wf>&focus=<target>` (load-time
  `?focus=` resolves node/container/IO); **edge target** → open `?workflow=<wf>` then re-POST every
  ~0.25s until `delivered>0` or a 15s timeout (the load-time `?focus=` can't parse `from -> to`). On
  **timeout**, print a DISTINCT message: "opened a window but it didn't connect within 15s — re-run
  `pflow ui focus …` now that it may be up" (never the plain `0 windows` report — that's misleading
  after an open). `--open` gates strictly on `delivered==0` (never duplicates a backgrounded window).
- **`pflow ui frame <workflow> <target> [--json] [--port]`** → `frame`.
- **`pflow ui clear-focus <workflow> [--json] [--port]`** → `clear`.
- **`pflow ui user-activity [workflow] [--json] [--port]`** → `GET /api/activity`; newest-first with
  relative ages + addressing notation; ALWAYS print an explicit count line; echo the resolved
  `workflow_key`; distinguish "server up, no interactions recorded" from "none for workflow key X
  (is a window open on it?)".

### Text report shapes (agent-first; the `--json` payload is the server body verbatim)

```
focus 'fetch-data' in 'my-wf':  resolved 1 (fetch-data) · delivered to 2 windows (1 visible, 1 backgrounded)
  workflow key: /abs/.../my-wf.pflow.md
focus 'gen' in 'my-wf':  ambiguous — 2 matches, not delivered. Qualify with one of:
    create-songs.gen
    remix.gen
focus 'fetchdata' in 'my-wf':  not found. did you mean: fetch-data, fetch-config?   # FUZZY, not substring
focus 'fetch-data' in 'my-wf':  resolved 1 · 0 windows open.
  → re-run with --open, or run `pflow ui my-wf`
user-activity 'my-wf' (0 events)  — server up, no interactions recorded yet.
```
(Run `review-agent-ux` once more on the final strings.)

### Rename `--no-watch` → `--no-auto-update` (flag only; keep the internal `?watch=0` URL param)

Rename: `ui.py` option/help/param/docstrings (`:57/60/63/72-73/83`); the URL builder keeps emitting
`watch=0` (`:123-124`). Docs: `docs/reference/cli/index.mdx:493`,
`src/pflow/guide/features/visualization.md:28`, `src/pflow/ui/CLAUDE.md:116/123`. Also update the stale
description string `(pflow ui --no-watch)` in `web/src/utils/viewParams.test.ts:23` (won't fail — it
tests the `watch` URL param, unchanged — but it's agent-facing drift). Leave the rest of `web/`
untouched (the `?watch` param is an internal CLI↔frontend contract).

---

## Implementation order (phases)

0. **Write the ADR amendment FIRST** (`context/adr/`, amending/citing ADR-0005): the UI server gains
   its first stateful, push-capable layer (SSE + in-memory registry); it carries UI-interaction
   vocabulary and is the transport the deferred run-overlay rides, but does NOT define a run-event
   schema. This reopens a recorded "read-only, stateless, no side effects" decision (`server.py:279`,
   `ui/CLAUDE.md`) — pin it before code or a validation-consistency reviewer treats the stateful
   server as an unjustified regression.
1. **Server hub + 5 endpoints + `targets.py` + security comment.** Pure-Python, browser-free. The
   overlay's transport seam; land first.
2. **Frontend `events.ts` + `flatIdForRef` + edge-lookup + GraphView wiring + focus-free `frame`
   camera + interaction reporting.** `make ui-build` (output → `src/pflow/ui/static/`, gitignored).
3. **CLI `UiGroup` restructure + hidden `serve` + 4 subcommands + `--open` + `--no-watch` rename.**
4. **Docs:** `src/pflow/ui/CLAUDE.md` (endpoints, the hub + per-app-instance/no-persistence note,
   security extension, name-collision, the async-only INVARIANT), `web/CLAUDE.md` (`events.ts` exists).
   Flip Task 169 → ✅ in root `CLAUDE.md`.

## Edge cases to handle (verified)

- **Dropped tab (incl. silent drop):** the keepalive-yield SSE loop surfaces the dead socket → `finally:
  hub.unregister` → next command reports the corrected count.
- **Mid-edit-invalid source:** `/api/command` → 422 diagnostics (CLI renders via `format_diagnostic`,
  not a traceback); `/api/activity`/`/api/visibility` unaffected.
- **Ambiguous target:** not delivered; qualify list of fully-qualified addresses, each resolving to 1.
- **IO in/out + body-name collision; batched sub-workflow interiors:** addresses carry `in:`/`out:`
  and `[batch_index]` so the qualify list is distinct + actionable.
- **Collapsed node/frame target (large auto-collapsed workflow):** resolve via the visible
  representative; never frame an off-canvas id; report if unresolvable.
- **Collapsed edge endpoint:** re-anchored → explicit "endpoint collapsed" outcome.
- **Default-density (beautiful) data-edge focus:** the focus must un-hide the edge.
- **Name vs path Viewer split:** `_workflow_key` normalizes both to the resolved entry path (symlinks
  included); the key is echoed.
- **Unknown workflow name:** actionable not-found with fuzzy suggestions (not a silent 0-window).
- **`--open` duplicate / backgrounded-only / zero windows / edge-open timeout:** each a distinct
  message (see CLI).

## Test strategy

- **Hub unit tests** (`tests/test_ui/test_hub.py`, new): register/broadcast/`windows_for`/visibility/
  ring bound+newest-first+age. **Cleanup MUST be tested here** (register→unregister→count drops) —
  see the next bullet.
- **SSE cleanup CANNOT be tested via `TestClient`** — its `receive()` never emits `http.disconnect`
  for an infinite generator, so a `client.stream(...)` "cleanup" test passes green WITHOUT exercising
  cleanup (false confidence). Test cleanup via (a) the `_Hub` unit tests above and (b) a raw-ASGI scope
  driving `gen()` with an injected `http.disconnect`. Use `client.stream(...)` only to assert the
  `connected` frame + one broadcast frame.
- **`targets.py` unit tests** (new): flat workflow; nested sub-workflow with duplicate `node_id`;
  literal batch (N>4) of a sub-workflow; input+output sharing a name; a data edge. Assert
  node/container/IO/edge resolution, scoped + `in:`/`out:` + `[i]` disambiguation, 0→fuzzy suggestions,
  and that **every emitted `qualify` address resolves to exactly 1 element**.
- **Endpoint integration** via `TestClient(create_app())`: `/api/command` delivery counts, 415 on
  non-JSON, 422 on invalid source, the unknown-workflow not-found; `/api/activity` shape + empty case.
- **CLI tests** (`CliRunner`): bare serve preserved (`test_ui.py:593/628` green; patch
  `_port_available`/`uvicorn.run`/`webbrowser.open`); subcommand dispatch; `httpx.ConnectError` →
  actionable hint + exit 1; `httpx.HTTPStatusError` 422 → rendered diagnostics (not traceback);
  `--json` payload; `--open` dedup gating + edge-timeout message.
- **Frontend** (jsdom — state/transform only): `flatIdForRef`, the edge-by-endpoints lookup keyed on
  `data.from`/`data.to` (pinned in `flow.test.ts`), the flat-id↔node_id reporting map. Visual
  focus/reveal + the beautiful-density edge un-hide → real browser via
  `.claude/skills/screenshot-pflow-web-ui`.
- **All Task 168 server tests stay green** (four `/api/graph` arms, catalog, static, 503, lazy-import).

## End-to-end verification (the originating scenario)

1. `pflow ui my-wf` (browser opens). Second terminal: `pflow ui focus my-wf fetch-data` → the window
   focuses/reveals it, no reload; output `delivered to 1 window (1 visible)`.
2. Second window same workflow → re-run → `2 windows`.
3. Background the tab → report says `backgrounded`. Close it (incl. a hard close) → next focus reports
   the corrected count.
4. No window → `0 windows` + hint; `--open` opens focused (node) or opens+delivers-once-connected
   (edge); a backgrounded window present → `--open` does NOT duplicate.
5. `pflow ui focus my-wf "gen.response -> summarize.prompt"` → the data line lights (even in beautiful).
6. Click a node → `pflow ui user-activity my-wf` shows it with the right `node_id` + view state +
   relative age; hover/pan produce nothing. `pflow ui focus my-wf --json …` emits a parseable body.

## Reused functions / anchors (do not re-implement)

- `resolve_validate_build` `graph_service.py:50` · `render_react_flow` `react_flow.py:172` ·
  `WorkflowGraphValidationError` `graph_service.py:33` · `_json` `server.py:64` · `create_app`
  `server.py:263` · `WorkflowManager.{exists:366, get_path:304, list_names:315}` ·
  `find_similar_items(method="fuzzy")` + `format_did_you_mean` `suggestion_utils.py:14/77` ·
  `format_diagnostic` (CLI diagnostic render).
- `RFRef/RFNode/RFEdge/RFGroup` `react_flow.py:36/88/126/147`; `(node_id, ancestor_path, port)` unique
  key (`model.py:18`); `RFEdge.source/target` are flat ids (`react_flow.py:339`).
- `sameRef` `remap.ts:16` · `onSelectNode` `GraphView.tsx:390` · `onEdgeClick` `:237` · `onPaneClick`
  `:261` · `focusPort` `:274` · `resolveEndpointFlatId`/`nodeRepresentativeId` `viewParams.ts:111/132` ·
  `fitView` recipe `useCameraNavigation.ts:102` · `DENSITY_TO_PARAM` `viewParams.ts:43` ·
  `data.from`/`data.to` keying `flow.ts:1075`, `GraphView.tsx:288` · `client.ts` (`ApiError`) `:9`.
- CLI: serve body `ui.py:89-142` · helpers `ui.py:17/28` · `PflowCLI` idiom `main.py:18-49` +
  `cli/CLAUDE.md` "How routing works" · registration `main.py:151/168` · `--json` idiom `list.py:15-46`
  · `httpx` core dep `pyproject.toml:36`.

## Out of scope / fast-follows (state in `ui/CLAUDE.md`)

Standalone body-row targets (need a field-level descriptor beyond `RFRef`); control/branch edges;
`user-activity --follow` livestream (same bus, "when a consumer exists"); SSE replacing the Auto-update
poll; any run-event schema (Task 133 boundary — envelope stays vocabulary-agnostic).

---

## Review hardening (deep-review, 4 agents) — what each fix traces to

- **CLI group is a custom `UiGroup` (not a plain group)** — review-plan C1 (reproduced: plain
  group+positional+subcommands breaks both the headline command and existing tested serve forms).
- **Address string carries `port` (`in:`/`out:`) + `batch_index` (`[i]`)** — review-feature-interactions
  (the scheme was lossier than `RFRef`; IO-name collisions and batched interiors gave identical
  un-disambiguatable qualify entries).
- **SSE keepalive-yield (not bare `try/finally`, not `is_disconnected()`)** — review-concurrency W1
  (cleanup silently breaks on ASGI spec≥2.4; `is_disconnected` double-consumes `receive()` on spec<2.4).
- **SSE cleanup tested via `_Hub` + raw-ASGI, not `TestClient`** — review-concurrency W2 (TestClient
  can't deliver `http.disconnect` to an infinite generator → false-green).
- **Async-only hub INVARIANT comment names the specific failure** — review-concurrency W3.
- **`_workflow_key` gates on `exists()` + `.resolve()`; unknown name → fuzzy not-found** — review-plan
  W1 (dead `try/except`; phantom-path → silent 0 windows) + review-feature-interactions (symlink).
- **`frame`/focus resolve via the visible representative; never frame an off-canvas id** —
  review-feature-interactions (auto-collapse silent false-delivery).
- **Edge lookup keyed on `data.from`/`data.to`; beautiful-density edge un-hide** —
  review-feature-interactions (+ review-plan W3: pin with a `flow.test.ts` assertion).
- **`--json` flag + structured passthrough; per-window visibility in JSON** — review-agent-ux C1.
- **Fuzzy `not-found` suggestions (not substring)** — review-agent-ux C2 (the substring example was
  impossible).
- **`_request` handles 422/415, not just `ConnectError`; ConnectError echoes the real workflow** —
  review-agent-ux W1/W2/S2.
- **`user-activity` explicit empty line + echo key; `--open` edge-timeout distinct message** —
  review-agent-ux W3/W4.
- **ADR written FIRST** — review-plan S1. **`viewParams.test.ts:23` in the rename checklist** —
  review-plan W2.
