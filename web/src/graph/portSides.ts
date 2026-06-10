// Post-LAYOUT edge decoration (positions in, edges out; pure — unit-tested, no
// DOM). Two passes, both wired in useWorkflowGraph after ELK:
//
// 1. assignFacingSides — PORTS rows attach on the side FACING their peer. A ports
//    row is a scope BRIDGE (receives AND feeds — dots on both sides by hard
//    requirement), so side-switching is semantically honest there. buildFlow
//    assigns the base sides (target=left, source=right) before positions exist;
//    this pass flips to the mirrored handle when the peer clearly sits on the
//    other side, so a binding never wraps around the ports node (sibling
//    wrap-arounds crossed each other). The comparison uses the HANDLE x, not the
//    node center — a row source exits its node's RIGHT edge, so a vertically
//    stacked pair (centers equal) still reads "peer to the east".
//    PARAM/OUTPUT rows are deliberately NOT flipped (user decision 2026-06-10):
//    inputs-left / outputs-right is the node-graph convention and beats the
//    shortest path. Their wrap-arounds are handled by pass 2 instead.
//
// 2. assignDataRails — a wrap-around's middle rail used to sit at the blind
//    handle-midpoint, which can land a few px from a node border (the "edge hugs
//    the condition node" bug). With boxes known post-layout, a data edge whose
//    endpoint nodes have a clear gap on an axis gets a rail hint CENTERED in that
//    gap (data.railX/railY); DataEdge uses the hint instead of the midpoint.
//
// Deliberately NOT a router: full crossing/node avoidance (vs OTHER nodes) remains
// the deferred smart edge-router (visualization-requirements.md).

import type { FlowEdge, FlowNode } from "./flow";
import { isPortSource, isPortTarget, mirrorPortSource, mirrorPortTarget } from "./handles";

// Flip only when the peer is CLEARLY past the row's node — no flip-flopping on
// small layout jitter.
const HYSTERESIS = 24;

type Box = { left: number; right: number; top: number; bottom: number; cx: number };

function boxes(nodes: FlowNode[]): (id: string) => Box | null {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return (id: string): Box | null => {
    const node = byId.get(id);
    if (!node) return null;
    // Laid-out positions are parent-relative (React Flow's parentId convention) —
    // walk the ancestor chain for the absolute box.
    let left = node.position?.x ?? 0;
    let top = node.position?.y ?? 0;
    for (let p = node.parentId ? byId.get(node.parentId) : undefined; p; p = p.parentId ? byId.get(p.parentId) : undefined) {
      left += p.position?.x ?? 0;
      top += p.position?.y ?? 0;
    }
    const width = node.width ?? 0;
    const height = node.height ?? 0;
    return { left, right: left + width, top, bottom: top + height, cx: left + width / 2 };
  };
}

export function assignFacingSides(nodes: FlowNode[], edges: FlowEdge[]): FlowEdge[] {
  const boxOf = boxes(nodes);
  return edges.map((edge) => {
    const portSource = edge.sourceHandle != null && isPortSource(edge.sourceHandle);
    const portTarget = edge.targetHandle != null && isPortTarget(edge.targetHandle);
    if (!portSource && !portTarget) return edge;
    const sBox = boxOf(edge.source);
    const tBox = boxOf(edge.target);
    if (!sBox || !tBox) return edge;

    // Where the source handle actually sits: a ports-row source exits the node's
    // RIGHT edge (base side); anything else approximates as center.
    const sourceX = portSource ? sBox.right : sBox.cx;
    // Target side first: receive on the RIGHT when the peer's exit is clearly east
    // of the row's node. Then the source side, against the CHOSEN target x.
    const flipTarget = portTarget && sourceX > tBox.cx + HYSTERESIS;
    const targetX = portTarget ? (flipTarget ? tBox.right : tBox.left) : tBox.cx;
    const flipSource = portSource && targetX < sBox.cx - HYSTERESIS;

    if (!flipTarget && !flipSource) return edge;
    return {
      ...edge,
      ...(flipTarget ? { targetHandle: mirrorPortTarget(edge.targetHandle!) } : {}),
      ...(flipSource ? { sourceHandle: mirrorPortSource(edge.sourceHandle!) } : {}),
    };
  });
}

export function assignDataRails(nodes: FlowNode[], edges: FlowEdge[]): FlowEdge[] {
  const boxOf = boxes(nodes);
  return edges.map((edge) => {
    if (edge.data?.kind !== "data_flow") return edge;
    const sBox = boxOf(edge.source);
    const tBox = boxOf(edge.target);
    if (!sBox || !tBox) return edge;
    // Center the rail in the clear gap between the two endpoint boxes, per axis.
    // No clear gap (overlapping spans) → no hint; DataEdge falls back to the
    // handle-midpoint as before.
    const railY =
      sBox.bottom < tBox.top ? (sBox.bottom + tBox.top) / 2 : tBox.bottom < sBox.top ? (tBox.bottom + sBox.top) / 2 : undefined;
    const railX =
      sBox.right < tBox.left ? (sBox.right + tBox.left) / 2 : tBox.right < sBox.left ? (tBox.right + sBox.left) / 2 : undefined;
    if (railX === undefined && railY === undefined) return edge;
    if (edge.data.railX === railX && edge.data.railY === railY) return edge;
    return { ...edge, data: { ...edge.data, railX, railY } };
  });
}
