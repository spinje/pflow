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

/** The React Flow handle type a handle id denotes. The contract every edge must
 *  honor: sourceHandle resolves to "source", targetHandle to "target". Throws on an
 *  unknown id so a new handle scheme can't slip past the invariant test untyped. */
export function handleType(handleId: string): "source" | "target" {
  if (handleId === NODE_IN || handleId.startsWith(PARAM) || handleId.startsWith(PORT_TARGET)) {
    return "target";
  }
  if (
    handleId === NODE_OUT ||
    handleId.startsWith(OUTPUT) ||
    handleId.startsWith(BRANCH) ||
    handleId.startsWith(PORT_SOURCE)
  ) {
    return "source";
  }
  throw new Error(`unknown handle scheme: ${handleId}`);
}
