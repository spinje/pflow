// The one leaf-node component, at two densities from the same data. Both share the
// header (neutral tile + native-color icon + category line + bold purpose); the
// ADVANCED body (param rows with per-row target handles + output ports) renders only
// when density="detailed". Fork outcomes (BranchPorts) show in BOTH densities — a
// fork is structure, not advanced detail. `density` rides in `data`, so toggling it
// re-renders this one component (no node-type swap / remount).
//
// Per-row handles sit inside position:relative rows; React Flow measures their DOM
// rects for edge routing, so a ${ref} line lands on its exact row with no pixel math.

import { type CSSProperties, memo, useEffect, useRef } from "react";
import { Handle, type NodeProps, Position, useUpdateNodeInternals } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { NODE_IN, NODE_OUT, outputHandle, paramHandle } from "../../graph/handles";
import { METRICS } from "../../graph/metrics";
import { categoryLabel, collapseWhitespace, kindColor, parseTemplate, previewValue, truncate } from "../../utils/format";
import { iconFor } from "../../utils/icons";
import type { RFParam } from "../../types";
import { NodeBadges } from "./Badges";
import { BranchPorts } from "./BranchPorts";

type WorkflowNodeType = Extract<FlowNode, { type: "node" }>;

// The connector flare: a 3px stem (== the control-edge stroke width) flowing via
// concave elliptical-arc fillets onto a wide flat base that sinks into the tile's
// 3px border. ONE set of constants drives the path, the viewBox, AND the element's
// inline size — if viewBox and box ever disagree, the browser silently rescales and
// centers the paint inside the (correctly placed) box, which bounding-box measurement
// cannot see: the tip renders thinner than the edge and the cove reads angular.
// Arcs (`A`), not eyeballed cubics: tangent is exactly vertical at the stem and
// exactly horizontal at the base, so the landing is flat by construction.
const CONN = {
  w: 14, // base span == element width
  tipW: METRICS.edgeStroke, // the stem must continue the edge at exactly its width
  stemH: 2, // straight stem run; slides under the edge terminus (same width+color → seamless)
  coveH: 7, // fillet height: vertical tangent at the stem → horizontal at the tile
  // The landing line sits baseSink px INSIDE the tile border: landing exactly ON the
  // outer edge puts the silhouette's 90° corner right on the color boundary, which
  // antialiases into a 1px jag. Sunk inside, the cove crosses the edge while still
  // sloped — no corner on the silhouette. The apron continues past the landing line;
  // baseSink + baseApron must stay WITHIN the tile border (past it = a dark notch).
  baseSink: 1,
  baseApron: 1,
};
const CONN_H = CONN.stemH + CONN.coveH + CONN.baseApron;
const TIP_L = (CONN.w - CONN.tipW) / 2;
const TIP_R = TIP_L + CONN.tipW;
const BASE_Y = CONN.stemH + CONN.coveH; // where the cove lands flat (baseSink px inside the border)
const CONNECTOR_TOP = [
  `M${TIP_L},0 L${TIP_R},0 L${TIP_R},${CONN.stemH}`,
  `A${TIP_L},${CONN.coveH} 0 0 0 ${CONN.w},${BASE_Y}`,
  `L${CONN.w},${CONN_H} L0,${CONN_H} L0,${BASE_Y}`,
  `A${TIP_L},${CONN.coveH} 0 0 0 ${TIP_L},${CONN.stemH} Z`,
].join(" ");
const CONNECTOR_BOTTOM = [
  `M${TIP_L},${CONN_H} L${TIP_R},${CONN_H} L${TIP_R},${CONN_H - CONN.stemH}`,
  `A${TIP_L},${CONN.coveH} 0 0 1 ${CONN.w},${CONN.baseApron}`,
  `L${CONN.w},0 L0,0 L0,${CONN.baseApron}`,
  `A${TIP_L},${CONN.coveH} 0 0 1 ${TIP_L},${CONN_H - CONN.stemH} Z`,
].join(" ");
// Anchor offset from the tile's padding box (the containing block for an absolutely
// positioned child): +tileBorder would put the element's end at the border's OUTER
// edge; subtracting sink+apron drops the landing line baseSink px inside the border
// and keeps the apron's far end (sink+apron) px in — clear of the dark face.
const CONN_ANCHOR = `calc(100% + ${METRICS.tileBorder - CONN.baseSink - CONN.baseApron}px)`;

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

