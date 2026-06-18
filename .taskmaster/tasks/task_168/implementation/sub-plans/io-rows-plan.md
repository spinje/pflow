# IO Rows — workflow inputs/outputs as node anatomy (plan)

> **Goal:** delete the consolidated "ports" table node; a workflow's declared inputs/outputs render
> as ROWS on the workflow's own node representation, following the exact leaf-row conventions that
> already exist. Frontend-only — **zero Python contract change** (verified: names via `ref.node_id`,
> level ownership via wrapper `parent` → workflow group, `required`/`data_type` in `io`, all four
> edge directions present; output descriptions already ride `purpose`, just never surfaced).
>
> Design settled with the user via shoot-lab mockups 2026-06-10 (`/tmp/io-rows-lab/index.html`,
> final = v4 + 8px more padding). Decisions below are LOCKED — don't re-litigate.

## The locked design

1. **Root level** — two standalone IO cards (the floating 14-row table dies):
   - Real node anatomy: tile + icon, category `INPUTS`/`OUTPUTS` (teal, the data color), title =
     the workflow name. Count pill top-right: `14 inputs` / `2 outputs` (not bare `14`).
   - Beautiful = compact 68px card. Advanced / focus-expanded = single-column rows:
     `name` + required `*` (inputs only — outputs never carry required) + faint `data_type`.
     Output rows get the description (`RFNode.purpose`) as tooltip.
2. **Collapsed sub-workflow/batch card** — when rows visible, grows a two-column row area under
   the header: inputs left (top-aligned), outputs right **staggered one row down — ALWAYS**
   (`rows = max(nIn, nOut + 1)`; the in→out diagonal is the information, even at equal counts).
   Small col labels `INPUTS` / `OUTPUTS`. Beautiful unfocused = today's compact card, unchanged.
