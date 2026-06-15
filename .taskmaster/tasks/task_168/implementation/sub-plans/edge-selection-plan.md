# Edge SELECTION (click) + read panel — implementation plan

> **Status: IMPLEMENTED 2026-06-10** (Phases 1–4 + docs; see the progress-log entry for
> the two deviations — the `focus=<flat edge id>` deep-link escape hatch was pulled
> FORWARD from the deferral to serve the verification loop + Task 169, which exposed and
> fixed the `initialCollapsed` edge-protect gap; and zIndex became a fully
> applyFocus-owned channel after a re-processing test caught the stale-elevation
> fallback). **Pending: the Phase-4 shoot-lab** (selected shade × halo weight — the
> `--data-edge-selected` var is the one knob) and the closing `/code-review`. Hover
> (Phase 6) remains gated.
>
> Plan hardened pre-implementation by a 4-lens review (review-plan /
> feature-interactions / silent-failures / impact-completeness — all four verified the
> architecture sound; their fixes are folded in as **R1–R16** below and into the phase
> text). Design converged in conversation (edge-click chosen over hover-first; hover is a
> deferred follow-on layer).
> Companion docs: `web/CLAUDE.md` (current behavior), `visualization-requirements.md`
> (Implemented section), the read-panel mocks in the conversation record.

## The problem (one paragraph)

Edges are the viewer's core subject — the `${ref}` wiring it exists to reveal — yet they are
the only canvas objects with no interaction: not clickable, no read panel, and in dense
graphs (the harness: 124 data edges) a long line tunnels UNDER cards (React Flow paints all
edges behind nodes), so a skip edge reads as "did this connect or pass?". Nodes, containers,
ports, and IO rows all select; lines don't. Edge-click closes that gap: **select a line →
it lights, elevates above the cards it crosses, everything else dims, and the read panel
explains the connection** (what flows, the authored template + file:line, branch condition,
error/end semantics). It also gives Task 169's point-and-watch channel an addressable verb
for connections, which hover never can.

## Decided design (locked — don't re-litigate)

| Gesture | Action |
|---|---|
| Click an edge | **SELECT**: focus = the edge; edge + its two endpoint nodes light, all else dims; edge elevates (zIndex) above nodes; its floating label suppresses; panel shows the connection |
| Click a `loop:` self-arc | redirects to selecting its anchor NODE (the loop spec lives on the node panel) |
| Click an `io-flow:` synthesized edge | restyle-only focus, **no panel** (no contract identity) |
| Pane click | clears, as today |
| Endpoint chips in the panel | click → focus jumps to that node (panel swaps) — graph-walking |
| Hover highlight | **NOT in this plan** — follow-on layer on the same machinery, own design gate |

**Color/state principle (user-converged):** hue carries identity, brightness carries state.
A selected data edge becomes a **brighter, more saturated member of the same green-teal
family** (`--data-edge` is `#6fbfa8`; selected ≈ `#8fe8c0`-territory — exact shade via
shoot-lab, checked against transform cyan `#5fd4dd` and shell green neighbors). Selected
gradient (control) edges keep their source→target blend at full strength. Selection is
expressed by: bright variant + **halo under-stroke** (the edge analog of the node focus
ring — a ~3× width, low-opacity path under the edge in its own color) + **elevation** +
ambient dimming. Never a foreign "selection blue".

**Beautiful-mode expansion:** selecting a data edge expands BOTH endpoint owners
(`expandTargets`), so the selected line lands row-to-row (source output row → target param
row) — same machinery as leaf focus-expansion (cached / animated / camera-anchored).
Control-edge selection expands nothing (node-level endpoints already read fine).

**Read panel variants** (all data already in `/api/graph` — ZERO Python change):

- **data** — title `output_field → input_name`; endpoint chips (kind-colored, navigate);
  the target's matching param block REUSED from the existing read-param rendering (full
  value + `[dynamic]` badge + SourceRef file:line). Interpolated params: "one of N
  references into `prompt`" (count edges sharing `(to, input_name)`), this ref highlighted
  in the value.
