# Workflow Graph Package

Renderer-agnostic workflow structure for Task 155. This package is the static
"see" substrate: it carries nodes, edges, containers, loop/batch metadata,
authored params, and source pointers. It must not carry runtime status, outputs,
timings, or render syntax (Mermaid / React Flow / ELK layout) — that purity is
mechanized by `tests/test_core/test_graph_model_purity.py`.

## File Map

```
graph/
├── __init__.py          # Public graph API exports
├── model.py             # Dataclasses + derived helpers/invariant checks
├── scope.py             # Pure template ref extraction helpers
├── build.py             # The only IR walk: IR -> GraphModel
└── renderers/
    ├── __init__.py      # Renderer exports
    ├── mermaid.py       # GraphModel -> Mermaid syntax
    └── react_flow.py    # GraphModel -> React Flow JSON contract (Task 168)
```

Renderers consume `GraphModel`; they do not read IR. The legacy
`workflow/mermaid` package is only a compatibility shim that calls
`build_graph()` and `render_mermaid()`.

## Load-Bearing Invariants

- `NodeId(node_id, ancestor_path, port)` is structural identity. `ancestor_path`
  is real host descents only. `port ∈ {in, out, None}` disambiguates synthetic
  IO-wrapper nodes that may share a name with each other or a body node at the
  same level — the role is `port`, never a synthetic ancestor step. Body nodes
  carry `port=None`. Renderers derive flat IDs such as Mermaid's `parent__child`
  (and `in_`/`out_` prefixes from `Node.kind`); the model never stores them.
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
- `Node.params` carries authored param **values** inline (small literals through
  full prompts/code) — the model's one complete static read-model, for the React
  Flow renderer's click-to-read. `build.py` fills it with a non-dict guard
  (unvalidated IR may carry `params: None`/str/list → `{}`). `render_mermaid`
  ignores it, so Mermaid goldens are unaffected by its presence.

## Runtime Overlay Join Contract

The static identity mirrors today's runtime shape without importing trace code:
top-level/sub-workflow child events use bare node ids nested under their parent
events; batch items are keyed by integer index; IO nodes and the synthetic END
node have no runtime node events. Future JSONL/span trace work should join onto
this identity rather than changing the graph model. The join keys on body-node
identity `(node_id, ancestor_path)` — and body nodes always have `port=None` —
so `NodeId.port` (set only on the never-traced IO nodes) is invisible to the join.

## Build Notes

`build_graph()` is a two-sub-pass level walk. First create all nodes,
containers, child input maps, and output maps; then resolve structural and
data-flow edges. This avoids the legacy Mermaid resolver's partial-read
ordering trap.

`scope.py` intentionally only contains `refs_in` and `source_refs_in`.
Mermaid-ID-dependent `Scope.resolve()` was not moved; build performs structural
resolution to `NodeId` plus optional output field. `refs_in` is a readability
alias of `source_refs_in` (identical behavior) — not two distinct extractors.

`build_graph()` assumes **pre-validated IR**. It is not a validation layer: the
`WorkflowValidator` pipeline is the enforcement point, and the only production
caller (`pflow visualize`) runs that pipeline (`--validate-only` checks) before
building. So semantically-invalid combinations the validator rejects upstream —
e.g. a node with both `loop:` and `batch:` (rejected at `data_flow.py`) — never
reach `build_graph` via the CLI. Where such a node would still be constructed if
fed unvalidated IR directly, the model carries both specs faithfully and the
Mermaid renderer prioritizes the batch (the loop badge is not drawn for a batch
node); do not add a hard assert that would crash `visualize` on in-progress work.

Literal-batch sub-workflow items that cannot expand (resolver `None`/raise/empty,
depth limit, `${...}` dynamic path, or recursion-stack cycle) are recorded on the
batch `Container.annotations["unexpanded_items"] = {index: reason}`, mirroring the
`Node.unexpanded` discriminator on the regular/dynamic expansion paths. This keeps
a failed sub-workflow item distinguishable from a genuine leaf item (the "no
information loss" bar) even though Mermaid renders both as a leaf box.

A `DATA_FLOW` edge's `input_name`/`output_field` attributes are **best-effort**:
when one source feeds a target through multiple roles (e.g. a `params.inputs`
binding *and* `loop.max_iterations`), the `(source, target)` dedup keeps a single
edge and only the first role's `input_name` survives. The structural dependency is
always preserved; only the role label is lossy in that rare multi-role case.

## Renderer Notes

`renderers/mermaid.py` owns Mermaid-only concerns: flat IDs, shapes, classDefs,
labels, batch ellipsis/dots, visual end sinks, and subgraph styling. It may use
private helpers internally, but callers should use `render_mermaid()` or the
compatibility `generate_mermaid()` shim.

`renderers/react_flow.py` (Task 168) is the second renderer: `GraphModel ->
RFGraph`, a typed React-Flow-native JSON contract that `asdict` + `json.dumps`
round-trips. It mints flat ids **injectively** from the unique `NodeId`
(`n{i}`/`g{j}`) rather than reusing Mermaid's collision-patched scheme — the two
renderers deliberately share no helpers. It bakes the derived predicates as facts
and emits the model's **general** `shadowed()` fact; the frontend picks its own
visual policy, so do **not** copy Mermaid's narrower render-time shadowing here.
Representative batch-item truncation lives in this renderer. The wire contract the
frontend consumes is documented in `src/pflow/ui/CLAUDE.md`; the import-purity
guard is enforced by the purity test cited in the intro.
