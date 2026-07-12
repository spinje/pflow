# Graph transform (`web/src/graph/`)

The PURE `RFGraph` (Python wire contract) → React Flow transform. **No React** — plain
functions, so tests run node-env (fast, no jsdom). Keep hooks/components out of here.

> Read `web/CLAUDE.md` (web root) FIRST — the cross-cutting invariants every file here
> obeys (the handle/edge contract, edges-are-additive, density-governs-edges,
> build-vs-focus, geometry-single-sourced) live there and are NOT restated here. The
> contract this transforms is Python-defined
> (`src/pflow/core/workflow/graph/renderers/react_flow.py`); `web/src/types.ts` mirrors it.

Dependency DAG (no runtime cycle): `scan → io → rows → focus/flow`. `flow.ts` is the
package FAÇADE — re-exports the siblings, so consumers `import … from "../graph/flow"`;
rows/focus take flow's types TYPE-only.

**Files:** `flow.ts` (buildFlow + the RF data types) · `scan.ts` (param-text read scan) ·
`io.ts` (IO ownership) · `rows.ts` (the leaf row model + sizing) · `focus.ts` (restyle +
expansion policy) · `layout.ts` (ELK) · `portSides.ts` (post-layout edge rails) · `spine.ts`
(chain straightening) · `collapse.ts` · `direction.ts` (auto-direction) · `remap.ts`
(reload remap) · `handles.ts` (handle-id scheme) · `metrics.ts` (geometry constants) ·
`sourceDecorate.ts` (source-pane decoration — consumed by `components/SourcePane`) ·
`testFixtures.ts` (shared fixture builders — non-`.test` name so vitest doesn't collect it).

## The leaf ROW MODEL (`rows.ts`)

`nodeRows` is the ONE source of truth for a leaf's body: a `NodeRow[]` list — left column
(`paramRowsFor`) → output rows (`outputRowsFor`) → the ↻ loop-rule rows (condition; cap
only when set) — each row CARRYING its own handle. It rides `LeafData.rows` and is the
SAME list consumed by `WorkflowNode` (one switch over `row.kind`), `leafSize` (body height
= `rows.length`), `rowAnchorsFor` (LR ELK row ports — every row advances y, only
handle-bearing rows emit an anchor; label/loop rows anchor nothing), and `sourceHandleFor`
(the output landing ladder via `rowsByNode`). Render/size/ports/handles therefore cannot
drift; adding a row kind touches `rows.ts` + one `WorkflowNode` JSX branch.

- **`paramRowsFor` (left column) — two specifics:** (1) **per-ref binding SUB-ROWS** — a
  param receiving ≥2 refs (interpolated prompt, dict of bindings) grows one nested `·` row
  per ref (label = the ref text rebuilt from the edge via `refText`, rendered as a ref-chip;
  a dict-key row prepends its key), each landing on its own `bindingRowHandle(input_name,
  ref)`; a single ref keeps landing on the param row (no sub-row noise on the common case).
  (2) **cache chunks** — the same mechanism under parent group `"prompt_cache"`, placed
  before `prompt` via `cacheInsertIndex` (request order: system → cached prefix → prompt):
  one chunk = a flat `cached prefix` row, several = a handle-less `cached prefix ×N` label
  row + nested rows; cache edges ALWAYS land on their chunk row (no param row exists, so
  without one they merge invisibly into the control trunk at `NODE_IN`).
- **`outputRowsFor` (right column) composition:** authored shape (`RFNode.output_shape` —
  its `field` names the port: result/response) ∪ observed reads (edge `output_field` +
  first `output_path` segment). A bare read or unknown keys → parent row + nested key rows
  (D2); no bare read + keys known → flat full-dotted-path rows, no parent (D3); `quiet` = no
  reading edge (D4 — grey dot, faint; no line can exist). A field-level row's type falls
  back to `graph.kind_output_types[kind]` (the registry's declared interface, injected at the
  server seam — types existing rows, never creates one; authored shapes win). A batched node
  ships NO `output_shape` (its real output is the aggregate, not the per-item field).
- **The landing rule lives in `targetHandleFor`/`sourceHandleFor`, reading the SAME
  `refRowsByNode` derivation `paramRowsFor` builds** — so rows and landings can't disagree.
  Output ladder, one level deep: sub-key ref → its exact key row (`o:result.ok`) → the
  field's parent row → `NODE_OUT`. Rows hidden (beautiful) → `NODE_IN`/`NODE_OUT` fallback.
- **Quiet stays truthful via `scanParamReads` (`scan.ts`)** — see the scan section.

## Reads scan (`scan.ts`)

The scope.py grammar MIRROR: which output fields the graph actually reads. `scanParamReads`
merges sibling param-text `${ref}` reads into the observed set so a quiet output row means
"no reader at ALL", not "no edge" — scope-aware (same-parent `node_id` only),
batch-alias-skipping, grammar-gated (escaped `$${x}` and spaced operands are never reads).
It NEVER creates a field row or a line (no edge + no shape → no row; lines come only from
edges). Build-time dedup still collapses two same-param sub-key refs (`Edge.output_path` is
`compare=False`), and the scan recovers those lost reads. `consumedReadPaths`/`producedTypeOf`
feed the panels (components/). Residual: refs outside params (loop conditions) are not scanned.

## Edge routing (`flow.ts` lanes + `portSides.ts` rails)

This folder decides WHERE lines go; `components/edges/` draws them (path/stroke/gradient).
- **Lanes** (`assignEdgeLanes`, flow.ts): each parallel binding/branch/error edge at a node
  gets a distinct stub + mid-rail offset so bundles fan apart instead of overlapping
  pixel-exactly. Sequential edges are exempt (one out per node).
- **Rails** (post-layout, `portSides.ts`, computed from final boxes): `assignDataRails`
  centers a wrap-around's middle segment in the clear gap between endpoint boxes (never
  hugging a border); `assignBackRails` routes a BACKWARD branch/error edge (loop-back to an
  earlier node) past both boxes (LR below / TD left), lane-staggered — smoothstep's stock
  wrap U-turns at the source stub and knots siblings; `assignLoopRails` gives a synthesized
  loop edge its wrap rail (TD right / LR above) — LOAD-BEARING, since a self-loop's endpoints
  share an axis and the default midpoint runs the line back THROUGH the node. Sequential
  edges are deliberately untouched (their backward cycle already renders clean).
