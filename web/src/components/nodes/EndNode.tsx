// The synthetic per-level end sink. Reconciles is_terminal nodes + kind="end"
// nodes + kind="end" edges into one visual sink per level (H10): every level's
// `next: end` routes land here as a single small terminator.

import { Handle, type NodeProps, Position } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { NODE_IN } from "../../graph/handles";

type EndNodeType = Extract<FlowNode, { type: "end" }>;

export function EndNode({ data }: NodeProps<EndNodeType>): JSX.Element {
  const { direction, dimmed, focused } = data;
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const classes = ["node", "end"];
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");

  return (
    <div className={classes.join(" ")} title="end">
      <Handle id={NODE_IN} type="target" position={targetPos} className="handle node-handle" />
      <span className="end-glyph">■</span>
    </div>
  );
}
