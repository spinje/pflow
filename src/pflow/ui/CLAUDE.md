# pflow Web UI Server (`src/pflow/ui/`)

Local **Starlette** server behind the `pflow-cli[ui]` extra. It serves the GraphModel →
`render_react_flow` JSON contract and the built frontend bundle. It never executes workflows
in-process or mutates workflow files; run/resume endpoints preflight and spawn the normal CLI.
Graph requests remain stateless (`resolve` → `validate` → `build_graph` →
`render_react_flow`); the interaction hub is ephemeral state owned by one `create_app()` instance.

The frontend lives in `web/`. Design rationale: `.taskmaster/tasks/task_168/task-168.md`
and `context/adr/0005-web-ui-local-server-delivery.md`.

## Files

- `server.py` — Starlette handlers, the app-local interaction hub, detached CLI launch, and static mount.
- `run_tailer.py` — trace discovery/tailing, replay snapshots, writer liveness, and run event projection.
- `run_node.py` — trace-backed node details, run-input prefill, and IO value projection.
- `targets.py` — pure Point address resolution to structural `RFRef` descriptors.
- `static/` — generated frontend bundle, built by `make ui-build`; absent in a source checkout.

The command lives in `cli/commands/ui.py`. The renderer and frozen wire dataclasses live in
`core/workflow/graph/renderers/react_flow.py`; `web/src/types.ts` mirrors them. Shared graph
resolution/validation/building lives in `execution/graph_service.py`.

## HTTP contract and server boundaries

`server.py:create_app` is the authoritative route inventory. For changes spanning routes:

- Static delivery/cache policy → `server.py:_BundleFiles`.
- Launch/preflight/detachment → `server.py:run`, `resume`, `_preflight`, `_spawn_detached_cli`.
- Trace history/discovery/liveness → `run_tailer.py:scan_traces`, `discover_live_trace`,
  `is_trace_locked`; streaming/replay → `RunTailer`.
- Recorded values/input prefill → `run_node.py:run_node_detail`, `read_run_inputs`;
  gate masking → `server.py:gate`.
- Point address resolution → `targets.py:resolve_target`.
- Interaction delivery/replay → `server.py:_Hub`, `events`, `command` and
  `web/src/api/events.ts:subscribe`. `sent_to` counts connection queues accepting the primary
  command, not browser apply acknowledgements; for `/say`, it counts the Point broadcast,
  not audio delivery.

Keep these non-obvious contracts:

- `/api/graph` distinguishes malformed requests (`400`), resolution/validation diagnostics
  (`422`), and unexpected build/render failures (`500`). Never turn a build bug into an empty
  successful graph.
- `/api/version` fingerprints source paths and mtimes, falling back to entry-file paths when
  graph building fails so polling survives invalid edits. `/api/source` derives its file set
  from the full GraphModel, not representative/truncated RFGraph nodes.
- Run and resume handlers do blocking resolution/compile preflight through `asyncio.to_thread`,
  then use the single detached `Popen` seam. The server observes the child trace; it does not
  host execution or infer success from the spawn. A UI launch forces the minted execution ID
  through `PFLOW_EXECUTION_ID` so the browser pins the exact run.
  Known limit: a forced resume can still die before trace creation when an edit introduces a
  validator-only error; compile preflight does not run the full validator.
- Runtime data joins the current graph through structural refs (`node_id`, `ancestor_path`,
  and `port`). React Flow flat IDs are positional render IDs and may change after rebuilds.
- Run-input and gate responses are server-redacted. Do not move secret masking exclusively to
  the browser or add bulky gate payloads to the run list/SSE stream.
- `_Hub`, `_AudioStore`, and narration state are event-loop-owned and intentionally lock-free.
  Every handler touching any of them must be `async def`, including `audio()` even though it
  does no hub access or blocking I/O. Blocking graph/trace work goes through a thread.
  Per-viewer queues are bounded, and an overrun viewer is evicted so memory use and `sent_to`
  remain truthful. Keepalive writes, rather than a second competing disconnect receive, detect
  dead SSE sockets.
