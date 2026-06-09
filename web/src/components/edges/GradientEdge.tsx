// A smooth bezier control edge whose stroke blends sourceColor -> targetColor along
// the TRUE edge direction. We use a `userSpaceOnUse` gradient positioned by the
// actual source/target coords, so the blend follows direction in any orientation
// (LR/TD, backward, re-anchored) with no degenerate-bbox bug (the objectBoundingBox
// artifact, xyflow #4822). Pure styling — handles/anchoring are untouched. No
// arrowhead: the line flows straight into the node's (same-color) border.
//
// The stop list depends on the edge KIND:
//   sequential/branch — blend source→target across the whole length.
//   error/end         — keep the SEMANTIC color (red / faint grey) along the body,
//                       but fade into the node's type color over the last ~FADE_PX
//                       at each node, so the line flows out of / into the
//                       kind-colored connectors instead of clashing. An end edge
//                       fades only at its source — the end-sink side stays faint.
//
// A label is rendered only when present — in practice TD fork edges (a branch's
// outcome rides the edge there; in LR it rides the node's border handle instead).

import { memo, type CSSProperties } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";

import type { FlowEdge } from "../../graph/flow";
import { METRICS } from "../../graph/metrics";

// How far the node-color fade reaches into an error/end edge, in px. The gradient
// runs along the straight source→target chord, so offsets are FADE_PX as a fraction
// of the chord length — near an endpoint the path hugs it, so a short fade tracks
// the curve well. Semantic colors come from the CSS vars (set via style, where
// var() resolves) so a palette re-theme can't drift from them.
const FADE_PX = 26;

export type GradientStop = { offset: number; color: string };

export function gradientStops(kind: string | undefined, from: string, to: string, chordLen: number): GradientStop[] {
  if (kind === "error" || kind === "end") {
    const semantic = kind === "error" ? "var(--danger)" : "var(--text-faint)";
    // Clamp so the two fades can't cross on a short edge (each stays in its half).
    const t = chordLen > 0 ? Math.min(FADE_PX / chordLen, 0.4) : 0.4;
    if (kind === "error") {
      return [
        { offset: 0, color: from },
        { offset: t, color: semantic },
        { offset: 1 - t, color: semantic },
        { offset: 1, color: to },
      ];
    }
    return [
      { offset: 0, color: from },
      { offset: t, color: semantic },
    ];
  }
  return [
    { offset: 0, color: from },
    { offset: 1, color: to },
  ];
}

export const GradientEdge = memo(function GradientEdge({
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
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const gradientId = `grad-${id}`;
  const from = data?.sourceColor ?? "var(--accent)";
  const to = data?.targetColor ?? "var(--accent)";
  const chordLen = Math.hypot(targetX - sourceX, targetY - sourceY);
  const stops = gradientStops(data?.kind, from, to, chordLen);
  return (
    <>
      <defs>
        <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" x1={sourceX} y1={sourceY} x2={targetX} y2={targetY}>
          {stops.map((s, i) => (
            <stop key={i} offset={`${s.offset * 100}%`} style={{ stopColor: s.color }} />
          ))}
        </linearGradient>
      </defs>
      <BaseEdge id={id} path={edgePath} style={{ stroke: `url(#${gradientId})`, strokeWidth: selected ? METRICS.edgeStroke + 1 : METRICS.edgeStroke }} />
      {label && (
        <EdgeLabelRenderer>
          {/* The pill takes its EDGE's color (tinted fill + faint hairline; text stays
              white): error = the semantic red, otherwise the target node's color (the
              line's color where it arrives). CSS reads --label-c. */}
          <div
            className="edge-label nodrag nopan"
            style={
              {
                transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
                "--label-c": data?.kind === "error" ? "var(--danger)" : to,
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