// A kind-colored connector flare bridging the edge into the icon tile. PURE DECORATION —
// it owns NO handle. The control handle lives on the node BORDER (reliable RF measurement);
// the edge ends there, hidden UNDER this opaque flare, so it appears to flow into the tile.
// Decoupling the handle from the flare is what closed the gap (a handle nested in this
// transformed, outside-the-box element was mis-measured by React Flow). TD/beautiful only.
function Connector({ side }: { side: "top" | "bottom" }): JSX.Element {
  const anchor: CSSProperties = side === "top" ? { bottom: CONN_ANCHOR } : { top: CONN_ANCHOR };
  return (
    <div
      className={`node-connector node-connector-${side}`}
      style={{ width: CONN.w, height: CONN_H, ...anchor }}
      aria-hidden="true"
    >
      <svg viewBox={`0 0 ${CONN.w} ${CONN_H}`}>
        <path d={side === "top" ? CONNECTOR_TOP : CONNECTOR_BOTTOM} />
      </svg>
    </div>
  );
}

export const WorkflowNode = memo(function WorkflowNode({ id, data }: NodeProps<WorkflowNodeType>): JSX.Element {
  const { node, density, direction, outputFields, branchLabels, hasIncoming, hasOutgoing, expanded, dimmed, focused } = data;
  const detailed = density === "detailed";
  // Focus-expansion (beautiful only): the card renders its full advanced body in place.
  const showBody = detailed || expanded;
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const sourcePos = direction === "LR" ? Position.Right : Position.Bottom;
  // TD/beautiful: a control edge flows into the icon via the connector flare — but only
  // the side that actually HAS an edge gets one. An EXPANDED card keeps the TOP flare
  // (the tile still abuts the top border) but drops the BOTTOM one: the body grew below
  // the tile, so a tile-anchored flare would sit mid-card, away from the outgoing edge.
  const topConnector = direction === "TD" && !detailed && hasIncoming;
  const bottomConnector = direction === "TD" && !detailed && !expanded && hasOutgoing;
  // In TD the control handles sit on the icon column (left:34 = tile center) and are
  // pulled INWARD toward the tile (top/bottom offset) so the edge terminates closer to
  // the tile — letting the connector flare be short instead of bridging the full header
  // padding. NODE_IN is Position.Top (offset down), NODE_OUT is Position.Bottom (offset up).
  const topHandleStyle = direction === "TD" ? { left: 34, top: 5 } : undefined;
  const bottomHandleStyle = direction === "TD" ? { left: 34, bottom: 5 } : undefined;

  // React Flow caches handle positions; moving them (LR↔TD flips the border handles
  // from the sides to the icon column; focus-expansion adds/removes the per-row
  // handles) needs a re-measure or edges use stale coords and fly to the origin.
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, direction, density, expanded, updateNodeInternals]);

  // Dev tripwire for the open-loop ELK sizing: leafSize PREDICTS this box and React
  // Flow pins the node to it, so offsetHeight always "agrees" — the drift signal is
  // content overflowing the pinned box (scrollHeight). Detailed only: compact is
  // fixed-height and its connector flare legitimately overflows. Skips jsdom
  // (clientHeight 0); compiled out of production builds.
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!import.meta.env.DEV || !showBody) return;
    const el = rootRef.current;
    if (el && el.clientHeight > 0 && el.scrollHeight > el.clientHeight + 1) {
      console.warn(
        `pflow UI: node ${id} content is ${el.scrollHeight}px but leafSize predicted ${el.clientHeight}px — update METRICS / leafSize (flow.ts) or ELK lays out on a lie`,
      );
    }
  });

  // `kind-*` has NO CSS rules but is NOT dead: the real-browser inspect tooling
  // (examples/real-workflows/screenshot-pflow-web-ui/inspect.pflow.md) reads the node
  // kind off the classList. Removing it breaks `inspect` with no test failing.
  const classes = ["node", detailed ? "detailed" : "compact", `kind-${node.kind}`];
  if (expanded) classes.push("expanded"); // focus-expanded beautiful card (shares the body styling)
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");
  if (node.is_terminal) classes.push("terminal");
  if (node.unexpanded) classes.push("unexpanded");
  const kindStyle = { "--kind": kindColor(node.kind) } as CSSProperties;
  const hasBody = showBody && (node.params.length > 0 || outputFields.length > 0);

  return (
    <div ref={rootRef} className={classes.join(" ")} style={kindStyle}>
      {/* Control handles ALWAYS sit on the node border (in TD, on the icon column via
          fallbackHandleStyle) — the reliable RF measurement. The flare is additive
          decoration anchored to the tile; the edge ends at the border handle, hidden
          under the flare. */}
      <Handle id={NODE_IN} type="target" position={targetPos} className="handle node-handle" style={topHandleStyle} />
      <Handle id={NODE_OUT} type="source" position={sourcePos} className="handle node-handle" style={bottomHandleStyle} />

      <div className="node-header">
        <div className="node-tile">
          <img className="node-icon-img" src={iconFor(node)} alt="" />
          {topConnector && <Connector side="top" />}
          {bottomConnector && <Connector side="bottom" />}
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
});
