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
  utils/             pure helpers — format.ts (${ref} parsing, value previews, kind
                     colors, category label); icons.ts (node-kind/provider → SVG URL)
  assets/icons/      vendored brand/tool SVGs (Vite bundles them into static/assets)
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
- **One node component, two densities.** `WorkflowNode` is the single leaf component
  (React Flow node `type: "node"`); `density` rides in `data`. The card is colored **by
  type**: the kind color in the border + a faint kind-tinted bg — the same color the
  node's edges use (Option B keeps the tile/icon in the icon's **native** color, so the
  type color lives in the border). **Both** densities show the **category (type)** line
  + the **description** (`purpose`, or `node_id` when absent), which wraps to ≤2 lines;
  `node_id` (the `${ref}` key) is on the tooltip + in the read panel. *Advanced*
  (`detailed`) adds the body (param rows with per-row target handles + output ports).
  Fork outcomes show as labeled border handles in **LR** (both densities) or fan from the
  icon column in **TD** (see the control-edge note). Toggling density re-renders the one
  component (no node-type swap). Beautiful node height is a FIXED `HEADER_HEIGHT` (68px) —
  the 56px tile dominates any 2-line description, so the tile stays vertically **centered**
  (the connector stubs anchor to that via `calc(50% ± Npx)` — don't let the header grow);
  advanced adds body rows. Keep `leafSize` in step with the DOM or ELK overlaps. Icons come
  from `utils/icons.ts`: one map keys a node `kind` →
  SVG; `llm` resolves from its `model` param's `provider/` prefix (default: a sparkle).
  Add a node-kind icon in that one file.
- **Density controls edges, not just node detail.** *Advanced* shows every edge.
  *Beautiful* shows only the control-flow skeleton: data-flow (`${ref}`) edges are built
  but `hidden`, and `applyFocus` reveals just the clicked node's data lines (hidden
  ones are also excluded from ELK so the layout stays tight). `applyFocus` reveals any
  default-hidden edge incident to the focus, so it needs no density flag — only
  `buildFlow` sets the default.
- **Control edges are gradients; no arrowheads; forks differ by direction.**
  Sequential/branch edges get `type: "gradient"` (`components/edges/GradientEdge.tsx`) —
  a `userSpaceOnUse` SVG gradient blending the **source** → **target** node color along
  the true edge direction (both colors in `edge.data`; **3px** to match the node border,
  so a line flows seamlessly into the same-color rounded border). **No arrowheads** (clean
  lines into the borders). Data/error/end stay React Flow's `"default"` edge, stroked by
  CSS. **Never set `stroke` in CSS for `edge-sequential`/`edge-branch`** — the component
  owns it; CSS would override the gradient. Dash (branch) + shadow/dim opacity ARE CSS
  (separate properties). **Forks:** in **LR** a branch leaves a labeled border handle
  (`BranchPorts`, n8n-style). In **TD** the control handles (`NODE_IN`/`NODE_OUT`) AND the
  forks all align to the **icon column** (`WorkflowNode` offsets them ~36px from the left),
  so the trunk + forks flow through the icon; a fork's label then rides its edge
  (GradientEdge renders it) instead of a border row, and `BranchPorts` draws nothing.
- **🚧 Icon connector stub (UNFINISHED — see the progress-log HANDOFF).** In TD+beautiful a
  kind-colored SVG stub (`Connector` in `WorkflowNode`; `CONNECTOR_TOP/BOTTOM` paths; CSS
  `.node-connector*`) should bridge the control edge **into the icon tile** — one per side, only
  if `hasIncoming`/`hasOutgoing` (computed in `flow.ts buildFlow`). The stub OWNS its `Handle` (at
  the tip) so the edge meets it. **Known constraint:** React Flow draws edges *behind* nodes, so
  the line-into-the-icon must be our geometry, never a stock edge. **Still broken:** gaps between
  the stub↔edge and stub↔tile, and the flare proportions — **debug in a real browser** (the model
  calc'd right but renders wrong; likely a RF handle-measurement issue for a handle nested in a
  transformed container that extends outside the node box). Fallbacks: put the handle back on the
  border + stub bridges inside; or elevate the edge `zIndex`.
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
