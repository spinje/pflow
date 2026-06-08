import type { EdgeTypes } from "@xyflow/react";

import { LoopEdge } from "./LoopEdge";

// Keyed by the `type` flow.ts mints on synthesized loop edges. Module-level so
// React Flow doesn't see a new object identity each render.
export const edgeTypes: EdgeTypes = {
  loop: LoopEdge,
};
