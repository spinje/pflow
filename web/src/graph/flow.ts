// The RFGraph -> React Flow transform. Pure and unit-tested: given the contract
// payload and the current view state, produce React Flow nodes + edges (positions
// are filled afterwards by ELK in layout.ts).
//
// This is where the load-bearing contract rules live (each traces to a Task-168
// review item — see src/pflow/ui/CLAUDE.md):
//   - is_group_host nodes are SUPPRESSED as leaves; their group box stands in,
//     and a host is NOT 1:1 with a group (H8).
//   - every edge is ADDITIVE: an endpoint hidden by collapse or host-suppression
//     re-anchors to a visible ancestor (group / batch host), never dropped (H6/W1).
//   - data-flow lines land on the exact param row when input_name matches a param,
//     else degrade to a node-level connection (input_name=None is common — H6).

import type { Edge, Node } from "@xyflow/react";

import { branchHandle, LOOP_ROW, NODE_IN, NODE_OUT, outputHandle, paramHandle, portHandle, portTargetHandle } from "./handles";
import { METRICS } from "./metrics";
import { IO_COLOR, kindColor, nodeColor } from "../utils/format";
import type { EdgeKind, LoopSpec, RFEdge, RFGraph, RFGroup, RFNode } from "../types";

export type Density = "detailed" | "compact";
export type Direction = "LR" | "TD";

// What the structural build (and therefore ELK layout) depends on. Focus itself is
// NOT here (applyFocus is a cheap styling pass) — but `expanded` (derived FROM focus
// by expandTargets) is: expanding a card to its advanced body changes its size, so
// it must flow through build → ELK. In beautiful, clicking a node therefore DOES
// re-layout (decided 2026-06-09: a card growing along the TD flow axis collides with
// the node below it otherwise); the hook keeps the clicked node visually anchored.
export interface BuildOptions {
  density: Density;
  direction: Direction;
  collapsed: ReadonlySet<string>;
  // Leaf nodes that render their advanced body while the global density stays
  // beautiful (the focused node + its data-flow endpoints). Ignored in advanced.
  // Also carries IO-row OWNERS (a root IO card's wrapper id / a workflow group's
  // id) whose rows should render — expandTargets emits them.
  expanded?: ReadonlySet<string>;
  // The display name of the loaded workflow — the root IO cards' title line.
  workflowName?: string;
}

// `type` (not `interface`) so each satisfies React Flow's `data extends
// Record<string, unknown>` constraint via the implicit-index-signature rule.
export type LeafData = {
  node: RFNode;
  density: Density;
  direction: Direction;
  outputFields: string[];
  branchLabels: string[]; // decision fork outcomes — labeled handles on the border
  // Outcome label → the extracted condition selecting it ("if len(items) > 5").
  // In LR the BranchPorts ROW is the condition's home (mid-path pills clipped
  // under cards / floated on backward wraps — user-caught 2026-06-10); populated
  // only when the rows show it (advanced / focus-expanded), else {}. TD has no
  // rows — there the condition rides the edge (EdgeData.condition).
  branchConditions: Record<string, string>;
  // Whether the node has an incoming / outgoing CONTROL edge — drives the icon
  // connector stubs (a top stub only if something flows in, a bottom stub only if
  // something flows out). Computed in buildFlow from the control edges.
  hasIncoming: boolean;
  hasOutgoing: boolean;
  // Focus-expansion: render the advanced body while density stays beautiful. The
  // card keeps its TOP flare (the tile still abuts the top border) but drops the
  // BOTTOM one (the body grew below the tile, so a tile-anchored flare would float
  // mid-card away from the outgoing edge).
  expanded: boolean;
  dimmed: boolean;
  focused: boolean;
  // Transient, set by applyFocus (LR only): outcome → condition for a branch whose
  // TARGET is the focus — the reveal lands on THIS (source) node's BranchPorts row,
  // the condition's LR home (an edge pill at the target entry overlapped the
  // clicked card — user-caught 2026-06-10). Merged over branchConditions in
  // WorkflowNode; undefined when nothing is revealed.
  revealedConditions?: Record<string, string>;
};

// One IO row. `id` is the IO node's contract id — it doubles as the row's handle
// key and its focus target (click a row → focus that port). IO rows render ON the
// workflow's own node: the root IO card, a collapsed sub-workflow card, or an
// expanded region's sidebar/strip — never as a separate floating table.
export type Port = {
  id: string;
  name: string;
  dataType: string | null;
  required: boolean;
  // Outputs carry their authored description (the contract's `purpose`); inputs
  // have none. Surfaced as the row tooltip.
  description: string | null;
};

// A ROOT workflow's inputs (or outputs) as a standalone node card: tile + INPUTS/
// OUTPUTS category + the workflow's name, a count pill, and — when rows are visible
// (advanced / focus-expanded) — one row per port. Nested workflows put the same
// rows on their group node instead (GroupData.inputs/outputs); the root has no
// containing node, so it gets these two cards at the flow's start and end.
export type IOCardData = {
  kind: "input" | "output";
  ports: Port[];
  workflowName: string;
  density: Density;
  direction: Direction;
  rowsVisible: boolean; // advanced, or focus-expanded (the leaf showBody rule)
  focusedPortId: string | null; // the row to highlight when an individual port is focused
  // Control-edge incidence (the connector flares, same as LeafData): the cards join
  // the control SKELETON via the synthesized io-flow edges (Inputs → entry step,
  // terminal step → Outputs), so they behave like nodes — flares included. Filled
  // by the control-incidence post-pass over the FLOW edges.
  hasIncoming: boolean;
  hasOutgoing: boolean;
  dimmed: boolean;
  focused: boolean;
};

export type GroupData = {
  group: RFGroup;
  hostNode: RFNode | null;
  collapsed: boolean;
  showTitle: boolean;
  direction: Direction;
  // Control-edge incidence (drives the connector flares, same as LeafData): the
  // collapsed card draws top+bottom; the expanded region draws its TOP flare (the
  // trunk enters through the region's tile like any node's). Computed in a
  // post-pass over the FLOW edges (not the contract edges): a group is never a
  // contract endpoint — edges re-anchor onto it — and a purely-internal edge
  // (both ends inside) must not count.
  hasIncoming: boolean;
  hasOutgoing: boolean;
  // Recursive workflow-step count (the count pill) — NOT group.members.length,
  // which only sees direct children and counts IO ports/hosts.
  memberCount: number;
  // The workflow's declared IO, rendered as rows on this node (from the child
  // level's input_wrapper/output_wrapper groups, whose parent is this group).
  // Collapsed card: a two-column area under the header (inputs left, outputs
  // right BOTTOM-ANCHORED — the in→out diagonal). Expanded region: inputs
  // as the LEFT SIDEBAR (the body lays out beside it via ELK left padding),
  // outputs as the bottom-right strip.
  inputs: Port[];
  outputs: Port[];
  ioRowsVisible: boolean; // advanced, or focus-expanded (and there IS io to show)
  focusedPortId: string | null;
  dimmed: boolean;
  focused: boolean;
};

