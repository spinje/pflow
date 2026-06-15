// The leaf-card ROW MODEL + node sizing. A card's body is rows: the left column
// (paramRowsFor — params, the cached prefix, per-ref sub-rows), the right column
// (outputRowsFor — authored shape ∪ observed reads), loop-rule rows, and the IO
// row areas on cards/groups. The lists assembled here are THE single source the
// render (WorkflowNode/GroupNode/IOCardNode), the height (leafSize), the LR ELK
// ports (rowAnchorsFor) and the edge-handle ladders (buildFlow) all consume, so
// render, size, ports and handles cannot drift.

import { branchHandle, LOOP_ROW, outputHandle, paramHandle, portHandle, portTargetHandle } from "./handles";
import { METRICS } from "./metrics";
import { EMPTY_READS, type FieldReadsView } from "./scan";
import type { Port } from "./io";
import type { Density, Direction, FlowNode } from "./flow";
import type { LoopSpec, RFNode, RFParam } from "../types";

// Size estimates feed ELK and are applied as the node's rendered box, so they
// must match what the components draw (the components fill width/height: 100%).
// Heights shared with CSS rules come from METRICS (single source — the stylesheet
// reads the same values as injected CSS vars); the widths/paddings below are
// TS-only (CSS doesn't pin them). Re-tune live against the real DOM if it drifts.
export const DETAILED_WIDTH = 320;
// MOCK trial (2026-06-11): 230 → 258 → 280 — longer compact cards (more room for
// the 2-line description; the name label above gains runway too). The collapsed
// container / IO cards grow in step (below) to keep their width lead over a
// plain step — the hierarchy must not invert.
export const COMPACT_WIDTH = 280;
export const HEADER_HEIGHT = METRICS.nodeHeaderH; // tile + small padding (both densities)
export const ROW_HEIGHT = METRICS.rowH;
export const ROW_PADDING = 14;
export const END_SIZE = 46;
// The root IO card with rows visible (single column, slightly wider than compact
// so long port names breathe). MOCK trial: 260 → 300, in step with COMPACT_WIDTH.
export const IO_CARD_WIDTH = 300;
// A collapsed group card showing its IO area sizes to CONTENT (MOCK, 2026-06-11 —
// replaced the fixed 380): wide enough that no row truncates, but never narrower
// than the plain collapsed card and never past the max. Mono rows make the
// estimate exact — counting characters IS measuring a fixed-advance font.
export const GROUP_IO_MAX_WIDTH = 480;
// 12px var(--mono) advance ≈ 0.6em. Verified against the real DOM via inspect.
const IO_CHAR_W = 7.2;
// Row chrome around the text: row side padding (8×2) + the required-star gap+glyph.
const IO_ROW_CHROME = 26;

/** Pixels one IO column needs so its longest `name: type *` row renders untruncated. */
function ioColNeed(ports: Port[]): number {
  if (ports.length === 0) return 0;
  const chars = Math.max(
    ...ports.map((p) => p.name.length + (p.dataType ? p.dataType.length + 2 : 0) + (p.required ? 2 : 0)),
  );
  return chars * IO_CHAR_W + IO_ROW_CHROME;
}

/** Width of a collapsed group card with IO rows: both columns' content + the
 *  column gap + the area's side padding, clamped to
 *  [COLLAPSED_GROUP_WIDTH, GROUP_IO_MAX_WIDTH] — "prefer the unexpanded card's
 *  width when possible" (user decision 2026-06-11). */
export function groupIoWidth(io: { inputs: Port[]; outputs: Port[] }): number {
  const inNeed = ioColNeed(io.inputs);
  const outNeed = ioColNeed(io.outputs);
  const gap = inNeed > 0 && outNeed > 0 ? 16 : 0;
  const padding = 12 + 4; // .io-rows side padding (6×2) + card border (2×2)
  const needed = Math.ceil(inNeed + outNeed + gap + padding);
  return Math.min(GROUP_IO_MAX_WIDTH, Math.max(COLLAPSED_GROUP_WIDTH, needed));
}
// The collapsed group renders as a leaf-anatomy CARD (GroupNode): compact height,
// slightly wider than a leaf so the count pill fits beside the titles.
// MOCK trial: 260 → 300, keeping the lead over COMPACT_WIDTH (280).
export const COLLAPSED_GROUP_WIDTH = 300;
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

/** Where the cached-prefix rows sit in a leaf body: immediately BEFORE the
 *  `prompt` param row — the real request order is system → cached prefix →
 *  prompt (a `system` param authored before `prompt` stays above for free).
 *  Shared by paramRowsFor and the ReadPanel so canvas and panel can't drift. */
export function cacheInsertIndex(params: RFNode["params"]): number {
  const i = params.findIndex((p) => p.name === "prompt");
  return i === -1 ? params.length : i;
}

// One per-ref binding sub-row, derived from a data edge (buildFlow's edge
// pass): `name` is the binding-level key when it differs from the parent
// param's name (a dict-key binding), null for an interpolated ref.
export type RefRow = { handle: string; name: string | null; ref: string };

