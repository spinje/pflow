# Workflow Visualization — Requirements & Features

> The **what-must-hold** for the `pflow ui` viewer, distilled from the design
> conversation. The *journey / why* lives in `implementation/progress-log.md`; the
> *how* (architecture, file map) in `src/pflow/ui/CLAUDE.md` + (Phase 5) `web/CLAUDE.md`.
> Keep this concise — it's a checklist, not prose.

## Hard requirements (must hold — don't regress)

- **Edges land on the EXACT handle**, never a box border: a `${ref}` data line on its
  param row; a fork on its labeled outcome handle; an IO binding on its port row.
  (This is why we route edges ourselves, not via ELK's edge routing.)
- **No information loss in advanced mode.** Every node, edge, container, loop, batch,
  and `${ref}` is reconstructable. (Beautiful is a deliberate *projection* — less is OK.)
- **Inputs/outputs = one consolidated "ports" node per level** (a row + handles per
  port — the table-node pattern), NOT one node per port. Shown in **both** densities.
- **Every port row has BOTH handles** — a *target* (receives: input bound from parent,
  output written by a producer) and a *source* (feeds: input → consumers, output → parent).
  A port bridges two scopes; both roles must connect.
- **Row-level focus:** clicking a single input/output **row** reveals just *that* port's
  connections + highlights the row (not the whole node).
- **Beautiful = control skeleton; data wiring is on-demand.** `${ref}` data-flow lines are
  hidden by default in beautiful; clicking a node/port/consumer reveals just its lines
  (progressive disclosure). Advanced shows them all.
- **Forks are explicit:** a decision node shows one **labeled** source handle per outcome
  on its border (n8n-Switch style), each line to its target — in **both** densities.
- **Branch conditions are extracted FAIL-CLOSED, never guessed.** `RFEdge.condition`
  ("if len(items) > 5" / "else") comes from AST analysis of the decision node's code
  (`_branch_conditions`, react_flow.py); unsupported shapes ship `None` and the UI
  shows nothing — an absent label beats a wrong one.
- **Two density modes from one model:** advanced (detailed cards + ports + params + wiring)
  and beautiful (compact, type-colored). Same data, different detail — not two apps.
- **Packaging:** base `pip install pflow` gains no bundle; `pflow[ui]` serves it offline;
  the wheel ships the built `static/` (hatchling `artifacts`); `pflow ui` without the extra
  prints the install hint.

## Design principles (decided — don't re-litigate)

- **A linear pipeline IS a line.** Don't force 2D with width-cutoff wrapping (rejected:
  arbitrary cuts + carriage-return edges). Sequence flows one direction; a *genuinely
  independent* fork fans out on its own (ELK stacks sibling targets). 2D space comes from
  real branching, not from folding a chain.
- **Layout reflects ALL structure** (control + data) even when data renders hidden — so a
  data-only node never floats. Density decides only what's *drawn*, not the layout.
- **Focus never re-layouts** — it's a cheap restyle (dim + reveal), not a rebuild.
- **Color is the frontend's** (payload is presentation-free): nodes colored by type; control
  edges take their source node's color; loop = amber, error = red, end = faint, data = green.
- **Predicates baked in Python, visual policy in TS** (`is_decision`/`is_terminal`/`shadowed`
  ship as facts; the frontend decides treatment).
- **Rounded-orthogonal edges (the Tines language)** — axis-aligned runs, generous rounded turns
  (`METRICS.edgeRadius`), the rail just past the source, straight columns into targets.
  *(Supersedes the earlier "smooth bezier edges" decision, 2026-06-09 — user-driven from Tines
  references.)* The leftmost sibling keeps the straight trunk through forks AND merges; error
  branches order last (rightmost in TD / bottom in LR).
- **ELK must know where the handles are.** TD control handles sit on the ICON COLUMN, not the node
  center — layout declares fixed ports at `ICON_COL_X` so columns align icon-to-icon. Without
  ports, "straight" chains render with a jog ELK can't see.
