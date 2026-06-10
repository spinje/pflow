// A decision node's fork outcomes. In LR they render as labeled source handles on the
// right border — the n8n-Switch pattern (which value goes where), in both densities.
// In TD the forks instead fan from the icon column (via NODE_OUT) with their labels
// riding the edges (see flow.ts), like the references — so nothing is drawn here.

import { Handle, Position } from "@xyflow/react";

import type { Direction } from "../../graph/flow";
import { branchHandle } from "../../graph/handles";

export function BranchPorts({
  labels,
  conditions,
  direction,
}: {
  labels: string[];
  conditions?: Record<string, string>;
  direction: Direction;
}): JSX.Element | null {
  if (labels.length === 0 || direction === "TD") return null;
  return (
    <div className="branch-ports">
      {labels.map((label) => {
        // The condition selecting this outcome, on its row — the row is the
        // condition's home in LR (flow.ts populates LeafData.branchConditions only
        // when the rows show it: advanced / focus-expanded). Truncation is CSS
        // ellipsis; the full text rides the title + the read panel's table.
        const cond = conditions?.[label];
        return (
          <div className="branch-port" key={label} title={`branch: ${label}`}>
            {cond && (
              <span className="branch-cond" title={cond}>
                {cond}
              </span>
            )}
            <span className="branch-label">{label}</span>
            <Handle id={branchHandle(label)} type="source" position={Position.Right} className="handle branch-handle" />
          </div>
        );
      })}
    </div>
  );
}
