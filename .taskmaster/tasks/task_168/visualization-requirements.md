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
- **Inputs/outputs = ROWS on the workflow's OWN node, never a floating table**
  (supersedes the consolidated "ports" node, 2026-06-10): a ROOT wrapper is a standalone
  IO *card* (node anatomy: tile + INPUTS/OUTPUTS + workflow name + `"14 inputs"` pill;
  compact in beautiful, rows in advanced/focus-expanded — the leaf showBody rule); a
  NESTED wrapper's rows live on the workflow GROUP — collapsed card: two-column area
  (inputs left, outputs right BOTTOM-ANCHORED, always ≥ 1 row below the inputs' start —
  the in→out diagonal IS the information; equals the original one-row stagger at
  balanced counts, ends at the bottom-right corner when inputs dominate; rows in
  advanced/focus-expanded); expanded region: inputs = LEFT
  SIDEBAR (the body lays out BESIDE it, via ELK left padding), outputs = bottom-right
  strip, full-width dividers — shown WHENEVER the region is open, both densities (an
  open container hiding its inputs reads as "has none"; beautiful hides only the data
  LINES). The root IO card CLICK TOGGLES its rows (expansion = its open state). Rejected:
  "last node beside the outputs strip" (multiple endings; collides with branch fan-out).
- **IO rows are STRICT-sided like param/output rows** — receive LEFT, feed RIGHT
  (no side-flipping; `assignFacingSides` + the mirrored handles died with the table).
  A region row bridges two scopes (outer = parent, inner = body) so it carries both
  handles; BOTH always render (a named-but-missing handle silently drops the edge) with
  the role-less side's dot hidden. Rows hidden (beautiful) → IO edges land node-level,
  never a handle that doesn't render.
- **Row-level focus:** clicking a single input/output **row** reveals just *that* port's
  connections + highlights the row (not the whole node). Focusing a consumer expands the
  IO owner so revealed lines land row-to-row (`expandTargets` is owner-aware).
- **Beautiful = control skeleton; data wiring is on-demand.** `${ref}` data-flow lines are
  hidden by default in beautiful; clicking a node/port/consumer reveals just its lines
  (progressive disclosure). Advanced shows them all.
- **Forks are explicit:** a decision node shows one **labeled** source handle per outcome
  on its border (n8n-Switch style), each line to its target — in **both** densities.
- **A continue-or-stop gate IS a decision; "end" is a real outcome (2026-06-10).**
  `is_decision` counts the reserved end route (`if ok: next="end" else: next="fix"` —
  the model's old ≥2-branch-labels rule missed 4 of the corpus's 6 deciders). The
  "end" outcome renders LAST as a faint fork row (LR) and its condition rides the
  END edge (pill on the final approach into the end dot in TD; read-panel row
  `→ end`). A static `- next: end` stays a non-decision.
- **Branch conditions are extracted FAIL-CLOSED, never guessed.** `RFEdge.condition`
  ("if len(items) > 5" / "else") comes from AST analysis of the decision node's code
  (`_branch_conditions`, react_flow.py); unsupported shapes ship `None` and the UI
  shows nothing — an absent label beats a wrong one. An outcome selected by multiple
  non-adjacent arms LISTS them verbatim (`"if ok · else"`) — still nothing inferred.
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
- **A table row connects SIDEWAYS** — direction moves the trunk, never a row's anchor. ALL rows
  are STRICT-sided (receive left, feed right — the convention beats the shortest path; user
  decision 2026-06-10; the old ports-table's post-layout facing-sides flip died with the table —
  IO rows on the boundary have structural sides). A wrap-around to reach a strict row is fine:
  its rail centers in the clear gap between the endpoint nodes (`assignDataRails`), never hugging
  a border. **Parallel edges at a node ride LANES** (distinct stubs + rails) — EXCEPT a TD fork,
  whose branches leave one point and share the trunk rail by design. Data lines: flat teal;
  solid-at-click hint-fade when focused.

## Implemented

