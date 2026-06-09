// The loop-back arc. The contract has no loop edge — flow.ts synthesizes a
// self-loop edge from a node's LoopSpec, and this draws it as a smooth arc bulging
// off the node (or its group), labeled with the condition + cap. The bulge is
// perpendicular to the source->target handle line, so it reads correctly in both
// LR (over the top) and TD (around the side) layouts.

import { memo } from "react";
import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from "@xyflow/react";

import type { FlowEdge } from "../../graph/flow";
import { truncate } from "../../utils/format";

const BULGE = 80;

export const LoopEdge = memo(function LoopEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  markerEnd,
  data,
}: EdgeProps<FlowEdge>): JSX.Element {
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const dist = Math.hypot(dx, dy) || 1;
  // Unit perpendicular, scaled — the arc's apex offset from the chord.
  const nx = (-dy / dist) * BULGE;
  const ny = (dx / dist) * BULGE;
  const path =
    `M ${sourceX},${sourceY} ` +
    `C ${sourceX + dx * 0.25 + nx},${sourceY + dy * 0.25 + ny} ` +
    `${sourceX + dx * 0.75 + nx},${sourceY + dy * 0.75 + ny} ` +
    `${targetX},${targetY}`;
  const labelX = sourceX + dx * 0.5 + nx;
  const labelY = sourceY + dy * 0.5 + ny;

  const loop = data?.loop;
  const label = loop
    ? `↻ ${loop.polarity} ${truncate(loop.condition, 30)}${loop.cap != null ? ` ≤ ${loop.cap}` : ""}`
    : "";

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="loop-edge-label nodrag nopan"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});
