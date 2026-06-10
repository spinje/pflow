// A workflow's inputs (or outputs) as ONE node with a row per port — the table-node
// pattern. Each row has its own handle (so each port keeps its own connection point)
// and is individually clickable (click a row → focus just that port's connections).
// Replaces the old one-node-per-port pills.

import { memo } from "react";
import { Handle, type NodeProps, Position } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { portHandle, portHandleLeft, portTargetHandle, portTargetHandleRight } from "../../graph/handles";
import { useInteraction } from "../interaction";

type PortsNodeType = Extract<FlowNode, { type: "ports" }>;

export const PortsNode = memo(function PortsNode({ data }: NodeProps<PortsNodeType>): JSX.Element {
  const { kind, ports, focusedPortId, dimmed, focused } = data;
  // Every port bridges two scopes, so each row carries BOTH handles: a TARGET that
  // RECEIVES (an input bound from the parent, an output written by a producer) and a
  // SOURCE that FEEDS (an input feeding consumers, an output feeding the parent).
  // A row in a vertical table ALWAYS connects SIDEWAYS — same rule as the advanced
  // param/output rows. Direction moves the trunk, not a row's connection point: the
  // old TD top/bottom row handles rendered as floating dots BETWEEN rows, and edges
  // dove into the middle of the stack (user-caught, 2026-06-09). The `kind` only
  // labels the header.
  const targetPos = Position.Left;
  const sourcePos = Position.Right;

  const { focusPort } = useInteraction();
  const classes = ["ports", `ports-${kind}`];
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");

  return (
    <div className={classes.join(" ")}>
      <div className="ports-header">{kind === "input" ? "Inputs" : "Outputs"}</div>
      <div className="ports-rows">
        {ports.map((port) => (
          <div
            key={port.id}
            className={`ports-row${focusedPortId === port.id ? " focused" : ""}`}
            title={`${port.name}${port.dataType ? `: ${port.dataType}` : ""}${port.required ? " (required)" : ""}`}
            onClick={(e) => {
              e.stopPropagation(); // row click drives port focus, not whole-node focus
              focusPort(port.id);
            }}
          >
            {/* Four handles per row: the BASE pair (target=left, source=right) plus
                the MIRRORED pair stacked on the opposite dots. buildFlow assigns base
                sides; the post-layout assignPortSides pass flips an edge to the
                mirrored id when its peer sits on the other side, so a binding never
                wraps around the node. Mirrors share the dots' exact positions — no
                visual change, and nothing moves on a direction flip (no re-measure). */}
            <Handle id={portTargetHandle(port.id)} type="target" position={targetPos} className="handle port-handle" />
            <Handle id={portHandleLeft(port.id)} type="source" position={targetPos} className="handle port-handle" />
            <span className="ports-name">{port.name}</span>
            {port.required && <span className="ports-required">*</span>}
            <Handle id={portHandle(port.id)} type="source" position={sourcePos} className="handle port-handle" />
            <Handle id={portTargetHandleRight(port.id)} type="target" position={sourcePos} className="handle port-handle" />
          </div>
        ))}
      </div>
    </div>
  );
});
