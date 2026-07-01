// IO ownership + presentation-suppression rules: which flow node carries a
// wrapper's port rows (ioOwners / wrapperPorts) and which batch groups are
// decorator shells that must never render (shellBatchIds). Each is THE single
// copy of its rule — buildFlow, expandTargets, collapse.ts, viewParams.ts and
// the panels all import from here, never re-derive (three drifting copies is
// how the 2026-06-11 literal-batch bug shipped).

import { producedTypeOf } from "./scan";
import type { RFGraph, RFGroup, RFNode } from "../types";

// One IO row. `id` is the IO node's contract id — it doubles as the row's handle
// key and its focus target (click a row → focus that port). IO rows render ON the
// workflow's own node: the root IO card, a collapsed sub-workflow card, or an
// expanded region's sidebar/strip — never as a separate floating table.
export type Port = {
  id: string;
  name: string;
  dataType: string | null;
  required: boolean;
  // The authored `default:` value (inputs only); null when absent.
  defaultValue: unknown;
  // The authored description (the contract's `purpose`), inputs and outputs
  // alike. Surfaced as the row tooltip and the IoPanel entry.
  description: string | null;
  // Per-SIDE connection facts — something binds INTO the port (receives: an
  // edge targets it) / something reads FROM it (feeds: an edge sources it).
  // PortRows picks the side(s) its location presents (the `handles` prop) to
  // decide the wired styling: a sub-workflow output every caller ignores must
  // read grey on the collapsed card even though its INNER producer edge exists
  // (user-caught 2026-06-12). Canvas-truthful, never a consumption claim
  // (loop-condition reads form no edges — the quiet≠unconsumed rule).
  receives: boolean;
  feeds: boolean;
};

/** IO ownership — which flow node carries a wrapper's rows: the root IO card
 *  (the wrapper's own id) or the enclosing workflow group, reparented past
 *  decorator shells. `wrappers` maps wrapper id → owner; `ports` maps each IO
 *  member node → that owner. THE single copy of the rule: buildFlow (row
 *  emission + edge handle resolution) and expandTargets (focus expansion) both
 *  consume it — the same concept under two divergent rules 200 lines apart was
 *  a drift trap (review-caught 2026-06-11). Strict on purpose: only non-empty
 *  wrappers own rows, and only io-kind members are ports. */
export function ioOwners(graph: RFGraph): { wrappers: Map<string, string>; ports: Map<string, string> } {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));
  const shells = shellBatchIds(graph);
  const wrappers = new Map<string, string>();
  const ports = new Map<string, string>();
  for (const g of graph.groups) {
    if ((g.kind !== "input_wrapper" && g.kind !== "output_wrapper") || g.members.length === 0) continue;
    let parent = g.parent;
    while (parent && shells.has(parent)) parent = groupById.get(parent)?.parent ?? null;
    const owner = g.parent ? (parent ?? g.id) : g.id;
    wrappers.set(g.id, owner);
    for (const m of g.members) {
      if (nodeById.get(m)?.io != null) ports.set(m, owner);
    }
  }
  return { wrappers, ports };
}

/** A wrapper's IO members as row models, in member order. THE single copy:
 *  buildFlow's row areas (cards/regions) and the IoPanel's port entries both
 *  consume it, so canvas rows and panel entries can never disagree.
 *
 *  `dataType` is the authored `type:` when declared, else — outputs only —
 *  derived FAIL-CLOSED from the port's single producer edge via producedTypeOf
 *  (a multi-edge `source:` is an interpolation, not one field; unknown stays
 *  null, NEVER a filler like "any" — user-caught 2026-06-11). */
