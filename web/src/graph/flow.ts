// The RFGraph -> React Flow transform. Pure and unit-tested: given the contract
// payload and the current view state, produce React Flow nodes + edges (positions
// are filled afterwards by ELK in layout.ts).
//
// This file is the graph package's FAÇADE: it keeps buildFlow + edge construction
// and re-exports the sibling modules (scan / io / rows / focus), so consumers keep
// importing from "../graph/flow". The dependency DAG is scan → io → rows →
// focus/flow (rows and focus import flow's types TYPE-ONLY, which TS erases — no
// runtime cycle).
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

import { bindingRowHandle, branchHandle, LOOP_ROW, NODE_IN, NODE_OUT, outputHandle, paramHandle, portHandle, portTargetHandle } from "./handles";
import { METRICS } from "./metrics";
import { type FieldReads, scanParamReads } from "./scan";
import { ioOwners, type Port, shellBatchIds, wrapperPorts } from "./io";
import {
  COLLAPSED_GROUP_HEIGHT,
  COLLAPSED_GROUP_WIDTH,
  COMPACT_WIDTH,
  END_SIZE,
  groupIoWidth,
  HEADER_HEIGHT,
  IO_CARD_WIDTH,
  ioAreaHeight,
  leafSize,
  type NodeRow,
  nodeRows,
  outputRowsFor,
  paramRowsFor,
  type RefRow,
  ROW_HEIGHT,
  ROW_PADDING,
} from "./rows";
import { NO_EXPANSION } from "./focus";
import { IO_COLOR, bindingLabel, kindColor, nodeColor } from "../utils/format";
import type { EdgeKind, LoopSpec, RFEdge, RFGraph, RFGroup, RFNode } from "../types";

export * from "./scan";
export * from "./io";
export * from "./rows";
export * from "./focus";

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
  // The card's WHOLE body as one ordered row list (nodeRows — the left column
  // via paramRowsFor, output rows via outputRowsFor, then the loop-rule rows),
  // each row carrying its own handle. THE single source the render
  // (WorkflowNode's switch), height (leafSize) and ports (rowAnchorsFor) all
  // consume, so render, size, ports and handles cannot drift.
  rows: NodeRow[];
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
  // control sink → Outputs), so they behave like nodes — flares included. Filled
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
  density: Density; // MOCK: the NameLabel picks humanized (beautiful) vs verbatim (advanced)
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
  // Edge SELECTION (edge-click, 2026-06-10): set by applyFocus when this edge IS
  // the focus. Components draw the bright selected treatment + halo and suppress
  // their own floating label/pill (the elevated edge would strike through it — the
  // read panel carries the info instead). The elevation zIndex rides the edge
  // OBJECT, not data.
  selected?: boolean;
  // Set by applyFocus alongside the dim className: EdgeLabelRenderer pills render
  // OUTSIDE .react-flow__edge, so the CSS opacity dim never reaches them — the
  // components apply this flag to their label/pill divs.
  dimmed?: boolean;
  loop?: LoopSpec; // present only on synthesized loop-back arcs
};

export type FlowNode =
  | Node<LeafData, "node">
  | Node<IOCardData, "io">
  | Node<GroupData, "group">
  | Node<EndData, "end">;
export type FlowEdge = Edge<EdgeData>;

/** An edge's ref as authored text, rebuilt from its resolved endpoints
 *  (`extract.response` — for cache chunks the parser enforces chunk name ==
 *  var, so this IS the `prompt_cache:` entry). Sub-row label + handle key;
 *  the SAME helper derives the rows (buildFlow) and lands the edges
 *  (targetHandleFor), so a line can never miss its row. */
function refText(edge: RFEdge, nodeById: Map<string, RFNode>): string {
  const root = nodeById.get(edge.source)?.ref.node_id ?? edge.source;
  return [root, ...(edge.output_field ? [edge.output_field, ...edge.output_path] : [])].join(".");
}

// Control-flow edge kinds — these connect at a node's NODE_IN/NODE_OUT (the trunk),
// so they drive the icon connector stubs. data_flow lands on param rows; loop is a
// self-arc — neither implies a trunk in/out. Exported for layout.ts (straightness
// priorities + error-branch ordering work on control edges only).
export const CONTROL_KINDS: ReadonlySet<EdgeKind> = new Set<EdgeKind>(["sequential", "branch", "error", "end"]);