- **branch** — title = outcome; chips; untruncated condition; the source's full outcome
  table (the EXISTING branches table, this edge's row marked).
- **error** — chips + fixed semantics line ("taken when X fails, after retries").
- **end** — a decision's end edge = the branch variant labeled `→ end` (condition + table);
  a static end edge = chips + "the workflow's final step".
- **sequential** — chips + "runs after"; when `shadowed: true`, the line "this ordering is
  also implied by a data dependency" (first surfacing of the model's shadowed fact).

Degrade additively (the contract's own rule): `input_name`/`output_field` are often null
(re-anchored/truncated edges clear role labels) — the panel shows what's present, never
guesses.

## Verified facts the plan builds on (file:line)

- Flow edges keep contract ids (`flow.ts:1133 id: edge.id`); synthesized edges are
  namespaced (`io-flow:` :857, `loop:` :924) → `graph.edges.find(e => e.id === selectedId)`
  cleanly resolves contract edges and naturally misses synthesized ones.
- `applyFocus` (flow.ts:1187) is the single restyle pass; `EdgeData` (flow.ts:152) already
  carries `from/to/kind/outcome/condition/defaultHidden` — everything the focus arm needs.
- `expandTargets` (flow.ts:364) already has the container arm precedent for a non-node
  focus subject; the hook gates it to beautiful (`useWorkflowGraph.ts:120`).
- `elementsSelectable` is ON (GraphView.tsx:277) and `DataEdge` reads RF's `selected` prop
  (DataEdge.tsx:87, a stray +1px branch) — RF native edge selection is HALF-AWAKE. The plan
  makes `applyFocus`-written `data.selected` the single styling truth (deep links must
  select too; RF's prop can't) and removes/neutralizes the stray branch.
- Camera anchoring keys on `absolutePosition(nodes, anchorRef)` (useWorkflowGraph.ts:181) —
  an edge id resolves to no node → no pan. Phase 2 anchors edge-focus on an endpoint.
- RF edge `zIndex` elevates an edge above nodes; KNOWN CAVEAT (loop-edge history,
  web/CLAUDE.md): an elevated edge paints above the EdgeLabelRenderer layer — hence label
  suppression on the selected edge (the panel carries the info). Browser-verify the layer
  stack in Phase 4; the suppression makes the worst case a non-issue.
- jsdom renders NO edge DOM (web/CLAUDE.md) — edge-click wiring is browser-verified;
  selection logic is pure-layer tested; EdgePanel is a plain component, jsdom-testable
  directly.

## Review hardening (R1–R16) — folded from the 4-lens review

- **R1 (3 lenses)** Remove the stray RF-`selected` strokeWidth branch from **BOTH**
  `DataEdge.tsx:87` AND `GradientEdge.tsx:224` (identical twins; the only RF-`selected`
  consumers — verified). Neutralize RF native selection wholesale: `deleteKeyCode={null}`
  on ReactFlow (Backspace currently DELETES a selected element from the store — live
  hazard once edges are routine click targets). The new halo path must carry an **inline
  stroke** (RF's base stylesheet strokes `.selected` paths grey `#727272`; inline wins).
- **R2 (3 lenses)** Endpoint chips resolve through **`resolveNodeFlatId`**
  (viewParams.ts:76 — host→representative group, rendered-id check), NEVER raw contract
  ids (an edge endpoint is often a suppressed group host, an IO port, or inside a
  collapsed group → naive setFocus gives panel-without-canvas half-states). Policy:
  IO-port endpoint → `focusPort` semantics (focus the port id, no panel swap); resolvable
  node/group → focus + panel; **unresolvable → the chip renders as plain text (not
  clickable)** — visible honesty over a silent no-op.
- **R3 (2 lenses)** `loop:` redirect targets the FLOW edge's **`e.source`** (the render
  anchor — a GROUP id for looped sub-workflows, flowing through the container-unit /
  host-panel paths), never `data.from` (the suppressed host). Test on a group-anchored loop.
- **R4 (2 lenses)** `applyFocus`'s identity-preserving early-return (flow.ts:1305-1311)
  must compare AND write the new fields (`selected`, `zIndex`) — for a focused **control**
  edge nothing in the current tuple changes, so selection would silently never land; and
  an edge→its-own-endpoint focus transition must clear them (test both).
- **R5** `focusEnd` is **explicitly cleared** on the focused edge (the existing ternary
  would default it to `"target"` → one end falsely fades). Test pin.
- **R6** `expandTargets` edge arm: endpoints go through `add()` into the OUTPUT set —
  NEVER seeded into `foci` (the data-edge loop would expand both endpoints' entire data
  neighborhoods). Negative pin: A has data edges to B, C, D; selecting A→B expands
  exactly {A, B}.
- **R7 (2 lenses)** **Rebuild survival rule**: an edge-id focus has no `from/to` escape
  hatch — single-group collapse can re-anchor + dedupe the focused edge's id out of the
  flow (flow.ts:790, 795-797) → all-dim canvas + live panel. Rule: GraphView clears
  focus+selectedId when the selected id is an edge id absent from the current flow edges
  (cheap effect; pure-testable predicate).
- **R8** io-flow click: focus + **`setSelectedId(null)`** explicitly (else a stale node
  panel persists beside an unrelated focused edge).
- **R9** applyFocus strips **`edge-shadowed`** from the selected edge's className (35%
  opacity would fight bright+halo; it already owns className surgery via `stripDim`).
- **R10** Dimming must reach **EdgeLabelRenderer pills**: applyFocus writes `dimmed` into
  EdgeData; components apply it to their label/pill divs (today sibling outcome labels
  glow at full strength over a 0.18-opacity canvas — this feature's value IS the dim
  contrast).
- **R11** Branch-edge selection & label suppression: the selected edge suppresses its OWN
  floating label/pill (elevation strike-through). So a selected LR branch ALSO reveals its
  condition on the SOURCE's BranchPorts row (extend `revealBySource` matching to
  `e.id === focus` — node-side, no layer conflict); TD accepts panel-only. Without this a
  selected branch is a bright dashed line with no name anywhere on canvas.
