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
  /** one row: param / branch-port / ports-row (leafSize row math + 3 CSS rules). */
  rowH: 26,
  /** .ports-header height (leafSize for ports nodes). */
  portsHeaderH: 30,
  /** .node-tile box — the icon tile leafSize assumes dominates the header. */
  tileSize: 56,
  /** .node-tile border width; the flare's base apron must stay WITHIN it. */
  tileBorder: 3,
  /** control-edge stroke width == the connector flare's tip width (CONN.tipW). */
  edgeStroke: 3,
  /** .group-header height; ELK's group top padding must clear it (layout.ts). */
  groupHeaderH: 38,
} as const;

/** The CSS custom properties main.tsx injects on :root — the stylesheet's view of
 *  METRICS. A pure map (no DOM access) so graph/ stays node-env testable. */
export function metricsCssVars(): Record<string, string> {
  return {
    "--node-header-h": `${METRICS.nodeHeaderH}px`,
    "--row-h": `${METRICS.rowH}px`,
    "--ports-header-h": `${METRICS.portsHeaderH}px`,
    "--tile-size": `${METRICS.tileSize}px`,
    "--tile-border": `${METRICS.tileBorder}px`,
    "--edge-stroke": `${METRICS.edgeStroke}px`,
    "--group-header-h": `${METRICS.groupHeaderH}px`,
  };
}
