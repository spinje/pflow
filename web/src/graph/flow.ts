// The RFGraph -> React Flow transform. Pure and unit-tested: given the contract
// payload and the current view state, produce React Flow nodes + edges (positions
// are filled afterwards by ELK in layout.ts).
//
// This is where the load-bearing contract rules live (each traces to a Task-168
// review item — see src/pflow/ui/CLAUDE.md):
//   - is_group_host nodes are SUPPRESSED as leaves; their group box stands in,
//     and a host is NOT 1:1 with a group (H8).
//   - every edge is ADDITIVE: an endpoint hidden by collapse or host-suppression
//     re-anchors to a visible ancestor (group / batch host), never dropped (H6/W1).
//   - data-flow lines land on the exact param row when input_name matches a param,
//     else degrade to a node-level connection (input_name=None is common — H6).

import type { Edge, Node } from "@xyflow/react";

import { branchHandle, NODE_IN, NODE_OUT, outputHandle, paramHandle, portHandle, portTargetHandle } from "./handles";
import { METRICS } from "./metrics";
import { kindColor, nodeColor } from "../utils/format";
import type { EdgeKind, LoopSpec, RFEdge, RFGraph, RFGroup, RFNode } from "../types";

export type Density = "detailed" | "compact";
export type Direction = "LR" | "TD";

// What the structural build (and therefore ELK layout) depends on. Focus itself is
// NOT here (applyFocus is a cheap styling pass) — but `expanded` (derived FROM focus
// by expandTargets) is: expanding a card to its advanced body changes its size, so
// it must flow through build → ELK. In beautiful, clicking a node therefore DOES
// re-layout (decided 2026-06-09: a card growing along the TD flow axis collides with
// the node below it otherwise); the hook keeps the clicked node visually anchored.
export interface BuildOptions {
  density: Density;
  direction: Direction;
  collapsed: ReadonlySet<string>;
  // Leaf nodes that render their advanced body while the global density stays
  // beautiful (the focused node + its data-flow endpoints). Ignored in advanced.
  expanded?: ReadonlySet<string>;
}

// `type` (not `interface`) so each satisfies React Flow's `data extends
// Record<string, unknown>` constraint via the implicit-index-signature rule.
export type LeafData = {
  node: RFNode;
  density: Density;
  direction: Direction;
  outputFields: string[];
  branchLabels: string[]; // decision fork outcomes — labeled handles on the border
  // Whether the node has an incoming / outgoing CONTROL edge — drives the icon
  // connector stubs (a top stub only if something flows in, a bottom stub only if
  // something flows out). Computed in buildFlow from the control edges.
  hasIncoming: boolean;
  hasOutgoing: boolean;
  // Focus-expansion: render the advanced body while density stays beautiful. The
  // card keeps its TOP flare (the tile still abuts the top border) but drops the
  // BOTTOM one (the body grew below the tile, so a tile-anchored flare would float
  // mid-card away from the outgoing edge).
  expanded: boolean;
  dimmed: boolean;
  focused: boolean;
};

// One row on an Inputs/Outputs node. `id` is the IO node's contract id — it doubles
// as the row's handle key and its focus target (click a row → focus that port).
export type Port = {
  id: string;
  name: string;
  dataType: string | null;
  required: boolean;
};

// A workflow's inputs (or outputs) consolidated into ONE node — a row + handle per
// port (the table-node pattern), instead of one floating node per port.
export type PortsData = {
  kind: "input" | "output";
  ports: Port[];
  direction: Direction;
  focusedPortId: string | null; // the row to highlight when an individual port is focused
  dimmed: boolean;
  focused: boolean;
};

export type GroupData = {
  group: RFGroup;
  hostNode: RFNode | null;
  collapsed: boolean;
  showTitle: boolean;
  direction: Direction;
  dimmed: boolean;
  focused: boolean;
};

export type EndData = {
  node: RFNode;
  direction: Direction;
  dimmed: boolean;
  focused: boolean;
};