// One left-column row on a leaf card. paramRowsFor assembles the full ordered
// list; "label" is the handle-less "cached prefix ×N" heading; "ref" rows are
// the per-ref landings (nested under their parent, except the flat
// single-chunk cache row, which carries its own name).
export type ParamRowItem =
  | { kind: "param"; param: RFParam }
  | { kind: "label"; text: string; count: number }
  | { kind: "ref"; handle: string; name: string | null; ref: string; nested: boolean };

/** Assemble a leaf's LEFT column: params in authored order, the cached-prefix
 *  group before `prompt`, and per-ref sub-rows under any param that receives
 *  TWO or more refs (one ref keeps landing on the param row itself — no
 *  sub-row noise on the common case). The cache group mirrors the same rule:
 *  one chunk is a flat row, several get a label row + nested rows. */
export function paramRowsFor(node: RFNode, refRows: ReadonlyMap<string, RefRow[]> | undefined): ParamRowItem[] {
  const rows: ParamRowItem[] = [];
  const cacheAt = cacheInsertIndex(node.params);
  const emitCache = (): void => {
    const chunks = refRows?.get("prompt_cache") ?? [];
    if (chunks.length === 1) {
      rows.push({ kind: "ref", ...chunks[0]!, name: "cached prefix", nested: false });
    } else if (chunks.length > 1) {
      rows.push({ kind: "label", text: "cached prefix", count: chunks.length });
      rows.push(...chunks.map((c): ParamRowItem => ({ kind: "ref", ...c, nested: true })));
    }
  };
  node.params.forEach((param, i) => {
    if (i === cacheAt) emitCache();
    rows.push({ kind: "param", param });
    const subs = refRows?.get(param.name) ?? [];
    if (subs.length >= 2) rows.push(...subs.map((s): ParamRowItem => ({ kind: "ref", ...s, nested: true })));
  });
  if (cacheAt >= node.params.length) emitCache();
  return rows;
}

// One BODY row on a leaf card — the WHOLE body as one ordered list (the nodeRows
// row model): the left column's ParamRowItems gain their target handle, output
// rows carry their source handle, and the ↻ loop-rule rows close the list. THE
// single list the render (WorkflowNode's switch), the height (leafSize), the LR
// ELK ports (rowAnchorsFor) and the edge-landing ladder (buildFlow's rowsByNode)
// all consume — the four consumers that previously mirrored this order by hand.
export type NodeRow =
  | { kind: "param"; param: RFParam; targetHandle: string } // paramHandle(param.name)
  | { kind: "label"; text: string; count: number } // handle-less heading ("cached prefix ×N")
  | { kind: "ref"; handle: string; name: string | null; ref: string; nested: boolean }
  | { kind: "output"; row: OutputRow; sourceHandle: string } // outputHandle(row.field)
  | { kind: "loop-condition"; loop: LoopSpec; targetHandle: string } // LOOP_ROW — the U's landing
  | { kind: "loop-cap"; loop: LoopSpec }; // no handle; present only when cap != null

/** Assemble a leaf's FULL body row list, in render order: the left column
 *  (paramRowsFor order) → output rows (outputRowsFor order) → the loop-condition
 *  row → the loop-cap row. Composes paramRowsFor/outputRowsFor — it does not
 *  replace them; their composition rules (and tests) are untouched. */
export function nodeRows(node: RFNode, paramRows: ParamRowItem[], outputRows: OutputRow[]): NodeRow[] {
  const rows: NodeRow[] = paramRows.map(
    (r): NodeRow => (r.kind === "param" ? { kind: "param", param: r.param, targetHandle: paramHandle(r.param.name) } : r),
  );
  for (const row of outputRows) rows.push({ kind: "output", row, sourceHandle: outputHandle(row.field) });
  // The ↻ loop-rule rows a looped leaf renders in its body (WorkflowNode): the
  // condition row (the U's landing) + a cap row when one is set.
  if (node.loop) {
    rows.push({ kind: "loop-condition", loop: node.loop, targetHandle: LOOP_ROW });
    if (node.loop.cap != null) rows.push({ kind: "loop-cap", loop: node.loop });
  }
  return rows;
}

export function leafSize(
  density: Density,
  direction: Direction,
  rows: NodeRow[],
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
  // The body row count IS nodeRows' length — every NodeRow draws one ROW_HEIGHT row.
  return { width, height: HEADER_HEIGHT + (rows.length + branchRows) * ROW_HEIGHT + ROW_PADDING };
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
    const { density, direction, rows, branchLabels, expanded } = n.data;
    const anchors: RowAnchor[] = [];
    let row = 0;
    if (density === "detailed" || expanded) {
      // The body in nodeRows order: EVERY row advances the counter; only rows
      // with an ELK-usable handle emit an anchor — a "label" row is handle-less,
      // and loop rows carry only the self-loop, which never enters ELK.
      for (const r of rows) {
        const y = HEADER_HEIGHT + row++ * ROW_HEIGHT + mid;
        if (r.kind === "param") anchors.push({ handle: r.targetHandle, side: "left", y });
        else if (r.kind === "ref") anchors.push({ handle: r.handle, side: "left", y });
        else if (r.kind === "output") anchors.push({ handle: r.sourceHandle, side: "right", y });
      }
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