const NO_CONDITIONS: Record<string, string> = {};

export function buildFlow(graph: RFGraph, view: BuildOptions): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));
  const expandedSet = view.expanded ?? NO_EXPANSION;

  // Decorator-shell batch groups are never rendered: their children reparent past
  // them and a suppressed host's representative skips them. A literal batch group
  // holding expanded item groups is NOT a shell — it renders and represents its
  // host (the single copy of the rule lives in io.ts shellBatchIds).
  const shellBatch = shellBatchIds(graph);
  const effectiveParent = (parent: string | null): string | null => {
    while (parent && shellBatch.has(parent)) parent = groupById.get(parent)?.parent ?? null;
    return parent;
  };

  // CONTRACT-level control incidence. Render-time incidence (the connector flares)
  // comes from a post-pass over the FLOW edges — these sets exist to find the root
  // ENTRY steps (no incoming control edge) and CONTROL SINKS (no forward control
  // successor) for the synthesized io-flow skeleton. Sinks count only
  // sequential/branch out-edges (error/end excluded, the model's own clauses) and
  // deliberately NOT the contract's `is_terminal`: that fact also counts DATA_FLOW,
  // so a final leaf feeding a declared output reads non-terminal — filtering on it
  // left the Outputs card with no io-flow edge at all, a floating island
  // (user-caught 2026-06-11 on lyrics-generator).
  const incomingControl = new Set<string>();
  const outgoingForward = new Set<string>();
  for (const e of graph.edges) {
    if (!CONTROL_KINDS.has(e.kind)) continue;
    incomingControl.add(e.target);
    if (e.kind === "sequential" || e.kind === "branch") outgoingForward.add(e.source);
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

  // What each node's output fields are READ as (bare and/or sub-key reads, per
  // field) — feeds outputRowsFor (only used when an edge keeps its real source;
  // re-anchored edges fall back to node-level).
  const observedReadsByNode = new Map<string, Map<string, FieldReads>>();
  // Branch outcomes a decision node forks on — one labeled source handle per
  // outcome, in declared order (deduped). Drives the n8n-Switch-style border ports.
  const branchLabelsByNode = new Map<string, string[]>();
  // Outcome label → extracted condition, per decision node (LeafData.branchConditions).
  const branchConditionsByNode = new Map<string, Record<string, string>>();
  // Per-target binding groups (RefRow[]), keyed by the PARENT each edge lands
  // under: the containing param's name (interpolated refs AND dict-key
  // bindings, via bindingParam) or "prompt_cache" (`## Cache` chunks). Contract
  // order == authored order (text/dict/`prompt_cache:` list order). Feeds
  // paramRowsFor (the sub-rows) and targetHandleFor (the ≥2 landing rule) —
  // one derivation, so rows and landings can't disagree.
  const refRowsByNode = new Map<string, Map<string, RefRow[]>>();
  for (const e of graph.edges) {
    if (e.kind === "data_flow" && e.input_name) {
      const target = nodeById.get(e.target);
      const groupName =
        e.input_name === "prompt_cache" ? "prompt_cache" : target?.io == null ? bindingParam(target, e.input_name)?.name : undefined;
      if (groupName != null) {
        const groups = refRowsByNode.get(e.target) ?? new Map<string, RefRow[]>();
        const rows = groups.get(groupName) ?? [];
        const ref = refText(e, nodeById);
        const handle = bindingRowHandle(e.input_name, ref);
        if (!rows.some((r) => r.handle === handle)) {
          rows.push({ handle, name: e.input_name === groupName || groupName === "prompt_cache" ? null : e.input_name, ref });
        }
        groups.set(groupName, rows);
        refRowsByNode.set(e.target, groups);
      }
    }
    if (e.kind === "data_flow" && e.output_field) {
      const fields = observedReadsByNode.get(e.source) ?? new Map<string, FieldReads>();
      const reads = fields.get(e.output_field) ?? { bare: false, subKeys: [] };
      const sub = e.output_path?.[0];
      if (sub != null) {
        if (!reads.subKeys.includes(sub)) reads.subKeys.push(sub);
      } else {
        reads.bare = true;
      }
      fields.set(e.output_field, reads);
      observedReadsByNode.set(e.source, fields);
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
  // The reserved "end" OUTCOME: a decision's END edge is its stop arm (`if ok:
  // next="end"` — the model counts it toward is_decision, and the contract attaches
  // the extracted condition to that END edge). A SEPARATE pass so "end" always
  // reads LAST among the fork rows — forward outcomes first, stop last — regardless
  // of contract edge order. A non-decision's END edge (static `- next: end`) is
  // single-outcome routing and gets no row.
  const decisionIds = new Set(graph.nodes.filter((n) => n.is_decision).map((n) => n.id));
  for (const e of graph.edges) {
    if (e.kind !== "end" || !decisionIds.has(e.source)) continue;
    const labels = branchLabelsByNode.get(e.source) ?? [];
    if (!labels.includes("end")) labels.push("end");
    branchLabelsByNode.set(e.source, labels);
    if (e.condition) {
      const conds = branchConditionsByNode.get(e.source) ?? {};
      conds.end = e.condition;
      branchConditionsByNode.set(e.source, conds);
    }
  }

  // Plain-param reads (user decision 2026-06-10): `prompt: ${gen.result.ok}`
  // forms NO data-flow edge (the model's known scope limit), so edge-derived
  // quiet rows wrongly claimed "produced but unconsumed" for the most common
  // wiring. Scan every node's param text for sibling refs and merge them into
  // the observed reads — quiet then truthfully means "no reader at all".
  // Bounded on purpose: scope-aware (a ref root resolves only to a SIBLING
  // node_id — same parent — mirroring build's level-scoped resolution, so a
  // name reused in another sub-workflow can't be mis-marked); the reader's
  // batch alias is skipped; a param read NEVER creates a new top-level field
  // row (no edge + no shape → no row = no claim) and draws no line (D5: lines
  // come only from edges). Residual: refs outside params (loop conditions) are
  // not scanned.
  scanParamReads(graph, observedReadsByNode);

  // A workflow's IO ports render as ROWS on an OWNER node, never as a separate
  // table: a NESTED workflow's wrapper puts its rows on the workflow GROUP node
  // (wrapper.parent — collapsed card columns / expanded region sidebar+strip); a
  // ROOT wrapper becomes a standalone IO CARD reusing the wrapper's group id (no
  // node uses a g* id, so no collision — and focus/deep-link ids stay stable).
  // The IO member nodes are NOT emitted; each maps to (its owner, its row handle).
  const ioWrappers = graph.groups.filter(
    (g) => (g.kind === "input_wrapper" || g.kind === "output_wrapper") && g.members.length > 0,
  );
  // IO ownership (ioOwners — the single rule): port → owner feeds edge handle
  // resolution; wrapper → owner places the row areas.
  const { wrappers: ownerByWrapper, ports: ioNodeToOwner } = ioOwners(graph);
  // Group id -> the IO rows it carries (from its child level's wrappers).
  const groupIO = new Map<string, { inputs: Port[]; outputs: Port[] }>();
  for (const wrapper of ioWrappers) {
    if (!wrapper.parent) continue; // root wrappers become standalone IO cards below
    const owner = ownerByWrapper.get(wrapper.id) ?? wrapper.id;
    const slot = groupIO.get(owner) ?? { inputs: [], outputs: [] };
    if (wrapper.kind === "input_wrapper") slot.inputs = wrapperPorts(graph, wrapper);
    else slot.outputs = wrapperPorts(graph, wrapper);
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
  // The row list actually given to each emitted leaf — the landing ladder
  // (sourceHandleFor) checks "does this row render" against THIS list, never a
  // recomputed one (the silent-drop rule: never name a handle that doesn't render).
  const rowsByNode = new Map<string, NodeRow[]>();

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
      ? { width: groupIoWidth(io), height: HEADER_HEIGHT + ioAreaHeight(io.inputs.length, io.outputs.length) }
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
        density: view.density,
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
      const outputRows = outputRowsFor(n, observedReadsByNode.get(n.id), graph.kind_output_types?.[n.kind]);
      const rows = nodeRows(n, paramRowsFor(n, refRowsByNode.get(n.id)), outputRows);
      rowsByNode.set(n.id, rows);
      const branchLabels = branchLabelsByNode.get(n.id) ?? [];
      const isExpanded = view.density === "compact" && expandedSet.has(n.id);
      // Same visibility rule as the edge pill: advanced always, else focus-expanded.
      const showsRows = view.density === "detailed" || isExpanded;
      const branchConditions = showsRows ? (branchConditionsByNode.get(n.id) ?? NO_CONDITIONS) : NO_CONDITIONS;
      const size = leafSize(view.density, view.direction, rows, branchLabels, isExpanded);
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
          rows,
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
    const ports = wrapperPorts(graph, wrapper);
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
      // +ioLabelH: the rows carry an INPUTS/OUTPUTS column caption — GRID PARITY
      // with a group card's IO columns (header + chrome + label + rows), so when
      // the LR spine aligns two card headers their bindings align row-to-row too.
      height: rowsVisible ? HEADER_HEIGHT + METRICS.ioLabelH + ports.length * ROW_HEIGHT + ROW_PADDING : HEADER_HEIGHT,
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

    const sourceHandle = sourceHandleFor(e, source, rowsVisible(e.source), view.direction, rowsByNode, nodeById, ioNodeToOwner);
    const targetHandle = targetHandleFor(e, target, rowsVisible(e.target), nodeById, ioNodeToOwner, refRowsByNode);

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
    // An IO binding's floating label duplicates what the port ROWS already name
    // (and a binding's label often single-names one side) — IO-touching data
    // lines carry no label; the rows / read panel name the fields (user-caught
    // 2026-06-10). Leaf-to-leaf data lines keep theirs (`stdout → data`).
    const ioBinding = sourceNode?.io != null || targetNode?.io != null;
    // A labeled LR branch's condition lives on its BranchPorts ROW
    // (LeafData.branchConditions) — the edge pill is TD's home (no rows there)
    // and the re-anchored fallback's (a collapsed source has no rows to hold it).
    // A decision's END edge is its "end" outcome and follows the same rule (its
    // row is the "end" BranchPorts row).
    // A decision's END edge is its reserved "end" outcome — discriminated by the
    // SOURCE's is_decision fact, never by condition presence (extraction is
    // fail-closed: an unparseable gate ships condition=null and is still a decision).
    const decisionEnd = e.kind === "end" && decisionIds.has(e.source);
    const isOutcomeEdge = e.kind === "branch" ? e.label != null : decisionEnd;
    const conditionOnRow = view.direction === "LR" && isOutcomeEdge && source === e.source;
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
        ioBinding,
        decisionEnd,
      ),
    );
  }

  // The root IO cards JOIN THE CONTROL SKELETON (user-decided 2026-06-10): the
  // Inputs card heads the flow — a control-style edge into each root ENTRY step
  // (no incoming control edge; falls back to the FIRST root step, where pflow
  // starts execution, when a root cycle leaves no entry) — and every root CONTROL
  // SINK's representative runs into the Outputs card (no forward control successor,
  // derived from the edges — see `outgoingForward`; falls back to the LAST root
  // step on a root cycle). These are NOT contract
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
      const sinks = rootSteps.filter((n) => !outgoingForward.has(n.id));
      // A root cycle can leave no sink — fall back to the LAST root step (the
      // mirror of the entry side's first-step fallback) so the card never floats.
      for (const n of sinks.length > 0 ? sinks : rootSteps.slice(-1)) {
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
    // hasOutgoing means "the trunk leaves THIS node's NODE_OUT" — it drives the
    // exit decorations (TD bottom flare, LR exit dot). HANDLE-aware on purpose:
    // an LR decision's outcomes leave their labeled BranchPorts ROWS, not
    // NODE_OUT, so a pure decider must not light an exit at the icon row. (In TD
    // forks fan from NODE_OUT, so the handle check changes nothing there.)
    if (e.sourceHandle === NODE_OUT) outControlFlow.add(e.source);
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
  rowsByNode: Map<string, NodeRow[]>,
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
  // A decision's END edge leaves its "end" outcome row — the row exists exactly
  // when the source is a decision (buildFlow appends "end" to its branchLabels),
  // mirroring BranchPorts' render condition (the silent-drop rule).
  if (isRealSource && edge.kind === "end" && direction === "LR" && nodeById.get(edge.source)?.is_decision) {
    return branchHandle("end");
  }
  if (rowsVisible && isRealSource && edge.kind === "data_flow" && edge.output_field) {
    // The landing ladder (H6, one level deeper — D7): a sub-key ref lands on its
    // exact key row when that row renders; else the field's parent row; else
    // node-level. "Renders" is checked against the node's ACTUAL row list
    // (rowsByNode — the same list buildFlow gave the leaf) — never name a
    // handle that doesn't render (React Flow drops it silently).
    const hasOutputRow = (field: string): boolean =>
      rowsByNode.get(edge.source)?.some((r) => r.kind === "output" && r.row.field === field) ?? false;
    const sub = edge.output_path?.[0];
    const keyField = sub != null ? `${edge.output_field}.${sub}` : null;
    if (keyField != null && hasOutputRow(keyField)) {
      return outputHandle(keyField);
    }
    if (hasOutputRow(edge.output_field)) {
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
  refRowsByNode: Map<string, Map<string, RefRow[]>>,
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
    // The per-ref landing rule, mirroring paramRowsFor's sub-row rule (both
    // read refRowsByNode, so rows and landings can't disagree): a cache edge
    // ALWAYS lands on its chunk row (the flat single-chunk row carries the
    // handle too); a param edge lands on its ref's sub-row only when the
    // param receives ≥2 refs — a single ref keeps the param row itself.
    if (edge.input_name === "prompt_cache") return bindingRowHandle("prompt_cache", refText(edge, nodeById));
    const p = bindingParam(node, edge.input_name);
    if (p) {
      const subs = refRowsByNode.get(edge.target)?.get(p.name) ?? [];
      return subs.length >= 2 ? bindingRowHandle(edge.input_name, refText(edge, nodeById)) : paramHandle(p.name);
    }
  }
  return NODE_IN;
}

/** The param a data edge LANDS ON: direct name match first, else the dict-valued
 *  param whose `input_name` KEY is itself a `${...}` string (a code node's
 *  `inputs: {data: ${...}}` — the edge builder walks dict-of-string leaves, so the
 *  edge carries the dict key, not the param name). Only that exact
 *  edge-creating condition matches; anything else returns null so callers
 *  degrade, never mis-attribute (H6). THE single copy of this walk — the
 *  EdgePanel's param block consumes it too, so the panel can never highlight a
 *  param the rendered line doesn't land on (review-caught duplication,
 *  2026-06-11). */
export function bindingParam(target: RFNode | null | undefined, inputName: string | null): RFNode["params"][number] | null {
  if (!target || target.io != null || !inputName) return null;
  const direct = target.params.find((p) => p.name === inputName);
  if (direct) return direct;
  return (
    target.params.find((p) => {
      if (typeof p.value !== "object" || p.value === null || Array.isArray(p.value)) return false;
      const v = (p.value as Record<string, unknown>)[inputName];
      return typeof v === "string" && v.includes("${");
    }) ?? null
  );
}

// What flows on a data-flow line, e.g. "stdout → data". Shown as the edge label in
// beautiful mode only (advanced shows the field names as node rows, so a label there
// would just duplicate them). input_name routes through bindingLabel: a cache edge
// can never land row-to-row (no param row exists for it), so without the mapping the
// raw `prompt_cache` sentinel would always show.
function dataFlowLabel(edge: RFEdge): string | undefined {
  const out = edge.output_field;
  const inp = edge.input_name == null ? edge.input_name : bindingLabel(edge.input_name);
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
  ioBinding = false,
  decisionEnd = false,
): FlowEdge {
  const isData = edge.kind === "data_flow";
  // ALL control flow draws via the custom "gradient" edge, which owns the stroke
  // COLOR: sequential/branch blend source→target; error/end keep their semantic
  // color with a short node-color fade at the node ends (see GradientEdge). Only
  // data-flow stays React Flow's "default" edge, stroked by CSS. Dash patterns +
  // shadow opacity are CSS, via the className.
  const isControl = CONTROL_KINDS.has(edge.kind);
  const classes = [`edge-${edge.kind}`];
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
      : isData && !detailed && !rowToRow && !ioBinding
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
      // A decision's END edge carries the reserved "end" outcome — gated on the
      // SOURCE's is_decision fact (`decisionEnd`), never on condition presence:
      // extraction is fail-closed, so a decision whose end-route condition could
      // not be parsed ships condition=null yet its END edge is still an outcome
      // (buildFlow's branchLabels machinery and EdgePanel already use this rule;
      // review-caught 2026-06-11).
      outcome: edge.kind === "branch" ? (edge.label ?? undefined) : decisionEnd ? "end" : undefined,
    },
    hidden: defaultHidden,
  };
}