- **A table row connects SIDEWAYS** — direction moves the trunk, never a row's anchor. PORTS rows
  (scope bridges, dual-handled) pick their side post-layout to FACE the peer; PARAM/OUTPUT rows are
  STRICT (inputs left, outputs right — the convention beats the shortest path; user decision
  2026-06-10). A wrap-around to reach a strict row is fine: its rail centers in the clear gap
  between the endpoint nodes (`assignDataRails`), never hugging a border. **Parallel edges at a
  node ride LANES** (distinct stubs + rails) — EXCEPT a TD fork, whose branches leave one point
  and share the trunk rail by design. Data lines: flat teal; solid-at-click hint-fade when focused.

## Implemented

- Catalog → per-workflow graph; `?workflow=` auto-load.
- Collapse/expand containers (re-layout); focus+context (dim non-incident); LR/TD toggle;
  advanced/beautiful density toggle.
- Click-to-read panel (full params/prompts/code, source file:line).
- Loop-back **arc** synthesized from `LoopSpec` (amber, condition+cap label; wraps a looped
  sub-workflow's container).
- Color-by-type nodes + source-colored edges; roomy spacing.
- Consolidated **Inputs/Outputs ports nodes** (rows, dual handles, row-level focus).
- **Fork handles** (labeled, both densities).
- **Branch labels at the target entry (2026-06-10):** in TD the outcome label sits on the
  edge just above its target's left side (bare text, shadow halo, +4px nudge); error pills
  stay mid-edge. Fork targets LAY OUT in the code's chain order (`orderForkSiblings`,
  layout.ts — first `if` leftmost; Steps-declaration order is irrelevant to a fork).
  *(Ordinal number prefixes were tried and removed same day.)*
- **Branch CONDITIONS on the edge (2026-06-10):** `RFEdge.condition` (AST-extracted,
  fail-closed) renders as an orange-tinted white-text pill — on the edge's lone rail run,
  or the final descent for the straight child (`conditionAnchor`, never on the rail
  crossing) — advanced always, beautiful while the condition node is focus-expanded; the
  read panel shows the full outcome → condition table.
- IO hidden-data-flow revealed on click (progressive disclosure).
- **Click-to-expand in beautiful (2026-06-09):** focusing a node expands it + its data-flow
  endpoints to the full advanced body in place; revealed lines land **row-to-row** (output row →
  param row) and drop the floating `stdout → data` label when they do (the rows name the fields);
  control-only neighbors stay compact. The ONE focus action that re-layouts (expansion changes
  sizes); the viewport pans so the clicked node never moves (camera anchoring). Expanded cards keep
  the top flare, drop the bottom one. Selection ring = the node's kind color. Deep-linkable via
  `?focus=<node_id>` (read-only, like `node=`) — also how agents screenshot the state.

### Phase A — Tines/n8n visual aesthetic (frontend-only, zero contract change; committed)

> Full journey + critical learnings: `implementation/progress-log.md` → "Phase A — Visual Redesign …
> HANDOFF" and the 2026-06-09 entries. Design/Flowise teardown: `research/visual-redesign-knowledge.md`.
> The connector flare is **done** (geometry rules: `web/CLAUDE.md` → "Icon connector flare").

- **One leaf component** `WorkflowNode` (RF `type:"node"`, density in `data`) — replaced the
  Detailed/Compact split. Card = category(type) + description(`purpose`||`node_id`, 2-line clamp);
  `node_id` on tooltip + read panel.