- **R12** EdgePanel end-variant discriminator = the **source node's `is_decision`**
  (exactly GraphView.tsx:295's rule), never `condition != null` (extraction is
  fail-closed — a decision's end edge can ship condition-less).
- **R13** Data-variant param join must handle: **dict-key bindings** (input_name is a key
  inside a dict-valued param — mirror `targetHandleFor`'s fallback walk, flow.ts:1056);
  **IO-port targets** (no params → show the port's io facts instead); **null roles**
  (re-anchored: title falls back to "data connection", never an empty h2).
- **R14** Deduped-bundle honesty: a clicked node-level line can represent N bindings
  (client dedupe keeps the FIRST contract edge's id+labels). The data variant counts
  contract data edges sharing the selected edge's `(source, target)` and shows
  "one of N bindings between these nodes" listing the sibling roles. (The same-`(to,
  input_name)` interpolation count is a separate, additional line.)
- **R15** Camera anchor: resolve edge-focus → the FLOW edge's `source` endpoint **at
  set time** (needs built edges in scope — not literally one line), never `data.from`
  (can be a never-rendered IO port). Browser-verify camera stability on a beautiful
  data-edge click.
- **R16** Panel "reuse" = **extraction**: pull `ParamBlock` and `OutcomeTable` out of
  ReadPanel as shared components (they're inline JSX today), then extend (highlight-this-
  ref; mark-this-row). ReadPanel's jsdom pin (GraphView.test.tsx:123) re-verified after.

Deliberate parity choices (named, not bugs): toolbar "clear focus" clears the highlight
but keeps the panel open — identical to today's node behavior, kept for consistency.
Task 169 deferral note: when edge deep-links land, `resolveNodeFlatId` (viewParams.ts:76)
AND `initialCollapsed`'s protect chain (collapse.ts:42) both need edge arms — recorded
here so the future task inherits the list.

## Phases

### Phase 1 — pure layer: edge focus in `flow.ts`

- `EdgeData.selected?: boolean` + `EdgeData.dimmed?: boolean` (R10) — written by
  `applyFocus`, read by components. `zIndex` written on the edge object.
- `applyFocus` edge arm: when `focus` matches an edge id — connected = the edge's
  endpoints (`source/target` AND original `from/to`); ONLY the focused edge is incident
  (endpoint nodes light, their OTHER edges dim — the clicked connection is the subject; a
  separate incidence test, NOT the unit machinery); the focused edge gets
  `selected: true`, `zIndex` (constant), reveal-if-defaultHidden, `focusEnd` explicitly
  cleared (R5), `edge-shadowed` stripped (R9); LR branch-row condition reveal extends to
  edge focus (R11). The identity early-return compares the new fields (R4). Leaf/group/
  port focus paths byte-identical (existing pins are the regression proof).
- `expandTargets` edge arm: a data-edge focus contributes both endpoints through the
  existing `add()` directly into the output set (R6; owner-aware for IO ports);
  control-edge focus → ∅.
- Tests (flow.test.ts, node-env): edge-focus dim/light; selected+zIndex flags on a
  CONTROL edge (the R4 silent-swallow case) and a data edge; edge→endpoint-node
  transition clears selected/zIndex (R4); focusEnd cleared (R5); shadowed class stripped
  (R9); dimmed flag written (R10); LR branch-row reveal on edge focus (R11);
  defaultHidden edge stays revealed under its own focus; expandTargets both-endpoints
  (incl. an IO-port endpoint → owner) + the R6 negative + control edge → ∅; existing
  focus pins untouched.

### Phase 2 — wiring: GraphView + hook

- A **pure dispatch helper** (`edgeClickAction(edgeId)` → `{focus, selectedId}`), tested
  node-env (jsdom can't click edge DOM): `loop:` → the flow edge's `source` (R3);
  `io-flow:` → focus + selectedId `null` (R8); contract edge → focus + select.
  `onEdgeClick` applies it.
- `selectedEdge` memo: `graph.edges.find(e => e.id === selectedId)` + endpoint
  resolution; render `<EdgePanel>` when it hits (node panel logic unchanged).
- Rebuild-survival effect (R7): selected edge id absent from current flow edges → clear
  focus + selectedId.
- `deleteKeyCode={null}` on ReactFlow (R1).
- Hook: camera-anchor guard maps an edge focus to its flow `source` endpoint at set time
  (R15).
- Toolbar "clear focus", collapse-all clearing, deep-link `focus=` (node-only) all work
  unchanged. **Edge deep-link addressing is deferred** (see the Task 169 note above).

### Phase 3 — `EdgePanel` component

- Extract `ParamBlock` + `OutcomeTable` from ReadPanel first (R16), extend with
  highlight-this-ref / mark-this-row; ReadPanel consumes the extractions (its rendering
  byte-identical).
- New `components/EdgePanel.tsx` beside ReadPanel, same design language (kind line tinted
  with the edge's paint → title → chips row → facts `<dl>` → ParamBlock / OutcomeTable).
  The chips row is the only new UI primitive; chips resolve-or-disable per R2.
- The five variants per the locked table above; end-variant discriminated by source
  `is_decision` (R12); data-variant join per R13; dedupe count per R14; "one of N refs"
  interpolation count.
- Tests (jsdom, like ReadPanel's): one render test per variant off hand-built RFEdge/
  RFNode fixtures matching real contract shapes (run-from-plan's `e2/e3/e12/e14` +
  conditional-branching's error edge as fixture source); a deduped multi-binding fixture
  (R14); a dict-key binding fixture (R13); a role-less re-anchored fixture (R13 title
  fallback); chip resolve-or-disable.

### Phase 4 — visual treatment (shoot-lab first)

- **Lab round** (`/tmp/edge-select-lab/`, real card anatomy, opened in the user's
  browser): bright-green shade × halo weight/opacity × thicken-or-not — checked beside a
  transform node and a shell node for hue collision. User picks; constants land in
  metrics/format.
- `DataEdge`: `data.selected` → bright solid variant (no fade), halo path under the main
  path (inline stroke, R1); `data.dimmed` → label dims (R10). `GradientEdge`: same +
  full-strength blend; skip `EdgeLabelRenderer` while selected. Remove BOTH stray
  RF-`selected` branches (R1). Dash/dim stay CSS; **stroke stays component-owned** (the
  pinned rule).
- Browser verification (screenshot-pflow-web-ui): run-from-plan advanced TD — select a
  long data edge → elevated over crossed cards (check the elevated ~20px hit band doesn't
  shield clicks on crossed cards — mitigation if it bites: `interactionWidth: 0` while
  selected), bright + halo, both ends solid, label gone, panel correct; select an edge
  INSIDE an expanded region (child z-order — the loop-edge zIndex lesson); a crossing
  over ANOTHER edge's condition pill; camera stability on a beautiful data-edge click
  (R15); beautiful — select a control edge (restyle only), then a revealed data edge
  (both endpoints expand, line lands row-to-row); conditional-branching — error edge
  panel; validate-fix — a decision's end edge panel shows `→ end` + condition; a shadowed
  sequential edge selects bright (R9).

### Phase 5 — docs + review (closing)

- `web/CLAUDE.md`: an "edges SELECT on click" bullet (data.selected channel, R-rules:
  focusEnd-clear, loop redirect, rebuild survival, RF-selection neutralized);
  `visualization-requirements.md` Implemented section; progress-log entry per convention.
- `/code-review` pass over the full diff.

### Phase 6 (separate, gated) — hover highlight

Additive transient layer (brighten + elevate incident edges on node/edge hover, no dim,
no panel, no layout) on the same `data.selected`-style channel. Own design check-in
before building — NOT part of this plan's definition of done.

## Gates

`npx vitest run` (web), `tsc --noEmit` strict, `npm run build`, real-browser loop per
Phase 4. No Python files change → no `make test` impact beyond the usual final run.

## Risks / honest unknowns

- **RF zIndex layer stack** (edge-above-node, above-other-labels, inside expanded
  regions) is browser-verified, not assumed — if elevation misbehaves, fallback is
  bright+halo+dim without elevation (still a complete feature; elevation is additive).
- **Dense-bundle click precision**: 13-binding bundles have overlapping ~20px hit bands —
  top edge wins. Accepted for v1; lanes separate them visually. Revisit only if it bites.
- **Parallel agent in repo**: another agent is editing `types.ts`, `flow.test.ts`,
  `GraphView.test.tsx` and the Python contract files. Re-read fresh before every edit;
  keep changes additive (new describe blocks / new optional fields); never commit.
