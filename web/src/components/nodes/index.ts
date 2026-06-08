import type { NodeTypes } from "@xyflow/react";

import { CompactNode } from "./CompactNode";
import { DetailedNode } from "./DetailedNode";
import { EndNode } from "./EndNode";
import { GroupNode } from "./GroupNode";
import { PortsNode } from "./PortsNode";

// Keys match the `type` field minted in flow.ts (density "detailed"/"compact",
// plus "ports"/"group"/"end"). Defined once, module-level, so React Flow doesn't see
// a new object identity each render.
export const nodeTypes: NodeTypes = {
  detailed: DetailedNode,
  compact: CompactNode,
  ports: PortsNode,
  group: GroupNode,
  end: EndNode,
};
