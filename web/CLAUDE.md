# pflow Web UI frontend (`web/`)

Browser SPA for `pflow ui`: **Vite + React 18 + React Flow v12 (`@xyflow/react`) +
ELK (`elkjs`)**. It fetches the typed JSON contract the Python server emits and
draws an interactive workflow canvas. Build output → `../src/pflow/ui/static/`.

The contract is defined in Python (`../src/pflow/core/workflow/graph/renderers/
react_flow.py`) and the rendering rules the transform must honor are documented in
`../src/pflow/ui/CLAUDE.md`. `src/types.ts` hand-mirrors the contract — **read
those two before changing `graph/`.**

**Per-folder detail lives in subfolder CLAUDE.mds** (each auto-loads alongside this one
when you touch its files, so the invariants below are stated once here and only
*referenced* there):

- `src/graph/CLAUDE.md` — the pure transform (rows model, edge routing, layout /
  auto-direction / SPINE, IO logic, focus policy, the elkjs gotchas).
- `src/components/CLAUDE.md` — the React render (nodes, edges, containers, panels,
  hover, authored-text, source pane).
- `src/hooks/CLAUDE.md` — the runtime machinery (pipeline, layout cache, camera,
  animation, the live-source poll/reload).
- `src/utils/CLAUDE.md` — pure helpers (color/text, the shiki seam, URL/deep-link,
  source mapping, batch items).
- `src/views/CLAUDE.md` — the two screens (CatalogView, GraphView): the canvas wiring hub —
  view state, the selection→panel model, the per-workflow one-shot effects.

## Where things live (and where new code goes)

Each folder is one role; add code to the slot that matches it.

```
src/
  main.tsx           entry — injects metrics.ts CSS vars on :root, mounts <App> in <ErrorBoundary>
  App.tsx            shell: ?workflow= URL param → <GraphView>, else <CatalogView>
  index.css          all styles (one sheet; theme vars at :root — geometry vars are
                     INJECTED from graph/metrics.ts, never hardcoded here)
  types.ts           the wire contract (mirrors react_flow.py) — imported everywhere
  api/               server communication (client.ts: fetch + ApiError + fetchVersion,
                     the source-watch poll; a live /events subscription would go here)
  graph/             PURE contract → React Flow transform; NO React (tests run node-env).
                     flow.ts is the FAÇADE (re-exports the siblings); the DAG is
                     scan → io → rows → focus/flow.  >> src/graph/CLAUDE.md
  hooks/             useWorkflowGraph / useCameraNavigation / usePanelPair / useSourceWatch
                     — fetch→build→layout→focus, camera, panes, watch.  >> src/hooks/CLAUDE.md
  utils/             pure helpers: color/text (format.ts), the shiki seam (highlight.ts),
                     URL/deep-link (viewParams.ts), source mapping (sourceMap.ts), pane
                     clamp (panelWidth.ts), icons, batch items.  >> src/utils/CLAUDE.md
  views/             the screens App switches between (CatalogView, GraphView).  >> src/views/CLAUDE.md
  components/        React render: nodes/ (WorkflowNode, GroupNode, IOCardNode, EndNode,
                     PortRows, BranchPorts, ChipRail), edges/ (GradientEdge, DataEdge,
                     LoopEdge, EdgeHalo), panels (ReadPanel, EdgePanel, IoPanel, Chip,
                     PanelHeader, Markdown, CodeBlock, BatchItems), shell (Toolbar,
                     ErrorBoundary, SourcePane, PanelResizer), interaction.ts (the
                     click-callback context + hover-set channel).  >> src/components/CLAUDE.md
  test/              rf-jsdom.ts — React Flow jsdom mocks; fixtures/contracts/ — real
                     /api/graph payloads, drift-guarded by a Python test
```

Tests sit beside their subject.

## Cross-cutting invariants (every folder obeys these)

- **`graph/` is PURE — no React.** The transform is plain functions, so its tests run
  node-env (no jsdom) and stay fast. Keep hooks/components out of it; keep the transform
  out of the components.
- **Build and focus are separate passes.** `buildFlow` produces the structural nodes/edges
  ELK lays out; `applyFocus` is a cheap restyle (dim/reveal/select) with **no re-layout**.
  Collapse / density / direction re-run layout; clicking a node does not (the one exception —
  focus-EXPANSION in beautiful — is in `hooks/CLAUDE.md`). The laid-out nodes and their edges
  are kept as one snapshot so focus never restyles edges against stale node positions.
- **The handle/edge contract** (the recurring bug class):
  1. An edge handle must EXIST on its node **and be the right TYPE** or React Flow silently
     drops the edge — no error. Each handle id encodes a fixed type via `handleType`
     (`graph/handles.ts`): a `sourceHandle` must resolve to "source", a `targetHandle` to
     "target". A per-row handle is emitted only when its row renders, else the edge falls back
     to `NODE_IN`/`NODE_OUT`.
  2. Edges are **ADDITIVE** — an endpoint hidden by collapse or a suppressed group-host
     re-anchors to a visible ancestor, never dropped; a missing anchor **warns**, never
     silently drops.
  3. React Flow draws **ALL edges BEHIND nodes** in one SVG layer, so a stock edge is painted
     over at the box edge — any line-flowing-*into*-the-icon (the connector flare) must be
     **our own geometry**, never a built-in edge.
- **jsdom renders ZERO edge DOM** (and logs no handle error), so any "no edge errors"
  assertion under jsdom is theater. **Edge integrity is a pure `graph/flow.test.ts` test**
  (the HANDLE-TYPE INVARIANT), never a render test.
