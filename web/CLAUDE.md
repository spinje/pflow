# pflow Web UI frontend (`web/`)

Browser SPA for `pflow ui`: **Vite + React 18 + React Flow v12 (`@xyflow/react`) +
ELK (`elkjs`)**. It fetches the typed JSON contract the Python server emits and
draws an interactive workflow canvas. Build output → `../src/pflow/ui/static/`.

The contract is defined in Python (`../src/pflow/core/workflow/graph/renderers/
react_flow.py`) and the rendering rules the transform must honor are documented in
`../src/pflow/ui/CLAUDE.md`. `src/types.ts` hand-mirrors the contract — **read
those two before changing `graph/`.**

## Where things live (and where new code goes)

Each folder is one role; add code to the slot that matches it.

```
src/
  main.tsx           entry — <ErrorBoundary> wraps <App>
  App.tsx            shell: ?workflow= URL param → <GraphView>, else <CatalogView>
  index.css          all styles (one sheet; theme vars at :root — geometry vars are
                     INJECTED from graph/metrics.ts, never hardcoded here)
  types.ts           the wire contract (mirrors react_flow.py) — imported everywhere
  api/               server communication (client.ts: fetch + ApiError + fetchVersion,
                     the source-watch poll; a live /events subscription would go here)
  graph/             PURE contract → React Flow transform; NO React (tests run node-env).
                     flow.ts is the package FAÇADE (it re-exports the siblings, so
                     consumers import everything from "../graph/flow"); the DAG is
                     scan → io → rows → focus/flow (rows/focus take flow's types
                     TYPE-only — no runtime cycle)
    flow.ts          buildFlow (nodes/edges, edge construction + handle ladders) +
                     the RF data types (LeafData/GroupData/EdgeData/FlowNode/…)
    scan.ts          param-text read scanning (the scope.py grammar mirror):
                     scanParamReads, consumedReadPaths, producedTypeOf
    io.ts            IO ownership + suppression single-copies: ioOwners, wrapperPorts,
                     shellBatchIds, the Port row model
    rows.ts          the leaf ROW MODEL + sizing: nodeRows (the whole body as one
                     handle-carrying list), paramRowsFor, outputRowsFor, leafSize,
                     rowAnchorsFor, the size constants
    focus.ts         the restyle pass + expansion policy: applyFocus, expandTargets,
                     rowTouches, NO_EXPANSION
    layout.ts        ELK positioning (the only async step; lazy-loads elkjs as its own chunk)
    portSides.ts     post-layout edge decoration (data rails, loop rails, back rails)
    spine.ts         post-layout sequential-chain re-alignment (the SPINE bullet)
    collapse.ts      initial-collapse policy (auto-collapse budget, URL overrides)
    remap.ts         reload-time remap of preserved selection/focus/collapse through the
                     stable structural ref (flat ids are positional — a structural edit
                     renumbers them; see the live source auto-update bullet)
    handles.ts       handle-id scheme (each id encodes its source/target type)
    metrics.ts       layout-coupled geometry constants — the single source for rows.ts
                     sizes, the connector/edge geometry, and the :root CSS vars main.tsx
                     injects before first paint
    testFixtures.ts  shared fixture builders (node/group/edge + view consts) for the
                     graph tests — non-.test name so vitest doesn't collect it
    lossless.test.ts the no-information-loss invariant, swept over synthetic shapes +
                     real committed contracts (test/fixtures/contracts/)
  hooks/             useWorkflowGraph (fetch → build → layout → focus → RF state +
                     status; the in-place `reload` path + `reloadError` banner channel);
                     useCameraNavigation (view fits, node=/focus= deep links, chip
                     navigation + the paint-deferred follow); usePanelPair (the two side
                     panes' widths: clamp, persistence, symmetric re-clamp); useSourceWatch
                     (polls /api/version → fires the in-place reload on a source change)
  utils/             pure helpers — format.ts (${ref} parsing, value previews, kind
                     colors, category label); icons.ts (node-kind/provider → SVG URL);
                     viewParams.ts (URL params, deep-link id resolution, edge-click dispatch);
                     panelWidth.ts (pane width clamp + localStorage persistence — BOTH
                     side panes share the symmetric reserved-budget clamp);
                     sourceMap.ts (source↔canvas mapping: nodeAtLine, breadcrumbs)
  assets/icons/      vendored brand/tool SVGs (Vite bundles them into static/assets)
  views/             the screens App switches between (CatalogView, GraphView)
  components/        reusable UI: Toolbar, ReadPanel, EdgePanel, IoPanel, ErrorBoundary,
                     SourcePane (the left source view — see the Source pane bullet),
                     Chip.tsx (the shared node chip + ConnectionSections — see the chip bullet),
                     interaction.ts (the click-callback context + the hover-set channel),
                     PanelResizer (the side panel's drag handle — width rides the
                     --panel-w var GraphView sets on .graph-body; all three panels share
                     .read-panel so they follow for free; double-click resets),
                     nodes/, edges/
  test/              rf-jsdom.ts — React Flow jsdom mocks; fixtures/contracts/ — real
                     /api/graph payloads, drift-guarded by a Python test (regen command
                     in its failure message)
```

Tests sit beside their subject.

## Concepts that aren't obvious from the code

- **`graph/` has no React.** The transform is pure functions, so its tests run in
  node-env (no jsdom) and stay fast. Keep hooks/components out of it.
- **Build and focus are separate passes.** `buildFlow` produces the structural
  nodes/edges that ELK lays out; `applyFocus` is a cheap restyle (dim/reveal) with **no
  re-layout**. Collapse / density / direction re-run layout; clicking a node does not.
  `useWorkflowGraph` keeps the laid-out nodes and their edges as one snapshot so focus
  never restyles edges against stale node positions.
