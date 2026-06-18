// Client-side layout with ELK (the GraphModel carries no positions — the contract
// is presentation-free). ELK handles pflow's nested/compound containers natively,
// and running it in the browser means collapse/expand re-layouts instantly with no
// server round-trip. Direction is a render knob (LR default, TD toggle).
//
// dagre is the documented fallback if ELK's bundle ever bites (plan §Risks); it
// would be isolated to this module.

import type { ELK, ElkExtendedEdge, ElkNode } from "elkjs/lib/elk.bundled.js";

import { CONTROL_KINDS, type Direction, type FlowEdge, type FlowNode, rowAnchorsFor } from "./flow";
import { NODE_IN, NODE_OUT } from "./handles";
import { ICON_COL_X, ICON_ROW_Y, METRICS } from "./metrics";
import { alignSpine } from "./spine";

// ELK is ~80% of the app bundle, and layoutGraph is already async — so it loads as
// its own chunk on first layout instead of blocking the initial page. Cached: one
// load per session. A failed chunk load rejects layoutGraph, which the hook already
// surfaces as the error banner (never a stuck "Laying out…").
//
// It runs in a WEB WORKER when possible: a 100+-node layout costs ~150ms, and on the
// main thread that freezes the canvas mid-click (measured on a real 128-node
// workflow). elk-api is the thin shell; the heavy GWT build loads inside the worker
// (Vite's `?worker` import bundles it as its own asset). The bundled main-thread ELK
// is the fallback — node-env tests (no Worker) take it silently; a browser where
// worker construction fails takes it with a warning (a silent fallback would be an
// invisible perf regression). The probe layout fails fast at load time so a broken
// worker can't poison the first real layout.
let elkLoad: Promise<ELK> | null = null;
const loadElk = (): Promise<ELK> => (elkLoad ??= createElk());

// The bundled main-thread build, memoized separately: it is both the no-Worker
// fallback and the watchdog's rescue engine for a silent worker (below).
let bundledLoad: Promise<ELK> | null = null;
const loadBundledElk = (): Promise<ELK> =>
  (bundledLoad ??= import("elkjs/lib/elk.bundled.js").then((m) => new m.default()));

async function createElk(): Promise<ELK> {
  if (typeof Worker !== "undefined") {
    try {
      const [{ default: ElkApi }, { default: ElkWorker }] = await Promise.all([
        import("elkjs/lib/elk-api.js"),
        import("elkjs/lib/elk-worker.min.js?worker"),
      ]);
      const elk = new ElkApi({ workerFactory: () => new ElkWorker() }) as ELK;
      await elk.layout({ id: "probe", children: [{ id: "p", width: 1, height: 1 }], edges: [] });
      return elk;
    } catch (err) {
      console.warn("pflow UI: ELK worker unavailable — layouts will run on the main thread", err);
    }
  }
  return loadBundledElk();
}

// WATCHDOG: a worker layout that never answers must not hang the canvas. The
// elk-api PromisedWorker keeps its promise pending forever on an unanswered
// message, and a worker-side failure can be COMPLETELY silent (no reply, no
// `error`, no `messageerror` — observed in the wild on the 2026-06-10
// focus-deep-link hang; root cause environmental, never pinned — see
// task_168/implementation/handoff-focus-deeplink-worker-hang.md). After
// WORKER_TIMEOUT_MS of silence the layout re-runs on the bundled main-thread
// ELK (which provably handles real workflow graphs), the silent worker is
// terminated, and the session is DEMOTED to main-thread layouts — bounded
// badness: at most one stall per session, never a dead canvas. A main-thread
// layout cannot falsely trip the timer: while it computes, the main thread is
// blocked, so its result settles the race before the timer callback can run.
export const WORKER_TIMEOUT_MS = 10_000;

export async function layoutWithWatchdog(elk: ELK, root: ElkNode): Promise<ElkNode> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timedOut = new Promise<"timeout">((resolve) => {
    timer = setTimeout(() => resolve("timeout"), WORKER_TIMEOUT_MS);
  });
  try {
    const result = await Promise.race([elk.layout(root), timedOut]);
    if (result !== "timeout") return result;
  } finally {
    clearTimeout(timer);
  }
  console.warn(
    `pflow UI: ELK worker did not answer within ${WORKER_TIMEOUT_MS / 1000}s — ` +
      "re-running this layout on the main thread (worker demoted for this session)",
  );
  (elk as { terminateWorker?: () => void }).terminateWorker?.();
  elkLoad = loadBundledElk(); // demote: later layouts skip the silent worker
  const bundled = await elkLoad;
  return bundled.layout(root);
}

