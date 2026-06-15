// Focus+context: the restyle pass (applyFocus — dim/reveal, NO re-layout) and
// the beautiful-mode expansion policy (expandTargets — which cards render their
// advanced body for a given focus). Build and focus are separate passes by
// design: buildFlow produces the structure ELK lays out; this module decorates
// the laid-out snapshot. The ONE crossover is expandTargets' output feeding
// BuildOptions.expanded (expansion changes node sizes, so it re-runs the build).

import { ioOwners } from "./io";
import type { FlowEdge, FlowNode } from "./flow";
import type { RFGraph } from "../types";

// The shared empty expansion set — expandTargets deliberately returns this ONE
// module-level constant for every no-expansion result: the hook's build memo
// keys on the set's IDENTITY, and a fresh empty Set per click would re-run
// build + ELK. Nothing else may mint empty sets for the no-expansion case.
export const NO_EXPANSION: ReadonlySet<string> = new Set();

/** The hover marks for a ROW: every edge landing on it PLUS each edge's far-end
 *  node (edge ids light their line, node ids ring their box — one set, disjoint
 *  id namespaces). Reads the FLOW edges, not the contract: a flow edge's handles
 *  ARE its resolved row landing — re-anchoring, dict-key walks, owner resolution
 *  and dedupe already applied — so this can never disagree with what's drawn.
 *  A self-edge's far end is skipped (ringing the hovered node says nothing),
 *  but its line still lights. */
export function rowTouches(edges: readonly FlowEdge[], nodeId: string, handles: readonly string[]): ReadonlySet<string> {
  const out = new Set<string>();
  for (const e of edges) {
    if (e.source === nodeId && e.sourceHandle != null && handles.includes(e.sourceHandle)) {
      out.add(e.id);
      if (e.target !== nodeId) out.add(e.target);
    } else if (e.target === nodeId && e.targetHandle != null && handles.includes(e.targetHandle)) {
      out.add(e.id);
      if (e.source !== nodeId) out.add(e.source);
    }
  }
  return out;
}

