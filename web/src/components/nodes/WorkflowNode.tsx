// The one leaf-node component, at two densities from the same data. Both share the
// header (neutral tile + native-color icon + category line + bold purpose); the
// ADVANCED body (param rows with per-row target handles + output ports) renders only
// when density="detailed". Fork outcomes (BranchPorts) show in BOTH densities — a
// fork is structure, not advanced detail. `density` rides in `data`, so toggling it
// re-renders this one component (no node-type swap / remount).
//
// Per-row handles sit inside position:relative rows; React Flow measures their DOM
// rects for edge routing, so a ${ref} line lands on its exact row with no pixel math.

import { type CSSProperties, useEffect } from "react";
import { Handle, type NodeProps, Position, useUpdateNodeInternals } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { NODE_IN, NODE_OUT, outputHandle, paramHandle } from "../../graph/handles";
import { categoryLabel, collapseWhitespace, kindColor, parseTemplate, previewValue, truncate } from "../../utils/format";
import { iconFor } from "../../utils/icons";
import type { RFParam } from "../../types";
import { NodeBadges } from "./Badges";
import { BranchPorts } from "./BranchPorts";

type WorkflowNodeType = Extract<FlowNode, { type: "node" }>;

// The connector stub (viewBox 16×14): a small flat tip (≈ edge width) flowing with
// concave sides onto a flat base on the tile border — FLAT (90°) at both ends. TOP has
// the tip at the top (y=0); BOTTOM is the exact vertical mirror (tip at the bottom) so
// neither needs a CSS flip (a flip would also throw off the handle's measured position).
const CONNECTOR_TOP = "M6.5,0 L9.5,0 C9.5,9 11,14 14,14 L2,14 C5,14 6.5,9 6.5,0 Z";
const CONNECTOR_BOTTOM = "M6.5,14 L9.5,14 C9.5,5 11,0 14,0 L2,0 C5,0 6.5,5 6.5,14 Z";

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

// A kind-colored connector stub that bridges the edge into the icon. It OWNS its control
// handle, placed at the stub's outer TIP, so the edge meets the stub exactly — there is
// no second element with separate math to drift out of sync (that was the visible gap).
function Connector({ side, handleId, handleType }: { side: "top" | "bottom"; handleId: string; handleType: "source" | "target" }): JSX.Element {
  const position = side === "top" ? Position.Top : Position.Bottom;
  // The handle sits at the stub's tip: the top of the top stub / the bottom of the bottom.
  const tipStyle: CSSProperties = side === "top" ? { top: 0, left: "50%" } : { top: "auto", bottom: 0, left: "50%" };
  return (
    <div className={`node-connector node-connector-${side}`}>
      <svg viewBox="0 0 16 14" aria-hidden="true">
        <path d={side === "top" ? CONNECTOR_TOP : CONNECTOR_BOTTOM} />
      </svg>
      <Handle id={handleId} type={handleType} position={position} className="handle node-handle" style={tipStyle} />
    </div>
  );
}

export function WorkflowNode({ id, data }: NodeProps<WorkflowNodeType>): JSX.Element {
  const { node, density, direction, outputFields, branchLabels, hasIncoming, hasOutgoing, dimmed, focused } = data;
  const detailed = density === "detailed";
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const sourcePos = direction === "LR" ? Position.Right : Position.Bottom;
  // TD/beautiful: a control edge flows into the icon via a connector STUB that owns its
  // handle — but only the side that actually HAS an edge gets a stub. The other side
  // (and the whole LR / advanced / loop case) falls back to a node handle, on the icon
  // column in TD so the trunk still lines up.
  const topConnector = direction === "TD" && !detailed && hasIncoming;
  const bottomConnector = direction === "TD" && !detailed && hasOutgoing;
  const fallbackHandleStyle = direction === "TD" ? { left: 36 } : undefined;

  // React Flow caches handle positions; moving them (LR↔TD, or a stub appearing) needs a
  // re-measure or edges use stale coords and fly to the origin.
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, direction, density, hasIncoming, hasOutgoing, updateNodeInternals]);

  const classes = ["node", detailed ? "detailed" : "compact", `kind-${node.kind}`];
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");
  if (node.is_terminal) classes.push("terminal");
  if (node.unexpanded) classes.push("unexpanded");
  const kindStyle = { "--kind": kindColor(node.kind) } as CSSProperties;
  const hasBody = detailed && (node.params.length > 0 || outputFields.length > 0);

  return (
    <div className={classes.join(" ")} style={kindStyle}>
      {topConnector ? (
        <Connector side="top" handleId={NODE_IN} handleType="target" />
      ) : (
        <Handle id={NODE_IN} type="target" position={targetPos} className="handle node-handle" style={fallbackHandleStyle} />
      )}
      {bottomConnector ? (
        <Connector side="bottom" handleId={NODE_OUT} handleType="source" />
      ) : (
        <Handle id={NODE_OUT} type="source" position={sourcePos} className="handle node-handle" style={fallbackHandleStyle} />
      )}

      <div className="node-header">
        <div className="node-tile">
          <img className="node-icon-img" src={iconFor(node)} alt="" />
        </div>
        <div className="node-titles">
          {/* Type line + description, in BOTH densities. The description (purpose, or
              node_id when absent) wraps to ≤2 lines; node_id (the ${ref} key) is on
              the tooltip + in the read panel. */}
          <span className="node-category">{categoryLabel(node)}</span>
          <span className="node-name" title={node.ref.node_id}>
            {node.purpose || node.ref.node_id}
          </span>
        </div>
        <NodeBadges node={node} max={detailed ? undefined : 1} />
      </div>

      {hasBody && (
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
        </div>
      )}

      <BranchPorts labels={branchLabels} direction={direction} />
    </div>
  );
}
