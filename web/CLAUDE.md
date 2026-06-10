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
  api/               server communication (client.ts: fetch + ApiError; a live /events
                     subscription would go here)
  graph/             PURE contract → React Flow transform; NO React (tests run node-env)
    flow.ts          buildFlow (nodes/edges) + applyFocus; size constants
    layout.ts        ELK positioning (the only async step; lazy-loads elkjs as its own chunk)
    handles.ts       handle-id scheme
    metrics.ts       layout-coupled geometry constants — the single source for flow.ts
                     sizes, the connector/edge geometry, and the :root CSS vars main.tsx
                     injects before first paint
  hooks/             useWorkflowGraph: fetch → build → layout → focus → RF state + status
  utils/             pure helpers — format.ts (${ref} parsing, value previews, kind
                     colors, category label); icons.ts (node-kind/provider → SVG URL)
  assets/icons/      vendored brand/tool SVGs (Vite bundles them into static/assets)
  views/             the screens App switches between (CatalogView, GraphView)
  components/         reusable UI: Toolbar, ReadPanel, ErrorBoundary, nodes/, edges/
  test/              rf-jsdom.ts — React Flow jsdom mocks for component tests
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
- **An edge handle must exist on its node — and be the right TYPE — or React Flow
  silently drops the edge.** This is the recurring bug (it bit us twice). `flow.ts` only
  emits a per-row handle when a matching row exists, else falls back to `NODE_IN`/`NODE_OUT`.
  Each handle id encodes a fixed type via the scheme (`handleType` in `handles.ts`): a
  `sourceHandle` must resolve to "source", a `targetHandle` to "target". The
  HANDLE-TYPE INVARIANT test (`flow.test.ts`) enforces this — **jsdom CANNOT** (React
  Flow renders no edge DOM under jsdom, so any "no edge errors" assertion there is
  theater). Edge integrity is a pure `flow.ts` test, never a render test.
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
  label `CONDITION`, a fork icon (`assets/icons/condition.svg`: hollow orange ring in,
  hollow white rings out, legs blending orange→white — see the comment in the file for
  the baked-flip/evenodd-hole/gradient-stop geometry), and the condition orange
  (`#ffa657` == the CSS `--decision` var; keep them equal). `nodeColor(node)` is the single seam — card border, tile,
  category AND edge gradients all go through it; never call raw `kindColor(kind)` for a
  node's identity. Safe because multi-way routing (`next: str = ...`) is code-only, so
  the presentation hides no other kind; the kind gate is defensive. No decision badge
  (same reasoning as the deleted loop badge); the read panel shows `code · condition`
  so the canvas stays mappable to `type: code` in the file.
- **Density controls edges, not just node detail.** *Advanced* shows every edge.
  *Beautiful* shows only the control-flow skeleton: data-flow (`${ref}`) edges are built
  but `hidden`, and `applyFocus` reveals just the clicked node's data lines (hidden
  ones are also excluded from ELK so the layout stays tight). `applyFocus` reveals any
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
  fallback warns, never silent); the decoration effect paints ONLY a laid snapshot
  whose key matches the current state (stale-paint guard — without it every cached
  click "shakes": one frame of new-focus-on-old-layout). Small graphs
  (≤ `ANIMATE_MAX_NODES`) ANIMATE expansion re-layouts: positions interpolate
  through the RF store per frame so edge paths follow (a CSS transform transition
  detaches edges from gliding nodes — rejected, measured reasoning in the progress
  log); the anchoring pan eases in sync; only moved nodes change identity per frame;
  large flows snap; `prefers-reduced-motion` snaps.
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
  order is irrelevant to a fork's reading order). **Branch CONDITIONS**
  (`EdgeData.condition`, from the contract's fail-closed AST extraction) render
  as an orange-tinted `.edge-label` pill on a LONE segment (`conditionAnchor`:
  the edge's own rail run, or the final descent for the straight child — never
  the shared rail crossing) — set in `data` only when visible (advanced always;
  beautiful while the condition node is focus-expanded — safe as build-time
  state since expansion re-runs the build); the read panel shows the untruncated
  outcome → condition table (GraphView passes the node's branch edges).
- **Layout is told where the handles are (layout.ts).** TD leaf nodes declare ELK
  `FIXED_POS` ports at `ICON_COL_X` — without them ELK aligns box CENTERS while the
  handles render at the icon column, jogging every "straight" connection. Port-aware
  NETWORK_SIMPLEX aligns columns icon-to-icon; each target's FIRST non-error control
  in-edge gets a straightness priority (the LEFTMOST sibling keeps the straight trunk
  through forks AND merges, user-decided); error-only targets order LAST among
  siblings (rightmost TD / bottom LR) via `forceNodeModelOrder` — the ONLY model-order
  option that survives `INCLUDE_CHILDREN` (every `considerModelOrder.strategy` value
  crashes elkjs on a cross-hierarchy edge; bisected 2026-06-09).
- **Icon connector flare (TD+beautiful).** A kind-colored SVG cove (`Connector` in
  `WorkflowNode`, anchored as a child of `.node-tile`) makes a control edge appear to flow
  **into the icon tile** — drawn only on sides that have a control edge (`hasIncoming`/
  `hasOutgoing`, computed in `flow.ts buildFlow`). Three rules keep it gap-free; breaking any
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
  focus-expanded) grows ↻ loop-rule rowS (WorkflowNode; amber, right-aligned —
  it's authored LOOP config, deliberately NOT presented as a data param; leafSize
  counts them): the CONDITION row + the cap `≤ ${…}` on its OWN row (one row
  truncated both operands). The category line carries an amber ↻ mark in ALL
  states (`.loop-mark` — a compact looped leaf otherwise says nothing about
  looping). The U's arrow lands ON the condition row (`LOOP_ROW` handle, target-type)
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
  region padding is derived from it). The member-count pill (`.group-pill`, ▸/▾ +
  recursive step count `memberCount` — `group.members` only sees direct children)
  is ABSOLUTE on the top-right border in both states. COLLAPSED → leaf classes
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
  never dim. Icon from `groupIconFor` (host's icon; a LOOPED sub-workflow swaps to
  the amber loop glyph — the category line still says SUB-WORKFLOW; leaf kinds
  never swap). React Flow's default `node-group` wrapper styling is neutralized in
  index.css **including its `text-align: center`** — GroupNode owns the visual.
  Batch cards (and `.batched` leaves — unexpanded dynamic batches) draw a stacked
  DECK via pseudo-elements (the Tines stacked-copies look).