export type EdgeData = {
  kind: EdgeKind | "loop";
  shadowed: boolean;
  // Original contract endpoints (before re-anchoring) — lets focus match an edge to a
  // node OR an individual IO port (whose edges re-anchor onto a shared ports node).
  from: string;
  to: string;
  // Set ONCE by the build: "this edge renders hidden unless revealed by focus"
  // (beautiful mode's data-flow lines). applyFocus must read THIS, never the mutable
  // `hidden` flag it also writes — otherwise re-processing its own output would
  // misread a revealed edge as default-visible and pin it shown forever.
  defaultHidden: boolean;
  // Source/target node colors for the gradient control edge (sequential/branch).
  // Optional: data/error/end/loop edges don't read them.
  sourceColor?: string;
  targetColor?: string;
  // The data edge's LANE (assignEdgeLanes): distinct stub lengths + rail offsets
  // per parallel binding at a node. DataEdge reads it; absent elsewhere.
  lane?: number;
  // Post-layout rail hints (assignDataRails): the middle segment centered in the
  // clear gap between the endpoint nodes' boxes, so a wrap-around never hugs a
  // node border. Absent when the boxes overlap on that axis (midpoint fallback).
  railX?: number;
  railY?: number;
  // Set by applyFocus on incident data edges: which end the clicked node is on.
  // DataEdge draws the line solid at that end, fading a hint toward the other.
  focusEnd?: "source" | "target";
  loop?: LoopSpec; // present only on synthesized loop-back arcs
};

export type FlowNode =
  | Node<LeafData, "node">
  | Node<PortsData, "ports">
  | Node<GroupData, "group">
  | Node<EndData, "end">;
export type FlowEdge = Edge<EdgeData>;

// Size estimates feed ELK and are applied as the node's rendered box, so they
// must match what the components draw (the components fill width/height: 100%).
// Heights shared with CSS rules come from METRICS (single source — the stylesheet
// reads the same values as injected CSS vars); the widths/paddings below are
// TS-only (CSS doesn't pin them). Re-tune live against the real DOM if it drifts.
export const DETAILED_WIDTH = 320;
export const COMPACT_WIDTH = 230;
export const HEADER_HEIGHT = METRICS.nodeHeaderH; // tile + small padding (both densities)
export const ROW_HEIGHT = METRICS.rowH;
export const ROW_PADDING = 14;
export const END_SIZE = 46;
export const PORTS_WIDTH = 200;
export const PORTS_HEADER_HEIGHT = METRICS.portsHeaderH;
export const COLLAPSED_GROUP_WIDTH = 240;
export const COLLAPSED_GROUP_HEIGHT = 84;

function leafSize(
  node: RFNode,
  density: Density,
  direction: Direction,
  outputFields: string[],
  branchLabels: string[],
  expanded: boolean,
): { width: number; height: number } {
  // Fork rows show only in LR (the n8n-style labeled border handles). In TD the forks
  // fan from the icon column and their labels ride the edges, so no rows are drawn.
  const branchRows = direction === "LR" ? branchLabels.length : 0;
  // A focus-expanded card renders the full advanced body, so it takes the advanced box.
  const showsBody = density === "detailed" || expanded;
  const width = showsBody ? DETAILED_WIDTH : COMPACT_WIDTH;
  // The 56px icon tile is taller than even a 2-line description, so it dominates the
  // header height — keep it a fixed HEADER_HEIGHT. That also keeps the tile vertically
  // CENTERED (equal inset top/bottom), which the connector stubs depend on.
  if (!showsBody) {
    return { width, height: HEADER_HEIGHT + branchRows * ROW_HEIGHT };
  }
  const rows = node.params.length + outputFields.length + branchRows;
  return { width, height: HEADER_HEIGHT + rows * ROW_HEIGHT + ROW_PADDING };
}

// Control-flow edge kinds — these connect at a node's NODE_IN/NODE_OUT (the trunk),
// so they drive the icon connector stubs. data_flow lands on param rows; loop is a
// self-arc — neither implies a trunk in/out. Exported for layout.ts (straightness
// priorities + error-branch ordering work on control edges only).
export const CONTROL_KINDS: ReadonlySet<EdgeKind> = new Set<EdgeKind>(["sequential", "branch", "error", "end"]);

const NO_EXPANSION: ReadonlySet<string> = new Set();

