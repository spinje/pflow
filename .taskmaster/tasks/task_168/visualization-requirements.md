# Workflow Visualization — Requirements & Features

> The **what-must-hold** for the `pflow ui` viewer, distilled from the design
> conversation. The *journey / why* lives in `implementation/progress-log.md`; the
> *how* (architecture, mechanism, file map, gotchas) in `src/pflow/ui/CLAUDE.md` +
> `web/CLAUDE.md`. Keep this concise — it's a checklist, not prose; implementation
> detail belongs in `web/CLAUDE.md`, not here.

## Hard requirements (must hold — don't regress)

- **Edges land on the EXACT handle**, never a box border: a `${ref}` data line on its
  param row; a fork on its labeled outcome handle; an IO binding on its port row.
  (This is why we route edges ourselves, not via ELK's edge routing.)
- **No information loss in advanced mode.** Every node, edge, container, loop, batch,
  and `${ref}` is reconstructable. (Beautiful is a deliberate *projection* — less is OK.)
  Guarded at BOTH layers: Python (model→RF, `test_graph_react_flow_renderer.py`) and
  the frontend (`web/src/graph/lossless.test.ts` — RF→flow over synthetic shapes AND
  real committed contracts).
- **Inputs/outputs = ROWS on the workflow's OWN node, never a floating table**
  (2026-06-10): a ROOT wrapper is a standalone IO *card* (tile + INPUTS/OUTPUTS +
  workflow name + count pill; compact in beautiful, rows in advanced/focus-expanded;
  click SELECTS + opens the interface panel — the 2026-06-10 toggle died 2026-06-11
  when the card got a panel); a NESTED wrapper's rows live on the workflow GROUP —
  collapsed card: two-column area (inputs left, outputs right BOTTOM-ANCHORED, always
  ≥ 1 row below the inputs' start — the in→out diagonal IS the information); expanded
  region: inputs = LEFT SIDEBAR (the body lays out BESIDE it), outputs = bottom-right
  strip — shown WHENEVER the region is open, both densities (an open container hiding
  its inputs reads as "has none"; beautiful hides only the data LINES). Rejected:
  "last node beside the outputs strip" (multiple endings; collides with branch fan-out).
- **IO rows are STRICT-sided like param/output rows** — receive LEFT, feed RIGHT
  (no side-flipping). A region row bridges two scopes (outer = parent, inner = body) so
  it carries both handles; BOTH always render (a named-but-missing handle silently
  drops the edge) with the role-less side's dot hidden. Rows hidden (beautiful) → IO
  edges land node-level, never a handle that doesn't render.
- **Row-level focus:** clicking a single input/output **row** reveals just *that* port's
  connections + highlights the row (not the whole node). Focusing a consumer expands
  the IO owner so revealed lines land row-to-row. A ROOT card's row ALSO opens the
  interface panel with its entry marked (card = whole interface, row = one port —
  same panel both ways); nested rows stay focus-only.
- **Beautiful = control skeleton; data wiring is on-demand.** `${ref}` data-flow lines
  are hidden by default in beautiful; clicking a node/port/consumer reveals just its
  lines (progressive disclosure). Advanced shows them all.
- **Forks are explicit and labeled in BOTH densities:** LR — one labeled source handle
  per outcome on the border (n8n-Switch style); TD — forks fan from the icon column
  with the outcome label at the target's entry.
- **A continue-or-stop gate IS a decision; "end" is a real outcome (2026-06-10).**
  `is_decision` counts the reserved end route (`if ok: next="end" else: next="fix"` —
  the old ≥2-branch-labels rule missed 4 of the corpus's 6 deciders). The "end"
  outcome renders LAST as a faint fork row (LR) and its condition rides the END edge.
  A static `- next: end` stays a non-decision.
- **Branch conditions are extracted FAIL-CLOSED, never guessed.** `RFEdge.condition`
  comes from AST analysis of the decision node's code (`_branch_conditions`,
  react_flow.py); unsupported shapes ship `None` and the UI shows nothing — an absent
  label beats a wrong one. An outcome selected by multiple non-adjacent arms LISTS
  them verbatim (`"if ok · else"`) — still nothing inferred.
- **Two density modes from one model:** advanced (detailed cards + ports + params +
  wiring) and beautiful (compact, type-colored). Same data, different detail — not two
  apps.
- **Packaging:** base `pip install pflow` gains no bundle; `pflow[ui]` serves it
  offline; the wheel ships the built `static/` (hatchling `artifacts`); `pflow ui`
  without the extra prints the install hint.

## Design principles (decided — don't re-litigate)

- **A linear pipeline IS a line.** Don't force 2D with width-cutoff wrapping (rejected:
  arbitrary cuts + carriage-return edges). Sequence flows one direction; a *genuinely
  independent* fork fans out on its own. 2D space comes from real branching, not from
  folding a chain.
- **Layout reflects ALL structure** (control + data) even when data renders hidden —
  so a data-only node never floats. Density decides only what's *drawn*, not the layout.
- **Focus dim/reveal never re-layouts.** The ONE exception: focus-EXPANSION in
  beautiful (cards grow, so it must re-flow) — cached, animated, and camera-anchored so
  the clicked node never moves on screen. In advanced, focus stays a pure restyle.
- **Color is the frontend's** (payload is presentation-free): nodes colored by type;
  control edges blend source→target node colors; loop = amber, error = red, end =
  faint, data = teal.
- **Predicates baked in Python, visual policy in TS**
  (`is_decision`/`is_terminal`/`shadowed` ship as facts; the frontend decides
  treatment).
- **Rounded-orthogonal edges (the Tines language)** — axis-aligned runs, generous
  rounded turns, the rail just past the source, straight columns into targets.
  *(Supersedes the earlier bezier decision, 2026-06-09.)* The leftmost sibling keeps
  the straight trunk through forks AND merges; error branches order last (rightmost in
  TD / bottom in LR).
- **ELK must know where the handles are.** Control handles sit on the icon column
  (TD) / icon row (LR), not the node center — layout declares fixed ports there so
  chains align icon-to-icon. Without ports, "straight" chains render with a jog ELK
  can't see.
- **A table row connects SIDEWAYS** — direction moves the trunk, never a row's anchor.
  ALL rows are STRICT-sided (receive left, feed right — the convention beats the
  shortest path; user decision 2026-06-10). A wrap-around to reach a strict row is
  fine: its rail centers in the clear gap between the endpoint nodes, never hugging a
  border. **Parallel edges at a node ride LANES** (distinct stubs + rails) — EXCEPT a
  TD fork, whose branches leave one point and share the trunk rail by design.
- **Identity never mutates; behavior is border chrome.** A node's tile/icon/category
  always show its KIND; loop/batch modifiers (and future run status) ride the chip
  rail — never an icon swap, header badge, or category mark.

## Implemented

> Mechanism + invariants for everything below: `web/CLAUDE.md`. Per-feature decisions
> and rejected alternatives: the dated plan docs under `implementation/`.

- Catalog → per-workflow graph; URL params `workflow=` / `node=` / `focus=` (node,
  container name, or flat edge id) / `collapse=all|none` / `direction=` / `density=` —
  deep links are also how agents screenshot a specific state.
- Two densities + LR/TD toggle; collapse/expand containers; focus+context (dim
  non-incident); click-to-read panel (full params/prompts/code, source file:line).
- **IO interface panel (2026-06-11):** clicking a root INPUTS/OUTPUTS card selects
  it + opens `IoPanel` — the workflow's API written out (per input: type/required/
  default/description + consumer chips; per output: producer chip + the read field +
  source line; no "unused" claims — quiet ≠ unconsumed). Backed by a contract fix:
  inputs now ship `purpose` (description), `io.default`, and `required` with the
  TRUE default (the wire's old `False` default contradicted validator/executor —
  one Mermaid golden updated to the truthful `(string, required)` label). Card
  click = select everywhere (the io toggle died); root row click opens the panel
  with its entry marked.
