// Client-side layout with ELK (the GraphModel carries no positions — the contract
// is presentation-free). ELK handles pflow's nested/compound containers natively,
// and running it in the browser means collapse/expand re-layouts instantly with no
// server round-trip. Direction is a render knob (LR default, TD toggle).
//
// dagre is the documented fallback if ELK's bundle ever bites (plan §Risks); it
// would be isolated to this module.

import type { ELK, ElkExtendedEdge, ElkNode } from "elkjs/lib/elk.bundled.js";

import { CONTROL_KINDS, type Direction, type FlowEdge, type FlowNode } from "./flow";
import { NODE_IN, NODE_OUT } from "./handles";
import { ICON_COL_X, METRICS } from "./metrics";

// ELK is ~80% of the app bundle, and layoutGraph is already async — so it loads as
// its own chunk on first layout instead of blocking the initial page. Cached: one
// load per session. A failed chunk load rejects layoutGraph, which the hook already
// surfaces as the error banner (never a stuck "Laying out…").
//
// It runs in a WEB WORKER when possible: a 100+-node layout costs ~150ms, and on the
// main thread that freezes the canvas mid-click (measured on a real 128-node
// workflow). elk-api is the thin shell; the heavy GWT build loads inside the worker
// (Vite's `?worker` import bundles it as its own asset). The bundled main-thread ELK
// is the fallback — node-env tests (no Worker) take it silently; a browser where
// worker construction fails takes it with a warning (a silent fallback would be an
// invisible perf regression). The probe layout fails fast at load time so a broken
// worker can't poison the first real layout.
let elkLoad: Promise<ELK> | null = null;
const loadElk = (): Promise<ELK> => (elkLoad ??= createElk());

async function createElk(): Promise<ELK> {
  if (typeof Worker !== "undefined") {
    try {
      const [{ default: ElkApi }, { default: ElkWorker }] = await Promise.all([
        import("elkjs/lib/elk-api.js"),
        import("elkjs/lib/elk-worker.min.js?worker"),
      ]);
      const elk = new ElkApi({ workerFactory: () => new ElkWorker() }) as ELK;
      await elk.layout({ id: "probe", children: [{ id: "p", width: 1, height: 1 }], edges: [] });
      return elk;
    } catch (err) {
      console.warn("pflow UI: ELK worker unavailable — layouts will run on the main thread", err);
    }
  }
  const m = await import("elkjs/lib/elk.bundled.js");
  return new m.default();
}

const ELK_DIRECTION: Record<Direction, string> = { LR: "RIGHT", TD: "DOWN" };

// Top padding leaves room for the group header the GroupNode component draws
// (header height from METRICS + 8px breathing room below it).
const GROUP_PADDING = `[top=${METRICS.groupHeaderH + 8},left=16,bottom=16,right=16]`;

// Port ids for the TD icon-column ports (one pair per leaf node). Only minted
// inside this module — ELK-internal, never rendered.
const portIn = (id: string): string => `${id}::in`;
const portOut = (id: string): string => `${id}::out`;

/** Run ELK over the flow nodes/edges and return them with positions + final box
 *  sizes. Child positions come back relative to their parent — exactly React
 *  Flow's parentId convention. */