export type EndData = {
  node: RFNode;
  direction: Direction;
  dimmed: boolean;
  focused: boolean;
};

export type EdgeData = {
  kind: EdgeKind | "loop";
  shadowed: boolean;
  // Original contract endpoints (before re-anchoring) — lets focus match an edge to a
  // node OR an individual IO port (whose edges re-anchor onto a shared ports node).
  from: string;
  to: string;
  // Set ONCE by the build: "this edge renders hidden unless revealed by focus"
  // (beautiful mode's data-flow lines). applyFocus must read THIS, never the mutable
  // `hidden` flag it also writes — otherwise re-processing its own output would
  // misread a revealed edge as default-visible and pin it shown forever.
  defaultHidden: boolean;
  // Source/target node colors for the gradient control edge (sequential/branch).
  // Optional: data/error/end/loop edges don't read them.
  sourceColor?: string;
  targetColor?: string;
  // The data edge's LANE (assignEdgeLanes): distinct stub lengths + rail offsets
  // per parallel binding at a node. DataEdge reads it; absent elsewhere.
  lane?: number;
  // Post-layout rail hints: assignDataRails centers a data edge's middle segment
  // in the clear gap between the endpoint boxes (a wrap-around never hugs a node
  // border); assignBackRails routes a BACKWARD branch/error edge around both boxes
  // (LR below / TD left) so loop-backs don't knot at the source handle. Absent →
  // the component's midpoint fallback.
  railX?: number;
  railY?: number;
  // Set by applyFocus on incident data edges: which end the clicked node is on.
  // DataEdge draws the line solid at that end, fading a hint toward the other.
  focusEnd?: "source" | "target";
  // A branch edge's outcome label (edge.label), carried on data so applyFocus can
  // map a revealed condition back to its source's BranchPorts row
  // (LeafData.revealedConditions).
  outcome?: string;
  // The source condition selecting this outcome ("if len(items) > 5" / "else"),
  // from the contract (RFEdge.condition) — ALWAYS carried so focus can reveal it.
  // GradientEdge renders the pill when conditionShown OR conditionRevealed:
  //  - conditionShown: the build-time default — advanced always, beautiful while
  //    the condition node is focus-expanded (safe as build-time state because
  //    expansion re-runs the build). False for a labeled LR branch whose source
  //    renders rows — there the BranchPorts row is the condition's home
  //    (LeafData.branchConditions).
  //  - conditionRevealed: set by applyFocus when the branch's TARGET is the
  //    focus — clicking a target answers "why was I reached?". TD (and an LR
  //    branch whose flow source has no rows, i.e. re-anchored): the edge pill;
  //    a labeled LR branch from a leaf instead reveals on the source's row
  //    (LeafData.revealedConditions) — the pill overlapped the clicked card.
  condition?: string;
  conditionShown?: boolean;
  conditionRevealed?: boolean;
  loop?: LoopSpec; // present only on synthesized loop-back arcs
};

export type FlowNode =
  | Node<LeafData, "node">
  | Node<IOCardData, "io">
  | Node<GroupData, "group">
  | Node<EndData, "end">;
export type FlowEdge = Edge<EdgeData>;

// Size estimates feed ELK and are applied as the node's rendered box, so they
// must match what the components draw (the components fill width/height: 100%).
// Heights shared with CSS rules come from METRICS (single source — the stylesheet
// reads the same values as injected CSS vars); the widths/paddings below are
// TS-only (CSS doesn't pin them). Re-tune live against the real DOM if it drifts.
export const DETAILED_WIDTH = 320;
export const COMPACT_WIDTH = 230;
export const HEADER_HEIGHT = METRICS.nodeHeaderH; // tile + small padding (both densities)
export const ROW_HEIGHT = METRICS.rowH;
export const ROW_PADDING = 14;
export const END_SIZE = 46;
// The root IO card with rows visible (single column, slightly wider than compact
// so long port names breathe).
export const IO_CARD_WIDTH = 260;
// A collapsed group card showing its two-column IO area (inputs left, outputs right).
export const GROUP_IO_WIDTH = 380;
// The collapsed group renders as a leaf-anatomy CARD (GroupNode): compact height,
// slightly wider than a leaf so the count pill fits beside the titles.
export const COLLAPSED_GROUP_WIDTH = 260;
export const COLLAPSED_GROUP_HEIGHT = HEADER_HEIGHT;

/** Row count of a two-column IO area. Outputs are BOTTOM-ANCHORED, at least one
 *  row below the inputs' start — even at equal counts (user decision 2026-06-10):
 *  the top-left → bottom-right diagonal IS the information (in flows to out).
 *  GroupNode pushes the outputs column down by `ioRowsCount − nOut` rows — the
 *  original fixed one-row stagger whenever counts are balanced (nOut + 1 ≥ nIn),
 *  and the card's bottom-right corner when inputs dominate (a 13-in/3-out card
 *  left the outputs hugging the top). */
export function ioRowsCount(nIn: number, nOut: number): number {
  if (nIn > 0 && nOut > 0) return Math.max(nIn, nOut + 1);
  return Math.max(nIn, nOut);
}

/** Height of the IO row area on a collapsed group card (0 when nothing to show). */
export function ioAreaHeight(nIn: number, nOut: number): number {
  const rows = ioRowsCount(nIn, nOut);
  return rows === 0 ? 0 : METRICS.ioLabelH + rows * ROW_HEIGHT + ROW_PADDING;
}

