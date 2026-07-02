# Workflow Graph Package

Renderer-agnostic workflow structure for Task 155. This package is the static
"see" substrate: it carries nodes, edges, containers, loop/batch metadata,
authored params, and source pointers. It must not carry runtime status, outputs,
timings, or render syntax (Mermaid / React Flow / ELK layout) — that purity is
mechanized by `tests/test_core/test_graph_model_purity.py`. The `approval:` gate
field (Task 125) is deliberately NOT surfaced on GraphNode — the visual gate
marker is deferred to the Task 155/176 web-approval work; its absence is a
decision, not a miss.

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
- `is_decision()` counts OUTCOMES, not just branch labels: BRANCH labels plus the
  reserved "end" route when an END edge exists (a dynamic `next="end"` arm becomes
  an END edge, never a BRANCH — so a continue-or-stop gate like `if ok: next="end"
  else: next="fix"` IS a decision). No branch labels at all (a static `- next: end`)
  stays a non-decision. Changed 2026-06-10; the old ≥2-branch-labels rule missed
  every loop gate in the corpus (4 of 6 real deciders).
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

`scope.py` contains three extractor views over ONE shared walk (they cannot
drift): `refs_with_path_in` → `(root, first_segment, remaining_segments)` —
the path-preserving form (`${a.b.c.d}` → `("a", "b", ("c", "d"))`); `refs_in`
and `source_refs_in` are the legacy `(root, field)` truncations of it and stay
byte-identical (readability aliases of each other, not distinct extractors).
Mermaid-ID-dependent `Scope.resolve()` was not moved; build performs structural
resolution to `NodeId` plus optional output field.

`build_graph()` assumes **pre-validated IR**. It is not a validation layer: the
`WorkflowValidator` pipeline is the enforcement point, and the only production
caller (`pflow mermaid`) runs that pipeline (`--validate-only` checks) before
building. So semantically-invalid combinations the validator rejects upstream —
e.g. a node with both `loop:` and `batch:` (rejected at `data_flow.py`) — never
reach `build_graph` via the CLI. Where such a node would still be constructed if
fed unvalidated IR directly, the model carries both specs faithfully and the
Mermaid renderer prioritizes the batch (the loop badge is not drawn for a batch
node); do not add a hard assert that would crash `mermaid` on in-progress work.

Literal-batch sub-workflow items that cannot expand (resolver `None`/raise/empty,
depth limit, `${...}` dynamic path, or recursion-stack cycle) are recorded on the
batch `Container.annotations["unexpanded_items"] = {index: reason}`, mirroring the
`Node.unexpanded` discriminator on the regular/dynamic expansion paths. This keeps
a failed sub-workflow item distinguishable from a genuine leaf item (the "no
information loss" bar) even though Mermaid renders both as a leaf box.

**Every `${ref}` the language enforces as a dependency is one DATA_FLOW edge**
(2026-06-13, the unified-edge consolidation). ONE general-purpose emitter —
`_add_ref_edges`, full-equality dedup, `_resolve_ref`'s inputs-first resolution —
serves plain params (any depth: dicts AND lists, validator parity), `inputs:`
bindings, batch `items:`, the templated loop cap, and `## Cache` chunks. A node
reading the same input in two params gets TWO edges (distinct `input_name`s) —
the old `(source, target)` pair-dedup is gone. `_params_strings`' `shallow` flag
keeps a deep dict ref from claiming a same-named child-input port (it attaches
host-level). Deliberately still edge-less: loop `while`/`until`/`carry` refs
(recorded Task 155 decision), refs inside literal `batch.items` VALUES (the
validator doesn't enforce them), escaped `$${x}`, and operands failing the
runtime grammar (`${ a.x }` — scope.py gates on `_VAR_NAME_PATTERN` fullmatch;
bracket refs like `${data[0].x}` keep a root-only edge, role-lossy not absent).

**`_connect_source_expression` (output `source:`) stays a SEPARATE emitter** —
its no-dedup is load-bearing: two sub-key refs in one output `source:` must keep
both edges (react_flow re-keys on `output_path` there).

**Cache edges** (`_add_cache_edges`): a node's `prompt_cache: [chunk]` draws one
edge from each chunk var's producer, `input_name="prompt_cache"` (a reserved
name — no param row exists). The chunk's ref is FORBIDDEN in the consumer's
prompt body, so this edge is the dependency's only visibility. Per-file scoping
(`## Cache` never crosses sub-workflow levels); one ref per chunk by
construction; a cache edge COUNTS AS A READ of the producer's field (intended —
the field genuinely is read through the cached prefix). The same pass assembles
`Node.cached_prefix` — the consumer's cached system prefix as authored TEMPLATE
text (`prose_before + ${var}` per consumed chunk, declaration order — the
runtime's assembly rule, core/prompt_cache.py `build_cache_system_blocks`).
`render_mermaid` ignores it; the React Flow contract ships it for the panel's
"what will the prompt look like" view.

Residual role lossiness is now ONLY the same-param sub-key collapse:
`Edge.output_path` (the ref's sub-path below `output_field`: `${gen.result.ok}`
→ `("ok",)`) is declared `compare=False` — **load-bearing, do not "fix"**: edge
dedup is full dataclass equality, so putting the path in identity would turn two
same-`input_name` sub-key refs into two edges and change Mermaid's edge count
(goldens break). The first ref's path wins under dedup; the web's param-text
scan recovers the lost reads. Only `_add_ref_edges` and
`_connect_source_expression` set it, behind two guards: never through the batch
alias, and only when the resolved `output_field` equals the ref's first segment.

Consequences a reader must expect (all BY-DESIGN, 2026-06-13): input-rooted
bindings on literal-batch hosts land per-item (the host-level fallback died); a
workflow input literally named `item`/`__iteration__` draws no plain-param edges
(`_resolve_ref` reserves those roots); `is_terminal`/`shadowed` flips caused by
a new edge are correct drift, not bugs (a node gaining a data out-edge stops
being terminal). Mermaid dedups identical rendered arrow LINES per diagram
(presentation only — the model keeps every edge) and its literal-batch
fork-coverage suppression excludes input-kind sources (input fan-in must never
delete an execution-order arrow).

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
