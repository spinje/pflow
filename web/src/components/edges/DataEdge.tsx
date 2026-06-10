// The data-flow edge: rounded-orthogonal like everything else, with two jobs the
// built-in smoothstep can't do (no centerX/centerY knob — why this component exists):
//
//   lane geometry — each lane (EdgeData.lane, assignDataEdgeLanes) gets its own stub
//     length AND middle-rail offset, so a bundle of parallel bindings fans into
//     traceable parallel lines instead of merging on one shared rail;
//
//   focus-directional fade — when a node/row is clicked, applyFocus marks each
//     revealed line with WHICH end the focus is on (EdgeData.focusEnd); the line
//     draws SOLID at the clicked node and fades a hint toward the far end, so the
//     revealed wiring visibly belongs to — and flows away from — the focus.
//     Unfocused data lines are plain --data-edge teal. (User-chosen over lane tints
//     and node-color gradients, both judged confusing — 2026-06-10.)
//
// The component owns the stroke; CSS keeps only the dash pattern (a stroke rule
// there would override the gradient, and a regression to a built-in edge type now
// renders INVISIBLY — pinned by a flow test). The label (beautiful's "stdout →
// data") renders as the same .edge-label pill as the control edges.

import { memo, type CSSProperties } from "react";
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from "@xyflow/react";

import type { FlowEdge } from "../../graph/flow";
import { LANE_COUNT } from "../../graph/flow";
import { METRICS } from "../../graph/metrics";

// Lane → geometry. Stub: distance an edge runs out of its handle before the first
// turn (base 24, 8px apart — the base also bounds the FIRST corner's roundness:
// smoothstep clamps a bend to half its segment, so a 16px base meant 8px corners,
// the tightest on the canvas). Rail: how far the middle segment shifts off the
// midpoint (centered around 0 so the bundle straddles the default rail).
const STUB_BASE = 24;
const STUB_STEP = 8;
const RAIL_STEP = 9;

// The far end of a focused line keeps this much opacity — "a hint" of fade, enough
// to read direction-from-the-click without making the line hard to follow.
const FADE_TO = 0.45;

export const DataEdge = memo(function DataEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  label,
}: EdgeProps<FlowEdge>): JSX.Element {
  const lane = (data?.lane ?? 0) % LANE_COUNT;
  const rail = (lane - (LANE_COUNT - 1) / 2) * RAIL_STEP;
  // The middle segment sits at the post-layout rail hint when one exists (centered
  // in the clear gap between the endpoint nodes — assignDataRails), else at the
  // handle midpoint. The blind midpoint is what made wrap-arounds hug node borders.
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: METRICS.edgeRadius,
    offset: STUB_BASE + lane * STUB_STEP,
    centerX: (data?.railX ?? (sourceX + targetX) / 2) + rail,
    centerY: (data?.railY ?? (sourceY + targetY) / 2) + rail,
  });
  const focusEnd = data?.focusEnd;
  const gradientId = `data-grad-${id}`;
  // Gradient axis runs FROM the clicked end TO the far end (solid → hint-faded).
  const fromFocus = focusEnd === "target" ? { x1: targetX, y1: targetY, x2: sourceX, y2: sourceY } : { x1: sourceX, y1: sourceY, x2: targetX, y2: targetY };
  const stroke = focusEnd ? `url(#${gradientId})` : "var(--data-edge)";
  return (
    <>
      {focusEnd && (
        <defs>
          <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" {...fromFocus}>
            <stop offset="0%" style={{ stopColor: "var(--data-edge)" }} stopOpacity={1} />
            <stop offset="100%" style={{ stopColor: "var(--data-edge)" }} stopOpacity={FADE_TO} />
          </linearGradient>
        </defs>
      )}
      <BaseEdge
        id={id}
        path={edgePath}
        style={{ stroke, strokeWidth: selected ? METRICS.edgeStroke + 1 : METRICS.edgeStroke }}
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="edge-label nodrag nopan"
            style={
              {
                transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
                "--label-c": "var(--data-edge)",
              } as CSSProperties
            }
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});