- **Live source auto-update — the canvas reloads in place as the `.pflow.md` is edited.**
  `useSourceWatch` polls `GET /api/version` (~1.5s, visibility-gated, in-flight-guarded)
  for a source-file fingerprint; on a CHANGE it triggers `useWorkflowGraph`'s `reload`
  path, which re-fetches `/api/graph` and rebuilds the canvas **in place** — a React
  reconcile, NOT `location.reload()` — preserving viewport, focus/selection, collapse, and
  the source pane (`prevWorkflowRef` distinguishes a workflow CHANGE = full reset from a
  same-workflow reload = in-place). A mid-edit **invalid** save returns `422`: the reload
  routes it to a SEPARATE `reloadError` channel (a non-blocking banner over the last-good
  canvas) instead of the full-screen `errors` view, and recovers on the next valid save.
  **The remap is load-bearing:** flat ids (`n{i}`/`g{j}`) are POSITIONAL (renderer
  `enumerate`), so a structural edit (insert/delete/reorder, not an append) renumbers them
  — `graph/remap.ts` re-points preserved selection/focus/collapse through the STABLE
  structural ref (`node_id` + `ancestor_path` + `port`, the contract's overlay join key)
  in a pre-paint `useLayoutEffect`, so focus FOLLOWS a node across an insert instead of
  jumping. On by default; `--no-watch` (→ `?watch=0`) freezes it. **Detection (the poll)
  is deliberately separable from reaction (the in-place rebuild):** Task 169's SSE can
  later replace the poll with a push that calls the same reaction trigger via the `api/`
  seam, nothing downstream changing.
- **An edge handle must exist on its node — and be the right TYPE — or React Flow
  silently drops the edge.** This is the recurring bug (it bit us twice). `flow.ts` only
  emits a per-row handle when a matching row exists, else falls back to `NODE_IN`/`NODE_OUT`.
  Each handle id encodes a fixed type via the scheme (`handleType` in `handles.ts`): a
  `sourceHandle` must resolve to "source", a `targetHandle` to "target". The
  HANDLE-TYPE INVARIANT test (`flow.test.ts`) enforces this — **jsdom CANNOT** (React
  Flow renders no edge DOM under jsdom, so any "no edge errors" assertion there is
  theater). Edge integrity is a pure `flow.ts` test, never a render test.
- **A leaf's BODY has ONE source of truth: `nodeRows` (graph/rows.ts, 2026-06-13 —
  the row-model generalization of the original `outputRowsFor` consolidation).**
  The `NodeRow[]` list it assembles — the left column (`paramRowsFor`: params in
  authored order, the cached-prefix group before `prompt`, per-ref sub-rows under
  a ≥2-ref param) → output rows (`outputRowsFor`) → the ↻ loop-rule rows
  (condition; cap only when set) — rides `LeafData.rows`, each row CARRYING its
  own handle, and is the SAME list consumed by `WorkflowNode` (one switch over
  `row.kind`), `leafSize` (body height = `rows.length`), `rowAnchorsFor` (LR ELK
  ports — every row advances the y counter; only handle-bearing rows emit an
  anchor: label/loop rows anchor nothing, the self-loop never enters ELK), and
  `sourceHandleFor` (the landing ladder via `rowsByNode`) — so render, size,
  ports and handles cannot drift; adding a row kind touches `rows.ts` + one JSX
  branch. `outputRowsFor` composition (TRANSFORM L2, 2026-06-10): authored shape
  (`RFNode.output_shape` — its `field` names the port: result/response) ∪
  observed reads (edge `output_field` + first `output_path` segment); a bare
  read or unknown keys → parent row + nested key rows (D2); no bare read + keys
  known → flat full-dotted-path rows, no parent (D3); `quiet` = no reading edge
  (D4 — grey dot, faint, no line can exist). A field-level row's type falls
  back to `graph.kind_output_types[kind]` (the registry's declared interface —
  types existing rows, never creates one; authored shapes win). The landing
  ladder, one level deeper than H6: sub-key ref → its exact key row
  (`o:result.ok`) → the field's parent row → `NODE_OUT`. Quiet is kept truthful
  by `scanParamReads` (graph/scan.ts): the scan merges sibling param-text reads
  into the observed set — scope-aware (same-parent node_id only),
  batch-alias-skipping, grammar-gated (mirrors scope.py: escaped `$${x}` and
  spaced operands are never reads), and it NEVER creates a new field row or a
  line (no edge + no shape → no row; lines come only from edges — D5). KEPT
  after the unified-edge model fix (2026-06-13, every authored `${ref}` now
  draws a contract edge): build-time dedup still collapses two same-param
  sub-key refs (`Edge.output_path` is compare=False) — the scan recovers those
  lost reads. Residual: refs outside params (loop conditions) are not scanned.
- **Edges are additive.** An endpoint hidden by collapse or a suppressed group-host
  re-anchors to a visible ancestor — never dropped. A missing anchor is a bug and
  `flow.ts` warns instead of dropping it.
- **One node component, two densities.** `WorkflowNode` is the single leaf component
  (React Flow node `type: "node"`); `density` rides in `data`. The card is colored **by
  type**: the kind color in the border + a faint kind-tinted bg — the same color the
  node's edges use (Option B keeps the tile/icon in the icon's **native** color, so the
  type color lives in the border). **Both** densities show the **category (type)** line
  + the **description** (`purpose`, or `node_id` when absent), which wraps to ≤2 lines;
  `node_id` (the `${ref}` key) is on the tooltip + in the read panel. *Advanced*
  (`detailed`) adds the body (param rows with per-row target handles + output ports).
  Fork outcomes show as labeled border handles in **LR** (both densities) or fan from the
  icon column in **TD** (see the control-edge note). Toggling density re-renders the one
  component (no node-type swap). Beautiful node height is a FIXED `HEADER_HEIGHT` —
  the tile dominates any 2-line description, so the tile stays vertically **centered**;
  advanced adds body rows. (The connector flare anchors to the TILE itself, so header
  growth no longer breaks it — but `leafSize` must stay in step with the DOM or ELK
  overlaps; a dev-only tripwire in `WorkflowNode` warns when detailed content overflows
  the pinned box.) Icons come
  from `utils/icons.ts`: one map keys a node `kind` →
  SVG; `llm` resolves from its `model` param's `provider/` prefix (default: a sparkle).
  Add a node-kind icon in that one file.
- **CONDITION is a presented pseudo-kind, not a contract kind.** A decision **code** node
  (`is_decision && kind === "code"` — `isCondition` in `utils/format.ts`) presents as
  label `CONDITION`, a fork icon (`assets/icons/condition.svg` — its in-file comment
  carries the baked-flip/evenodd-hole/gradient-stop geometry), and the condition orange
  (`#ffa657` == the CSS `--decision` var; keep them equal). `nodeColor(node)` is the single seam — card border, tile,
  category AND edge gradients all go through it; never call raw `kindColor(kind)` for a
  node's identity. Safe because multi-way routing (`next: str = ...`) is code-only, so
  the presentation hides no other kind; the kind gate is defensive. No decision badge
  (same reasoning as the deleted loop badge); the read panel shows `code · condition`
  so the canvas stays mappable to `type: code` in the file.
- **TRANSFORM is the second presented pseudo-kind (2026-06-10).** A pure-reshape **code**
  node (`is_transform && kind === "code"` — `isTransform` in `utils/format.ts`) presents
  as label `TRANSFORM`, the shuffle icon (`assets/icons/transform.svg`), and the
  transform cyan (`TRANSFORM_COLOR = #5fd4dd` — deliberately apart from
  the muted file/IO teals and shell green). UNLIKE is_decision the frontend CANNOT
  derive this fact — it needs the AST; Python classifies it FAIL-CLOSED
  (`_is_transform_code` in react_flow.py: provably pure reshape into `result`, no
  effects, no `next`). A pure decider sets `next` and is excluded by the classifier,
  so CONDITION/TRANSFORM never both claim a node (the isCondition-first order in
  `nodeColor`/`categoryLabel` is defensive). Read panel shows `code · transform`.
  Finer Tines-style sub-modes were considered + DEFERRED (intent inference breaks
  fail-closed) — rationale in the task-168 `visualization-requirements.md`; don't
  re-propose without it.
- **Density controls edges, not just node detail.** *Advanced* shows every edge.
  *Beautiful* shows only the control-flow skeleton: data-flow (`${ref}`) edges are built
  but `hidden`, and `applyFocus` reveals just the clicked node's data lines. Hidden
  data edges still go to ELK (only self-loops are excluded — layout.ts), so the layout
  reflects ALL structure in both densities; more model edges shift layouts everywhere —
  expected. `applyFocus` reveals any
  default-hidden edge incident to the focus, so it needs no density flag — only
  `buildFlow` sets the default.
