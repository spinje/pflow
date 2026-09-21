# Hooks (`web/src/hooks/`)

Runtime coordination between the pure graph transform, React Flow store, and browser.

- Data/build/layout/decoration and failure states → `useWorkflowGraph.ts`.
- View fitting, deep links and navigation follow → `useCameraNavigation.ts`.
- Source/read pane widths and persistence → `usePanelPair.ts`, `../utils/panelWidth.ts`.
- Source-file change detection → `useSourceWatch.ts`.
- SSE presence/reconnect/catch-up → `../api/events.ts:subscribe` (see web root).

## Layout snapshots and painting

`useWorkflowGraph` caches by layout-affecting state. Focus alone is a restyle, except when
beautiful-mode expansion changes card sizes; advanced mode uses the stable empty expansion set.
Keep laid nodes and edges as one snapshot, and decorate only when its layout key matches current
state. Otherwise new focus briefly paints on old positions, including during cache hits.

On expansion layout, apply the viewport delta in the same effect that pushes node positions so
the focused card remains anchored. IO-port focus anchors to its owner card; edge focus anchors
to its rendered source. Neither a port ID nor an edge ID is itself a positioned node.

Animate positions through the RF store so edge paths follow, with camera anchoring eased in
sync. CSS-only transforms would move cards while edges snap. Large graphs and reduced-motion
preferences snap. `paintEpoch` advances only after a completed paint, including animation landing;
`useCameraNavigation` waits on it before following a target's final position.

`builtEdgeIds` is returned synchronously with focus-derived expansion. GraphView invalidates
edge selection against it, not the painted edges that lag behind a layout round-trip.

Live status-only updates skip redundant edge writes to avoid transient edge blanking. Terminal
replay dimming is the exception: its edge classes also depend on status-map identity.

ELK worker/fallback and watchdog belong to `../graph/layout.ts:layoutWithWatchdog`; worker silence
must reach fallback/error handling rather than leaving the hook permanently loading.

## Camera timing

`useCameraNavigation` runs inside ReactFlowProvider and gates initial fits/deep-link focus on
`useNodesInitialized`. Navigation waits for the completed `paintEpoch`; navigating to unchanged
focus fits immediately because no new decoration paint will arrive. Resolve IO ports to owner
cards for both fitting and expansion anchoring.

A focus changed while the tab is hidden needs a reframe on return because its rAF-driven fit
may never run. Keep that reframe pending until its target paints. An ordinary tab return with
no hidden focus change must preserve the viewport.

## Reload and panes

`useSourceWatch` polls `/api/version` with visibility and in-flight guards. The initial response
seeds the baseline without reloading; transient poll errors retain it. `--no-auto-update`
(`?watch=0`) disables watching.

A same-workflow reload rebuilds in place, preserving viewport/selection/collapse/source pane;
a workflow change resets state. `reloadError` reports invalid edits over the last-good canvas,
separately from initial fetch/layout failure. A successful new graph clears the layout cache.
GraphView's pre-paint graph-replacement effect remaps held state through structural refs because
positional IDs may renumber.

`usePanelPair` treats source/read widths as one reserved-budget constraint and reclamps on both
pane changes and window resize. Both panes are nonshrinking flex items; omitting the resize arm
can reduce the canvas to zero width. Pure sizing and persistence helpers live in `../utils/panelWidth.ts`.