- **Option B node iconography:** neutral tile + brand/native-color icon (registry in `utils/icons.ts`;
  `llm` resolved from its `model` `provider/` prefix, default sparkle). *(Tile is NOT solid-color —
  user-chosen; don't re-litigate.)*
- **Gradient control edges** (`GradientEdge`, `userSpaceOnUse` source→target blend) at 3px, **no
  arrowheads**; branch dashed. ALL four control kinds route through it (error/end via the endpoint
  fades below); only data-flow stays CSS-stroked.
- **Type-colored card border + faint kind-tinted bg**; softened palette (neon green → calm teal).
  **Tile (image) border = full `--kind` 3px** (matches the edge); **node CARD border stays subtle —
  do not thicken/recolor it.**
- **Beautiful is the default density**; canvas `#0D0D0D`, dots `#272727`.
- **TD "through the icon":** control trunk + forks routed through the icon column; forks fan from
  `NODE_OUT` with the label on the edge (`BranchPorts` is **LR-only**). `hasIncoming`/`hasOutgoing`
  computed per node to drive connectors.
- **Icon connector flare** (TD/beautiful) — ✅ DONE: a control edge flows into the icon tile via a
  kind-colored cove, gap-free *by construction* (handle on the node border; flare = pure opaque
  decoration overlapping both ends; path/viewBox/box derived from ONE constant set). The rules that
  keep it gap-free: `web/CLAUDE.md` → "Icon connector flare".
- **Endpoint fades** — ✅ DONE: error/end edges blend into their endpoint node colors over ~26px
  (`gradientStops` in `GradientEdge`; all four control kinds now route through it).
- **Geometry single-source** — ✅ DONE: layout-coupled constants live in `web/src/graph/metrics.ts`
  and are injected as `:root` CSS vars; CSS never hardcodes them (kills the TS↔CSS drift bug class).
- **Frontend hygiene batch** — ✅ DONE (2026-06-09): memo'd RF components; lazy-ELK dynamic import
  (initial bundle 1.79 MB → 372 KB); explicit `defaultHidden` on EdgeData; class-name
  construction-site comments in CSS; ELK-size dev tripwire (scrollHeight, detailed-only).
- **Tines edge language** — ✅ DONE (2026-06-09): control edges rounded-orthogonal
  (`getSmoothStepPath` + near-source rail in `GradientEdge`); data edges built-in `smoothstep`
  (dotted, same radius); ELK fixed ports at the icon column (TD) so chains/end-sinks are dead
  straight and one branch continues the trunk; leftmost-straight priority; error branches last;
  TD layer spacing 80. Gotcha pinned in the progress log: `considerModelOrder.*` crashes elkjs
  under `INCLUDE_CHILDREN` — use `crossingMinimization.forceNodeModelOrder`.
- **Click perf + motion** — ✅ DONE (2026-06-09/10, user-accepted): layout cache (un-click/re-click
  instant — ELK measured ~150ms per layout on a 128-node flow); ELK runs in a Web Worker (no
  main-thread freeze; main-thread chunk is the silently-tested fallback); stale-paint guard (one
  visible change per click — killed the cached-click "shake"); **animated expansion transitions**
  (200ms easeOutCubic THROUGH the store so edges follow; camera pan eases in sync; gated
  `ANIMATE_MAX_NODES = 60` so large flows snap; `prefers-reduced-motion` respected). Knobs:
  `ANIMATE_MAX_NODES`/`ANIMATE_MS` in `useWorkflowGraph.ts`.
- **Collapse controls + overview default** — ✅ DONE (2026-06-10): toolbar `[⊟|⊞] N/M open`
  (buttons + count, user-picked via mockups; hidden when a workflow has no containers; disabled
  states mark the extremes); big workflows (> `AUTO_COLLAPSE_NODE_BUDGET` = 60 contract nodes)
  OPEN fully collapsed — overview-first AND a faster first ELK run; `collapse=all|none` URL
  override; `node=`/`focus=` deep-link targets keep their ancestor chain expanded; collapse-all
  clears focus. Policy is pure + tested: `graph/collapse.ts`.
- **Edge disambiguation batch** — ✅ DONE (2026-06-10, all user-caught): ports rows connect
  **sideways in both directions** (TD top/bottom row dots floated between rows) with FOUR
  handles/row + the post-layout `assignFacingSides` pass picking the side FACING the peer (PORTS rows only — param/output rows stay strict-sided; wrap rails center in the node gap via `assignDataRails`) (no more
  wrap-arounds — they were the crossing tangle); **LANES** for data/branch/error edges
  (`assignEdgeLanes` + `DataEdge` geometry: distinct stubs AND middle rails, so parallel bindings
  fan apart instead of overlapping pixel-exactly; LR fork rails stagger per lane — TD trunk rail
  stays shared by design); dict-key `input_name` lands on the **containing param's row** (was the
  node top); rail corners full-radius (`RAIL_OFFSET = 2×radius` — smoothstep clamps bends to half
  the segment); **focus-directional fade** (a revealed data line draws solid at the clicked node,
  fading a hint — `FADE_TO = 0.45` — toward the far end; replaces the rejected lane-tints and
  node-color gradients, judged confusing). CSS strokes NO edge kind — components own color; a
  regression to a built-in type renders invisibly (test-pinned).
