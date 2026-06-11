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
  outputRows: OutputRow[];
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
  // The authored `default:` value (inputs only); null when absent.
  defaultValue: unknown;
  // The authored description (the contract's `purpose`), inputs and outputs
  // alike. Surfaced as the row tooltip and the IoPanel entry.
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
  outputRows: OutputRow[],
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
  const rows = node.params.length + outputRows.length + branchRows + loopRows;
  return { width, height: HEADER_HEIGHT + rows * ROW_HEIGHT + ROW_PADDING };
}

// One output-port row on a leaf card, derived by outputRowsFor — THE single
// source of truth that WorkflowNode (render), leafSize (height), rowAnchorsFor
// (LR ELK ports) and sourceHandleFor (edge landing) all consume, so render,
// size, ports and handles stay in lockstep by construction.
export type OutputRow = {
  // The handle key: "result" | "result.summary" (always the full dotted path).
  field: string;
  // The row text: "result" (parent) | "summary" (nested under a parent, D2) |
  // "result.summary" (flat wrapper-collapse, D3 — always the FULL dotted path,
  // the exact text an author must write in `${...}`, never a bare key name).
  label: string;
  // Faint `: type` suffix (D1) — the authored annotation / inferred key type.
  dataType: string | null;
  // Authored-but-unread (D4): grey dot, faint text. No line can exist — lines
  // come only from edges, and edges only from actual `${refs}` (D5).
  quiet: boolean;
  nested: boolean; // renders indented under its parent row (the D2 case)
};

// What the graph's edges READ from one node, per output field: a bare read
// (`${n.result}`) and/or sub-key reads (`${n.result.ok}` → "ok" — the FIRST
// path segment only, D7; deeper structure is read-panel-only, matching where
// edges can form). Collected in buildFlow's edge scan, in first-read order.
export type FieldReads = { bare: boolean; subKeys: string[] };
// The read-only view outputRowsFor consumes — the edge scan needs mutation,
// the composition must not (a future refactor merging authored keys INTO
// subKeys would silently corrupt the frozen EMPTY_READS singleton otherwise).
type FieldReadsView = { readonly bare: boolean; readonly subKeys: readonly string[] };

const EMPTY_READS: FieldReadsView = Object.freeze({ bare: false, subKeys: Object.freeze([]) });

/** The type a producer's `field[.key]` carries, FAIL-CLOSED: the authored
 *  shape's field/key type, else the registry's kind interface — the same
 *  resolution order the output rows use (outputRowsFor). Deeper paths and
 *  anything unprovable return null; never a filler like "any". IoPanel uses
 *  this to type an undeclared workflow output from its producer's annotation. */
export function producedTypeOf(
  node: RFNode | undefined,
  field: string | null,
  path: readonly string[],
  kindTypes?: Readonly<Record<string, string>>,
): string | null {
  if (!node || !field) return null;
  const shape = node.output_shape;
  if (path.length === 0) {
    if (shape?.field === field && shape.data_type) return shape.data_type;
    return kindTypes?.[field] ?? null;
  }
  if (path.length === 1 && shape?.field === field) {
    return shape.keys?.find((k) => k.name === path[0])?.data_type ?? null;
  }
  return null;
}