- **Density governs edges.** Advanced shows every edge. Beautiful shows only the control-flow
  skeleton — data-flow (`${ref}`) edges are built but `hidden`, and a focus REVEALS just the
  clicked node's data lines. Hidden data edges still go to ELK (only self-loops are excluded),
  so the layout reflects ALL structure in both densities. (The two densities are named
  **advanced** = the `detailed` node / **beautiful** = the `compact` node — same two states,
  one vocabulary; `.node.detailed`/`.compact` are the code names.)
- **Geometry is single-sourced.** Layout-coupled constants live ONLY in `graph/metrics.ts`;
  `main.tsx` injects them as `:root` CSS vars before first paint. CSS must never hardcode them
  (a TS↔CSS dual-source is what drifted historically). `src/cssOrder.test.ts` pins the two
  equal-specificity rule pairs where source order decides paint.
- **Errors never blank the canvas.** `ErrorBoundary` catches any render throw; the `status`
  machine and its fetch/layout failure handling live in `hooks/` (useWorkflowGraph).
- **Predicates are Python facts; visual policy is TS.** `is_decision`/`is_terminal`/`shadowed`/
  `is_transform` ship as booleans from the contract; the frontend decides treatment. Don't
  re-derive them in JS.
- **Overlay-ready seam.** Node components keep static data separate from a future `status`
  prop; `api/` is the single data-loading point a live stream plugs into. Every React Flow
  component the registries reference must be `memo()`'d.
- **Chrome palette is SCOPED, never `:root`.** The dark UI tokens (`--bg/--border/--text/
  --accent/--bg-field`, surface ladder `#0d0d0d` void < `#151515` panel < `#1c1c1c` field) are
  redefined on the chrome containers (`.toolbar/.read-panel/.source-pane/.catalog/.banner/
  .canvas-overlay/.react-flow__minimap/-controls`) — NOT `:root`, because the RF node/edge layers
  share those names and a `:root` redefine recolors the CANVAS. `body` bg is a LITERAL `#0d0d0d`
  (a canvas ancestor — a token would inherit into nodes). Adding a chrome surface → add it to that
  selector list or it renders with stale `:root` values. The source-row selection tint
  (`.src-line-active/-block`) keeps blue `#6ea8fe`, not the orange `--accent` (selection ≠ accent).
- **The chrome rail is a floating capsule of ACTIONS & TOGGLES (`components/Rail.tsx` +
  `RailSearch.tsx`), never a node palette** (read-only viewer). Rendered INSIDE `.canvas`
  (position-relative) so it anchors to the canvas's LEFT edge — far-left when the source pane is
  closed, right of the pane when open. Holds **search**, the **markdown** source toggle, the
  **sub-workflow** expand toggle, and **clear focus**; the back-nav + the mode pills
  (advanced/beautiful, LR/TD) stay in the Toolbar (labeled pills keep "which mode am I in"
  legible — an icon would lose it). Toggle glyphs speak the CANVAS language and light on enable
  (`markdown.svg`/`subworkflow.svg`, grey → identity-color via a CSS `grayscale` filter lifted on
  `.active`; `.rail` is in the scoped-chrome token list but NOT a parent of RF nodes, so it's
  safe). Top slot reserved for the future run/status control.
- **Search (`RailSearch.tsx`) is REVEAL-then-node-click.** Ranks node_id prefix > substring >
  purpose; selecting → `GraphView.onSelectNode` expands the target's collapsed ancestor chain (so
  a buried node is reachable) then `onNavigate(repId, repId)` — the SELECTION arm (not a bare
  focus) is what opens the read panel AND scrolls the source pane (`selectedNode → activeLine`).
  `nodeRepresentativeId` (utils/viewParams) resolves a host → its group; Cmd/Ctrl+K toggles search
  (a global keydown the component owns; `preventDefault` stops Chrome's omnibox).

## Dev, build, test

- **Dev:** run `uv run pflow ui --no-open` and `cd web && npm run dev`; Vite proxies
  `/api` → `127.0.0.1:8765` (override with `PFLOW_UI_PORT`).
- **Build:** `make ui-build` (`npm ci && npm run build`) → `../src/pflow/ui/static/`
  with `base:"./"`. `npm run build` runs `tsc --noEmit` first (strict).
- **Test:** `npx vitest run`. `graph/`/`utils/`/`api/` are node-env; component/hook tests
  are jsdom (`// @vitest-environment jsdom`) using `test/rf-jsdom.ts`. Real-browser geometry
  invariants (dots-on-border, edge coverage, no-overlap) live in the screenshot skill's
  `visual-invariants.pflow.md`, not vitest.
- **`?raw` CSS trap (cssOrder.test.ts):** it reads `index.css` via `node:fs`, NOT
  `import ... from "./index.css?raw"` — vitest's default `css: false` stubs `.css` imports to
  an empty string EVEN under the `?raw` query (probed on vitest 4.1.8; `test.css: true` would
  fix it but enabling CSS processing for every test to prettify one import isn't worth it).
- **Packaging gotcha:** the bundle is gitignored and hatchling honors `.gitignore`, so
  `pyproject.toml` needs `[tool.hatch.build.targets.wheel] artifacts =
  ["src/pflow/ui/static/**/*"]` to ship it in the wheel — don't remove it.
  `web/package-lock.json` is committed (CI `npm ci`); `node_modules`/`dist` are not.