const ELK_DIRECTION: Record<Direction, string> = { LR: "RIGHT", TD: "DOWN" };

// Inner gutter between a region's frame and its body nodes — ELK padding (CSS
// renders no region padding; the body's position is ELK's). A flat 16 read cramped
// (user-caught 2026-06-15): body nodes hugged the header divider, the right edge,
// and the bottom. The TOP carries EXTRA because every node floats a NameLabel ~20px
// ABOVE its top border (7px offset + the 13px label box — WorkflowNode/index.css);
// ELK doesn't know it exists, so without the extra the first node's label collides
// with the header divider. These same gutters drive the nodeSize.minimum math below,
// so a tall inputs sidebar still can't overflow — keep them the single source.
// Per-side inner gutter between a region's frame and its body nodes — ELK padding
// (CSS renders no region padding; the body's position is ELK's). A flat 16 read
// cramped (user-caught 2026-06-15). The TOP holds the floating NameLabel (~20px
// above each node's top border — WorkflowNode/index.css) in its upper portion, so
// its CLEAR space reads ~20px less than the number. LEFT/BOTTOM run more generous
// than TOP/RIGHT (user-tuned). These same gutters drive the nodeSize.minimum math
// below, so a tall inputs sidebar still can't overflow — keep them the single source.
const REGION_TOP = 32; // header divider → first node
const REGION_LEFT = 48; // inputs sidebar (or bare left border) → body
const REGION_BOTTOM = 48; // body → outputs strip (or bare bottom border)
// Extra breathing room between the inputs SIDEBAR and the body's first node (on top of
// REGION_LEFT) — applies ONLY when an inputs sidebar is shown (user-tuned 2026-06-17).
const IO_BODY_GAP = 80;
// body → right border. Matched to the LEFT breathing gap (REGION_LEFT + IO_BODY_GAP) so
// an inputs region's body sits with SYMMETRIC left/right margins — the right edge
// mirrors the sidebar→body gap (user-tuned 2026-06-17).
const REGION_RIGHT = REGION_LEFT + IO_BODY_GAP;

/** Region LEFT padding: inputs sidebar + gutter (+ breathing room) when the region
 *  shows an inputs sidebar, else the bare-border gutter. SINGLE SOURCE for groupPadding
 *  (the ELK reservation), the minW clamp, AND the compactScopes de-center target — they
 *  MUST agree or the body lands off the gutter. */
function regionPadLeft(node: FlowNode): number {
  return node.type === "group" && node.data.ioRowsVisible && node.data.inputs.length > 0
    ? METRICS.ioSidebarW + REGION_LEFT + IO_BODY_GAP
    : REGION_LEFT;
}

// Region padding reserves room for the chrome GroupNode draws around the body:
// the header (always), the inputs SIDEBAR on the left and the outputs strip at the
// bottom (when the group renders its IO rows) — so the body's first layer lays out
// BESIDE the sidebar, not below it, and nothing overlaps the strip.
function groupPadding(node: FlowNode): string {
  const left = regionPadLeft(node);
  let bottom = REGION_BOTTOM;
  if (node.type === "group" && node.data.ioRowsVisible && node.data.outputs.length > 0) {
    bottom = METRICS.ioLabelH + node.data.outputs.length * METRICS.rowH + REGION_BOTTOM;
  }
  return `[top=${METRICS.groupHeaderH + REGION_TOP},left=${left},bottom=${bottom},right=${REGION_RIGHT}]`;
}

// Port ids for the TD icon-column ports (one pair per leaf node). Only minted
// inside this module — ELK-internal, never rendered.
const portIn = (id: string): string => `${id}::in`;
const portOut = (id: string): string => `${id}::out`;

/** Run ELK over the flow nodes/edges and return them with positions + final box
 *  sizes. Child positions come back relative to their parent — exactly React
 *  Flow's parentId convention. */