// The expansion set for a focus in beautiful mode: the focused leaf plus every leaf
// on the other end of one of its DATA-FLOW lines. Those cards render their advanced
// body so the revealed lines land on actual rows (source's output row → target's
// param row) instead of carrying a floating "stdout → data" label. Control-flow
// neighbors stay compact — their connection already reads fine at node level.
// `focus` may be a leaf id, an individual IO port id, or a ports-node id (the
// consolidated Inputs/Outputs box reuses its wrapper group's id → all member ports).
export function expandTargets(graph: RFGraph, focus: string | null): ReadonlySet<string> {
  if (!focus) return NO_EXPANSION;
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const wrapper = graph.groups.find(
    (g) => g.id === focus && (g.kind === "input_wrapper" || g.kind === "output_wrapper"),
  );
  const foci = new Set<string>(wrapper ? wrapper.members : [focus]);
  // Only a leaf card can expand: IO ports always show rows, a group host has no card,
  // and an end sink has no body.
  const expandable = (id: string): boolean => {
    const n = nodeById.get(id);
    return n != null && n.io === null && !n.is_group_host && n.kind !== "end";
  };
  const out = new Set<string>();
  for (const id of foci) if (expandable(id)) out.add(id);
  for (const e of graph.edges) {
    if (e.kind !== "data_flow") continue;
    if (!foci.has(e.source) && !foci.has(e.target)) continue;
    if (expandable(e.source)) out.add(e.source);
    if (expandable(e.target)) out.add(e.target);
  }
  return out;
}

