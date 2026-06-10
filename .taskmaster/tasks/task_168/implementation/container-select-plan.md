# Container SELECT vs EXPAND/COLLAPSE — implementation plan

> **Status: PLANNED, not started** (user instruction: no code until go).
> Design locked 2026-06-10 via mockup labs (`/tmp/expand-btn-lab/` rounds 1–3, shoot-verified).
> Companion docs: `web/CLAUDE.md` (current behavior), `visualization-requirements.md` (will gain
> the decided interaction model on completion).

## The problem (one paragraph)

A click on a container is one gesture carrying two intents: **select/inspect** (ring, dim
non-incident, reveal its connections, read panel — cheap, no re-layout) and **open/close**
(structural navigation, re-layouts). Today containers have ONLY open/close
(`GraphView.onNodeClick`, web/src/views/GraphView.tsx:157 — `type === "group"` → collapse
toggle, nothing else). Consequences: a container can never be selected; its bindings are
invisible in beautiful (data lines reveal only on focus, and containers can't be focused);
the read panel is unreachable for containers (loop/batch spec, description, source); and the
collapsed card *looks* exactly like a node (deliberate redesign) yet is the only card that
doesn't select on click.

## Decided design (locked — don't re-litigate)

**Design D** (user-picked from option families A–D):

| Click target | Action |
|---|---|
| Container card/region body or header | **SELECT** (focus + read panel) — exactly like a leaf |
| NEW corner button (top-right) | **TOGGLE** expand/collapse |
| Double-click anywhere on the container | TOGGLE (accelerator; requires `zoomOnDoubleClick={false}`) |
| Leaf / IO card / port row / pane | unchanged |

**The corner button** (user-picked via 3 mockup rounds):
- **V2 placement**: square rounded icon button INSIDE the card face, top-right corner
  (window-control style). Same position on the expanded region (its header area).
- **A1 glyphs**: arrows-out (expand) / arrows-in (collapse) — maximize/restore language.
  Rejected: unfold-chevrons, single chevron (reads as dropdown), plus/minus (collides with a
  future editor's "add").
- **R1 rest weight**: full boxed button always visible (bg `color-mix(--kind 12%, --bg-node)`,
  border `color-mix(--kind 30%, transparent)`, muted glyph); hover brightens to kind color
  (bg 22%, border 55%, glyph `var(--kind)`). Rejected: quiet 55% icon, kind-tinted bare icon,
  hover-only (discoverability: touch/screenshots/first-run never see it).
- Geometry from the lab: 22×22px, radius 7, `top: 7px; right: 7px`, 12px glyph, stroke 1.8
  round caps. The existing count pill (`.group-pill`, top −9 / right 14, straddling the
  border) coexists above it — verified visually in the lab.

**Who gets the button (user-confirmed):** GroupNode-rendered containers ONLY — collapsed
workflow group cards, expanded regions, literal-batch containers, and a batched
sub-workflow's representative workflow group. A **batched LEAF gets nothing** (it renders via
WorkflowNode with deck + ×N badge; its shell batch group never renders — there is nothing to
open). This needs zero special-casing: the button lives in GroupNode, period.

**What SELECTing a container means (decided in planning):**
- Focus = the group id. Ring on the card/region (kind color).
- **The unit lights up**: the group, ALL its descendants, and every edge touching any of them
  — internal wiring AND external bindings. Everything else dims. (For a collapsed card,
  descendants aren't emitted, so the unit degrades to just the card + its re-anchored edges —
  the same shape as a leaf focus.)
- In beautiful, the container's default-hidden data lines (bindings) REVEAL — this is the
  headline win: "what feeds this 20-node box?" answered without opening it.
- Read panel opens showing the group's **host node** (purpose, params, loop/batch spec,
  source). Wrapper groups have no host → no panel (io-card panel stays the parked knob).
- **No neighbor row-expansion in v1** (`expandTargets` already returns the empty set for a
  group id — verified flow.ts:297; revealed lines land node-level on the card). Group focus
  is therefore a pure restyle: NO re-layout, honoring "focus never re-layouts".

## Verified facts (file:line, 2026-06-10)

- `GraphView.onNodeClick` (web/src/views/GraphView.tsx:157): group → collapse toggle only;
  io → focus toggle; leaf → `setFocus` + `setSelectedId`. `onPaneClick` clears both.
- `selectedNode` resolution (GraphView.tsx:191): `graph.nodes.find(id)` — a group id finds
  nothing, so the read panel silently never opens for groups today.
