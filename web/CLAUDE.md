# pflow Web UI frontend (`web/`)

Browser SPA for `pflow ui`: Vite, React 18, React Flow v12 (`@xyflow/react`), and ELK
(`elkjs`). Build output goes to `src/pflow/ui/static/`. `src/App.tsx` switches between the
catalog and a workflow at `/?workflow=<name|path>`; `src/main.tsx` mounts the app.

The wire contract is defined in `src/pflow/core/workflow/graph/renderers/react_flow.py`
and hand-mirrored in `src/types.ts`. Before changing the graph transform, read both and
`src/pflow/ui/CLAUDE.md` → RFGraph contract and rendering seam.

## Navigation

- `src/graph/CLAUDE.md` — graph construction, rows, handles, layout, IO ownership, focus.
- `src/components/CLAUDE.md` — nodes/edges, panels, authored text, source pane.
- `src/hooks/CLAUDE.md` — layout snapshots, camera timing, panes, source reload.
- `src/utils/CLAUDE.md` — colors/text, highlighting, URL and source mapping.
- `src/views/CLAUDE.md` — selection, overlays, per-workflow defaults and reload remapping.
- HTTP → `src/api/client.ts`; SSE reconnect/catch-up → `src/api/events.ts:subscribe`;
  command handlers and run selection → `src/views/GraphView.tsx`.

## Cross-folder constraints

- **`graph/` is pure:** no React or component state. Components consume its structure.
- **Build and decoration are separate.** `buildFlow` creates the structure ELK lays out;
  `applyFocus` restyles it without layout. Beautiful-mode focus expansion is the exception:
  changed card sizes require a rebuild/layout and camera anchoring (see hooks guide).
  Nodes and edges must be decorated from the same laid-out snapshot.
- **Handles must exist and have the right type.** `src/graph/handles.ts:handleType` is the
  authority: a source edge endpoint needs a source handle, a target needs a target handle.
  A hidden row requires an existing fallback handle; React Flow silently drops invalid edges.
- **Represented connectivity survives hiding.** Collapse or group-host suppression re-anchors
  endpoints to visible representatives; missing anchors warn rather than silently disappearing.
- **Edges paint behind nodes.** A connector that appears to enter an icon needs component-owned
  decorative geometry; a stock edge is covered by the node box.
- **Density affects visibility, not dependency layout.** Advanced (`detailed`) shows all edges;
  beautiful (`compact`) hides data-flow edges until focus reveals relevant lines. Hidden data
  edges still inform ELK; self-loops are excluded.
- **Shared TS/CSS geometry comes from `src/graph/metrics.ts`.** `src/main.tsx` injects its CSS variables
  before mount. Do not hardcode a second copy in CSS. TS-only sizing estimates live in
  `src/graph/rows.ts` and `src/graph/layout.ts`. `src/cssOrder.test.ts` guards sensitive rule ordering.
- **Python owns graph facts; TS owns visual policy.** Consume `is_decision`, `is_terminal`,
  `shadowed`, and `is_transform` rather than re-deriving them. Control-sink routing has a
  different definition from `is_terminal` (see graph guide).
- **Scope chrome tokens to chrome containers.** Moving them to `:root` recolors the canvas
  through inheritance.
- **Search reveals before selecting.** Expand collapsed ancestors before selection opens a
  panel and coordinates camera/source navigation.
- Register memoized React Flow components. Route SSE handlers through GraphView's stable
  handler ref rather than subscription dependencies; runtime targets use structural refs,
  because flat IDs can change on rebuild.
- Point/run-selection epoch baselines in `src/api/events.ts` are separate per workflow/channel
  and survive re-subscription, so a replayed agent selection cannot undo a user's run switch.
  A new server boot ID resets them. This deduplication is not a rule for every SSE event.
  Hidden tabs close/reopen their connection to release browser slots; `onerror` recovery stays
  trigger-independent. Both paths share one subscription state machine.
- Render failures belong to `src/components/ErrorBoundary`; fetch/layout failures belong to
  `src/hooks/useWorkflowGraph`. Same-workflow reload failures preserve the last-good canvas through
  `reloadError`; initial-load failures use the error state.

## Dev, build, verification

- Dev: `uv run pflow ui --no-open` and `cd web && npm run dev`; Vite proxies `/api` to
  `127.0.0.1:8765` (override with `PFLOW_UI_PORT`).
- Build: `make ui-build` (`npm ci && npm run build`) emits `src/pflow/ui/static/` with relative
  asset URLs. `npm run build` runs strict TypeScript checking first. Packaging/release rules:
  `src/pflow/ui/CLAUDE.md` → Build and release wiring.
- Stale UI after rebuild → `src/pflow/ui/server.py:_BundleFiles`: unhashed `index.html` must
  revalidate (`Cache-Control: no-cache`), or it can point at the previous build's hashed assets.
- Tests are colocated: `npx vitest run`. Graph/utils/api tests use node; component/hook tests use
  jsdom and `src/test/rf-jsdom.ts`. Real `/api/graph` fixtures in `src/test/fixtures/contracts/`
  are drift-checked by Python.
- jsdom renders no edge DOM, so “no edge errors” render assertions do not establish integrity.
  Use the handle invariant in `src/graph/flow.test.ts` and connectivity in `src/graph/lossless.test.ts`.
  Browser geometry checks live in the screenshot skill's
  `examples/real-workflows/screenshot-pflow-web-ui/visual-invariants.pflow.md`.
- `src/cssOrder.test.ts` reads CSS with `node:fs`: Vitest's CSS stubbing can also swallow `?raw`
  imports. Keep that test reading the actual stylesheet.