export function buildFlow(graph: RFGraph, view: BuildOptions): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));
  const expandedSet = view.expanded ?? NO_EXPANSION;

  // Which nodes have a control edge flowing IN / OUT — drives the connector stubs.
  const incomingControl = new Set<string>();
  const outgoingControl = new Set<string>();
  for (const e of graph.edges) {
    if (!CONTROL_KINDS.has(e.kind)) continue;
    incomingControl.add(e.target);
    outgoingControl.add(e.source);
  }

  // A host node may back several groups (a dynamic-batch-of-subworkflow hosts
  // both a batch and a workflow group — H8). Edges into the suppressed host land
  // on the OUTERMOST of them; the rest nest inside.
  const groupsByHost = new Map<string, RFGroup[]>();
  for (const g of graph.groups) {
    if (g.host) {
      const list = groupsByHost.get(g.host) ?? [];
      list.push(g);
      groupsByHost.set(g.host, list);
    }
  }
  const primaryGroupForHost = new Map<string, string>();
  for (const [host, groups] of groupsByHost) {
    const outerCandidates = groups.filter((g) => {
      if (!g.parent) return true;
      return groupById.get(g.parent)?.host !== host;
    });
    const pool = outerCandidates.length > 0 ? outerCandidates : groups;
    const outer = pool.reduce((a, b) => (b.nesting_depth < a.nesting_depth ? b : a));
    primaryGroupForHost.set(host, outer.id);
  }

  // Output fields a node exposes as right-side ports: the distinct output_field
  // of its outgoing data-flow edges. Computed from the raw edges (only used when
  // an edge keeps its real source — re-anchored edges fall back to node-level).
  const outputFieldsByNode = new Map<string, Set<string>>();
  // Branch outcomes a decision node forks on — one labeled source handle per
  // outcome, in declared order (deduped). Drives the n8n-Switch-style border ports.
  const branchLabelsByNode = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (e.kind === "data_flow" && e.output_field) {
      const set = outputFieldsByNode.get(e.source) ?? new Set<string>();
      set.add(e.output_field);
      outputFieldsByNode.set(e.source, set);
    }
    if (e.kind === "branch" && e.label) {
      const labels = branchLabelsByNode.get(e.source) ?? [];
      if (!labels.includes(e.label)) labels.push(e.label);
      branchLabelsByNode.set(e.source, labels);
    }
  }

  // Consolidate each input_wrapper/output_wrapper group into ONE Inputs/Outputs node
  // whose rows are its member IO ports (the table-node pattern). The IO member nodes
  // are NOT emitted; each maps to (its ports node, its row handle). The ports node
  // reuses the wrapper's group id (no node uses a g* id, so no collision).
  const ioWrappers = graph.groups.filter(
    (g) => (g.kind === "input_wrapper" || g.kind === "output_wrapper") && g.members.length > 0,
  );
  const ioNodeToPortsNode = new Map<string, string>(); // IO node id -> its ports node id
  for (const wrapper of ioWrappers) {
    for (const memberId of wrapper.members) {
      if (nodeById.get(memberId)?.io != null) {
        ioNodeToPortsNode.set(memberId, wrapper.id);
      }
    }
  }

  const collapsed = view.collapsed;
  const groupParent = (id: string): string | null => groupById.get(id)?.parent ?? null;

  // The root-most collapsed group in the chain [start..root]. `inclusive` decides
  // whether `start` itself counts. A leaf/group hidden by collapse re-anchors to
  // this group (collapsing further if its parent is also collapsed).
  const outermostCollapsed = (start: string | null, inclusive: boolean): string | null => {
    let cur = inclusive ? start : start ? groupParent(start) : null;
    let result: string | null = null;
    while (cur) {
      if (collapsed.has(cur)) result = cur;
      cur = groupParent(cur);
    }
    return result;
  };

  const flowNodes: FlowNode[] = [];
  const emitted = new Set<string>();

  // Groups first, parents before children (ascending nesting_depth) — React Flow
  // requires a parent node to precede its children in the array.
  for (const g of [...graph.groups].sort((a, b) => a.nesting_depth - b.nesting_depth)) {
    if (g.kind === "input_wrapper" || g.kind === "output_wrapper") continue; // → a ports node, emitted below
    if (outermostCollapsed(g.parent, true)) continue; // inside a collapsed ancestor
    const isCollapsed = collapsed.has(g.id);
    const hostNode = g.host ? (nodeById.get(g.host) ?? null) : null;
    const showTitle = g.host != null && primaryGroupForHost.get(g.host) === g.id;
    flowNodes.push({
      id: g.id,
      type: "group",
      position: { x: 0, y: 0 },
      parentId: g.parent ?? undefined,
      extent: g.parent ? "parent" : undefined,
      data: {
        group: g,
        hostNode,
        collapsed: isCollapsed,
        showTitle,
        direction: view.direction,
        dimmed: false,
        focused: false,
      },
      ...(isCollapsed ? { width: COLLAPSED_GROUP_WIDTH, height: COLLAPSED_GROUP_HEIGHT } : {}),
    });
    emitted.add(g.id);
  }

  for (const n of graph.nodes) {
    if (n.is_group_host) continue; // represented by its group box
    if (n.io !== null) continue; // IO nodes are rows on a ports node (emitted below)
    if (outermostCollapsed(n.parent, true)) continue; // inside a collapsed group
    const parentId = n.parent ?? undefined;
    const extent = n.parent ? ("parent" as const) : undefined;
    if (n.kind === "end") {
      flowNodes.push({
        id: n.id,
        type: "end",
        position: { x: 0, y: 0 },
        parentId,
        extent,
        width: END_SIZE,
        height: END_SIZE,
        data: { node: n, direction: view.direction, dimmed: false, focused: false },
      });
    } else {
      const outputFields = [...(outputFieldsByNode.get(n.id) ?? [])];
      const branchLabels = branchLabelsByNode.get(n.id) ?? [];
      const isExpanded = view.density === "compact" && expandedSet.has(n.id);
      const size = leafSize(n, view.density, view.direction, outputFields, branchLabels, isExpanded);
      flowNodes.push({
        id: n.id,
        type: "node", // one leaf component at two densities; density rides in data
        position: { x: 0, y: 0 },
        parentId,
        extent,
        width: size.width,
        height: size.height,
        data: {
          node: n,
          density: view.density,
          direction: view.direction,
          outputFields,
          branchLabels,
          hasIncoming: incomingControl.has(n.id),
          hasOutgoing: outgoingControl.has(n.id),
          expanded: isExpanded,
          dimmed: false,
          focused: false,
        },
      });
    }
    emitted.add(n.id);
  }

  // One Inputs/Outputs node per wrapper (rows = its IO ports). Lives where the
  // wrapper did (parentId = wrapper.parent = the workflow group), shown in both
  // densities. Hidden only when its workflow group is collapsed.
  for (const wrapper of ioWrappers) {
    if (outermostCollapsed(wrapper.parent, true)) continue;
    const ports: Port[] = wrapper.members
      .map((memberId) => nodeById.get(memberId))
      .filter((m): m is RFNode => m != null && m.io != null)
      .map((m) => ({ id: m.id, name: m.ref.node_id, dataType: m.io!.data_type, required: m.io!.required }));
    if (ports.length === 0) continue;
    flowNodes.push({
      id: wrapper.id,
      type: "ports",
      position: { x: 0, y: 0 },
      parentId: wrapper.parent ?? undefined,
      extent: wrapper.parent ? "parent" : undefined,
      width: PORTS_WIDTH,
      height: PORTS_HEADER_HEIGHT + ports.length * ROW_HEIGHT + 8,
      data: {
        kind: wrapper.kind === "input_wrapper" ? "input" : "output",
        ports,
        direction: view.direction,
        focusedPortId: null,
        dimmed: false,
        focused: false,
      },
    });
    emitted.add(wrapper.id);
  }

  // Map a contract node id to the flow node that represents it on-canvas, or null
  // if it has no representation (defensive — should not happen).
  const renderAnchor = (nodeId: string): string | null => {
    if (emitted.has(nodeId)) return nodeId;
    const node = nodeById.get(nodeId);
    if (!node) return null;
    if (node.io != null) {
      // IO node → its consolidated ports node (or that node's collapsed ancestor).
      const portsId = ioNodeToPortsNode.get(nodeId);
      if (!portsId) return null;
      if (emitted.has(portsId)) return portsId;
      const anchor = outermostCollapsed(groupById.get(portsId)?.parent ?? null, true);
      return anchor && emitted.has(anchor) ? anchor : null;
    }
    if (node.is_group_host) {
      const gid = primaryGroupForHost.get(node.id);
      if (!gid) return null;
      const hiddenAnc = outermostCollapsed(groupById.get(gid)?.parent ?? null, true);
      if (hiddenAnc) return emitted.has(hiddenAnc) ? hiddenAnc : null;
      return emitted.has(gid) ? gid : null;
    }
    const anchor = outermostCollapsed(node.parent, true);
    return anchor && emitted.has(anchor) ? anchor : null;
  };

  const detailed = view.density === "detailed";
  // Rows are visible on an endpoint when the whole view is advanced OR that node is
  // focus-expanded — handle resolution is per-ENDPOINT, so a data line lands on a row
  // wherever the row actually renders (and only there — the silent-drop rule).
  const rowsVisible = (id: string): boolean => detailed || expandedSet.has(id);
  const flowEdges: FlowEdge[] = [];
  const seen = new Set<string>();
  for (const e of graph.edges) {
    const source = renderAnchor(e.source);
    const target = renderAnchor(e.target);
    if (!source || !target) {
      // Every contract edge endpoint has an on-canvas representative (itself, its
      // group, or a collapsed ancestor) — a null anchor means a broken invariant.
      // Warn rather than drop silently so a future regression is observable (the
      // worst outcome for the "no information loss" bar is an invisibly-lost edge).
      console.warn(`pflow UI: dropped edge ${e.id} (${e.source} -> ${e.target}) — no on-canvas anchor`);
      continue;
    }
    if (source === target) continue; // collapsed/host self-loop — a correct drop

    const sourceHandle = sourceHandleFor(e, source, rowsVisible(e.source), view.direction, outputFieldsByNode, nodeById, ioNodeToPortsNode);
    const targetHandle = targetHandleFor(e, target, rowsVisible(e.target), nodeById, ioNodeToPortsNode);

    const key = `${source}->${target}|${e.kind}|${e.label ?? ""}|${sourceHandle}|${targetHandle}`;
    if (seen.has(key)) continue;
    seen.add(key);
    // Control edges (sequential/branch) draw as a source-node-color → target-node-
    // color gradient (the GradientEdge custom edge). Colors come from the ORIGINAL
    // endpoints (the real producer→consumer), even when re-anchored — via nodeColor,
    // so a condition node's fan-out leaves in condition orange, not code yellow.
    // error/end/data keep their semantic colors (see toFlowEdge / CSS).
    const sourceNode = nodeById.get(e.source);
    const targetNode = nodeById.get(e.target);
    const sourceColor = sourceNode ? nodeColor(sourceNode) : kindColor("");
    const targetColor = targetNode ? nodeColor(targetNode) : kindColor("");
    flowEdges.push(toFlowEdge(e, source, target, sourceHandle, targetHandle, detailed, view.direction, sourceColor, targetColor));
  }

  // Synthesize a loop-back arc for each looped node, drawn on the node — or on its
  // GROUP when it's a looped sub-workflow host. It is NOT a contract edge; we build
  // it from the LoopSpec (pure visual policy). Self-loops are dropped from ELK
  // (layout.ts) and rendered by the custom LoopEdge. Skip a loop whose node is
  // hidden inside a *collapsed ancestor* (the loop is hidden with it) — only draw
  // on the box that actually loops.
  const loopAnchors = new Set<string>();
  for (const n of graph.nodes) {
    if (!n.loop) continue;
    const anchor = renderAnchor(n.id);
    if (!anchor || loopAnchors.has(anchor)) continue;
    const ownsAnchor = anchor === n.id || anchor === primaryGroupForHost.get(n.id);
    if (!ownsAnchor) continue;
    loopAnchors.add(anchor);
    flowEdges.push({
      id: `loop:${anchor}`,
      source: anchor,
      target: anchor,
      sourceHandle: NODE_OUT,
      targetHandle: NODE_IN,
      type: "loop",
      className: "edge-loop",
      data: { kind: "loop", shadowed: false, from: n.id, to: n.id, defaultHidden: false, loop: n.loop },
      zIndex: 20,
    });
  }

  assignEdgeLanes(flowEdges);
  return { nodes: flowNodes, edges: flowEdges };
}