- Catalog → per-workflow graph; `?workflow=` auto-load.
- **TRANSFORM pseudo-kind (2026-06-10):** a code node whose AST provably only
  reshapes inputs into `result` (no effects, no `next`) presents as TRANSFORM —
  cyan `#5fd4dd` + shuffle glyph (user-picked via shoot-lab). Classified
  FAIL-CLOSED in Python (`RFNode.is_transform`, `_is_transform_code`); the
  frontend reads the fact (it can't re-derive — needs the AST). Corpus: 10/20
  unique code nodes classify, 0 false positives. Mutually exclusive with
  CONDITION by construction (a `next`-setter is never a transform). *Considered
  + deferred:* Tines-style sub-modes (extract/dedupe/message-only) — intent
  inference from arbitrary Python breaks the fail-closed bar, and the card's
  `purpose` line already names the specifics; explode/implode map to pflow
  batch, "automatic" to the llm kind, delay/throttle have no pflow analog. The
  higher-value refinement is Level-2 result-shape extraction (literal `result`
  dict keys → real output rows; 6/10 corpus transforms qualify).
- Collapse/expand containers (re-layout); focus+context (dim non-incident); LR/TD toggle;
  advanced/beautiful density toggle.
- Click-to-read panel (full params/prompts/code, source file:line).
- Loop-back **arc** synthesized from `LoopSpec` (amber, condition+cap label; wraps a looped
  sub-workflow's container).
- Color-by-type nodes + source-colored edges; roomy spacing.
- **IO rows on the workflow node (2026-06-10)** — replaced the consolidated ports
  table wholesale: root IO cards (compact-in-beautiful — kills the floating 14-row
  table on input-heavy workflows), collapsed-card two-column IO, region sidebar +
  outputs strip (ELK per-group padding + `nodeSize.minimum`, TD-transposed gotcha
  pinned). Deleted: `PortsNode`, `assignFacingSides`, the `iotr:`/`iol:` mirror
  handles. Shared `PortRows` renderer; row-level focus preserved.
- **Root IO cards join the control skeleton (2026-06-10):** synthesized `io-flow:`
  control edges — Inputs card → entry step(s) (no incoming control; first-root-step
  fallback on a cycle), terminal step(s) → Outputs card — in BOTH densities. The
  cards behave like nodes: ELK lays them into the spine, TD icon-column ports +
  connector flares, gradient blends IO teal ↔ the step's kind color. Pure visual
  policy, not contract edges; the per-port data lines are unchanged.
- **LR ICON-ROW SPINE + ROW PORTS (2026-06-10):** LR control handles sit on the
  ICON ROW (`ICON_ROW_Y` — in left / out right at the SAME height; the trunk passes
  straight THROUGH the node) with fixed ELK ports + a LEFT tile flare (the TD
  connector language rotated) + a kind-colored EXIT DOT on the right border (E1,
  user-picked via lab — no right flare: the tile is at the card's left; hasOutgoing
  is handle-aware so LR deciders light no icon-row exit).
  Different-height cards sit header-to-header on ONE line. Every visible row also
  declares a port (`rowAnchorsFor`); priorities are WEIGHTS: trunk 100 (a 13-binding
  bundle at 5 out-voted 10 — measured), bindings 5. The io card's rows carry an
  INPUTS/OUTPUTS caption for GRID PARITY with group-card columns, so spine-aligned
  card pairs ALSO get straight binding bundles (was a constant 52px jog); leaf↔card
  bindings have no parity guarantee (honest geometry). All test-pinned ≤1px.
- **Containers SELECT on click; toggle = corner button (design D, 2026-06-10):**
  a container's body focuses + opens the read panel (host node) like any node; the
  `.group-toggle` corner button (A1 arrows-out/in, full-at-rest, both states) and
  double-click are the only toggles. Selecting lights the whole UNIT (descendants +
  internal wiring + external bindings; hidden data lines reveal in beautiful) AND,
  in beautiful, expands the container's own IO ROWS + each binding's far end
  (revealed lines land row-to-row — node-level they DEDUPE into one mislabeled
  line; same-day user catch). IO-touching data lines never carry a floating label
  (the rows name the fields). Batched leaves get no button (nothing to open). Deep
  links select containers by name (`focus=<sub-workflow name>` → representative
  group). Plan + decisions: `implementation/container-select-plan.md`.
- **Fork handles** (labeled, both densities).
- **Branch labels at the target entry (2026-06-10):** in TD the outcome label sits on the
  edge just above its target's left side (bare text, shadow halo, +4px nudge); error pills
  stay mid-edge. Fork targets LAY OUT in the code's chain order (`orderForkSiblings`,
  layout.ts — first `if` leftmost; Steps-declaration order is irrelevant to a fork).
  *(Ordinal number prefixes were tried and removed same day.)*
- **Branch CONDITIONS (2026-06-10):** `RFEdge.condition` (AST-extracted, fail-closed)
  renders where the outcome lives, advanced always / beautiful while the condition node
  is focus-expanded — and clicking a branch TARGET reveals just its own condition
  ("why was I reached?": TD → the edge pill above the target; LR → on the source's
  BranchPorts row — an entry pill overlapped the clicked card); the read panel shows
  the full outcome → condition table. **TD:** an
  edge-colored white-text pill (target node's color, the standard pill rule) on the
  FINAL APPROACH into its target, stacked above the outcome label (`conditionAnchor` —
  one pill per target entry; path-midpoint anchors collided on shared rails,
  measured). **LR:** quiet text ON the BranchPorts row beside its
  outcome pill (`LeafData.branchConditions`) — mid-path pills clipped under cards /
  floated on backward wraps (user-caught); a re-anchored branch (collapsed source, no
  rows) keeps the edge pill. When the source's rows show, LR targets also get their
  outcome name at their entry (TD-style bare text, above the line) so a row's line
  is findable without tracing it.
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
- **Edge disambiguation batch** — ✅ DONE (2026-06-10, all user-caught): rows connect
  **sideways** (TD top/bottom row dots floated between rows — fixed) *(the four-handle +
  `assignFacingSides` facing-side machinery from this batch was DELETED same day with the
  ports table — IO rows on the workflow node are strict-sided; wrap rails center in the
  node gap via `assignDataRails`)*; **LANES** for data/branch/error edges
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
- **Backward branch/error edges ride a BACK RAIL** — ✅ DONE (2026-06-10, user-caught):
  a loop-back to an earlier node used smoothstep's stock wrap, U-turning at the ~20px
  stub right at the source handle — sibling loop-backs knotted into curls (check-groups,
  LR). `assignBackRails` (portSides.ts, 4th post-layout pass) routes them around both
  endpoint boxes — LR below (the loop U owns above), TD left (the loop rail owns the
  right) — lane-staggered; GradientEdge prefers the rail over its railCenter default.
  Sequential edges deliberately untouched. Third-party node avoidance stays the smart
  edge-router's job.
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

- **Batch/loop CHIP RAIL (2026-06-10, user-picked via 3-round shoot-lab):** behavior
  modifiers are 22px tinted chips straddling the card's top border (ChipRail.tsx) —
  loop = amber round ↻, batch = purple capsule `⧉ ×{count}` (literal) / `⧉ ×N`
  (dynamic — the count is statically unknowable; the iterated source rides the
  tooltip, NEVER a guessed number; the future run overlay fills the real count).
  Groups append the merged COUNT-EXPANDER `[25 ⤢]` (count pill + corner button
  became ONE rounded-square element — round = info, square = button; "nodes" word
  + ▸ chevron died). RETIRED: the header batch badge (squeezed the description,
  duplicated the deck), the category-line ↻ mark, the looped-sub-workflow tile-icon
  swap (identity never mutates — behavior is border chrome). The io card's count
  pill restyled to the same chip language. The rail is the RESERVED home for
  live-overlay status chips (status joins leftmost). Deck + loop-rule rows + read
  panel unchanged. Plan: `implementation/batch-chip-rail-plan.md`.

- **TRANSFORM Level 2 — output shape + per-key landing (2026-06-10):** a
  node's card shows WHAT it produces (`RFNode.output_shape`; its `field` names
  the port it describes — where that kind actually writes). Sources: code
  nodes via AST (the authored `result:` annotation + literal-dict keys w/
  types, FAIL-CLOSED: mutations/multi-assign/`result.update()` ship
  `keys=None`, never a partial list; ships for ALL code nodes, not just
  transforms), and structured claude-code/llm via their `output_schema`
  (authored truth, object schemas only — claude-code's value lands in
  `result`, llm's in `response`, and the shape names the RIGHT one). A sub-key
  ref (`${gen.result.ok}`) lands on its EXACT key row (`RFEdge.output_path` —
  first segment only, D7; deeper = read panel). Row composition (`outputRowsFor`,
  flow.ts) = authored ∪ observed: bare read → parent row + nested `· key` rows
  (D2); no bare read + keys known → flat `→ result.ok` full-path rows (D3);
  quiet rows = no reader at all (D4 — plain-param refs form no edges, so a
  frontend param-text scan (`scanParamReads`) merges sibling prompt/command
  reads into the observed set; quiet stays truthful; the scan never creates
  rows or lines — loop-condition refs are the unscanned residual). Wholesale
  sends never decompose (D6). ONE row list drives render/height/LR-ports/
  landing by construction. Mermaid byte-identical (`Edge.output_path` is
  `compare=False` — load-bearing, see graph/CLAUDE.md). Plan:
  `implementation/transform-l2-plan.md`.

- **Edges SELECT on click + EdgePanel — ✅ DONE (2026-06-10, user-driven; plan + 4-lens
  review: `implementation/edge-selection-plan.md`):** clicking any edge focuses the
  CONNECTION — bright same-hue variant (`--data-edge-selected`, lab-tunable) + halo
  under-stroke + zIndex elevation above the cards it crosses (the interactive answer to
  edge tunneling), endpoints lit, all else dims (incl. label pills via
  `EdgeData.dimmed` — they previously glowed over a dimmed canvas), own label
  suppressed. The read panel explains the connection (5 variants: data with the
  authored `${ref}` highlighted + file:line, branch/decision-end with the marked
  outcome table, error semantics, static end, sequential incl. the `shadowed` fact's
  first user surfacing); endpoint chips navigate (host→representative group) or
  disable when hidden. `loop:` arcs redirect to their anchor; `io-flow:` edges restyle
  only. Beautiful: selecting a data edge expands both endpoints so the line lands
  row-to-row. `focus=<flat edge id>` deep-links work (collapse protects both
  endpoints' chains); RF native selection neutralized (incl. Backspace-delete).
  Selected-shade/halo shoot-lab pending; hover highlight is the gated follow-on.

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
