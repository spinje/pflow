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
- **Smooth (bezier) edges.**

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

## Wanted / planned (NOT yet built)

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
- **Edge routing:** straight-ish beziers; in *dense* graphs, skip/back edges can overlap
  nodes. Fix = the smart edge-router above.
- The harness (`plan-to-code`) is an unusually hard case (deep nesting + loops + ~124 data
  edges); most workflows are far simpler and render clean today.
- **The visual layer cannot be verified without a real browser.** Use the real-browser loop
  (`.claude/skills/screenshot-pflow-web-ui`): `inspect` for boxes/geometry, zoomed screenshot crops for
  paint (a paint-vs-box bug — e.g. a viewBox mismatch rescaling the drawing — is invisible to rects).

## Deferred increments (from task-168 — architected-for, not built)

- **Live-run observability overlay** (Task 133 JSONL → node `status`). The contract already
  carries the structural `ref` join key + `api.ts` is the pluggable data seam.
- **Visual editing** (canvas → `.pflow.md` write-back). The per-param `SourceRef` is the seam.