// Edges entering/leaving a node all turned at the SAME default stub, so parallel
// lines overlapped pixel-exactly into one ambiguous segment (user-caught, twice):
// data bindings (a 6-row Inputs node feeding one consumer), and LR branch fan-outs
// (each outcome leaves its OWN labeled row handle, yet all merged onto one rail).
// Give each such edge a LANE: the smallest bucket unused among the laned edges
// already assigned at EITHER of its endpoint nodes. DataEdge turns the lane into
// geometry always; GradientEdge applies it in LR ONLY — in TD a fork's branches
// leave ONE point (the icon column), so the shared rail IS the trunk-split look,
// by design. Sequential edges are exempt (one out per node; merges come from
// different sources, so their rails already differ). Build-time (lane multiplexing,
// not geometry).
export const LANE_COUNT = 6; // wraps past 6 parallel lanes at one node (collision acceptable)
const LANED_KINDS = new Set<EdgeKind | "loop">(["data_flow", "branch", "error"]);

function assignEdgeLanes(edges: FlowEdge[]): void {
  const used = new Map<string, Set<number>>();
  const usedAt = (id: string): Set<number> => used.get(id) ?? used.set(id, new Set()).get(id)!;
  for (const e of edges) {
    if (!e.data || !LANED_KINDS.has(e.data.kind)) continue;
    const taken = new Set([...usedAt(e.source), ...usedAt(e.target)]);
    let lane = 0;
    while (taken.has(lane % LANE_COUNT) && lane < LANE_COUNT) lane += 1;
    lane %= LANE_COUNT;
    usedAt(e.source).add(lane);
    usedAt(e.target).add(lane);
    e.data.lane = lane;
  }
}

