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
import { stripMarkdown } from "../../utils/format";
import { useHoverMarks, useInteraction } from "../interaction";

export type PortRowHandles = "receive" | "feed" | "both";

function rowTitle(port: Port): string {
  const type = port.dataType ? `: ${port.dataType}` : "";
  const required = port.required ? " (required)" : "";
  // Only the description is prose — tooltips can't render markdown, so its
  // markers strip; name/type/required are not prose and stay verbatim.
  const description = port.description ? ` — ${stripMarkdown(port.description)}` : "";
  return `${port.name}${type}${required}${description}`;
}

export function PortRows({
  ports,
  kind,
  handles,
  ownerId,
  focusedPortId,
  label,
  staggerRows = 0,
}: {
  ports: Port[];
  kind: "input" | "output";
  handles: PortRowHandles;
  // The flat id of the node these rows render ON (io card / group) — the id the
  // rows' edges anchor to; row hover marks that anchor's touch set.
  ownerId: string;
  focusedPortId: string | null;
  label?: string; // the small INPUTS/OUTPUTS column caption (two-column areas)
  // Rows to push this column DOWN in a two-column area: outputs are BOTTOM-ANCHORED
  // (ioRowsCount − nOut, always ≥ 1 beside inputs — user decision 2026-06-10: the
  // top-left → bottom-right in→out diagonal IS the information; a fixed one-row
  // stagger left a 3-output column hugging the top of a 13-input card).
  staggerRows?: number;
}): JSX.Element {
  const { focusPort, hoverRow } = useInteraction();
  const hovered = useHoverMarks(); // a hovered panel chip lights its port's row
  // Text hugs its CONNECTION side (the leaf-row convention — a name sits beside
  // its dot, user decision 2026-06-12): alignment keys on which side carries
  // the LIVE handle, not on input/output kind. A root Inputs card FEEDS (dots
  // right) → right-aligned; a root Outputs card RECEIVES (dots left) →
  // left-aligned; two-column/region rows ("both") fall back to their column's
  // natural side (inputs left, outputs right — unchanged).
  const alignRight = handles === "feed" || (handles === "both" && kind === "output");
  const classes = ["io-col", `io-col-${kind}`, ...(alignRight ? ["io-col-right"] : [])];
  // The wired styling follows the SIDE this location presents (`handles`): a
  // collapsed card's output column shows the FEED side, so an output no caller
  // reads stays grey even though its inner producer edge exists.
  const isWired = (port: Port): boolean =>
    handles === "receive" ? port.receives : handles === "feed" ? port.feeds : port.receives || port.feeds;
  return (
    <div
      className={classes.join(" ")}
      style={staggerRows > 0 ? { marginTop: `calc(${staggerRows} * var(--row-h))` } : undefined}
    >
      {label && <div className="io-col-label">{label}</div>}
      {ports.map((port) => (
        <div
          key={port.id}
          className={`io-row${isWired(port) ? " wired" : ""}${focusedPortId === port.id ? " focused" : ""}${hovered.has(port.id) ? " hover-mark" : ""}`}
          title={rowTitle(port)}
          onClick={(e) => {
            e.stopPropagation(); // row click drives port focus, not whole-node focus
            focusPort(port.id);
          }}
          // Row hover marks the nodes this port's edges touch (an io row carries
          // BOTH handles — edges may land on either role).
          onMouseEnter={() => hoverRow({ nodeId: ownerId, handles: [portHandle(port.id), portTargetHandle(port.id)] })}
          onMouseLeave={() => hoverRow(null)}
        >
          <Handle
            id={portTargetHandle(port.id)}
            type="target"
            position={Position.Left}
            className={`handle port-handle${handles === "feed" ? " quiet" : ""}`}
          />
          {/* Same text grammar as a leaf's output rows (`result: str` — the
              faint .row-type suffix): one vocabulary for "name: type" wherever
              rows render (user-caught divergence 2026-06-11). */}
          <span className="io-name">
            {port.name}
            {port.dataType && <span className="row-type">: {port.dataType}</span>}
          </span>
          {port.required && <span className="io-required">*</span>}
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
