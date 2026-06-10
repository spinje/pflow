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

import type { RFGraph } from "../types";

// Roughly where a fully-expanded canvas stops being readable at fit-zoom — also the
// scale where the first ELK layout starts costing real time, so the overview default
// doubles as a faster first paint.
export const AUTO_COLLAPSE_NODE_BUDGET = 60;

export type CollapseMode = "all" | "none" | null;

/** Every group id that can collapse on the canvas: workflow/batch containers. IO
 *  wrappers are excluded — they render as IO rows on their owner node, not group boxes.
 *  Shell batch groups (no direct members — a batched leaf's empty decorator, or the
 *  wrapper around a batched sub-workflow's workflow group) are excluded too: buildFlow
 *  never renders them, so they can't be toggled and must not inflate the N/M count. */
export function collapsibleGroupIds(graph: RFGraph): string[] {
  return graph.groups
    .filter((g) => (g.kind === "workflow" || g.kind === "batch") && !(g.kind === "batch" && g.members.length === 0))
    .map((g) => g.id);
}

/** The collapsed set a workflow opens with. `mode` (the `collapse=` param) wins;
 *  otherwise auto: over-budget workflows open fully collapsed, others fully expanded.
 *  `protect` (deep-link targets — node_id or flat id) keeps each target visible by
 *  expanding its whole ancestor chain. */
export function initialCollapsed(graph: RFGraph, mode: CollapseMode, protect: readonly (string | null)[]): ReadonlySet<string> {
  const all = collapsibleGroupIds(graph);
  const collapseAll = mode === "all" || (mode === null && graph.nodes.length > AUTO_COLLAPSE_NODE_BUDGET);
  if (!collapseAll) return new Set();
  const set = new Set(all);
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));
  for (const target of protect) {
    if (!target) continue;
    const node = graph.nodes.find((n) => n.ref.node_id === target || n.id === target);
    let parent = node?.parent ?? null;
    while (parent) {
      set.delete(parent);
      parent = groupById.get(parent)?.parent ?? null;
    }
  }
  return set;
}
