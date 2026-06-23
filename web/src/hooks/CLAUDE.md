# Hooks (`web/src/hooks/`)

The runtime machinery between the pure `graph/` transform and the React Flow store — the
fetch→build→layout→focus pipeline, the camera, the two side panes, and the source-watch poll.
This is where the last several user-caught timing bugs lived.

> Read `web/CLAUDE.md` (web root) FIRST for the cross-cutting invariants (build vs focus are
> separate passes; errors never blank the canvas). The transform itself
> (`buildFlow`/`layoutGraph`/`applyFocus`/`expandTargets`) lives in `web/src/graph/` — these
> hooks ORCHESTRATE it, they don't re-implement it.

**Files:** `useWorkflowGraph` (the data pipeline + RF state + `status`) · `useCameraNavigation`
(view fits, deep links, chip-navigation follow) · `usePanelPair` (the two panes' widths) ·
`useSourceWatch` (the `/api/version` poll).

## `useWorkflowGraph` — the pipeline + the perf/motion machinery

Owns fetch → `buildFlow` → `layoutGraph` → `applyFocus` → React Flow store, plus `status`
(`loading`/`ready`/`empty`/`error`) — a malformed 200 throws from `fetchGraph` (caught), an ELK
failure becomes `error` (not a stuck spinner). The laid-out-nodes-and-edges snapshot that keeps
focus off stale positions is kept HERE (the build-vs-focus invariant, root, in practice).

- **Layout cache:** keyed by `layoutKey` (`density|direction|collapsed|expanded` — focus itself
  is NOT layout-affecting), so un-click/re-click never re-runs ELK; a cache hit applies
  synchronously.
- **ELK in a web worker + watchdog** (the worker/fallback machinery is `graph/layout.ts`'s
  `loadElk`/`layoutWithWatchdog`; this hook consumes it): a worker layout silent for 10s warns,
  re-runs on the main-thread build, and demotes the session to main-thread layouts — bounded
  badness, never a dead canvas (the silent-worker stall was environmental).
- **Stale-paint guard:** the decoration effect paints ONLY a laid snapshot whose `layoutKey`
  matches the current state — without it every cached click "shakes" (one frame of
  new-focus-on-old-layout).
- **Focus-EXPANSION is the one focus action that re-layouts** (beautiful): when `expandTargets`
  (graph/) changes node sizes, the change flows build → ELK; this hook pans the viewport by the
  focused node's layout delta IN THE SAME EFFECT that pushes the new positions, so the clicked
  node never moves on screen (CAMERA ANCHORING). In advanced the expansion set is the stable
  empty constant, so focus stays a pure restyle (no re-layout).
- **Animation:** small graphs (≤ `ANIMATE_MAX_NODES`) interpolate positions THROUGH the RF store
  per frame so edge paths follow (a CSS transform transition would glide nodes while edges snap —
  rejected); the anchoring pan eases in sync; only moved nodes change identity; large flows /
  `prefers-reduced-motion` snap.
- **`paintEpoch`:** bumped after every COMPLETED decoration paint (animated glides bump when they
  land) — `useCameraNavigation` defers its camera follow to this so a fit aims at post-re-layout
  positions, not click-time ones.
- **Live-source reload:** `useSourceWatch` triggers the in-place `reload` path here — re-fetch
  `/api/graph` + rebuild via a React reconcile (NOT `location.reload()`), preserving viewport /
  focus / collapse / source pane (`prevWorkflowRef` distinguishes a workflow CHANGE = full reset
  from a same-workflow reload = in-place). A mid-edit 422 routes to a SEPARATE `reloadError`
  channel (a non-blocking banner over the last-good canvas), recovering on the next valid save.
  Preserved state survives the positional flat-id renumber via `graph/remap.ts`, applied in a
  GraphView pre-paint `useLayoutEffect`.
- **`builtEdgeIds`** is returned synchronously with the focus-derived expansion so GraphView's
  edge-selection invalidation reads it, never the painted edges that lag one layout round-trip.

## `useCameraNavigation` — the camera

Owns the viewport: the fit-on-view-change effect (gated on `useNodesInitialized`), the one-shot
`focus=` deep link (burn-the-flag, also gated on `useNodesInitialized` or it races RF's empty
store), and `onNavigate` (chip clicks). The follow is DEFERRED to the `paintEpoch` bump the click
produces — a fit started at click time aims at the target's PRE-re-layout position (first click
landed wrong, second right). A same-focus navigate repaints nothing and fits immediately. An
io-port chip resolves to its OWNER card via `ioOwners` (graph/) for both the follow and the
expansion anchor (a port id is never a rendered node — unresolved, the follow silently skipped).
**Hidden-tab re-frame:** a focus that CHANGES while the tab is `hidden` applies its state but
its camera fit (rAF-driven) never runs and is not re-issued on return, leaving the node
off-screen (agent Point at a backgrounded Viewer, user-confirmed 2026-06-23). The hook captures
a change-while-hidden and re-fits on `visibilitychange → visible` — change-while-hidden ONLY, so
an ordinary tab return where focus didn't move leaves the viewport alone. This is the ONE place a
camera concern legitimately keys on `visibilitychange`; SSE *connection* recovery (`api/events.ts`)
deliberately must NOT (it's `onerror`-driven).

## `usePanelPair` — the two side panes

The source (left) + read (right) panes as ONE state machine: widths, drag/reset callbacks,
persistence, and the symmetric reserved-budget re-clamp (incl. the window-resize arm — both panes
are flex no-shrink, so a shrinking window would otherwise crush the canvas to 0). Pure clamp math
is `utils/panelWidth.ts`.

## `useSourceWatch` — change detection

Polls `GET /api/version` (~1.5s, visibility-gated, in-flight-guarded) for a source-file
fingerprint; fires the `useWorkflowGraph` reload on a CHANGE. Detection is deliberately separable
from reaction: Task 169's SSE can later replace the poll with a push calling the same trigger,
nothing downstream changing. On by default; `--no-auto-update` (→ `?watch=0`) freezes it.
