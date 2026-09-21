# Workflow Graph Package

Renderer-agnostic static workflow structure. There is **no render syntax in the
model**: `model.py`/`build.py` must not acquire Mermaid/React Flow layout, runtime
status, timings, outputs, or gate state. The boundary is enforced by
`tests/test_core/test_graph_model_purity.py`.

## Task Navigation

| Task | Owner |
|---|---|
| Change identity, invariants, or derived graph predicates | `model.py::GraphModel`, `NodeId`, `Edge` |
| Change IR expansion, sub-workflow/batch structure, or dependency edges | `build.py::build_graph`, `_GraphBuilder` |
| Change template-reference extraction | `scope.py` |
| Change Mermaid presentation | `renderers/mermaid.py::render_mermaid` |
| Change React Flow contract, IDs, or batch-item truncation | `renderers/react_flow.py::render_react_flow` |
| Change workflow-reference resolution/validation for UI | `src/pflow/execution/graph_service.py::resolve_validate_build` |
| Change legacy Mermaid entry point | `../mermaid/CLAUDE.md` |

Renderers consume `GraphModel`; neither should become a second IR walker.
`build_graph()` is not a validator. Production callers validate through
`execution/graph_service.py` or `cli/commands/mermaid.py`; arbitrary direct callers
do not inherit that guarantee.

## Identity and derived structure

- `NodeId(node_id, ancestor_path, port)` is structural identity. Ancestors record
  real host descents only; IO-wrapper roles use `port`, not invented ancestor
  steps. Body nodes have `port=None`. Flat display IDs belong to renderers.
- Literal batch sub-workflows use `AncestorStep(host, batch_index)`; dynamic ones
  use a None index. Leaf batch items are data, not separate graph nodes.
- Loops are metadata on a static node; repeated runtime visits overlay that same
  node. Do not turn loop visits into static edges/nodes.
- Decision, terminal, and shadowing state are derived by `GraphModel`. A branch
  plus reserved END route is a decision; a static END route alone is not.
  Mermaid end sinks use `is_terminal()`, not raw outgoing-edge presence.
- Parent pointers and container membership intentionally coexist for different
  consumers. `GraphModel.__post_init__` enforces their consistency.
- Pass `source_file` for file-loaded root workflows; expanded children use
  `SubWorkflowResult.path`. Source pointers support click-to-read, while authored
  params and cached-prefix text remain static content in the model.

## Runtime Overlay Join Contract

Join body-node identity `(node_id, ancestor_path)` to runtime events. IO/END nodes
have no runtime event; their `port` role is not part of the body-node join.
In the reconstructed trace tree, child events nest under hosts and batch items
use integer indices. That read-model structure is distinct from JSONL storage;
trace-format changes must not redefine static identity.

## Dependency-edge limits

`build.py::_add_ref_edges` is the shared dependency emitter. Scope extraction must
match runtime grammar and skip escaped templates. Loop condition/carry references
and references inside literal batch-item values are deliberately edge-less; do not
assume every visible template has a DATA_FLOW edge.

`_connect_source_expression` handles output `source:` separately and preserves
multiple sub-key edges. General edge equality instead excludes `Edge.output_path`:
two same-param sub-key reads collapse, keeping the first path. This is intentional
Mermaid edge-count compatibility, not an optimization to remove. The frontend's
authored-param scan recovers lost read roles (`web/src/graph/scan.ts`,
`web/src/graph/flow.ts`).

Cache dependencies belong in `_add_cache_edges`: consumed chunk refs may not
appear in the prompt body, so these edges are their only dependency visibility.
Chunk scope is per workflow file; the cached prefix follows the same authored
assembly rule as `core/prompt_cache.py::build_cache_system_blocks`.

Failed literal-batch child expansion is recorded in
`Container.annotations["unexpanded_items"]`, analogous to `Node.unexpanded`.
Preserve that distinction from a genuine leaf even if a renderer draws them alike.

## Renderer boundaries

`renderers/mermaid.py` owns shapes, labels, flat IDs, visual end sinks, and
presentation-only edge suppression. `renderers/react_flow.py` emits the general
model `shadowed()` fact so the frontend can choose its own visual policy; do not
copy Mermaid's narrower render-time policy into that contract. Structural
shadowing must not let workflow-input fan-in erase execution-order edges from a
different source.

Tests: `tests/test_core/test_graph_build.py` for structure,
`test_graph_model_purity.py` for boundaries, and
`test_graph_mermaid_renderer.py`/`test_mermaid.py` plus goldens for Mermaid.