// The expansion set for a focus in beautiful mode: the focused leaf plus every leaf
// on the other end of one of its DATA-FLOW lines. Those cards render their advanced
// body so the revealed lines land on actual rows (source's output row → target's
// param row) instead of carrying a floating "stdout → data" label. Control-flow
// neighbors stay compact — their connection already reads fine at node level.
//
// IO ports are ROWS on an OWNER node (the root IO card — reusing its wrapper's
// group id — or the enclosing workflow group), so an IO endpoint contributes its
// OWNER to the set: the owner renders its rows and the revealed line lands on the
// exact row. `focus` may be a leaf id, an individual IO port id, or an IO card /
// wrapper id (→ all member ports).
//
// `pinned` is the OPEN PANEL's subject (user decision 2026-06-12): its card keeps
// its body rendered regardless of where focus goes. Chip navigation moves focus to
// the chip's target while the panel stays — without the pin the panel's subject
// contracts mid-read whenever it isn't an endpoint of the new focus's scan
// (host-level edges — e.g. a batch sub-workflow's `${x.results}` — never surface
// in a container focus's port-level scan). Self only: the pin does NOT pull in
// the subject's data neighborhood; focus owns that.
export function expandTargets(graph: RFGraph, focus: string | null, pinned: string | null = null): ReadonlySet<string> {
  if (!focus && !pinned) return NO_EXPANSION;
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  // IO port id -> the node carrying its row (ioOwners — the same rule buildFlow
  // resolves edge handles with, so expansion and row emission can't disagree).
  const io = ioOwners(graph);
  const ioOwner = io.ports;
  let focusWrapper: { members: string[] } | null = null;
  for (const g of graph.groups) {
    if ((g.kind === "input_wrapper" || g.kind === "output_wrapper") && g.id === focus) focusWrapper = g;
  }
  // Only a leaf card can expand to its advanced body; a group host has no card and
  // an end sink has no body. An IO port expands its OWNER instead.
  const expandable = (id: string): boolean => {
    const n = nodeById.get(id);
    return n != null && n.io === null && !n.is_group_host && n.kind !== "end";
  };
  const out = new Set<string>();
  const add = (id: string): void => {
    if (expandable(id)) out.add(id);
    else {
      const owner = ioOwner.get(id);
      if (owner) out.add(owner);
    }
  };
  // The pin first — every arm below (including the early returns) keeps it.
  // A pinned leaf/port resolves like any endpoint; a pinned CONTAINER or root
  // IO card adds the card itself (its io rows render — it was selected, so its
  // panel is open). A pinned edge id resolves to nothing (the matching focus
  // arm below already expands its endpoints).
  if (pinned != null) {
    if (expandable(pinned)) out.add(pinned);
    else {
      const owner = ioOwner.get(pinned);
      if (owner != null) out.add(owner);
      else if (graph.groups.some((g) => g.id === pinned)) out.add(io.wrappers.get(pinned) ?? pinned);
    }
  }
  // Empty results return the shared constant — the hook's build memo keys on
  // the set's identity, and a fresh empty Set per click would re-run the build.
  const settled = (): ReadonlySet<string> => (out.size > 0 ? out : NO_EXPANSION);
  if (!focus) return settled();
  // Selecting a DATA EDGE (edge-click) expands exactly its two endpoints (owner-
  // aware), so the selected line lands row-to-row. The endpoints go straight into
  // the OUTPUT set — never into `foci`, or the data-flow scan below would expand
  // both endpoints' entire data neighborhoods. A control-edge focus expands
  // nothing (node-level endpoints already read fine at the trunk).
  const focusEdge = graph.edges.find((e) => e.id === focus);
  if (focusEdge) {
    if (focusEdge.kind !== "data_flow") return settled();
    add(focusEdge.source);
    add(focusEdge.target);
    return settled();
  }
  // Selecting a CONTAINER (workflow/batch group) expands "just its inputs and
  // outputs" (user-decided 2026-06-10): the focus acts as ALL of its IO ports —
  // each port's owner IS the group, so the card/region renders its IO rows, and
  // every binding's far end expands too. Without this, a selected card's 13
  // bindings re-anchor node-level, DEDUPE into one line, and the surviving label
  // single-names the first port — actively misleading.
  if (!focusWrapper) {
    const container = graph.groups.find((g) => g.id === focus && (g.kind === "workflow" || g.kind === "batch"));
    if (container) {
      const ports = graph.groups
        .filter((w) => (w.kind === "input_wrapper" || w.kind === "output_wrapper") && w.parent === container.id)
        .flatMap((w) => w.members);
      if (ports.length > 0) focusWrapper = { members: ports };
    }
  }
  const foci = new Set<string>(focusWrapper ? focusWrapper.members : [focus]);
  for (const id of foci) add(id);
  for (const e of graph.edges) {
    if (e.kind !== "data_flow") continue;
    if (!foci.has(e.source) && !foci.has(e.target)) continue;
    add(e.source);
    add(e.target);
  }
  return settled();
}

const DIMMED_EDGE_CLASS = "edge-dimmed";