export async function layoutGraph(nodes: FlowNode[], edges: FlowEdge[], direction: Direction): Promise<FlowNode[]> {
  if (nodes.length === 0) return nodes;
  const elk = await loadElk();

  // Incoming CONTROL kinds per rendered target — drives the error-branch ordering
  // below (a node reached ONLY via an error edge is an error handler).
  const inKinds = new Map<string, Set<string>>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    const kind = e.data?.kind;
    if (!kind || kind === "loop" || !CONTROL_KINDS.has(kind)) continue;
    (inKinds.get(e.target) ?? inKinds.set(e.target, new Set()).get(e.target)!).add(kind);
  }
  // Error handlers order LAST among their siblings (the user-decided policy): the
  // happy path keeps the leftmost, straight-trunk column; error branches fan right.
  // considerModelOrder (below) makes ELK respect this list order.
  const isErrorOnly = (id: string): boolean => {
    const kinds = inKinds.get(id);
    return !!kinds && kinds.has("error") && !kinds.has("sequential") && !kinds.has("branch");
  };

  // A fork's targets order by their BRANCH-EDGE order — the code's if/elif/else
  // chain order, carried by contract edge order — so the FIRST condition lands
  // leftmost (TD) / topmost (LR). Steps-declaration order is irrelevant to how a
  // fork reads (user-decided 2026-06-10); the spatial ordinal labels then match
  // the code's reading order by construction. First branch in-edge wins per target.
  const branchOrder = new Map<string, { source: string; rank: number }>();
  {
    const rankBySource = new Map<string, number>();
    for (const e of edges) {
      if (e.source === e.target || e.data?.kind !== "branch") continue;
      const rank = rankBySource.get(e.source) ?? 0;
      rankBySource.set(e.source, rank + 1);
      if (!branchOrder.has(e.target)) branchOrder.set(e.target, { source: e.source, rank });
    }
  }

  const childrenByParent = new Map<string | undefined, FlowNode[]>();
  for (const node of nodes) {
    const key = node.parentId ?? undefined;
    const list = childrenByParent.get(key) ?? [];
    list.push(node);
    childrenByParent.set(key, list);
  }
  for (const [key, list] of childrenByParent) {
    const sorted = orderForkSiblings(list, branchOrder);
    childrenByParent.set(key, [...sorted.filter((n) => !isErrorOnly(n.id)), ...sorted.filter((n) => isErrorOnly(n.id))]);
  }

  // The layered + wrapping + spacing options. Applied to root AND to EVERY composite
  // (group) — ELK does not propagate these into nested subgraphs, so a long chain
  // inside a sub-workflow only wraps if its own container carries them too.
  const layeredOptions: Record<string, string> = {
    "elk.algorithm": "layered",
    "elk.direction": ELK_DIRECTION[direction],
    // Lets edges declared at the root connect nodes nested in different groups.
    "elk.hierarchyHandling": "INCLUDE_CHILDREN",
    // No width-cutoff wrapping (that folds a chain at arbitrary points and sweeps
    // edges back across the canvas). The honest model, like n8n: a sequence flows
    // in one direction; genuinely independent branches fan out on their own (ELK
    // stacks sibling targets across the cross-axis). A linear pipeline IS a line.
    // TD runs tighter between layers (rail close under the source,
    // short drops into the next row); LR keeps the wider gap that suits wide cards.
    "elk.layered.spacing.nodeNodeBetweenLayers": direction === "TD" ? "80" : "140",
    "elk.spacing.nodeNode": "80",
    "elk.spacing.edgeNode": "32",
    "elk.layered.spacing.edgeEdgeBetweenLayers": "20",
    "elk.spacing.componentComponent": "80",
    "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    // Siblings keep the input (model) order — deterministic, and the error-handlers-
    // last partition above becomes "error branches fan out rightmost". NOTE: this is
    // the ONLY model-order option that survives INCLUDE_CHILDREN — every
    // considerModelOrder.strategy crashes elkjs on a cross-hierarchy edge
    // ("Cannot read properties of undefined (reading 'a')", bisected 2026-06-09).
    "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
  };

  // Card nodes declare FIXED control ports on the ICON LINE — TD: the icon column
  // (ICON_COL_X), LR: the icon row (ICON_ROW_Y; user-decided 2026-06-10). The
  // control handles render there, NOT at the node center — without ports ELK
  // aligns box centers, so every chain/merge jogs by the cards' height/width
  // difference. Port-aware NETWORK_SIMPLEX aligns the icon line itself: chains
  // and end-sinks go dead straight, exactly one branch of a fork/merge continues
  // the trunk (the rounded-orthogonal pattern), and in LR the headers of different-height
  // cards sit on ONE line with the bodies hanging below. LR ROW handles get
  // their own fixed ports too (`rowPorts`) so binding bundles align row-to-row.
  const portable = new Set<string>();
  for (const node of nodes) {
    // Leaves, IO cards AND collapsed groups: all three render the same card
    // anatomy with control handles on the icon LINE — TD: the icon column
    // (ICON_COL_X), LR: the icon row (ICON_ROW_Y, the header's center; user-
    // decided 2026-06-10 so the trunk passes straight THROUGH the node, in left /
    // out right at the same height). Without the ports ELK aligns box centers and
    // the trunk jogs at every height difference. EXPANDED groups render their
    // handles on the icon line too (the trunk flows into the region's tile),
    // but get NO ELK port: a port on a COMPOUND node crashes elkjs under
    // INCLUDE_CHILDREN when an edge references it ("NEdge must have a source
    // and target NNode specified" — found in-browser 2026-06-10, same crash
    // family as considerModelOrder). ELK anchors region edges at the border
    // default; smoothstep absorbs the offset to the rendered handle.
    if (node.type === "node" || node.type === "io" || (node.type === "group" && node.data.collapsed)) portable.add(node.id);
  }

  // LR: row-bearing nodes (visible param/output/branch/IO rows) declare FIXED ports
  // at each row handle's exact (side, y) — flow.ts rowAnchorsFor owns the y math.
  // Port-aware NETWORK_SIMPLEX then aligns ROW-to-ROW, so a bundle of bindings
  // between two cards runs dead straight instead of jogging by the cards' grid
  // offset (measured: a constant 52px on run-from-plan, 2026-06-10). Expanded
  // regions return no anchors (the compound-port crash, same rule as TD).
  const rowPorts = new Map<string, Map<string, { side: "left" | "right"; y: number }>>();
  if (direction === "LR") {
    for (const node of nodes) {
      const anchors = rowAnchorsFor(node);
      if (anchors.length > 0) {
        rowPorts.set(node.id, new Map(anchors.map((a) => [a.handle, { side: a.side, y: a.y }])));
      }
    }
  }
  const rowPortId = (nodeId: string, handle: string): string => `${nodeId}::h:${handle}`;
  const rowPortFor = (nodeId: string, handle: string | null | undefined): string | null =>
    handle != null && rowPorts.get(nodeId)?.has(handle) ? rowPortId(nodeId, handle) : null;

  const toElk = (node: FlowNode): ElkNode => {
    const children = childrenByParent.get(node.id) ?? [];
    const elkNode: ElkNode = { id: node.id, width: node.width ?? 200, height: node.height ?? 60 };
    // One port list per node: the control pair on the icon line (TD column /
    // LR row) plus, in LR, a port per visible row handle.
    const ports: NonNullable<ElkNode["ports"]> = [];
    if (portable.has(node.id)) {
      ports.push(
        direction === "TD"
          ? { id: portIn(node.id), x: ICON_COL_X, y: 0, width: 0, height: 0 }
          : { id: portIn(node.id), x: 0, y: ICON_ROW_Y, width: 0, height: 0 },
        direction === "TD"
          ? { id: portOut(node.id), x: ICON_COL_X, y: elkNode.height, width: 0, height: 0 }
          : { id: portOut(node.id), x: elkNode.width ?? 0, y: ICON_ROW_Y, width: 0, height: 0 },
      );
    }
    const anchors = rowPorts.get(node.id);
    if (anchors) {
      for (const [handle, a] of anchors) {
        ports.push({
          id: rowPortId(node.id, handle),
          x: a.side === "left" ? 0 : (elkNode.width ?? 0),
          y: a.y,
          width: 0,
          height: 0,
        });
      }
    }
    if (ports.length > 0) {
      elkNode.layoutOptions = { "elk.portConstraints": "FIXED_POS" };
      elkNode.ports = ports;
    }
    if (children.length > 0) {
      elkNode.children = children.map(toElk);
      elkNode.layoutOptions = { ...layeredOptions, "elk.padding": groupPadding(node) };
      // A region whose inputs sidebar is taller than its body would overflow —
      // clamp the region to fit the sidebar. GOTCHA (measured 2026-06-10): under
      // direction DOWN, elkjs applies nodeSize.minimum in its INTERNAL (transposed)
      // coordinates — pass (minH, minW) in TD, (minW, minH) in LR.
      if (node.type === "group" && node.data.ioRowsVisible && node.data.inputs.length > 0) {
        const minW = regionPadLeft(node) + 230 + REGION_RIGHT;
        const minH =
          METRICS.groupHeaderH + REGION_TOP + METRICS.ioLabelH + node.data.inputs.length * METRICS.rowH + REGION_BOTTOM +
          (node.data.outputs.length > 0 ? METRICS.ioLabelH + node.data.outputs.length * METRICS.rowH + REGION_BOTTOM : REGION_BOTTOM);
        elkNode.layoutOptions["elk.nodeSize.constraints"] = "MINIMUM_SIZE";
        elkNode.layoutOptions["elk.nodeSize.minimum"] =
          direction === "TD" ? `(${minH}, ${minW})` : `(${minW}, ${minH})`;
      }
    }
    return elkNode;
  };

  // The straight trunk: each target's FIRST incoming non-error control edge (model
  // order — the leftmost sibling after the error demotion) gets a straightness
  // priority, so NETWORK_SIMPLEX keeps THAT edge as the straight column and the
  // other branches pay the corner. Chains get it trivially (single in-edge).
  const straight = new Set<string>();
  const seenTarget = new Set<string>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    const kind = e.data?.kind;
    if (!kind || kind === "loop" || kind === "error" || !CONTROL_KINDS.has(kind)) continue;
    if (seenTarget.has(e.target)) continue;
    seenTarget.add(e.target);
    straight.add(e.id);
  }

  // Layout reflects ALL structure (control + data), even edges that render hidden
  // (beautiful mode's data-flow lines) — otherwise a node connected only by data
  // would float as a disconnected island. Only self-loops (the loop-back arcs,
  // drawn by LoopEdge) are excluded; ELK must not route a node to itself.
  // An endpoint whose rendered handle is the icon-column trunk (TD: NODE_IN/NODE_OUT
  // on a ported leaf) or a declared LR row port connects to the matching ELK port;
  // everything else stays node-level (ELK's default side-center anchor — what the
  // rendered node-level handles already match).
  const elkEdges: ElkExtendedEdge[] = edges
    .filter((edge) => edge.source !== edge.target)
    .map((edge) => {
      const source =
        edge.sourceHandle === NODE_OUT && portable.has(edge.source)
          ? portOut(edge.source)
          : (rowPortFor(edge.source, edge.sourceHandle) ?? edge.source);
      const target =
        edge.targetHandle === NODE_IN && portable.has(edge.target)
          ? portIn(edge.target)
          : (rowPortFor(edge.target, edge.targetHandle) ?? edge.target);
      // Row-to-row bindings ask for straightness too: the ports make alignment
      // POSSIBLE, the priority makes NETWORK_SIMPLEX actually pay for it (without
      // it ELK still aligns boxes and the bundle keeps the cards' chrome offset —
      // measured 11px in the alignment test). The control SPINE is the hard rule:
      // priorities are WEIGHTS, so a 13-binding bundle (13×5) out-votes a lone
      // trunk edge at 10 (measured: preflight sat 233px off the spine) — 100 puts
      // the trunk above any plausible bundle; bindings then align wherever the
      // grids allow (grid parity makes card↔card bundles straight ANYWAY).
      const rowToRow = source.includes("::h:") && target.includes("::h:");
      const priority = straight.has(edge.id) ? "100" : rowToRow ? "5" : null;
      return {
        id: edge.id,
        sources: [source],
        targets: [target],
        ...(priority ? { layoutOptions: { "elk.layered.priority.straightness": priority } } : {}),
      };
    });

  const root: ElkNode = {
    id: "root",
    layoutOptions: layeredOptions,
    children: (childrenByParent.get(undefined) ?? []).map(toElk),
    edges: elkEdges,
  };

  const laidOut = await layoutWithWatchdog(elk, root);

  const boxes = new Map<string, { x: number; y: number; width: number; height: number }>();
  const collect = (node: ElkNode): void => {
    boxes.set(node.id, { x: node.x ?? 0, y: node.y ?? 0, width: node.width ?? 0, height: node.height ?? 0 });
    node.children?.forEach(collect);
  };
  laidOut.children?.forEach(collect);

  const positioned = nodes.map((node) => {
    const box = boxes.get(node.id);
    if (!box) {
      // ELK should place every node it was given; a miss would silently pile the
      // node at the origin. Warn so the loss is observable rather than invisible.
      console.warn(`pflow UI: ELK did not place node ${node.id}`);
      return node;
    }
    return {
      ...node,
      position: { x: box.x, y: box.y },
      width: box.width,
      height: box.height,
      style: { ...node.style, width: box.width, height: box.height },
    };
  });

  // Expanded regions carry no ELK port (the compound crash above), so ELK anchors
  // their trunk edges at the box CENTER while the handles render on the icon line
  // — a chain through wide regions renders as an accumulating staircase. The
  // spine pass re-aligns each pure sequential chain's anchors to its head
  // (graph/spine.ts); running it HERE means the layout cache, camera anchoring
  // and the animation all see the aligned positions.
  return compactScopes(alignSpine(positioned, edges, direction), direction);
}

