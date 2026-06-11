# pflow Web UI Server (`src/pflow/ui/`)

Local **Starlette** server behind the `pflow[ui]` extra. It serves a typed JSON
contract (the Task 155 GraphModel → `render_react_flow`) plus the built frontend
bundle. It runs **no workflows** — every request is read-only: resolve →
validate → `build_graph` → `render_react_flow`.

**Phase status (Task 168):** Phase 3 (this server + the `pflow ui` command +
the `[ui]` extra) is DONE. **Phase 4 builds the `web/` frontend that consumes
this server** — start from the contract below, not from scratch. The deeper
*why* is `task-168.md` + the plan (`implementation/implementation-plan.md`).

## Files

```
src/pflow/ui/
├── __init__.py     # package marker (docstring only)
├── server.py       # the Starlette app: create_app(), endpoints, static mount
└── static/         # built frontend bundle — GITIGNORED, built by `make ui-build`
                    #   (Phase 4), served at "/". Absent in a source checkout.
```

The command lives in `cli/commands/ui.py`; the contract translator + dataclasses
live in `core/workflow/graph/renderers/react_flow.py`; the shared resolve→
validate→build helper is `execution/graph_service.py`.

## The HTTP contract (this is what the Phase 4 frontend codes against)

`web/src/api/client.ts` is the single data-loading seam. Endpoints:

### `GET /api/catalog`
→ `200` `[{name, description, path}]` — saved workflows with `ir` stripped.
`path` is the absolute entry-point `.pflow.md`. Pass **either** `name` or `path`
to `/api/graph` (both resolve). Unparseable saved workflows are silently
omitted (inherited from `WorkflowManager.list_all()`, parity with `pflow list`);
surfacing a `skipped[]` field is an open Phase-4 product choice.

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

### Static bundle (`/` + assets)
Build the SPA into `src/pflow/ui/static/` (Vite `build.outDir = "../src/pflow/ui/static"`)
with `base = "./"` (relative asset paths so it serves from `/`). The server
mounts it via `StaticFiles(html=True)` **only when `static/index.html` exists**;
otherwise non-API paths return `503` with a "run `make ui-build`" hint (dev
convenience — not an error).

> **SPA routing caveat (verified).** `StaticFiles(html=True)` serves
> `index.html` at `/`, but a deep client route like `/graph/123` returns **404**
> — there is **no SPA fallback**. If Phase 4 adds React Router, either use **hash
> routing**, or add a server catch-all that returns `index.html` for any
> non-`/api/` path (then re-test `/api/*` precedence — API routes are registered
> *before* the catch-all in `create_app()` and must stay that way).

## The `pflow ui` command (`cli/commands/ui.py`)

- `pflow ui [workflow] [--port 8765] [--no-open]`. Behind the `[ui]` extra
  (lazy import of `uvicorn`/`starlette` → prints `pip install pflow[ui]` if
  absent; a real bug inside the server module surfaces as a loud traceback, not
  the hint).
- **Opens the browser to `http://127.0.0.1:{port}/?workflow=<urlencoded>`**
  once the port is actually listening (polls, not a guessed delay). →
  **`App.tsx` should read `?workflow=` from the URL and auto-load that
  workflow**; with no param, show the catalog.
- **Local dev loop:** run `pflow ui` (backend) and Vite's dev server
  concurrently; set `server.proxy` in `vite.config.ts` to forward `/api` →
  `http://127.0.0.1:<port>` so the React app hot-reloads against the live
  backend. Production serves the built bundle from the Python server directly
  (no proxy).

## The RFGraph contract + load-bearing rendering rules

Source of truth: `core/workflow/graph/renderers/react_flow.py` (frozen
dataclasses `RFGraph{nodes,edges,groups}`, `RFNode`, `RFEdge`, `RFGroup`,
`RFParam`, `RFRef`). `web/src/types.ts` hand-mirrors these for v1. Rules the
frontend MUST honor or it loses information (each traces to a Task-168 review
item / progress-log entry — read those before rendering chips/groups/batches):

