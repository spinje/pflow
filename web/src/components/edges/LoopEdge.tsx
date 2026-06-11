// The loop-back U. The contract has no loop edge — flow.ts synthesizes a
// self-loop edge from a node's LoopSpec, and this draws it in the same
// rounded-orthogonal language as every other edge (the Tines backward-edge U):
// out of NODE_OUT, onto a rail OUTSIDE the box (assignLoopRails, post-layout:
// TD → right of the box, LR → above it), back into NODE_IN. Replaced the old
// perpendicular-bulge bezier (2026-06-10), which cut straight through any box
// taller than its fixed 80px bulge. Without a rail hint smoothstep's midpoint
// would run the line back THROUGH the node (a self-loop's endpoints share an
// axis) — the rail is load-bearing, not a tweak.

import { memo } from "react";
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, Position, type EdgeProps } from "@xyflow/react";

import type { FlowEdge } from "../../graph/flow";
import { METRICS } from "../../graph/metrics";
import { truncate } from "../../utils/format";

// The app draws NO arrowheads (clean lines into borders) — the loop U is the one
// deliberate exception (user decision 2026-06-10): it's the only edge whose
// direction the layout doesn't imply, so the re-entry point carries a small arrow.
// Drawn as our own polygon (themable via CSS --loop; RF's marker objects take only
// literal colors). Points INTO the box along the final approach: down through the
// TOP in TD, rightward through the LEFT side in LR — or leftward into the ↻
// loop-rule ROW's right-side handle when the row renders.
function arrowPoints(x: number, y: number, into: Position): string {
  const w = 5; // half-width of the arrow base
  const len = 9;
  if (into === Position.Top) return `${x - w},${y - len} ${x + w},${y - len} ${x},${y}`;
  if (into === Position.Right) return `${x + len},${y - w} ${x + len},${y + w} ${x},${y}`;
  return `${x - len},${y - w} ${x - len},${y + w} ${x},${y}`;
}

export const LoopEdge = memo(function LoopEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps<FlowEdge>): JSX.Element {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: METRICS.edgeRadius,
    offset: 24,
    // The wrap rail (assignLoopRails). Only the direction-relevant one is set;
    // the other falls back to smoothstep's midpoint, which is exact here (a
    // self-loop's endpoints share that coordinate).
    ...(data?.railX !== undefined ? { centerX: data.railX } : {}),
    ...(data?.railY !== undefined ? { centerY: data.railY } : {}),
  });

  // Label on the U's BOTTOM RUN in TD (the horizontal segment from NODE_OUT to the
  // rail) — NOT the smoothstep path-center (the rail's middle, where the pill pokes
  // past the rightmost node and fitView clips it), and NOT the top run: above a
  // node is contested space in TD (incoming trunk, branch edges, the outcome label
  // at the target entry all live there — user-caught collision on the harness's
  // review-round). Below a node there's only the outgoing trunk and the layer gap.
  // In LR the path center IS the top rail (above the box, uncontested) — keep it.
  // STUB must match `offset` above.
  const STUB = 24;
  const labelPos =
    data?.railX !== undefined ? { x: (data.railX + sourceX) / 2, y: sourceY + STUB } : { x: labelX, y: labelY };

  const loop = data?.loop;
  const label = loop
    ? `↻ ${loop.polarity} ${truncate(loop.condition, 30)}${loop.cap != null ? ` ≤ ${loop.cap}` : ""}`
    : "";

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} />
      <polygon className="loop-arrow" points={arrowPoints(targetX, targetY, targetPosition)} />
      {label && (
        <EdgeLabelRenderer>
          <div
            className={`loop-edge-label nodrag nopan${data?.dimmed ? " label-dimmed" : ""}`}
            style={{ transform: `translate(-50%, -50%) translate(${labelPos.x}px, ${labelPos.y}px)` }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});
