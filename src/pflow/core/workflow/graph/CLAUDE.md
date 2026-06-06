# Workflow Graph Package

Renderer-agnostic workflow structure for Task 155. This package is the static
"see" substrate: it carries nodes, edges, containers, loop/batch metadata, and
source pointers. It must not carry runtime status, outputs, timings, or Mermaid
syntax.

## File Map

```
graph/
├── __init__.py          # Public graph API exports
├── model.py             # Dataclasses + derived helpers/invariant checks
├── scope.py             # Pure template ref extraction helpers
├── build.py             # The only IR walk: IR -> GraphModel
└── renderers/
    ├── __init__.py      # Renderer exports
    └── mermaid.py       # GraphModel -> Mermaid syntax
```

Renderers consume `GraphModel`; they do not read IR. The legacy
`workflow/mermaid` package is only a compatibility shim that calls
`build_graph()` and `render_mermaid()`.

## Load-Bearing Invariants

- `NodeId(node_id, ancestor_path)` is structural identity. Renderers derive flat
  IDs such as Mermaid's `parent__child`; the model never stores them.
- Literal batch sub-workflow items use `AncestorStep(host, batch_index)`.
  Dynamic batches use `AncestorStep(host, None)`. Leaf batch items are
  `BatchSpec.items` data, not nodes.
- Loops are `Node.loop` metadata. They are not edges; runtime loop visits are an
  N:1 overlay onto the same static node.
- `EdgeKind.END` is a graph edge to a synthetic per-level `__end__` node, sourced
  from parser metadata `_routes_to_end`. Mermaid parity renderers should still
  derive their visual end sink from `GraphModel.is_terminal()`, not from raw
  outgoing edge presence.
- `GraphModel.is_decision()`, `is_terminal()`, and `shadowed()` are derived
  views. Do not store duplicate decision/terminal/suppression flags.
- `shadowed()` is a model-level view of structural-edge suppression. A
  structural edge is shadowed only by data-flow edges from the same structural
  source; top-level workflow input edges do not replace execution-order edges
  from another source.
- `Node.parent` and `Container.members` are intentionally bidirectional because
  React Flow wants parent pointers while renderers also walk container members.
  `GraphModel.__post_init__` enforces consistency plus edge endpoint integrity.
- `Node.source` is a click-to-read pointer, not embedded source content.
  File-loaded callers should pass `source_file` to `build_graph()` for the root
  workflow; expanded child workflow nodes get their file path from
  `SubWorkflowResult.path`.

## Runtime Overlay Join Contract

The static identity mirrors today's runtime shape without importing trace code:
top-level/sub-workflow child events use bare node ids nested under their parent
events; batch items are keyed by integer index; IO nodes and the synthetic END
node have no runtime node events. Future JSONL/span trace work should join onto
this identity rather than changing the graph model.

## Build Notes

`build_graph()` is a two-sub-pass level walk. First create all nodes,
containers, child input maps, and output maps; then resolve structural and
data-flow edges. This avoids the legacy Mermaid resolver's partial-read
ordering trap.

`scope.py` intentionally only contains `refs_in` and `source_refs_in`.
Mermaid-ID-dependent `Scope.resolve()` was not moved; build performs structural
resolution to `NodeId` plus optional output field.

## Renderer Notes

`renderers/mermaid.py` owns Mermaid-only concerns: flat IDs, shapes, classDefs,
labels, batch ellipsis/dots, visual end sinks, and subgraph styling. It may use
private helpers internally, but callers should use `render_mermaid()` or the
compatibility `generate_mermaid()` shim.