- **Shared node CHIP + connection sections + hover-set (2026-06-11/12):** panel
  chips are mini node avatars (28px canvas tile + name, no box; category word on
  the tooltip) in ONE shared component (`web/src/components/Chip.tsx` —
  EdgePanel/IoPanel/ReadPanel all consume it); a nested io-port chip is
  scope-prefixed (`create-songs.concept`). Every ReadPanel ends with
  `references (N)` (upstream) + `referenced by (N)` (downstream) chip stacks
  (contract data-flow edges only — completes for free when
  scratchpads/param-ref-data-flow-edges lands; an empty direction → no section,
  the no-claims rule). HOVER = mark a set of canvas subjects, a PURE highlight
  (no focus change, no expansion, no camera move — user decision): a chip marks
  its node (an io-port chip rings the port's owner + lights its row); a canvas
  param/output/io ROW marks every node its edges touch (`rowTouches` over the
  flow edges — the resolved landings, never a re-derivation).
- **Tines/n8n visual language** (Phase A + follow-ups, 2026-06-09/10): one leaf
  component; neutral tile + brand/native-color icon (*tile is NOT solid-color —
  user-chosen*; node CARD border stays subtle — *do not thicken/recolor it*);
  gradient control edges, no arrowheads; rounded-orthogonal paths everywhere; icon
  connector flares + LR exit dot; error/end endpoint fades; beautiful is the default
  density; dark-themed minimap + zoom controls; geometry single-sourced in
  `metrics.ts`.
- **CONDITION + TRANSFORM pseudo-kinds:** a decision code node presents as CONDITION
  (orange, fork icon); a provably pure-reshape code node as TRANSFORM (cyan, shuffle
  icon), classified FAIL-CLOSED in Python (corpus: 10/20 unique code nodes classify,
  0 false positives); mutually exclusive by construction. *Considered + deferred:*
  Tines-style sub-modes (extract/dedupe/message-only) — intent inference from
  arbitrary Python breaks the fail-closed bar, and the card's `purpose` line already
  names the specifics; explode/implode map to pflow batch, "automatic" to the llm
  kind, delay/throttle have no pflow analog.
- **TRANSFORM Level 2 — output shape + per-key landing (2026-06-10):** cards show
  WHAT a node produces (`RFNode.output_shape` — code AST or claude-code/llm
  `output_schema`; the shape names its REAL port: result vs response); a sub-key ref
  (`${gen.result.ok}`) lands on its exact key row; quiet rows truthfully mean "no
  reader at all" (a param-text scan covers refs that form no edges; loop-condition
  refs are the unscanned residual); wholesale sends never decompose. Plan:
  `implementation/transform-l2-plan.md`.