export function wrapperPorts(graph: RFGraph, wrapper: RFGroup): Port[] {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const derivedType = (port: RFNode): string | null => {
    if (port.kind !== "output") return null;
    const producers = graph.edges.filter((e) => e.kind === "data_flow" && e.target === port.id);
    if (producers.length !== 1) return null;
    const producer = nodeById.get(producers[0]!.source);
    return producedTypeOf(producer, producers[0]!.output_field, producers[0]!.output_path, graph.kind_output_types?.[producer?.kind ?? ""]);
  };
  return wrapper.members
    .map((memberId) => nodeById.get(memberId))
    .filter((m): m is RFNode => m != null && m.io != null)
    .map((m) => ({
      id: m.id,
      name: m.ref.node_id,
      dataType: m.io!.data_type ?? derivedType(m),
      required: m.io!.required,
      defaultValue: m.io!.default ?? null,
      description: m.purpose || null,
      receives: graph.edges.some((e) => e.kind === "data_flow" && e.target === m.id),
      feeds: graph.edges.some((e) => e.kind === "data_flow" && e.source === m.id),
    }));
}

// One TOP-LEVEL workflow input, as the run form's model (Task 175). Derived from
// the `kind==="input"` nodes the contract ships — exactly the inputs the CLI takes
// as `name=value` args, so the form is faithful to a hand-typed run.
export type InputField = {
  // The bare input name (`ref.node_id`) — the `name` in the `name=value` token.
  name: string;
  dataType: string | null;
  // Absent `required:` ⇒ true (the ir_schema default every runtime reader applies).
  required: boolean;
  // The authored `default:` value verbatim; null when absent.
  defaultValue: unknown;
  description: string | null;
  // Sensitive-NAMED (is_sensitive_parameter): rendered with a "from settings/env"
  // hint and left blank by default — the spawned run re-resolves it by name.
  sensitive: boolean;
};

/** The TOP-LEVEL workflow's inputs as form fields, in contract order. Reads the
 *  `kind==="input"` body nodes directly (NOT wrapperPorts, which maps `io` to a
 *  `Port` that DROPS `sensitive`) — `sensitive` is read straight off the raw `io`,
 *  the single source of truth the renderer attaches it to (input nodes only).
 *
 *  Sub-workflow input nodes (non-empty `ancestor_path`) are excluded: only the
 *  top-level inputs are the CLI's `name=value` args. */
export function inputFields(graph: RFGraph): InputField[] {
  return graph.nodes
    .filter((n) => n.kind === "input" && n.ref.ancestor_path.length === 0 && n.io != null)
    .map((n) => ({
      name: n.ref.node_id,
      dataType: n.io!.data_type,
      required: n.io!.required,
      defaultValue: n.io!.default ?? null,
      description: n.purpose || null,
      sensitive: n.io!.sensitive ?? false,
    }));
}

/** Decorator-shell batch groups — batch boxes that must NEVER render. The contract
 *  models "batched X" as batch-wrapping-X, but presentationally batch is a MODIFIER on
 *  the thing itself — the deck + ×N chip, not a box to travel through (user decision
 *  2026-06-10): a DYNAMIC batch group is always a shell (its one representative body
 *  is "the sub-workflow WITH batch" — the workflow group reparents past it), and a
 *  literal-batched LEAF's empty group is a shell too (leaf items are BatchSpec.items
 *  data — nothing to reveal). The EXCEPTION is a LITERAL batch whose items expanded
 *  into real item groups: those are actual copies to reveal, so the batch container
 *  renders and is the suppressed host's representative ("literal batches keep their
 *  container"). The discriminator is literal-vs-dynamic + expanded child groups, NOT
 *  memberlessness — a batch group never has direct node members (sub-workflow items
 *  live in child item groups), so the old `members.length === 0` rule swallowed
 *  literal sub-workflow batches and severed the host's spine (review-caught
 *  2026-06-11, CRITICAL). THE single copy of the rule — buildFlow, collapse.ts and
 *  viewParams.ts all consume it (three drifting copies is how the bug shipped). */
export function shellBatchIds(graph: RFGraph): ReadonlySet<string> {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const parentsOfGroups = new Set<string>();
  for (const g of graph.groups) {
    if (g.parent != null) parentsOfGroups.add(g.parent);
  }
  const shells = new Set<string>();
  for (const g of graph.groups) {
    if (g.kind !== "batch" || g.members.length > 0) continue;
    const batch = g.host ? nodeById.get(g.host)?.batch : null;
    // A literal batch WITH expanded item groups is a real box, never a shell.
    if (batch != null && !batch.dynamic && parentsOfGroups.has(g.id)) continue;
    shells.add(g.id);
  }
  return shells;
}
