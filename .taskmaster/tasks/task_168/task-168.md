# Task 168: Workflow Visualization Web UI — Static Structure Viewer

## Description

An interactive, browser-based visual UI for *seeing and understanding* a pflow workflow: its
structure, its input→node wiring, the template-variable (`${ref}`) connections between nodes, and
its prompts/params (click-to-read). Delivered as a local web server serving a React Flow canvas over
a typed JSON contract derived from the Task 155 GraphModel. This is the **static** first increment of
a longer arc (see *Scope* and ADR-0005); the live-run **observability** overlay and visual **editing**
are deliberately later, separate increments.

## Status

done

## Priority

high — leads the "see / understand the agentic harness" track (promoted from medium during the
strategy sessions; the unblocked, low-risk first layer of the visual-UI vision).

## Problem

pflow workflows are authored as text (`.pflow.md`), and a real one — e.g. the Task 163 plan→code
harness — is a **deep tree of sub-workflows** with batch, loops, and many `${...}` template
references threading data between nodes. The load-bearing user quote: *"It's very hard for me as a
human user to understand how this agentic workflow actually works and I NEED to have full control."*

The specific comprehension gaps:
- **The data-flow graph is implicit.** A node's connections come from `${ref}` templates scattered
  across params/files; the wiring they imply is invisible in the text. (This is exactly where a
  text-first tool differs from a draw-by-hand builder like Flowise: in pflow the connections are
  *derived from code*, so a viewer's job is to *reveal* structure the author created implicitly.)
- **Mermaid (`pflow mermaid`) is the $0 baseline but static text** — it cannot collapse/expand a
  deep sub-workflow tree interactively, nor let a user click a node to read its prompt/params.
- No way to *see* params, the dynamic-vs-hardcoded distinction, or per-node template connections.

## Solution

A local **ASGI web server (Starlette)**, shipped behind an optional **`pflow[ui]` extra**, that
serves a **React Flow** single-page app over a typed JSON contract. The contract is produced in
Python by a new **`render_react_flow(graph)` translator** (a second renderer alongside
`render_mermaid`, consuming the Task 155 GraphModel). Layout is computed **client-side with ELK**.

First increment serves the **static** view only:
- A workflow **catalog** (list all workflows from the registry) + a per-workflow **graph**.
- Nodes rendered with type, description, **params** (values + the dynamic/hardcoded distinction),
  and **input/output ports**.
- **Template connections** (`${ref}`) drawn as lines between nodes (the GraphModel's `DATA_FLOW`
  edges — one per `${ref}`).
- **Click-to-read** prompts/params (all param values — including full prompts/code — ship inline in the
  `/graph` payload; the click panel just surfaces them, no on-demand fetch).
- Interactive **collapse/expand** of containers (sub-workflow / batch / loop) and **focus+context**
  (click a node → reveal just its connections).
- Two **density modes** over one model: an "advanced" detailed node (ports + param values + wiring)
  and a "beautiful" compact node — the same data at different detail, not two apps.

Why a server (not a static HTML export or a JSON-only dump), why behind an extra, and why an ASGI
server specifically: recorded in **ADR-0005** — do not re-derive. The short version: the real
destination is live observability + a future hosted platform; a `file://` page can't tail a live Run
log, so streaming intrinsically needs a server, and the ASGI shape is what the cloud will run.

## Design Decisions

The cross-cutting "why a server" decision lives in **ADR-0005** (and its *Considerations* section
holds the wire-contract rationale). The decisions specific to this task:

- **Wire contract = a Python `render_react_flow(graph)` translator, NOT raw `asdict(GraphModel)`**
  (the "Option B" choice). `asdict` is not React Flow's shape (`NodeId` is a nested object, not a
  string `id`; `Container` must map to `parentNode`) and — more consequentially — it **drops the
  derived views** (`is_terminal`/`is_decision`/`shadowed` are *methods*, not fields), forcing the
  frontend to re-implement model semantics in JS and risk drift. The translator keeps flat-id
  derivation and the predicates in Python as **one source of truth**. The contract is a stable,
  React-Flow-native, typed payload decoupled from the model's internals. (Rationale: ADR-0005
  *Considerations*.)
