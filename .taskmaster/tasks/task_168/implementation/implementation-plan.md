# Task 168 — Implementation Plan: Workflow Visualization Web UI (Static Viewer)

> This plan is written to be executed by an AI agent in isolation. Every integration point below is
> verified against current code with file:line. The *why/what/spec* lives in
> `.taskmaster/tasks/task_168/task-168.md`; rationale for "why a server" lives in **ADR-0005**. This
> file is the *how* — phase by phase, file by file.

## Context

pflow workflows are text (`.pflow.md`). A real one (the Task 163 plan→code harness) is a deep tree of
sub-workflows with batch/loops and many `${ref}` templates threading data between nodes — and that
wiring is **invisible in the text**. `pflow visualize` (Mermaid) is the $0 baseline but static text:
no collapse/expand, no click-to-read. Task 155 shipped a renderer-agnostic `GraphModel`; this task
adds a **second renderer** (`render_react_flow`) and a **local web server** (`pflow ui`) that serves
a React Flow canvas so a human can *see and understand* a workflow: structure, input→node wiring,
template connections, params, and prompts. **Static structure only** — the live-run overlay and visual
editing are deliberately later increments (architected-for, not built).

## Decisions baked into this plan (resolved during design)

- **Delivery = local ASGI server (Starlette), behind a `pflow[ui]` extra.** Not a static export / JSON
  dump. (ADR-0005.)
- **Wire contract = a Python `render_react_flow(graph)` translator** emitting a typed, React-Flow-native
  payload — NOT raw `asdict(GraphModel)` (which drops the `is_decision`/`is_terminal`/`shadowed`
  methods and ships nested `NodeId`). Predicates baked as facts in Python; visual policy in TS.
- **Flat ids: mint a trivial *injective* id from the already-unique `NodeId`** (`n0, n1, …`); **do NOT
  reuse or refactor Mermaid's collision-patched `_assign_flat_ids`** (RF ids aren't user-visible; the
  structural `ref` carries real identity). `mermaid.py` is **not touched**.
- **`Node.params` lives in the model** (small follow-on to `build_graph`). **Inline ALL param values in
  `/graph`** (the server parses the file per request; values are in hand; payload is bounded by the
  small `.pflow.md` size). No lazy-fetch endpoint, no file-by-line reader, no `is_large` flag.
- **Per-body-node ports are derived** (frontend: inputs = params, outputs = outgoing `DATA_FLOW`
  `output_field`s). No new model field for ports. Workflow-level IO are already first-class synthetic
  nodes.
- **No `/events` SSE stub.** Overlay-readiness = the structural `ref` in the contract + pluggable
  frontend data-loading, not a dead route.
- **Single package: the built bundle ships under `src/pflow/ui/static/`** (free via hatchling
  `packages=["src/pflow"]`); `pflow[ui]` gates only the *server* deps (starlette/uvicorn).
- **Layout client-side with ELK** (`elkjs`); direction LR default + toggle; dagre is the documented
  fallback if ELK is too heavy.

## Architecture (data flow)

```
.pflow.md (disk)
   │  pflow ui → Starlette server (long-running; runs NO workflows)
   │  per /api/graph request:
   ▼
resolve_workflow → WorkflowRunner().validate → build_graph(ir, resolve_child=resolve_sub_workflow,…)
   ▼
GraphModel ──render_react_flow──▶ RFGraph (typed dataclasses) ──asdict+json──▶ browser
                                                                                  │
                                                            React app: ELK layout → React Flow canvas
```

The server is stateless per request (re-parses the file each time; an mtime cache is a trivial later
optimization). Catalog = saved workflows from the registry.

---

## Wire contract (Phase 2 deliverable)

New module `src/pflow/core/workflow/graph/renderers/react_flow.py`. Return **dataclasses** (so
`asdict`+`json.dumps` works and is testable, mirroring the existing model round-trip test):

