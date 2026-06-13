// Handle id scheme. Every edge sets its source/target handle explicitly, so all
// handles carry ids (an edge with an unset handle would not connect once any
// id'd handle exists on a node). Node-level handles catch control-flow edges and
// data-flow edges that can't be attributed to a specific row (input_name=None is
// COMMON — see ui/CLAUDE.md H6); per-row handles let a ${ref} line land on its
// exact param row in the detailed view.
//
// CRITICAL: each handle id encodes a fixed React Flow TYPE (source feeds out, target
// receives in). An edge whose sourceHandle is a target-type id (or vice versa) is
// SILENTLY DROPPED by React Flow — this has been the recurring bug. `handleType` is
// the authoritative scheme; the invariant test asserts buildFlow never crosses it.

export const NODE_IN = "__in"; // target
export const NODE_OUT = "__out"; // source
// The ↻ loop-rule row on a looped leaf's expanded body — TARGET: the loop-back U's
// arrow lands here when the row renders ("iteration re-enters under this rule"),
// instead of NODE_IN. One row per node, so a constant id suffices.
export const LOOP_ROW = "loop:row";
// Per-chunk "cached prefix" rows on a prompt_cache consumer's expanded body —
// TARGET: each `## Cache` chunk's edge lands on its OWN row (without them the
// lines merged invisibly into the control trunk at NODE_IN — user-caught
// 2026-06-13). The key is the chunk's authored ref text rebuilt from the edge
// (`cacheChunkKey` in flow.ts — the parser enforces chunk name == var, so this
// IS the entry the author wrote in `prompt_cache:`).
const CACHE = "cache:";
export const cacheHandle = (chunkKey: string): string => CACHE + chunkKey;

// Prefixes — kept as constants so the constructors and `handleType` can't drift.
const PARAM = "p:"; // param row — TARGET (a node input slot, receives)
const OUTPUT = "o:"; // output field — SOURCE (a node output, feeds)
const BRANCH = "b:"; // decision fork outcome — SOURCE (feeds a labeled route)
// The trailing colons keep these disjoint — "io:" is NOT a prefix of "iot:"
// (`"iot:x".startsWith("io:")` is false), so handleType's branch order is
// irrelevant. Don't drop a colon: bare "io" WOULD prefix "iot" and silently
// mis-type every IO target handle as a source (→ React Flow drops the edge).
const PORT_SOURCE = "io:"; // workflow IO port — SOURCE (input → consumers, output → parent)
const PORT_TARGET = "iot:"; // workflow IO port — TARGET (input ← parent, output ← producer)
// IO rows follow the SAME strict side convention as param/output rows (user
// decision 2026-06-10: in-left/out-right beats the shortest path): the receive
// handle (iot:) renders LEFT, the feed handle (io:) renders RIGHT, everywhere a
// row renders (root IO card, collapsed group card, expanded region). Sides are
// structural now — IO rows sit ON the workflow node itself, so the old floating
// ports table's mirrored handles + post-layout side flipping (assignFacingSides)
// are gone with it. A wrap-around to reach a strict-side row is fine; its rail
// clears the endpoint nodes via the data-rail hint (assignDataRails), not by
// switching sides.

export const paramHandle = (name: string): string => PARAM + name;
export const outputHandle = (field: string): string => OUTPUT + field;
// Branch (fork) outputs: one labeled source handle per outcome on a decision node's
// border, shown in BOTH densities (a fork is structure, not advanced data detail).
export const branchHandle = (label: string): string => BRANCH + label;
// Workflow IO ports: each input/output is a ROW on the workflow's own node (the
// root IO card, a collapsed sub-workflow card, or an expanded region's IO area).
// A port bridges two scopes, so a row can carry BOTH handles: a SOURCE (feeds out —
// an input feeding consumers, an output feeding the parent) and a TARGET (receives
// in — an input bound from the parent, an output written by a producer). Each
// location renders only the handles whose edges can exist there (a collapsed card's
// inner-scope edges are self-loop-dropped, so its rows are single-handled).
export const portHandle = (ioNodeId: string): string => PORT_SOURCE + ioNodeId;
export const portTargetHandle = (ioNodeId: string): string => PORT_TARGET + ioNodeId;

/** The React Flow handle type a handle id denotes. The contract every edge must
 *  honor: sourceHandle resolves to "source", targetHandle to "target". Throws on an
 *  unknown id so a new handle scheme can't slip past the invariant test untyped. */
export function handleType(handleId: string): "source" | "target" {
  if (
    handleId === NODE_IN ||
    handleId === LOOP_ROW ||
    handleId.startsWith(CACHE) ||
    handleId.startsWith(PARAM) ||
    handleId.startsWith(PORT_TARGET)
  ) {
    return "target";
  }
  if (handleId === NODE_OUT || handleId.startsWith(OUTPUT) || handleId.startsWith(BRANCH) || handleId.startsWith(PORT_SOURCE)) {
    return "source";
  }
  throw new Error(`unknown handle scheme: ${handleId}`);
}