- **`RFEdge.input_name=None` is COMMON, not rare** (output-`source:` edges,
  batch-`items:` edges, multi-role dedup). → attach the data-flow line at
  **node level**, never drop it. (H6.)
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
  literal batch, or an expanded sub-workflow host). **Suppress its leaf box**;
  read its loop badge off the host node. A host is NOT 1:1 with a group — a
  dynamic-batch-of-subworkflow emits two groups with the same `host`. (H8 /
  progress-log "Deviation 2".)
- **`RFNode.is_transform`** (2026-06-10): the code node is a provably pure data
  reshape (inputs → `result`, no external effects, no `next` routing) — classified
  **fail-closed** from its AST (`_is_transform_code` in react_flow.py; anything
  unrecognized ships `False`). The frontend MUST read this fact, never re-derive
  it (it cannot — it needs the AST). Mutually exclusive with the CONDITION role
  by construction (a `next`-setter is never a transform).
- **`RFNode.output_shape`** (TRANSFORM L2, 2026-06-10): the authored shape of
  the node's structured output. `shape.field` names the port it describes —
  where the kind actually WRITES: `"result"` for code (AST-extracted,
  `_result_shape_from_code`: multiple assignments, mutations — incl.
  `result.update()`/`del`/`for`-rebinding — empty/non-literal dicts all ship
  `keys=None`, never a partial list) and structured claude-code
  (`output_schema` → parsed value in `result`); `"response"` for structured
  llm (its parsed value lands in `response`, never `result` —
  `_shape_from_output_schema` is fail-closed: only top-level `type: object`
  schemas with dict `properties` ship). Key types use each source's OWN
  vocabulary (Python names from annotations; "string"/"number" from schemas).
  Ships for ALL code nodes, not just transforms (D9 — display policy is the
  frontend's). A non-null shape with data_type AND keys null means only
  "provably assigns `result`". Drives the output rows (`outputRowsFor`,
  web/src/graph/flow.ts).
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
  `data_flow` edges into hidden items are re-anchored to the batch host. (H9 /
  W1.)
- **`RFParam.is_dynamic`** is derived one level deep (mirrors the edge builder):
  a ref nested >1 level reads `False`, but the raw `${...}` text is still in
  `value`, so render the literal text + chips per visible ref. (H5.)
- **`RFNode.unexpanded`** (one of 4 reasons) → render a badge, never crash.
  `RFGroup.annotations["unexpanded_items"]` keys are **strings** post-JSON.
- Reconcile `is_terminal` nodes + synthetic `kind="end"` nodes + `kind="end"`
  edges into **one visual sink per level**. (H10.)
- `RFRef` carries the structural join key (`node_id` + `ancestor_path` +
  `port`) for the future runtime-overlay; the flat `id` is React-Flow-only.
  Keep both; don't flatten the structural identity away.

## Build + release wiring (Phase 4 — DONE)

- `make ui-build` → `cd web && npm ci && npm run build` (emits into
  `src/pflow/ui/static/`); `make build` depends on it so local wheels include the
  bundle.
- **CRITICAL (H1):** the release CI (`.github/workflows/on-release-main.yml`,
  `uv build`) has **no Node step** by default. The publish job now runs
  `actions/setup-node` + `make ui-build` **before** `uv build` (plus a guard that
  fails if `static/index.html` is missing), or the `[ui]` wheel ships an **empty**
  bundle and `pflow ui` 404s. Local `uv build` likewise needs `make ui-build` first.
- **Load-bearing (the plan got this wrong):** `static/` is gitignored, and
  hatchling honors `.gitignore`, so `packages = ["src/pflow"]` alone EXCLUDES the
  bundle from the wheel. `[tool.hatch.build.targets.wheel] artifacts =
  ["src/pflow/ui/static/**/*"]` force-includes it — **do not remove it** or the
  wheel ships empty. (The sdist still omits the bundle by design; end users install
  the prebuilt wheel and never run Node.)

## Already verified — don't re-litigate

All four `/api/graph` arms; `/api/catalog` shape (ir-stripped); production
bundle serving + `/api/*` route precedence; adversarial `?workflow=` inputs (no
hang/500); real-subprocess end-to-end; port-in-use hint; browser
poll-until-ready; **cold-registry concurrency** (was a torn-read bug; fixed at
the root — `Registry._write_atomic`, atomic tempfile+`os.replace`). Tests:
`tests/test_cli/test_ui.py`, `tests/test_registry/test_registry.py::TestRegistryAtomicWrite`.