function leafSize(
  node: RFNode,
  density: Density,
  direction: Direction,
  outputFields: string[],
  branchLabels: string[],
  expanded: boolean,
): { width: number; height: number } {
  // Fork rows show only in LR (the n8n-style labeled border handles). In TD the forks
  // fan from the icon column and their labels ride the edges, so no rows are drawn.
  const branchRows = direction === "LR" ? branchLabels.length : 0;
  // A focus-expanded card renders the full advanced body, so it takes the advanced box.
  const showsBody = density === "detailed" || expanded;
  const width = showsBody ? DETAILED_WIDTH : COMPACT_WIDTH;
  // The 56px icon tile is taller than even a 2-line description, so it dominates the
  // header height — keep it a fixed HEADER_HEIGHT. That also keeps the tile vertically
  // CENTERED (equal inset top/bottom), which the connector stubs depend on.
  if (!showsBody) {
    return { width, height: HEADER_HEIGHT + branchRows * ROW_HEIGHT };
  }
  // The ↻ loop-rule rows a looped leaf renders in its body (WorkflowNode): the
  // condition row (the U's landing) + a cap row when one is set.
  const loopRows = node.loop ? (node.loop.cap != null ? 2 : 1) : 0;
  const rows = node.params.length + outputFields.length + branchRows + loopRows;
  return { width, height: HEADER_HEIGHT + rows * ROW_HEIGHT + ROW_PADDING };
}

// Control-flow edge kinds — these connect at a node's NODE_IN/NODE_OUT (the trunk),
// so they drive the icon connector stubs. data_flow lands on param rows; loop is a
// self-arc — neither implies a trunk in/out. Exported for layout.ts (straightness
// priorities + error-branch ordering work on control edges only).
export const CONTROL_KINDS: ReadonlySet<EdgeKind> = new Set<EdgeKind>(["sequential", "branch", "error", "end"]);

const NO_EXPANSION: ReadonlySet<string> = new Set();
const NO_CONDITIONS: Record<string, string> = {};

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
export function expandTargets(graph: RFGraph, focus: string | null): ReadonlySet<string> {
  if (!focus) return NO_EXPANSION;
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const ioOwner = new Map<string, string>(); // IO port id -> the node carrying its row
  let focusWrapper: { members: string[] } | null = null;
  for (const g of graph.groups) {
    if (g.kind !== "input_wrapper" && g.kind !== "output_wrapper") continue;
    if (g.id === focus) focusWrapper = g;
    const owner = g.parent ?? g.id;
    for (const m of g.members) ioOwner.set(m, owner);
  }
  const foci = new Set<string>(focusWrapper ? focusWrapper.members : [focus]);
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
  for (const id of foci) add(id);
  for (const e of graph.edges) {
    if (e.kind !== "data_flow") continue;
    if (!foci.has(e.source) && !foci.has(e.target)) continue;
    add(e.source);
    add(e.target);
  }
  return out;
}