- **Focus-expansion (beautiful): clicking a node expands it — and this is the ONE focus
  action that re-layouts.** The focused leaf + its data-flow endpoints (`expandTargets`)
  render their full advanced body in place (`LeafData.expanded`; `expanded` is a
  *flag*, not a density override). Handle resolution is per-ENDPOINT (`rowsVisible`):
  a revealed data line lands on the source's output row / target's param row wherever
  that row actually renders — and when BOTH ends land on rows the `stdout → data` edge
  label drops (the rows already name the fields, like advanced). Expansion changes node
  sizes, so it flows through build → ELK (decided 2026-06-09: a card growing along the
  TD flow axis would otherwise collide with the node below); `useWorkflowGraph` pans
  the viewport by the focused node's layout delta so the clicked node never moves on
  screen (camera anchoring — applied in the same effect that pushes the new positions).
  An expanded card keeps its TOP connector flare but drops the BOTTOM one (the body
  grew below the tile). In advanced the expansion set stays the stable EMPTY constant —
  focus there remains a pure restyle, no re-layout. Selection ring = `var(--kind)`.
  **Click performance + motion (all in `useWorkflowGraph`):** layouts are CACHED by
  `layoutKey` (density|direction|collapsed|expanded — focus itself is not
  layout-affecting), so un-click/re-click never re-run ELK; ELK itself runs in a WEB
  WORKER (`layout.ts loadElk`, main-thread bundled build as fallback — a browser
  fallback warns, never silent) guarded by a WATCHDOG (`layoutWithWatchdog`): a
  worker layout silent for 10s warns, re-runs on the main-thread build, and demotes
  the session to main-thread layouts — a silent worker (observed once, environmental,
  see the task-168 hang handoff doc) can stall one layout but never hang the canvas;
  the decoration effect paints ONLY a laid snapshot
  whose key matches the current state (stale-paint guard — without it every cached
  click "shakes": one frame of new-focus-on-old-layout). Small graphs
  (≤ `ANIMATE_MAX_NODES`) ANIMATE expansion re-layouts: positions interpolate
  through the RF store per frame so edge paths follow (a CSS transform transition
  detaches edges from gliding nodes — rejected, measured reasoning in the progress
  log); the anchoring pan eases in sync; only moved nodes change identity per frame;
  large flows snap; `prefers-reduced-motion` snaps.
- **Source pane = verbatim authored `.pflow.md`, one file at a time.** `GraphView`
  fetches `/api/source` beside `/api/graph` and caches both by workflow so line
  mapping is one consistent snapshot; opening/closing the pane never refetches.
  The server derives the file map from GraphModel nodes, not the rendered RFGraph
  (representative-batch truncation can hide child files). Multi-file workflows
  auto-switch with selection; breadcrumbs describe the invocation chain and resolve
  host contract ids through `resolveEndpointFlatId` at click time. Host/container
  selection lands in the parent file at the invoking `### step`; member selection
  lands in the child file. Line clicks use `nodeAtLine` (greatest authored
  `source.line <= clicked line`, ignoring null lines), then iterate candidates
  until one resolves to a rendered id; unresolved clicks still mark the local line.
  **No diff view belongs here**: this UI is comprehension-only, while the user's
  IDE/unstaged-diff staging loop is the approval surface. A ROOT io-card
  selection syncs to its `## Inputs`/`## Outputs` SECTION HEADING found in the
  root file's TEXT (`sectionHeadingLine`, fence-aware) — io selections carry no
  node and input ports no `SourceRef`, so the heading is the interface's
  authored home; reverse output-line clicks focus the Outputs wrapper through
  the IO-member resolution arm. Remaining v1 gap: individual `### input`
  declaration lines are unmappable (no `SourceRef` on input ports — a Python
  `_add_inputs` change would close it).
- **All edges are ROUNDED-ORTHOGONAL (the Tines language); the components own the
  stroke; no arrowheads; forks differ by direction.** Paths come from
  `getSmoothStepPath` + `railCenter` (GradientEdge): the first turn sits
  2×`METRICS.edgeRadius` past the source (shorter STARVES the corners — smoothstep
  clamps each bend to half its segment). ALL four control kinds
  (sequential/branch/error/end) get `type: "gradient"`
  (`components/edges/GradientEdge.tsx`) — a `userSpaceOnUse` SVG gradient along the true
  edge direction; the pure `gradientStops()` decides the blend per kind: sequential/branch =
  full **source → target** node-color blend; **error** = node color fading to red over
  ~26px at each end; **end** = node color fading to faint grey at the source.
  `data_flow` gets the custom `type: "data"` (`DataEdge.tsx`): the same path language
  plus per-LANE geometry — `EdgeData.lane` (assigned by `assignEdgeLanes` in flow.ts)
  gives each parallel binding at a node a distinct stub length AND middle-rail offset,
  so bundles fan apart instead of overlapping pixel-exactly. Data lines are flat
  `--data-edge` teal EXCEPT a focused line, which draws SOLID at the clicked end and
  fades a hint toward the far end (`EdgeData.focusEnd`, set by `applyFocus`).
  Branch/error edges carry lanes too: in **LR** (own row handles) `railCenter`
  staggers their rails apart; in **TD** the lane is IGNORED — branches leave ONE point
  (the icon column), so the shared rail IS the trunk-split look, by design. Stroke
  width comes from `metrics.ts` (== the tile border, so a line flows seamlessly into
  the same-color border). **No arrowheads** (clean lines into the borders). **Never
  set ANY edge kind's `stroke` in CSS** — the components own color and CSS strokes
  nothing, so a regression to a built-in edge type renders INVISIBLY (pinned by flow
  tests). Dash (branch), the data/end dot patterns, and shadow/dim opacity ARE CSS
  (separate properties). **Forks:** in **LR** a branch leaves a labeled border handle
  (`BranchPorts`, n8n-style). In **TD** the control handles (`NODE_IN`/`NODE_OUT`) AND the
  forks all align to the **icon column** (`ICON_COL_X` from metrics.ts — the SAME x
  layout.ts declares to ELK as fixed ports, see next bullet), so the trunk + forks flow
  through the icon; a fork's label then rides its edge
  (GradientEdge renders it) instead of a border row, and `BranchPorts` draws nothing.
  A TD outcome label is BARE TEXT (shadow halo, no pill) anchored at the TARGET's
  entry — left edge just right of the node's left border (`labelAnchor` +
  `LABEL_NUDGE_X`). Error pills stay mid-path. Fork TARGETS lay out in the code's
  chain order (`orderForkSiblings` in layout.ts — first `if` leftmost; Steps
  order is irrelevant to a fork's reading order). **Branch CONDITIONS** (the
  contract's fail-closed AST extraction) render where the outcome lives. **TD**: an
  edge-colored `.edge-label` pill (target node's color, the standard pill rule)
  rides `EdgeData.condition` on the FINAL APPROACH into its target, stacked above
  the outcome label (`conditionAnchor` — ONE pill per target entry; a path-midpoint
  anchor collides: TD fork siblings share the rail Y, and a back-railed loop-back's
  midpoint sits on its wrap — measured). **LR**: the source's BranchPorts ROW is
  the condition's home — quiet text beside the outcome pill
  (`LeafData.branchConditions`; mid-path pills clipped under cards and floated on
  backward wraps); a branch re-anchored onto a group (no rows) keeps the edge pill.
  Visible in advanced always / beautiful while the condition node is
  focus-expanded (the build-time `conditionShown` default — safe since expansion
  re-runs the build) — PLUS clicking a branch TARGET reveals just its own condition
  ("why was I reached?"): the edge pill via `conditionRevealed` (applyFocus), or
  for a labeled LR branch from a leaf, the SOURCE's row via
  `LeafData.revealedConditions` (an edge pill at the target entry overlapped the
  clicked card). The raw `condition` + `outcome` always ride EdgeData so the
  restyle pass has them. In LR, whenever the source's rows show, each target ALSO
  gets its outcome name at its entry — TD-style bare text ABOVE the line
  (`labelAnchor` Left arm; on-line struck the text) — so a reader finds where each
  row's line lands without tracing it. The read panel shows the untruncated
  outcome → condition table (GraphView passes the node's branch edges + a
  decision's END edge, labeled "end"). **A decision's END edge is its reserved
  "end" OUTCOME** (`is_decision` counts the end route — `if ok: next="end" else:
  next="fix"` gates ARE decisions): buildFlow appends `"end"` LAST to the node's
  `branchLabels` (BranchPorts renders it as a faint row, `.branch-port-end` — a
  real outcome that stops the flow), the LR end edge leaves `branchHandle("end")`,
  and the END edge's `condition` follows the same pill/row/reveal rules (incl.
  clicking the end dot — "why did flow stop?"). A non-decision's END edge (static
  `- next: end`) is untouched. **BACKWARD branch/error
  edges** (loop-backs to an earlier node) get a post-layout BACK RAIL
  (`assignBackRails`, portSides.ts — LR routes below both endpoint boxes, TD left
  of them; lane-staggered): smoothstep's stock wrap U-turned at the ~20px stub
  right at the source handle, knotting sibling loop-backs. GradientEdge prefers
  `data.railX/railY` over its `railCenter` default; sequential edges are
  deliberately untouched (their backward cycle already renders clean).
- **Layout is told where the handles are (layout.ts).** TD leaf nodes declare ELK
  `FIXED_POS` ports at `ICON_COL_X` — without them ELK aligns box CENTERS while the
  handles render at the icon column, jogging every "straight" connection. Port-aware
  NETWORK_SIMPLEX aligns columns icon-to-icon; each target's FIRST non-error control
  in-edge gets a straightness priority (the LEFTMOST sibling keeps the straight trunk
  through forks AND merges, user-decided); error-only targets order LAST among
  siblings (rightmost TD / bottom LR) via `forceNodeModelOrder` — the ONLY model-order
  option that survives `INCLUDE_CHILDREN` (every `considerModelOrder.strategy` value
  crashes elkjs on a cross-hierarchy edge; bisected 2026-06-09). **LR has the same
  icon-line discipline** (2026-06-10): control handles sit on the ICON ROW
  (`ICON_ROW_Y` = header center — in on the left, out on the right at the SAME
  height, so the trunk passes straight THROUGH the node), with matching fixed
  ports; different-height cards then sit header-to-header on one line, bodies
  hanging below. **LR also declares ROW ports**: every visible param/output/
  branch/IO row gets a fixed port at its exact (side, y) — `rows.ts rowAnchorsFor`
  owns the y math (mirrors the components' render order + `METRICS.ioRowsChrome`).
  Ports only make alignment POSSIBLE; straightness priorities make ELK pay for
  it, and they are WEIGHTS, not constraints: the control trunk carries **100**
  (a 13-binding bundle at 5 each out-voted the old 10 — measured 233px off-spine),
  row-to-row bindings carry **5**. The io card's rows carry an INPUTS/OUTPUTS
  column caption for GRID PARITY with a group card's IO columns (one shared grid:
  header + chrome + label + rows), so spine-aligned card pairs get straight
  binding bundles simultaneously — leaf↔card bindings have no parity guarantee
  and may keep small jogs (honest geometry). Expanded regions stay port-less
  (the compound crash).
- **The SPINE pass straightens what the missing region ports bend
  (`graph/spine.ts alignSpine`, run at the END of `layoutGraph` — so the layout
  cache / camera anchoring / animation all see aligned positions).** Because
  expanded regions carry no ELK port, ELK anchors their trunk edges at the box
  CENTER while the handles render on the icon line — every wide region knocks
  the following chain sideways by ~half its width and the error COMPOUNDS down
  the flow (the "staircase", user-caught 2026-06-11). The pass re-aligns each
  PURE sequential chain's control anchors (icon line; an end dot's CENTER) to
  its HEAD's — the head keeps ELK's position (entry placement, fork ordering).
  Chain links are sequential/end edges between same-scope siblings; a node with
  >1 spine-relevant control edge on either side (fork / merge / multi-terminal
  sink) breaks the chain there — fork fan-outs keep their 2D spread, a shared
  Outputs card stays ELK-balanced between its sources. ERROR edges count toward
  neither side (a handler hanging off a node must not break the trunk through
  it). A shift that would land within `SPINE_CLEARANCE` of a same-scope sibling
  is SKIPPED (honest jog beats overlap — ELK's collision guarantees only hold
  for the positions it chose). Runs per scope in parent-relative coords, so
  nested chains straighten past their own nested regions too. LR residual,
  stated: shifting a region vertically can re-jog row-aligned bindings crossing
  its boundary — trunk-over-bindings is the established priority order (100 vs
  5), now applied post-hoc as well.