```python
@dataclass(frozen=True)
class RFRef:            # structural join key — aligns to graph/CLAUDE.md "Runtime Overlay Join Contract"
    node_id: str
    ancestor_path: list[dict]   # [{node_id, batch_index}] — body-node identity is (node_id, ancestor_path)
    port: str | None            # "in"/"out"/None; None for body nodes

@dataclass(frozen=True)
class RFParam:
    name: str
    value: Any                  # JSON-able (str incl. full prompt/code, int, float, bool, list, dict)
    is_dynamic: bool            # value contains ${...} → derived via scope.source_refs_in
    source: dict | None         # {file, line} from Node.param_sources (sparse: code/file params only)

@dataclass(frozen=True)
class RFNode:
    id: str                     # injective "n{i}" from enumeration over graph.nodes
    ref: RFRef
    kind: str                   # node type, plus synthetic "input"/"output"/"end"
    purpose: str
    params: list[RFParam]
    io: dict | None             # {data_type, required} — only on synthetic input/output nodes
    loop: dict | None           # {polarity, condition, cap, carry}
    batch: dict | None          # {parallel, dynamic, as_name, source_ref, count, items}
    parent: str | None          # group id "g{j}" (from Node.parent → Container.id)
    source: dict | None         # {file, line} node-level click-to-read
    is_decision: bool           # graph.is_decision(node.id)
    is_terminal: bool           # graph.is_terminal(node.id)
    unexpanded: str | None
    annotations: dict

@dataclass(frozen=True)
class RFEdge:
    id: str                     # "e{k}"
    source: str                 # node id "n{i}"
    target: str
    kind: str                   # EdgeKind value: sequential|branch|error|data_flow|end
    label: str | None
    output_field: str | None    # data-flow: source's output field
    input_name: str | None      # data-flow: target param the line lands on (best-effort/lossy)
    shadowed: bool              # graph.shadowed(edge)

@dataclass(frozen=True)
class RFGroup:
    id: str                     # injective "g{j}" from enumeration over graph.containers
    kind: str                   # workflow|batch|input_wrapper|output_wrapper
    parent: str | None          # group id
    host: str | None            # node id of the host node (loop badge: frontend reads host node's loop)
    members: list[str]          # node ids
    nesting_depth: int
    annotations: dict

@dataclass(frozen=True)
class RFGraph:
    nodes: list[RFNode]
    edges: list[RFEdge]
    groups: list[RFGroup]

def render_react_flow(graph: GraphModel) -> RFGraph: ...
```

**ID mapping (the only non-trivial translator logic, ~10 lines):**
- `node_id_map: dict[NodeId, str] = {n.id: f"n{i}" for i, n in enumerate(graph.nodes)}`
- `group_id_map: dict[str, str] = {c.id: f"g{j}" for j, c in enumerate(graph.containers)}`
- Edge endpoints (NodeId) → `node_id_map`; `Node.parent`/`Container.parent` (already Container.id
  strings) → `group_id_map`; `Container.members`/`Container.host` (NodeId) → `node_id_map`.
- `n*` and `g*` namespaces are disjoint by construction → no collisions, no collision loop.
- `is_dynamic` for a param: `bool(source_refs_in(str(value)))` using
  `src/pflow/core/workflow/graph/scope.py` (`source_refs_in`, scope.py:15-40).

**Predicates / derived views to call (do NOT re-derive):** `graph.is_decision(nid)`,
`graph.is_terminal(nid)`, `graph.shadowed(edge)` (model.py). Per `graph/CLAUDE.md` Load-Bearing
Invariants — derive the visual end-sink from `is_terminal()`, not raw edges.

---

## Phase 1 — `Node.params` model extension

**Files:** `src/pflow/core/workflow/graph/model.py`, `src/pflow/core/workflow/graph/build.py`.

1. `model.py`: `Node` is a plain (mutable) `@dataclass` at line 77. Add **one field** immediately after
   `param_sources` (line 87): `params: dict[str, Any] = field(default_factory=dict)`. (`Any` is already
   imported.) Invariants (`GraphModel.__post_init__`, model.py:130-226) never read params → safe.
2. `build.py`: at the single body-node construction site (**build.py:96-111**, inside `build_level`
   Pass A), add `params=raw_node.get("params", {})` to the `Node(...)` call — right beside the existing
   `param_sources=_param_source_refs(raw_node, source_file)` (line 108). The raw IR `params` dict is in
   scope there. The 3 synthetic node sites (input/output/end) take no params — leave them.

**Verify (Phase 1):** add to `tests/test_core/test_graph_build.py` a test modelled on
`test_nodes_carry_param_level_source_refs_for_click_to_read` (l.204-228): build a graph from a
hand-built IR whose node has `params` incl. a multi-line `prompt`, assert
`_node(graph, NodeId("x")).params["prompt"] == <full string>` and a scalar param round-trips.
**Mermaid goldens must stay byte-identical** (params are Mermaid-invisible) — run
`tests/test_core/test_mermaid_golden.py`.

