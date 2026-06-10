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
// Mirrored-SIDE variants of the two port handles ("iotr:"/"iol:" stay disjoint from
// "iot:"/"io:" thanks to the trailing colons). A ports ROW renders all four; buildFlow
// always assigns the BASE side (target=left, source=right) because positions don't
// exist yet — the post-layout `assignPortSides` pass (graph/portSides.ts) flips an
// edge to the mirrored side when its peer clearly sits on the other side of the
// ports node, so a binding never wraps around the node (wrap-arounds crossed each
// other; user-caught 2026-06-09).
const PORT_TARGET_R = "iotr:"; // port target, RIGHT side (receives from a peer to the right)
const PORT_SOURCE_L = "iol:"; // port source, LEFT side (feeds a peer to the left)
// NOTE: ONLY ports rows have mirrored sides. Param/output rows stay strict
// left-in/right-out (user decision 2026-06-10: the in/out side convention beats the
// shortest path; a ports row is a scope BRIDGE — both directions are its semantics).
// A wrap-around to reach a strict-side row is fine; its rail clears the endpoint
// nodes via the data-rail hint (assignDataRails), not by switching sides.

export const paramHandle = (name: string): string => PARAM + name;
export const outputHandle = (field: string): string => OUTPUT + field;
// Branch (fork) outputs: one labeled source handle per outcome on a decision node's
// border, shown in BOTH densities (a fork is structure, not advanced data detail).
export const branchHandle = (label: string): string => BRANCH + label;
// Workflow IO ports: each input/output is a ROW on a single Inputs/Outputs node.
// A port bridges two scopes, so each row has BOTH handles: a SOURCE (feeds out — an
// input feeding consumers, an output feeding the parent) and a TARGET (receives in —
// an input bound from the parent, an output written by a producer).
export const portHandle = (ioNodeId: string): string => PORT_SOURCE + ioNodeId;
export const portTargetHandle = (ioNodeId: string): string => PORT_TARGET + ioNodeId;
export const portHandleLeft = (ioNodeId: string): string => PORT_SOURCE_L + ioNodeId;
export const portTargetHandleRight = (ioNodeId: string): string => PORT_TARGET_R + ioNodeId;

// Helpers for the post-layout side flip (assignFacingSides): detect a base-side
// PORTS-row handle and swap its prefix for the mirrored side, keeping the io-node id
// intact. Base sides: target = LEFT, source = RIGHT; the pass flips an edge to the
// mirror when its peer sits on the other side of the ports node.
export const isPortTarget = (h: string): boolean => h.startsWith(PORT_TARGET);
export const isPortSource = (h: string): boolean => h.startsWith(PORT_SOURCE);
export const mirrorPortTarget = (h: string): string => PORT_TARGET_R + h.slice(PORT_TARGET.length);
export const mirrorPortSource = (h: string): string => PORT_SOURCE_L + h.slice(PORT_SOURCE.length);

/** The React Flow handle type a handle id denotes. The contract every edge must
 *  honor: sourceHandle resolves to "source", targetHandle to "target". Throws on an
 *  unknown id so a new handle scheme can't slip past the invariant test untyped. */
export function handleType(handleId: string): "source" | "target" {
  if (
    handleId === NODE_IN ||
    handleId === LOOP_ROW ||
    handleId.startsWith(PARAM) ||
    handleId.startsWith(PORT_TARGET) ||
    handleId.startsWith(PORT_TARGET_R)
  ) {
    return "target";
  }
  if (
    handleId === NODE_OUT ||
    handleId.startsWith(OUTPUT) ||
    handleId.startsWith(BRANCH) ||
    handleId.startsWith(PORT_SOURCE) ||
    handleId.startsWith(PORT_SOURCE_L)
  ) {
    return "source";
  }
  throw new Error(`unknown handle scheme: ${handleId}`);
}
