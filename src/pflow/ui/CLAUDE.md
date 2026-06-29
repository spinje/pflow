# pflow Web UI Server (`src/pflow/ui/`)

Local **Starlette** server behind the `pflow-cli[ui]` extra. It serves a typed JSON
contract (the Task 155 GraphModel → `render_react_flow`) plus the built frontend
bundle. It runs **no workflows** and never mutates workflow files. Graph requests
remain stateless (`resolve` → `validate` → `build_graph` →
`render_react_flow`); the interaction hub is ephemeral, in-memory state scoped to
one `create_app()` instance.

The frontend that consumes this server lives in `web/` (its own CLAUDE.md
suite). The design *why* is `task-168.md` + `ADR-0005`.

## Files

```
src/pflow/ui/
├── __init__.py     # package marker (docstring only)
├── server.py       # the Starlette app: create_app(), endpoints, static mount
├── targets.py      # pure Point address resolution to structural RFRef descriptors
└── static/         # built frontend bundle — GITIGNORED, built by `make ui-build`,
                    #   served at "/". Absent in a source checkout.
```

The command lives in `cli/commands/ui.py`; the contract translator + dataclasses
live in `core/workflow/graph/renderers/react_flow.py`; the shared resolve→
validate→build helper is `execution/graph_service.py`.

## The HTTP contract (what the frontend codes against)

`web/src/api/` is the server-communication seam: `client.ts` owns graph/source
reads and `events.ts` owns the live interaction channel. Endpoints:

### `GET /api/catalog`
→ `200` `[{name, description, path}]` — saved workflows with `ir` stripped.
`path` is the absolute entry-point `.pflow.md`. Pass **either** `name` or `path`
to `/api/graph` (both resolve). Unparseable saved workflows are silently
omitted (inherited from `WorkflowManager.list_all()`, parity with `pflow list`);
surfacing a `skipped[]` field is an open product choice.

### `GET /api/graph?workflow=<name|path>`
The React Flow contract as JSON (`json.dumps(asdict(render_react_flow(...)),
default=str)`). **Four status arms — `api.ts` must handle all:**

| Status | Body | Meaning |
|---|---|---|
| `200` | `{nodes, edges, groups}` (the contract) | success |
| `400` | `{"errors": [{"message": ...}]}` | missing/empty `workflow` param |
| `422` | `{"errors": [<Diagnostic.to_dict()> ...]}` | resolution / validation failure — render these to the user |
| `500` | (Starlette default) | a build/render bug on validated IR — **never** a 200-with-empty-graph; surface it, don't swallow |

The server always sends `max_depth=5`; collapse/expand is **client-side** (no
depth round-trip). The `422` diagnostics are the same structured objects the CLI
renders (`core/diagnostic.py`).

**Payload size (inline-all):** every param value — including full prompts/code —
ships inline, so click-to-read needs no second fetch. Batch×depth fan-out is
bounded by representative-item truncation, but a deep workflow with large prompts
can still produce a multi-MB payload. Fine for this local single-user server; a
future remote / multi-client phase may want a by-ref fetch for large values.

### `GET /api/source?workflow=<name|path>`
→ `200` `{"root": "<abs path>" | null, "files": {"<abs path>": "<text>", ...}}`
— raw `.pflow.md` source text for the authored workflow files represented by
the graph. Status arms mirror `/api/graph`: missing/empty `workflow` is `400`;
resolution or validation diagnostics are `422`; unexpected pipeline bugs are
loud `500`s.

The file set is derived from the **GraphModel nodes**, not the React Flow
render. This is load-bearing: renderer-level representative-batch truncation can
omit a child file from `RFGraph`, while `GraphModel` still contains every
expanded level. Only `Node.source.file` participates; `param_sources` may point
at prompt/code files whose contents already ride inline in `/api/graph` params
and are not a v1 source-pane concern.

