// The SELECTED edge's halo under-stroke — the edge analog of the node focus ring,
// drawn in the edge's own paint (hue carries identity, brightness carries state).
// One component so the halo geometry lives in one place. The INLINE stroke is
// load-bearing: React Flow's base stylesheet strokes `.selected` paths grey, and
// inline wins — a CSS-styled halo would silently grey out exactly when selected.

import { METRICS } from "../../graph/metrics";

export function EdgeHalo({ path, stroke }: { path: string; stroke: string }): JSX.Element {
  return (
    <path
      d={path}
      fill="none"
      stroke={stroke}
      strokeWidth={METRICS.edgeStroke * 3.5}
      strokeOpacity={0.25}
      strokeLinecap="round"
      className="edge-halo"
    />
  );
}