3. **Expanded region** — inputs = **left sidebar** under the header (NOT a top strip: the body's
   first layer starts beside it — implemented as ELK left padding, so it needs no per-node
   forcing and works for branches/multi-starts/LR identically). Outputs = **bottom-right strip**.
   Both section dividers run the FULL region width, touching the border (no gap); body content
   pads off both dividers (~14px + the user's extra 8px). Outputs stay at the bottom (rejected:
   symmetric "last node beside outputs" — multiple endings, tiny win, collides with branch fan-out).
   Collapsed↔expanded parity: inputs are the left column in BOTH states (they don't move on open);
   outputs stretch from upper-right column to bottom strip (the diagonal expanding around the body).
4. **Strict sides, structural** — input rows: target handle on the LEFT border; output rows: source
   on the RIGHT. The region rows are dual-handled (outer = parent scope, inner = body scope) but the
   side is knowable at build time, so **`assignFacingSides` and the mirror handle schemes
   (`iotr:`/`iol:`) are DELETED**, not migrated.
5. **Row visibility** = the leaf rule verbatim: `detailed || expandedSet.has(ownerId)`. Beautiful
   stays a control skeleton; clicking reveals (focus-expansion already re-layouts — no new mechanism).
6. **Row focus preserved**: clicking a row → `focusPort(ioNodeId)`; reveal works through the
   existing `data.from`/`data.to` original-endpoint mechanism, untouched.

## What this deletes (the simplicity payoff)

- `components/nodes/PortsNode.tsx` + `ports` registration (`components/nodes/index.ts:5,15`)
  + minimap `case "ports"` (`GraphView.tsx:49-50`).
- ALL `.ports*` CSS (`index.css:518-580`) + `METRICS.portsHeaderH` / `--ports-header-h`
  (`metrics.ts:13,48`; sole consumer is `.ports-header`).
- `assignFacingSides` (`portSides.ts:73-99` + header doc 4-15) + `HYSTERESIS` + its 6 tests
  (`portSides.test.ts:46-98`). Keep `assignDataRails`/`assignBackRails`/`assignLoopRails`.
- Mirror handles: `PORT_TARGET_R`/`PORT_SOURCE_L` (`handles.ts:37-38`), constructors
  `portHandleLeft`/`portTargetHandleRight` (:56-57), `isPortTarget`/`isPortSource`/
  `mirrorPortTarget`/`mirrorPortSource` (:63-66), their `handleType` entries (:77,:86).
- `flow.ts`: `PortsData` (:78-85), the ports-node emission block (:463-489), `PORTS_WIDTH`/
  `PORTS_HEADER_HEIGHT` (:172-173).

Keep: `io:`/`iot:` schemes + `portHandle`/`portTargetHandle` (already type-registered — the row
handle ids are unchanged, keyed by io-node id), `Port` type (gains `description: string | null`),
`ROW_HEIGHT`/`rowH` (shared with param/branch rows).

## Phase 1 — `flow.ts`: ownership + emission + edges + sizes

**1a. Wrapper → owner mapping.** Replace `ioNodeToPortsNode` (:346-353) with `ioNodeToOwner`:
- Root wrapper (`wrapper.parent === null`): owner = a NEW synthetic IO-card node, **id =
  `wrapper.id`** (preserves `expandTargets`/`focusPort` deep-link semantics for free — the
  wrapper-id-reuse trick today, `flow.ts:472-473`).
- Nested wrapper: owner = **the workflow group node** (`effectiveParent(wrapper.parent)` — the
  same shell-batch-aware resolution as today, :470-476).
- Keep the `members.length > 0` / `io != null` filters (:343-353). IO member nodes stay
  suppressed (:411); wrapper groups stay suppressed (:377).

**1b. Port lists.** `wrapperPorts(wrapper)` → `Port[]` from members, as today (:465-468) plus
`description: m.purpose || null` (outputs carry it; inputs are always `""` → null) and keep
`required` rendering inputs-only.

**1c. New node type `io`** (root cards): `Node<IOCardData, "io">` in the `FlowNode` union (:156).
`IOCardData = { kind: "input" | "output"; ports: Port[]; workflowName: string; density; direction;
expanded: boolean; dimmed: boolean; focused: boolean; focusedPortId: string | null }`. Emit one per
root wrapper. `workflowName` comes from the view (GraphView knows the loaded workflow id — pass
through `BuildOptions`).

**1d. Group data gains IO.** `GroupData` += `inputs: Port[]; outputs: Port[]; rowsVisible: boolean;
focusedPortId: string | null`. Populate from the wrappers whose owner is that group.

**1e. Sizing** (all constants in/derived from `metrics.ts`, §Phase 3):
- IO card: compact → `COMPACT_WIDTH × HEADER_HEIGHT` (230×68); rows visible →
  `IO_CARD_WIDTH (260) × (HEADER_HEIGHT + IO_LABEL_H? — no label on single-column cards —
  + n×ROW_HEIGHT + ROW_PADDING)`. No col label on root cards (the category line already says it).
- Collapsed group card with rows visible: `GROUP_IO_WIDTH (380) ×
  (HEADER_HEIGHT + IO_LABEL_H + max(nIn, nOut + 1)×ROW_HEIGHT + ROW_PADDING)`. Without: today's
  fixed 260×68 (:404). Omit a column entirely when that side has 0 ports; if BOTH are 0 (no
  declared IO) nothing changes at all.
- Expanded region: size comes from ELK padding (Phase 3), not a preset.

**1f. Edge handles.** `sourceHandleFor`/`targetHandleFor` (:676-738) IO branches: row handle
(`portHandle(ioId)`/`portTargetHandle(ioId)`) when the edge endpoint's owner is the rendered
anchor AND `rowsVisible(owner)`; else `NODE_OUT`/`NODE_IN`. `rowsVisible` for an owner id =
`detailed || expandedSet.has(ownerId)` — extend the existing closure (:520) to cover group/io ids.
`renderAnchor` IO branch (:497-504): io node → owner → `outermostCollapsed` chain as today.
NOTE the H6 rule stands: degraded endpoints land node-level, never drop; `data.from`/`data.to`
(:807-808) unchanged.

**1g. `expandTargets`** (:222-244): replace the wrapper special-case (:225-228) with owner-aware
logic: (i) focus = a port id or an io-card/wrapper id → expand the owner + the consumers/producers
on the other end of its ports' data edges (current behavior, new owner); (ii) focus = a leaf with a
data edge whose far end is an IO port → include that port's OWNER in the expansion set (so the line
can land row-to-row — the per-endpoint silent-drop rule, :536-537, then does the rest). `expandable`
(:231-234) drops its IO-port exclusion in favor of the owner mapping; group owners ARE expandable now.

