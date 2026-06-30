// URL <-> canvas view state. A view (which workflow, LR/TD, beautiful/advanced, and
// an optional node to frame the camera on) is fully described by the URL query, so a
// view is deep-linkable + shareable AND an agent can screenshot an exact state
// (e.g. ?workflow=x&direction=TD&density=beautiful&node=fetch-data) without driving
// the UI. The `workflow` param itself is owned by App.tsx; this module owns the three
// VIEW params. Pure (no React, no `window`) so it unit-tests node-env — the component
// passes `window.location.search` in and applies the returned string via history.

import { type Density, type Direction, shellBatchIds } from "../graph/flow";
import type { RFGraph, RFNode } from "../types";

export interface ViewParams {
  // LR/TD. null = AUTO: dense pipelines open TD (graph/direction.ts), like collapse's
  // auto. An explicit `direction=` always wins; the toolbar toggle then sets it.
  direction: Direction | null;
  density: Density;
  // A node to frame the camera on (a node_id, or a flat id as a fallback). null = fit
  // the whole graph. Read-only: a load-time camera instruction, never written back.
  node: string | null;
  // A node (or IO port) to FOCUS on load (a node_id, or a flat id as a fallback) — the
  // same state a click produces: dim non-incident, reveal data lines, and (beautiful)
  // expand the card + its data-flow endpoints. Read-only, like `node` — focus is
  // transient interaction state, never written back. Combine with `node=` to also
  // frame the camera on it.
  focus: string | null;
  // Initial collapse state: "all" opens as an overview, "none" fully expanded.
  // Absent = AUTO (big workflows open collapsed — see graph/collapse.ts). Read-only,
  // like `node` — collapse is transient interaction state, never written back.
  collapse: "all" | "none" | null;
  // Source pane open state. The width persists in localStorage; the open/closed
  // state rides the URL so screenshots/deep links can reproduce it.
  source: boolean;
  // Live source watch: poll for `.pflow.md` edits and re-fetch the graph in
  // place. On by default; `pflow ui --no-auto-update` opens with `watch=0` to freeze
  // the view. Read-only (a session preference), like the other view params.
  watch: boolean;
}

export const DEFAULT_VIEW: ViewParams = { direction: null, density: "compact", node: null, focus: null, collapse: null, source: false, watch: true };

// The URL uses the USER-FACING density words (advanced/beautiful); the code uses the
// internal density (detailed/compact). Keep the mapping in one place so they can't drift.
export const DENSITY_TO_PARAM: Record<Density, "advanced" | "beautiful"> = {
  detailed: "advanced",
  compact: "beautiful",
};
const PARAM_TO_DENSITY: Record<string, Density> = { advanced: "detailed", beautiful: "compact" };

/** Parse the three view params from a query string. Invalid/missing values fall back
 *  to DEFAULT_VIEW silently (a bad deep link still renders something sensible). */
export function readViewParams(search: string): ViewParams {
  const p = new URLSearchParams(search);
  const dir = p.get("direction");
  const den = p.get("density");
  const node = p.get("node");
  const focus = p.get("focus");
  const collapse = p.get("collapse");
  const source = p.get("source");
  return {
    direction: dir === "TD" || dir === "LR" ? dir : DEFAULT_VIEW.direction,
    density: (den !== null && PARAM_TO_DENSITY[den]) || DEFAULT_VIEW.density,
    node: node !== null && node.trim() !== "" ? node : null,
    focus: focus !== null && focus.trim() !== "" ? focus : null,
    collapse: collapse === "all" || collapse === "none" ? collapse : null,
    source: source === "1",
    watch: p.get("watch") !== "0", // on unless explicitly disabled (pflow ui --no-auto-update)
  };
}

/** A new query string with direction/density set to their user-facing words, every
 *  OTHER param (workflow, node, …) preserved. Used for replaceState write-back on a
 *  toolbar toggle. `node` is read-only, so it is never written here. `run` (Task 173 D6)
 *  PINS the live overlay to one run: a run_id sets it, `null` clears it (back to following
 *  newest) — written on a run-selector pick so the view is shareable + survives a reload. */
export function writeViewParams(
  search: string,
  patch: { direction?: Direction; density?: Density; source?: boolean; run?: string | null },
): string {
  const p = new URLSearchParams(search);
  if (patch.direction) p.set("direction", patch.direction);
  if (patch.density) p.set("density", DENSITY_TO_PARAM[patch.density]);
  if (patch.source !== undefined) p.set("source", patch.source ? "1" : "0");
  if (patch.run !== undefined) {
    if (patch.run) p.set("run", patch.run);
    else p.delete("run");
  }
  return p.toString();
}

