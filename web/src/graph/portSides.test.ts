// The post-layout edge decoration (graph/portSides.ts):
//  - assignFacingSides: PORTS-row edges attach on the side facing their peer (a
//    ports row is a scope bridge — both directions are its semantics). Param/output
//    rows are deliberately NOT flipped: inputs-left/outputs-right is the node-graph
//    convention (user decision 2026-06-10).
//  - assignDataRails: a data edge's middle rail centers in the clear gap between
//    its endpoint boxes, so a wrap-around never hugs a node border (the
//    stdout→inputs bug — the blind handle-midpoint landed ~10px above the card).

import { describe, expect, it } from "vitest";

import type { FlowEdge, FlowNode } from "./flow";
import {
  handleType,
  outputHandle,
  paramHandle,
  portHandle,
  portHandleLeft,
  portTargetHandle,
  portTargetHandleRight,
} from "./handles";
import { assignDataRails, assignFacingSides } from "./portSides";

function portsNode(id: string, x: number, opts: { parentId?: string; y?: number; height?: number } = {}): FlowNode {
  return {
    id,
    type: "ports",
    position: { x, y: opts.y ?? 0 },
    width: 100,
    height: opts.height ?? 100,
    data: {} as never,
    ...(opts.parentId ? { parentId: opts.parentId } : {}),
  } as FlowNode;
}

function bindingEdge(id: string, source: string, target: string): FlowEdge {
  return {
    id,
    source,
    target,
    sourceHandle: portHandle("out1"),
    targetHandle: portTargetHandle("in1"),
  } as FlowEdge;
}

describe("assignFacingSides — ports-row edges attach on the side facing the peer", () => {
  it("flips BOTH ends when the target node is clearly left of the source", () => {
    // source box 400..500, target box 100..200 → peer on the other side at both ends
    const nodes = [portsNode("src", 400), portsNode("dst", 100)];
    const [edge] = assignFacingSides(nodes, [bindingEdge("e", "src", "dst")]);
    expect(edge!.sourceHandle).toBe(portHandleLeft("out1")); // feeds from its LEFT
    expect(edge!.targetHandle).toBe(portTargetHandleRight("in1")); // receives on its RIGHT
    // the mirrored ids keep the correct React Flow types (the silent-drop class)
    expect(handleType(edge!.sourceHandle!)).toBe("source");
    expect(handleType(edge!.targetHandle!)).toBe("target");
  });

  it("keeps the base sides when the peer is clearly to the right", () => {
    const right = assignFacingSides([portsNode("src", 100), portsNode("dst", 400)], [bindingEdge("e", "src", "dst")]);
    expect(right[0]!.sourceHandle).toBe(portHandle("out1"));
    expect(right[0]!.targetHandle).toBe(portTargetHandle("in1"));
  });

  it("a vertically-stacked ports pair flips the TARGET to its right side (handle-x, not centers)", () => {
    // Same column (centers equal): the source ROW handle exits at the node's RIGHT
    // edge, so the line enters the target's right side instead of wrapping left.
    const nodes = [portsNode("src", 100), portsNode("dst", 100, { y: 300 })];
    const [edge] = assignFacingSides(nodes, [bindingEdge("e", "src", "dst")]);
    expect(edge!.targetHandle).toBe(portTargetHandleRight("in1"));
    expect(edge!.sourceHandle).toBe(portHandle("out1")); // entry is east of source center — stays right
  });

  it("param/output row handles are NEVER flipped — strict in-left/out-right", () => {
    const nodes = [portsNode("src", 400), portsNode("dst", 100)];
    const e = {
      id: "e",
      source: "src",
      target: "dst",
      sourceHandle: outputHandle("stdout"),
      targetHandle: paramHandle("inputs"),
    } as FlowEdge;
    expect(assignFacingSides(nodes, [e])[0]).toBe(e);
  });

  it("uses ABSOLUTE boxes (parent-relative positions accumulate)", () => {
    // dst sits at x=50 inside a group at x=500 → absolute box 550..650, right of src.
    const group = { id: "g", type: "group", position: { x: 500, y: 0 }, width: 300, data: {} as never } as FlowNode;
    const nodes = [portsNode("src", 400), group, portsNode("dst", 50, { parentId: "g" })];
    const [edge] = assignFacingSides(nodes, [bindingEdge("e", "src", "dst")]);
    expect(edge!.targetHandle).toBe(portTargetHandle("in1")); // peer is right — no flip
  });

  it("leaves non-row edges untouched", () => {
    const nodes = [portsNode("src", 400), portsNode("dst", 100)];
    const plain = { id: "e", source: "src", target: "dst", sourceHandle: "__out", targetHandle: "__in" } as FlowEdge;
    expect(assignFacingSides(nodes, [plain])[0]).toBe(plain);
  });
});

describe("assignDataRails — wrap rails center in the clear gap between endpoint boxes", () => {
  const dataEdge = (id: string, source: string, target: string): FlowEdge =>
    ({
      id,
      source,
      target,
      sourceHandle: outputHandle("stdout"),
      targetHandle: paramHandle("inputs"),
      data: { kind: "data_flow", shadowed: false, from: source, to: target, defaultHidden: false },
    }) as FlowEdge;

  it("stacked nodes get railY at the middle of the vertical gap (not the handle midpoint)", () => {
    // src box y 0..100, dst box y 215..380 → clear gap 100..215, center 157.5.
    // The blind handle-midpoint could land ~10px above the dst box (the bug).
    const nodes = [portsNode("src", 100, { height: 100 }), portsNode("dst", 100, { y: 215, height: 165 })];
    const [edge] = assignDataRails(nodes, [dataEdge("e", "src", "dst")]);
    expect(edge!.data?.railY).toBeCloseTo(157.5);
    expect(edge!.data?.railX).toBeUndefined(); // x-spans overlap — no horizontal hint
  });

  it("side-by-side nodes get railX at the middle of the horizontal gap", () => {
    const nodes = [portsNode("src", 0), portsNode("dst", 300)];
    const [edge] = assignDataRails(nodes, [dataEdge("e", "src", "dst")]);
    expect(edge!.data?.railX).toBeCloseTo(200); // gap 100..300
    expect(edge!.data?.railY).toBeUndefined();
  });

  it("overlapping boxes get no hint; non-data edges untouched", () => {
    const nodes = [portsNode("src", 100), portsNode("dst", 120)];
    const [edge] = assignDataRails(nodes, [dataEdge("e", "src", "dst")]);
    expect(edge!.data?.railX).toBeUndefined();
    expect(edge!.data?.railY).toBeUndefined();
    const ctrl = { id: "c", source: "src", target: "dst", data: { kind: "sequential" } } as FlowEdge;
    expect(assignDataRails(nodes, [ctrl])[0]).toBe(ctrl);
  });
});
