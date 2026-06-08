// A container box (sub-workflow / batch / IO wrapper). Its header shows the host
// node's title + badges when this is the host's primary (outermost) group — a host
// is NOT 1:1 with a group (H8), so only one group of a multi-group host draws the
// title. Clicking a group toggles collapse (wired in GraphView's onNodeClick); the
// chevron is the affordance.

import { Handle, type NodeProps, Position } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { NODE_IN, NODE_OUT } from "../../graph/handles";
import type { ContainerKind } from "../../types";
import { NodeBadges } from "./Badges";

type GroupNodeType = Extract<FlowNode, { type: "group" }>;

const KIND_LABEL: Record<ContainerKind, string> = {
  workflow: "sub-workflow",
  batch: "batch",
  input_wrapper: "inputs",
  output_wrapper: "outputs",
};

function unexpandedItemCount(annotations: Record<string, unknown>): number {
  const items = annotations["unexpanded_items"];
  return items && typeof items === "object" ? Object.keys(items as Record<string, unknown>).length : 0;
}

function warningCount(annotations: Record<string, unknown>): number {
  const warnings = annotations["warnings"];
  return Array.isArray(warnings) ? warnings.length : 0;
}

export function GroupNode({ data }: NodeProps<GroupNodeType>): JSX.Element {
  const { group, hostNode, collapsed, showTitle, direction, dimmed, focused } = data;
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const sourcePos = direction === "LR" ? Position.Right : Position.Bottom;
  const classes = ["group", `group-${group.kind}`];
  if (collapsed) classes.push("collapsed");
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");

  const unexpanded = unexpandedItemCount(group.annotations);
  const warnings = warningCount(group.annotations);

  return (
    <div className={classes.join(" ")}>
      <Handle id={NODE_IN} type="target" position={targetPos} className="handle node-handle" />
      <Handle id={NODE_OUT} type="source" position={sourcePos} className="handle node-handle" />
      <div className="group-header">
        <span className="chevron">{collapsed ? "▸" : "▾"}</span>
        <span className="group-kind">{KIND_LABEL[group.kind]}</span>
        {showTitle && hostNode && <span className="group-title">{hostNode.ref.node_id}</span>}
        {showTitle && hostNode && <NodeBadges node={hostNode} />}
        {collapsed && <span className="group-collapsed-count">{group.members.length} hidden</span>}
        {unexpanded > 0 && (
          <span className="badge badge-unexpanded" title="literal batch items that failed to expand">
            {unexpanded} unexpanded
          </span>
        )}
        {warnings > 0 && (
          <span className="badge badge-warning" title="child warnings">
            {warnings} warning{warnings === 1 ? "" : "s"}
          </span>
        )}
      </div>
    </div>
  );
}