export function outputRowsFor(
  node: RFNode,
  observed?: ReadonlyMap<string, FieldReadsView>,
  // The registry's declared types for this node's KIND (graph.kind_output_types
  // [node.kind]) — the LAST fallback for a field-level row's type. Never adds a
  // row: shell/http/mcp rows exist only from reads; this just names what flows.
  kindTypes?: Readonly<Record<string, string>>,
): OutputRow[] {
  const fields = [...(observed?.keys() ?? [])];
  const shape = node.output_shape;
  // An authored shape produces rows even with zero readers — "produced but
  // unconsumed" is exactly the signal the quiet rows exist to show (D4). The
  // shape names its own port (`result` / `response` — where that kind actually
  // writes); it leads when authored-only: it is the node's primary product.
  if (shape && !fields.includes(shape.field)) fields.unshift(shape.field);
  const rows: OutputRow[] = [];
  for (const field of fields) {
    const reads = observed?.get(field) ?? EMPTY_READS;
    const fieldShape = shape != null && field === shape.field ? shape : null;
    const authored = fieldShape?.keys ?? null;
    // The key set is ALWAYS authored ∪ observed: an observed sub-read of a key
    // ABSENT from the authored shape (stale shape / post-literal mutation /
    // permissive mode) still gets an ACTIVE row — otherwise its line falls to
    // NODE_OUT and the feature fails for exactly the read it exists to show.
    const names = (authored ?? []).map((k) => k.name);
    for (const k of reads.subKeys) if (!names.includes(k)) names.push(k);
    const read = new Set(reads.subKeys);
    const typeOf = (name: string): string | null => authored?.find((k) => k.name === name)?.data_type ?? null;
    if (reads.bare || authored == null) {
      // D2 (wholesale read) / keys-unknown: the parent row renders and key rows
      // nest under it. With no keys at all this IS today's single-row behavior
      // — which non-`result` fields (stdout) keep, except they too gain nested
      // rows when sub-reads exist (the observed-usage generalization).
      rows.push({
        field,
        label: field,
        dataType: fieldShape?.data_type ?? kindTypes?.[field] ?? null,
        quiet: !reads.bare,
        nested: false,
      });
      for (const name of names) {
        rows.push({ field: `${field}.${name}`, label: name, dataType: typeOf(name), quiet: !read.has(name), nested: true });
      }
    } else {
      // D3 (wrapper-collapse): nothing reads the field bare AND the keys are
      // known — the parent row is dropped; keys render flat with full paths.
      for (const name of names) {
        rows.push({
          field: `${field}.${name}`,
          label: `${field}.${name}`,
          dataType: typeOf(name),
          quiet: !read.has(name),
          nested: false,
        });
      }
    }
  }
  return rows;
}

// Template-ref extraction for the param-read scan — mirrors scope.py's walk
// (refs_with_path_in): find each ${...} block, split it on the coalesce operator
// into operands, SKIP literal operands, then capture root + dotted tail per
// non-literal operand. The operand split is load-bearing, not hygiene: a quoted
// fallback like `${cfg.text ?? "ask gen.result owner"}` contains spaces, and a
// space INSIDE the literal satisfies the root prefix class — without the skip,
// `gen`'s `result` row would read as ACTIVE with zero real readers (the inverse
// of the lie quiet rows exist to prevent; review-caught 2026-06-11).
const REF_BLOCK_RE = /\$\{([^}]*)\}/g;
const REF_IN_BLOCK_RE = /(?:^|[\s?])([a-zA-Z0-9_-]+)((?:\.[a-zA-Z0-9_-]+)*)/g;
const COALESCE_SPLIT_RE = /\s*\?\?\s*/;

/** Mirrors TemplateResolver.is_literal_operand (the skip scope.py applies before
 *  extracting refs): literals start with one of `{ [ " -` or a digit, or are
 *  exactly the keywords true/false/null; identifiers start with a letter/underscore. */
function isLiteralOperand(operand: string): boolean {
  const first = operand[0];
  if (first == null) return false;
  if ('{["-0123456789'.includes(first)) return true;
  return operand === "true" || operand === "false" || operand === "null";
}

function stringLeaves(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(stringLeaves);
  if (value !== null && typeof value === "object") return Object.values(value).flatMap(stringLeaves);
  return [];
}

// One plain-param `${sibling.field…}` read, resolved to its producer. The shared
// walk both consumers below derive from (canvas rows AND the read panel — split
// scans would drift; review-caught 2026-06-11): scope-aware (same-parent node_id
// only), batch-alias-skipping, coalesce-literal-skipping; a bare `${gen}` names
// no field and never counts.
type ParamRead = { producer: RFNode; segments: string[] };

