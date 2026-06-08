// A decision node's fork outcomes as labeled source handles on the right border —
// the n8n-Switch pattern (which value goes where). Shown in BOTH densities, because
// a fork is structure, not advanced data detail. Each branch edge connects from its
// named handle (branchHandle(label)), so the line clearly leaves its own outcome.

import { Handle, Position } from "@xyflow/react";

import { branchHandle } from "../../graph/handles";

export function BranchPorts({ labels }: { labels: string[] }): JSX.Element | null {
  if (labels.length === 0) return null;
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