- **Icon connector flare (beautiful; TD top/bottom + LR left).** A kind-colored SVG
  cove (`Connector` in `WorkflowNode`, anchored as a child of `.node-tile`) makes a
  control edge appear to flow **into the icon tile** — drawn only on sides that have
  a control edge (`hasIncoming`/`hasOutgoing`, computed in `flow.ts buildFlow`). The
  LR variant (`side="left"`, `CONNECTOR_LEFT` — the TOP path transposed, arc sweeps
  flipped) lands on the tile's LEFT border at the icon row; there is NO right tile
  flare — the tile sits at the card's left. The LR EXIT instead gets the **exit
  dot** (`.exit-dot`, user-picked 2026-06-10): a
  kind-colored 10px dot straddling the right border at the icon row, pure
  decoration (the invisible NODE_OUT handle is tucked 5px INSIDE the card so the
  edge terminus hides under it — RF otherwise anchors a right handle just outside
  the border, a visible 2px unplugged gap). Rendered by all three card components
  on `hasOutgoing`, which is HANDLE-aware (`flow.ts` incidence post-pass counts
  only edges leaving NODE_OUT): an LR decision's outcomes leave their BranchPorts
  rows — which carry their own dots — so a pure decider lights no icon-row exit. Three rules keep it gap-free; breaking any
  one re-opens the historical gaps:
  1. The control `Handle`s stay on the node BORDER as direct, untransformed children — the
     only placement React Flow measures reliably. (A handle nested inside the transformed,
     outside-the-box connector div is mis-measured ~5px → a visible edge↔stub gap. Measured,
     not theorized.)
  2. The flare is PURE DECORATION (owns no handle), opaque, drawn ON TOP, and OVERLAPS both
     ends — the stem slides under the edge terminus (same width + color), the base sinks into
     the tile's 3px border (within it; past it = a dark notch). Sub-pixel alignment can never
     open a gap.
  3. ONE constant set (`CONN`, fed by `graph/metrics.ts`) derives the SVG path, the viewBox,
     AND the element's inline size. If viewBox and box disagree, the browser silently rescales
     the paint inside a correctly-placed box — invisible to rect measurement (the "1px-thin
     tip / angular cove" bug). Paths use elliptical arcs, so tangency (vertical at the stem,
     horizontal at the base) holds by construction.
  Underlying constraint that forced all this: React Flow draws edges *behind* nodes, so any
  line-into-the-icon must be our geometry, never a stock edge.
