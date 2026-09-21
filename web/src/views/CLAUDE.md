# Views (`web/src/views/`)

`App` uses `?workflow=` to choose CatalogView (saved workflows) or GraphView (canvas).
GraphView owns view state, React Flow registration, panels and interaction wiring; data/camera/pane
behavior belongs to `hooks/`, rendering to `components/`.

## Selection and interaction

- `selectedId` resolves to one panel: node/container host → ReadPanel; root IO wrapper → IoPanel;
  contract edge → EdgePanel. Keep selectable namespaces disjoint.
- `../utils/viewParams.ts:edgeClickAction` has three cases: contract edges open EdgePanel; synthetic
  `loop:` edges select their source node and open that node's panel; synthetic `io-flow:` edges
  focus the edge and clear the panel. Synthetic edges have no EdgePanel of their own.
- Styling uses `applyFocus`-written `data.selected`, not React Flow's native selection.
  Keep `deleteKeyCode={null}` and node dragging/connecting disabled so Backspace cannot remove
  elements from the store.
- GraphView creates `../components/interaction.ts` context to keep callbacks out of node data.
  `focusPort` no-ops for a nested port with no visible line. Search uses `../graph/collapse.ts:revealNodes`
  before selecting so the selected target has a visible representative.

## Defaults, reloads and runs

Initial direction (`../graph/direction.ts:autoDirection`) and collapse (`../graph/collapse.ts:initialCollapsed`)
are frozen per workflow. On each replacement graph, the `prevGraphRef` layout effect remaps held
focus/selection/collapse via `../graph/remap.ts` before paint; flat IDs may renumber after every edit.
Auto-direction also runs before paint; initial collapse uses its own one-shot effect.

Gate/run overlays stay outside `selectedId`. They share `selectRun` as the pin path and resolve
structural anchors each render rather than caching flat IDs. When synthesizing paused status,
merge into an existing entry so recorded metrics and event identity survive.

SSE subscription handlers dispatch through the stable `pointHandlers` ref. Connection and replay
deduplication belong to `../api/events.ts:subscribe`, not view-effect dependencies.

Source-pane jump lifetime crosses GraphView/SourcePane: closing the pane must clear
`sourceJumpTarget`, or remounting it replays the stale jump (see components guide).

`GraphView.test.tsx` covers selection/panels/defaults; `../utils/viewParams.test.ts` covers edge-click
dispatch. Edge geometry/integrity belongs to graph tests and browser verification, not jsdom.
