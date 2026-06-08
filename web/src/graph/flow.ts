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
import { MarkerType } from "@xyflow/react";

import { branchHandle, NODE_IN, NODE_OUT, outputHandle, paramHandle, portHandle, portTargetHandle } from "./handles";
import { kindColor } from "../utils/format";
import type { EdgeKind, LoopSpec, RFEdge, RFGraph, RFGroup, RFNode } from "../types";

// Loop-back arcs are drawn amber; the marker color must be a literal (React Flow
// renders the SVG marker, not via CSS).
const LOOP_COLOR = "#f0b86c";

export type Density = "detailed" | "compact";
export type Direction = "LR" | "TD";

// What the structural build (and therefore ELK layout) depends on. Focus is
// deliberately NOT here: focus+context is a cheap styling pass (applyFocus) over
// already-laid-out nodes, so clicking a node never re-runs layout.
export interface BuildOptions {
  density: Density;
  direction: Direction;
  collapsed: ReadonlySet<string>;
}

// `type` (not `interface`) so each satisfies React Flow's `data extends
// Record<string, unknown>` constraint via the implicit-index-signature rule.
export type LeafData = {
  node: RFNode;
  density: Density;
  direction: Direction;
  outputFields: string[];
  branchLabels: string[]; // decision fork outcomes — labeled handles on the border
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
  loop?: LoopSpec; // present only on synthesized loop-back arcs
};

export type FlowNode =
  | Node<LeafData, "detailed">
  | Node<LeafData, "compact">
  | Node<PortsData, "ports">
  | Node<GroupData, "group">
  | Node<EndData, "end">;
export type FlowEdge = Edge<EdgeData>;

// Size estimates feed ELK and are applied as the node's rendered box, so they
// must match what the components draw (the components fill width/height: 100%).
export const DETAILED_WIDTH = 300;
export const COMPACT_WIDTH = 210;
export const COMPACT_HEIGHT = 58;
export const HEADER_HEIGHT = 56;
export const ROW_HEIGHT = 26;
export const ROW_PADDING = 14;
export const END_SIZE = 46;
export const PORTS_WIDTH = 200;
export const PORTS_HEADER_HEIGHT = 30;
export const COLLAPSED_GROUP_WIDTH = 240;
export const COLLAPSED_GROUP_HEIGHT = 84;

function leafSize(
  node: RFNode,
  density: Density,
  outputFields: string[],
  branchLabels: string[],
): { width: number; height: number } {
  // Branch (fork) rows show in BOTH densities — they're structure, not detail.
  const branchRows = branchLabels.length;
  if (density === "compact") {
    return { width: COMPACT_WIDTH, height: COMPACT_HEIGHT + branchRows * ROW_HEIGHT };
  }
  const rows = node.params.length + outputFields.length + branchRows;
  return { width: DETAILED_WIDTH, height: HEADER_HEIGHT + rows * ROW_HEIGHT + ROW_PADDING };
}

export function buildFlow(graph: RFGraph, view: BuildOptions): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));

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
      const size = leafSize(n, view.density, outputFields, branchLabels);
      flowNodes.push({
        id: n.id,
        type: view.density,
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

    const sourceHandle = sourceHandleFor(e, source, detailed, outputFieldsByNode, nodeById, ioNodeToPortsNode);
    const targetHandle = targetHandleFor(e, target, detailed, nodeById, ioNodeToPortsNode);

    const key = `${source}->${target}|${e.kind}|${e.label ?? ""}|${sourceHandle}|${targetHandle}`;
    if (seen.has(key)) continue;
    seen.add(key);
    // Control edges take their source node's type color (sequential/branch); a
    // stepping stone to the deferred source→target gradient. error/end/data keep
    // their semantic colors (see toFlowEdge / CSS).
    const sourceColor = kindColor(nodeById.get(e.source)?.kind ?? "");
    flowEdges.push(toFlowEdge(e, source, target, sourceHandle, targetHandle, detailed, sourceColor));
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
      data: { kind: "loop", shadowed: false, from: n.id, to: n.id, loop: n.loop },
      markerEnd: { type: MarkerType.ArrowClosed, color: LOOP_COLOR },
      zIndex: 20,
    });
  }

  return { nodes: flowNodes, edges: flowEdges };
}

function sourceHandleFor(
  edge: RFEdge,
  source: string,
  detailed: boolean,
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
  // A fork leaves its own labeled border handle (both densities) — that's how a
  // decision's outcomes are made legible (which value goes where).
  if (isRealSource && edge.kind === "branch" && edge.label) {
    return branchHandle(edge.label);
  }
  if (detailed && isRealSource && edge.kind === "data_flow" && edge.output_field) {
    if (outputFieldsByNode.get(edge.source)?.has(edge.output_field)) {
      return outputHandle(edge.output_field);
    }
  }
  return NODE_OUT;
}

function targetHandleFor(
  edge: RFEdge,
  target: string,
  detailed: boolean,
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
  if (detailed && isRealTarget && edge.kind === "data_flow" && edge.input_name) {
    if (node?.params.some((p) => p.name === edge.input_name)) {
      return paramHandle(edge.input_name);
    }
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
  sourceColor: string,
): FlowEdge {
  const isData = edge.kind === "data_flow";
  // sequential/branch take the source node's type color; error/end/data keep their
  // semantic CSS colors (red / faint / green dashed).
  const typeColored = edge.kind === "sequential" || edge.kind === "branch";
  const classes = [`edge-${edge.kind}`];
  // Advanced DIMS a control edge a data line already covers; beautiful hides the
  // data lines, so its control edges show full-strength (not shadow-dimmed).
  if (edge.shadowed && detailed) classes.push("edge-shadowed");
  // Branch labels ride the border handle; a beautiful data line is labeled with what
  // it carries (the node rows that would show it are collapsed); else the raw label.
  const label =
    edge.kind === "branch"
      ? undefined
      : isData && !detailed
        ? dataFlowLabel(edge)
        : (edge.label ?? undefined);
  return {
    id: edge.id,
    source,
    target,
    sourceHandle,
    targetHandle,
    type: "default", // smooth bezier for every edge (the curvy look)
    label,
    className: classes.join(" "),
    data: { kind: edge.kind, shadowed: edge.shadowed, from: edge.source, to: edge.target },
    markerEnd: isData ? undefined : { type: MarkerType.ArrowClosed, color: typeColored ? sourceColor : undefined },
    ...(typeColored ? { style: { stroke: sourceColor } } : {}),
    // Beautiful = control skeleton: data-flow edges are built but hidden, and
    // applyFocus reveals just the ones touching the clicked node (progressive
    // disclosure). Advanced shows them all.
    hidden: isData && !detailed,
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
    const defaultHidden = e.hidden === true;
    const hidden = defaultHidden && !incident;
    const base = stripDim(e.className);
    const dim = focus != null && !incident;
    const className = dim ? `${base} ${DIMMED_EDGE_CLASS}`.trim() : base;
    if (className === e.className && hidden === (e.hidden ?? false)) return e;
    return { ...e, className, hidden };
  });
  return { nodes: outNodes, edges: outEdges };
}
