import type { NodeTypes } from "@xyflow/react";

import { EndNode } from "./EndNode";
import { GroupNode } from "./GroupNode";
import { PortsNode } from "./PortsNode";
import { WorkflowNode } from "./WorkflowNode";

// Keys match the `type` field minted in flow.ts. One leaf node type ("node") at two
// densities (density rides in data), plus "ports"/"group"/"end". Defined once,
// module-level, so React Flow doesn't see a new object identity each render.
// Every registered component must be memo()'d: applyFocus preserves object identity
// for unchanged nodes, so memo lets React Flow skip them on pan/zoom/store churn.
export const nodeTypes: NodeTypes = {
  node: WorkflowNode,
  ports: PortsNode,
  group: GroupNode,
  end: EndNode,
};