`root` is the source file of the first top-level node that actually has a source
file. Do not use "first top-level node" blindly: workflows with `## Inputs`
emit sourceless input nodes before authored steps. Inline-content workflows have
no source file and return `{"root": null, "files": {}}`. If a file disappears
or is unreadable after graph construction, the server logs a warning and skips
that file rather than failing the whole request. A `depth_limit`-unexpanded
sub-workflow contributes no nodes and therefore no source file.

### `GET /api/version?workflow=<name|path>`
→ `200` `{"fingerprint": "<sha256>"}` — a cheap change-fingerprint (sha256 over each
source file's `path:mtime_ns`). The frontend **polls** this (`useSourceWatch`); when the
digest changes it re-fetches `/api/graph` and rebuilds the canvas **in place** (no page
reload), so an agent can edit the `.pflow.md` while the user watches it update.

Unlike the other endpoints this one **never `500`s** and only `400`s on a missing
`workflow` param — the poll must survive a mid-edit *invalid* workflow. The file set comes
from `_source_files_for()`, a fallback chain so the fingerprint still tracks the edited
file when the build fails: built-graph files → resolvable entry file → saved-NAME entry
path (`WorkflowManager.get_path`) → the literal path arg → `[]` (a constant fingerprint;
the poll keeps running). An invalid edit still moves the entry file's mtime, so the
triggered `/api/graph` re-fetch surfaces the `422` as a non-blocking banner and recovers
on the next valid save. **Known limit:** a workflow mid-edit-invalid in a *sub-workflow*
file tracks only the entry file's mtime until it parses again (recovery still fires on the
fixing save).

### `GET /api/runs[?workflow=<name|path>]`
→ `200` `[{run_id, workflow_name, workflow_path, start_time, complete, final_status, live,
only_node, trace_file, git_root}]` — runs scanned from `~/.pflow/debug`, newest-first (Task 173 D6 run
navigation). Bare = every run; `?workflow=X` = that workflow's history (matched on the recorded
`meta.workflow_path`). RAW facts (the UI composes the badge): `complete` = has a `run.complete`
trailer; `final_status` = that trailer's outcome (`success`/`degraded`/`failed`) or `null` while
not complete; `live` = not complete AND the writer still holds the trace's advisory lock (EXACT
`flock` liveness via `is_trace_locked` — the old `_STALE_RUN_S` mtime heuristic is deleted; a
no-`fcntl` FS falls back to "incomplete = live"); `only_node` LABELS `--only` runs (they are kept
here, unlike the live overlay which excludes them); `git_root` = the run's enclosing git repo (cached;
buckets ad-hoc runs by project in the catalog) or `null`. Inline/stdin/MCP runs carry `workflow_path =
"ir-hash:<md5>"` (a content fingerprint, not a file): they appear in the bare listing and a
`?workflow=<file>` query can't match them. `404` on an unresolvable `?workflow=`; `200 []` for zero
runs (a hard scan failure also degrades to `[]` — the scanner is shared non-throwing with the live
tailer). The shared scanner is `run_tailer.scan_traces` (cheap head+tail read, never a full parse).
Pin a Viewer to one run for replay/concurrent-watch via `GET /api/events?workflow=X&run=<run_id>`.