// The z-index applyFocus writes onto a SELECTED edge so it paints above the cards
// it crosses (React Flow otherwise renders all edges behind nodes — the tunneling
// problem edge selection exists to solve). Exported for tests/components.
export const SELECTED_EDGE_Z = 1000;

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
// `focus` is a contract id — a node id, a root IO card's id, an individual IO
// port's id (a row), OR a flow EDGE's id (edge-click selection). An edge is
// incident if its flow endpoints OR its original endpoints (`data.from`/`to`)
// touch the focus, so a single port reveals just its own lines even though its
// edges re-anchor onto the shared owner node. For an EDGE focus the clicked
// CONNECTION is the subject: only that edge lights (selected + elevated), its two
// endpoint nodes stay full-strength, and everything else — including the
// endpoints' OTHER edges — dims.
export function applyFocus(
  nodes: FlowNode[],
  edges: FlowEdge[],
  focus: string | null,
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  // Selecting an EDGE: deliberately NOT the unit machinery below — seeding the
  // unit with the endpoints would light their entire neighborhoods, when the
  // subject is one connection.
  const focusedEdge = focus != null ? (edges.find((e) => e.id === focus) ?? null) : null;
  // Selecting a CONTAINER (focus = a group node's id) selects the whole UNIT:
  // the group, ALL its descendants, and every edge touching any of them —
  // internal wiring and external bindings light up, everything else dims
  // (design D, 2026-06-10: the card/region body SELECTS; the corner button
  // toggles). For a leaf/port focus the unit is just the focus id, which
  // preserves the original single-id incidence exactly.
  const unit = new Set<string>();
  if (focus && !focusedEdge) {
    unit.add(focus);
    if (nodes.some((n) => n.id === focus && n.type === "group")) {
      const childrenByParent = new Map<string, string[]>();
      for (const n of nodes) {
        if (!n.parentId) continue;
        const siblings = childrenByParent.get(n.parentId) ?? [];
        siblings.push(n.id);
        childrenByParent.set(n.parentId, siblings);
      }
      const queue = [focus];
      while (queue.length > 0) {
        for (const child of childrenByParent.get(queue.pop()!) ?? []) {
          unit.add(child);
          queue.push(child);
        }
      }
    }
  }
  const touches = (e: FlowEdge): boolean =>
    unit.has(e.source) || unit.has(e.target) || (e.data != null && (unit.has(e.data.from) || unit.has(e.data.to)));
  // Incidence: for an edge focus, exactly the focused edge; otherwise any edge
  // touching the unit.
  const incidentTo = (e: FlowEdge): boolean => (focusedEdge ? e.id === focus : touches(e));
  const connected = new Set<string>(unit);
  if (focusedEdge) {
    // The lit nodes are the selected edge's endpoints — both the rendered anchors
    // and the original contract endpoints (a re-anchored line lights the visible
    // ancestor it lands on).
    connected.add(focusedEdge.source);
    connected.add(focusedEdge.target);
    if (focusedEdge.data) {
      connected.add(focusedEdge.data.from);
      connected.add(focusedEdge.data.to);
    }
  } else if (focus) {
    for (const e of edges) {
      if (touches(e)) {
        connected.add(e.source);
        connected.add(e.target);
      }
    }
  }
  // Clicking a branch TARGET reveals the condition gating it ("why was I
  // reached?") — just its own, not the fork's siblings. WHERE it reveals is
  // direction-split, matching where conditions live: LR → on the SOURCE leaf's
  // BranchPorts row (revealBySource → LeafData.revealedConditions; an edge pill
  // at the target entry overlapped the clicked card); TD, or an LR branch whose
  // flow source has no rows (re-anchored onto a group) → the edge pill
  // (EdgeData.conditionRevealed below).
  const leafById = new Map(nodes.filter((n) => n.type === "node").map((n) => [n.id, n]));
  const isLR = [...leafById.values()].some((n) => n.type === "node" && n.data.direction === "LR");
  const revealBySource = new Map<string, Record<string, string>>();
  const rowReveals = (e: FlowEdge): boolean =>
    isLR && e.data?.outcome != null && e.source === e.data.from && leafById.has(e.source);
  if (focus) {
    for (const e of edges) {
      // Outcome edges: branches, plus a decision's END edge (its "end" outcome —
      // clicking the end dot answers "why did flow stop here?"). Selecting the
      // branch EDGE itself also reveals its condition here (the selected edge
      // suppresses its own floating pill — elevation would strike through it —
      // so the source's row is the condition's visible home; TD stays panel-only).
      if ((e.data?.kind !== "branch" && e.data?.kind !== "end") || e.data.condition == null) continue;
      if (e.target !== focus && e.data.to !== focus && e.id !== focus) continue;
      if (!rowReveals(e)) continue;
      const conds = revealBySource.get(e.source) ?? {};
      conds[e.data.outcome!] = e.data.condition;
      revealBySource.set(e.source, conds);
    }
  }
  const outNodes = nodes.map((n) => {
    const focused = focus != null && n.id === focus;
    // Expanded groups never dim (the region must stay readable around its lit
    // children) — but a COLLAPSED group is a card in the flow and dims like a leaf.
    const dimmed = focus != null && (n.type !== "group" || n.data.collapsed) && !connected.has(n.id);
    // IO rows live on IO cards and group nodes — highlight the focused row when an
    // individual port is the focus.
    if (n.type === "io" || n.type === "group") {
      const ports = n.type === "io" ? n.data.ports : [...n.data.inputs, ...n.data.outputs];
      const focusedPortId = focus != null && ports.some((p) => p.id === focus) ? focus : null;
      if (n.data.focused === focused && n.data.dimmed === dimmed && n.data.focusedPortId === focusedPortId) {
        return n;
      }
      return { ...n, data: { ...n.data, focused, dimmed, focusedPortId } } as FlowNode;
    }
    const revealedConditions = n.type === "node" ? revealBySource.get(n.id) : undefined;
    if (n.data.focused === focused && n.data.dimmed === dimmed && (n.type !== "node" || n.data.revealedConditions === revealedConditions)) {
      return n;
    }
    return { ...n, data: { ...n.data, focused, dimmed, ...(n.type === "node" ? { revealedConditions } : {}) } } as FlowNode;
  });
  const outEdges = edges.map((e) => {
    const incident = focus != null && incidentTo(e);
    const selected = focusedEdge != null && e.id === focus ? true : undefined;
    // A default-hidden edge (beautiful mode's data-flow lines) is revealed when it
    // touches the focus — "show me this node's / port's data wiring." Edges hidden
    // by the build stay hidden otherwise; control edges are never default-hidden.
    // Read the build-time fact from data, NOT the mutable `hidden` flag this pass
    // writes — so re-processing decorated output can't misread a revealed edge.
    const defaultHidden = e.data?.defaultHidden === true;
    const hidden = defaultHidden && !incident;
    const base = stripDim(e.className);
    const dim = focus != null && !incident;
    const className = dim ? `${base} ${DIMMED_EDGE_CLASS}`.trim() : base;
    // EdgeLabelRenderer pills live OUTSIDE .react-flow__edge, so the CSS dim can't
    // reach them — carry the dim as data for the components' label divs.
    const dimmed = dim ? true : undefined;
    // The selected edge paints above the cards it crosses. applyFocus OWNS this
    // channel (the build never sets edge zIndex — a loop edge deliberately must
    // not): falling back to e.zIndex would pin a stale elevation when this pass
    // re-processes its own decorated output (caught by test).
    const zIndex = selected ? SELECTED_EDGE_Z : undefined;
    // Which END of an incident data line the focus sits on — DataEdge renders the
    // line solid at the clicked node and fading a hint toward the far end, so the
    // revealed wiring visibly BELONGS to the focus (user-chosen treatment). A
    // SELECTED edge clears it explicitly: both ends draw solid (without this the
    // ternary would silently default the focused edge to "target" and fade one end).
    const focusEnd =
      incident && !selected && e.data?.kind === "data_flow"
        ? e.source === focus || e.data.from === focus
          ? ("source" as const)
          : ("target" as const)
        : undefined;
    // The edge-pill arm of the target-click reveal (see revealBySource above for
    // the LR row arm). The pill is otherwise governed by conditionShown.
    const conditionRevealed =
      focus != null &&
      (e.data?.kind === "branch" || e.data?.kind === "end") &&
      e.data.condition != null &&
      (e.target === focus || e.data.to === focus) &&
      !rowReveals(e)
        ? true
        : undefined;
    if (
      className === e.className &&
      hidden === (e.hidden ?? false) &&
      focusEnd === e.data?.focusEnd &&
      conditionRevealed === e.data?.conditionRevealed &&
      selected === e.data?.selected &&
      dimmed === e.data?.dimmed &&
      zIndex === e.zIndex
    ) {
      return e;
    }
    return {
      ...e,
      className,
      hidden,
      zIndex,
      ...(e.data ? { data: { ...e.data, focusEnd, conditionRevealed, selected, dimmed } } : {}),
    };
  });
  return { nodes: outNodes, edges: outEdges };
}
