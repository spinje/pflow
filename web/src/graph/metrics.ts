// The layout-coupled geometry constants, single-sourced. Every number here lives in
// BOTH worlds: the TS that predicts boxes for ELK (flow.ts leafSize) or draws
// geometry (the connector flare, the gradient edge stroke), AND the CSS that renders
// the real DOM. These used to exist twice, synced only by comment strings — the bug
// class behind the tile-drift and the connector viewBox-drift incidents. TS imports
// METRICS; the stylesheet reads the SAME values as CSS custom properties injected on
// :root by main.tsx (metricsCssVars). index.css must never hardcode one of these.

export const METRICS = {
  /** .node-header min-height == the compact node's fixed height (leafSize). */
  nodeHeaderH: 68,
  /** one row: param / branch-port / io-row (leafSize row math + 3 CSS rules). */
  rowH: 26,
  /** .io-col-label height — the small INPUTS/OUTPUTS column caption above IO rows
   *  (collapsed group card + expanded region; sizing math counts it once). */
  ioLabelH: 18,
  /** .io-rows TOP CHROME — the sum of its margin-top (4) + border-top (1) +
   *  padding-top (6) in index.css. The LR row-PORT alignment (flow.ts
   *  rowAnchorsFor → layout.ts ports) depends on this matching the rendered
   *  rows; change the `.io-rows` rule and this together or ports drift off
   *  the row dots. */
  ioRowsChrome: 11,
  /** .group-io-in sidebar width — the expanded region's inputs column. layout.ts
   *  reserves it as ELK left padding so the body lays out BESIDE the sidebar. */
  ioSidebarW: 200,
  /** .node-tile box — the icon tile leafSize assumes dominates the header. */
  tileSize: 56,
  /** .node-tile border width; the flare's base apron must stay WITHIN it. */
  tileBorder: 3,
  /** control-edge stroke width == the connector flare's tip width (CONN.tipW). */
  edgeStroke: 3,
  /** .group-header height; ELK's group top padding must clear it (layout.ts).
   *  MUST equal nodeHeaderH: the expanded region's header is the leaf card's
   *  `.node-header` verbatim (user requirement 2026-06-10 — the icon/name must
   *  not move when a container opens), so it is exactly one card-header tall. */
  groupHeaderH: 68,
  /** .node-header padding — the tile's inset from the node edge (ICON_COL_X math). */
  headerPad: 6,
  /** corner radius of the rounded-orthogonal edges (GradientEdge + DataEdge — ONE
   *  constant for both, user-tuned 18 → 24 → 20). This is a MAX — smoothstep clamps
   *  each bend to HALF its adjoining segment, so cramped spots (short stubs,
   *  adjacent-layer hops) render tighter; a wrap-around chains two bends and reads
   *  rounder. */
  edgeRadius: 20,
} as const;

/** The icon-column center x: in TD every control handle sits HERE, not at the node
 *  center — so ELK must be told (fixed ports, layout.ts) or it aligns box centers
 *  and a "straight" chain renders with a jog at every node. */
export const ICON_COL_X = METRICS.headerPad + METRICS.tileSize / 2;

/** The icon-row center y — the LR analog of ICON_COL_X (user-decided 2026-06-10):
 *  every LR control handle sits at the HEADER's vertical center (the tile's
 *  center), in on the left and out on the right at the SAME height, so the trunk
 *  reads as passing straight THROUGH the node and ELK (fixed ports, layout.ts)
 *  aligns headers — bodies of different heights hang below the aligned line. */
export const ICON_ROW_Y = METRICS.nodeHeaderH / 2;

/** The CSS custom properties main.tsx injects on :root — the stylesheet's view of
 *  METRICS. A pure map (no DOM access) so graph/ stays node-env testable. */
export function metricsCssVars(): Record<string, string> {
  return {
    "--node-header-h": `${METRICS.nodeHeaderH}px`,
    "--row-h": `${METRICS.rowH}px`,
    "--io-label-h": `${METRICS.ioLabelH}px`,
    "--io-sidebar-w": `${METRICS.ioSidebarW}px`,
    "--tile-size": `${METRICS.tileSize}px`,
    "--tile-border": `${METRICS.tileBorder}px`,
    "--edge-stroke": `${METRICS.edgeStroke}px`,
    "--group-header-h": `${METRICS.groupHeaderH}px`,
    "--header-pad": `${METRICS.headerPad}px`,
  };
}