## Phase 2 — `render_react_flow` translator + typed contract

**New file:** `src/pflow/core/workflow/graph/renderers/react_flow.py` (the dataclasses above +
`render_react_flow`). Mirror `render_mermaid`'s factory shape (mermaid.py:49-52): a thin free function
optionally wrapping a small private builder. **Build only the small structural maps you need inline**
(`node_id_map`, `group_id_map`, and a `nodes_by_id`/`children_by_parent` if convenient — these are
trivial dict comprehensions, ~5 lines; do NOT introduce a shared base class for them). **Do not import
or touch `mermaid.py`.**

**Register exports:**
- `src/pflow/core/workflow/graph/renderers/__init__.py`: add
  `from ...renderers.react_flow import render_react_flow` and extend `__all__`.
- `src/pflow/core/workflow/graph/__init__.py`: import alongside `render_mermaid` (line ~17) and add to
  `__all__` (lines 19-33).

**Reuse:** consume only `GraphModel` + its derived methods (renderer purity — `graph/CLAUDE.md`).
Per-node ports are **not** emitted; the frontend derives them. Workflow-level IO nodes (kind
`input`/`output`, `port` set, `io=IOPort`) pass through as ordinary `RFNode`s.

**Verify (Phase 2):** new file `tests/test_core/test_graph_react_flow_renderer.py` (mirror
`test_graph_mermaid_renderer.py`'s property-assertion style — assert structural properties, not frozen
strings):
- every `RFEdge.source`/`.target` resolves to an emitted `RFNode.id`; every `RFNode.parent`/
  `RFGroup.parent`/`RFGroup.host`/`RFGroup.members` resolves to an emitted id.
- a template `"${a.x} and ${b.y}"` produces **two** `data_flow` edges into the consuming node, each with
  `input_name` set; a pure-literal param has `is_dynamic=False`.
- every `RFNode.ref` equals its source `NodeId` (`node_id` + ancestor_path), `port=None` for body nodes.
- `is_decision`/`is_terminal` present and match `graph.*`.
- `json.dumps(asdict(render_react_flow(graph)))` round-trips on an adversarial graph (reuse the
  adversarial-values shape from `test_graph_build.py:694-713`).

## Phase 3 — `pflow ui` command, Starlette server, `[ui]` extra, packaging

**New files:** `src/pflow/cli/commands/ui.py` (the Click command), `src/pflow/ui/server.py` (the
Starlette app + endpoint logic), `src/pflow/ui/__init__.py`.

1. **CLI command** `cli/commands/ui.py`: `@click.command(name="ui")`, args `workflow` (optional,
   name OR path), `--port` (default e.g. 8765), `--no-open`. Body:
   - Lazily `import` the server module; catch `ImportError` for starlette/uvicorn → print
     `→ pip install pflow[ui]` and `ctx.exit(1)`. (Keeps base install working without the extra.)
   - `uvicorn.run(app, …)` **blocks**, so schedule the browser open *before* it: a
     `threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/?workflow=…"))` (unless
     `--no-open`), then call `uvicorn.run`. If the chosen `--port` is taken, surface a clear error
     (auto-pick is a later nicety).
   Register in `cli/main.py`: lazy import beside line 150 (`# noqa: E402`) + `cli.add_command(ui_cmd)`
   beside line 165. (Pattern verified at main.py:136-166.)