- **Fork layout** (`orderForkSiblings`, layout.ts): fork targets lay out in the code's chain
  order (first `if` leftmost; Steps order is irrelevant). Branch CONDITIONS are the
  contract's fail-closed AST extraction (Python); this folder only carries `condition`/
  `outcome`/`decisionEnd` on `EdgeData` and decides anchor PLACEMENT data — the pill render
  is `components/edges`. A decision's END edge is its reserved `"end"` OUTCOME (buildFlow
  appends `"end"` last to `branchLabels`); a non-decision's static `- next: end` is untouched.
- **Synthesized edges** (not in the contract): `loop:` self-loops (from `LoopSpec`, anchored
  to the node or its group) and `io-flow:` control edges (Inputs card → entry step; control
  SINK → Outputs card). SINK-ness is derived from contract sequential/branch edges, NOT
  `is_terminal` (that counts DATA_FLOW out-edges, so a final leaf feeding a declared output
  reads non-terminal and the Outputs card would float). LAST-root-step fallback on a cycle.
- **Additivity** (the root invariant) is `renderAnchor` (flow.ts): any contract node id → its
  on-canvas representative (itself / its group / the outermost collapsed ancestor), so a hidden
  or suppressed endpoint degrades to a node/group-level connection, never drops.
- *Interacts with:* `components/edges/` (GradientEdge/DataEdge/LoopEdge consume these hints);
  `hooks/` reveals default-hidden data edges on focus.

## Layout (`layout.ts`)

ELK over nested/compound containers (the only async step; lazy elkjs chunk, run in a web
worker via the hooks watchdog). ELK is told where the handles are, because it aligns box
CENTERS while handles render off-center:
- **TD:** leaf nodes (and io/group cards) declare `FIXED_POS` ports at `ICON_COL_X`; the
  trunk + forks flow through the icon column. **LR:** control handles sit on `ICON_ROW_Y`
  (in left / out right, same height → trunk passes straight THROUGH the node); every visible
  param/output/branch/IO row also declares a fixed port at its `(side, y)` from
  `rowAnchorsFor`, so spine-aligned card pairs get straight binding bundles.
