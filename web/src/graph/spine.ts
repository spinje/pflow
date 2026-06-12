// Post-LAYOUT spine alignment (positions in, positions out; pure — unit-tested,
// no DOM). Called at the end of layoutGraph, BEFORE the portSides edge passes
// (rails are computed from the final boxes).
//
// THE BUG THIS FIXES (user-caught 2026-06-11, the "staircase"): expanded group
// REGIONS carry no ELK port (a port on a compound node crashes elkjs under
// INCLUDE_CHILDREN — see layout.ts), so ELK anchors their trunk edges at the box
// CENTER while the rendered handles sit on the icon line (TD: ICON_COL_X from the
// left edge; LR: ICON_ROW_Y from the top). Every wide region therefore knocks the
// following chain sideways by ~half its width, and the error compounds down a
// sequential chain — a deep workflow renders as a staircase wandering across the
// canvas. Ported cards (leaves / io cards / collapsed groups) never drift; only
// the port-less members do.
//
// THE RULE: a pure sequential chain follows its HEAD. For each maximal chain of
// pure spine links (one spine out-edge at the source, one spine in-edge at the
// target, same scope), every member's control ANCHOR (icon line; an end dot's
// center) aligns to the head's — the head keeps ELK's position (it encodes the
// global constraints: entry placement, fork ordering), downstream drift is the
// bug. Forks and merges break chains by construction (degree counting), so fork
// fan-outs keep their 2D spread; error edges count toward NEITHER side — an
// error handler hanging off a node must not break the trunk through it.
//
// A member whose shift would land it within SPINE_CLEARANCE of a same-scope
// sibling is SKIPPED (honest jog beats overlap) — ELK's collision guarantees
// only hold for the positions it chose.

import type { Direction, FlowEdge, FlowNode } from "./flow";
import { ICON_COL_X, ICON_ROW_Y } from "./metrics";

/** Minimum box gap a shifted member must keep from every same-scope sibling. */
export const SPINE_CLEARANCE = 24;

// Kinds that FORM a chain link vs kinds that COUNT toward a node's control
// degree (>1 on either side of a node = fork/merge = chain boundary there).
// Loop arcs (self-loops) and data_flow never participate.
const LINK_KINDS: ReadonlySet<string> = new Set(["sequential", "end"]);
const DEGREE_KINDS: ReadonlySet<string> = new Set(["sequential", "branch", "end"]);

type Box = { left: number; top: number; right: number; bottom: number };

/** Align each pure sequential chain's control anchors to its head's. Returns a
 *  new array; unmoved nodes keep object identity. Positions are parent-relative
 *  (React Flow's convention) — chain links require same-scope endpoints, so all
 *  arithmetic stays in one parent's coordinate space and a shifted region moves
 *  its subtree implicitly. */
