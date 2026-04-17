# Task 155: Extract Workflow Graph Model for Multi-Renderer Support

## Description

Refactor the mermaid visualizer to build an intermediate **semantic graph model**, then render from that model. This separates "what to draw" (IR-walking logic) from "how to draw it" (mermaid syntax), enabling a future React Flow (or equivalent) web UI to reuse the IR walker unchanged.

Positioned as a **pre-step** to the planned web-based interactive visualizer: done just before UI work begins so the UI effort only needs a new renderer, not a reimplementation of graph construction.

**Builds on Option X** (the `Scope` + unified `resolve_ref` consolidation done on branch `fix/cluster-mermaid-visualizer-fidelity`, which closed GH #283 and #263). Task 155 assumes that baseline: `Scope` exists, ref resolution is centralized, `_RESERVED_PARAMS` and `_SOURCE_NODE_FIELD_RE` are gone. The remaining architectural gap is the absence of an intermediate data layer — what this task extracts.

## Status

not started

## Priority

medium

## Problem

### Architectural debt: text-in-text-out

The current mermaid package (`src/pflow/core/workflow/mermaid/`, ~1500 lines across 5 files) is text-oriented end to end. Every function appends strings to `ctx.lines`. There is **no intermediate data structure** between workflow IR and mermaid syntax. As a result:

- Adding a second renderer (React Flow, Cytoscape, DOT, JSON API) requires duplicating every IR-walking decision (which node renders as what, which edges exist, how sub-workflows nest, how batch items fan out).
- Parsing the mermaid output back into structured data is not viable (mermaid syntax is lossy for our purposes, and `classDef` + shape directives are write-only).
- Task 145's review explicitly anticipated this: *"Mermaid ships fast and doesn't compete with building a browser visualizer later — the same IR-to-graph logic feeds both."* The design intent was documented; the code never realized it.

### No separation between graph construction and rendering

Option X consolidated reference resolution behind a single `Scope.resolve()` primitive and fixed the two fidelity bugs it had caused. What it did **not** change is the text-in-text-out shape of the package: every structural decision about the diagram is made by a function that immediately appends mermaid syntax to `ctx.lines`. The IR-walking logic and the rendering logic are interleaved in the same call stack.

That shape is the remaining blocker for a second renderer. To ship a React Flow (or Cytoscape, or DOT, or a JSON API) view, there is currently no choice but to parse mermaid text back into structured data (lossy and brittle) or reimplement every IR-walking decision from scratch in a parallel package — duplicating sub-workflow expansion, batch item fan-out, external IO wrapping, cycle detection, data-flow edge inference, and the `outgoing_routes` / `fork_join_map` / `data_flow_targets` interaction rules.

Task 145's review anticipated exactly this: *"Mermaid ships fast and doesn't compete with building a browser visualizer later — the same IR-to-graph logic feeds both."* The design intent was recorded; the code never realized it.

## Solution

### Two-layer architecture

```
   IR  →  build_graph()  →  GraphModel  ─┬─→  render_mermaid()   →  str
                                         ├─→  render_react_flow() →  {nodes, edges}    (future)
                                         ├─→  render_dot()        →  str                (future)
                                         └─→  as_json()           →  API payload        (future)
```

**Layer 1 — IR-walking & graph construction**: one pass over the workflow IR (including sub-workflow expansion, batch item expansion, ref resolution) produces a `GraphModel` — a pure data object. All decisions about "what should be drawn" live here.

**Layer 2 — Renderers**: each renderer consumes `GraphModel` and emits its target format. Mermaid is the first (and currently only) renderer. Future renderers (React Flow, etc.) do not touch IR; they only translate the model.

### Consolidated reference resolution

Introduce a `Scope` object representing everything named at one workflow level: nodes, inputs, outgoing routes, batch source. One method — `Scope.resolve(root, field) -> Optional[str]` — handles the three-case resolution, used by every edge emitter in the IR walker. Eliminates `_resolve_ref_source`, the open-coded loop in `_connect_sources_to_output`, and the scattered nested-dict descents.

### Semantic, not syntactic, model

`GraphModel` describes **what nodes are** (kind, shape category, label, purpose, batch metadata), not **how mermaid draws them**. No `classdef="shell"` strings, no mermaid-specific shape brackets, no inline style directives in the model. Each renderer maps semantic fields to its own vocabulary.

This is the load-bearing constraint: if the model leaks mermaid syntax, a React Flow renderer becomes a translation layer over a mermaid-shaped thing — worse than not refactoring at all.

## Design Decisions

- **Do the full refactor, not the smaller Scope-only consolidation.** The Scope refactor (fixing both bugs by consolidating ref resolution) was considered as a cheaper middle ground. Rejected because the web UI is a near-term plan; the Scope refactor would need to be redone as part of the GraphModel extraction later. Doing the full thing once avoids rework.

- **Pre-step, not co-step.** Done *before* web UI work begins, not concurrently. The UI effort then only needs to write a new renderer against a stable `GraphModel`; no co-evolution risk.

- **Semantic model, enforced.** Model fields describe node kind / role / shape-category, never mermaid-specific strings. Renderer maps semantics → mermaid vocabulary at render time. This discipline is what makes the model actually reusable.

- **Public API `generate_mermaid(ir, ...)` signature preserved.** Internal restructure only; all existing CLI callers, tests, and consumers continue to work unchanged.

- **No new runtime dependencies.** `GraphModel` is plain dataclasses. Renderers emit strings (or dicts for structured formats) using stdlib only. Any future web-UI payload would use `dataclasses.asdict` + `json.dumps`.

- **Keep `MermaidContext`'s load-bearing invariants in the IR walker.** The `outgoing_routes` / `has_expanded_outputs` split, the `suppress_io` flag for external IO, and the fork/join map all represent real structural facts about the graph — they become fields on `GraphModel` subgraph/node records, not stripped away.

## Dependencies

- **Option X consolidation** (branch `fix/cluster-mermaid-visualizer-fidelity`) — introduces `Scope` + unified `resolve_ref`, deletes `_RESERVED_PARAMS` / `_SOURCE_NODE_FIELD_RE`, closes GH #283 and #263. Must land before 155 starts. Task 155 assumes that baseline.

Task 155 is itself a prerequisite for the planned (not yet filed) web-based interactive visualizer task.

## Requirements

### GraphModel (semantic data layer)

- Pure dataclasses. No mermaid strings, no classDef names, no shape brackets in field values.
- Node records carry: `id`, `kind` (e.g. `"llm"`, `"shell"`, `"code"`, `"workflow"`, `"input"`, `"output"`, `"decision"`), `shape` (e.g. `"rect"`, `"diamond"`, `"parallelogram"`, `"stack"`), `label`, `purpose` (optional), `batch_suffix` (optional), `parent_subgraph_id` (optional).
- Edge records carry: `source` (mermaid-id-equivalent stable ID), `target`, `kind` (`"structural"` | `"data_flow"` | `"error"`), optional `label`.
- Subgraph records carry: `id`, `label`, `nesting_depth`, `kind` (`"workflow"` | `"batch"` | `"input_wrapper"` | `"output_wrapper"`), `parent_subgraph_id` (optional).
- Stable IDs use the existing convention (`{prefix}{node_id}`, `{prefix}{node_id}__in_{name}`, etc.) — don't invent a new ID scheme, since the convention is already load-bearing.

### Scope (inherited from Option X)

- `Scope` type already consolidated by X: one `Scope.resolve(root, field) -> Optional[str]` handling batch / node / input cases. Task 155 does not redesign it; it reuses Scope as graph-construction state.

### IR walker (`build_graph`)

- One entry: `build_graph(ir, resolve_child=..., base_path=..., max_depth=..., descriptions=...) -> GraphModel`.
- Handles sub-workflow recursive expansion (with cycle detection via recursion stack, as today).
- Handles batch item expansion and fork/join fan-out.
- Handles external IO wrappers for expanded sub-workflows.
- Handles data-flow edge inference from `${ref}` templates via `Scope.resolve`.
- Emits zero mermaid syntax. Produces `GraphModel` records only.

### Mermaid renderer

- `render_mermaid(graph: GraphModel, *, direction: str = "LR") -> str`.
- Consumes the semantic model; emits mermaid syntax.
- Maps `kind` / `shape` to mermaid classDef names and shape brackets at render time.
- Output matches current generator byte-for-byte for IR shapes that aren't affected by #283/#263 (see Verification).

### Public API

- `generate_mermaid(ir, ...)` signature unchanged. Internally implemented as `render_mermaid(build_graph(ir, ...))`.
- All `tests/test_core/test_mermaid.py`, `test_mermaid_golden.py`, `tests/test_cli/test_visualize.py` continue to pass (with golden regeneration for #283/#263 affected files).

### Extension seam for future renderers

- `GraphModel` is importable from `pflow.core.workflow.mermaid` (or a better-named module — see Implementation Notes).
- `build_graph` and `render_mermaid` are both importable separately, not only as the combined `generate_mermaid`.
- A future `render_react_flow(graph: GraphModel) -> dict` can be added without touching `build_graph`. Verified by writing a throwaway 20-line sketch during implementation (not committed — just to confirm the model is sufficient).

## Implementation Notes

### Current architecture (what's being replaced)

- `src/pflow/core/workflow/mermaid/` — 5 files, ~1500 lines.
- `_render.py` (470 lines) — pipeline orchestration (`generate_mermaid`, `_render_workflow`, `_render_node`, batch, subgraph, end nodes).
- `_edges.py` (293 lines) — structural edge routing, data-flow edge generation, ref resolution.
- `_io.py` (351 lines) — input/output rendering (top-level, sub-workflow, external wrappers).
- `_context.py` (289 lines) — `MermaidConfig`, `MermaidContext`, constants, utilities.
- `MermaidContext` currently mixes per-level routing state (`outgoing_routes`, `incoming_map`, `data_flow_targets`, `fork_join_map`) with rendering concerns (`ctx.lines`, `ctx.indent`). After the refactor, most of these routing maps move into `GraphModel`-construction state; only a thin `RenderContext` holding `lines` and `indent` remains in the renderer.

### Mapping current features to new layers

| Current responsibility | New home |
|---|---|
| Sub-workflow resolution & cycle detection (`_try_resolve_child`) | IR walker |
| Batch item expansion, fork/join map | IR walker → `GraphModel.subgraphs` (kind=`"batch"`) |
| External IO wrappers (`_render_external_inputs/outputs`) | IR walker → `GraphModel.subgraphs` (kind=`"input_wrapper"`/`"output_wrapper"`) |
| Data-flow edge generation (`_generate_data_flow_edges`, `_generate_batch_item_data_flow`) | IR walker, using `Scope.resolve` |
| Output source parsing (`_connect_sources_to_output`) | IR walker, using `Scope.resolve` |
| Top-level input → consumer wiring (`_connect_top_level_inputs`) | IR walker, using `Scope.resolve` + nearest-consumer heuristic preserved |
| Edge dedup, decision detection, terminal detection | IR walker (pre-graph preprocessing) |
| Structural edge suppression when data-flow covers (`data_flow_targets`) | Either recorded on edges (`Edge.suppressed_by_dataflow: bool`) or resolved at model-build time |
| Shape & class mapping (`_SHAPE_MAP`, `_CLASSDEF_STYLES`) | Mermaid renderer only |
| `@{ shape: procs }` directive | Mermaid renderer only (maps from semantic `shape="stack"`) |
| Subgraph nesting opacity (`_SUBGRAPH_OPACITIES`) | Mermaid renderer only (reads `nesting_depth` from model) |
| `.md` wrapping with title/description | `cli/commands/visualize.py` — unchanged |

### Semantic vocabulary (starting sketch)

```python
class NodeKind(str, Enum):
    LLM = "llm"; SHELL = "shell"; CODE = "code"; WRITE_FILE = "write_file"
    WORKFLOW = "workflow"; MCP = "mcp"
    INPUT = "input"; OUTPUT = "output"
    DECISION = "decision"; END = "end"

class NodeShape(str, Enum):
    RECT = "rect"; DOUBLE_RECT = "double_rect"
    ROUND_RECT = "round_rect"; STADIUM = "stadium"
    DIAMOND = "diamond"; HEXAGON = "hexagon"
    PARALLELOGRAM = "parallelogram"; CYLINDER = "cylinder"
    STACK = "stack"  # maps to mermaid @{ shape: procs }

class EdgeKind(str, Enum):
    STRUCTURAL = "structural"
    DATA_FLOW = "data_flow"
    ERROR = "error"
```

This vocabulary is a starting point, not a spec. Finalize during implementation — add/rename as the renderer mapping reveals what's actually needed.

### Order of work (suggested)

1. Define `GraphModel` dataclasses. No rendering yet.
2. Write `build_graph` that produces a `GraphModel` from IR, walking the same structure as today but emitting model records instead of mermaid lines. Reuse `Scope` from X. Verify via small unit tests that the model is well-formed.
3. Write `render_mermaid(graph)` that consumes the model and produces mermaid syntax. Target: byte-identical output on all existing goldens.
4. Rewire `generate_mermaid` to be `render_mermaid(build_graph(...))`. Run full mermaid test suite — must pass without golden regeneration.
5. Write the 20-line throwaway React Flow renderer sketch to confirm the model is sufficient. Discard after.

### Module layout consideration

Current layout has `mermaid/` as a package. After extraction, `build_graph` and `GraphModel` are not mermaid-specific. Two options:

- **A**: Keep everything under `mermaid/` for now, pragmatically named (e.g., `mermaid/graph.py`, `mermaid/render.py`). Move later if/when a second renderer ships.
- **B**: Rename to `visualize/` (or `graph/`) with `graph.py`, `scope.py`, `renderers/mermaid.py`, `renderers/react_flow.py` (later).

Defer this decision to implementation time — don't prematurely commit to B before knowing what the actual code looks like. Option A is the lower-risk default.

### Load-bearing invariants to preserve

From Task 146 review and mermaid CLAUDE.md, these must survive the refactor:

- Recursion-stack `seen` set (add-on-enter, discard-on-exit) for cycle detection — not global visited set.
- Mermaid ID convention (`{prefix}{node_id}`, `{prefix}{node_id}__in_{name}`, `{prefix}{node_id}__out_{name}`) is load-bearing for every lookup; don't change it.
- Top-level inputs connect to **nearest consumer only** (not all consumers) — long-range edges destroy dagre layout.
- `outgoing_routes` and `has_expanded_outputs` are written together (two-field invariant). In the new model, either collapse into a single field or preserve the invariant explicitly with a helper.
- Structural edge suppression when data-flow covers the same connection.

## Verification

### Functional parity (highest priority — this task has NO intended output changes)

- All tests in `tests/test_core/test_mermaid.py`, `tests/test_core/test_mermaid_golden.py`, and `tests/test_cli/test_visualize.py` pass **without golden regeneration**. If a golden changes, investigate — the refactor should be behavior-preserving.
- `make check` clean.

### Architectural criteria

- `GraphModel` dataclasses contain no strings matching `classDef|@{|:::|fill:|stroke:` — i.e. no mermaid syntax leaked into the model. Grep check.
- `build_graph` emits zero mermaid lines (no `ctx.lines.append`, no string formatting with mermaid syntax). Grep check.
- `render_mermaid` consumes `GraphModel` and touches no workflow IR fields directly. Grep check.
- Throwaway React Flow sketch: ~20 lines, consumes `GraphModel`, produces `{nodes: [...], edges: [...]}` matching React Flow's expected shape. Not committed — verifies the model is sufficient for a second renderer.

## References

### GitHub issues (historical context, not scope)

- **GH #283**: Mermaid visualizer: data-flow edges lose fidelity when child inputs use `inputs:` dict. Closed by Option X on branch `fix/cluster-mermaid-visualizer-fidelity`.
- **GH #263**: Mermaid output wiring ignores input-root output sources. Closed by Option X on the same branch.

Both bugs are historical evidence that fragmented ref resolution hides correctness gaps — part of the motivation Option X acted on. Task 155 does not re-fix them; it assumes they are already fixed and preserves that fix through the architectural split.

### Prior tasks (context)

- `fix/cluster-mermaid-visualizer-fidelity` branch — Option X consolidation (Scope, unified resolve_ref). Direct predecessor.
- `.taskmaster/tasks/task_145/task-review.md` — initial mermaid generator (sub-workflow resolver extraction + mermaid flowchart + `visualize` CLI). Contains the original design note: *"the same IR-to-graph logic feeds both"* mermaid and a future browser visualizer — the intent task 155 finally realizes.
- `.taskmaster/tasks/task_146/task-review.md` — rich mermaid visualization (data-flow edges, external IO, batch item expansion, `procs` shape, 163 → 1444 lines). Current architecture's load-bearing invariants are documented here.
- `.taskmaster/tasks/task_153/task-review.md` — `inputs:` dict canonical form. Motivating context for why Scope was needed.

### Code to read before starting

- `src/pflow/core/workflow/mermaid/CLAUDE.md` — file map, function-to-file map, context state table, common pitfalls, testing commands.
- `src/pflow/core/workflow/mermaid/_render.py` — pipeline orchestration (start with `generate_mermaid`, then `_render_workflow`, then `_render_node`).
- `src/pflow/core/workflow/mermaid/_context.py` — `MermaidContext`, constants, utilities.
- `src/pflow/core/workflow/mermaid/_edges.py` — ref resolution, data-flow edges.
- `src/pflow/core/workflow/mermaid/_io.py` — input/output rendering, the call sites that need unification.
- `tests/test_core/golden_mermaid/deep-research-TD.mmd` — reference golden (current coarse form; will be regenerated).
- `examples/nested/deep-research/deep-research.pflow.md` — canonical test workflow exercising `inputs:` dict + batch + sub-workflow.

### External

- React Flow data model (for sketch verification): https://reactflow.dev/learn (nodes/edges shape).
- Mermaid flowchart syntax (renderer target): https://mermaid.js.org/syntax/flowchart.html.