- **Sub-workflow/batch container redesign** — ✅ DONE (2026-06-10, user-picked via shoot-lab):
  ONE object in two states. COLLAPSED = a real node card (leaf anatomy via `.node.compact`
  classes: tile + frame + icon, kind category, name, count pill `▸ N nodes` = recursive STEP
  count, not `members.length`); EXPANDED = a region whose header is the card's identity shrunk
  (mini-tile + icon + kind category + title + right-aligned count pill), kind-tinted border.
  Sub-workflow kind color = **magenta `#e26ad8`** (clear of mcp salmon-pink / claude-code violet);
  batch keeps `--batch` purple. New `subworkflow.svg` (frame + mini-graph) + `loop.svg` glyphs; a
  **LOOPED sub-workflow swaps its tile icon to the amber loop glyph** (category still says
  SUB-WORKFLOW — behavior telegraphed at zero identity cost; leaf kinds never swap). Collapsed
  cards join the TD machinery: ELK icon-column ports (straight trunks — they jogged before) +
  connector flares (incidence computed over FLOW edges post-re-anchoring; internal edges don't
  count) + focus-dimming like a leaf (expanded regions still never dim). **Batch cards get a
  stacked DECK** (two kind-tinted layers peeking below; also on `.batched` leaves = unexpanded
  dynamic batches). React Flow's default `node-group` wrapper styling is neutralized in CSS.
  **Header parity across the fold (follow-up, same day, user requirement):** opening a container
  changes NOTHING in its header — both states render the SAME `.node-header` markup (full-size
  tile, leaf typography/positions, left-aligned — RF's group wrapper centers text, neutralized);
  `groupHeaderH == nodeHeaderH`; the count pill is ABSOLUTE on the top-right border (▸/▾) in both
  states; the expanded region's handles stay on the icon column with the TOP flare, so the trunk
  flows into the region's tile like any node (no bottom flare — the tile is at the top; no ELK
  port — a compound port crashes elkjs under INCLUDE_CHILDREN, test-pinned).
  **Batch is a MODIFIER, not a box to travel through** (follow-up, same day): a batch group
  with NO direct members is a decorator SHELL and never renders — a batched leaf is a normal
  selectable node (deck + ×N badge; the shell was the "▸ 0 nodes" card), and a batched
  sub-workflow IS a sub-workflow WITH batch (the workflow group reparents past the shell,
  takes edges/title/deck, and its collapsed card opens the sub-workflow body in one click).
  Literal batches (real item copies) keep their container.