export function alignSpine(nodes: FlowNode[], edges: FlowEdge[], direction: Direction): FlowNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Control degrees over unique (source, target) pairs — two contract edges that
  // re-anchored onto the same rendered pair are one visual connection, not a fork.
  const outDeg = new Map<string, number>();
  const inDeg = new Map<string, number>();
  const links: Array<{ source: string; target: string }> = [];
  {
    const degreeSeen = new Set<string>();
    const linkSeen = new Set<string>();
    for (const e of edges) {
      const kind = e.data?.kind;
      if (!kind || e.source === e.target) continue;
      const pair = `${e.source}\u0000${e.target}`;
      if (DEGREE_KINDS.has(kind) && !degreeSeen.has(pair)) {
        degreeSeen.add(pair);
        outDeg.set(e.source, (outDeg.get(e.source) ?? 0) + 1);
        inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
      }
      if (!LINK_KINDS.has(kind) || linkSeen.has(pair)) continue;
      const s = byId.get(e.source);
      const t = byId.get(e.target);
      if (!s || !t || (s.parentId ?? null) !== (t.parentId ?? null)) continue;
      linkSeen.add(pair);
      links.push({ source: e.source, target: e.target });
    }
  }

  // Pure links → at most one successor/predecessor per node: chains are paths.
  const next = new Map<string, string>();
  const prev = new Map<string, string>();
  for (const l of links) {
    if (outDeg.get(l.source) === 1 && inDeg.get(l.target) === 1) {
      next.set(l.source, l.target);
      prev.set(l.target, l.source);
    }
  }
  if (next.size === 0) return nodes;

  const chains: string[][] = [];
  const visited = new Set<string>();
  const walk = (head: string): void => {
    const chain: string[] = [];
    for (let id: string | undefined = head; id !== undefined && !visited.has(id); id = next.get(id)) {
      visited.add(id);
      chain.push(id);
    }
    if (chain.length >= 2) chains.push(chain);
  };
  // Heads first (stable node order keeps the pass deterministic) …
  for (const node of nodes) {
    if (next.has(node.id) && !prev.has(node.id)) walk(node.id);
  }
  // … then any leftover pure CYCLE (a root cycle of sequential links has no
  // head); the walk's visited guard terminates it, an arbitrary-but-stable
  // member anchors it.
  for (const node of nodes) {
    if (next.has(node.id) && !visited.has(node.id)) walk(node.id);
  }

  // The control anchor inside a node's own box: every card anatomy (leaf, io
  // card, collapsed group card AND expanded region) renders its trunk handles on
  // the icon line; the end dot's handle is side-centered (EndNode).
  const anchorOffset = (n: FlowNode): number => {
    if (n.type === "end") return (direction === "TD" ? (n.width ?? 0) : (n.height ?? 0)) / 2;
    return direction === "TD" ? ICON_COL_X : ICON_ROW_Y;
  };
  const mainOf = (n: FlowNode): number => (direction === "TD" ? n.position.x : n.position.y);

  // Mutable sibling boxes (parent-relative) for the clearance guard — updated as
  // shifts land so later members (and later chains) see earlier moves.
  const box = new Map<string, Box>();
  const siblings = new Map<string | null, string[]>();
  for (const n of nodes) {
    box.set(n.id, {
      left: n.position.x,
      top: n.position.y,
      right: n.position.x + (n.width ?? 0),
      bottom: n.position.y + (n.height ?? 0),
    });
    const scope = n.parentId ?? null;
    (siblings.get(scope) ?? siblings.set(scope, []).get(scope)!).push(n.id);
  }

  const moved = new Map<string, number>();
  for (const chain of chains) {
    const head = byId.get(chain[0]!)!; // chains have ≥2 members by construction
    const target = mainOf(head) + anchorOffset(head);
    const scopeSiblings = siblings.get(head.parentId ?? null) ?? [];
    for (const id of chain.slice(1)) {
      const n = byId.get(id)!;
      const delta = target - (mainOf(n) + anchorOffset(n));
      if (Math.abs(delta) < 0.5) continue;
      const b = box.get(id)!;
      const nb: Box =
        direction === "TD"
          ? { left: b.left + delta, right: b.right + delta, top: b.top, bottom: b.bottom }
          : { left: b.left, right: b.right, top: b.top + delta, bottom: b.bottom + delta };
      const collides = scopeSiblings.some((sid) => {
        if (sid === id) return false;
        const sb = box.get(sid)!;
        return (
          nb.left < sb.right + SPINE_CLEARANCE &&
          sb.left < nb.right + SPINE_CLEARANCE &&
          nb.top < sb.bottom + SPINE_CLEARANCE &&
          sb.top < nb.bottom + SPINE_CLEARANCE
        );
      });
      if (collides) continue;
      box.set(id, nb);
      moved.set(id, delta);
    }
  }
  if (moved.size === 0) return nodes;

  return nodes.map((n) => {
    const delta = moved.get(n.id);
    if (delta === undefined) return n;
    return {
      ...n,
      position:
        direction === "TD"
          ? { x: n.position.x + delta, y: n.position.y }
          : { x: n.position.x, y: n.position.y + delta },
    };
  });
}