**1h. `applyFocus`** (:836-879): move the `focusedPortId` write from ports nodes (:860-866) to
group/io node data; keep identity preservation (only touched nodes get new objects).

## Phase 2 — components + CSS

- **`PortRows`** (new, `components/nodes/PortRows.tsx`): ONE column of port rows for a given
  `kind` — row = optional dot-handle left (`portTargetHandle`, inputs) / right (`portHandle`,
  outputs), name, `*`, faint type; `title` tooltip with name/type/required/description; row click →
  `focusPort(port.id)` with `stopPropagation` (the `PortsNode.tsx:42-45` pattern); `focused` class
  via `focusedPortId`. **Region variant renders BOTH handles per row** (outer + inner) — a prop,
  not a fork: `dual?: boolean`.
- **`IOCardNode`** (new): `.node` anatomy (header/tile/category/title + count pill) + a single
  `PortRows` when rows visible. Register `io` in `nodeTypes` (must be `memo()`'d — registry rule);
  `useUpdateNodeInternals` keyed on `[id, direction, density, expanded]` (handles appear/disappear
  with rows — the stale-measurement trap, `WorkflowNode.tsx:139-142` precedent). Minimap: `io` →
  neutral (the old ports wash).
- **`GroupNode`**: collapsed + rows visible → the two-column area (grid, outputs col staggered
  `margin-top: var(--row-h)`) between header and card bottom. Expanded → inputs `PortRows` as the
  left sidebar block; outputs `PortRows` bottom-right strip; full-width dividers (`margin: 0 -pad`)
  per the v4 mockup + 8px extra breathing room. Header itself UNCHANGED (parity holds; the
  `useUpdateNodeInternals` dep list gains `rowsVisible`).
- **CSS**: new `.io-rows` / `.io-col` / `.io-col-label` / `.io-row` rules (reuse `--row-h`; new
  `--io-label-h`); region divider + sidebar rules; delete `.ports*` block. Construction-site
  comments per the grep-ability convention.
- Icons: reuse an existing glyph for the IO tile (arrow-into-bar style); data-URI like condition.svg
  if no asset fits. Tile border = teal (`--data-edge`).

## Phase 3 — `layout.ts` + `metrics.ts`

- **`metrics.ts`**: `+ ioLabelH (18)`, `+ ioSidebarW (200)`; widths (`IO_CARD_WIDTH`,
  `GROUP_IO_WIDTH`) stay TS-only in flow.ts (widths/paddings are TS-only per `flow.ts:162-165`).
  Inject `--io-label-h` (CSS consumes it); drop `portsHeaderH`.
- **Per-group ELK padding** (replaces the constant `GROUP_PADDING`, `layout.ts:51-53,175`): for an
  expanded group, `top = groupHeaderH + 16`, `left = rowsVisible && nIn > 0 ? ioSidebarW + 24 : 16`,
  `bottom = rowsVisible && nOut > 0 ? ioLabelH + nOut×rowH + 24 : 16`, `right = 16`.
  (+8px already folded into these numbers vs the mockup.)
- **Min height**: `elk.nodeSize.minimum` on the group when the sidebar is taller than the body
  could be — `minHeight = headerPad + ioLabelH + nIn×rowH + bottomStrip` (verify elkjs option name
  against the bundled version; fall back to `org.eclipse.elk.nodeSize.minimum`).
- **ELK edges**: nothing to change — IO data edges already feed ELK even when hidden (:202-209,
  the island rule). The endpoints become the io-card node (root) / the group (nested);
  group↔own-child hierarchical edges VERIFIED OK under `INCLUDE_CHILDREN` (4-shape experiment,
  /tmp/elk-hier-edge.mjs, 2026-06-10 — no crash, sane positions, both directions, root-level or
  in-group declaration). **Do NOT put ELK ports on an expanded group** (compound-port crash,
  pinned by `layout.test.ts:726`). IO cards: type `io` joins the `portable` set ONLY if control
  edges ever touch them — they don't (data-only) → leave them out.

## Phase 4 — tests (update the pinned set, add the new pins)

Update (from the inventory — these pin the OLD policy):
- `flow.test.ts:487` (ONE ports node) → root wrappers become `io` cards (id = wrapper id, count,
  compact size beautiful / rows advanced); nested wrappers put rows on the group data.
- `flow.test.ts:497` (row re-anchor + original endpoints) → same assertion shape, owner = io card
  or group; `portHandle`/`portTargetHandle` ids unchanged.
- `flow.test.ts:512/:523` (row focus reveal) → unchanged semantics, new owner.
- `flow.test.ts:565` (HANDLE-TYPE INVARIANT) → fixture keeps exercising `io:`/`iot:` in
  source/target slots via the new owners; drop `iotr:`/`iol:` coverage.
- `flow.test.ts:933` (expandTargets wrapper focus) → owner-aware version + the NEW case: focusing
  a consumer expands the IO owner.
- `flow.test.ts:210` (collapsed card 260×68) → only when rows hidden; new sizing case when visible.
- `collapse.test.ts:37` — unchanged (wrappers still not collapsible; assert still green).
- `portSides.test.ts:46-98` — DELETE (with the pass). The rail describes (:100+) keep their
  `portsNode()` helper renamed/retargeted to any data-edge fixture.

New pins:
- io-card emission (both kinds, pill text source data, compact↔rows sizing, no card when a side
  has 0 ports).
- group two-column sizing: `max(nIn, nOut+1)` stagger formula; zero-IO group identical to today.
- region padding: layout test asserting first-layer child x ≥ sidebar width when rows visible
  (TD), and an edge into the region still lays out (no compound port — extend `layout.test.ts:726`).
- per-endpoint row landing: binding edge onto a region input row (dual handles) vs node-level when
  rows hidden (the H6 degrade).
- `applyFocus` focusedPortId on group/io data + identity preservation.

## Phase 5 — verification + docs

- **Real browser** (the skill loop): `execute-plan` root (14 inputs — the motivating screenshot;
  beautiful = one quiet card, advanced = rows), `run-cycle` (nested + batch-modifier interplay),
  `orchestrate` (nested regions, sidebar + bottom strip + dividers), `lyrics-generator` (128-node
  scale + collapse defaults), `conditional-branching` (zero-IO — must be pixel-identical to today).
  Both densities × TD/LR; `inspect` for row-dot landings + sidebar/first-node same-row check;
  zoomed crops for the dividers. Cache-bust `&v=`.
- **Gates**: web vitest + tsc + build; Python suite untouched (zero contract change) — still run
  `test_graph_react_flow_renderer.py` + goldens as the no-regression sanity.
- **Docs**: `web/CLAUDE.md` (IO section rewrite: ports node → IO rows/owners; facing-sides bullet
  removed; the dual-handle rule now region-scoped), `visualization-requirements.md` (hard
  requirement "one consolidated ports node per level" → superseded by the IO-rows requirement;
  record the locked decisions incl. stagger rule + sidebar/bottom-strip + rejected last-node-
  beside-outputs), progress-log entry, `ui/CLAUDE.md` only if its IO wording goes stale.

## Open knobs (decide during build, not blockers)

- `IO_CARD_WIDTH`/`GROUP_IO_WIDTH`/`ioSidebarW` exact values — tune on canvas.
- LR region: sidebar stays left (flow-aligned in LR too); outputs strip bottom-right — verify it
  reads well, else outputs become a right-side column in LR only.
- ReadPanel for io cards (click currently → focus only): probably show the port list; decide when
  wiring `GraphView.onNodeClick`.
- Root io cards and `node=`/`focus=` URL params: wrapper ids work today via expandTargets — keep.