- `applyFocus` (web/src/graph/flow.ts:1060): incidence = `edgeTouchesFocus` (flow.ts:1056 —
  endpoint or `data.from/to` equals focus). Already handles `focused`/`dimmed` for group
  nodes (the `n.type === "io" || n.type === "group"` branch); expanded regions never dim
  (`n.type !== "group" || n.data.collapsed` guard). Missing ONLY: unit semantics (descendants
  + their edges).
- `expandTargets` (flow.ts:297): a non-wrapper group id yields the empty set — safe, no crash.
- `InteractionContext` (web/src/components/interaction.ts): tiny, currently `focusPort` only —
  the established channel for clicks originating inside a node (node `data` stays
  callback-free). `toggleGroup` belongs here.
- `GroupNode` (web/src/components/nodes/GroupNode.tsx:150): one root div, shared header both
  states, count pill absolute on border. Root is `position: relative` contextually (`.node`/
  `.group` both `position: relative`, index.css:273) → `position: absolute` button just works.
- Ring CSS: `.node.focused` only (index.css:288). The collapsed card has `.node` classes →
  ring free; the expanded region's root class is `.group` → needs a `.group.focused` rule.
- `GraphView.test.tsx`: NO pins on group clicks (fixture has `groups: []`) — clean to change.
- Deep-link gap: `resolveNodeFlatId` (web/src/utils/viewParams.ts:72) resolves a node_id to
  the node's flat id and checks it's RENDERED — a group-HOST's node_id (e.g. `execute-plan`)
  maps to the suppressed host node (n15, never rendered) → **null**. Only the flat `g*` id
  works today. Fix in scope (agents + Task 169 need "select container by name").
- Double-click: React Flow exposes `onNodeDoubleClick` and `zoomOnDoubleClick` (must set
  false or every double-click zooms). A dblclick fires its two clicks first → select runs
  twice (idempotent) then toggle: acceptable (select-then-open), no guard needed.
- Focus survives a toggle: the group id is the flow-node id in BOTH states (collapsed card
  and region share the wrapper/group id), so collapsing a focused region keeps a valid focus.

## Phases

### P1 — `applyFocus` learns container units (flow.ts, pure)
- Build the unit set: `unit = {focus}`; if focus is a rendered `group` node, BFS the flow
  nodes' `parentId` chain to add all descendants.
- Replace the three `edgeTouchesFocus(e, focus)` incidence checks with
  `touches(e) = e.source/target/data.from/data.to ∈ unit`.
- Seed `connected` with the whole unit (descendants must not dim).
- Leave the condition-reveal logic on exact `focus` equality (clicking a branch target is a
  specific-thing gesture; a collapsed group as branch target already matches by endpoint).
- Degenerate case = leaf/port focus: unit = {focus} → byte-identical behavior to today
  (pin this with the existing focus tests staying green).

### P2 — the toggle channel + the corner button
- `interaction.ts`: add `toggleGroup(groupId: string): void` (default no-op) beside `focusPort`.
- `GroupNode`: render `<span className="group-toggle" title="Expand|Collapse">` with the A1
  inline SVG (two paths, swap on `collapsed`), `onClick={(e) => { e.stopPropagation();
  toggleGroup(id); }}` — the io-row stopPropagation pattern. No handle inside (no
  `updateNodeInternals` interaction). Title padding: `.group-card .node-titles`/region header
  titles get `padding-right` so the 2-line name can't run under the button.
- CSS (index.css, construction-site comment "GroupNode group-toggle"): R1 styling + hover, and
  the `.group.focused` ring rule (`box-shadow: 0 0 0 2px var(--kind)` matching `.node.focused`).
  Glyph paths from the lab: out `M7.2 1.8 H10.2 V4.8 M10.2 1.8 L6.8 5.2 M4.8 10.2 H1.8 V7.2
  M1.8 10.2 L5.2 6.8`; in `M6.8 5.2 H10 M6.8 5.2 V2 M10.2 1.8 L6.8 5.2 M5.2 6.8 H2 M5.2 6.8
  V10 M1.8 10.2 L5.2 6.8` (12×12 viewBox).

### P3 — GraphView semantics
- Extract `toggleGroup = useCallback(id => setCollapsed(prev ⊕ id))`; pass through the
  `interaction` memo (now `{ focusPort, toggleGroup }`).
- `onNodeClick`: group → `setFocus(node.id); setSelectedId(node.id)` (leaf-identical,
  idempotent re-click; pane click clears — NOT the io-card toggle pattern).
- `onNodeDoubleClick`: group → `toggleGroup(node.id)`. Set `zoomOnDoubleClick={false}` on
  `<ReactFlow>`.
