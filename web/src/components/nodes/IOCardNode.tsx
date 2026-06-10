// The ROOT workflow's Inputs/Outputs as a real node card (the old floating ports
// table is gone): tile + INPUTS/OUTPUTS category + the workflow's name, a count
// pill ("14 inputs"), and — when rows are visible (advanced / focus-expanded, the
// leaf showBody rule) — one row per port via the shared PortRows. In beautiful the
// card stays a quiet compact node like every other; clicking it expands the rows
// and reveals its data lines. Nested workflows render the same rows on their group
// node instead (GroupNode) — the root has no containing node, so it gets these two
// cards at the flow's start and end.

import { type CSSProperties, memo, useEffect } from "react";
import { Handle, type NodeProps, Position, useUpdateNodeInternals } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { NODE_IN, NODE_OUT } from "../../graph/handles";
import { IO_COLOR } from "../../utils/format";
import { ioCardIcon } from "../../utils/icons";
import { PortRows } from "./PortRows";

type IOCardNodeType = Extract<FlowNode, { type: "io" }>;

export const IOCardNode = memo(function IOCardNode({ id, data }: NodeProps<IOCardNodeType>): JSX.Element {
  const { kind, ports, workflowName, direction, rowsVisible, focusedPortId, dimmed, focused } = data;
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const sourcePos = direction === "LR" ? Position.Right : Position.Bottom;

  // Rows appearing/disappearing adds/removes per-row handles; without a re-measure
  // React Flow keeps stale handle coords and edges fly to the origin.
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, direction, rowsVisible, updateNodeInternals]);

  // ALWAYS `compact`: the card shell (radius/bg/border) lives on
  // `.node.compact/.detailed`, and `.node.expanded` would add a header divider on
  // top of the `.io-rows` one (the double-divider bug). The rows area carries its
  // own divider, like the collapsed group card.
  const classes = ["node", "compact", "io-card", `io-card-${kind}`];
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");
  const kindStyle = { "--kind": IO_COLOR } as CSSProperties;
  const count = `${ports.length} ${kind}${ports.length === 1 ? "" : "s"}`;

  return (
    <div className={classes.join(" ")} style={kindStyle}>
      {/* Node-level handles: data edges land here whenever the rows don't render
          (beautiful unfocused). IO cards carry no control edges, so no icon-column
          offset / connector flares — the data lines connect sideways. */}
      <Handle id={NODE_IN} type="target" position={targetPos} className="handle node-handle" />
      <Handle id={NODE_OUT} type="source" position={sourcePos} className="handle node-handle" />

      <div className="node-header">
        <div className="node-tile">
          <img className="node-icon-img" src={ioCardIcon(kind)} alt="" />
        </div>
        <div className="node-titles">
          <span className="node-category">{kind === "input" ? "INPUTS" : "OUTPUTS"}</span>
          <span className="node-name" title={workflowName}>
            {workflowName}
          </span>
        </div>
      </div>
      <span className="count-pill group-pill">{count}</span>

      {rowsVisible && (
        <div className="io-rows">
          <PortRows
            ports={ports}
            kind={kind}
            // The root has only the outer scope: inputs FEED consumers, outputs
            // RECEIVE from producers (there is no parent to bind from / feed to).
            handles={kind === "input" ? "feed" : "receive"}
            focusedPortId={focusedPortId}
          />
        </div>
      )}
    </div>
  );
});