function sourceHandleFor(
  edge: RFEdge,
  source: string,
  rowsVisible: boolean, // the source node renders its body rows (advanced, or focus-expanded)
  direction: Direction,
  outputFieldsByNode: Map<string, Set<string>>,
  nodeById: Map<string, RFNode>,
  ioNodeToPortsNode: Map<string, string>,
): string {
  // An IO source feeds OUT on its row's source handle — but only when the edge
  // actually reaches the ports node (not a collapsed ancestor it re-anchored past).
  if (nodeById.get(edge.source)?.io != null) {
    return source === ioNodeToPortsNode.get(edge.source) ? portHandle(edge.source) : NODE_OUT;
  }
  const isRealSource = source === edge.source;
  // LR: a fork leaves its own labeled border handle (n8n-style — which value goes
  // where). TD: forks fan from the icon column, so a branch leaves NODE_OUT (below
  // the icon) and its label rides the edge instead (toFlowEdge), like the references.
  if (isRealSource && edge.kind === "branch" && edge.label && direction === "LR") {
    return branchHandle(edge.label);
  }
  if (rowsVisible && isRealSource && edge.kind === "data_flow" && edge.output_field) {
    if (outputFieldsByNode.get(edge.source)?.has(edge.output_field)) {
      return outputHandle(edge.output_field);
    }
  }
  return NODE_OUT;
}