- **Straightness priorities are WEIGHTS, not constraints:** the control trunk carries 100
  (a binding bundle at 5 each out-voted the old 10), row-to-row bindings 5 — the spine wins.
  Each target's first non-error in-edge keeps the straight trunk; error-only targets order
  LAST among siblings via `forceNodeModelOrder`.
- **Auto-direction** (`direction.ts`): with no explicit `direction=`, `autoDirection(graph)`
  returns LR under `DENSE_NODE_FLOOR` (16) nodes, else TD once `data_flow` edges per node
  reach `DENSE_DATA_PER_NODE` (1.4). Data-edge DENSITY — not loops, not raw size — is the
  measured predictor of "edges drawn THROUGH unrelated boxes". `GraphView` applies it
  one-shot-per-workflow (frozen ref, pre-paint), bypassed by `direction=`/toolbar.
- **`alignSpine`** (`spine.ts`, run at the END of `layoutGraph` so cache/anchoring/animation
  see aligned positions): expanded regions carry NO ELK port, so ELK center-anchors their
  trunk and the error COMPOUNDS down the chain (the "staircase"). It re-aligns each PURE
  sequential chain's control anchors to its HEAD's; forks/merges/multi-terminal sinks break
  the chain, error edges count toward neither side; a shift that would crowd a same-scope
  sibling (`SPINE_CLEARANCE`) is SKIPPED.