export function buildFlow(graph: RFGraph, view: BuildOptions): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));
  const expandedSet = view.expanded ?? NO_EXPANSION;

  // A batch group with NO direct members is a decorator SHELL (the contract models
  // "batched X" as batch-wrapping-X): empty for a batched leaf, or holding only the
  // workflow group of a batched sub-workflow. Presentationally, batch is a MODIFIER
  // on the thing itself — the deck + ×N badge — not a box to travel through (user
  // decision 2026-06-10): shells are never rendered, their child reparents past
  // them, and a suppressed host's representative skips them (a batched sub-workflow
  // IS a sub-workflow WITH batch). Literal batches (real item-copy members) keep
  // their container — there are actual items to reveal.
  const shellBatch = new Set(
    graph.groups.filter((g) => g.kind === "batch" && g.members.length === 0).map((g) => g.id),
  );
  const effectiveParent = (parent: string | null): string | null => {
    while (parent && shellBatch.has(parent)) parent = groupById.get(parent)?.parent ?? null;
    return parent;
  };

  // CONTRACT-level control incidence. Render-time incidence (the connector flares)
  // comes from a post-pass over the FLOW edges — these sets exist to find the root
  // ENTRY steps (no incoming control edge) for the synthesized io-flow skeleton.
  const incomingControl = new Set<string>();
  const outgoingControl = new Set<string>();
  for (const e of graph.edges) {
    if (!CONTROL_KINDS.has(e.kind)) continue;
    incomingControl.add(e.target);
    outgoingControl.add(e.source);
  }

  // Workflow STEPS inside each container, recursively — what a user would call
  // "what's in this box" (the count pill). group.members only lists DIRECT children,
  // which undercounts nested structure and counts IO ports/hosts a reader wouldn't.
  const stepCountByGroup = new Map<string, number>();
  for (const n of graph.nodes) {
    if (n.io !== null || n.kind === "end" || n.is_group_host) continue;
    let g: string | null = n.parent;
    while (g) {
      stepCountByGroup.set(g, (stepCountByGroup.get(g) ?? 0) + 1);
      g = groupById.get(g)?.parent ?? null;
    }
  }

  // A host node may back several groups (a dynamic-batch-of-subworkflow hosts
  // both a batch and a workflow group — H8). Edges into the suppressed host land
  // on the OUTERMOST of them; the rest nest inside. Shell batch groups are not
  // rendered, so they can't be anyone's representative.
  const groupsByHost = new Map<string, RFGroup[]>();
  for (const g of graph.groups) {
    if (g.host && !shellBatch.has(g.id)) {
      const list = groupsByHost.get(g.host) ?? [];
      list.push(g);
      groupsByHost.set(g.host, list);
    }
  }
  const primaryGroupForHost = new Map<string, string>();
  for (const [host, groups] of groupsByHost) {
    const outerCandidates = groups.filter((g) => {
      if (!g.parent) return true;
      return groupById.get(g.parent)?.host !== host;
    });
    const pool = outerCandidates.length > 0 ? outerCandidates : groups;
    const outer = pool.reduce((a, b) => (b.nesting_depth < a.nesting_depth ? b : a));
    primaryGroupForHost.set(host, outer.id);
  }

  // Output fields a node exposes as right-side ports: the distinct output_field
  // of its outgoing data-flow edges. Computed from the raw edges (only used when
  // an edge keeps its real source — re-anchored edges fall back to node-level).
  const outputFieldsByNode = new Map<string, Set<string>>();
  // Branch outcomes a decision node forks on — one labeled source handle per
  // outcome, in declared order (deduped). Drives the n8n-Switch-style border ports.
  const branchLabelsByNode = new Map<string, string[]>();
  // Outcome label → extracted condition, per decision node (LeafData.branchConditions).
  const branchConditionsByNode = new Map<string, Record<string, string>>();
  for (const e of graph.edges) {
    if (e.kind === "data_flow" && e.output_field) {
      const set = outputFieldsByNode.get(e.source) ?? new Set<string>();
      set.add(e.output_field);
      outputFieldsByNode.set(e.source, set);
    }
    if (e.kind === "branch" && e.label) {
      const labels = branchLabelsByNode.get(e.source) ?? [];
      if (!labels.includes(e.label)) labels.push(e.label);
      branchLabelsByNode.set(e.source, labels);
      if (e.condition) {
        const conds = branchConditionsByNode.get(e.source) ?? {};
        conds[e.label] = e.condition;
        branchConditionsByNode.set(e.source, conds);
      }
    }
  }

  // A workflow's IO ports render as ROWS on an OWNER node, never as a separate
  // table: a NESTED workflow's wrapper puts its rows on the workflow GROUP node
  // (wrapper.parent — collapsed card columns / expanded region sidebar+strip); a
  // ROOT wrapper becomes a standalone IO CARD reusing the wrapper's group id (no
  // node uses a g* id, so no collision — and focus/deep-link ids stay stable).
  // The IO member nodes are NOT emitted; each maps to (its owner, its row handle).
  const ioWrappers = graph.groups.filter(
    (g) => (g.kind === "input_wrapper" || g.kind === "output_wrapper") && g.members.length > 0,
  );
  const wrapperOwner = (wrapper: RFGroup): string =>
    wrapper.parent ? (effectiveParent(wrapper.parent) ?? wrapper.id) : wrapper.id;
  const ioNodeToOwner = new Map<string, string>(); // IO node id -> its owner flow-node id
  for (const wrapper of ioWrappers) {
    const owner = wrapperOwner(wrapper);
    for (const memberId of wrapper.members) {
      if (nodeById.get(memberId)?.io != null) {
        ioNodeToOwner.set(memberId, owner);
      }
    }
  }
  const wrapperPorts = (wrapper: RFGroup): Port[] =>
    wrapper.members
      .map((memberId) => nodeById.get(memberId))
      .filter((m): m is RFNode => m != null && m.io != null)
      .map((m) => ({
        id: m.id,
        name: m.ref.node_id,
        dataType: m.io!.data_type,
        required: m.io!.required,
        // Only outputs carry an authored description (build puts it on purpose).
        description: m.purpose || null,
      }));
  // Group id -> the IO rows it carries (from its child level's wrappers).
  const groupIO = new Map<string, { inputs: Port[]; outputs: Port[] }>();
  for (const wrapper of ioWrappers) {
    if (!wrapper.parent) continue; // root wrappers become standalone IO cards below
    const owner = wrapperOwner(wrapper);
    const slot = groupIO.get(owner) ?? { inputs: [], outputs: [] };
    if (wrapper.kind === "input_wrapper") slot.inputs = wrapperPorts(wrapper);
    else slot.outputs = wrapperPorts(wrapper);
    groupIO.set(owner, slot);
  }
  const NO_IO = { inputs: [] as Port[], outputs: [] as Port[] };

  const collapsed = view.collapsed;
  const groupParent = (id: string): string | null => groupById.get(id)?.parent ?? null;

  // The root-most collapsed group in the chain [start..root]. `inclusive` decides
  // whether `start` itself counts. A leaf/group hidden by collapse re-anchors to
  // this group (collapsing further if its parent is also collapsed).
  const outermostCollapsed = (start: string | null, inclusive: boolean): string | null => {
    let cur = inclusive ? start : start ? groupParent(start) : null;
    let result: string | null = null;
    while (cur) {
      if (collapsed.has(cur)) result = cur;
      cur = groupParent(cur);
    }
    return result;
  };

  const flowNodes: FlowNode[] = [];
  const emitted = new Set<string>();
  // Owners whose IO rows actually RENDER this build — the single truth edge handle
  // resolution reads, so a row handle is emitted exactly when its row exists.
  const ioRowsShown = new Set<string>();

  // Groups first, parents before children (ascending nesting_depth) — React Flow
  // requires a parent node to precede its children in the array.
  for (const g of [...graph.groups].sort((a, b) => a.nesting_depth - b.nesting_depth)) {
    if (g.kind === "input_wrapper" || g.kind === "output_wrapper") continue; // → rows on their owner (group / root IO card)
    if (shellBatch.has(g.id)) continue; // decorator shell — batch rides what it wraps
    if (outermostCollapsed(g.parent, true)) continue; // inside a collapsed ancestor
    const isCollapsed = collapsed.has(g.id);
    const hostNode = g.host ? (nodeById.get(g.host) ?? null) : null;
    const showTitle = g.host != null && primaryGroupForHost.get(g.host) === g.id;
    const parentId = effectiveParent(g.parent);
    const io = groupIO.get(g.id) ?? NO_IO;
    // An OPEN region always shows its IO rows — they're the workflow's interface,
    // and an open container hiding its inputs read as "has none" (user-caught
    // 2026-06-10). Beautiful still hides the rows' EDGES (the skeleton rule —
    // data lines reveal on focus); only the rows themselves are always-on. A
    // COLLAPSED card keeps the leaf showBody rule: advanced or focus-expanded.
    const ioRowsVisible =
      (!isCollapsed || view.density === "detailed" || expandedSet.has(g.id)) &&
      (io.inputs.length > 0 || io.outputs.length > 0);
    if (ioRowsVisible) ioRowsShown.add(g.id);
    // A collapsed card showing its IO grows a two-column row area (and widens to
    // fit both columns); without rows it keeps the fixed compact card box.
    const collapsedSize = ioRowsVisible
      ? { width: GROUP_IO_WIDTH, height: HEADER_HEIGHT + ioAreaHeight(io.inputs.length, io.outputs.length) }
      : { width: COLLAPSED_GROUP_WIDTH, height: COLLAPSED_GROUP_HEIGHT };
    flowNodes.push({
      id: g.id,
      type: "group",
      position: { x: 0, y: 0 },
      parentId: parentId ?? undefined,
      extent: parentId ? "parent" : undefined,
      data: {
        group: g,
        hostNode,
        collapsed: isCollapsed,
        showTitle,
        direction: view.direction,
        // Filled by the control-incidence post-pass below (needs the flow edges,
        // which don't exist yet — re-anchoring decides what touches this group).
        hasIncoming: false,
        hasOutgoing: false,
        memberCount: stepCountByGroup.get(g.id) ?? 0,
        inputs: io.inputs,
        outputs: io.outputs,
        ioRowsVisible,
        focusedPortId: null,
        dimmed: false,
        focused: false,
      },
      ...(isCollapsed ? collapsedSize : {}),
    });
    emitted.add(g.id);
  }

  for (const n of graph.nodes) {
    if (n.is_group_host) continue; // represented by its group box
    if (n.io !== null) continue; // IO nodes are rows on their owner node
    if (outermostCollapsed(n.parent, true)) continue; // inside a collapsed group
    const parentId = effectiveParent(n.parent) ?? undefined;
    const extent = parentId ? ("parent" as const) : undefined;
    if (n.kind === "end") {
      flowNodes.push({
        id: n.id,
        type: "end",
        position: { x: 0, y: 0 },
        parentId,
        extent,
        width: END_SIZE,
        height: END_SIZE,
        data: { node: n, direction: view.direction, dimmed: false, focused: false },
      });
    } else {
      const outputFields = [...(outputFieldsByNode.get(n.id) ?? [])];
      const branchLabels = branchLabelsByNode.get(n.id) ?? [];
      const isExpanded = view.density === "compact" && expandedSet.has(n.id);
      // Same visibility rule as the edge pill: advanced always, else focus-expanded.
      const showsRows = view.density === "detailed" || isExpanded;
      const branchConditions = showsRows ? (branchConditionsByNode.get(n.id) ?? NO_CONDITIONS) : NO_CONDITIONS;
      const size = leafSize(n, view.density, view.direction, outputFields, branchLabels, isExpanded);
      flowNodes.push({
        id: n.id,
        type: "node", // one leaf component at two densities; density rides in data
        position: { x: 0, y: 0 },
        parentId,
        extent,
        width: size.width,
        height: size.height,
        data: {
          node: n,
          density: view.density,
          direction: view.direction,
          outputFields,
          branchLabels,
          branchConditions,
          hasIncoming: false, // filled by the control-incidence post-pass (flow edges)
          hasOutgoing: false,
          expanded: isExpanded,
          dimmed: false,
          focused: false,
        },
      });
    }
    emitted.add(n.id);
  }

  // The ROOT workflow's IO: two standalone IO CARDS (Inputs at the flow's start,
  // Outputs at its end — anchored into the spine by the synthesized io-flow
  // control edges below). Node anatomy like every other card; rows render
  // under the leaf showBody rule (advanced / focus-expanded), so beautiful shows
  // one quiet compact card instead of a floating table of N rows.
  let rootInputCard: string | null = null;
  let rootOutputCard: string | null = null;
  for (const wrapper of ioWrappers) {
    if (wrapper.parent) continue; // nested → rows on the workflow group (above)
    const ports = wrapperPorts(wrapper);
    if (ports.length === 0) continue;
    const rowsVisible = view.density === "detailed" || expandedSet.has(wrapper.id);
    if (rowsVisible) ioRowsShown.add(wrapper.id);
    if (wrapper.kind === "input_wrapper") rootInputCard = wrapper.id;
    else rootOutputCard = wrapper.id;
    flowNodes.push({
      id: wrapper.id,
      type: "io",
      position: { x: 0, y: 0 },
      width: rowsVisible ? IO_CARD_WIDTH : COMPACT_WIDTH,
      height: rowsVisible ? HEADER_HEIGHT + ports.length * ROW_HEIGHT + ROW_PADDING : HEADER_HEIGHT,
      data: {
        kind: wrapper.kind === "input_wrapper" ? "input" : "output",
        ports,
        workflowName: view.workflowName ?? "",
        density: view.density,
        direction: view.direction,
        rowsVisible,
        focusedPortId: null,
        hasIncoming: false, // filled by the control-incidence post-pass (flow edges)
        hasOutgoing: false,
        dimmed: false,
        focused: false,
      },
    });
    emitted.add(wrapper.id);
  }

  // Map a contract node id to the flow node that represents it on-canvas, or null
  // if it has no representation (defensive — should not happen).
  const renderAnchor = (nodeId: string): string | null => {
    if (emitted.has(nodeId)) return nodeId;
    const node = nodeById.get(nodeId);
    if (!node) return null;
    if (node.io != null) {
      // IO node → the node carrying its row (root IO card / workflow group), or
      // that owner's collapsed ancestor.
      const owner = ioNodeToOwner.get(nodeId);
      if (!owner) return null;
      if (emitted.has(owner)) return owner;
      const anchor = outermostCollapsed(groupById.get(owner)?.parent ?? null, true);
      return anchor && emitted.has(anchor) ? anchor : null;
    }
    if (node.is_group_host) {
      const gid = primaryGroupForHost.get(node.id);
      if (!gid) return null;
      const hiddenAnc = outermostCollapsed(groupById.get(gid)?.parent ?? null, true);
      if (hiddenAnc) return emitted.has(hiddenAnc) ? hiddenAnc : null;
      return emitted.has(gid) ? gid : null;
    }
    const anchor = outermostCollapsed(node.parent, true);
    return anchor && emitted.has(anchor) ? anchor : null;
  };

  const detailed = view.density === "detailed";
  // Rows are visible on an endpoint when the whole view is advanced OR that node is
  // focus-expanded — handle resolution is per-ENDPOINT, so a data line lands on a row
  // wherever the row actually renders (and only there — the silent-drop rule).
  // An IO endpoint's rows live on its OWNER; `ioRowsShown` is the render truth the
  // emission loops recorded (open regions show rows in BOTH densities).
  const rowsVisible = (id: string): boolean => {
    const owner = ioNodeToOwner.get(id);
    if (owner) return ioRowsShown.has(owner);
    return detailed || expandedSet.has(id);
  };
  const flowEdges: FlowEdge[] = [];
  const seen = new Set<string>();
  for (const e of graph.edges) {
    const source = renderAnchor(e.source);
    const target = renderAnchor(e.target);
    if (!source || !target) {
      // Every contract edge endpoint has an on-canvas representative (itself, its
      // group, or a collapsed ancestor) — a null anchor means a broken invariant.
      // Warn rather than drop silently so a future regression is observable (the
      // worst outcome for the "no information loss" bar is an invisibly-lost edge).
      console.warn(`pflow UI: dropped edge ${e.id} (${e.source} -> ${e.target}) — no on-canvas anchor`);
      continue;
    }
    if (source === target) continue; // collapsed/host self-loop — a correct drop

    const sourceHandle = sourceHandleFor(e, source, rowsVisible(e.source), view.direction, outputFieldsByNode, nodeById, ioNodeToOwner);
    const targetHandle = targetHandleFor(e, target, rowsVisible(e.target), nodeById, ioNodeToOwner);

    const key = `${source}->${target}|${e.kind}|${e.label ?? ""}|${sourceHandle}|${targetHandle}`;
    if (seen.has(key)) continue;
    seen.add(key);
    // Control edges (sequential/branch) draw as a source-node-color → target-node-
    // color gradient (the GradientEdge custom edge). Colors come from the ORIGINAL
    // endpoints (the real producer→consumer), even when re-anchored — via nodeColor,
    // so a condition node's fan-out leaves in condition orange, not code yellow.
    // error/end/data keep their semantic colors (see toFlowEdge / CSS).
    const sourceNode = nodeById.get(e.source);
    const targetNode = nodeById.get(e.target);
    const sourceColor = sourceNode ? nodeColor(sourceNode) : kindColor("");
    const targetColor = targetNode ? nodeColor(targetNode) : kindColor("");
    // A labeled LR branch's condition lives on its BranchPorts ROW
    // (LeafData.branchConditions) — the edge pill is TD's home (no rows there)
    // and the re-anchored fallback's (a collapsed source has no rows to hold it).
    const conditionOnRow = view.direction === "LR" && e.kind === "branch" && e.label != null && source === e.source;
    // LR target entries get their outcome name (TD-style bare text) whenever the
    // source's rows show — rows + target labels appear together.
    const lrOutcomeLabel = view.direction === "LR" && e.kind === "branch" && rowsVisible(e.source);
    flowEdges.push(
      toFlowEdge(
        e,
        source,
        target,
        sourceHandle,
        targetHandle,
        detailed,
        view.direction,
        sourceColor,
        targetColor,
        rowsVisible(e.source) && !conditionOnRow,
        lrOutcomeLabel,
      ),
    );
  }

  // The root IO cards JOIN THE CONTROL SKELETON (user-decided 2026-06-10): the
  // Inputs card heads the flow — a control-style edge into each root ENTRY step
  // (no incoming control edge; falls back to the FIRST root step, where pflow
  // starts execution, when a root cycle leaves no entry) — and every terminal
  // step's representative runs into the Outputs card. These are NOT contract
  // edges (pflow has no io→node control flow); they are visual policy that makes
  // the cards behave like nodes: ELK lays them into the spine (instead of parking
  // data-only islands beside it) and their tiles grow connector flares like any
  // leaf's. The per-port data lines are unchanged (hidden in beautiful, revealed
  // on focus). Drawn in BOTH densities — like forks, this is structure.
  if (rootInputCard || rootOutputCard) {
    const rootSteps = graph.nodes.filter(
      (n) => effectiveParent(n.parent) === null && n.io === null && n.kind !== "end",
    );
    // `end`: which endpoint is the IO card — colors blend IO teal into the step's
    // kind color (in) or the step's color into teal (out), the standard gradient rule.
    const ioFlowEdge = (end: "in" | "out", source: string, target: string, step: RFNode): FlowEdge => ({
      id: `io-flow:${source}->${target}`,
      source,
      target,
      sourceHandle: NODE_OUT,
      targetHandle: NODE_IN,
      type: "gradient",
      className: "edge-sequential",
      data: {
        kind: "sequential",
        shadowed: false,
        from: end === "in" ? source : step.id,
        to: end === "in" ? step.id : target,
        defaultHidden: false,
        sourceColor: end === "in" ? IO_COLOR : nodeColor(step),
        targetColor: end === "in" ? nodeColor(step) : IO_COLOR,
      },
    });
    const anchored = new Set<string>();
    if (rootInputCard) {
      const entries = rootSteps.filter((n) => !incomingControl.has(n.id));
      for (const n of entries.length > 0 ? entries : rootSteps.slice(0, 1)) {
        const anchor = renderAnchor(n.id);
        if (!anchor || anchor === rootInputCard || anchored.has(`in:${anchor}`)) continue;
        anchored.add(`in:${anchor}`);
        flowEdges.push(ioFlowEdge("in", rootInputCard, anchor, n));
      }
    }
    if (rootOutputCard) {
      for (const n of rootSteps.filter((s) => s.is_terminal)) {
        const anchor = renderAnchor(n.id);
        if (!anchor || anchor === rootOutputCard || anchored.has(`out:${anchor}`)) continue;
        anchored.add(`out:${anchor}`);
        flowEdges.push(ioFlowEdge("out", anchor, rootOutputCard, n));
      }
    }
  }

  // Synthesize a loop-back U for each looped node, drawn on the node — or on its
  // GROUP when it's a looped sub-workflow host. It is NOT a contract edge; we build
  // it from the LoopSpec (pure visual policy). Self-loops are dropped from ELK
  // (layout.ts) and rendered by the custom LoopEdge. Skip a loop whose node is
  // hidden inside a *collapsed ancestor* (the loop is hidden with it) — only draw
  // on the box that actually loops.
  //
  // Where the U LANDS and what it SAYS (user-decided 2026-06-10, "loop row"):
  //   - A LEAF whose body rows render (advanced / focus-expanded) grows a ↻
  //     loop-rule row (WorkflowNode); the U's arrow lands ON that row (LOOP_ROW
  //     handle) — "iteration re-enters under this rule" — and the edge carries NO
  //     floating label (the row holds the condition, like data lines dropping
  //     their label when both ends land on rows).
  //   - A compact leaf (beautiful, unexpanded) keeps a BARE U into NODE_IN — the
  //     skeleton stays quiet; click to expand and see why.
  //   - A GROUP anchor has no rows: the floating label renders in advanced only
  //     (data.loop is the label's presence switch — LoopEdge reads nothing else
  //     from it; the read panel always has the full spec from the NODE).
  const loopAnchors = new Set<string>();
  for (const n of graph.nodes) {
    if (!n.loop) continue;
    const anchor = renderAnchor(n.id);
    if (!anchor || loopAnchors.has(anchor)) continue;
    const isLeafAnchor = anchor === n.id;
    const ownsAnchor = isLeafAnchor || anchor === primaryGroupForHost.get(n.id);
    if (!ownsAnchor) continue;
    loopAnchors.add(anchor);
    const ontoRow = isLeafAnchor && rowsVisible(n.id);
    const showLabel = !isLeafAnchor && detailed;
    flowEdges.push({
      id: `loop:${anchor}`,
      source: anchor,
      target: anchor,
      sourceHandle: NODE_OUT,
      targetHandle: ontoRow ? LOOP_ROW : NODE_IN,
      type: "loop",
      className: "edge-loop",
      // No zIndex elevation: the old bezier ARC needed to paint above the group box
      // it crossed; the U wraps OUTSIDE its box, and an elevated edge renders above
      // the EdgeLabelRenderer layer — striking through its own label pill.
      data: {
        kind: "loop",
        shadowed: false,
        from: n.id,
        to: n.id,
        defaultHidden: false,
        ...(showLabel ? { loop: n.loop } : {}),
      },
    });
  }

  // Control-incidence for every flare-bearing node (leaves, groups, IO cards):
  // the collapsed card draws top+bottom flares, the expanded region its TOP — the
  // trunk enters through the tile like any node's. Must run over the FLOW edges:
  // contract edges never name a group — re-anchoring decides what actually touches
  // it — the self-loop drop above already removed purely-internal edges (both ends
  // inside the same collapsed group), and the synthesized io-flow skeleton edges
  // (not in the contract) must count for the IO cards and the entry/terminal steps.
  const inControlFlow = new Set<string>();
  const outControlFlow = new Set<string>();
  for (const e of flowEdges) {
    const kind = e.data?.kind;
    if (!kind || kind === "loop" || !CONTROL_KINDS.has(kind)) continue;
    inControlFlow.add(e.target);
    outControlFlow.add(e.source);
  }
  for (const n of flowNodes) {
    if (n.type === "node" || n.type === "group" || n.type === "io") {
      n.data.hasIncoming = inControlFlow.has(n.id);
      n.data.hasOutgoing = outControlFlow.has(n.id);
    }
  }

  assignEdgeLanes(flowEdges);
  return { nodes: flowNodes, edges: flowEdges };
}