function targetHandleFor(
  edge: RFEdge,
  target: string,
  rowsVisible: boolean, // the target node renders its body rows (advanced, or focus-expanded)
  nodeById: Map<string, RFNode>,
  ioNodeToPortsNode: Map<string, string>,
): string {
  const node = nodeById.get(edge.target);
  if (node?.io != null) {
    // An IO target RECEIVES on its row's target handle (an input bound from the
    // parent, an output written by a producer) — these are the binding edges.
    return target === ioNodeToPortsNode.get(edge.target) ? portTargetHandle(edge.target) : NODE_IN;
  }
  const isRealTarget = target === edge.target;
  if (rowsVisible && isRealTarget && edge.kind === "data_flow" && edge.input_name) {
    if (node?.params.some((p) => p.name === edge.input_name)) {
      return paramHandle(edge.input_name);
    }
    // input_name may be a KEY inside a dict-valued param (a code node's
    // `inputs: {data: ${...}}` — the edge builder walks dict-of-string leaves, so
    // the edge carries the dict key, not the param name). Land on the param row that
    // CONTAINS the key — but only when that key's value is itself a `${...}` string,
    // the exact condition that created the edge. Anything else stays the node-level
    // fallback: degrade, never mis-attribute (H6).
    const key = edge.input_name;
    const host = node?.params.find((p) => {
      if (typeof p.value !== "object" || p.value === null || Array.isArray(p.value)) return false;
      const v = (p.value as Record<string, unknown>)[key];
      return typeof v === "string" && v.includes("${");
    });
    if (host) return paramHandle(host.name);
  }
  return NODE_IN;
}

// What flows on a data-flow line, e.g. "stdout → data". Shown as the edge label in
// beautiful mode only (advanced shows the field names as node rows, so a label there
// would just duplicate them).
function dataFlowLabel(edge: RFEdge): string | undefined {
  const { output_field: out, input_name: inp } = edge;
  if (out && inp) return `${out} → ${inp}`;
  return out ?? inp ?? undefined;
}

function toFlowEdge(
  edge: RFEdge,
  source: string,
  target: string,
  sourceHandle: string,
  targetHandle: string,
  detailed: boolean,
  direction: Direction,
  sourceColor: string,
  targetColor: string,
): FlowEdge {
  const isData = edge.kind === "data_flow";
  // ALL control flow draws via the custom "gradient" edge, which owns the stroke
  // COLOR: sequential/branch blend source→target; error/end keep their semantic
  // color with a short node-color fade at the node ends (see GradientEdge). Only
  // data-flow stays React Flow's "default" edge, stroked by CSS. Dash patterns +
  // shadow opacity are CSS, via the className.
  const isControl = CONTROL_KINDS.has(edge.kind);
  const classes = [`edge-${edge.kind}`];
  // Advanced DIMS a control edge a data line already covers; beautiful hides the
  // data lines, so its control edges show full-strength (not shadow-dimmed).
  if (edge.shadowed && detailed) classes.push("edge-shadowed");
  // Branch labels ride the border handle in LR (BranchPorts), so the edge is
  // unlabeled there; in TD the forks fan from the icon column, so the label rides the
  // edge. A beautiful data line is labeled with what it carries — UNLESS both of its
  // ends land on visible rows (focus-expanded cards / IO port rows), where the rows
  // themselves already name the fields, exactly like advanced mode.
  const rowToRow = sourceHandle !== NODE_OUT && targetHandle !== NODE_IN;
  const label =
    edge.kind === "branch"
      ? direction === "TD"
        ? (edge.label ?? undefined)
        : undefined
      : isData && !detailed && !rowToRow
        ? dataFlowLabel(edge)
        : (edge.label ?? undefined);
  // No arrowheads — clean lines flow straight into the node borders (the seamless
  // look). Beautiful = control skeleton: data-flow edges are built but hidden, and
  // applyFocus reveals just the ones touching the clicked node. Advanced shows them.
  const defaultHidden = isData && !detailed;
  return {
    id: edge.id,
    source,
    target,
    sourceHandle,
    targetHandle,
    // Data-flow uses the custom DataEdge ("data") so EVERY edge speaks the same
    // rounded-orthogonal language as the control edges (GradientEdge) — a bezier
    // here swoops across node bodies when an output row feeds the node below. The
    // component owns the stroke (lane tint + endpoint node-color fades); CSS keeps
    // only the dash pattern. The per-edge lane rides data.lane (assignDataEdgeLanes).
    type: isControl ? "gradient" : "data",
    label,
    className: classes.join(" "),
    data: { kind: edge.kind, shadowed: edge.shadowed, from: edge.source, to: edge.target, defaultHidden, sourceColor, targetColor },
    hidden: defaultHidden,
  };
}