- **`compactScopes`** (TD only, after `alignSpine`): the same missing region port makes a
  wide region open with half its width of dead space on the left; this shifts each region's
  body (DEEPEST first) to `regionPadLeft` and shrinks it to content + `REGION_RIGHT` (derived
  `REGION_LEFT + IO_BODY_GAP` so an inputs region's margins are symmetric).
- **elkjs crashes (both pinned by layout tests):** a fixed port on a COMPOUND node crashes
  elkjs under `INCLUDE_CHILDREN` when an edge references it ("NEdge must have a source and
  target NNode") — so expanded regions get NO ELK port (smoothstep absorbs the offset); and
  every `considerModelOrder.strategy` value crashes on a cross-hierarchy edge —
  `crossingMinimization.forceNodeModelOrder` is the only survivor.
- **Nested IO region padding (`groupPadding`):** an expanded sub-workflow's inputs SIDEBAR is
  reserved as ELK LEFT padding (the body's first layer lays out beside it) and the outputs
  strip as bottom padding, plus `nodeSize.minimum` so a tall sidebar can't overflow a short
  body. GOTCHA (measured, test-pinned): under direction DOWN elkjs applies `nodeSize.minimum`
  TRANSPOSED — pass `(minH, minW)` in TD (unswapped in LR).

## IO ownership (`io.ts`)

The single copies of the IO/suppression rules (`components/` renders from these, never
re-derives): `wrapperPorts` (a wrapper group's ports — the SAME source the canvas rows and
the IoPanel render from; an undeclared output's type is derived fail-closed from its single
producer via `producedTypeOf`), `ioOwners` (wrapper→owner + port→owner maps), and
`shellBatchIds` — the ONE definition of a decorator-SHELL batch group that never renders.
Batch is presentationally a MODIFIER, not a box to travel through: a DYNAMIC batch group is
always a shell (the workflow group reparents past it via `effectiveParent` and becomes the
host's representative); a batched LEAF renders as a normal node; the EXCEPTION is a LITERAL
batch whose items expanded into real item groups — it keeps its container. The discriminator
is literal-vs-dynamic + child groups, NEVER memberlessness (a batch group never has direct
node members, so the old `members.length === 0` rule swallowed literal batches whole and
shattered the spine — CRITICAL). `collapse.ts` and `viewParams.resolveEndpointFlatId` both
consume `shellBatchIds`.

IO ports render as ROWS on the workflow's own node (root → an IO card; nested → the workflow
group), never a floating table. Rows are STRICT-sided (receive LEFT, feed RIGHT — never
flipped post-layout); both handles always render (a named-but-missing handle silently drops
the edge), the role-less side hidden. *Interacts with:* `components/nodes/PortRows` +
`IOCardNode` render these; `io-flow:` skeleton edges (edge-routing section) join the cards
to the control spine.

## Focus + expansion policy (`focus.ts`)

`applyFocus` is a cheap restyle (dim/reveal/select), NO re-layout — it returns NEW arrays so
React re-renders. Focusing a node reveals its incident default-hidden data edges (no density
flag — only `buildFlow` sets the default). A GROUP focus selects the whole UNIT (the group +
its `parentId`-BFS descendants + every edge touching any of them). The edge-select arm lights
only the clicked connection (its endpoints stay full-strength) and owns the `zIndex`
elevation channel. `expandTargets` is the beautiful-mode expansion policy: the focused node +
its data-flow endpoints (and, for a container focus, all its IO ports) expand to the full
body; the open panel's subject pins its OWN card. `NO_EXPANSION` is the shared empty-set
constant — a fresh empty Set per call would change object identity and force a needless
build+ELK re-run.
`applyReplayDim` (Task 176) is the third pure restyle beside applyFocus/applyStatus: on a
pinned TERMINAL replay it greys status-less nodes (`.node.unrun`, 0.45 — focus-dim 0.18 wins by
CSS order, pinned in cssOrder.test.ts) and edges with an un-run endpoint (`edge-unrun`, appended
beside applyFocus's classes); join rule mirrors applyStatus (leaves by ref, hosts by primary
group), expanded regions carry the fact for edges but never the class (children dim — opacity
would compound), identity-stable + idempotent, and inactive is a pass-through so live runs pay
nothing. `rowTouches` resolves which canvas subjects a hovered row marks. Every flow edge carries its
ORIGINAL contract endpoints (`data.from`/`data.to`), so a focus reveals a SINGLE port's lines
even though the edge re-anchors onto the port's OWNER. *Interacts with:* `hooks/`
runs the re-layout + camera anchor when expansion changes node sizes; `components/` renders
the dim/reveal/select styling.

## Lossless invariant (`lossless.test.ts`)

`expectLossless(graph, view)`: the production "dropped edge — no on-canvas anchor" warn
becomes a test FAILURE; every non-IO contract node has an on-canvas representative; every
contract edge's connectivity survives (some flow edge of the same kind connects a
representative of its source to one of its target). Swept over a synthetic structural matrix
AND the committed real contracts (`web/src/test/fixtures/contracts/`), drift-guarded by a
Python test. Representatives derive THROUGH the production seams (`ioOwners`, `shellBatchIds`),
never a re-implementation — so a single-copy mutation can't cancel out.

## Collapse / direction / remap policy

`collapse.ts`: `collapsibleGroupIds` (workflow/batch only, excludes shells) + `initialCollapsed`
(over `AUTO_COLLAPSE_NODE_BUDGET` (60) opens fully collapsed; `collapse=all|none` overrides; a
`node=`/`focus=` target keeps its ancestor chain expanded — an edge target protects BOTH
endpoints' chains). `remap.ts`: flat ids (`n{i}`/`g{j}`) are POSITIONAL (renderer `enumerate`),
so a structural edit renumbers them — `remap` re-points preserved selection/focus/collapse
through the STABLE structural ref (`node_id` + `ancestor_path` + `port`, the contract's overlay
join key). Consumed by the hooks reload path in a pre-paint `useLayoutEffect`.

## Handle-id scheme (`handles.ts`)

Each id encodes a fixed type; `handleType` is the authority (throws on unknown). Builders:
`NODE_IN`/`NODE_OUT`, `branchHandle(label)`, `bindingRowHandle(input_name, ref)`,
`portHandle`/`portTargetHandle` (IO rows), `LOOP_ROW`. The handle/edge contract (a handle must
exist + be the right type or RF silently drops the edge) and its pure `flow.test` guard are in
the web root — this folder just owns the id namespace.