export async function layoutGraph(nodes: FlowNode[], edges: FlowEdge[], direction: Direction): Promise<FlowNode[]> {
  if (nodes.length === 0) return nodes;
  const elk = await loadElk();

  // Incoming CONTROL kinds per rendered target — drives the error-branch ordering
  // below (a node reached ONLY via an error edge is an error handler).
  const inKinds = new Map<string, Set<string>>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    const kind = e.data?.kind;
    if (!kind || kind === "loop" || !CONTROL_KINDS.has(kind)) continue;
    (inKinds.get(e.target) ?? inKinds.set(e.target, new Set()).get(e.target)!).add(kind);
  }
  // Error handlers order LAST among their siblings (the user-decided policy): the
  // happy path keeps the leftmost, straight-trunk column; error branches fan right.
  // considerModelOrder (below) makes ELK respect this list order.
  const isErrorOnly = (id: string): boolean => {
    const kinds = inKinds.get(id);
    return !!kinds && kinds.has("error") && !kinds.has("sequential") && !kinds.has("branch");
  };

  // A fork's targets order by their BRANCH-EDGE order — the code's if/elif/else
  // chain order, carried by contract edge order — so the FIRST condition lands
  // leftmost (TD) / topmost (LR). Steps-declaration order is irrelevant to how a
  // fork reads (user-decided 2026-06-10); the spatial ordinal labels then match
  // the code's reading order by construction. First branch in-edge wins per target.
  const branchOrder = new Map<string, { source: string; rank: number }>();
  {
    const rankBySource = new Map<string, number>();
    for (const e of edges) {
      if (e.source === e.target || e.data?.kind !== "branch") continue;
      const rank = rankBySource.get(e.source) ?? 0;
      rankBySource.set(e.source, rank + 1);
      if (!branchOrder.has(e.target)) branchOrder.set(e.target, { source: e.source, rank });
    }
  }

  const childrenByParent = new Map<string | undefined, FlowNode[]>();
  for (const node of nodes) {
    const key = node.parentId ?? undefined;
    const list = childrenByParent.get(key) ?? [];
    list.push(node);
    childrenByParent.set(key, list);
  }
  for (const [key, list] of childrenByParent) {
    const sorted = orderForkSiblings(list, branchOrder);
    childrenByParent.set(key, [...sorted.filter((n) => !isErrorOnly(n.id)), ...sorted.filter((n) => isErrorOnly(n.id))]);
  }

  // The layered + wrapping + spacing options. Applied to root AND to EVERY composite
  // (group) — ELK does not propagate these into nested subgraphs, so a long chain
  // inside a sub-workflow only wraps if its own container carries them too.
  const layeredOptions: Record<string, string> = {
    "elk.algorithm": "layered",
    "elk.direction": ELK_DIRECTION[direction],
    // Lets edges declared at the root connect nodes nested in different groups.
    "elk.hierarchyHandling": "INCLUDE_CHILDREN",
    // No width-cutoff wrapping (that folds a chain at arbitrary points and sweeps
    // edges back across the canvas). The honest model, like n8n: a sequence flows
    // in one direction; genuinely independent branches fan out on their own (ELK
    // stacks sibling targets across the cross-axis). A linear pipeline IS a line.
    // TD runs tighter between layers (the Tines look: rail close under the source,
    // short drops into the next row); LR keeps the wider gap that suits wide cards.
    "elk.layered.spacing.nodeNodeBetweenLayers": direction === "TD" ? "80" : "140",
    "elk.spacing.nodeNode": "80",
    "elk.spacing.edgeNode": "32",
    "elk.layered.spacing.edgeEdgeBetweenLayers": "20",
    "elk.spacing.componentComponent": "80",
    "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    // Siblings keep the input (model) order — deterministic, and the error-handlers-
    // last partition above becomes "error branches fan out rightmost". NOTE: this is
    // the ONLY model-order option that survives INCLUDE_CHILDREN — every
    // considerModelOrder.strategy crashes elkjs on a cross-hierarchy edge
    // ("Cannot read properties of undefined (reading 'a')", bisected 2026-06-09).
    "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
  };

  // TD only: leaf nodes declare FIXED ports at the icon column. The control handles
  // render there (WorkflowNode: left = ICON_COL_X), NOT at the node center — without
  // ports ELK aligns box centers, so every chain/merge got a ~100px jog between the
  // out-handle and the in-handle below it. Port-aware NETWORK_SIMPLEX aligns columns
  // icon-to-icon: chains and end-sinks go dead straight, and exactly one branch of a
  // fork/merge continues the trunk (the Tines pattern). LR handles are side-centered,
  // which matches ELK's default anchors — no ports needed there.
  const portable = new Set<string>();
  if (direction === "TD") {
    for (const node of nodes) {
      // Leaves AND collapsed groups: a collapsed group renders the same card
      // anatomy (GroupNode), handles on the icon column — without its ports the
      // trunk jogs at every collapsed sub-workflow. EXPANDED groups render their
      // handles at the icon column too (the trunk flows into the region's tile),
      // but get NO ELK port: a port on a COMPOUND node crashes elkjs under
      // INCLUDE_CHILDREN when an edge references it ("NEdge must have a source
      // and target NNode specified" — found in-browser 2026-06-10, same crash
      // family as considerModelOrder). ELK anchors region edges at the border
      // default; smoothstep absorbs the offset to the rendered handle.
      if (node.type === "node" || (node.type === "group" && node.data.collapsed)) portable.add(node.id);
    }
  }

  const toElk = (node: FlowNode): ElkNode => {
    const children = childrenByParent.get(node.id) ?? [];
    const elkNode: ElkNode = { id: node.id, width: node.width ?? 200, height: node.height ?? 60 };
    if (portable.has(node.id)) {
      elkNode.layoutOptions = { "elk.portConstraints": "FIXED_POS" };
      elkNode.ports = [
        { id: portIn(node.id), x: ICON_COL_X, y: 0, width: 0, height: 0 },
        { id: portOut(node.id), x: ICON_COL_X, y: elkNode.height, width: 0, height: 0 },
      ];
    }
    if (children.length > 0) {
      elkNode.children = children.map(toElk);
      elkNode.layoutOptions = { ...layeredOptions, "elk.padding": GROUP_PADDING };
    }
    return elkNode;
  };

  // The straight trunk: each target's FIRST incoming non-error control edge (model
  // order — the leftmost sibling after the error demotion) gets a straightness
  // priority, so NETWORK_SIMPLEX keeps THAT edge as the straight column and the
  // other branches pay the corner. Chains get it trivially (single in-edge).
  const straight = new Set<string>();
  const seenTarget = new Set<string>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    const kind = e.data?.kind;
    if (!kind || kind === "loop" || kind === "error" || !CONTROL_KINDS.has(kind)) continue;
    if (seenTarget.has(e.target)) continue;
    seenTarget.add(e.target);
    straight.add(e.id);
  }

  // Layout reflects ALL structure (control + data), even edges that render hidden
  // (beautiful mode's data-flow lines) — otherwise a node connected only by data
  // would float as a disconnected island. Only self-loops (the loop-back arcs,
  // drawn by LoopEdge) are excluded; ELK must not route a node to itself.
  // An endpoint whose rendered handle is the icon-column trunk (NODE_IN/NODE_OUT on a
  // ported leaf) connects to the matching ELK port; row-level handles (advanced data
  // lines, ports-node rows) stay node-level — same anchor approximation as before.
  const elkEdges: ElkExtendedEdge[] = edges
    .filter((edge) => edge.source !== edge.target)
    .map((edge) => ({
      id: edge.id,
      sources: [edge.sourceHandle === NODE_OUT && portable.has(edge.source) ? portOut(edge.source) : edge.source],
      targets: [edge.targetHandle === NODE_IN && portable.has(edge.target) ? portIn(edge.target) : edge.target],
      ...(straight.has(edge.id) ? { layoutOptions: { "elk.layered.priority.straightness": "10" } } : {}),
    }));

  const root: ElkNode = {
    id: "root",
    layoutOptions: layeredOptions,
    children: (childrenByParent.get(undefined) ?? []).map(toElk),
    edges: elkEdges,
  };

  const laidOut = await elk.layout(root);

  const boxes = new Map<string, { x: number; y: number; width: number; height: number }>();
  const collect = (node: ElkNode): void => {
    boxes.set(node.id, { x: node.x ?? 0, y: node.y ?? 0, width: node.width ?? 0, height: node.height ?? 0 });
    node.children?.forEach(collect);
  };
  laidOut.children?.forEach(collect);

  return nodes.map((node) => {
    const box = boxes.get(node.id);
    if (!box) {
      // ELK should place every node it was given; a miss would silently pile the
      // node at the origin. Warn so the loss is observable rather than invisible.
      console.warn(`pflow UI: ELK did not place node ${node.id}`);
      return node;
    }
    return {
      ...node,
      position: { x: box.x, y: box.y },
      width: box.width,
      height: box.height,
      style: { ...node.style, width: box.width, height: box.height },
    };
  });
}

/** Reorder a sibling list so each fork's targets follow their branch-edge order
 *  (the code's if/elif/else chain order). Targets of one fork CLUSTER at the
 *  position of their first occurrence in the list, internally sorted by rank;
 *  every other sibling keeps its model-order position. Pure — unit-tested. */
export function orderForkSiblings(list: FlowNode[], branchOrder: Map<string, { source: string; rank: number }>): FlowNode[] {
  const anchor = new Map<string, number>();
  list.forEach((node, i) => {
    const branch = branchOrder.get(node.id);
    if (branch && !anchor.has(branch.source)) anchor.set(branch.source, i);
  });
  return list
    .map((node, i) => {
      const branch = branchOrder.get(node.id);
      return { node, primary: branch ? anchor.get(branch.source)! : i, secondary: branch ? branch.rank : 0, stable: i };
    })
    .sort((a, b) => a.primary - b.primary || a.secondary - b.secondary || a.stable - b.stable)
    .map((entry) => entry.node);
}
