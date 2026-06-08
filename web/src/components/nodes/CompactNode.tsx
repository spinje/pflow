// The "beautiful" density: the same node as a small colored card (glyph + name +
// one badge), colored by type. Forks still show — a decision node's branch outcomes
// render as labeled border handles even here, because a fork is structure.

import type { CSSProperties } from "react";
import { Handle, type NodeProps, Position } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { NODE_IN, NODE_OUT } from "../../graph/handles";
import { kindColor, kindGlyph } from "../../utils/format";
import { NodeBadges } from "./Badges";
import { BranchPorts } from "./BranchPorts";

type CompactNodeType = Extract<FlowNode, { type: "compact" }>;

export function CompactNode({ data }: NodeProps<CompactNodeType>): JSX.Element {
  const { node, direction, branchLabels, dimmed, focused } = data;
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const sourcePos = direction === "LR" ? Position.Right : Position.Bottom;
  const classes = ["node", "compact", `kind-${node.kind}`];
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");
  if (node.is_terminal) classes.push("terminal");
  if (node.unexpanded) classes.push("unexpanded");
  const kindStyle = { "--kind": kindColor(node.kind) } as CSSProperties;

  return (
    <div className={classes.join(" ")} style={kindStyle}>
      <Handle id={NODE_IN} type="target" position={targetPos} className="handle node-handle" />
      <Handle id={NODE_OUT} type="source" position={sourcePos} className="handle node-handle" />
      <div className="compact-header">
        <span className="kind-glyph">{kindGlyph(node.kind)}</span>
        <span className="node-title" title={node.purpose || node.ref.node_id}>
          {node.ref.node_id}
        </span>
        <NodeBadges node={node} max={1} />
      </div>
      <BranchPorts labels={branchLabels} />
    </div>
  );
}