- `selectedNode` resolution: `graph.nodes.find(id)` **else**
  `graph.groups.find(g => g.id === selectedId)?.host` → host node lookup → ReadPanel renders
  it unchanged (purpose/params/loop/batch/source all live on the host RFNode). Branches prop:
  keep filtering by the resolved node's id (host id is the contract edge source).
- Collapse-all keeps clearing focus (unchanged); single-button collapse of the focused group
  keeps focus (id valid in both states — verified fact above).

### P4 — deep-link parity (viewParams.ts)
- `resolveNodeFlatId`: when the matched node is rendered → flat id (today's path). NEW: when
  the matched node is a group HOST whose id is NOT rendered, resolve to its representative
  group id if THAT is rendered (mirror flow.ts's `primaryGroupForHost` notion: the group whose
  `host` is the node, skipping memberless batch shells). `focus=execute-plan` then selects the
  card/region; `node=` framing gains the same by construction.

### P5 — tests (vitest, pure where possible)
- `flow.test.ts` applyFocus unit semantics: expanded-group focus → member NOT dimmed,
  internal edge NOT dimmed, boundary edge lit + far endpoint connected, unrelated node/edge
  dimmed; collapsed-group focus reveals its default-hidden binding line; leaf-focus behavior
  byte-identical (existing pins must stay green untouched — that IS the regression test).
- `viewParams.test.ts`: host node_id → representative group id; shell-batch host → workflow
  group id; non-host unchanged.
- Component-level (jsdom, rf-jsdom): GroupNode renders the toggle with the right glyph per
  state and calls `toggleGroup` (not focus) on button click — the stopPropagation pin.
- NOT testable in jsdom (browser checklist instead): dblclick zoom suppression, visual ring
  on region, button hover.

### P6 — docs + real-browser verification
- Browser checklist (screenshot/inspect loop on run-from-plan + execute-plan + a
  literal-batch example): click collapsed card → ring + dim + teal binding lines reveal, NO
  re-layout; corner button → opens (focus retained, ring on region); click region header →
  selects (children stay lit, outside dims); double-click → toggles; batched LEAF shows no
  button; read panel shows host info incl. loop spec on a looped sub-workflow; io card
  behavior unchanged; `?focus=execute-plan` deep-link selects the container (screenshot-able).
- Doc sync: `web/CLAUDE.md` (the container bullet's "clicking its collapsed card opens the
  sub-workflow body in one click" is now WRONG — rewrite to the new model), `ui/CLAUDE.md`
  untouched (server-side), `visualization-requirements.md` (new Implemented bullet + the
  decided interaction model under Design principles), progress-log entry.

## Decisions & rationale (made in planning; flag if you disagree)

1. **Group re-click stays focused (leaf pattern), not toggle-off (io-card pattern).** One
   rule for all selectable things; pane-click clears. The io card keeps its toggle because
   its focus IS its open state — revisit alignment later.
2. **Selecting an expanded region lights the whole unit** (descendants + internal wiring +
   boundary edges). Alternative (host-level edges only, children dim) makes the region look
   broken — you selected the box, not nothing.
3. **No neighbor row-expansion on group select (v1).** Keeps group select a pure restyle
   (no ELK). The revealed lines land node-level; if that proves too coarse, extend
   `expandTargets` later — additive change.
4. **Double-click included** (it's cheap, n8n-familiar) — but it's an accelerator, not the
   primary affordance; remove later costs nothing.
5. **Deep-link host-name resolution in scope** — small, and Task 169 (point-and-watch)
   immediately needs "select container by name".
6. **IO cards untouched in v1** — their click model (focus=open) was user-decided same week;
   re-aligning is a separate decision after this lands.

## Risks / gotchas

- **stopPropagation is load-bearing** on the button (else the click also selects — confusing
  with dblclick). Pin in the component test.
- **`zoomOnDoubleClick` default is true** — forgetting it makes every toggle also zoom.
- **`.group.focused` ring rule** must not leak to `.group-card` double-ring (card already has
  `.node.focused`; selectors are disjoint — verify visually).
- The **collapse toggle re-layouts and may not animate** (collapse changes snap by design —
  only expansion re-layouts animate). Unchanged behavior, but now reachable from a button;
  if the snap feels harsh next to the leaf animation, that's a later motion decision.
- Muscle memory: "click card to open" dies. The button + dblclick both cover it; docs updated.

## Explicitly NOT in scope

- IO-card click model changes; ⌘K search; smart edge-router; any contract/Python change
  (this is 100% `web/`); neighbor expansion on group select; animating collapse toggles.