- **Param values live in the model (`Node.params`), not joined from the IR at render time** ("c1").
  Keeps renderers symmetric (`render_react_flow(graph)` like `render_mermaid(graph)` — a renderer
  consumes the model, not the IR), gives one complete static read-model (structure + authored
  config — consistent with `LoopSpec`/`BatchSpec` config already on the model), and is editor-ready.
  Exercises the per-node extension seam Task 155 explicitly left. **Payload discipline (decided
  inline-all):** ALL param values inline in `/graph` — including full prompts/code. The server re-parses
  the small `.pflow.md` per request, so values are already in hand; this retires the entire by-ref
  machinery (no lazy-fetch endpoint, no file-by-line reader, no `is_large` flag). The `batch×depth`
  fan-out the old by-ref scheme guarded against is instead bounded by **representative-batch-item
  truncation** inside `render_react_flow` (mirrors Mermaid's `_visible_batch_indexes`: ≤2 expanded items
  + the count), while the full per-item descriptors still ride `RFNode.batch.items`.
- **Predicates baked as facts in Python; visual policy in TS.** `is_decision`/`is_terminal`/`shadowed`
  ship as booleans. The frontend decides treatment — and the React Flow view picks its **own**
  `shadowed` policy (advanced mode *dims* shadowed structural edges; simple mode *hides* them); it
  must **not** copy Mermaid's deliberately narrower `_edge_shadowed_for_render`.
- **Layout is client-side (ELK / `elkjs`), dagre as fallback.** React Flow ships no autolayout; the
  GraphModel carries no positions. Client-side layout keeps the contract presentation-free, enables
  instant **re-layout on collapse/expand** (no server round-trip), avoids a Python layout system
  dependency (Graphviz), and handles pflow's **nested/compound** containers (ELK's strength;
  dagre is weak on nesting). Direction (LR/TD) is a render knob + UI toggle, default LR; not in the
  model.
- **Modes = one model at different density**, not two data models or two apps. Advanced is the
  priority; beautiful is a *projection* (shows less). Focus+context (per-node expand) is the same
  data + an interaction. None of these affect the contract.
- **View-first; editing is a deferred, named axis.** This increment is read-only. A future visual
  *editor* (change params, write back to `.pflow.md`) comes after the observability overlay + HITL
  (Task 125). The per-param `SourceRef` already in the contract is the seam that later makes
  write-back *surgical* (target a source line) rather than a destructive file regeneration.
- **Static and runtime are two uncoupled substrates.** The GraphModel (this task) carries **zero**
  runtime data; the runtime event stream (Task 133's JSONL) carries **zero** structure. They share
  only the **structural `NodeId`** as a join key (ADR-0003 / the "Runtime Overlay Join Contract" in
  `graph/CLAUDE.md`). The contract therefore carries, per node, **both** a flat string `id` (for React
  Flow) **and** the structural `ref` (the future-overlay join key) — *do not flatten the structural
  identity away.*
- **Frontend lives in a mono `web/` directory** (not a separate package yet). The cloud is the only
  reason to split, and it isn't concrete — premature decoupling. The contract is the reuse seam, not
  the repo boundary; split when the cloud is real.
- **Command:** a new `pflow ui` verb (do not overload `visualize`, which means "emit Mermaid text").

## Dependencies

- **Task 155 (GraphModel) — DONE.** This task consumes `build_graph()` + the `graph/` package and
  adds `render_react_flow` alongside `render_mermaid`. The `Node.params` extension (c1) is a small
  follow-on change to `build_graph`/`model.py` and is **part of this task**.
- **Task 133 (Trace/Cache Storage Architecture)** — *not* a dependency of the static increment.
  Relevant only to the deferred live-overlay increment (its JSONL is the runtime source). The static
  contract is designed to be forward-compatible (it carries the structural `ref`); no overlay code is
  built here.

## Requirements

### Backend — `render_react_flow` translator + contract
- A `render_react_flow(graph: GraphModel) -> <typed payload>` lives in `graph/renderers/`, consumes
  **only** the GraphModel (+ its derived methods), and emits `{nodes, edges, containers}`.
- Per **node**: a flat string `id`; the structural `ref` (`node_id`, `ancestor_path`, `batch_index?`);
  `kind`; `purpose`; `params: [{name, value|null, is_dynamic, source: {file, line}}]`; ports;
  `loop?`; `batch?`; `parent` (container id); node-level `source`; baked `is_decision` / `is_terminal`;
  `annotations`.
- `is_dynamic` per param is **derived** — run the shared `source_refs_in` extractor over the value's
  string leaves (the string itself, or a dict's string values; mirrors `build_graph`'s `_params_strings`
  so it can never disagree with the `DATA_FLOW` edges), **not** a raw `str(value)`/`${` substring check.
  So a literal operand like `${5}` correctly reads static. Not a separate stored flag.
- Per **edge**: `{id, source, target, kind, label?, output_field?, input_name?, shadowed}`. One
  `DATA_FLOW` edge per `${ref}`; the frontend joins it to a param row by `input_name` and to the
  source's output by `output_field`. `input_name` is **best-effort** (lossy in rare multi-role cases,
  per the 155 review) — the renderer/frontend must degrade gracefully to a node-level connection
  rather than mis-attribute.