- **Output-shape TYPING extended (2026-06-11):** result-dict key types resolve
  through module locals + Python-semantics certainties (`_TypeScope`,
  react_flow.py — corpus 17%→65% typed, still fail-closed: uncertain ships
  None); branch-assigned SAME-key literal dicts ship keys (the loop-gate
  pattern); schema-less llm/claude-code ship `field: str` (kind contract) →
  a quiet `→ response: str` row on every llm card. Output-row labels no
  longer truncate at the param-row 42% cap.
- **Registry types on observed rows (2026-06-11):** `RFGraph.kind_output_types`
  (the registry's parsed docstring interfaces, injected at the server seam —
  renderer stays registry-free) types shell/http/file/mcp rows that exist
  from reads (`→ stdout: str`); never creates a row; authored shapes win;
  `any` entries dropped. Fixture generator mirrors the server injection.
- **IO rows on the workflow node (2026-06-10):** root IO cards + collapsed-card
  two-column IO + region sidebar/outputs strip — replaced the floating ports table
  wholesale. Plan: `implementation/io-rows-plan.md`.
- **Root IO cards join the control skeleton:** synthesized `io-flow:` edges — Inputs
  card → entry step(s); control SINK step(s) → Outputs card (sinks derived from
  sequential/branch contract edges, NOT the contract's `is_terminal`, which counts
  data-flow: a final leaf feeding a declared output read non-terminal and the card
  floated, fixed 2026-06-11). Both densities; the cards behave like nodes (spine,
  ELK ports, flares).