const DIMMED_EDGE_CLASS = "edge-dimmed";

function stripDim(className: string | undefined): string {
  return (className ?? "")
    .split(" ")
    .filter((c) => c && c !== DIMMED_EDGE_CLASS)
    .join(" ");
}

// Focus+context: dim everything not incident to the focused node. A pure styling
// pass over already-laid-out nodes — NO re-layout (the plan: focus is "the same
// data + an interaction"). Returns fresh node/edge objects so React Flow re-renders
// the changed styling. Groups are never dimmed (they carry context for the focus).
// `focus=null` clears any prior dim/highlight.
// `focus` is a contract id — a node id, the ports-node id, OR an individual IO
// port's id (a row). An edge is incident if its flow endpoints OR its original
// endpoints (`data.from`/`to`) touch the focus, so a single port reveals just its
// own lines even though its edges re-anchor onto a shared ports node.
function edgeTouchesFocus(e: FlowEdge, focus: string): boolean {
  return e.source === focus || e.target === focus || e.data?.from === focus || e.data?.to === focus;
}

export function applyFocus(
  nodes: FlowNode[],
  edges: FlowEdge[],
  focus: string | null,
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const connected = new Set<string>();
  if (focus) {
    connected.add(focus);
    for (const e of edges) {
      if (edgeTouchesFocus(e, focus)) {
        connected.add(e.source);
        connected.add(e.target);
      }
    }
  }
  const outNodes = nodes.map((n) => {
    const focused = focus != null && n.id === focus;
    const dimmed = focus != null && n.type !== "group" && !connected.has(n.id);
    if (n.type === "ports") {
      // Highlight the focused row when an individual port is the focus.
      const focusedPortId = focus != null && n.data.ports.some((p) => p.id === focus) ? focus : null;
      if (n.data.focused === focused && n.data.dimmed === dimmed && n.data.focusedPortId === focusedPortId) {
        return n;
      }
      return { ...n, data: { ...n.data, focused, dimmed, focusedPortId } };
    }
    if (n.data.focused === focused && n.data.dimmed === dimmed) return n;
    return { ...n, data: { ...n.data, focused, dimmed } } as FlowNode;
  });
  const outEdges = edges.map((e) => {
    const incident = focus != null && edgeTouchesFocus(e, focus);
    // A default-hidden edge (beautiful mode's data-flow lines) is revealed when it
    // touches the focus — "show me this node's / port's data wiring." Edges hidden
    // by the build stay hidden otherwise; control edges are never default-hidden.
    // Read the build-time fact from data, NOT the mutable `hidden` flag this pass
    // writes — so re-processing decorated output can't misread a revealed edge.
    const defaultHidden = e.data?.defaultHidden === true;
    const hidden = defaultHidden && !incident;
    const base = stripDim(e.className);
    const dim = focus != null && !incident;
    const className = dim ? `${base} ${DIMMED_EDGE_CLASS}`.trim() : base;
    // Which END of an incident data line the focus sits on — DataEdge renders the
    // line solid at the clicked node and fading a hint toward the far end, so the
    // revealed wiring visibly BELONGS to the focus (user-chosen treatment).
    const focusEnd =
      incident && e.data?.kind === "data_flow"
        ? e.source === focus || e.data.from === focus
          ? ("source" as const)
          : ("target" as const)
        : undefined;
    if (className === e.className && hidden === (e.hidden ?? false) && focusEnd === e.data?.focusEnd) return e;
    return { ...e, className, hidden, ...(e.data ? { data: { ...e.data, focusEnd } } : {}) };
  });
  return { nodes: outNodes, edges: outEdges };
}