- Narration ordering/pacing lives in `server.py:say`, `narration`, and `command`: never `await`
  between the Point and transient `say` broadcasts or latch `say` for replay. Only current-clip
  `started`/`ended` beacons may move `narration_until`; stale ones still clear the blocked flag.
  `clear` resets the whole narration rendezvous even with no viewers.
- This local server relies on loopback binding, no CORS headers, and `_LoopbackOnly` middleware
  on every route to close DNS-rebinding reads/writes. Re-evaluate that boundary before adding
  CORS or bypassing the middleware. Keep it pure ASGI: `BaseHTTPMiddleware` would wrap the
  long-lived SSE stream.
- Register API routes before the static fallback. The bundle uses query-parameter navigation;
  `StaticFiles(html=True)` does not provide a general SPA deep-route fallback.

`discover_live_trace` excludes `--only` traces and prefers live runs, otherwise falling back to
the newest matching trace (which can be incomplete); `RunTailer`
resolves a pinned run to a fixed file after allowing for the launch window before its meta line.
`is_trace_locked` detects writer death, not hangs. When advisory-lock probing is unavailable
(including Windows), it returns `None` and callers use the incomplete-trace heuristic, not exact
liveness. Preserve `scan_traces`' per-file corruption tolerance. Structural state comes from trace
facts rather than UI vocabulary.

## The `pflow ui` command (`cli/commands/ui.py`)

`cli/commands/ui.py` owns Click parsing, optional-dependency loading, browser launch, server reuse,
and Point/Watch/narration calls. Keep detailed flags and rendered help in its Click declarations.

The important integration constraints are:

- Browser opening waits until the loopback port is listening. On an occupied port, the command
  reuses it only when `/api/health` identifies a pflow Viewer; a foreign process remains an error.
- `focus --open` polls cheap health/window readiness rather than repeatedly posting a graph-building
  command. The hub is process-local, so reuse and broadcasts do not cross ports.
- UI backend imports stay lazy behind the `[ui]` extra. Internal import failures must surface as
  failures rather than being mislabeled as a missing optional dependency.
- Detached execution belongs to the server's one `Popen` seam. Its Windows creation flags and
  POSIX session behavior preserve the invariant that a launched run survives Viewer shutdown.
- Point targets cross the wire as structural refs. Never send positional flat IDs between
  independently rendered graphs.

## RFGraph contract and rendering seam

The frozen dataclasses and their docstrings in
`core/workflow/graph/renderers/react_flow.py` are authoritative; `web/src/types.ts` mirrors the
wire shape. Real renderer payloads in `web/src/test/fixtures/contracts/` are regenerated and
drift-checked by `tests/test_core/test_react_flow_contract_fixtures.py`. Any contract change must
update Python, TypeScript, and fixtures together.

Backend predicates such as `is_decision`, `is_terminal`, `shadowed`, and `is_transform` are
facts; the frontend chooses visual policy but must not re-derive them. Preserve these lossy-edge
guards:

- `RFRef` is the current stable runtime join key (`node_id` + `ancestor_path` + `port`); flat `id`
  is React-Flow-only and positional.
- A missing `RFEdge.input_name` is valid and anchors at node level. Every represented dependency,
  including prompt-cache chunks and multiple refs in one parameter, must remain visible.
- Representative batch truncation keeps the full batch descriptors and re-anchors cross-boundary
  edges to a visible host. Map retained items through structural ancestry/batch index, not list order.
- `is_group_host`, `is_transform`, output shape/type facts, branch conditions, and unexpanded
  reasons are fail-closed renderer facts. Unknown analysis must stay absent/false rather than
  becoming an inferred frontend claim.
- Reconcile terminal nodes, synthetic end nodes, and end edges into one visual sink per level.

The detailed row, handle, layout, focus, and component rules live in the `web/` CLAUDE files.

## Build and release wiring

`make ui-build` runs `npm ci && npm run build` and emits into `src/pflow/ui/static/`; `make build`
depends on it. The release workflow must build the frontend before `uv build` and verify that the
wheel contains `pflow/ui/static/index.html`.

`static/` is gitignored and hatchling honors `.gitignore`. The artifact include for
`src/pflow/ui/static/**/*` must remain on both the sdist and wheel targets: local/release wheels
are built through the sdist, so a wheel-only include silently ships an empty UI. This is pinned by
`tests/test_packaging.py`.