- **LR icon-row spine + row ports (2026-06-10):** the control trunk passes straight
  THROUGH nodes in both directions; every visible row declares an ELK port;
  straightness priorities are WEIGHTS (trunk 100 out-votes binding bundles at 5 —
  measured). Spine + binding-bundle alignment test-pinned ≤1px.
- **SPINE alignment (2026-06-11):** `alignSpine` post-pass straightens pure
  sequential chains past port-less expanded regions (the "staircase");
  forks/merges/multi-terminal sinks break chains; a shift that would crowd a sibling
  is skipped.
- **Containers:** ONE object in two states — collapsed card with full leaf anatomy,
  expanded kind-tinted region with the IDENTICAL header (*nothing moves across the
  fold — user requirement*). Sub-workflow magenta `#e26ad8` (picked clear of mcp
  salmon-pink / claude-code violet), batch purple + stacked DECK. **Batch is a
  MODIFIER, not a box to travel through:** decorator-shell batch groups never render
  (`shellBatchIds` is the single copy of the rule; the discriminator is
  literal-vs-dynamic + child groups, NEVER memberlessness — the memberlessness rule
  made literal batches invisible, fixed 2026-06-11); a literal batch with expanded
  items keeps its container, rendered as the host's box. Containers SELECT on click
  (whole-UNIT focus + read panel via the host node; in beautiful, selection also
  expands the container's IO rows so revealed bindings land row-to-row — node-level
  they DEDUPE into one mislabeled line); the rail's count-expander and double-click
  are the only toggles. Plan: `implementation/container-select-plan.md`.
- **Batch/loop CHIP RAIL (2026-06-10):** behavior modifiers are 22px chips straddling
  the top border — loop = amber ↻; batch = `⧉ ×{count}` literal / `⧉ ×N` dynamic (the
  count is statically unknowable: the iterated source rides the tooltip, NEVER a
  guessed number; the future run overlay fills the real count); groups append the
  merged count-expander (round chip = info, square = button). The rail is the
  RESERVED home for live-overlay status chips (status joins leftmost). Plan:
  `implementation/batch-chip-rail-plan.md`.
- **Loops:** an orthogonal U wrapping the box, carrying the app's ONE arrowhead at
  the re-entry; a looped leaf with rows shows amber LOOP-RULE rows (the condition row
  is the U's landing; the cap on its OWN row — authored loop config, deliberately NOT
  presented as a data param); beautiful unexpanded = a bare quiet U (the ↻ chip
  telegraphs the loop); group anchors keep a floating pill in advanced only.