// Edges entering/leaving a node all turned at the SAME default stub, so parallel
// lines overlapped pixel-exactly into one ambiguous segment (user-caught, twice):
// data bindings (a 6-row Inputs node feeding one consumer), and LR branch fan-outs
// (each outcome leaves its OWN labeled row handle, yet all merged onto one rail).
// Give each such edge a LANE: the smallest bucket unused among the laned edges
// already assigned at EITHER of its endpoint nodes. DataEdge turns the lane into
// geometry always; GradientEdge applies it in LR ONLY — in TD a fork's branches
// leave ONE point (the icon column), so the shared rail IS the trunk-split look,
// by design. Sequential edges are exempt (one out per node; merges come from
// different sources, so their rails already differ). Build-time (lane multiplexing,
// not geometry).
export const LANE_COUNT = 6; // wraps past 6 parallel lanes at one node (collision acceptable)
const LANED_KINDS = new Set<EdgeKind | "loop">(["data_flow", "branch", "error"]);

function assignEdgeLanes(edges: FlowEdge[]): void {
  const used = new Map<string, Set<number>>();
  const usedAt = (id: string): Set<number> => used.get(id) ?? used.set(id, new Set()).get(id)!;
  for (const e of edges) {
    if (!e.data || !LANED_KINDS.has(e.data.kind)) continue;
    const taken = new Set([...usedAt(e.source), ...usedAt(e.target)]);
    let lane = 0;
    while (taken.has(lane % LANE_COUNT) && lane < LANE_COUNT) lane += 1;
    lane %= LANE_COUNT;
    usedAt(e.source).add(lane);
    usedAt(e.target).add(lane);
    e.data.lane = lane;
  }
}

