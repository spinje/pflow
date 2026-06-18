import type { EdgeTypes } from "@xyflow/react";

import { DataEdge } from "./DataEdge";
import { GradientEdge } from "./GradientEdge";
import { LoopEdge } from "./LoopEdge";

// Keyed by the `type` flow.ts mints on edges: "gradient" for ALL control flow
// (sequential/branch/error/end), "data" for data-flow (lane geometry + lane-tinted
// body + endpoint node-color fades), "loop" for synthesized loop-back arcs. The
// components own their stroke COLOR — CSS keeps only dash patterns (a stroke rule
// would override the gradients, and a regression to a built-in type now renders
// INVISIBLY since CSS strokes nothing). Module-level so React Flow doesn't see a
// new object identity each render. Every registered component must be memo()'d
// (same rule as nodeTypes — skip unchanged edges on store churn).
export const edgeTypes: EdgeTypes = {
  gradient: GradientEdge,
  data: DataEdge,
  loop: LoopEdge,
};
