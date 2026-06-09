// A workflow's inputs (or outputs) as ONE node with a row per port — the table-node
// pattern. Each row has its own handle (so each port keeps its own connection point)
// and is individually clickable (click a row → focus just that port's connections).
// Replaces the old one-node-per-port pills.

import { memo } from "react";
import { Handle, type NodeProps, Position } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { portHandle, portTargetHandle } from "../../graph/handles";
import { useInteraction } from "../interaction";

type PortsNodeType = Extract<FlowNode, { type: "ports" }>;

export const PortsNode = memo(function PortsNode({ data }: NodeProps<PortsNodeType>): JSX.Element {
  const { kind, ports, direction, focusedPortId, dimmed, focused } = data;
  // Every port bridges two scopes, so each row carries BOTH handles: a TARGET that
  // RECEIVES (left/top — an input bound from the parent, an output written by a
  // producer) and a SOURCE that FEEDS (right/bottom — an input feeding consumers, an
  // output feeding the parent). The `kind` only labels the header.
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const sourcePos = direction === "LR" ? Position.Right : Position.Bottom;

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
            <Handle id={portTargetHandle(port.id)} type="target" position={targetPos} className="handle port-handle" />
            <span className="ports-name">{port.name}</span>
            {port.required && <span className="ports-required">*</span>}
            <Handle id={portHandle(port.id)} type="source" position={sourcePos} className="handle port-handle" />
          </div>
        ))}
      </div>
    </div>
  );
});