function sourceHandleFor(
  edge: RFEdge,
  source: string,
  rowsVisible: boolean, // the source node renders its body rows (advanced, or focus-expanded; an IO endpoint checks its OWNER)
  direction: Direction,
  outputFieldsByNode: Map<string, Set<string>>,
  nodeById: Map<string, RFNode>,
  ioNodeToOwner: Map<string, string>,
): string {
  // An IO source feeds OUT on its row's source handle — but only when the edge
  // actually reaches the owner (not a collapsed ancestor it re-anchored past) AND
  // the owner currently renders its rows (else node-level — the silent-drop rule).
  if (nodeById.get(edge.source)?.io != null) {
    return source === ioNodeToOwner.get(edge.source) && rowsVisible ? portHandle(edge.source) : NODE_OUT;
  }
  const isRealSource = source === edge.source;
  // LR: a fork leaves its own labeled border handle (n8n-style — which value goes
  // where). TD: forks fan from the icon column, so a branch leaves NODE_OUT (below
  // the icon) and its label rides the edge instead (toFlowEdge), like the references.
  if (isRealSource && edge.kind === "branch" && edge.label && direction === "LR") {
    return branchHandle(edge.label);
  }
  if (rowsVisible && isRealSource && edge.kind === "data_flow" && edge.output_field) {
    if (outputFieldsByNode.get(edge.source)?.has(edge.output_field)) {
      return outputHandle(edge.output_field);
    }
  }
  return NODE_OUT;
}

