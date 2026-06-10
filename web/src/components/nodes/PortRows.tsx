// ONE column of IO rows — the shared renderer for everywhere a workflow's
// inputs/outputs appear: the root IO card (IOCardNode), a collapsed group card's
// two-column area, and an expanded region's inputs sidebar / outputs strip
// (GroupNode). A row is individually clickable (click → focus just that port's
// connections) and carries per-row handles so binding lines land on the exact row.
//
// Handles follow the strict side convention (in-left / out-right, same as param/
// output rows): the RECEIVE handle (portTargetHandle) renders LEFT, the FEED handle
// (portHandle) RIGHT. BOTH always render — a handle an edge names but the node
// doesn't carry is SILENTLY dropped by React Flow (the recurring bug class), so
// attachment must never depend on per-location reasoning. `handles` names which
// roles carry edges at this location and only controls the DOT's visibility:
// a collapsed card's inner-scope edges are self-loop-dropped (only the outer role
// shows a dot), a region row bridges both scopes ("both"), a root card has only
// one scope (inputs feed, outputs receive).

import { Handle, Position } from "@xyflow/react";

import type { Port } from "../../graph/flow";
import { portHandle, portTargetHandle } from "../../graph/handles";
import { useInteraction } from "../interaction";

export type PortRowHandles = "receive" | "feed" | "both";

function rowTitle(port: Port): string {
  const type = port.dataType ? `: ${port.dataType}` : "";
  const required = port.required ? " (required)" : "";
  const description = port.description ? ` — ${port.description}` : "";
  return `${port.name}${type}${required}${description}`;
}

export function PortRows({
  ports,
  kind,
  handles,
  focusedPortId,
  label,
  stagger = false,
}: {
  ports: Port[];
  kind: "input" | "output";
  handles: PortRowHandles;
  focusedPortId: string | null;
  label?: string; // the small INPUTS/OUTPUTS column caption (two-column areas)
  // Outputs sit one row LOWER than inputs in a two-column area — ALWAYS, even at
  // equal counts (user decision 2026-06-10: the in→out diagonal IS the information).
  stagger?: boolean;
}): JSX.Element {
  const { focusPort } = useInteraction();
  const classes = ["io-col", `io-col-${kind}`];
  if (stagger) classes.push("stagger");
  return (
    <div className={classes.join(" ")}>
      {label && <div className="io-col-label">{label}</div>}
      {ports.map((port) => (
        <div
          key={port.id}
          className={`io-row${kind === "output" ? " io-row-out" : ""}${focusedPortId === port.id ? " focused" : ""}`}
          title={rowTitle(port)}
          onClick={(e) => {
            e.stopPropagation(); // row click drives port focus, not whole-node focus
            focusPort(port.id);
          }}
        >
          <Handle
            id={portTargetHandle(port.id)}
            type="target"
            position={Position.Left}
            className={`handle port-handle${handles === "feed" ? " quiet" : ""}`}
          />
          <span className="io-name">{port.name}</span>
          {port.required && <span className="io-required">*</span>}
          {port.dataType && <span className="io-type">{port.dataType}</span>}
          <Handle
            id={portHandle(port.id)}
            type="source"
            position={Position.Right}
            className={`handle port-handle${handles === "receive" ? " quiet" : ""}`}
          />
        </div>
      ))}
    </div>
  );
}