- **Loop arcs → orthogonal U** — ✅ DONE (2026-06-10): `LoopEdge` is `getSmoothStepPath` with a
  wrap rail from the post-layout `assignLoopRails` pass (portSides.ts; TD → rail right of the
  box, LR → above; the rail is LOAD-BEARING — a self-loop's smoothstep midpoint runs straight
  back through the node). Full `--edge-stroke` weight; the U carries the app's ONE arrowhead
  (own `<polygon>`, CSS `--loop` fill — RF markers can't take CSS vars) at the re-entry point —
  a loop is the only edge whose direction layout doesn't imply.
- **The ↻ LOOP-RULE ROWS** — ✅ DONE (2026-06-10, user-designed): a looped LEAF whose body rows
  render (advanced / focus-expanded) grows amber loop-rule rows — its authored loop config
  presented as rows, deliberately NOT a fake data param (it parameterizes the loop mechanism):
  the CONDITION row (the U's arrow lands on it — "iteration re-enters under this rule") + the
  CAP (`≤ ${max_…}`) on its OWN row (one row truncated both operands; user-caught). The floating
  label drops (the rows hold it, like data lines on row-landing). Beautiful unexpanded = a BARE
  quiet U into NODE_IN, no label — but the card's category line carries an amber **↻ mark**
  (`CLAUDE CODE ↻`) so a looped leaf telegraphs in any state (leaves keep their kind icon; only
  sub-workflows swap to the loop glyph). GROUP anchors (no rows) keep the floating pill in
  advanced only (bottom run TD / top rail LR; opaque bg; never zIndex-elevate the loop edge —
  it would paint over its own label). The read panel always carries the full spec.

## Wanted / planned (NOT yet built)

- **LR merge alignment residual:** the merge target sits ~8px off the straight row in LR (no LR
  ports; side-centered handles *mostly* match ELK's center anchors). Add LR ports if it bothers.
- **Smart edge-router** — pathfind edges around nodes, handle-to-handle, so **skip edges**
  (a dependency jumping over intermediate nodes) and **backward/loop edges** don't draw
  through boxes or U-turn. React Flow has no node-avoidance (edges are endpoint-only); needs
  custom A*/orthogonal routing (or `react-flow-smart-edge`). Only needed for the *gnarly tail*
  (dense agentic harnesses); clean branchy/linear workflows already render fine.
- Visual polish: tune palette/spacing; possibly a TD-default for branchy flows; dashed (branch)
  edges can show a small dash-phase gap right at the connector stem tip (first dash starts a few px
  into the path — tune with `strokeDashoffset` if it bothers).
- (Considered, currently covered by the read panel + consolidated ports) on-canvas
  "expand a node to advanced detail on click."

## Known limitations / honest constraints

- **React Flow renders ALL edges BEHIND nodes (one SVG layer).** This is the load-bearing
  constraint for the whole "edge flows *into* the icon" aesthetic: a stock edge is painted over at
  the node's box edge, so the line-into-the-icon must be **our own geometry** (the connector stub, or
  an elevated-zIndex edge, or a transparent card). Don't expect a built-in to do it.
- **`useUpdateNodeInternals` is mandatory when handles move** (LR↔TD, stub appear/disappear) or
  edges/labels render from stale coords and fly to the origin. **`EdgeLabelRenderer` children need
  `position:absolute`** or they render as full-width bars. (Both were real bugs this session.)
- **Edge routing:** rounded-orthogonal (smoothstep), no node-avoidance; in *dense* graphs,
  skip/back edges can overlap nodes. Fix = the smart edge-router above.
- The harness (`plan-to-code`) is an unusually hard case (deep nesting + loops + ~124 data
  edges); most workflows are far simpler and render clean today.
- **The visual layer cannot be verified without a real browser.** Use the real-browser loop
  (`.claude/skills/screenshot-pflow-web-ui`): `inspect` for boxes/geometry, zoomed screenshot crops for
  paint (a paint-vs-box bug — e.g. a viewBox mismatch rescaling the drawing — is invisible to rects).

## Deferred increments (from task-168 — architected-for, not built)

- **Live-run observability overlay** (Task 133 JSONL → node `status`). The contract already
  carries the structural `ref` join key + `api.ts` is the pluggable data seam.
- **Visual editing** (canvas → `.pflow.md` write-back). The per-param `SourceRef` is the seam.