function targetHandleFor(
  edge: RFEdge,
  target: string,
  rowsVisible: boolean, // the target node renders its body rows (advanced, or focus-expanded; an IO endpoint checks its OWNER)
  nodeById: Map<string, RFNode>,
  ioNodeToOwner: Map<string, string>,
): string {
  const node = nodeById.get(edge.target);
  if (node?.io != null) {
    // An IO target RECEIVES on its row's target handle (an input bound from the
    // parent, an output written by a producer) — these are the binding edges.
    // Row only when the edge reaches the owner AND its rows currently render.
    return target === ioNodeToOwner.get(edge.target) && rowsVisible ? portTargetHandle(edge.target) : NODE_IN;
  }
  const isRealTarget = target === edge.target;
  if (rowsVisible && isRealTarget && edge.kind === "data_flow" && edge.input_name) {
    if (node?.params.some((p) => p.name === edge.input_name)) {
      return paramHandle(edge.input_name);
    }
    // input_name may be a KEY inside a dict-valued param (a code node's
    // `inputs: {data: ${...}}` — the edge builder walks dict-of-string leaves, so
    // the edge carries the dict key, not the param name). Land on the param row that
    // CONTAINS the key — but only when that key's value is itself a `${...}` string,
    // the exact condition that created the edge. Anything else stays the node-level
    // fallback: degrade, never mis-attribute (H6).
    const key = edge.input_name;
    const host = node?.params.find((p) => {
      if (typeof p.value !== "object" || p.value === null || Array.isArray(p.value)) return false;
      const v = (p.value as Record<string, unknown>)[key];
      return typeof v === "string" && v.includes("${");
    });
    if (host) return paramHandle(host.name);
  }
  return NODE_IN;
}