function paramTextReads(graph: RFGraph): ParamRead[] {
  const byScopeName = new Map<string, RFNode>();
  for (const n of graph.nodes) {
    if (n.io === null && n.kind !== "end") byScopeName.set(`${n.parent ?? ""}|${n.ref.node_id}`, n);
  }
  const found: ParamRead[] = [];
  for (const reader of graph.nodes) {
    const alias = reader.batch?.as_name;
    for (const param of reader.params) {
      for (const leaf of stringLeaves(param.value)) {
        for (const block of leaf.matchAll(REF_BLOCK_RE)) {
          for (const operand of (block[1] ?? "").split(COALESCE_SPLIT_RE)) {
            const trimmed = operand.trim();
            if (isLiteralOperand(trimmed)) continue;
            for (const m of trimmed.matchAll(REF_IN_BLOCK_RE)) {
              const root = m[1];
              const tail = m[2] ?? "";
              if (root == null || root === alias) continue; // the per-item batch alias, never a sibling
              const producer = byScopeName.get(`${reader.parent ?? ""}|${root}`);
              if (!producer || producer.id === reader.id) continue;
              const segments = tail ? tail.slice(1).split(".") : [];
              if (segments.length === 0) continue; // a bare `${gen}` names no field
              found.push({ producer, segments });
            }
          }
        }
      }
    }
  }
  return found;
}

/** Merge plain-param `${sibling.field.key}` reads into the observed-read set
 *  (see the call site in buildFlow for the WHY + the deliberate bounds). */
function scanParamReads(graph: RFGraph, observed: Map<string, Map<string, FieldReads>>): void {
  for (const { producer, segments } of paramTextReads(graph)) {
    const field = segments[0]!;
    const fields = observed.get(producer.id);
    const existing = fields?.get(field);
    // Only correct rows that EXIST (via edges or the authored shape) —
    // a param read must not grow new field rows.
    if (existing == null && field !== producer.output_shape?.field) continue;
    const reads = existing ?? { bare: false, subKeys: [] };
    const subKey = segments[1];
    if (subKey != null) {
      if (!reads.subKeys.includes(subKey)) reads.subKeys.push(subKey);
    } else {
      reads.bare = true;
    }
    const slot = fields ?? new Map<string, FieldReads>();
    slot.set(field, reads);
    observed.set(producer.id, slot);
  }
}

/** Full-depth dotted read paths per producer — the read panel's "consumed" fact.
 *  ONE truth with the canvas rows: contract data-flow edges PLUS the same
 *  param-text scan buildFlow merges — a key consumed only through a prompt body
 *  must list in the panel too, or panel and canvas state contradictory facts
 *  about the same binding (review-caught 2026-06-11). Param reads pass the same
 *  no-new-claims gate as the canvas (a field must exist via an edge read or the
 *  authored shape); unlike the canvas rows (first segment only, D7) the paths
 *  here are untruncated — the panel is the full-depth home. */
export function consumedReadPaths(graph: RFGraph): Map<string, string[]> {
  const paths = new Map<string, string[]>();
  const edgeFields = new Map<string, Set<string>>();
  const add = (producerId: string, path: string): void => {
    const list = paths.get(producerId) ?? [];
    if (!list.includes(path)) list.push(path);
    paths.set(producerId, list);
  };
  for (const e of graph.edges) {
    if (e.kind !== "data_flow" || e.output_field == null) continue;
    const fields = edgeFields.get(e.source) ?? new Set<string>();
    fields.add(e.output_field);
    edgeFields.set(e.source, fields);
    add(e.source, [e.output_field, ...e.output_path].join("."));
  }
  for (const { producer, segments } of paramTextReads(graph)) {
    const field = segments[0]!;
    if (!edgeFields.get(producer.id)?.has(field) && field !== producer.output_shape?.field) continue;
    add(producer.id, segments.join("."));
  }
  return paths;
}