- **Branch presentation:** outcome labels at the target's entry; fork targets lay out
  in the code's chain order (first `if` leftmost — Steps-declaration order is
  irrelevant to a fork). *(Ordinal number prefixes were tried and removed same day.)*
  Conditions render where the outcome lives (TD: pill on the final approach into the
  target; LR: on the source's BranchPorts row), advanced always / beautiful on
  focus-expansion — and clicking a branch TARGET reveals just its own condition
  ("why was I reached?"). The read panel shows the full outcome → condition table.
- **Click-to-expand in beautiful (2026-06-09):** focusing a node expands it + its
  data-flow endpoints to the full advanced body in place; revealed lines land
  row-to-row and drop their floating label when they do; control-only neighbors stay
  compact.
- **Click perf + motion (user-accepted):** layout cache; ELK in a Web Worker with a
  10s watchdog (a silent worker can stall one layout, never hang the canvas);
  stale-paint guard (exactly one visible change per click); animated expansion
  transitions gated at `ANIMATE_MAX_NODES` (knobs in `useWorkflowGraph.ts`).
  *Rejected with evidence:* CSS-transition motion (edges compute from store positions
  and detach from gliding nodes); lane-tinted data lines + full node-color data
  gradients (same-endpoint bundles get identical gradients exactly where
  disambiguation is needed; the teal=data semantic dies) — the shipped treatment is
  the focus-directional fade (solid at the clicked end, hint toward the far end).
- **Collapse controls + overview default (2026-06-10):** toolbar `[⊟|⊞] N/M open`
  (hidden when a workflow has no containers; disabled states mark the extremes);
  workflows over `AUTO_COLLAPSE_NODE_BUDGET` (60) open fully collapsed —
  overview-first AND a faster first layout; `collapse=all|none` overrides; deep-link
  targets keep their ancestor chain expanded; collapse-all clears focus. Policy pure +
  tested: `graph/collapse.ts`.
- **Edge disambiguation:** rows connect sideways; LANES for data/branch/error edges
  (parallel bindings fan apart); dict-key `input_name` lands on the containing
  param's row; backward branch/error edges ride a BACK RAIL around both endpoint
  boxes; data wrap-arounds center their rail in the node gap.
- **Edges SELECT on click + EdgePanel (2026-06-10):** the clicked connection lights
  (bright + halo + elevated above the cards it crosses — the interactive answer to
  edge tunneling) while everything else dims; the panel explains the connection
  (5 variants, incl. the `shadowed` fact's first user surfacing); endpoint chips
  navigate with camera follow; `focus=<flat edge id>` deep-links. Selected-shade/halo
  shoot-lab pending; hover highlight is the gated follow-on. Plan:
  `implementation/edge-selection-plan.md`.
- **Resizable side panel (2026-06-11):** drag handle between canvas and panel (all
  three panels share `.read-panel`, width rides the `--panel-w` var); default 460px
  (was 360), clamped 300–860 and ≤70% viewport, persisted in localStorage,
  double-click resets. Drag verified end-to-end in real Chrome.

## Wanted / planned (NOT yet built)

- **LR merge alignment residual:** the merge target sits ~8px off the straight row in
  LR (no LR ports for that anchor class; side-centered handles *mostly* match ELK's
  center anchors). Add LR ports if it bothers.
- **Smart edge-router** — pathfind edges around nodes, handle-to-handle, so **skip
  edges** (a dependency jumping over intermediate nodes) and **backward/loop edges**
  don't draw through boxes or U-turn. React Flow has no node-avoidance (edges are
  endpoint-only); needs custom A*/orthogonal routing (or `react-flow-smart-edge`).
  Only needed for the *gnarly tail* (dense agentic harnesses); clean branchy/linear
  workflows already render fine.
- Visual polish: tune palette/spacing; possibly a TD-default for branchy flows;
  dashed (branch) edges can show a small dash-phase gap right at the connector stem
  tip (first dash starts a few px into the path — tune with `strokeDashoffset` if it
  bothers).

## Known limitations / honest constraints

- **React Flow renders ALL edges BEHIND nodes (one SVG layer).** This is the
  load-bearing constraint for the whole "edge flows *into* the icon" aesthetic: a
  stock edge is painted over at the node's box edge, so the line-into-the-icon must
  be **our own geometry** (the connector flare, an elevated-zIndex edge, or a
  transparent card). Don't expect a built-in to do it.
- **`useUpdateNodeInternals` is mandatory when handles move** (LR↔TD, stub
  appear/disappear) or edges/labels render from stale coords and fly to the origin.
  **`EdgeLabelRenderer` children need `position:absolute`** or they render as
  full-width bars. (Both were real bugs.)
- **Edge routing:** rounded-orthogonal (smoothstep), no node-avoidance; in *dense*
  graphs, skip/back edges can overlap nodes. Fix = the smart edge-router above.
- The harness (`plan-to-code`) is an unusually hard case (deep nesting + loops + ~124
  data edges); most workflows are far simpler and render clean today.
- **The visual layer cannot be verified without a real browser.** Use the
  real-browser loop (`.claude/skills/screenshot-pflow-web-ui`): `inspect` for
  boxes/geometry, zoomed screenshot crops for paint (a paint-vs-box bug — e.g. a
  viewBox mismatch rescaling the drawing — is invisible to rects).

## Deferred increments (from task-168 — architected-for, not built)

- **Live-run observability overlay** (Task 133 JSONL → node `status`). The contract
  already carries the structural `ref` join key + `api/` is the pluggable data seam.
- **Visual editing** (canvas → `.pflow.md` write-back). The per-param `SourceRef` is
  the seam.
