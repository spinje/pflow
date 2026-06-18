# Views (`web/src/views/`)

The two screens `App` switches between by the `?workflow=` URL param: `CatalogView` (the
saved-workflow list) and `GraphView` (the per-workflow canvas). This is the WIRING layer — it
owns view STATE and composes the pieces; the heavy lifting lives elsewhere.

> Read `web/CLAUDE.md` (web root) FIRST for the cross-cutting invariants (build vs focus are
> separate passes; the handle/edge contract; predicates are Python facts; hover marks a SET, a
> pure highlight). The data pipeline / camera / panes are HOOKS (`hooks/CLAUDE.md`); the panels,
> nodes, and the interaction context are COMPONENTS (`components/CLAUDE.md`). GraphView
> ORCHESTRATES them — it doesn't re-implement them.

## CatalogView

Fetches `/api/catalog`, lists workflows, click → `?workflow=` (App swaps to GraphView). Trivial.

## GraphView — the canvas wiring hub

Pure presentation + interaction. It owns the **view state** (the source-of-truth `useState`s:
`density` / `direction` / `collapsed` / `focus` / `selectedId` / `hovered` / `sourceOpen`), the
React Flow surface (module-level `nodeTypes`/`edgeTypes`), the three side panels, and the
interaction wiring. `useWorkflowGraph` (pipeline), `useCameraNavigation` (camera), and
`usePanelPair` (panes) are hooks consuming that state — their internals are in `hooks/CLAUDE.md`.

The load-bearing structural facts (everything else is in the inline comments):

- **One `selectedId`, three panels, disjoint by id namespace.** A selection resolves to exactly
  one of: a node OR a container (→ its HOST node) → `ReadPanel`; a root IO wrapper group →
  `IoPanel`; a contract edge → `EdgePanel`. The id namespaces never overlap (`n*` nodes, `g*`
  groups, contract edge ids, synthesized `io-flow:`/`loop:` ids — the last have NO panel by
  design). A new selectable thing MUST keep its namespace disjoint, or two panels race.
- **Ref-frozen one-shot-per-workflow effects.** auto-direction (`graph/direction.ts`),
  auto-collapse (`graph/collapse.ts`), and the live-reload selection/collapse remap
  (`graph/remap.ts`) each fire ONCE per workflow, `useRef`-guarded — so a live-source reload never
  re-rotates, re-collapses, or loses the held selection. auto-direction and the remap run in
  `useLayoutEffect` (pre-paint, no visible wrong-state frame).
- **React Flow's native selection is inert** (`deleteKeyCode={null}`,
  `nodesDraggable`/`nodesConnectable` off): the styling truth is `applyFocus`-written
  `data.selected`, not RF's own selection — so Backspace can't delete an element from the store.
- **The interaction context is created here** (`focusPort` / `toggleGroup` / `hoverNode` /
  `hoverRow`) and provided to the node tree via `components/interaction.ts`, keeping node `data`
  callback-free. `focusPort` no-ops on a nested port with no line in view (the into-nowhere click).

`GraphView.test.tsx` (jsdom) exercises click→selection→panel and the one-shots, but NOT edges
(jsdom renders no edge DOM); the edge-click three-way dispatch is pure-tested in
`utils/viewParams.test.ts`.