- Per **container**: `{id, kind, parent?, host?, members[], nesting_depth, loop?, annotations}`.
- The payload carries **no positions** and **no colors/shapes** (layout + styling are the frontend's).
- The flat-id derivation (collision-safe) lives in **one** Python place (may reuse/simplify Mermaid's
  `_assign_flat_ids`). React Flow ids are not user-visible, so a simpler injective scheme is allowed.
- `json.dumps(asdict(<payload>))` must round-trip; a test pins it (none guards it today).
- The contract is **defined once** as typed Python (the seam all consumers cite: local UI, future
  cloud, future overlay, future editor). TS types generated from it (e.g. via JSON Schema) is a
  nice-to-have, deferred until drift threatens.

### Backend — model change (`Node.params`)
- `build_graph` populates `Node.params` with authored param **values** (small literals/templates
  inline; large `prompt`/`code` values omitted/by-`source_ref`). `build_graph` already has params in
  hand (it parses `${}` for data-flow), so this is near-zero added work.
- `render_mermaid` is unaffected (it ignores `Node.params`); the existing Mermaid goldens stay
  byte-identical.

### Server & packaging
- A local **Starlette** server (`pflow ui <workflow>`): serves the built React bundle, a `/api/graph`
  JSON endpoint (the translator's payload, with all param values inline — so **no** separate
  click-to-read endpoint), and an `/api/catalog` list. **No `/events` SSE stub** in this increment:
  overlay-readiness is the structural `ref` in the contract + pluggable frontend data-loading, not a
  dead route.
- The server + frontend bundle + web-stack deps ship **only** behind a `pflow[ui]` **extra**. Base
  `pip install pflow` gains **no** new runtime dependency and **no** bundle. `pflow ui` without the
  extra prints a clear `→ pip install pflow[ui]` hint (no runtime download).
- The frontend bundle is built at release time (CI/Vite) and shipped as a static asset; **end users
  never run npm/Node**.

### Frontend
- **Vite + React + React Flow** (target React Flow v12 / `@xyflow/react`), client-only SPA. Any
  routing uses React Router v7 in **SPA/data mode** (not framework/SSR mode), added only when a
  second view exists.
- **ELK** client-side layout (dagre fallback); LR default with an LR/TD toggle.
- Renders: catalog → per-workflow graph; nested containers as collapsible groups (`parentNode`/
  `extent`); template `${ref}` connections as lines onto the correct param rows (interpolated params
  show literal text + an inline connection-chip per ref); click-to-read; advanced/beautiful density +
  focus+context.
- The node component keeps **static data separate from a future optional `status` prop** (undefined
  in static mode), and data-loading is pluggable (`/graph` now; `+ /events` later) — so the overlay
  is additive, not a rewrite. **No** SSE client, runtime store, or status styling is built here.

### Scope boundaries (explicit non-goals for this increment)
- No live-run overlay / no consuming Task 133's JSONL / no SSE wiring (architected-for only).
- No visual editing / no canvas→`.pflow.md` write-back.
- No multi-tenancy / auth / persistence (those are cloud concerns, deliberately not pre-built).

## Implementation Notes

- **Integration points:** `src/pflow/core/workflow/graph/build.py` + `model.py` (`Node.params`);
  `graph/renderers/` (new `render_react_flow`, registered in `renderers/__init__.py`); a new CLI
  command (`pflow ui`) wired in `cli/main.py`; `pyproject.toml` (`[project.optional-dependencies] ui`);
  a new `web/` frontend tree.
- **Renderer purity:** `render_react_flow` must consume only the GraphModel and its derived methods
  — do **not** re-derive `is_terminal` by a raw edge walk, and do **not** pass the IR into the
  renderer (param values come from the model via c1).
- **The `shadowed` trap:** emit the model's general `shadowed()` *fact*; let the frontend choose the
  visual policy per mode — do not bake Mermaid's narrower render policy into the contract.
- **Forward-compat check (for the later overlay, recorded now):** the structural `ref` emitted in the
  contract must be the exact join key the Task 133 JSONL events key on — align against
  `graph/CLAUDE.md` → "Runtime Overlay Join Contract" when the contract is pinned.
- The detailed `pflow mermaid` Mermaid view (`--depth 5 --descriptions`) is the $0 baseline and a
  useful cross-check while building.

## Verification

- **Acceptance = completeness, not matching a specific visual design.** Rendering the **Task 163 harness**
  (`examples/agent-orchestration/plan-to-code/`) and the six workflow patterns
  (`guide/features/patterns.md`) through the GraphModel → `render_react_flow` → React Flow reconstructs
  structure, input→node wiring, template connections, containers, loops, and batch **with no
  information loss**.
- **Template connections:** a param like `"${a.x} and ${b.y}"` renders as **two** connecting lines
  (one per ref) landing on that param; a pure-ref param renders as a connected port; a pure literal
  shows a value with no line.
- **Click-to-read:** clicking a node surfaces its prompt/params straight from the inline `/api/graph`
  payload (values are already present — no on-demand fetch). Batch fan-out is bounded by
  representative-item truncation, so the payload stays small.
- **Interactivity:** collapse/expand a sub-workflow/batch/loop container re-layouts instantly
  (client-side); focus+context reveals a single node's connections; LR/TD toggle works.
- **Modes:** the same workflow renders in advanced (ports + params + wiring) and beautiful (compact)
  density from one contract.
- **Packaging:** base `pip install pflow` has no new runtime dep and no bundle; `pflow ui` without the
  extra prints the install hint; `pflow[ui]` serves the UI offline (no runtime download).
- **Regression:** Mermaid goldens stay byte-identical (the `Node.params` change is Mermaid-invisible);
  `json.dumps(asdict(render_react_flow(graph)))` round-trips (new test).

## References

- **ADR-0005** (`context/adr/0005-web-ui-local-server-delivery.md`) — delivery = web server; the
  *Considerations* section holds the wire-contract rationale. **The "why" for this task; cite, don't
  restate.**
- **ADR-0003** (GraphModel structural node identity — the overlay join key) and **ADR-0004**
  (primitive-only model).
- **`CONTEXT.md`** — Run / Workflow→Run; Graph model; IR; Container.
- **Task 155 review** (`.taskmaster/tasks/task_155/task-review.md`) and the `graph/` package +
  `src/pflow/core/workflow/graph/CLAUDE.md` (model contract, derived-view invariants, "Runtime Overlay
  Join Contract").
- **Task 133** (`.taskmaster/tasks/task_133/task-133.md`) — the deferred runtime JSONL the later
  overlay consumes (D1–D3); not a dependency of this static increment.
- **Test subjects:** the Task 163 harness (`examples/agent-orchestration/plan-to-code/`) and the six
  workflow patterns (`guide/features/patterns.md`) — the real workflows the viewer must render
  completely.

> **Next artifact: the implementation plan** (separate). This task is the *why / what / spec*; the
> plan is the *how* — phase by phase, file by file, with per-phase verification (the `Node.params`
> extension → `render_react_flow` → the `pflow ui` server + `[ui]` extra → the Vite/React/ELK
> frontend → contract typing).
