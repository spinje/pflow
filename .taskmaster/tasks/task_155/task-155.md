# Task 155: Extract Workflow Graph Model for Multi-Renderer Support

## Description

Extract a renderer-agnostic **Graph model** from the mermaid visualizer: one IR walk produces a pure-data model of a workflow's structure, and mermaid becomes the first *renderer* over it. This separates "what to draw" (IR-walking) from "how to draw it" (mermaid syntax), so a React Flow web UI, a live execution overlay, and click-to-read-prompts can be built as new consumers of the model — without re-walking the IR.

155 is the **lead of the "see/understand" track**: the static-structure substrate beneath the planned interactive visualizer. (The runtime/live-overlay data is a separate substrate; the two converge only at the UI.)

Domain vocabulary (`context/CONTEXT.md`): **Graph model**, **IR**, **Container**.

## Status
done

## Priority
high

## Problem

### Text-in-text-out: no intermediate data layer

The mermaid package (`src/pflow/core/workflow/mermaid/`) is text-oriented end to end — every function appends mermaid strings to `ctx.lines`. There is no data structure between the IR and mermaid syntax. Consequences:

- A second renderer (React Flow, DOT, JSON API) must duplicate every IR-walking decision — sub-workflow expansion, batch fan-out, external IO wrapping, cycle detection, data-flow edge inference, and the routing-map interaction rules.
- Mermaid output can't be parsed back into structure (lossy; `classDef`/shape directives are write-only).
- IR-walking and rendering are interleaved in one call stack, so the structural facts can't be reused.

Task 145's review anticipated this: *"the same IR-to-graph logic feeds both"* mermaid and a future browser visualizer. The intent was recorded; the code never realized it. With React Flow now the committed endgame (two real renderers), the seam is earned rather than speculative.

## Solution

### Two-layer architecture

```
   IR  →  build_graph()  →  GraphModel  ─┬─→  render_mermaid()    →  str
                                         ├─→  render_react_flow() →  {nodes, edges, groups}  (future)
                                         └─→  as_json()           →  API payload             (future)
```

- **Layer 1 — `build_graph(ir) -> GraphModel`**: one IR walk (sub-workflow expansion, batch expansion, ref resolution) produces a pure-data model. All "what to draw" decisions live here.
- **Layer 2 — renderers**: each consumes the GraphModel and emits its format. Mermaid is first; React Flow / JSON come later. Renderers never touch the IR.

### Semantic, not syntactic

The Graph model describes what nodes *are* (kind, shape category, label, purpose, loop, batch metadata), never how mermaid draws them — no `classDef` strings, shape brackets, or style directives in the model. This is load-bearing: if the model leaks mermaid syntax, a React Flow renderer becomes a translation layer over a mermaid-shaped thing — worse than not refactoring.

### Packaging

A `graph/` package — the model + `build_graph` at the top (renderer-agnostic), renderers (mermaid now, react-flow later) in a `renderers/` subfolder. `generate_mermaid` is preserved via a compat shim so existing callers don't change.

## Design Decisions

- **Full refactor, not the Scope-only consolidation.** The cheaper Scope-only middle ground was considered and rejected — the UI is near-term, so the GraphModel extraction would redo it. Do it once.
- **Node identity is structural, not a flat string** (ADR-0003). The model identifies nodes by `(node_id, ancestor_path, batch_index?)`; renderers derive their own flat IDs. This lets a future live overlay join runtime events onto static nodes losslessly.
- **Loop is a node property, not an edge** (ADR-0001). The engine re-enters in place and creates no edge; the model carries loop metadata on the node/Container. #483's `_loop_label` decision relocates from the renderer into the model + render split.
- **Primitive-only model** (ADR-0004). Pattern recognition and cycle (SCC) containerization are a separate optional layer, not built here; the model must not preclude them.
- **Public API preserved.** `generate_mermaid(ir, ...)` keeps working via a compat shim; the only coupling is one call site + two test imports.
- **No new runtime dependencies.** The model is plain dataclasses, `dataclasses.asdict` + `json.dumps`-able.

## Requirements

### The Graph model (semantic data layer)