/** Where each ROW handle sits inside its node box — the LR layout's PORT
 *  declarations (layout.ts): with fixed ports ELK aligns ROW-to-ROW, so a bundle
 *  of bindings between two cards runs dead straight instead of jogging by the
 *  cards' constant grid offset (measured 52px on run-from-plan — user-caught
 *  2026-06-10). The y math mirrors the components' render order exactly:
 *  WorkflowNode body = params → outputs → loop rows, then BranchPorts below;
 *  IOCardNode/GroupNode = `.io-rows` chrome (METRICS.ioRowsChrome) + optional
 *  column label + rows, outputs column BOTTOM-ANCHORED (the stagger). Only the
 *  role-side handles edges can actually use are anchored; loop rows carry only
 *  the self-loop (never in ELK). An EXPANDED group returns none — an ELK port on
 *  a COMPOUND node crashes elkjs under INCLUDE_CHILDREN (test-pinned). */
export type RowAnchor = { handle: string; side: "left" | "right"; y: number };

export function rowAnchorsFor(n: FlowNode): RowAnchor[] {
  const mid = ROW_HEIGHT / 2;
  if (n.type === "node") {
    const { node, density, direction, outputRows, branchLabels, expanded } = n.data;
    const anchors: RowAnchor[] = [];
    let row = 0;
    if (density === "detailed" || expanded) {
      for (const p of node.params) {
        anchors.push({ handle: paramHandle(p.name), side: "left", y: HEADER_HEIGHT + row++ * ROW_HEIGHT + mid });
      }
      for (const r of outputRows) {
        anchors.push({ handle: outputHandle(r.field), side: "right", y: HEADER_HEIGHT + row++ * ROW_HEIGHT + mid });
      }
      if (node.loop) row += node.loop.cap != null ? 2 : 1;
    }
    if (direction === "LR") {
      for (const label of branchLabels) {
        anchors.push({ handle: branchHandle(label), side: "right", y: HEADER_HEIGHT + row++ * ROW_HEIGHT + mid });
      }
    }
    return anchors;
  }
  if (n.type === "io") {
    if (!n.data.rowsVisible) return [];
    const { kind, ports } = n.data;
    // ioLabelH: the card's rows carry a column caption (grid parity with a group
    // card's IO columns — both grids are header + chrome + label + rows).
    const top = HEADER_HEIGHT + METRICS.ioRowsChrome + METRICS.ioLabelH;
    return ports.map((p, i) => ({
      handle: kind === "input" ? portHandle(p.id) : portTargetHandle(p.id),
      side: kind === "input" ? ("right" as const) : ("left" as const),
      y: top + i * ROW_HEIGHT + mid,
    }));
  }
  if (n.type === "group" && n.data.collapsed && n.data.ioRowsVisible) {
    const { inputs, outputs } = n.data;
    const top = HEADER_HEIGHT + METRICS.ioRowsChrome + METRICS.ioLabelH;
    const stagger = ioRowsCount(inputs.length, outputs.length) - outputs.length;
    return [
      ...inputs.map((p, i) => ({
        handle: portTargetHandle(p.id),
        side: "left" as const,
        y: top + i * ROW_HEIGHT + mid,
      })),
      ...outputs.map((p, j) => ({
        handle: portHandle(p.id),
        side: "right" as const,
        y: top + (stagger + j) * ROW_HEIGHT + mid,
      })),
    ];
  }
  return [];
}

// Control-flow edge kinds — these connect at a node's NODE_IN/NODE_OUT (the trunk),
// so they drive the icon connector stubs. data_flow lands on param rows; loop is a
// self-arc — neither implies a trunk in/out. Exported for layout.ts (straightness
// priorities + error-branch ordering work on control edges only).
export const CONTROL_KINDS: ReadonlySet<EdgeKind> = new Set<EdgeKind>(["sequential", "branch", "error", "end"]);

