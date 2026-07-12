# Components (`web/src/components/`)

The React render layer: node/edge components React Flow registers, the side panels, and the
source pane. Reusable pieces in `components/`; RF node components in `nodes/`; RF edge
components in `edges/`.

> Read `web/CLAUDE.md` (web root) FIRST — these components obey its cross-cutting invariants
> (edges draw behind nodes · the handle/edge contract · density governs edges ·
> geometry-single-sourced). The STRUCTURE they render (rows, edge routing, IO ownership, focus
> state) is computed in `web/src/graph/` — this folder consumes it, never re-derives it.

**Registered (every one must be `memo()`'d):** `nodes/` → `WorkflowNode` (`type:"node"`),
`GroupNode` (`group`), `IOCardNode` (`io`), `EndNode` (`end`); `edges/` → `GradientEdge`
(`gradient`), `DataEdge` (`data`), `LoopEdge` (`loop`). Plus `BranchPorts`, `PortRows`,
`ChipRail`, `StatusBadge` (under `nodes/`), `EdgeHalo`/`arrow.ts` (under `edges/`).
`StatusBadge` is the corner run-status overlay (Task 173): the ONE per-node live-status
surface (running/success/cached/failed/stopped/unrecorded/paused), keyed off
`LeafData/GroupData.status` (set by `applyStatus`; `paused` is synthesized by GraphView from
the banner's `paused_node_id`, Task 176) — pending = absent = no badge. It replaced the status border ring
and the ChipRail's old status slot; three node surfaces now coexist — corner StatusBadge
(live run-status), ChipRail chips (static behavior modifiers + the count button), inline
`.badge` pills (static structural markers). **Panels:** `ReadPanel`,
`EdgePanel`, `IoPanel`, `Chip` (+ `ConnectionSections`), `PanelHeader`, `BatchItems`,
`Markdown`, `CodeBlock`. **Shell:** `Toolbar`, `ErrorBoundary`, `PanelResizer`, `SourcePane`,
`interaction.ts` (the click-callback context + hover-set channel — keeps node `data`
callback-free), `NodeCallout` (the content-agnostic node-anchored flow-space box, Task 175 —
the run-progress callout AND Task 174's agent "say" bubbles both ride it; `frameOnMount?`
(default `true`) gates its one-shot camera frame — say bubbles pass `false` because the
point message that precedes a say already owns the camera. Say bubbles are PERSISTENT and
per-target — a Map in GraphView, status model in `web/CLAUDE.md`'s overlay seam; each shows
the caption plus at most one button, unlock (`blocked`) or ↻ Replay (`done`) — the same
start-this-clip gesture; `expired` and caption-only boxes render no button).
**Approval bridge (Task 176):** `GateCallout` (the kind-switched gate panel content — approval
preview + Approve/Deny; escalation options are SELECTABLE cards + a free-text field with ONE
Answer button submitting whichever is active — selecting clears the text, typing clears the
selection (owner decision 2026-07-12: an answer consumes the gate token irreversibly, so
options never fire on click); answers POST `/api/resume` via
`resumeRun`, refusals are panel states keyed on `ApiError.body.refusal`, never string-parsed)
rides a `NodeCallout` GraphView anchors at the ⏸ frontier node; `ResumeControl` (the
failed/interrupted-run Resume arm, same refusal vocabulary + the ack-then-`force` dialogs)
renders inside the run callout below `RunProgress`. Both send `force: true` ONLY after an
explicit user ack — never on the first POST. Escalation answers send the option LABEL
(falsy `option N` fallback mirroring `core/gate.py::option_labels`), never the number.

## The leaf node — one component, two densities (`WorkflowNode`)

ONE leaf component; `density` rides in `data` (no node-type swap on toggle). Colored BY TYPE:
the kind color in the border + a faint kind-tinted bg (Option B keeps the tile/icon in the
icon's NATIVE color — do NOT thicken/recolor the 1.5px card border). Both densities show the
category line + description (`purpose`, else `node_id`); advanced (`detailed`) adds the body
rows. Beautiful height is a FIXED `HEADER_HEIGHT` so the tile stays vertically centered; a
dev-only tripwire warns when detailed content overflows the pinned box. The body it renders is
`graph/rows.ts`'s `nodeRows` (one switch over `row.kind`; handles arrive ON the rows). Icons
come from `utils/icons.ts` (`iconFor`); add a kind icon there.

- **CONDITION / TRANSFORM pseudo-kinds** (presented, not contract kinds): a decision **code**
  node (`is_decision && kind==="code"`) shows label `CONDITION` + fork icon + orange; a
  pure-reshape **code** node (`is_transform`, classified fail-closed in Python) shows
  `TRANSFORM` + shuffle icon + cyan. Identity color (card/tile/category + edge gradients) routes
  through `nodeColor` (utils/format.ts — the single seam; see utils/CLAUDE.md), never raw
  `kindColor`. Mutually exclusive by construction; the read panel shows
  `code · condition`/`code · transform` so the canvas stays mappable to `type: code`.

## Icon connector flare (`Connector` in `WorkflowNode`)

A kind-colored SVG cove makes a control edge appear to flow INTO the icon tile (beautiful;
TD top/bottom, LR left + the `.exit-dot` on the right). Drawn only on sides with a control
edge (`hasIncoming`/`hasOutgoing`, computed in `graph/flow.ts`, handle-aware). Three rules
keep it gap-free — break one and the historical gaps return: (1) the control `Handle`s stay
on the node BORDER as direct untransformed children (RF mis-measures a handle nested in the
transformed connector div ~5px); (2) the flare is PURE DECORATION, opaque, on top, overlapping
both ends (stem under the edge terminus, base sunk WITHIN the tile's 3px border — past it = a
dark notch); (3) ONE `CONN` constant set drives the path, the viewBox AND the element size
(a viewBox/box mismatch silently rescales the paint — invisible to rect measurement).

## Edge components (`edges/`)

Render the paths `graph/` routes (lanes from `assignEdgeLanes`, rails from `portSides`); this
folder owns appearance. All control kinds (sequential/branch/error/end) → `GradientEdge`
(the n8n-style rounded-orthogonal language: `getSmoothStepPath` + `railCenter`; a `userSpaceOnUse` source→target
gradient via `gradientStops`; error fades to red, end to faint grey). `data_flow` → `DataEdge`
(same path language + per-lane stub/rail geometry; flat teal, focus draws SOLID at the clicked
end). `loop:` → `LoopEdge` (the U on its `assignLoopRails` rail; carries the app's ONE
arrowhead at re-entry; must NOT set `zIndex` or it strikes through its own label). **No
arrowheads** elsewhere; stroke width == the tile border so a line flows seamlessly into the
same-color border. **NEVER set an edge kind's `stroke` in CSS** — the components own color, so
a regression to a built-in edge type renders INVISIBLY (pinned by flow tests); dashes/dot
patterns/dim opacity ARE CSS. The `shadowed` fact rides `EdgeData`, but NO density dims for it
— with one edge per `${ref}` most of the spine is shadowed and the old advanced 35% dim erased
the control skeleton; don't re-add it. **Forks:** LR → labeled border handles (`BranchPorts`,
n8n-style); TD → fork from the icon column, label on the edge. Branch CONDITION pills render
where the outcome lives (TD: final approach into the target; LR: on the source's `BranchPorts`
row) — visible in advanced always / beautiful on focus-expansion, plus clicking a branch
TARGET reveals just its own condition. *Interacts with:* `EdgeHalo` (selected/hover under-stroke,
inline stroke since RF greys `.selected`); the selection/dim state comes from `graph/focus`.

## Containers (`GroupNode`) + chip rail (`ChipRail`)

ONE object in two states; NOTHING in the header moves across the fold (a single header JSX
block — `METRICS.groupHeaderH` MUST equal `nodeHeaderH`). COLLAPSED = a leaf card (card CSS,
focus ring, dimming, icon-column ports + connector flares all reused); EXPANDED = a kind-tinted
region (workflow magenta, batch purple) with handles still at the icon column + the TOP flare,
but NO ELK port (the compound-port crash — see graph/). Icon is always the host's KIND
(`groupIconFor`); behavior rides the rail. The `ChipRail` straddles the top border in both
states: loop = amber ↻, batch = `×{count}`/`×N` (count statically unknowable → the source rides
the tooltip), + the group count-expander (the one SQUARE chip = button; round = info). Live
run-status is NOT here — it ships as the corner `StatusBadge` (below); the rail's old
"reserved status-chip slot" was retired (Task 173). `.node.compact/.detailed` are BOTH
`overflow: visible` for it (detailed was silently clipping the deck). Batch cards + `.batched`
leaves draw a stacked DECK via pseudo-elements.

**Container click = SELECT** (focus + ReadPanel via the group's HOST node); the ONLY single-click
toggle is the rail's count-expander (its `stopPropagation` is load-bearing) + double-click
(`zoomOnDoubleClick={false}`). In beautiful, selecting a container also expands its IO rows so
revealed bindings land row-to-row (the `expandTargets` policy, graph/) — node-level they'd
dedupe into one mislabeled line. *Interacts with:* `graph/focus` (unit selection semantics);
`graph/io` (`shellBatchIds` — a shell batch group never renders).

## IO rows render (`IOCardNode`, `PortRows`)

IO ports render as ROWS on the workflow's own node (the LOGIC + strict-side rule is in
`graph/io`; this folder renders them). A ROOT wrapper → a standalone IO CARD (tile +
INPUTS/OUTPUTS + a `"14 inputs"` pill; click SELECTS + opens `IoPanel`); a NESTED wrapper → rows
on the workflow GROUP (collapsed: two-column, outputs BOTTOM-ANCHORED — the in→out diagonal IS
the information; expanded region: inputs LEFT SIDEBAR, outputs bottom-right strip, shown whenever
open in BOTH densities). Rows speak `name: type` via the shared `.row-type` suffix. **ALL rows
speak ONE connection language:** wired = teal name + live dot, unwired/static = muted + quiet
dot (a dynamic param, a read output, a wired io row, all identical). An io row's wiring is
SIDE-AWARE (`Port.receives`/`feeds`). CSS-order trap: `.port-handle`'s teal MUST come AFTER the
generic `.handle` rule (equal specificity); the OUTER io dot offsets onto the border via
`--io-inset`. Edge handle resolution is owner-aware (rows hidden → node-level, never a missing
handle). Clicking a row focuses just that PORT (`focusPort` → `focusedPortId` highlights the row),
driven through the `InteractionContext` so node `data` stays callback-free.
*Interacts with:* `graph/io` (`wrapperPorts`/`ioOwners`); the `io-flow:` skeleton edges
join the cards to the spine.

## Panels (`ReadPanel`, `EdgePanel`, `IoPanel`, `Chip`, `PanelHeader`)

Click-to-read off the inline `/api/graph` payload (no on-demand fetch). `ReadPanel` (a node's
full detail: params/prompts/code, source `file:line`, loop/batch/io config, + the
`CachedPrefixBlock` and `BatchItems` listings) and `IoPanel` (the workflow's interface — per
input: type/required/default/description + consumer chips; per output: producer chip + read
field + source line; an input with no data-flow edge shows no "used by" — quiet ≠ unconsumed)
share `PanelHeader` (a large node avatar + name-as-navigate button). An IoPanel port's TWO
links: the source `file:line` opens the source pane at the PORT's own line (`onOpenSource(ref)`
→ GraphView's `sourceJumpTarget` — io selections set no selectedNode, so the jump carries an
explicit ref). `sourceJumpTarget` is a one-shot the pane re-fires on every MOUNT (SourcePane is
conditionally rendered — `prevJump` reseeds to null), so `changeSourceOpen` MUST clear it on
close or a bare Rail-toggle reopen lands on the stale target instead of the current selection.
The dot-prefixed field (`.stdout`) SELECTS the producer (both `onNavigate`
args — opens its ReadPanel, the recorded output's home; deliberately more than the chip beside
it). EVERY value box carries the ⛶ expand — it lives in `CodeBlock` itself (params, code,
prompts, batch items, errors, run values — one seam): a portaled full-screen modal
(`.value-modal-overlay`, in the scoped chrome-token list) with the value un-capped — Esc /
backdrop / × close; the panel box itself stays scroll-capped at 320px. On open it moves focus
to the × (so Esc works without a prior click) and locks page scroll behind the overlay,
restoring both on close (mount-only effect — the inline `onClose` gets a fresh identity each
render, so re-running it would re-steal focus). `expandLabel` titles
the modal (default "value"); `expandLabel={null}` disables it (the modal's own inner
CodeBlock — the recursion guard); an empty value renders no button. The modal is a READING
surface: a caller still holding the structured value can replace its content via `modalBody`
— `RunValue` uses it to expand a DICT run value as a per-field document (labeled blocks,
strings as REAL text — not JSON `\n` escapes; top-level only, arrays stay JSON; an EMPTY dict
expands to plain `{}`, never a blank document). The string-vs-JSON derivation is single-sourced
in `RunValue`'s `fieldCode` helper, shared by the compact box and each doc field. Deliberately
RunValue-only: authored params must render exactly as authored (a literal `\n` in a code
param is content), and the compact box stays JSON (it answers "what shape", the modal "what
does it say"). `EdgePanel` reads a
contract edge by id: five variants (data / branch+decision-end / error / static-end /
sequential) — the data variant has a CACHE arm (`input_name === "prompt_cache"`: "cached
context", never a param binding). RF native selection stays inert — components ignore the
`selected` prop, and `deleteKeyCode={null}` (Backspace would otherwise delete from the store).
All single-subject panels share `.read-panel` (width rides `--panel-w`, `PanelResizer` drag).

- **`Chip` + `ConnectionSections`:** a chip is a mini node avatar (canvas tile + name, category
  on the tooltip); a nested io-port chip is scope-prefixed. Chips NAVIGATE WITHOUT OPENING
  (`onNavigate(id)`, no selectedId): focus + camera follow, the open panel never swaps — click
  the centered node to open it. `ConnectionSections` (the ReadPanel tail): `references (N)` then
  `referenced by (N)` chip stacks from contract data-flow edges (empty direction → nothing; a
  GROUP HOST aggregates as a black box over its port members). *Interacts with:* the
  io-port→owner resolution and the deferred follow live in `hooks/useCameraNavigation`.

## Hover (`interaction.ts` + the components that read it)

HOVER marks a SET of canvas subjects — a PURE highlight (no focus change, no expansion, no
camera move). A panel CHIP marks its one node; a canvas ROW marks every edge landing on it + each
far end (the mark set is `rowTouches` from `graph/focus`, over the resolved FLOW edges — never a
contract re-derivation). Nodes ring (`.hover-mark` — must stay after `.node.dimmed` in the
sheet); edges light with the selected treatment minus the elevation. Marks wipe on any
focus/selection/structure change.

## Authored-text rendering (`Markdown`, `CodeBlock`, + `utils/`)

Three treatments, one per surface class:
- **RENDER** — prose descriptions render as real markdown via `Markdown` (react-markdown +
  remark-gfm; raw HTML stays text, images alt-only — workflows are THIRD-PARTY content, no
  `innerHTML` anywhere; catalog uses INLINE mode).
- **HIGHLIGHT** — `CodeBlock` renders a param value via the `utils/highlight.ts` shiki seam +
  `paramLanguage` (the lazy / fail-closed seam + language policy: see utils/CLAUDE.md). Prompts
  color as markdown SOURCE, never rendered; markdown/plain values teal every `${ref}`,
  code/yaml/json don't.
- **STRIP** — canvas lines + tooltips use `stripMarkdown` (utils/format.ts — markers hidden,
  more conservative than CommonMark; see utils/CLAUDE.md).

## Source pane (`SourcePane` + `graph/sourceDecorate.ts`)

Verbatim authored `.pflow.md`, one file at a time, colored in the CANVAS language. `GraphView`
fetches `/api/source` beside `/api/graph` (one snapshot → no line-mapping drift). Selection
auto-switches files; breadcrumbs describe the invocation chain; line clicks resolve via
`utils/sourceMap.ts` (`nodeAtLine`) through `resolveEndpointFlatId`. Coloring is per-segment
(`sourceDecorate.ts`, a pure graph/ module): a whole-file shiki pass can't recognize the
role-only fences (`prompt`/`command`/`cache`), so a length-aware fence parser infers grammar
(`prompt`/`cache`→markdown, `command`→bash) — instant sync pass then an async shiki content
upgrade, line-count asserted (the pane is line-number-keyed). NO diff view belongs here (this is
comprehension-only; the IDE staging loop is the approval surface).
