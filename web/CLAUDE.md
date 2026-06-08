# pflow Web UI frontend (`web/`)

Browser SPA for `pflow ui`: **Vite + React 18 + React Flow v12 (`@xyflow/react`) +
ELK (`elkjs`)**. It fetches the typed JSON contract the Python server emits and
draws an interactive workflow canvas. Build output → `../src/pflow/ui/static/`.

The contract is defined in Python (`../src/pflow/core/workflow/graph/renderers/
react_flow.py`) and the rendering rules the transform must honor are documented in
`../src/pflow/ui/CLAUDE.md`. `src/types.ts` hand-mirrors the contract — **read
those two before changing `graph/`.**

## Where things live (and where new code goes)

Each folder is one role; add code to the slot that matches it.

```
src/
  main.tsx           entry — <ErrorBoundary> wraps <App>
  App.tsx            shell: ?workflow= URL param → <GraphView>, else <CatalogView>
  index.css          all styles (one sheet; CSS vars at :root)
  types.ts           the wire contract (mirrors react_flow.py) — imported everywhere
  api/               server communication (client.ts: fetch + ApiError; a live /events
                     subscription would go here)
  graph/             PURE contract → React Flow transform; NO React (tests run node-env)
    flow.ts          buildFlow (nodes/edges) + applyFocus; size constants
    layout.ts        ELK positioning (the only async step)
    handles.ts       handle-id scheme
  hooks/             useWorkflowGraph: fetch → build → layout → focus → RF state + status
  utils/             pure helpers (format.ts: ${ref} parsing, value previews, glyphs)
  views/             the screens App switches between (CatalogView, GraphView)
  components/         reusable UI: Toolbar, ReadPanel, ErrorBoundary, nodes/, edges/
  test/              rf-jsdom.ts — React Flow jsdom mocks for component tests
```

Tests sit beside their subject.

## Concepts that aren't obvious from the code

- **`graph/` has no React.** The transform is pure functions, so its tests run in
  node-env (no jsdom) and stay fast. Keep hooks/components out of it.
- **Build and focus are separate passes.** `buildFlow` produces the structural
  nodes/edges that ELK lays out; `applyFocus` is a cheap restyle (dim/reveal) with **no
  re-layout**. Collapse / density / direction re-run layout; clicking a node does not.
  `useWorkflowGraph` keeps the laid-out nodes and their edges as one snapshot so focus
  never restyles edges against stale node positions.
- **An edge handle must exist on its node — and be the right TYPE — or React Flow
  silently drops the edge.** This is the recurring bug (it bit us twice). `flow.ts` only
  emits a per-row handle when a matching row exists, else falls back to `NODE_IN`/`NODE_OUT`.
  Each handle id encodes a fixed type via the scheme (`handleType` in `handles.ts`): a
  `sourceHandle` must resolve to "source", a `targetHandle` to "target". The
  HANDLE-TYPE INVARIANT test (`flow.test.ts`) enforces this — **jsdom CANNOT** (React
  Flow renders no edge DOM under jsdom, so any "no edge errors" assertion there is
  theater). Edge integrity is a pure `flow.ts` test, never a render test.
- **Edges are additive.** An endpoint hidden by collapse or a suppressed group-host
  re-anchors to a visible ancestor — never dropped. A missing anchor is a bug and
  `flow.ts` warns instead of dropping it.
- **Density controls edges, not just node detail.** *Advanced* shows every edge.
  *Beautiful* shows only the control-flow skeleton: data-flow (`${ref}`) edges are built
  but `hidden`, and `applyFocus` reveals just the clicked node's data lines (hidden
  ones are also excluded from ELK so the layout stays tight). `applyFocus` reveals any
  default-hidden edge incident to the focus, so it needs no density flag — only
  `buildFlow` sets the default.
- **A loop is drawn, not in the contract.** A loop is a `LoopSpec` on a node;
  `flow.ts` synthesizes a self-loop edge (`type:"loop"`) anchored to the node or its
  group, and `components/edges/LoopEdge.tsx` draws the arc + label. Self-loops are
  filtered out of ELK.
- **IO is ONE node, with row-level focus.** An `input_wrapper`/`output_wrapper` group
  becomes a single Inputs/Outputs `ports` node (`PortsNode`) — a row per port, the IO
  member nodes are NOT emitted. Each row carries BOTH handles: a *target* (`portTargetHandle`
  — receives: input bound from parent, output written by a producer) and a *source*
  (`portHandle` — feeds: input → consumers, output → parent). A port bridges two scopes,
  so dropping either side silently loses the binding edges. **Every edge carries its
  original endpoints (`data.from`/`data.to`)**, so `applyFocus` can reveal a *single*
  port's lines even though its edges re-anchor onto the shared ports node; clicking a row
  focuses that port id via the `InteractionContext`. Decision forks render as labeled
  border handles (`branchHandle`) in both densities; in beautiful, a revealed data line is
  labeled with what flows (`output_field → input_name`).
- **Errors never blank the canvas.** `useWorkflowGraph`'s `status`
  (`loading`/`ready`/`empty`/`error`) drives a banner; a malformed 200 throws from
  `fetchGraph` (caught), an ELK failure becomes an error (not a stuck spinner), and any
  other render throw hits `ErrorBoundary`.
- **Overlay-ready seam.** Node components keep static data separate from a future
  `status` prop; `api/` is the single data-loading point a live stream plugs into.

## Dev, build, test

- **Dev:** run `uv run pflow ui --no-open` and `cd web && npm run dev`; Vite proxies
  `/api` → `127.0.0.1:8765` (override with `PFLOW_UI_PORT`).
- **Build:** `make ui-build` (`npm ci && npm run build`) → `../src/pflow/ui/static/`
  with `base:"./"`. `npm run build` runs `tsc --noEmit` first (strict).
- **Test:** `npx vitest run`. `graph/`/`utils/`/`api/` are node-env; `GraphView.test.tsx`
  is jsdom (`// @vitest-environment jsdom`) using `test/rf-jsdom.ts`.
- **Packaging gotcha:** the bundle is gitignored and hatchling honors `.gitignore`, so
  `pyproject.toml` needs `[tool.hatch.build.targets.wheel] artifacts =
  ["src/pflow/ui/static/**/*"]` to ship it in the wheel — don't remove it.
  `web/package-lock.json` is committed (CI `npm ci`); `node_modules`/`dist` are not.
