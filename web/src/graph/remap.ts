// Live-reload view-state remap. A reload swaps the RFGraph for the SAME workflow,
// but flat ids (n{i}/g{j}) are POSITIONAL (the renderer enumerates), so a
// structural edit (insert/delete/reorder — NOT append) re-numbers them. Preserved
// selection/focus/collapse hold flat ids, which would then point at the WRONG node
// or dangle. We remap them through the STABLE structural ref (node_id +
// ancestor_path + port) — the contract's own runtime-overlay join key — so a
// still-existing node's selection follows it to its new flat id, and a vanished
// one clears. Identity is preserved when nothing renumbered (the common append
// case), so the build memo doesn't needlessly re-run.

import type { RFGraph, RFNode, RFRef } from "../types";

/** Two structural refs denote the same node iff node_id, port, and the full
 *  ancestor path (node_id + batch_index per step) match — the contract's stable
 *  identity, invariant across the positional flat-id renumbering. */
export function sameRef(a: RFRef, b: RFRef): boolean {
  if (a.node_id !== b.node_id || a.port !== b.port) return false;
  if (a.ancestor_path.length !== b.ancestor_path.length) return false;
  return a.ancestor_path.every((seg, i) => {
    const other = b.ancestor_path[i];
    return other !== undefined && seg.node_id === other.node_id && seg.batch_index === other.batch_index;
  });
}

function nodeByFlatId(graph: RFGraph, flatId: string): RFNode | undefined {
  return graph.nodes.find((n) => n.id === flatId);
}

/** Remap a node/io-port flat id. Returns the new flat id (node survived → follow
 *  it), null (vanished → clear), or undefined (not a node in `prev` — try group). */
function remapNodeFlatId(prev: RFGraph, next: RFGraph, flatId: string): string | null | undefined {
  const old = nodeByFlatId(prev, flatId);
  if (!old) return undefined;
  const match = next.nodes.find((n) => sameRef(n.ref, old.ref));
  return match ? match.id : null;
}

/** Remap a GROUP flat id. Collapsible/selectable containers (workflow/batch) carry
 *  a `host` node whose structural ref is the stable handle. Returns the new group
 *  flat id, null (host or group vanished → clear), or undefined (not a group in
 *  `prev`). A hostless wrapper (root IO card) has no stable handle to follow and
 *  isn't collapsible, so it clears rather than risk a wrong match. */
function remapGroupFlatId(prev: RFGraph, next: RFGraph, flatId: string): string | null | undefined {
  const old = prev.groups.find((g) => g.id === flatId);
  if (!old) return undefined;
  if (!old.host) return null;
  const oldHost = nodeByFlatId(prev, old.host);
  if (!oldHost) return null;
  const newHost = next.nodes.find((n) => sameRef(n.ref, oldHost.ref));
  if (!newHost) return null;
  const match = next.groups.find((g) => g.host === newHost.id && g.kind === old.kind);
  return match ? match.id : null;
}

/** Remap a focus/selection flat id (a node, io-port, group, or edge). Nodes and
 *  groups follow their structural identity; an edge or unknown id is left as-is
 *  (GraphView's edge-invalidation effect clears a vanished edge separately). */
export function remapSelection(prev: RFGraph, next: RFGraph, flatId: string | null): string | null {
  if (flatId == null) return null;
  const asNode = remapNodeFlatId(prev, next, flatId);
  if (asNode !== undefined) return asNode;
  const asGroup = remapGroupFlatId(prev, next, flatId);
  if (asGroup !== undefined) return asGroup;
  return flatId; // an edge id (or unknown) — left for the edge-invalidation effect
}

/** Remap the collapsed-container set. Each id follows its host's structural ref; a
 *  container that vanished or can't be mapped is dropped (reverts to expanded — the
 *  safe default). The ORIGINAL set is returned (same reference) when nothing
 *  renumbered, so a no-op reload doesn't churn the build memo. */
export function remapCollapsed(prev: RFGraph, next: RFGraph, collapsed: ReadonlySet<string>): ReadonlySet<string> {
  const out = new Set<string>();
  let changed = false;
  for (const id of collapsed) {
    const mapped = remapGroupFlatId(prev, next, id);
    if (mapped == null) {
      changed = true; // dropped (vanished/unmappable)
      continue;
    }
    if (mapped !== id) changed = true;
    out.add(mapped);
  }
  return changed ? out : collapsed;
}