- Pure dataclasses, `asdict`-able, **no mermaid syntax** in any field value.
- **Node record** carries:
  - **structural identity** — `node_id`, `ancestor_path`, `batch_index?` (ADR-0003); not a flat string.
  - **kind** — semantic node type (e.g. `llm`, `shell`, `code`, `write-file`, `workflow`, `mcp`, `input`, `output`, `decision`, `end`).
  - **shape** — semantic shape category (e.g. `rect`, `diamond`, `parallelogram`, `stack`, …), not mermaid brackets.
  - **label**, **purpose** (the human description), optional **batch_suffix**.
  - **loop** (optional) — `{polarity: while|until, condition, cap, carry}` (ADR-0001).
  - **source back-ref** for click-to-read — the param content (incl. `prompt`/`command`/`code`) and the on-disk origin (the IR's `_source_files` / `_source_lines` / `_source_line`), so a UI can open a node's prompt at its source. For synthetic nodes (expanded sub-workflows, batch items) this resolves to the child source + file; a statically unresolvable reference (e.g. a `${template}` workflow path) marks the node opaque rather than dropping it.
  - **annotations** — an open `dict` (the extension seam; no semantics implemented here).
  - **parent** — its containing Container.
- **Edge record** — `source`, `target` (by structural identity), `kind` (`sequential` | `branch` | `error` | `data_flow` | `end`), optional `label`. Structural-edge suppression (and decision/terminal detection) are *derived views* on the model, not stored flags/fields.
- **Container record** — ONE record type for every grouping: `id`, `label`, `kind` (`workflow` | `batch` | `input_wrapper` | `output_wrapper`; `cycle` reserved for the future analysis layer), `nesting_depth`, `parent`, `member_node_ids`, optional **loop**, **annotations**. `kind` must be fine enough for a renderer to choose the correct style (dashed IO-wrapper vs depth-opacity box).

The exact `kind`/`shape` vocabularies above are illustrative — finalize during implementation as the renderer mapping requires. The requirement is that they are *semantic enumerations*, never mermaid strings.

> **Refined during planning** — the implementation plan (`implementation/implementation-plan.md`, §6 "Deliberate deviations") is authoritative where it differs: `shape` and `decision`/`terminal` are *derived*, not stored fields; node identity is `NodeId(node_id, ancestor_path)` with `batch_index` carried on each `AncestorStep` (leaf batch items are `BatchSpec.items` data, not nodes); `Container` links its `host` node and reads loop/batch via it; the source back-ref is a `(file, line)` pointer, not embedded content; and `- next: end` is captured via a small parser field (`_routes_to_end`) and modeled as an `end`-kind edge to a synthetic per-level END node.

### build_graph

- `build_graph(ir, *, resolve_child, base_path, max_depth) -> GraphModel` — a **pure function** of `(IR, resolve_child)`; emits zero rendering syntax. (`descriptions` is a render concern — it lives on `render_mermaid`, not here.)
- Produces a **complete model independent of render order** — its result must not depend on any rendering pass.
- Handles: recursive sub-workflow expansion with **recursion-stack cycle detection** (add-on-enter / discard-on-exit, not a global visited set); batch expansion + fork/join fan-out; external IO wrappers for expanded sub-workflows; data-flow edge inference from `${ref}` templates via `Scope.resolve`; decision and terminal detection.
- **Testable without mocks** — `resolve_child` is the one injected port (real + test adapters already exist); tests assert on the returned GraphModel.

### Mermaid renderer

- `render_mermaid(graph, *, direction="LR", descriptions=False) -> str` — consumes the model; maps `kind` to mermaid classDefs + shape brackets at render time (shape is derived here); derives the flat mermaid IDs (`{parent}__{child}`, batch items by label) from structural identity; renders loop as the ⟳ badge / self-edge shipped in #483. The model always carries `purpose`; `descriptions` only gates whether it appears in the label.
- Reads no IR fields directly.

### Behavioral invariants to preserve

Real structural facts, not cosmetic — the refactor must keep them:

- Recursion-stack cycle detection (above).
- **Top-level input edges** — emitted to each distinct consumer, deduped per `(source, target)` pair (the legacy "nearest-consumer-only" wording is a misnomer: it never collapsed to a single consumer).
- Structural-edge suppression when a data-flow edge covers the same connection.
- The `outgoing_routes` / `has_expanded_outputs` routing maps are **build-time scratch, not model fields** — their behavior (edge routing/suppression) is preserved but reconstructed at build/render, never stored on the model.
- **Flat mermaid IDs derived from structural identity** — the renderer derives `{parent}__{child}` IDs from the model. Byte-identical output is not a contract (parity is a tripwire — see Verification); regenerate goldens when the correct model legitimately shifts them.

### Packaging & public API

- `graph/` package: `model.py` (GraphModel), `build.py` (`build_graph`), `scope.py` (`Scope`), `renderers/mermaid.py` (`render_mermaid`); `renderers/react_flow.py` slots in later.
- `generate_mermaid(ir, ...) == render_mermaid(build_graph(ir, ...))`, re-exported from the old `pflow.core.workflow.mermaid` path via a **compat shim** so the three external importers (`cli/commands/visualize.py` + two test files) need no change.
- No new runtime dependencies.

### Extension seam

- `build_graph` and `render_mermaid` importable separately (not only the combined `generate_mermaid`).
- A future `render_react_flow(graph) -> {nodes, edges, groups}` can be added without touching `build_graph`.

## Non-Goals

- **No analysis layer** (ADR-0004): pattern recognition (tournament, fan-out-synthesize, …) and SCC/cycle containerization are NOT built. The model must not preclude them — keep back-edges faithful, the Container record general, and the `annotations` slot present.
- **No React Flow renderer, UI, or server** — only a throwaway completeness sketch (see Verification), discarded.
- **No annotation semantics** — the slot only. Author-declared annotations end-to-end additionally need a future carve-out in the validator's unknown-param check; out of scope.
- **No change to runtime/trace node identity** — the model *aligns* with the runtime's structural identity; it doesn't alter it.
- **No `carry:`-as-data-flow-edge rendering** — deferred renderer concern.
- The existing **batch-output-fan** limitation is preserved as-is, not fixed.

## Verification

### Functional parity (tripwire, not a contract)

Mermaid parity is a regression *tripwire*, not a frozen spec — mermaid exists to prove the model is consumable. Run the mermaid/visualize suite; if a golden changes, investigate: accidental regression → fix; a justified consequence of the model's correct shape → regenerate the golden. `make check` clean.

### Model purity (grep-checkable)

- GraphModel fields contain no mermaid syntax (`classDef` | `@{` | `:::` | `fill:` | `stroke:`).
- `build_graph` emits zero rendering syntax.
- `render_mermaid` reads no IR fields directly.

### Sufficiency / completeness (the real acceptance bar)

A throwaway `render_react_flow(graph) -> {nodes, edges, groups}` (discarded, not committed) must reconstruct the full structure — with **no information loss** — of:

- the six workflow patterns in `src/pflow/guide/features/patterns.md` (classify-and-act, fan-out-and-synthesize, adversarial-verification, generate-and-filter, tournament, loop-until-done), and
- the Task 163 harness (`examples/agent-orchestration/plan-to-code/`).

"No information loss" = every node, every edge kind, every Container (including loops), and a reachable source back-ref per node. Anything the sketch can't draw that the IR knows = the model dropped a fact → fix the model.

### Testability

- `build_graph` is tested through its interface (assertions on the GraphModel), no mocks — `resolve_child` via a test adapter.
- Structural assertions live at the model level; the golden tests verify only the mermaid renderer.

## Dependencies

- **Option X** (landed — `b3bad44a`; `_scope.py` exists): `Scope` + unified ref resolution; `_RESERVED_PARAMS` / `_SOURCE_NODE_FIELD_RE` gone. 155 reuses `Scope` as graph-construction state.
- **ADR-0001** (loop = engine re-entry / node property), **ADR-0003** (structural node identity), **ADR-0004** (primitive-only model).
- Prerequisite for the (unfiled) **web-UI task**, which needs the Graph model (structure) + the runtime event log (live overlay).

## References

- **Domain vocabulary**: `context/CONTEXT.md` (Graph model, IR, Container).
- **Decisions**: `context/adr/0001-445-loop-engine-reentry.md`, `0003-155-graphmodel-node-identity.md`, `0004-155-graphmodel-primitive-only.md`.
- **Session context**: `scratchpads/handoff-see-control-storage/session-progress-log.md`; `.taskmaster/tasks/task_155/starting-context/` braindumps (static-substrate-for-visual-ui; loop-rendering-and-155-implications). The four pre-implementation verification passes (routing-map separability, ID alignment, IR inventory, container/blast-radius) are captured in the session thread.
- **Historical (not scope)**: GH #283 / #263 — fixed by Option X, preserved through the split. Prior task-reviews 145 / 146 / 153 for the visualizer's evolution and its load-bearing invariants.
