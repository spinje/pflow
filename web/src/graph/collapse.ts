// Collapse policy: which containers CAN collapse, and which state a workflow OPENS
// in. Pure (no React) so it unit-tests node-env, like the rest of graph/.
//
// Big workflows open as an OVERVIEW: when the contract exceeds the node budget,
// every collapsible group starts collapsed — the root pipeline reads as a handful
// of boxes, and one click expands the part you care about. Small workflows open
// fully expanded exactly as before (nobody wants an 8-node flow greeting them with
// a closed box). An explicit `collapse=` URL param overrides the auto rule in both
// directions, and a `node=`/`focus=` deep link is never hidden — its ancestor chain
// of groups stays expanded so the link always shows its target.

import { shellBatchIds } from "./flow";
import type { RFGraph } from "../types";

// Roughly where a fully-expanded canvas stops being readable at fit-zoom — also the
// scale where the first ELK layout starts costing real time, so the overview default
// doubles as a faster first paint.
export const AUTO_COLLAPSE_NODE_BUDGET = 60;

export type CollapseMode = "all" | "none" | null;

/** Every group id that can collapse on the canvas: workflow/batch containers. IO
 *  wrappers are excluded — they render as IO rows on their owner node, not group boxes.
 *  Shell batch groups (flow.ts shellBatchIds — the single copy of the rule) are
 *  excluded too: buildFlow never renders them, so they can't be toggled and must not
 *  inflate the N/M count. A LITERAL batch group with expanded item groups is NOT a
 *  shell — it renders as a real box and collapses like any container. */
export function collapsibleGroupIds(graph: RFGraph): string[] {
  const shells = shellBatchIds(graph);
  return graph.groups
    .filter((g) => (g.kind === "workflow" || g.kind === "batch") && !shells.has(g.id))
    .map((g) => g.id);
}

/** Expand every collapsed ancestor needed to render the given contract nodes. */
export function revealNodes(
  graph: RFGraph,
  collapsed: ReadonlySet<string>,
  nodeIds: readonly string[],
): ReadonlySet<string> {
  if (collapsed.size === 0) return collapsed;
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const groupById = new Map(graph.groups.map((group) => [group.id, group]));
  const next = new Set(collapsed);
  let changed = false;
  for (const nodeId of nodeIds) {
    let parent = nodeById.get(nodeId)?.parent ?? null;
    while (parent) {
      if (next.delete(parent)) changed = true;
      parent = groupById.get(parent)?.parent ?? null;
    }
  }
  return changed ? next : collapsed;
}

/** The collapsed set a workflow opens with. `mode` (the `collapse=` param) wins;
 *  otherwise auto: over-budget workflows open fully collapsed, others fully expanded.
 *  `protect` (deep-link targets — node_id, flat id, or a flat EDGE id) keeps each
 *  target visible by expanding its whole ancestor chain. An edge target protects
 *  BOTH endpoints: an auto-collapsed endpoint drops/re-anchors the edge out of the
 *  flow, and the selection invalidation then clears the deep link to a silent no-op. */
export function initialCollapsed(graph: RFGraph, mode: CollapseMode, protect: readonly (string | null)[]): ReadonlySet<string> {
  const all = collapsibleGroupIds(graph);
  const collapseAll = mode === "all" || (mode === null && graph.nodes.length > AUTO_COLLAPSE_NODE_BUDGET);
  if (!collapseAll) return new Set();
  const set = new Set(all);
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));
  const protectNode = (id: string | null | undefined): void => {
    const node = graph.nodes.find((n) => n.ref.node_id === id || n.id === id);
    let parent = node?.parent ?? null;
    while (parent) {
      set.delete(parent);
      parent = groupById.get(parent)?.parent ?? null;
    }
  };
  for (const target of protect) {
    if (!target) continue;
    const edge = graph.edges.find((e) => e.id === target);
    if (edge) {
      protectNode(edge.source);
      protectNode(edge.target);
    } else {
      protectNode(target);
    }
  }
  return set;
}