/** De-center expanded regions (TD only).
 *
 *  ELK cannot put a fixed port on a compound node (the INCLUDE_CHILDREN crash, see
 *  above), so it anchors an expanded region's trunk edge at the region's box CENTER,
 *  not the icon column where the handle renders. A narrow trunk node above a WIDE
 *  region is therefore centered OVER it — pushed right by ~half the region's width —
 *  and alignSpine then aligns the region to that pushed column, slamming its right edge
 *  into the parent border. Net: dead space on the left, content touching the right
 *  (measured on run-from-plan: execute-plan body 770px from its left border, only
 *  ~209px of it the inputs sidebar).
 *
 *  This pass removes the per-scope dead space AFTER alignSpine has straightened the
 *  trunk: per expanded-region scope (DEEPEST first, so a parent sees its child regions
 *  at their already-shrunk widths), shift every body child left so the leftmost sits at
 *  the region's configured left padding, then shrink the region to its content + right
 *  padding. The shift is UNIFORM per scope, so alignSpine's straightening is preserved;
 *  IO sidebar rows render via CSS (not child nodes), so they stay pinned at the border. */
function compactScopes(nodes: FlowNode[], direction: Direction): FlowNode[] {
  if (direction !== "TD") return nodes; // TD (the screenshot case) only
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const childrenByParent = new Map<string, FlowNode[]>();
  for (const n of nodes) {
    if (!n.parentId) continue;
    (childrenByParent.get(n.parentId) ?? childrenByParent.set(n.parentId, []).get(n.parentId)!).push(n);
  }
  const depthOf = (n: FlowNode): number => {
    let d = 0;
    for (let p = n.parentId; p; p = byId.get(p)?.parentId) d++;
    return d;
  };
  const regions = nodes
    .filter((n) => n.type === "group" && !n.data.collapsed && (childrenByParent.get(n.id)?.length ?? 0) > 0)
    .sort((a, b) => depthOf(b) - depthOf(a));

  const shiftById = new Map<string, number>(); // parent-relative x shift (negative = left)
  const widthById = new Map<string, number>();
  for (const region of regions) {
    const kids = childrenByParent.get(region.id)!;
    const padLeft = regionPadLeft(region);
    const minLeft = Math.min(...kids.map((k) => k.position.x));
    const shift = minLeft - padLeft; // dead space on the region's left
    if (shift <= 1) continue;
    for (const k of kids) shiftById.set(k.id, -shift);
    const maxRight = Math.max(...kids.map((k) => k.position.x - shift + (widthById.get(k.id) ?? k.width ?? 0)));
    widthById.set(region.id, maxRight + REGION_RIGHT);
  }
  if (shiftById.size === 0) return nodes;

  return nodes.map((n) => {
    const dx = shiftById.get(n.id);
    const w = widthById.get(n.id);
    if (dx === undefined && w === undefined) return n;
    return {
      ...n,
      position: dx !== undefined ? { x: n.position.x + dx, y: n.position.y } : n.position,
      ...(w !== undefined ? { width: w, style: { ...n.style, width: w } } : {}),
    };
  });
}

/** Reorder a sibling list so each fork's targets follow their branch-edge order
 *  (the code's if/elif/else chain order). Targets of one fork CLUSTER at the
 *  position of their first occurrence in the list, internally sorted by rank;
 *  every other sibling keeps its model-order position. Pure — unit-tested. */
export function orderForkSiblings(list: FlowNode[], branchOrder: Map<string, { source: string; rank: number }>): FlowNode[] {
  const anchor = new Map<string, number>();
  list.forEach((node, i) => {
    const branch = branchOrder.get(node.id);
    if (branch && !anchor.has(branch.source)) anchor.set(branch.source, i);
  });
  return list
    .map((node, i) => {
      const branch = branchOrder.get(node.id);
      return { node, primary: branch ? anchor.get(branch.source)! : i, secondary: branch ? branch.rank : 0, stable: i };
    })
    .sort((a, b) => a.primary - b.primary || a.secondary - b.secondary || a.stable - b.stable)
    .map((entry) => entry.node);
}
