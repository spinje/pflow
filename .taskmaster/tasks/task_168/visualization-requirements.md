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

## Wanted / planned (NOT yet built)

- **Gradient edges** — stroke blends source-node-color → target-node-color (per-edge SVG
  `<linearGradient>` + custom edge; NOT a React Flow built-in). ~1h. The last cosmetic gap
  to match the n8n look.
- **Smart edge-router** — pathfind edges around nodes, handle-to-handle, so **skip edges**
  (a dependency jumping over intermediate nodes) and **backward/loop edges** don't draw
  through boxes or U-turn. React Flow has no node-avoidance (edges are endpoint-only); needs
  custom A*/orthogonal routing (or `react-flow-smart-edge`). Only needed for the *gnarly tail*
  (dense agentic harnesses); clean branchy/linear workflows already render fine.
- Visual polish: tune palette/spacing; possibly a TD-default for branchy flows.
- (Considered, currently covered by the read panel + consolidated ports) on-canvas
  "expand a node to advanced detail on click."

## Known limitations / honest constraints

- **Edge routing:** straight-ish beziers; in *dense* graphs, skip/back edges can overlap
  nodes. Fix = the smart edge-router above.
- The harness (`plan-to-code`) is an unusually hard case (deep nesting + loops + ~124 data
  edges); most workflows are far simpler and render clean today.

## Deferred increments (from task-168 — architected-for, not built)

- **Live-run observability overlay** (Task 133 JSONL → node `status`). The contract already
  carries the structural `ref` join key + `api.ts` is the pluggable data seam.
- **Visual editing** (canvas → `.pflow.md` write-back). The per-param `SourceRef` is the seam.