### `GET /api/run-node?workflow=<name|path>&ref=<json>[&run=<run_id>]`
→ `200` `RunNodeDetail` `{node_type, status, duration_ms, cost_usd, tokens, error, input, output}` — ONE
node's runtime record for the detail panel's "This run" section (Task 173 D6 Phase 5). `ref` is the
structural `RFRef` (`{node_id, ancestor_path, port}`) JSON-encoded — the SAME identity the overlay joins on
(`sameRef`); no positional flat id. `&run=` reads the pinned run (matched by `meta.execution_id`); omitted
→ the newest live trace (what the unpinned overlay follows). The interactive single-node counterpart of
`pflow report`: realized `input` (post-`${...}` resolution — `node_params` is recorded RESOLVED + the
canonical `llm_prompt`/`llm_system`), resolved `output` (`node_output`/`llm_response`), `cost_usd` (the
shared `event_cost`, so it agrees with the chip + report), `tokens`, and `error`. Read off RAW JSONL lines
(never `load_trace_file`, which strips the `ancestor_path`/`port` join keys), blobs resolved via
`trace_io.substitute_refs`, `node_type` mapped through `node_type_tag` (NEVER the raw Python class name),
secrets recursively redacted by key name. `400` on a missing/malformed `ref`; `404` on an unresolvable
`workflow` or no matching run/event (incl. a `node.start`-only crashed node — no completion `event` to
project). A read-only GET of trace content, same exposure class as `/api/graph` (the CORS tripwire below
applies). The reader is `run_node.run_node_detail`.

### Live interaction channel

- `GET /api/events?workflow=<name|path>&visibility=<visible|hidden>` subscribes a
  Viewer to the SSE envelope `{type, ...}`. The envelope is vocabulary-agnostic:
  this task defines `connected`, `focus`, `frame`, and `clear`; it deliberately
  defines no run/trace event schema.
- `POST /api/command` validates a `focus`/`frame` target against a fresh graph (or
  broadcasts `clear`) and reports `sent_to`, per-window visibility, and the
  canonical `workflow_key`. It reports messages queued to live connections, not
  browser apply acknowledgments.
- `POST /api/interaction` records deliberate user actions; `GET /api/activity`
  returns the bounded, newest-first snapshot. `POST /api/visibility` updates one
  connection. All POSTs require `application/json`.
- `GET /api/health` is the cheap liveness + identity probe for discovery/reuse:
  `{"service": "pflow-ui"}` always, plus `{"workflow_key", "windows"}` when a
  resolvable `workflow` is supplied (`windows = len(windows_for(key))`, **no graph
  build**). An unresolvable workflow reports identity only (no 404 — a liveness probe
  must answer regardless, unlike `events()`/`command()`). It reads the hub, so it is
  `async def` per the invariant below. **`windows` can transiently over-count by 1**
  for up to one `_KEEPALIVE_S` cycle after a Viewer's `onerror` reconnect to *this*
  server (the dropped connection lingers until its next keepalive write fails); a
  server *restart* frees the whole hub, so that path is clean. Benign for a local
  single-user viewer; the count self-corrects.

Name-opened and path-opened Viewers share one resolved workflow key. Point targets
cross the wire only as structural refs; never send positional flat ids between
independent graph renders. The `_Hub` is per-process and non-persistent: restart
clears connections and activity.

> **Hub concurrency invariant.** Every route touching `_Hub` must be `async def`.
> Starlette runs sync handlers in a threadpool, while the hub's `asyncio.Queue`
> instances and deque are intentionally lock-free and event-loop-owned. Point's
> recursive validation/build runs via `asyncio.to_thread`; only the resulting
> graph returns to the loop before broadcast. Each connection queue is bounded;
> a Viewer that cannot consume 64 commands is evicted so memory and `sent_to`
> stay truthful. The SSE
> keepalive is required to surface silently dropped sockets across ASGI versions;
> do not replace it with a second `request.is_disconnected()` receive consumer.

The server binds loopback and sends no CORS headers. JSON POSTs force a cross-origin
preflight, and EventSource responses are unreadable cross-origin. The worst live
command changes focus in the user's Viewer; it has no file/system side effect. Any
future mutating or live-run endpoint must re-evaluate this boundary.

### Static bundle (`/` + assets)
The SPA builds into `src/pflow/ui/static/` (Vite `build.outDir`, `base = "./"`
so relative asset paths serve from `/`). The server mounts it via
`StaticFiles(html=True)` **only when `static/index.html` exists**; otherwise
non-API paths return `503` with a "run `make ui-build`" hint (dev convenience —
not an error). `index.html` is served `Cache-Control: no-cache` (the
`_BundleFiles` subclass) so a rebuild's new asset hashes can't be defeated by a
heuristically-cached stale entry; the content-hashed assets stay cacheable.

