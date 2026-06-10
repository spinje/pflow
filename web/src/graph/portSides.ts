// Post-LAYOUT edge decoration (positions in, edges out; pure — unit-tested, no
// DOM). Three passes, all wired in useWorkflowGraph after ELK:
//
// 1. assignDataRails — a wrap-around's middle rail used to sit at the blind
//    handle-midpoint, which can land a few px from a node border (the "edge hugs
//    the condition node" bug). With boxes known post-layout, a data edge whose
//    endpoint nodes have a clear gap on an axis gets a rail hint CENTERED in that
//    gap (data.railX/railY); DataEdge uses the hint instead of the midpoint.
//
// 2. assignLoopRails — the synthesized loop-back U (LoopEdge) must wrap AROUND
//    its box, but the edge component only sees handle coordinates (a self-loop's
//    default smoothstep midpoint runs straight back THROUGH the node). With boxes
//    known post-layout, each loop edge gets its rail: TD → a vertical rail just
//    RIGHT of the box (railX); LR → a horizontal rail just ABOVE it (railY).
//    LoopEdge feeds the rail to getSmoothStepPath as centerX/centerY.
//
// 3. assignBackRails — a BACKWARD branch/error edge (a loop-back to an earlier
//    node) keeps smoothstep's stock wrap, which turns at the default ~20px stub
//    right at the source handle — several branch rows emitting at nearly the same
//    point knot into tight curls (user-caught on the harness's check-groups, LR).
//    With boxes known post-layout, a backward edge gets a rail in the clear zone
//    PAST both endpoint boxes: LR → below them (the loop U owns the space above),
//    TD → left of them (the loop rail owns the right). Lane-staggered
//    (EdgeData.lane, assignEdgeLanes) so sibling loop-backs fan apart.
//    GradientEdge feeds the rail to getSmoothStepPath over its railCenter default.
//    Sequential edges are deliberately untouched (their backward cycle already
//    renders the clean orthogonal U; don't perturb what works).
//
// Deliberately NOT a router: full crossing/node avoidance (vs OTHER nodes) remains
// the deferred smart edge-router (visualization-requirements.md).

import type { Direction, FlowEdge, FlowNode } from "./flow";

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

// Far enough from the box that the U's two corners render at full radius
// (smoothstep clamps a bend to half its adjoining segment), close enough to
// read as wrapping THIS box.
const LOOP_RAIL_OFFSET = 36;

// Same clearance for backward control edges; lanes step apart like data stubs.
const BACK_RAIL_OFFSET = 36;
const BACK_LANE_STEP = 8;

export function assignBackRails(nodes: FlowNode[], edges: FlowEdge[], direction: Direction): FlowEdge[] {
  const boxOf = boxes(nodes);
  return edges.map((edge) => {
    const kind = edge.data?.kind;
    if (kind !== "branch" && kind !== "error") return edge;
    const sBox = boxOf(edge.source);
    const tBox = boxOf(edge.target);
    if (!sBox || !tBox) return edge;
    const stagger = (edge.data?.lane ?? 0) * BACK_LANE_STEP;
    if (direction === "LR") {
      // Forward (target clearly ahead of the source's right edge) → railCenter's
      // near-source rail already draws it; only a wrap needs the back rail.
      if (tBox.left > sBox.right) return edge;
      const railY = Math.max(sBox.bottom, tBox.bottom) + BACK_RAIL_OFFSET + stagger;
      if (edge.data?.railY === railY) return edge;
      return { ...edge, data: { ...edge.data!, railY } };
    }
    if (tBox.top > sBox.bottom) return edge;
    const railX = Math.min(sBox.left, tBox.left) - BACK_RAIL_OFFSET - stagger;
    if (edge.data?.railX === railX) return edge;
    return { ...edge, data: { ...edge.data!, railX } };
  });
}

export function assignLoopRails(nodes: FlowNode[], edges: FlowEdge[], direction: Direction): FlowEdge[] {
  const boxOf = boxes(nodes);
  return edges.map((edge) => {
    if (edge.data?.kind !== "loop") return edge;
    const box = boxOf(edge.source); // a loop edge's source === target === the looped box
    if (!box) return edge;
    const railX = direction === "TD" ? box.right + LOOP_RAIL_OFFSET : undefined;
    const railY = direction === "TD" ? undefined : box.top - LOOP_RAIL_OFFSET;
    if (edge.data.railX === railX && edge.data.railY === railY) return edge;
    return { ...edge, data: { ...edge.data, railX, railY } };
  });
}
