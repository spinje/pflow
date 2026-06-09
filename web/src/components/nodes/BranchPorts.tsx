// A decision node's fork outcomes. In LR they render as labeled source handles on the
// right border — the n8n-Switch pattern (which value goes where), in both densities.
// In TD the forks instead fan from the icon column (via NODE_OUT) with their labels
// riding the edges (see flow.ts), like the references — so nothing is drawn here.

import { Handle, Position } from "@xyflow/react";

import type { Direction } from "../../graph/flow";
import { branchHandle } from "../../graph/handles";

export function BranchPorts({ labels, direction }: { labels: string[]; direction: Direction }): JSX.Element | null {
  if (labels.length === 0 || direction === "TD") return null;
  return (
    <div className="branch-ports">
      {labels.map((label) => (
        <div className="branch-port" key={label} title={`branch: ${label}`}>
          <span className="branch-label">{label}</span>
          <Handle id={branchHandle(label)} type="source" position={Position.Right} className="handle branch-handle" />
        </div>
      ))}
    </div>
  );
}
