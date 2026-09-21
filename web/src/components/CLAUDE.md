# Components (`web/src/components/`)

React rendering consumes structure from `graph/`; it does not re-derive rows, IO ownership,
edge routing, or focus policy.

## Find the rendering concern

- Leaf cards/densities → `nodes/WorkflowNode.tsx`; container cards/regions → `nodes/GroupNode.tsx`.
  Row model and sizes → `../graph/rows.ts`; identity color → `../utils/format.ts:nodeColor`;
  kind/provider icons → `../utils/icons.ts`.
- IO cards and row handles → `nodes/IOCardNode.tsx`, `nodes/PortRows.tsx`;
  static behavior modifiers → `nodes/ChipRail.tsx`; live status → `nodes/StatusBadge.tsx`.
- Control/data/loop paint → `edges/GradientEdge.tsx`, `edges/DataEdge.tsx`, `edges/LoopEdge.tsx`;
  selection/hover under-stroke → `edges/EdgeHalo.tsx`. Lanes/rails belong to `graph/`.
- Node/interface/connection details → `ReadPanel.tsx`, `IoPanel.tsx`, `EdgePanel.tsx`;
  navigation chips and connection sections → `Chip.tsx:Chip`, `ConnectionSections`.
- Value boxes and expansion → `CodeBlock.tsx`; recorded values → `RunValue.tsx`.
- Node callbacks and hover → `interaction.ts`, created by `../views/GraphView.tsx`.
- Anchored overlays → `NodeCallout.tsx`; resume refusals/acknowledgement →
  `resumeAnswer.tsx:useResumeAnswer` and `RefusalNotice` (used by GateCallout/ResumeControl).
- Source display → `SourcePane.tsx`, `../graph/sourceDecorate.ts`, `../utils/sourceMap.ts`.

## Node, handle, and edge constraints

- Density stays in leaf node data, not a React Flow node-type swap. `WorkflowNode` renders the
  shared row model; changing row kinds also affects sizing, ports, and edge landings in graph/.
- Control handles remain direct, untransformed children on the node border. Nesting them inside
  a transformed `Connector` makes React Flow measure the wrong position. The connector is opaque
  decoration overlapping the edge terminus and tile border; keep path, viewBox, and element size
  driven by the same `CONN` geometry.
- `GroupNode` shares one header across collapsed/expanded states; `METRICS.groupHeaderH` must
  match `nodeHeaderH`. Expanded regions still render handles but receive no ELK compound port
  (see graph guide). Both densities need visible overflow for the external chip rail/deck.
- A container click selects it. The count-expander's `stopPropagation` prevents that click from
  selecting as well; double-click toggles with React Flow's double-click zoom disabled.
  Beautiful-mode container selection expands IO rows so revealed bindings retain distinct landings.
- `PortRows` always renders both handles: receive on the left, feed on the right. A quiet role
  hides styling, not the handle element. Ownership and fallback when rows are hidden come from
  `../graph/io.ts` and edge construction. `.port-handle` must follow the equal-specificity generic
  `.handle` rule in CSS or it loses its wiring color.
- Edge components own stroke/color; CSS owns patterns and dimming. Do not put edge-kind stroke
  colors in CSS. Do not dim every `shadowed` control edge: with one edge per reference, this can
  erase most of the control skeleton. `LoopEdge` must not elevate itself through its own label.
  Keep the loop re-entry arrowhead exception; other edges have no arrowheads.

## Selection, panels, and overlays

- Chip navigation focuses/follows without replacing the open panel (`onNavigate(id)`). The
  IoPanel producer-field link deliberately passes selection too, opening the producer's ReadPanel.
  Camera follow and IO-port-to-owner resolution belong to `../hooks/useCameraNavigation`.
- IoPanel source links pass an explicit source ref because IO selection has no selectedNode.
  GraphView must clear `sourceJumpTarget` when closing the source pane: SourcePane remounts on
  reopen and otherwise replays a stale jump instead of following current selection.
- `EdgePanel` treats `prompt_cache` dependencies as cached context, not ordinary param bindings.
- Node data stays callback-free through `InteractionContext`. Hover marks a set without changing
  focus, expansion, or camera: `../graph/focus.ts:rowTouches` uses resolved flow edges. Clear marks
  on focus/selection/structure changes. `.hover-mark` must follow `.node.dimmed` in CSS; hover
  does not inherit selected-edge elevation.
- Resume refusal UI consumes machine-readable fields, not diagnostic text. Send `force: true`
  only after explicit acknowledgement through the shared resume-answer state machine.

## Authored text and source

- Descriptions render through `Markdown`; prompts/parameter source through `CodeBlock` and
  `../utils/highlight.ts`; canvas labels/tooltips through `../utils/format.ts:stripMarkdown`.
- Workflow content is third-party input. Keep raw HTML as text and images alt-only; do not add
  innerHTML or remote image fetching. Catalog markdown flattens links because rows are buttons.
- A syntax-highlight upgrade must preserve every selected-reference mark. CodeBlock checks the
  exact mark count before replacing plain rendering; best-effort teal decoration is separate.
  Highlighting failure falls back to plain text (see utils guide).
- `RunValue` owns structured runtime-value presentation. Do not apply its display normalization
  to authored parameters: literal escape sequences in code are content.
- Full-screen value overlays portal outside panel overflow. Their chrome tokens must still be
  scoped explicitly; do not move tokens to `:root` to style the portal.
- GraphView reloads source alongside graph data so source mapping does not stay on an old file.
  `../graph/sourceDecorate.ts` handles role-only fences (`prompt`/`command`/`cache`) that a whole-file
  grammar cannot infer. Preserve authored text and line count: SourcePane navigation is line-keyed.
  This is a comprehension surface; the IDE staging loop remains the diff/approval surface.
