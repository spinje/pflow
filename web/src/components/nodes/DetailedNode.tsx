// The "advanced" density: a node as a titled card whose param rows each expose a
// left-side target handle, so a ${ref} data-flow line lands on its exact row.
// Output fields become right-side source ports. Node-level handles (header) catch
// control-flow edges and data-flow edges that can't be attributed to a row.
//
// Per-row handles sit inside position:relative rows; React Flow measures their DOM
// rects for edge routing, so no pixel math is needed to align lines to rows.

import type { CSSProperties } from "react";
import { Handle, type NodeProps, Position } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { NODE_IN, NODE_OUT, outputHandle, paramHandle } from "../../graph/handles";
import { collapseWhitespace, kindColor, kindGlyph, parseTemplate, previewValue, truncate } from "../../utils/format";
import type { RFParam } from "../../types";
import { NodeBadges } from "./Badges";
import { BranchPorts } from "./BranchPorts";

type DetailedNodeType = Extract<FlowNode, { type: "detailed" }>;

function ParamValue({ param }: { param: RFParam }): JSX.Element {
  if (param.is_dynamic && typeof param.value === "string") {
    const collapsed = collapseWhitespace(param.value);
    return (
      <>
        {parseTemplate(collapsed).map((seg, i) =>
          seg.isRef ? (
            <span key={i} className="ref-chip" title={`\${${seg.text}}`}>
              {seg.text}
            </span>
          ) : (
            <span key={i} className="lit">
              {truncate(seg.text, 28)}
            </span>
          ),
        )}
      </>
    );
  }
  return <span className="lit">{previewValue(param.value)}</span>;
}

export function DetailedNode({ data }: NodeProps<DetailedNodeType>): JSX.Element {
  const { node, direction, outputFields, branchLabels, dimmed, focused } = data;
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const sourcePos = direction === "LR" ? Position.Right : Position.Bottom;
  const classes = ["node", "detailed", `kind-${node.kind}`];
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");
  if (node.is_terminal) classes.push("terminal");
  if (node.unexpanded) classes.push("unexpanded");
  const kindStyle = { "--kind": kindColor(node.kind) } as CSSProperties;

  return (
    <div className={classes.join(" ")} style={kindStyle}>
      <Handle id={NODE_IN} type="target" position={targetPos} className="handle node-handle" />
      <Handle id={NODE_OUT} type="source" position={sourcePos} className="handle node-handle" />

      <div className="node-header">
        <span className="kind-glyph">{kindGlyph(node.kind)}</span>
        <span className="node-title" title={node.purpose || node.ref.node_id}>
          {node.ref.node_id}
        </span>
        <span className="kind-tag">{node.kind}</span>
        <NodeBadges node={node} />
      </div>

      <div className="param-rows">
        {node.params.map((param) => (
          <div className="param-row" key={param.name}>
            <Handle
              id={paramHandle(param.name)}
              type="target"
              position={Position.Left}
              className="handle param-handle"
            />
            <span className="param-name">{param.name}</span>
            <span className="param-value">
              <ParamValue param={param} />
            </span>
          </div>
        ))}
        {outputFields.map((field) => (
          <div className="param-row output-row" key={`o:${field}`}>
            <span className="param-name out">→ {field}</span>
            <Handle id={outputHandle(field)} type="source" position={Position.Right} className="handle out-handle" />
          </div>
        ))}
        <BranchPorts labels={branchLabels} />
      </div>
    </div>
  );
}