2. **Server** `src/pflow/ui/server.py` (imports starlette lazily / only loaded behind the extra):
   - `GET /api/catalog` → `WorkflowManager().list_all()` **with `ir` stripped** (mirror
     `cli/commands/list.py:44`) → `[{name, description, path: WorkflowManager().get_path(name)}]`.
   - `GET /api/graph?workflow=<name|path>` → reuse the **exact** `visualize.py` path:
     `resolve_workflow(workflow)` (visualize.py:59) → `WorkflowRunner().validate(resolved, params={},
     source_file_path=resolved.file_path)` (visualize.py:67-73) → on `not vresult.valid` return HTTP 422
     with a structured JSON error (don't 500) → else `build_graph(resolved.ir,
     resolve_child=resolve_sub_workflow, base_path=…, source_file=…, max_depth=depth)` (visualize.py:93-103
     pattern; `resolve_sub_workflow` from `core.workflow.sub_workflow_resolver`) →
     `json.dumps(asdict(render_react_flow(graph)))`. Default `max_depth` ≈ 5 (visualize's default).
   - Mount the static bundle: `StaticFiles(directory=<pkg>/ui/static, html=True)` at `/` (serves
     `index.html` + assets). Resolve the dir via `importlib.resources`/`Path(__file__).parent/"static"`.
3. **`pyproject.toml`** (hatchling; no optional-deps table exists yet — this is net-new):
   ```toml
   [project.optional-dependencies]
   ui = ["starlette>=0.40", "uvicorn>=0.30"]   # pin to current stable at implementation time
   ```
   No wheel-inclusion change needed: the bundle under `src/pflow/ui/static/` ships via the existing
   `[tool.hatch.build.targets.wheel] packages = ["src/pflow"]` (pyproject.toml:88-89). Add
   `starlette`/`uvicorn` to the `[dependency-groups] dev` list (pyproject.toml:48-61) so tests can run.
   Add `src/pflow/ui/static/` to `.gitignore` (built artifact, not committed).

**Verify (Phase 3):** new `tests/test_cli/test_ui.py`: with dev deps installed, use Starlette's
`TestClient` to assert `/api/catalog` returns JSON and `/api/graph?workflow=<fixture>` returns a payload
whose `nodes/edges/groups` are present and JSON-valid (use `tests/shared/markdown_utils.write_workflow_file`
to materialize a fixture, as `test_visualize.py:14` does). Assert an invalid workflow yields 422 with a
structured error, not a 500.

## Phase 4 — `web/` frontend (Vite + React + React Flow + ELK)

**New top-level dir `web/`** (mono-repo; source only — build output goes to `src/pflow/ui/static/`).
Stack: Vite, React 18, `@xyflow/react` (React Flow v12), `elkjs`. `vite.config.ts` sets
`build.outDir = "../src/pflow/ui/static"`, `base = "./"` (relative asset paths so it serves from `/`).

Modules:
- `web/src/types.ts` — TS types mirroring the `RFGraph` contract (hand-written for v1; codegen from JSON
  Schema is a later nicety).
- `web/src/api.ts` — `fetchCatalog()`, `fetchGraph(workflow)` hitting `/api/*`. **Single seam for data
  loading** (a future overlay adds an events subscription here without touching components).
- `web/src/layout.ts` — ELK layout: map `RFGraph` → ELK graph (nested via `RFGroup` → ELK children),
  run `elk.layout()`, map positions back onto React Flow nodes. Direction param (`elk.direction:
  RIGHT|DOWN`) from the LR/TD toggle. Containers → React Flow group nodes (`type:"group"`, children carry
  `parentNode`/`extent:"parent"`).
- `web/src/nodes/` — custom React Flow node components: `CompactNode` (icon + name + one badge) and
  `DetailedNode` (params as rows: literal → value field; `${ref}` → inline connection chips with
  handles; output handles from outgoing `data_flow` edges). **Keep static data separate from an optional
  `status` prop** (undefined in v1 — overlay-ready).
- `web/src/CatalogView.tsx`, `web/src/GraphView.tsx`, `web/src/App.tsx` — routing-free for v1 (single
  view + catalog sidebar; add React Router v7 **SPA mode** only when a second view appears).
- Interactions: collapse/expand groups (re-run ELK on toggle — client-side, instant), focus+context
  (click node → reveal its in/out edges, dim others), density toggle (Compact↔Detailed), LR/TD toggle,
  click-to-read panel (shows the inline param `value`; `source` gives a file:line "open in editor" hint).

**Local dev workflow:** run the Python server (`pflow ui`) and Vite's dev server concurrently; set
`server.proxy` in `vite.config.ts` to forward `/api` → `http://127.0.0.1:<port>` so the React app hot-reloads
against the live backend. (Production serves the built bundle from the Python server directly — no proxy.)

**Build wiring (see H1 — the original claim here was wrong):** add a `Makefile` target `make ui-build`
→ `cd web && npm ci && npm run build` (outputs into `src/pflow/ui/static/`). The published wheel is
built **in CI** (`.github/workflows/on-release-main.yml`, `uv build`) — which has **no Node step** — so
that workflow must gain `actions/setup-node` + `make ui-build` **before** `uv build`, or the gitignored
bundle ships empty. Local `uv build`/`hatch build` likewise requires `make ui-build` first (or a
hatchling build hook). Details in **Review Hardening → H1**.

**Verify (Phase 4):** `cd web && npm run build` succeeds and emits `src/pflow/ui/static/index.html` +
assets. Optional light Vitest smoke: `layout.ts` produces positions for a sample `RFGraph` and the app
renders it without throwing. (Keep frontend tests minimal for v1.)

## Phase 5 — Docs, purity guard, end-to-end verification

- **CLAUDE.md:** update `src/pflow/core/workflow/graph/CLAUDE.md` (note the `react_flow` sibling renderer
  + `Node.params`); add `src/pflow/ui/CLAUDE.md` (server + endpoints + the resolve→validate→build reuse)
  and `web/CLAUDE.md` (frontend structure, the data-loading seam, the overlay-ready `status` separation).
  Use the `claude-md-update` skill conventions.
- **Optional model-purity test** (the invariant is currently prose-only — verified no such test exists):
  `tests/test_core/test_graph_model_purity.py` — assert `model.py`/`build.py` source contains no
  React-Flow/Mermaid render tokens (`elk`, `position`, `classDef`, `:::`, `parentNode`). Cheap; mechanizes
  `graph/CLAUDE.md`'s "no render syntax in the model." Include it.
- **`make check`** clean (ruff/mypy); **`make test`** green.

---

## Reuse map (verified file:line — reuse, don't reinvent)

| Need | Reuse | Location |
|---|---|---|
| resolve → validate → build | `resolve_workflow` → `WorkflowRunner().validate` → `build_graph` | `cli/commands/visualize.py:59,67-73,93-103` |
| sub-workflow expansion | `resolve_sub_workflow` (pass as `resolve_child`) | `core/workflow/sub_workflow_resolver.py` |
| catalog list | `WorkflowManager().list_all()` (strip `ir`) + `get_path(name)` | `core/workflow/manager.py:331,304`; strip pattern `cli/commands/list.py:44` |
| CLI registration | lazy import + `cli.add_command` | `cli/main.py:136-166` |
| ref extraction (`${}`) | `source_refs_in` | `graph/scope.py:15-40` |
| derived views | `is_decision`/`is_terminal`/`shadowed` | `graph/model.py` |
| renderer factory shape | `render_mermaid` | `graph/renderers/mermaid.py:49-52` |
| test: build_graph + closure | hand-built IR + `resolve_child` | `tests/test_core/test_graph_build.py:444-476` |
| test: asdict round-trip | adversarial-values pattern | `tests/test_core/test_graph_build.py:694-713` |
| test: materialize fixture file | `write_workflow_file` | `tests/shared/markdown_utils.py` |

## End-to-end verification

1. `make ui-build` → confirm `src/pflow/ui/static/index.html` exists.
2. `pip install -e '.[ui]'` (or `uv pip install -e '.[ui]'`).
3. `pflow ui examples/agent-orchestration/plan-to-code/run-from-plan.pflow.md` → browser opens; the
   harness renders with **no information loss**: nested sub-workflow/batch/loop containers (collapsible),
   template `${ref}` lines landing on the right params, loop badges, click-to-read prompts. Cross-check
   structure against `pflow visualize <same> --depth 5 --descriptions`.
4. `pflow ui` (no arg) → catalog lists saved workflows; opening one renders it.
5. Acceptance: also render the six patterns (`guide/features/patterns.md`) — each reconstructs from the
   contract.
6. `make test` (incl. the new graph/renderer/CLI tests) green; **Mermaid goldens byte-identical**;
   `make check` clean.
7. Base-install untouched: in a clean env, `pip install -e .` (no `[ui]`) → `import pflow` works,
   `pflow --help` works, and `pflow ui` prints the `pip install pflow[ui]` hint (no crash).

## Risks & edge cases to handle explicitly

- **`unexpanded` nodes** (depth-limit/unresolved/dynamic/cycle): render with an "unexpanded" badge; never
  crash. (Field already on `Node`.)
- **Dynamic batch** (`BatchSpec.items=None`), **0-item batch**: per-item rendering must no-op, not
  `IndexError`.
- **Synthetic IO/END nodes**: no params; render as ports / end sink. `port` distinguishes them.
- **`input_name` is best-effort/lossy** in rare multi-role cases (`graph/CLAUDE.md` Build Notes): if a
  data-flow edge can't be attributed to a specific param row, fall back to a node-level connection.
- **Validation failure**: `/api/graph` returns 422 + structured error; the frontend shows it (no 500).
- **`port` in the ref**: body nodes always `port=None`; the overlay join keys on `(node_id,
  ancestor_path)` only (`graph/CLAUDE.md` Runtime Overlay Join Contract) — carry `port` but don't make
  the join depend on it.
- **Bundle size**: ELK dominates (~1.5–3MB). Acceptable in base wheel (disk, not runtime). If it ever
  bites, lazy-load elkjs as an async chunk or drop to dagre (isolated to `web/src/layout.ts`).

## Out of scope (do not build)

Live-run overlay / SSE / consuming Task 133 JSONL; visual editing / canvas→`.pflow.md` write-back;
auth / multi-tenancy / persistence; React Router (until a second view); TS-type codegen from the
contract.

---

## Review Hardening (folded in from a 4-lens plan review — supersedes conflicting earlier text)

A plan / feature-interactions / impact-completeness / silent-failures review verified the core against
code and **confirmed sound**: Mermaid goldens byte-identical, `__post_init__` invariants never read
`params`, the `n{i}`/`g{j}` injective-id scheme (correctly avoids Mermaid's collision-patched ids), the
`asdict`+`json.dumps` round-trip, and that the GraphModel has a single production render consumer
(`visualize`). The confirmed fixes below apply within the named phase.

### Critical
- **H1 — Release packaging.** Published wheels are built in CI (`.github/workflows/on-release-main.yml`:
  `uv build`), which has **no Node step**, from a checkout where `src/pflow/ui/static/` is gitignored →
  the `[ui]` wheel would ship **empty** and `pflow ui` would 404. Fix: add `actions/setup-node` +
  `make ui-build` to that workflow **before** `uv build`. Local `uv build` needs `make ui-build` first
  (or a hatchling build hook — more robust for sdist). This was the plan's one factual error.
- **H2 — `/api/graph` has THREE failure arms (Phase 3), not one.** Mirror `visualize.py:58-90`:
  (a) `validate(...)` **raises** → 422; (b) returns `not vresult.valid` → 422; (c) valid → build.
  `build_graph` must be unreachable on (a)/(b). The 422 body is JSON via `[d.to_dict() for d in
  vresult.errors]` (verify `Diagnostic.to_dict()` in `core/diagnostic.py` — `Diagnostic`s aren't JSON).
  A build/render exception on validated IR (e.g. a `GraphModel.__post_init__` `ValueError`) is a **loud
  500**, never a 200-with-empty-graph. Serialize with `json.dumps(asdict(payload), default=str)` so
  exotic param values (e.g. YAML-native dates) can't 500. Test all three arms.
- **H3 — `Node.params` non-dict guard (Phase 1).** `raw_node["params"]` may be `None`/str/list in
  unvalidated IR (every other build.py read guards `isinstance(..., dict)`; cf.
  `test_build_graph_tolerates_null_params_via_public_api`). Store
  `params = p if isinstance((p := raw_node.get("params")), dict) else {}`. Add a `params: None` test
  routed through `render_react_flow`, not just `build_graph`.
- **H4 — base-install import boundary (Phase 3).** `cli/commands/ui.py` is imported **eagerly** at
  `main.py` load. It must NOT import starlette/uvicorn/the server at module top — only inside the command
  body (catch `ImportError` → install hint). Test: in a clean env without `[ui]`, `pflow --help` and
  `pflow list` succeed.

### Translator correctness (Phase 2)
- **H5 — `is_dynamic` must NOT use `str(value)`.** `str({"text":"${a}"})` contains `${a}` → false
  positive on dict/list params, and disagrees with the edge-builder (which walks string leaves via
  `_params_strings`, build.py:761-772). Derive `is_dynamic` by running `source_refs_in` over the param's
  **string leaves** (one-level descent into dict/list, mirroring `_params_strings`) so it can never
  disagree with the DATA_FLOW edges. Test a dict-valued param and a literal `${5}`.
- **H6 — every DATA_FLOW edge renders (additive, never subtractive).** `input_name=None` is **common**,
  not rare — output-`source:` edges (build.py:629), batch-`items:` edges (build.py:573/579), and the
  multi-role dedup all yield `None`. Hard invariant: `input_name=None` → attach at node level, **never**
  omit. Phase 2 test must include an output-source edge (`input_name=None`, `output_field` set) and
  assert presence; fix the happy-path test to use **two distinct source nodes** (`a`,`b`) so "each with
  `input_name` set" is reliable.
- **H7 — surface container `unexpanded_items`/`warnings`.** A literal-batch item that fails to expand is
  recorded on `Container.annotations["unexpanded_items"]={index:reason}` (NOT on a node); child warnings
  on `Container.annotations["warnings"]`. Forward them (they ride `RFGroup.annotations` via asdict —
  assert it) and **render per-item badges**, distinguishing the four `UnexpandedReason` values. Phase 2
  test: a failed batch item is distinguishable from a genuine leaf (the "no information loss" bar).
- **H8 — host is NOT 1:1 with groups; expanded hosts are groups, not leaves.** A
  dynamic-batch-of-subworkflow emits **two** containers with the same `host` (a `batch` + a `workflow`,
  build.py:290/379); a loop-on-expanded-subworkflow node is **both** an `RFNode` (carrying `loop`) and an
  `RFGroup.host`. Fix: (a) any frontend host lookup keys on `(host, kind)` or group id — never one group
  per host; (b) the translator flags an `RFNode` as "materialized as a group" when its id is some
  `RFGroup.host` (kind workflow/batch) and the frontend **suppresses its leaf box** (reads the loop badge
  off the host node). Test the dynamic-batch-of-subworkflow and loop-on-subworkflow fixtures (both exist
  in `test_graph_mermaid_renderer.py:105`).
- **H9 — representative batch items, not all N.** Bound inline-all-params against batch×depth fan-out
  (a child under a 50-item literal batch inlines its prompts 50×). Mirror Mermaid's representative-item
  truncation (`_visible_batch_indexes`, ≤2 + a "×N" indicator); per-item data still rides
  `RFNode.batch.items`. This also dissolves the shadowed-batch-coverage concern: **the advanced view
  shows ALL DATA_FLOW edges (shadowed is a dim-only hint, never a hide)** → no render-aware shadowing.
- **H10 — contract precision + missing tests.** Emit `RFRef.ancestor_path[].batch_index` explicitly
  (`null` for dynamic) — the load-bearing overlay join key must be stable. Add a **branching** test
  (decision node, ≥2 distinct BRANCH labels + an ERROR edge → labels survive, `is_decision` matches) and
  an **adversarial-params** round-trip test (populate `Node.params` with a YAML date, nested dict,
  multi-line string, `None`). Phase 4: reconcile `is_terminal` nodes + synthetic `kind="end"` nodes +
  `kind="end"` edges into one visual sink per level (mirror `_render_end_nodes_and_edges`).

### Simplification & completeness
- **H11 — extract the resolve→validate→build helper.** `pflow ui` would be the THIRD copy (after
  `visualize.py` and `analyze_cache.py`). Extract `resolve_validate_build(workflow, *, max_depth) ->
  GraphModel` (raising a typed validation error the caller maps to exit-1 OR 422); `ui` uses it.
  Visualize/analyze adoption is an optional low-risk follow-up (don't perturb the Mermaid goldens).
- **H12 — purity test precision (Phase 5).** Word-boundary matching (so `position` ≠ `decomposition`),
  and assert `react_flow.py` imports only `model`/`scope`, **never** `mermaid` (renderers must not drift
  into shared helpers).
- **H13 — Phase 4 verification (was too thin).** Replace "npm build succeeds" as the sole gate with
  per-sub-feature checkpoints against the harness: collapse/expand re-layout; chips land on the right
  rows (incl. the `input_name=None` node-level case); focus+context; dynamic-batch source badge + 0-item
  indicator; the four unexpanded reasons; expanded-host-as-group (no phantom leaf). Specify error text for
  port-in-use and workflow-not-found.

### Spec follow-up (cannot edit in plan mode)
`task-168.md` still says "large values stay as `source_ref`, lazy-fetched" — after approval, update it to
the decided **inline-all + representative-batch-items** approach (H9 bounds the fan-out that requirement
guarded against) so spec and plan agree.