- **A loop is drawn, not in the contract.** A loop is a `LoopSpec` on a node;
  `flow.ts` synthesizes a self-loop edge (`type:"loop"`) anchored to the node or its
  group, and `components/edges/LoopEdge.tsx` draws it as a rounded-orthogonal **U**
  wrapping AROUND the box: `getSmoothStepPath` + a wrap rail from the post-layout
  `assignLoopRails` pass (portSides.ts — TD: rail right of the box via `centerX`,
  LR: above via `centerY`). The rail is LOAD-BEARING, not polish: a self-loop's
  endpoints share an axis, so the default smoothstep midpoint runs the line straight
  back THROUGH the node. **Where the U lands and what it says (the loop-row
  design, user-decided 2026-06-10):** a LEAF whose body rows render (advanced /
  focus-expanded) grows ↻ loop-rule rows (WorkflowNode; amber, right-aligned —
  it's authored LOOP config, deliberately NOT presented as a data param; leafSize
  counts them): the CONDITION row + the cap `≤ ${…}` on its OWN row (one row
  truncated both operands). A looped node telegraphs in ALL states via the amber
  ↻ CHIP on the border rail (ChipRail.tsx). The U's arrow lands ON the condition row (`LOOP_ROW` handle, target-type)
  — "iteration re-enters under this rule"; the edge then carries NO floating
  label (the row holds the condition, like data lines dropping their label on
  row-landing). A compact leaf shows a BARE U into NODE_IN — beautiful stays
  quiet; click to expand and see why. A GROUP anchor has no rows: the floating
  label (bottom run in TD — the top run is contested by trunk/branch labels;
  LR: top rail) renders in ADVANCED only, gated by `data.loop`'s presence (the
  edge's only use of it; the read panel always has the full spec from the node).
  The pill needs an OPAQUE bg (it sits on the line), and the loop edge must NOT
  set zIndex — an elevated edge paints above the EdgeLabelRenderer layer and
  strikes through its own pill. The U carries the app's ONE arrowhead at the
  re-entry (own `<polygon>`, CSS `--loop` fill — RF marker objects only take
  literal colors): a loop is the only edge whose direction the layout doesn't
  imply. Self-loops are filtered out of ELK.