> **SPA routing caveat (verified).** `StaticFiles(html=True)` serves
> `index.html` at `/`, but a deep client route like `/graph/123` returns **404**
> — there is **no SPA fallback**. The frontend avoids this today (it switches
> views by the `?workflow=` query param, not client routes). If a future version
> adds React Router, either use **hash routing**, or add a server catch-all that
> returns `index.html` for any non-`/api/` path (then re-test `/api/*` precedence
> — API routes are registered *before* the catch-all in `create_app()` and must
> stay that way).

## The `pflow ui` command (`cli/commands/ui.py`)

- `pflow ui [workflow] [--port 8765] [--no-open] [--no-auto-update]`. Behind the `[ui]` extra
  (lazy import of `uvicorn`/`starlette` → prints `uv tool install 'pflow-cli[ui]'` if
  absent; a real bug inside the server module surfaces as a loud traceback, not
  the hint).
- **Opens the browser to `http://127.0.0.1:{port}/?workflow=<urlencoded>`**
  once the port is actually listening (polls, not a guessed delay). `App.tsx`
  reads `?workflow=` and auto-loads it; with no param, it shows the catalog.
  `--no-auto-update` appends the private `?watch=0` URL param to freeze the
  live-source poll.
- **Discovery / reuse (probe-then-reuse-or-start).** On a port-in-use, `serve` probes
  `GET /api/health`; if a pflow viewer answers it **reuses** it — opens a tab against
  the running server (honoring `--no-open` / `--no-auto-update` via `_serve_url`) and
  exits 0, so `pflow ui <wf>` is idempotent. A *foreign* process on the port keeps the
  "port in use, try `--port`" error. `focus --open` polls the same cheap
  `/api/health?workflow=X` for `windows > 0` (then sends `focus` once) instead of
  re-POSTing the build-triggering command on a timer (which re-ran the full graph build
  ~60×). `windows > 0` means "SSE registered" (which only happens after the graph
  builds), not "render-acked" — the same readiness proxy the old `sent_to > 0` loop used.
  A server *restart* needs no cross-process cleanup (the killed process frees its whole
  `_Hub`); `SO_REUSEADDR` lets a fast double-invoke briefly "reuse" a dying server
  (benign — the frontend's reconnect + the `--open` poll recover). The probe
  (`_probe_health`) is non-failing (returns `None`, never `ctx.exit`) with a short
  `_PROBE_TIMEOUT_S` so a foreign socket can't stall it. Reuse composes only within one
  port (per-process `_Hub`, no cross-port broadcast).
- Point: `pflow ui focus <workflow> <target> [--open]`, `frame`, and
  `clear-focus`. Watch: `pflow ui user-activity [workflow]`. Each accepts `--port`
  and the project-standard `--output-format json` and talks to an already-running
  server. A saved workflow named like a subcommand is reachable by path (for
  example `./focus.pflow.md`).
- **Address grammar (`targets.py`):** a target is named the way it reads in the
  `.pflow.md` — a step/input/output by its bare name, a connection as
  `source -> target`. The grammar deliberately mirrors the file's own vocabulary
  rather than inventing a parallel notation: `in:`/`out:` is **not** required up
  front; the bare name of an IO port resolves like any node, and the prefix only
  appears in the qualify list when an input and output genuinely share a name
  (mirrors how a bare node name that occurs in two sub-workflows qualifies by
  scope). A miss suggests in the shape of what was typed (a connection attempt
  gets real connections back). `_node_addresses` returns the full alias set. A
  **unique-match report echoes the file's vocabulary** — the `in:`/`out:`
  side-prefix is dropped when the bare name still resolves to one element (a
  collision never reaches that path), but scope (`create.echo`) is kept and the
  prefix is *retained* if dropping it would re-introduce ambiguity. The **qualify
  list** keeps the canonical prefixed/scoped form, where it disambiguates.
- **Local dev loop:** run `pflow ui` (backend) and Vite's dev server
  concurrently; set `server.proxy` in `vite.config.ts` to forward `/api` →
  `http://127.0.0.1:<port>` so the React app hot-reloads against the live
  backend. Production serves the built bundle from the Python server directly
  (no proxy).

Deferred interaction targets are standalone body rows and control/branch edges.
Also deferred until a concrete consumer exists: activity `--follow`, replacing
the Auto-update poll with SSE, and programmatic browser apply acknowledgments.

## The RFGraph contract + load-bearing rendering rules

**Source of truth:** the frozen dataclasses + their docstrings in
`core/workflow/graph/renderers/react_flow.py` (`RFGraph{nodes,edges,groups}`,
`RFNode`, `RFEdge`, `RFGroup`, `RFParam`, `RFRef`); `web/src/types.ts` mirrors
them. The *rendering policy* these rules drive lives in the `web/` CLAUDE.md
suite (`graph/` = the transform, `components/` = the render); model invariants
are in `graph/CLAUDE.md`. This list is the consumer's INDEX — when it disagrees
with `react_flow.py`, the code wins. Rules the frontend MUST honor or it loses
information (read the cited progress-log entry before rendering
chips/groups/batches):

- **`RFEdge.input_name=None` is COMMON, not rare** (output-`source:` edges,
  batch-`items:` edges, truncation re-anchoring). → attach the data-flow line at
  **node level**, never drop it.
- **`input_name="prompt_cache"` is RESERVED** (2026-06-13): a `## Cache` chunk
  dependency — the chunk's ref is forbidden in the consumer's prompt body, so
  this edge is the dependency's only visibility. No PARAM row exists for it:
  present it as the cached prompt prefix (`bindingLabel` in utils/format.ts,
  the EdgePanel "cached context" variant), never as a binding. The canvas gives
  each chunk its own synthesized sub-row on the consumer card (derived from the
  edges themselves — the same per-ref sub-row mechanism multi-ref params use;
  see web/CLAUDE.md's left-column bullet). A cache edge
  counts as a READ of the producer's field (un-quiets its output row) — intended.
- **`RFNode.cached_prefix`** (2026-06-13): the consumer's cached system prefix
  as authored TEMPLATE text — per consumed chunk (declaration order),
  `prose_before + ${var}`, assembled in `build.py` with the runtime's own rule
  (core/prompt_cache.py `build_cache_system_blocks`) so the panel can show the
  prompt as the model receives it. Null when the node consumes no chunks.
  Rendered as a `cached prefix` block before the `prompt` param (request order:
  system → cached prefix → prompt).
- **Every validator-enforced `${ref}` is one DATA_FLOW edge** (2026-06-13):
  plain-param sibling refs, multi-param same-input reads (one edge PER ref —
  the old pair-dedup died), full-depth dict/list refs, and cache chunks all
  draw edges now. Advanced no longer dims shadowed structural edges (most of
  the sequential spine is shadowed under the richer edge set — the dim erased
  the control skeleton; user-gated via browser before/after, 2026-06-13).
- **`RFNode.io` carries the full interface fact (2026-06-11):**
  `{data_type, required, default}`. An input that omits `required:` ships
  `required=True` — the ir_schema default every runtime reader applies (the
  wire shipped `False` before, mislabeling the common authored case — do not
  "fix" it back). `default` is the authored value verbatim, `None` when
  absent. An INPUT's description rides `purpose` (symmetric with outputs);
  inputs ship `source=None` (the parser injects `_source_line` only for
  outputs/nodes — the inputs schema forbids extra keys). Consumed by the
  IO rows' tooltips and the IoPanel (the root IO card's interface panel).
- **`RFEdge.condition`** (branch edges + a DECISION's END edge): the source-code
  condition that selects this outcome (`"if len(items) > 5"` / `"else"`),
  AST-extracted **fail-closed** from the decision node's `code` param
  (`_branch_conditions` in react_flow.py — supported shapes documented there;
  anything else ships `None`, absent beats wrong). A decision's END edge is its
  reserved **"end" outcome** (`is_decision` counts the end route — a dynamic
  `next="end"` arm is an END edge, never a BRANCH), so it carries the `"end"`
  condition; a non-decision's END edge (static `- next: end`) never does. An
  outcome selected by multiple non-adjacent arms lists them verbatim
  (`"if ok · else"`). The frontend shows conditions on the edge / fork rows
  (advanced always; beautiful only while the condition node is focus-expanded)
  and in the read panel's outcome table.
- **`RFNode.is_group_host=True`** → the node is materialized as a group (a
  literal batch WITH expanded item containers, or an expanded sub-workflow
  host). **Suppress its leaf box**; read its loop badge off the host node. A
  host is NOT 1:1 with a group — a dynamic-batch-of-subworkflow emits two
  groups with the same `host`. A LITERAL-batched LEAF ships `False` (leaf items
  are BatchSpec.items data, not nodes — there is no body to draw; flagging it
  True left the node with no on-canvas representative and dropped its spine
  edges, review-caught 2026-06-11). The host of a literal batch OF
  SUB-WORKFLOWS is represented by its rendered BATCH container (the frontend's
  `shellBatchIds` rule). (progress-log "Deviation 2" + the 2026-06-11
  literal-batch fix.)
- **`RFNode.is_transform`** (2026-06-10): the code node is a provably pure data
  reshape (inputs → `result`, no external effects, no `next` routing) — classified
  **fail-closed** from its AST (`_is_transform_code` in react_flow.py; anything
  unrecognized ships `False`). The frontend MUST read this fact, never re-derive
  it (it cannot — it needs the AST). Mutually exclusive with the CONDITION role
  by construction (a `next`-setter is never a transform).
- **`RFNode.output_shape`** (TRANSFORM L2, 2026-06-10; typing extended
  2026-06-11): the authored shape of the node's structured output.
  `shape.field` names the port the kind actually WRITES: `"result"` for
  code/claude-code, `"response"` for llm. Everything is FAIL-CLOSED — a type
  ships only when it is authored truth or a Python-semantics certainty
  (`_TypeScope` + `_key_type` in react_flow.py; the resolution forms are
  pinned in `test_key_type_resolution_matrix`). Rules a consumer must know:
  code keys ship when every module-scope `result` assignment is a literal
  dict with the SAME key set (branch-assigned gates qualify; any mutation /
  differing arms → `keys=None`, never partial); **a schema-LESS llm/
  claude-code node ships `{field, "str", keys: null}`** (kind contract:
  free-form text) — so every such card renders a quiet `→ response: str` row
  (D4) — while a schema *present but unreadable* (templated `${...}`,
  non-object) stays null (its runtime value is parsed JSON; "str" would lie).
  Types use each source's own vocabulary, never normalized (annotation
  unparse: `dict[str, int]` verbatim; "string"/"number" from schemas). A
  non-null shape with data_type AND keys null means only "provably assigns
  `result`". Drives the output rows (`outputRowsFor`, web/src/graph/flow.ts).
- **`RFGraph.kind_output_types`** (2026-06-11): kind → output field → declared
  type, from the registry's parsed docstring interfaces
  (`Registry.output_types_by_kind()` — drops `any`), INJECTED at the server
  seam (the renderer never reads the registry; the model never carries
  platform facts). Filtered to kinds present in the graph. The frontend's
  LAST type fallback on output rows that already exist — it never creates a
  row, and per-node authored shapes always win (so it effectively serves
  shell/http/file/mcp; llm/claude-code/code always have a shape).
- **`RFEdge.output_path`** (TRANSFORM L2): the ref's sub-path below
  `output_field` — `${gen.result.ok}` ships `["ok"]`. Cleared together with
  `output_field` on truncation re-anchoring. The per-key landing uses the FIRST
  segment only (D7); deeper structure is read-panel territory. `output_path` is
  part of the renderer's edge-identity key: two sub-key refs in one output
  `source:` expression keep both edges. Residual lossiness: two sub-key refs
  sharing one `input_name` in one param string still collapse at BUILD dedup
  (first path wins — the `input_name` precedent; `Edge.output_path` is
  `compare=False`, see graph/CLAUDE.md).
- **Batch truncation:** only ≤2 *representative* item-groups survive in
  `groups`, but `RFNode.batch.items` keeps **all N** descriptors + `batch.count`.
  Map a surviving group to its item by the member ref's
  `ancestor_path[].batch_index` (**positional**, not list order). Cross-boundary
  `data_flow` edges into hidden items are re-anchored to the batch host.
- **`RFParam.is_dynamic`** is derived one level deep (mirrors the edge builder):
  a ref nested >1 level reads `False`, but the raw `${...}` text is still in
  `value`, so render the literal text + chips per visible ref.
- **`RFNode.unexpanded`** (one of 4 reasons) → render a badge, never crash.
  `RFGroup.annotations["unexpanded_items"]` keys are **strings** post-JSON.
- Reconcile `is_terminal` nodes + synthetic `kind="end"` nodes + `kind="end"`
  edges into **one visual sink per level**.
- `RFRef` carries the structural join key (`node_id` + `ancestor_path` +
  `port`) for the future runtime-overlay; the flat `id` is React-Flow-only.
  Keep both; don't flatten the structural identity away.

## Build + release wiring

- `make ui-build` → `cd web && npm ci && npm run build` (emits into
  `src/pflow/ui/static/`); `make build` depends on it so local wheels include the
  bundle.
- **CRITICAL:** the release CI (`.github/workflows/on-release-main.yml`,
  `uv build`) has **no Node step** by default. The publish job runs
  `actions/setup-node` + `make ui-build` **before** `uv build`, then guards at BOTH
  ends — a pre-build source-tree check (`static/index.html` exists) AND a post-build
  check that the *built wheel actually contains* `pflow/ui/static/index.html` — or
  the `[ui]` wheel ships an **empty** bundle and `pflow ui` 503s. Local `uv build`
  likewise needs `make ui-build` first.
- **Load-bearing (the plan got this wrong twice):** `static/` is gitignored, and
  hatchling honors `.gitignore`, so `packages = ["src/pflow"]` alone EXCLUDES the
  bundle. The `artifacts = ["src/pflow/ui/static/**/*"]` force-include ships it —
  and it must sit on **BOTH** the `wheel` AND the `sdist` hatch targets. `uv build`
  and `make build` build the wheel **from the sdist**, so a wheel-only force-include
  is silently dropped (the sdist had no bundle to copy) → the published `[ui]` wheel
  ships **empty** and `pflow ui` 503s. **Do not remove either line.** Pinned by
  `tests/test_packaging.py`; the release workflow greps the built wheel as the
  artifact-level guard. (The sdist now carries the bundle too — ~3 MB larger — so a
  from-sdist install needs no Node.)

## Already verified — don't re-litigate

All four `/api/graph` arms; `/api/catalog` shape (ir-stripped); production
bundle serving + `/api/*` route precedence; adversarial `?workflow=` inputs (no
hang/500); real-subprocess end-to-end; port-in-use hint; browser
poll-until-ready; **cold-registry concurrency** (was a torn-read bug; fixed at
the root — `Registry._write_atomic`, atomic tempfile+`os.replace`). Tests:
`tests/test_cli/test_ui.py`, `tests/test_registry/test_registry.py::TestRegistryAtomicWrite`.