/** Resolve a `node=` value to the flat React Flow id the camera should frame, or null
 *  (caller fits the whole graph). Prefers a structural node_id match — what an author
 *  knows from the .pflow.md — taking the FIRST match, since node_id is not globally
 *  unique across nested sub-workflows (documented limitation). A GROUP HOST's node is
 *  never rendered (its container represents it), so a host name resolves to its
 *  representative group — the workflow/batch group whose `host` it is, skipping
 *  memberless batch shells (flow.ts's `primaryGroupForHost` notion) — which makes
 *  `focus=<sub-workflow name>` select the card/region (agents, Task 169). Falls back
 *  to treating the value as a flat id (an agent's deterministic escape hatch for a
 *  duplicate). Returns null when nothing matched is currently rendered (hidden in a
 *  collapsed ancestor) — the caller degrades to a whole-graph fit. */
export function resolveNodeFlatId(
  graph: RFGraph | null,
  renderedIds: ReadonlySet<string>,
  nodeValue: string,
): string | null {
  if (!graph) return null;
  const match = graph.nodes.find((n) => n.ref.node_id === nodeValue);
  if (match) {
    const resolved = resolveEndpointFlatId(graph, renderedIds, match.id);
    if (resolved) return resolved;
  }
  if (renderedIds.has(nodeValue)) return nodeValue; // flat-id fallback
  return null;
}

/** Resolve a CONTRACT node id (an edge endpoint, a host) to the flat id that is
 *  actually rendered for it: the node itself, or — for a suppressed group host —
 *  its representative group (skipping decorator shells via flow.ts shellBatchIds,
 *  the single copy of the rule: a LITERAL batch group with expanded item groups IS
 *  the host's representative). Returns null when nothing is rendered (hidden inside
 *  a collapsed ancestor) — the caller must degrade VISIBLY (e.g. a non-clickable
 *  chip), never silently focus a ghost id. */
export function resolveEndpointFlatId(
  graph: RFGraph,
  renderedIds: ReadonlySet<string>,
  contractId: string,
): string | null {
  if (renderedIds.has(contractId)) return contractId;
  const ioWrapper = graph.groups.find(
    (g) => (g.kind === "input_wrapper" || g.kind === "output_wrapper") && g.members.includes(contractId),
  );
  if (ioWrapper && renderedIds.has(ioWrapper.id)) return ioWrapper.id;
  const shells = shellBatchIds(graph);
  const representative = graph.groups.find((g) => g.host === contractId && !shells.has(g.id));
  if (representative && renderedIds.has(representative.id)) return representative.id;
  return null;
}

/** The on-canvas representative of a node IGNORING current collapse state: a group
 *  host → its rendered group (skipping decorator shells, like resolveEndpointFlatId);
 *  a leaf → itself. Unlike resolveEndpointFlatId this does NOT gate on renderedIds —
 *  search-select expands the node's ancestor chain FIRST, so the representative is
 *  guaranteed to render even though it isn't in the current (pre-reveal) snapshot. */
export function nodeRepresentativeId(graph: RFGraph, node: RFNode): string {
  if (!node.is_group_host) return node.id;
  const shells = shellBatchIds(graph);
  const rep = graph.groups.find((g) => g.host === node.id && !shells.has(g.id));
  return rep ? rep.id : node.id;
}

/** What an edge CLICK does (pure — GraphView applies it; jsdom renders no edge
 *  DOM, so the dispatch is tested here, not through clicks). A `loop:` self-arc
 *  redirects to selecting its render ANCHOR (the flow edge's `source` — a GROUP
 *  id for a looped sub-workflow, flowing through the container-unit and
 *  group→host panel paths; never `data.from`, the suppressed host). A synthesized
 *  `io-flow:` edge has no contract identity: it focuses (restyle) and explicitly
 *  CLEARS the panel — leaving a stale node panel open beside an unrelated focused
 *  edge would misdescribe the selection. A contract edge selects fully. */
export function edgeClickAction(edge: { id: string; source: string }): { focus: string; selectedId: string | null } {
  if (edge.id.startsWith("loop:")) return { focus: edge.source, selectedId: edge.source };
  if (edge.id.startsWith("io-flow:")) return { focus: edge.id, selectedId: null };
  return { focus: edge.id, selectedId: edge.id };
}