- **A container is ONE object in two states (GroupNode, 2026-06-10 redesign) — and
  NOTHING in its header moves across the fold (user requirement).** Both states
  render the IDENTICAL header markup (one JSX block): the leaf `.node-header` with
  the full-size tile + `.node-titles` (category + purpose||node_id), in leaf
  positions/typography. `METRICS.groupHeaderH` MUST equal `nodeHeaderH` (ELK's
  region padding is derived from it). The CHIP RAIL (`.chip-rail`, ChipRail.tsx —
  the host's loop/batch behavior chips + the merged count-expander
  `.group-toggle`: recursive step count `memberCount` + the A1 glyph;
  `group.members` only sees direct children) is ABSOLUTE on the top-right border
  in both states. COLLAPSED → leaf classes
  (`.node.compact.group-card`): card CSS, focus ring, dimming come wholesale;
  icon-column ELK ports (TD `portable` set, layout.ts) + top AND bottom connector
  flares. EXPANDED → kind-tinted region (`--kind` inline: workflow magenta
  `#e26ad8`, batch purple = `BATCH_COLOR` == CSS `--batch`); handles STILL at the
  icon column (the trunk flows into the region's tile) with the TOP flare only
  (the tile sits at the region's top, far from the bottom exit) — but NO ELK port:
  **a port on a COMPOUND node crashes elkjs under INCLUDE_CHILDREN when an edge
  references it** ("NEdge must have a source and target NNode"; pinned by a layout
  test). Flare incidence comes from a control-incidence POST-pass over the FLOW
  edges for ALL groups (contract edges never name a group; purely-internal edges
  must not count). Collapsed cards dim under focus like leaves; expanded regions
  never dim. Icon from `groupIconFor` (the host's KIND icon, always — behavior
  rides the rail chips, never the icon). React Flow's default `node-group` wrapper styling is neutralized in
  index.css **including its `text-align: center`** — GroupNode owns the visual.
  Batch cards (and `.batched` leaves — unexpanded dynamic batches) draw a stacked
  DECK via pseudo-elements (the Tines stacked-copies look).
- **The border CHIP RAIL (ChipRail.tsx, 2026-06-10).** Behavior modifiers render
  as 22px tinted chips straddling the TOP
  border, right-aligned, on leaves AND containers: loop = amber round ↻ (tooltip:
  polarity + condition + cap), batch = purple capsule (stack glyph + `×{count}`
  literal / `×N` dynamic — the count is statically unknowable, so the iterated
  `source_ref` rides the TOOLTIP, never a guessed number; a future run overlay
  fills the real count). Grammar: round/capsule tinted chip = INFO; the one
  SQUARE element (the group expander) = button. Identity (tile/category)
  never mutates; behavior is additive border chrome. The rail is the reserved
  home for future live-overlay STATUS chips (status joins leftmost, outranks
  modifiers). It extends 11px above the box; ELK doesn't know (no layout
  impact). `.node.compact/.detailed` are BOTH
  `overflow: visible` for it (detailed was hidden, silently clipping the deck
  on advanced cards).
- **Containers SELECT on click; expand/collapse is the rail's count-expander
  (user-decided 2026-06-10).** A container's body — collapsed card OR expanded
  region/header — is a node like any other: click = focus + read panel (the panel
  shows the group's HOST node, resolved in GraphView's `selectedNode`; a ROOT
  wrapper group resolves through `selectedIoGroup` to the IoPanel instead — see
  the IO bullet). The ONLY single-click toggle is the
  `.group-toggle` expander GroupNode renders as the rail's last element in both
  states — the step count + arrows-out/in glyph in a rounded-SQUARE chip
  (its `stopPropagation` is LOAD-BEARING, else the click also selects) —
  plus double-click anywhere on the container (`onNodeDoubleClick`;
  `zoomOnDoubleClick={false}` on ReactFlow or every dblclick zooms). Batched
  LEAVES get no expander by construction — they render via WorkflowNode (nothing
  to open). **Selecting a container selects the whole UNIT** (`applyFocus`): the
  group, all descendants (flow `parentId` BFS), and every edge touching any of
  them — internal wiring + external bindings light, the rest dims; in beautiful
  the unit's hidden data lines reveal ("what feeds this box?" without opening
  it). In beautiful, selecting a container ALSO expands "just its inputs and
  outputs" (user-decided 2026-06-10): `expandTargets` treats a workflow/batch
  group focus as ALL of its IO ports (child wrappers' members), so the card/
  region renders its IO rows and each binding's far end expands too — every
  revealed line lands row-to-row. Without this the bindings re-anchor
  node-level and DEDUPE into one line whose surviving label single-names the
  first port (actively misleading). Group select therefore re-layouts in
  beautiful exactly like leaf focus-expansion (cached/animated/camera-anchored).
  Deep links select containers BY NAME: `resolveNodeFlatId`
  (viewParams.ts) resolves a group-host's node_id to its representative group
  (skipping decorator shells via `shellBatchIds` — a literal batch host resolves
  to its rendered BATCH container), so `?focus=<sub-workflow name>` works.
- **Edges SELECT on click (2026-06-10).** The clicked CONNECTION is the focus subject:
  only that edge lights — bright variant (`--data-edge-selected` for data lines; full
  gradient for control), a **halo under-stroke** (the edge analog of the node ring;
  its stroke must stay INLINE — RF's base stylesheet greys `.selected` paths),
  **elevation** (`zIndex: SELECTED_EDGE_Z`, an applyFocus-OWNED channel — never read
  back from the edge) — while its two endpoints stay full-strength and everything
  else dims, INCLUDING EdgeLabelRenderer pills (they live outside
  `.react-flow__edge`, so applyFocus writes `EdgeData.dimmed` and the components add
  `.label-dimmed`). The selected edge suppresses its OWN floating label/pill
  (elevation strikes through the label layer; the panel carries the info) — a
  selected LR branch instead reveals its condition on the source's row. `applyFocus`
  clears `focusEnd` on the selected edge (both ends solid — the ternary would default
  one end faded). The `shadowed` FACT still rides EdgeData but no density dims for
  it anymore (2026-06-13: with one edge per `${ref}` most of the sequential spine
  is shadowed — the old advanced 35% dim erased the control skeleton; user-gated
  removal via browser before/after). In beautiful, a
  selected DATA edge expands exactly its two endpoint owners (`expandTargets` edge
  arm — endpoints go into the OUTPUT set, never `foci`, or both neighborhoods would
  expand) so the line lands row-to-row. The click dispatch is pure
  (`edgeClickAction`, viewParams.ts — jsdom renders no edge DOM): `loop:` arcs
  redirect to their render ANCHOR (`e.source` — a group id for looped sub-workflows;
  never `data.from`, the suppressed host), `io-flow:` edges focus restyle-only and
  CLEAR the panel, contract edges select fully. **EdgePanel**
  (components/EdgePanel.tsx) reads the contract edge by id (flow edges keep contract
  ids; synthesized ids miss by design): five variants — data (param join via
  `bindingParam`, mirroring `targetHandleFor`'s dict-key walk; this edge's `${ref}`
  highlighted via ParamBlock's `highlightRef`; "one of N references/bindings"
  counts), branch/decision-end (OutcomeTable with the row marked; discriminate a
  decision's end by the SOURCE's `is_decision`, never condition presence —
  extraction is fail-closed), error, static-end, sequential (surfaces `shadowed`).
  The data variant has a CACHE arm (`input_name === "prompt_cache"`, the
  contract's reserved name for a `## Cache` chunk dependency): kind line
  "cached context", title `field → cached prompt prefix`, a purpose line naming
  the `## Cache` block — never a param binding (the chunk's
  ref is forbidden in the consumer's prompt, so this edge is the dependency's
  only visibility). ALL binding-name surfaces route through `bindingLabel`
  (utils/format.ts — `prompt_cache` → "cached prefix"): the beautiful edge
  label (`dataFlowLabel`), the panel's interpolated/bundle facts. The
  ReadPanel additionally shows `RFNode.cached_prefix` — the `## Cache` block's
  assembled template (prose + ${var}, prefix order, baked in Python with the
  runtime's own assembly rule) — as a `cached prefix` block placed by
  `cacheInsertIndex` before `prompt`, colored as markdown SOURCE like prompts.
- **The LEFT column has ONE source of truth: `paramRowsFor` (graph/rows.ts,
  2026-06-13) — the `outputRowsFor` mirror, composed into `nodeRows` (the body
  bullet above).** It assembles the ordered `ParamRowItem[]` list (params in
  authored order · the cached-prefix group before `prompt` via
  `cacheInsertIndex` — request order: system → cached prefix → prompt · per-ref
  binding SUB-ROWS). SUB-ROWS (user design 2026-06-13): a param receiving ≥2
  refs (an interpolated prompt, a dict of bindings) grows one nested `·` row
  per ref — label = the authored ref text rebuilt from the edge (`refText`;
  rendered as the established ref-chip; a dict-key row prepends its key) —
  and each edge lands on ITS row's `bindingRowHandle(input_name, ref)`; a
  single ref keeps landing on the param row itself (no sub-row noise on the
  common case). Cache chunks are the same mechanism with parent group
  "prompt_cache": one chunk = a flat `cached prefix` row, several = a
  handle-less `cached prefix ×N` label row + nested rows — and cache edges
  ALWAYS land on their chunk row (no param row exists for them; without one
  they merged invisibly into the control trunk at NODE_IN). The landing rule
  lives in `targetHandleFor` reading the SAME `refRowsByNode` derivation, so
  rows and landings can't disagree. Rows hidden (beautiful) → NODE_IN
  fallback unchanged.
  Endpoint CHIPS navigate via `resolveEndpointFlatId` (host → representative group)
  and render NON-CLICKABLE when the endpoint isn't rendered — never a silent no-op
  focus. RF native selection stays inert: components ignore the `selected` prop,
  `deleteKeyCode={null}` (Backspace would delete from the store). An edge-id focus
  has no `from/to` escape hatch through rebuilds, so GraphView CLEARS the selection
  when the focused edge id leaves the flow (collapse re-anchor/dedupe). Deep links:
  `focus=<flat edge id>` works (the deterministic escape hatch — agents/screenshot
  loop); `initialCollapsed` protects BOTH endpoints' ancestor chains for an edge
  target. Stable edge ADDRESSING (`source→target:input`) stays deferred (Task 169).
- **A decorator-SHELL batch group is never rendered — and `shellBatchIds` (graph/io.ts)
  is the ONE copy of what counts as a shell.** The contract models "batched X" as
  batch-wrapping-X, but presentationally batch is a MODIFIER (deck + ×N chip), not a
  box to travel through (user decision 2026-06-10): a DYNAMIC batch group is always
  a shell — the workflow group reparents past it (`effectiveParent`), becomes the
  host's representative (`groupsByHost` skips shells → edges/title/loop land on it),
  gets the deck from `hostNode.batch`, and its corner toggle opens the sub-workflow
  body directly; a batched LEAF renders as a normal selectable node (its shell was
  the "▸ 0 nodes" card bug; a LITERAL-batched leaf ships `is_group_host: false` from
  Python — leaf items are BatchSpec.items data, there is no body to draw). The
  EXCEPTION: a LITERAL batch whose items expanded into real item groups is NOT a
  shell — the batch container renders as the host's representative box (title +
  chips + deck) with the item groups inside ("literal batches keep their
  container"). The discriminator is literal-vs-dynamic + child groups, NEVER
  memberlessness — a batch group never has direct node members, so the old
  `members.length === 0` rule swallowed literal batches whole: the host had no
  on-canvas representative and every edge touching it warn-dropped, shattering the
  spine at each literal batch step (review-caught 2026-06-11, CRITICAL).
  `collapse.ts collapsibleGroupIds` and `viewParams.ts resolveEndpointFlatId` both
  consume `shellBatchIds` — never re-derive the rule locally.
- **IO is ROWS on the workflow's OWN node — never a floating table (2026-06-10
  redesign).** An `input_wrapper`/`output_wrapper` group's ports render via the shared
  `PortRows` component on their OWNER; the IO member nodes are NOT emitted. Three
  locations, one anatomy: (1) a ROOT wrapper becomes a standalone **IO card**
  (`IOCardNode`, RF type `"io"`, id = the wrapper's group id — focus/deep-link ids
  stay stable): tile + INPUTS/OUTPUTS category + a title line (the leaf
  `description || identity` convention: a SINGLE-port card shows that port's own
  description — the section has no description slot, only ports do; multi-port
  shows the workflow name; tooltip carries both) + a `"14 inputs"` pill; compact
  in beautiful, rows under the leaf `showBody` rule (advanced / focus-expanded).
  IO rows speak the SAME text grammar as leaf output rows — `name: type` via the
  shared `.row-type` faint suffix (PortRows; the old detached 10px `.io-type`
  died, user-caught 2026-06-11) — and clicking the card SELECTS like every other node
  (2026-06-11, the toggle died when the card got a panel): focus + **IoPanel**
  (components/IoPanel.tsx), the workflow's interface written out — per input:
  type/required/`default:`/full description + consumer chips under a faint
  `used by` label; per output: a `from` label + the producer chip + the
  dot-prefixed field it reads (one phrase: `from [build-report] .result`;
  `.io-port-uses` un-stretches `.edge-chip`, `.io-port-uses-label` is the
  relationship word — the panel's label-word vocabulary, clearer than bare
  arrows) + source line. Types carry NO filler — never "any" (an invented
  claim, user-caught 2026-06-11): `Port.dataType` is the authored `type:` when
  declared, else an OUTPUT derives fail-closed from its SINGLE producer edge
  via `producedTypeOf` (the same shape→registry resolution order the canvas
  output rows use), else null — and the derivation lives IN `wrapperPorts`,
  so the canvas io rows show `report str` identically to the panel. Ports come
  from the exported `wrapperPorts` (graph/io.ts — the SAME single copy the canvas
  rows render from); consumers/producers derive inline from contract data-flow
  edges; chips are the shared `Chip` (components/Chip.tsx). An input with
  NO data-flow edges shows no "used by" row at all — never an "unused" claim
  (loop-condition reads form no edges: the quiet≠unconsumed rule). A ROOT
  card's row click ALSO opens the panel with that entry marked (`focusPort` in
  GraphView resolves the port's owner via `ioOwners`; NESTED rows stay
  focus-only). GraphView's `selectedIoGroup` is the third panel-resolution arm,
  disjoint by id namespace from `selectedNode`/`selectedEdge`. In beautiful the
  card's rows still open via focus (selection sets focus → expansion); closing =
  pane click / panel ✕, like every node. The card class is
  ALWAYS `compact` (the card shell lives on `.node.compact/.detailed`; adding
  `expanded` doubles the divider — both were real bugs). **Root IO cards JOIN THE
  CONTROL SKELETON (2026-06-10):** `buildFlow` synthesizes `io-flow:` control edges
  — Inputs card → each root ENTRY step (no incoming control edge; falls back to
  the FIRST root step, where pflow starts execution, on a root cycle) and each
  root CONTROL SINK's representative → Outputs card (no sequential/branch out-edge,
  derived from contract edges; LAST-root-step fallback on a cycle). Sink-ness must
  NOT come from the contract's `is_terminal` — that fact counts DATA_FLOW out-edges
  (Mermaid end-sink parity), so a final leaf feeding a declared output reads
  non-terminal and the Outputs card floats as an island (the 2026-06-11 bug).
  NOT contract edges (pflow has no
  io→node control flow) — visual policy that makes the cards behave like nodes:
  drawn in BOTH densities, gradient blends IO teal ↔ the step's kind color, ELK
  lays the cards into the spine (they were data-only islands parked beside it),
  and the cards carry the full leaf flare anatomy (TD icon-column handles + ELK
  ports via layout.ts's `portable` set; an expanded card drops its BOTTOM flare,
  the leaf rule). Control-incidence (`hasIncoming`/`hasOutgoing`) for ALL
  flare-bearing types (leaves, groups, io cards) comes from ONE post-pass over the
  FLOW edges, so the synthesized edges count. (2) a NESTED wrapper
  puts its rows on the workflow GROUP
  (`GroupData.inputs/outputs`): the COLLAPSED card grows a two-column area — inputs
  left, outputs right BOTTOM-ANCHORED (`PortRows staggerRows = ioRowsCount − nOut`,
  always ≥ 1 row below the inputs' start: the in→out diagonal IS the information);
  the EXPANDED region
  renders inputs as the LEFT SIDEBAR and outputs as the bottom-right strip —
  ALWAYS shown while the region is OPEN, in BOTH densities (an open container
  hiding its inputs reads as "has none"; beautiful hides only the data LINES,
  which still reveal on focus) — with full-width dividers — `layout.ts groupPadding` reserves the sidebar as ELK LEFT
  padding (the body's first layer lays out BESIDE it) and the strip as bottom
  padding, plus `nodeSize.minimum` so a tall sidebar can't overflow a short body
  (GOTCHA: under direction DOWN elkjs applies the minimum TRANSPOSED — pass
  `(minH, minW)` in TD; measured, test-pinned). Rows follow the STRICT side
  convention (same as param/output rows): receive (`portTargetHandle`) LEFT, feed
  (`portHandle`) RIGHT — sides are structural, never flipped post-layout. Both
  handles always
  render (an edge naming a missing handle is silently dropped — the recurring bug
  class); the role-less side's dot is hidden via `.port-handle.quiet`. **ALL rows
  speak ONE connection language (2026-06-12):** wired = teal name + live teal
  dot, unwired/static = muted name + quiet dot — a dynamic param (`is_dynamic`),
  a read output, and a wired io row all render identically. An io row's wiring
  is SIDE-AWARE (`Port.receives`/`Port.feeds`; PortRows picks the side its
  location presents via `handles`) — a sub-workflow output no caller reads is
  grey on the collapsed card even though its INNER producer edge exists, and a
  NESTED row whose port has no line in the current view is click-INERT (the
  into-nowhere gate in GraphView's focusPort; root card rows always click —
  the panel is the payoff). Io paint gotcha: `.port-handle` color must live AFTER the generic
  `.handle` rule in index.css (equal specificity — defined earlier it silently
  renders grey, the 2026-06-12 drift). The OUTER io dot offsets onto the
  card/region border via `--io-inset` (defined beside each container's padding). Edge handle
  resolution is owner-aware (`ioNodeToOwner` + `rowsVisible(owner)`): rows hidden →
  node-level, never a handle that doesn't render. `expandTargets` pulls an IO
  endpoint's OWNER into the expansion set, so focusing a consumer expands the owner
  and the revealed line lands row-to-row. **Every edge carries its original
  endpoints (`data.from`/`data.to`)**, so `applyFocus` can reveal a *single* port's
  lines even though its edges re-anchor onto the owner; clicking a row focuses that
  port id via the `InteractionContext` (`focusedPortId` highlights the row).
  NOTE: with rows hidden (beautiful), parallel bindings between the same pair
  DEDUPE to one node-level line — correct, because any focus that could reveal
  them re-runs the build with the owner expanded, where each binding keeps its own
  row handle. Wrap-arounds to reach a strict-side row get the RAIL HINT
  (`assignDataRails`): the data edge's middle segment centers in the clear gap
  between the endpoint boxes (data.railX/railY → DataEdge) so a wrap never hugs a
  node border. Decision forks render as labeled border handles (`branchHandle`) in
  both densities; in beautiful, a revealed LEAF-TO-LEAF data line is labeled with
  what flows (`output_field → input_name`) — but an IO-touching binding carries NO
  label (the port rows name the fields, and a binding label often single-names one
  side; user-caught 2026-06-10), and any line landing row-to-row drops it too.
- **The node CHIP is one shared component (components/Chip.tsx, 2026-06-11) — a
  mini node avatar:** the canvas tile in miniature (kind-color border +
  native-color icon via `nodeColor`/`iconFor`) + the name, no box; the category
  word rides the TOOLTIP (identity by recognition — the canvas teaches the
  icon↔kind map once). Consumers: EdgePanel endpoints, IoPanel consumer/producer
  rows, ReadPanel's `ConnectionSections`. Semantics every consumer inherits:
  chips NAVIGATE WITHOUT OPENING (user decision 2026-06-12 — `onNavigate(id)`
  with no selectedId): focus moves to the target (it lights, its connections
  reveal, the camera follows) but the open panel never swaps — a chip answers
  "where is it / how are we connected?"; click the centered node itself to
  open it. Resolve-or-disable (an endpoint hidden in a collapsed ancestor
  renders non-clickable — never a silent no-op), io-port chips use port-focus,
  and HOVER marks the chip's canvas node. An io-port chip's camera follow AND the
  expansion re-layout's anchor both resolve the port to its OWNER card via
  `ioOwners` (a port id is never a rendered node — unresolved, the follow
  silently skipped and the anchorless re-layout jumped the canvas to nowhere;
  fixed 2026-06-12). The follow itself is DEFERRED to the paint the click
  produces (`paintEpoch` from useWorkflowGraph — bumped after every completed
  paint, animated glides included): a fit started at click time aims at the
  target's PRE-re-layout position (first click landed wrong, second landed
  right). A same-focus navigate repaints nothing and fits immediately. A NESTED io-port chip is SCOPE-PREFIXED
  (`create-songs.concept`, faint prefix — a bare port name loses whose input it
  is; root ports stay bare, the panel names the workflow) and its hover marks
  the PORT id. An IoPanel PORT-producer row drops a field that just repeats the
  port's name (`from execute-plan.pr_url .pr_url` said it twice); deeper
  sub-paths still show. **`ConnectionSections`** (the ReadPanel's tail): the
  node's data-flow neighborhood as chip stacks — `references (N)` (upstream,
  first: data flows in→out) then `referenced by (N)` (downstream), from
  `producersOf`/`consumersOf` (deduped, edge order); an EMPTY direction renders
  NOTHING (no-claims rule). A GROUP HOST aggregates as a BLACK BOX
  (2026-06-12): its data flow lives on its io-PORT members, not its own id
  (only batch `${x.results}` reads attach host-level), so `dataNeighbors`
  widens the subject to host + direct wrappers' ports and lists EXTERNAL far
  ends only — an input's inner consumer / an output's inner producer is the
  body's wiring, never the unit's neighborhood. Derived from contract edges ONLY —
  COMPLETE since the 2026-06-13 unified-edge model fix (every validator-enforced
  `${ref}`, incl. plain-param sibling refs, now draws a DATA_FLOW edge; the original
  design is recorded in
  .taskmaster/tasks/task_168/implementation/sub-plans/proposal.md).
- **HOVER is one concept: mark a SET of canvas subjects — a PURE highlight**
  (no focus change, no expansion, NO camera move; user decision 2026-06-11).
  Two producers: a panel CHIP marks its one resolved node
  (`Interaction.hoverNode`); a canvas ROW (param/output rows on leaves, io rows
  via PortRows) marks every edge landing on it AND each edge's far-end node
  (`Interaction.hoverRow` → GraphView derives the set with `rowTouches` over
  the FLOW edges — the resolved row landings, never a contract re-derivation,
  so the marks can't disagree with what's drawn; flow edges are read via a ref
  so the callbacks stay stable). The marked set rides `useHoverMarks` — ONE set,
  two readers by disjoint id namespace: NODE ids ring their box (leaves on
  `hovered.has(id)`; GroupNode/IOCardNode also ring when a hovered PORT id is
  theirs — findable with rows hidden; PortRows lights the matching row), EDGE
  ids light their line in DataEdge/GradientEdge with the SELECTED treatment
  (EdgeHalo + bright/gradient stroke) minus the zIndex elevation — hover is
  transient, tunneling relief stays a selection concern. Hidden beautiful data
  edges stay hidden (revealing is click/focus territory). `.hover-mark` = the
  focus ring + an un-dim override (must stay after `.node.dimmed` in the
  sheet). GraphView's `onNavigate` clears the hover (the clicked chip unmounts
  with the panel swap — its mouseleave never fires).
- **Authored text rendering (2026-06-12): three treatments, one per surface
  class.** (1) RENDER — prose descriptions (`node.purpose` in ReadPanel,
  `port.description` in IoPanel, catalog `item.description`) render as real
  markdown via `components/Markdown.tsx` (react-markdown + remark-gfm; raw HTML
  stays TEXT, images render alt-only — workflows are third-party content, no
  innerHTML anywhere). The catalog uses INLINE mode (bold/code spans only;
  blocks flatten to one flowing line — `p`/`li` stay allowed and map to
  trailing-space fragments so unwrapped boundaries keep their separation).
  Markdown CSS hangs off `.md` (its `white-space: normal` reset is
  load-bearing) — NEVER off `.read-panel-purpose`/`.io-port-desc`, which
  EdgePanel and the `default:` line share for app-written plain strings.
  (2) HIGHLIGHT — `utils/highlight.ts` is THE shiki seam (the SourcePane's
  whole-file view consumes this same module; a diff view was REJECTED —
  see the Source pane bullet): lazy
  promise-memoized chunk like ELK, except a REJECTED load resets the memo
  (transient 404'd chunk ≠ session-dead highlighting); 5 grammars
  (python/bash/json/yaml/markdown), fail-closed `null` → plain text for
  unknown langs, >50k chars, or any failure. `paramLanguage` (utils/format.ts)
  picks the language by VALUE TYPE first (object → json), then kind/name
  (code/shell/llm/claude-code); prompts color as markdown SOURCE, never
  rendered (user decision). `components/CodeBlock.tsx` is the one renderer of
  param values: the synchronous first paint is the legacy text + `.ref-mark`s
  (EdgePanel tests pin it), the shiki hast swaps in later — and with a
  `highlightRef`, ONLY if `markRefs` lands exactly the expected mark count (a
  tokenizer-split `${ref}` falls back to legacy; partial marks would lie).
  Shiki's `<pre>` never renders — its `<code>` children go inside OUR
  `.read-param-value` so pre-wrap keeps governing. (3) STRIP — canvas
  description lines + `title=` tooltips can't render formatting, so
  `stripMarkdown` (format.ts) hides markers, keeping all content; it is
  deliberately MORE conservative than CommonMark (no intraword `*`/`_`
  pairing: `2*3`, `snake_case`, `*.tmp` globs survive — under-strip beats
  corruption). Tiny truncated pills (condition/loop/field labels) are
  deliberately untouched: they hold code fragments, not prose.
- **Errors never blank the canvas.** `useWorkflowGraph`'s `status`
  (`loading`/`ready`/`empty`/`error`) drives a banner; a malformed 200 throws from
  `fetchGraph` (caught), an ELK failure becomes an error (not a stuck spinner), and any
  other render throw hits `ErrorBoundary`.
- **Overlay-ready seam.** Node components keep static data separate from a future
  `status` prop; `api/` is the single data-loading point a live stream plugs into.

## Dev, build, test

- **Dev:** run `uv run pflow ui --no-open` and `cd web && npm run dev`; Vite proxies
  `/api` → `127.0.0.1:8765` (override with `PFLOW_UI_PORT`).
- **Build:** `make ui-build` (`npm ci && npm run build`) → `../src/pflow/ui/static/`
  with `base:"./"`. `npm run build` runs `tsc --noEmit` first (strict).
- **Test:** `npx vitest run`. `graph/`/`utils/`/`api/` are node-env; `GraphView.test.tsx`
  is jsdom (`// @vitest-environment jsdom`) using `test/rf-jsdom.ts`.
- **CSS-order tripwire:** `src/cssOrder.test.ts` pins the two equal-specificity rule
  pairs where SOURCE ORDER decides paint (`.handle` before `.port-handle`;
  `.node.dimmed` before `.hover-mark`) — jsdom computes no cascade, so asserting the
  source text is the only CI-observable surface. It reads `index.css` via `node:fs`,
  NOT `import ... from "./index.css?raw"`: vitest's default `css: false` stubs `.css`
  imports to an empty string EVEN under the `?raw` query (probed on vitest 4.1.8;
  `?raw` on non-CSS files works, and `test.css: true` restores it — rejected here:
  enabling CSS processing for every test to prettify one import is the tail wagging
  the dog; upstream fixed the sibling `?inline` query in vitest#3954 but not `?raw`).
  Real-browser geometry invariants (dots-on-border, edge coverage,
  no-overlap) live in the screenshot skill's `visual-invariants.pflow.md` instead.
- **Packaging gotcha:** the bundle is gitignored and hatchling honors `.gitignore`, so
  `pyproject.toml` needs `[tool.hatch.build.targets.wheel] artifacts =
  ["src/pflow/ui/static/**/*"]` to ship it in the wheel — don't remove it.
  `web/package-lock.json` is committed (CI `npm ci`); `node_modules`/`dist` are not.
