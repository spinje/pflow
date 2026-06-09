// A smooth bezier control edge whose stroke blends sourceColor -> targetColor along
// the TRUE edge direction. We use a `userSpaceOnUse` gradient positioned by the
// actual source/target coords, so the blend follows direction in any orientation
// (LR/TD, backward, re-anchored) with no degenerate-bbox bug (the objectBoundingBox
// artifact, xyflow #4822). Pure styling — handles/anchoring are untouched. No
// arrowhead: the line flows straight into the node's (same-color) border.
//
// A label is rendered only when present — in practice TD fork edges (a branch's
// outcome rides the edge there; in LR it rides the node's border handle instead).

import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";

import type { FlowEdge } from "../../graph/flow";

export function GradientEdge({
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
  return (
    <>
      <defs>
        <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" x1={sourceX} y1={sourceY} x2={targetX} y2={targetY}>
          <stop offset="0%" stopColor={from} />
          <stop offset="100%" stopColor={to} />
        </linearGradient>
      </defs>
      <BaseEdge id={id} path={edgePath} style={{ stroke: `url(#${gradientId})`, strokeWidth: selected ? 4 : 3 }} />
      {label && (
        <EdgeLabelRenderer>
          <div className="edge-label nodrag nopan" style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}>
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