const NO_EXPANSION: ReadonlySet<string> = new Set();
const NO_CONDITIONS: Record<string, string> = {};

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
    }));
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
export function expandTargets(graph: RFGraph, focus: string | null): ReadonlySet<string> {
  if (!focus) return NO_EXPANSION;
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  // IO port id -> the node carrying its row (ioOwners — the same rule buildFlow
  // resolves edge handles with, so expansion and row emission can't disagree).
  const ioOwner = ioOwners(graph).ports;
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
  // Selecting a DATA EDGE (edge-click) expands exactly its two endpoints (owner-
  // aware), so the selected line lands row-to-row. The endpoints go straight into
  // the OUTPUT set — never into `foci`, or the data-flow scan below would expand
  // both endpoints' entire data neighborhoods. A control-edge focus expands
  // nothing (node-level endpoints already read fine at the trunk).
  const focusEdge = graph.edges.find((e) => e.id === focus);
  if (focusEdge) {
    if (focusEdge.kind !== "data_flow") return NO_EXPANSION;
    add(focusEdge.source);
    add(focusEdge.target);
    return out;
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
  return out;
}

/** Decorator-shell batch groups — batch boxes that must NEVER render. The contract
 *  models "batched X" as batch-wrapping-X; presentationally batch is a MODIFIER on
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

export function buildFlow(graph: RFGraph, view: BuildOptions): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));
  const expandedSet = view.expanded ?? NO_EXPANSION;

  // Decorator-shell batch groups are never rendered: their children reparent past
  // them and a suppressed host's representative skips them. A literal batch group
  // holding expanded item groups is NOT a shell — it renders and represents its
  // host (the single copy of the rule lives in shellBatchIds above).
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
  for (const e of graph.edges) {
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
  // The outputRows actually given to each emitted leaf — the landing ladder
  // (sourceHandleFor) checks "does this row render" against THIS list, never a
  // recomputed one (the silent-drop rule: never name a handle that doesn't render).
  const outputRowsByNode = new Map<string, OutputRow[]>();

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
      const outputRows = outputRowsFor(n, observedReadsByNode.get(n.id), graph.kind_output_types?.[n.kind]);
      outputRowsByNode.set(n.id, outputRows);
      const branchLabels = branchLabelsByNode.get(n.id) ?? [];
      const isExpanded = view.density === "compact" && expandedSet.has(n.id);
      // Same visibility rule as the edge pill: advanced always, else focus-expanded.
      const showsRows = view.density === "detailed" || isExpanded;
      const branchConditions = showsRows ? (branchConditionsByNode.get(n.id) ?? NO_CONDITIONS) : NO_CONDITIONS;
      const size = leafSize(n, view.density, view.direction, outputRows, branchLabels, isExpanded);
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
          outputRows,
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

    const sourceHandle = sourceHandleFor(e, source, rowsVisible(e.source), view.direction, outputRowsByNode, nodeById, ioNodeToOwner);
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
  outputRowsByNode: Map<string, OutputRow[]>,
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
    // node-level. "Renders" is checked against the node's ACTUAL outputRows —
    // never name a handle that doesn't render (React Flow drops it silently).
    const rows = outputRowsByNode.get(edge.source);
    const sub = edge.output_path?.[0];
    const keyField = sub != null ? `${edge.output_field}.${sub}` : null;
    if (keyField != null && rows?.some((r) => r.field === keyField)) {
      return outputHandle(keyField);
    }
    if (rows?.some((r) => r.field === edge.output_field)) {
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
    const p = bindingParam(node, edge.input_name);
    if (p) return paramHandle(p.name);
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

const DIMMED_EDGE_CLASS = "edge-dimmed";
const SHADOWED_EDGE_CLASS = "edge-shadowed";

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
    const stripped = stripDim(e.className);
    // A SELECTED shadowed structural edge renders full-strength: the build's
    // edge-shadowed class (35% opacity) would fight the bright+halo treatment.
    // Safe and reversible — this pass always re-runs on the pristine laid snapshot.
    const base = selected
      ? stripped
          .split(" ")
          .filter((c) => c && c !== SHADOWED_EDGE_CLASS)
          .join(" ")
      : stripped;
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