- **A SHELL batch group (no direct members) is never rendered.** The contract models
  "batched X" as batch-wrapping-X, but presentationally batch is a MODIFIER (deck +
  ×N badge), not a box to travel through (user decision 2026-06-10): a batched LEAF
  renders as a normal selectable node (its shell was the "▸ 0 nodes" card bug); a
  batched SUB-WORKFLOW is a sub-workflow WITH batch — the workflow group reparents
  past the shell (`effectiveParent`), becomes the host's representative
  (`groupsByHost` skips shells → edges/title/loop land on it), gets the deck from
  `hostNode.batch`, and clicking its collapsed card opens the sub-workflow body
  directly. Literal batches (real item-copy members) keep their container.
  `collapse.ts collapsibleGroupIds` excludes shells (they can't be toggled and must
  not inflate the N/M count).
- **IO is ONE node, with row-level focus.** An `input_wrapper`/`output_wrapper` group
  becomes a single Inputs/Outputs `ports` node (`PortsNode`) — a row per port, the IO
  member nodes are NOT emitted. Each row carries BOTH handles: a *target* (`portTargetHandle`
  — receives: input bound from parent, output written by a producer) and a *source*
  (`portHandle` — feeds: input → consumers, output → parent). A port bridges two scopes,
  so dropping either side silently loses the binding edges. Rows connect **SIDEWAYS in
  BOTH directions** (a row in a vertical table has no top/bottom anchor — the old TD
  top/bottom handles floated dots BETWEEN rows and edges dove into the stack). Each row
  actually renders FOUR handles: the base pair plus a mirrored pair (`iotr:`/`iol:`)
  stacked invisibly on the same dots; the post-layout `assignFacingSides` pass
  (`graph/portSides.ts`, wired in `useWorkflowGraph` after ELK) flips an edge to the
  side FACING its peer so a binding never wraps around the node — sibling
  wrap-arounds were the crossing tangle. The pass compares the HANDLE x
  (a row source exits the node's RIGHT edge), not node centers — a vertically-stacked
  pair still counts as "peer to the east". PARAM/OUTPUT rows are deliberately NOT
  flipped (user decision 2026-06-10): inputs-left/outputs-right is the node-graph
  convention and beats the shortest path; their wrap-arounds instead get a RAIL HINT
  (`assignDataRails`, same file): the data edge's middle segment centers in the clear
  gap between the endpoint boxes (data.railX/railY → DataEdge) so a wrap never hugs
  a node border (the blind handle-midpoint did). **Every edge carries its
  original endpoints (`data.from`/`data.to`)**, so `applyFocus` can reveal a *single*
  port's lines even though its edges re-anchor onto the shared ports node; clicking a row
  focuses that port id via the `InteractionContext`. Decision forks render as labeled
  border handles (`branchHandle`) in both densities; in beautiful, a revealed data line is
  labeled with what flows (`output_field → input_name`).
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
- **Packaging gotcha:** the bundle is gitignored and hatchling honors `.gitignore`, so
  `pyproject.toml` needs `[tool.hatch.build.targets.wheel] artifacts =
  ["src/pflow/ui/static/**/*"]` to ship it in the wheel — don't remove it.
  `web/package-lock.json` is committed (CI `npm ci`); `node_modules`/`dist` are not.
