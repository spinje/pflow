// The post-layout edge decoration (graph/portSides.ts):
//  - assignDataRails: a data edge's middle rail centers in the clear gap between
//    its endpoint boxes, so a wrap-around never hugs a node border (the
//    stdout→inputs bug — the blind handle-midpoint landed ~10px above the card).

import { describe, expect, it } from "vitest";

import type { FlowEdge, FlowNode } from "./flow";
import { outputHandle, paramHandle } from "./handles";
import { assignBackRails, assignDataRails, assignLoopRails } from "./portSides";

// A positioned box — the rail passes only read position/size, never the data.
function box(id: string, x: number, opts: { parentId?: string; y?: number; height?: number } = {}): FlowNode {
  return {
    id,
    type: "node",
    position: { x, y: opts.y ?? 0 },
    width: 100,
    height: opts.height ?? 100,
    data: {} as never,
    ...(opts.parentId ? { parentId: opts.parentId } : {}),
  } as FlowNode;
}

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
    const nodes = [box("src", 100, { height: 100 }), box("dst", 100, { y: 215, height: 165 })];
    const [edge] = assignDataRails(nodes, [dataEdge("e", "src", "dst")]);
    expect(edge!.data?.railY).toBeCloseTo(157.5);
    expect(edge!.data?.railX).toBeUndefined(); // x-spans overlap — no horizontal hint
  });

  it("side-by-side nodes get railX at the middle of the horizontal gap", () => {
    const nodes = [box("src", 0), box("dst", 300)];
    const [edge] = assignDataRails(nodes, [dataEdge("e", "src", "dst")]);
    expect(edge!.data?.railX).toBeCloseTo(200); // gap 100..300
    expect(edge!.data?.railY).toBeUndefined();
  });

  it("overlapping boxes get no hint; non-data edges untouched", () => {
    const nodes = [box("src", 100), box("dst", 120)];
    const [edge] = assignDataRails(nodes, [dataEdge("e", "src", "dst")]);
    expect(edge!.data?.railX).toBeUndefined();
    expect(edge!.data?.railY).toBeUndefined();
    const ctrl = { id: "c", source: "src", target: "dst", data: { kind: "sequential" } } as FlowEdge;
    expect(assignDataRails(nodes, [ctrl])[0]).toBe(ctrl);
  });
});


describe("assignLoopRails — the loop-back U gets a rail OUTSIDE its box", () => {
  // Without the rail, a self-loop's smoothstep midpoint == the handle axis → the
  // line runs straight back THROUGH the node. The rail is load-bearing.
  const loopEdge = (id: string, anchor: string): FlowEdge =>
    ({
      id,
      source: anchor,
      target: anchor,
      data: { kind: "loop", shadowed: false, from: anchor, to: anchor, defaultHidden: false },
    }) as FlowEdge;

  it("TD: railX sits right of the box; railY unset", () => {
    // box: x 100..200 (width 100)
    const [edge] = assignLoopRails([box("a", 100)], [loopEdge("l", "a")], "TD");
    expect(edge!.data!.railX).toBeGreaterThan(200);
    expect(edge!.data!.railY).toBeUndefined();
  });

  it("LR: railY sits above the box; railX unset", () => {
    const [edge] = assignLoopRails([box("a", 100, { y: 50 })], [loopEdge("l", "a")], "LR");
    expect(edge!.data!.railY).toBeLessThan(50);
    expect(edge!.data!.railX).toBeUndefined();
  });

  it("uses the ABSOLUTE box of a nested anchor (parent offsets applied)", () => {
    const parent = box("p", 500, { y: 300 });
    const child = box("a", 100, { parentId: "p" }); // absolute right edge = 500+100+100
    const [edge] = assignLoopRails([parent, child], [loopEdge("l", "a")], "TD");
    expect(edge!.data!.railX).toBeGreaterThan(700);
  });

  it("non-loop edges are untouched, identity preserved", () => {
    const seq = { id: "s", source: "a", target: "b", data: { kind: "sequential" } } as FlowEdge;
    const [out] = assignLoopRails([box("a", 100), box("b", 300)], [seq], "TD");
    expect(out).toBe(seq);
  });
});

describe("assignBackRails — a backward branch/error edge routes around both boxes", () => {
  // Without the rail, smoothstep's stock wrap U-turns at the default stub right at
  // the source handle — sibling loop-backs knot (the harness check-groups, LR).
  const branch = (id: string, source: string, target: string, lane?: number): FlowEdge =>
    ({
      id,
      source,
      target,
      data: { kind: "branch", shadowed: false, from: source, to: target, defaultHidden: false, ...(lane != null ? { lane } : {}) },
    }) as FlowEdge;

  it("LR: a backward branch gets a railY BELOW both boxes (the loop U owns above); lanes stagger", () => {
    // target behind the source: src box 400..500, tgt box 100..200, both y 0..100
    const nodes = [box("src", 400), box("tgt", 100)];
    const [e0] = assignBackRails(nodes, [branch("e0", "src", "tgt")], "LR");
    expect(e0!.data!.railY).toBeGreaterThan(100); // below both bottoms
    expect(e0!.data!.railX).toBeUndefined();
    const [e1] = assignBackRails(nodes, [branch("e1", "src", "tgt", 2)], "LR");
    expect(e1!.data!.railY).toBeGreaterThan(e0!.data!.railY!); // sibling fans apart
  });

  it("LR: a FORWARD branch is untouched (railCenter's near-source rail owns it)", () => {
    const nodes = [box("src", 100), box("tgt", 400)];
    const fwd = branch("f", "src", "tgt");
    expect(assignBackRails(nodes, [fwd], "LR")[0]).toBe(fwd);
  });

  it("TD: a backward branch gets a railX LEFT of both boxes (the loop rail owns the right)", () => {
    // target above the source: src box y 300..400, tgt box y 0..100
    const nodes = [box("src", 200, { y: 300 }), box("tgt", 400)];
    const [edge] = assignBackRails(nodes, [branch("e", "src", "tgt")], "TD");
    expect(edge!.data!.railX).toBeLessThan(200); // left of both lefts
    expect(edge!.data!.railY).toBeUndefined();
  });

  it("sequential and data edges are untouched, identity preserved", () => {
    const nodes = [box("src", 400), box("tgt", 100)];
    const seq = { id: "s", source: "src", target: "tgt", data: { kind: "sequential" } } as FlowEdge;
    const data = { id: "d", source: "src", target: "tgt", data: { kind: "data_flow" } } as FlowEdge;
    expect(assignBackRails(nodes, [seq], "LR")[0]).toBe(seq);
    expect(assignBackRails(nodes, [data], "LR")[0]).toBe(data);
  });
});
