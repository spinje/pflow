// Client-side layout with ELK (the GraphModel carries no positions — the contract
// is presentation-free). ELK handles pflow's nested/compound containers natively,
// and running it in the browser means collapse/expand re-layouts instantly with no
// server round-trip. Direction is a render knob (LR default, TD toggle).
//
// dagre is the documented fallback if ELK's bundle ever bites (plan §Risks); it
// would be isolated to this module.

import ELK, { type ElkExtendedEdge, type ElkNode } from "elkjs/lib/elk.bundled.js";

import type { Direction, FlowEdge, FlowNode } from "./flow";

const elk = new ELK();

const ELK_DIRECTION: Record<Direction, string> = { LR: "RIGHT", TD: "DOWN" };

// Top padding leaves room for the group header the GroupNode component draws.
const GROUP_PADDING = "[top=46,left=16,bottom=16,right=16]";

/** Run ELK over the flow nodes/edges and return them with positions + final box
 *  sizes. Child positions come back relative to their parent — exactly React
 *  Flow's parentId convention. */
export async function layoutGraph(nodes: FlowNode[], edges: FlowEdge[], direction: Direction): Promise<FlowNode[]> {
  if (nodes.length === 0) return nodes;

  const childrenByParent = new Map<string | undefined, FlowNode[]>();
  for (const node of nodes) {
    const key = node.parentId ?? undefined;
    const list = childrenByParent.get(key) ?? [];
    list.push(node);
    childrenByParent.set(key, list);
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
    "elk.layered.spacing.nodeNodeBetweenLayers": "140",
    "elk.spacing.nodeNode": "80",
    "elk.spacing.edgeNode": "32",
    "elk.layered.spacing.edgeEdgeBetweenLayers": "20",
    "elk.spacing.componentComponent": "80",
    "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  };

  const toElk = (node: FlowNode): ElkNode => {
    const children = childrenByParent.get(node.id) ?? [];
    const elkNode: ElkNode = { id: node.id, width: node.width ?? 200, height: node.height ?? 60 };
    if (children.length > 0) {
      elkNode.children = children.map(toElk);
      elkNode.layoutOptions = { ...layeredOptions, "elk.padding": GROUP_PADDING };
    }
    return elkNode;
  };

  // Layout reflects ALL structure (control + data), even edges that render hidden
  // (beautiful mode's data-flow lines) — otherwise a node connected only by data
  // would float as a disconnected island. Only self-loops (the loop-back arcs,
  // drawn by LoopEdge) are excluded; ELK must not route a node to itself.
  const elkEdges: ElkExtendedEdge[] = edges
    .filter((edge) => edge.source !== edge.target)
    .map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
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
