// URL <-> canvas view state. A view (which workflow, LR/TD, beautiful/advanced, and
// an optional node to frame the camera on) is fully described by the URL query, so a
// view is deep-linkable + shareable AND an agent can screenshot an exact state
// (e.g. ?workflow=x&direction=TD&density=beautiful&node=fetch-data) without driving
// the UI. The `workflow` param itself is owned by App.tsx; this module owns the three
// VIEW params. Pure (no React, no `window`) so it unit-tests node-env — the component
// passes `window.location.search` in and applies the returned string via history.

import type { Density, Direction } from "../graph/flow";
import type { RFGraph } from "../types";

export interface ViewParams {
  direction: Direction;
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
}

export const DEFAULT_VIEW: ViewParams = { direction: "LR", density: "compact", node: null, focus: null, collapse: null };

// The URL uses the USER-FACING density words (advanced/beautiful); the code uses the
// internal density (detailed/compact). Keep the mapping in one place so they can't drift.
const DENSITY_TO_PARAM: Record<Density, string> = { detailed: "advanced", compact: "beautiful" };
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
  return {
    direction: dir === "TD" || dir === "LR" ? dir : DEFAULT_VIEW.direction,
    density: (den !== null && PARAM_TO_DENSITY[den]) || DEFAULT_VIEW.density,
    node: node !== null && node.trim() !== "" ? node : null,
    focus: focus !== null && focus.trim() !== "" ? focus : null,
    collapse: collapse === "all" || collapse === "none" ? collapse : null,
  };
}

/** A new query string with direction/density set to their user-facing words, every
 *  OTHER param (workflow, node, …) preserved. Used for replaceState write-back on a
 *  toolbar toggle. `node` is read-only, so it is never written here. */
export function writeViewParams(search: string, patch: { direction?: Direction; density?: Density }): string {
  const p = new URLSearchParams(search);
  if (patch.direction) p.set("direction", patch.direction);
  if (patch.density) p.set("density", DENSITY_TO_PARAM[patch.density]);
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
  if (match && renderedIds.has(match.id)) return match.id;
  if (match) {
    const representative = graph.groups.find(
      (g) => g.host === match.id && !(g.kind === "batch" && g.members.length === 0),
    );
    if (representative && renderedIds.has(representative.id)) return representative.id;
  }
  if (renderedIds.has(nodeValue)) return nodeValue; // flat-id fallback
  return null;
}
