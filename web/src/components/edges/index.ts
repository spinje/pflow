import type { EdgeTypes } from "@xyflow/react";

import { GradientEdge } from "./GradientEdge";
import { LoopEdge } from "./LoopEdge";

// Keyed by the `type` flow.ts mints on edges: "gradient" for control flow
// (sequential/branch), "loop" for synthesized loop-back arcs. Data/error/end edges
// stay React Flow's built-in "default" (CSS-colored). Module-level so React Flow
// doesn't see a new object identity each render.
export const edgeTypes: EdgeTypes = {
  gradient: GradientEdge,
  loop: LoopEdge,
};
