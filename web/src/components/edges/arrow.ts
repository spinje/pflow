// The app draws NO arrowheads (clean lines into borders) — loop-backs are the one
// deliberate exception (user decision 2026-06-10): a loop-back is the only edge
// whose direction the layout doesn't imply, so its re-entry point carries a small
// arrow. Drawn as a polygon (themable via fill — RF's marker objects take only
// literal colors). Points INTO the box along the final approach: down through the
// TOP in TD, leftward through the RIGHT side, rightward through the LEFT side.
// Shared by LoopEdge (the LoopSpec self-loop) and GradientEdge (the backward
// sequential loop-back — a control cycle with no LoopSpec).

import { Position } from "@xyflow/react";

export function arrowPoints(x: number, y: number, into: Position): string {
  const w = 5; // half-width of the arrow base
  const len = 9;
  if (into === Position.Top) return `${x - w},${y - len} ${x + w},${y - len} ${x},${y}`;
  if (into === Position.Right) return `${x + len},${y - w} ${x + len},${y + w} ${x},${y}`;
  return `${x - len},${y - w} ${x - len},${y + w} ${x},${y}`;
}