// What flows on a data-flow line, e.g. "stdout → data". Shown as the edge label in
// beautiful mode only (advanced shows the field names as node rows, so a label there
// would just duplicate them).
function dataFlowLabel(edge: RFEdge): string | undefined {
  const { output_field: out, input_name: inp } = edge;
  if (out && inp) return `${out} → ${inp}`;
  return out ?? inp ?? undefined;
}

function toFlowEdge(
  edge: RFEdge,
  source: string,
  target: string,
  sourceHandle: string,
  targetHandle: string,
  detailed: boolean,
  direction: Direction,
  sourceColor: string,
  targetColor: string,
  conditionShown = false,
  lrOutcomeLabel = false,
): FlowEdge {
  const isData = edge.kind === "data_flow";
  // ALL control flow draws via the custom "gradient" edge, which owns the stroke
  // COLOR: sequential/branch blend source→target; error/end keep their semantic
  // color with a short node-color fade at the node ends (see GradientEdge). Only
  // data-flow stays React Flow's "default" edge, stroked by CSS. Dash patterns +
  // shadow opacity are CSS, via the className.
  const isControl = CONTROL_KINDS.has(edge.kind);
  const classes = [`edge-${edge.kind}`];
  // Advanced DIMS a control edge a data line already covers; beautiful hides the
  // data lines, so its control edges show full-strength (not shadow-dimmed).
  if (edge.shadowed && detailed) classes.push("edge-shadowed");
  // Branch labels: in TD the forks fan from the icon column, so the label always
  // rides the edge (rendered at the target's entry). In LR the labeled BranchPorts
  // row is the outcome's home, so the edge label shows only when the source's rows
  // are informative (lrOutcomeLabel = rowsVisible(source)) — then the target ALSO
  // gets its outcome name at its entry, TD-style, so a reader can find where each
  // row's line lands without tracing it (user ask, 2026-06-10). A beautiful data
  // line is labeled with what it carries — UNLESS both of its ends land on visible
  // rows (focus-expanded cards / IO rows), where the rows already name the fields.
  const rowToRow = sourceHandle !== NODE_OUT && targetHandle !== NODE_IN;
  const label =
    edge.kind === "branch"
      ? direction === "TD" || lrOutcomeLabel
        ? (edge.label ?? undefined)
        : undefined
      : isData && !detailed && !rowToRow
        ? dataFlowLabel(edge)
        : (edge.label ?? undefined);
  // No arrowheads — clean lines flow straight into the node borders (the seamless
  // look). Beautiful = control skeleton: data-flow edges are built but hidden, and
  // applyFocus reveals just the ones touching the clicked node. Advanced shows them.
  const defaultHidden = isData && !detailed;
  return {
    id: edge.id,
    source,
    target,
    sourceHandle,
    targetHandle,
    // Data-flow uses the custom DataEdge ("data") so EVERY edge speaks the same
    // rounded-orthogonal language as the control edges (GradientEdge) — a bezier
    // here swoops across node bodies when an output row feeds the node below. The
    // component owns the stroke (lane tint + endpoint node-color fades); CSS keeps
    // only the dash pattern. The per-edge lane rides data.lane (assignDataEdgeLanes).
    type: isControl ? "gradient" : "data",
    label,
    className: classes.join(" "),
    data: {
      kind: edge.kind,
      shadowed: edge.shadowed,
      from: edge.source,
      to: edge.target,
      defaultHidden,
      sourceColor,
      targetColor,
      condition: edge.condition ?? undefined,
      conditionShown: conditionShown && edge.condition != null,
      outcome: edge.kind === "branch" ? (edge.label ?? undefined) : undefined,
    },
    hidden: defaultHidden,
  };
}

const DIMMED_EDGE_CLASS = "edge-dimmed";

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
// `focus` is a contract id — a node id, a root IO card's id, OR an individual IO
// port's id (a row). An edge is incident if its flow endpoints OR its original
// endpoints (`data.from`/`to`) touch the focus, so a single port reveals just its
// own lines even though its edges re-anchor onto the shared owner node.
function edgeTouchesFocus(e: FlowEdge, focus: string): boolean {
  return e.source === focus || e.target === focus || e.data?.from === focus || e.data?.to === focus;
}

export function applyFocus(
  nodes: FlowNode[],
  edges: FlowEdge[],
  focus: string | null,
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const connected = new Set<string>();
  if (focus) {
    connected.add(focus);
    for (const e of edges) {
      if (edgeTouchesFocus(e, focus)) {
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
      if (e.data?.kind !== "branch" || e.data.condition == null) continue;
      if (e.target !== focus && e.data.to !== focus) continue;
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
    const incident = focus != null && edgeTouchesFocus(e, focus);
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
    // Which END of an incident data line the focus sits on — DataEdge renders the
    // line solid at the clicked node and fading a hint toward the far end, so the
    // revealed wiring visibly BELONGS to the focus (user-chosen treatment).
    const focusEnd =
      incident && e.data?.kind === "data_flow"
        ? e.source === focus || e.data.from === focus
          ? ("source" as const)
          : ("target" as const)
        : undefined;
    // The edge-pill arm of the target-click reveal (see revealBySource above for
    // the LR row arm). The pill is otherwise governed by conditionShown.
    const conditionRevealed =
      focus != null &&
      e.data?.kind === "branch" &&
      e.data.condition != null &&
      (e.target === focus || e.data.to === focus) &&
      !rowReveals(e)
        ? true
        : undefined;
    if (
      className === e.className &&
      hidden === (e.hidden ?? false) &&
      focusEnd === e.data?.focusEnd &&
      conditionRevealed === e.data?.conditionRevealed
    ) {
      return e;
    }
    return { ...e, className, hidden, ...(e.data ? { data: { ...e.data, focusEnd, conditionRevealed } } : {}) };
  });
  return { nodes: outNodes, edges: outEdges };
}
