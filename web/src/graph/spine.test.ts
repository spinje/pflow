// alignSpine: a pure sequential chain follows its HEAD — port-less members
// (expanded regions, end dots) that ELK center-anchored off the icon line snap
// back onto the spine; forks/merges break chains; a shift that would crowd a
// sibling is skipped. The integration test at the bottom proves the pass is
// actually WIRED into layoutGraph (tested-but-unwired is the named trap).

import { describe, expect, it } from "vitest";

import { buildFlow, type FlowEdge, type FlowNode } from "./flow";
import { layoutGraph } from "./layout";
import { ICON_COL_X, ICON_ROW_Y } from "./metrics";
import { alignSpine, SPINE_CLEARANCE } from "./spine";
import type { EdgeKind, RFEdge, RFGraph, RFGroup, RFNode } from "../types";

// ---- pure-pass fixtures (already-laid-out flow nodes) ---------------------

function fnode(
  id: string,
  x: number,
  y: number,
  over: { type?: FlowNode["type"]; w?: number; h?: number; parent?: string } = {},
): FlowNode {
  return {
    id,
    type: over.type ?? "node",
    position: { x, y },
    width: over.w ?? 230,
    height: over.h ?? 68,
    ...(over.parent ? { parentId: over.parent } : {}),
    data: {},
  } as unknown as FlowNode;
}

function fedge(id: string, source: string, target: string, kind: string): FlowEdge {
  return { id, source, target, data: { kind } } as unknown as FlowEdge;
}

const anchorX = (nodes: FlowNode[], id: string): number => {
  const n = nodes.find((x) => x.id === id)!;
  return n.position.x + (n.type === "end" ? (n.width ?? 0) / 2 : ICON_COL_X);
};

describe("alignSpine — pure pass", () => {
  it("TD: a chain through a center-drifted region aligns every anchor to the head's", () => {
    // ELK center-anchored the port-less 600px region: its icon column sits ~250px
    // right of the head's. The tail leaf then followed the region's exit.
    const nodes = [
      fnode("head", 100, 0),
      fnode("region", 300, 200, { type: "group", w: 600, h: 400 }),
      fnode("tail", 350, 700),
    ];
    const edges = [fedge("e0", "head", "region", "sequential"), fedge("e1", "region", "tail", "sequential")];
    const out = alignSpine(nodes, edges, "TD");
    expect(anchorX(out, "region")).toBe(anchorX(out, "head"));
    expect(anchorX(out, "tail")).toBe(anchorX(out, "head"));
    // only x moves; layers (y) are ELK's
    expect(out.find((n) => n.id === "region")!.position.y).toBe(200);
  });

  it("TD: an end dot aligns its CENTER to the spine (its handle is side-centered)", () => {
    const nodes = [fnode("head", 100, 0), fnode("fin", 200, 200, { type: "end", w: 46, h: 46 })];
    const edges = [fedge("e0", "head", "fin", "end")];
    const out = alignSpine(nodes, edges, "TD");
    expect(anchorX(out, "fin")).toBe(anchorX(out, "head"));
    expect(out.find((n) => n.id === "fin")!.position.x).toBe(100 + ICON_COL_X - 23);
  });

  it("a fork breaks the chain: branch targets keep their fan-out positions", () => {
    const nodes = [
      fnode("a", 100, 0),
      fnode("dec", 300, 200), // drifted, but pure-linked from a
      fnode("t1", 100, 400),
      fnode("t2", 500, 400),
    ];
    const edges = [
      fedge("e0", "a", "dec", "sequential"),
      fedge("b1", "dec", "t1", "branch"),
      fedge("b2", "dec", "t2", "branch"),
    ];
    const out = alignSpine(nodes, edges, "TD");
    // the chain INTO the decision still aligns it …
    expect(anchorX(out, "dec")).toBe(anchorX(out, "a"));
    // … but its targets are NOT chain members (outDeg 2): untouched
    expect(out.find((n) => n.id === "t1")!.position.x).toBe(100);
    expect(out.find((n) => n.id === "t2")!.position.x).toBe(500);
  });

  it("a merge breaks the chain; the merge node heads its own downstream chain", () => {
    const nodes = [fnode("a", 100, 0), fnode("b", 500, 0), fnode("m", 280, 200), fnode("c", 350, 400)];
    const edges = [
      fedge("e0", "a", "m", "sequential"),
      fedge("e1", "b", "m", "sequential"),
      fedge("e2", "m", "c", "sequential"),
    ];
    const out = alignSpine(nodes, edges, "TD");
    expect(out.find((n) => n.id === "m")!.position.x).toBe(280); // inDeg 2: unmoved
    expect(anchorX(out, "c")).toBe(anchorX(out, "m")); // m heads the next chain
  });

  it("an error out-edge does NOT break the trunk through its node", () => {
    const nodes = [fnode("a", 100, 0), fnode("b", 300, 200), fnode("h", 600, 200)];
    const edges = [fedge("e0", "a", "b", "sequential"), fedge("err", "a", "h", "error")];
    const out = alignSpine(nodes, edges, "TD");
    expect(anchorX(out, "b")).toBe(anchorX(out, "a"));
    expect(out.find((n) => n.id === "h")!.position.x).toBe(600); // handler untouched
  });

  it("skips a member whose shift would crowd a sibling; later members still align", () => {
    const nodes = [
      fnode("head", 1000, 0),
      // aligning this 600px region needs x=1000 .. 1600 — "blocker" occupies it
      fnode("region", 300, 200, { type: "group", w: 600, h: 400 }),
      fnode("blocker", 1100, 250, { w: 230, h: 68 }),
      fnode("tail", 350, 700),
    ];
    const edges = [fedge("e0", "head", "region", "sequential"), fedge("e1", "region", "tail", "sequential")];
    const out = alignSpine(nodes, edges, "TD");
    expect(out.find((n) => n.id === "region")!.position.x).toBe(300); // skipped
    expect(anchorX(out, "tail")).toBe(anchorX(out, "head")); // still aligns
    // the guard really is the clearance band, not exact overlap
    expect(SPINE_CLEARANCE).toBeGreaterThan(0);
  });

  it("chains are per-scope: nested children align in RELATIVE coords; cross-scope edges form no link", () => {
    const nodes = [
      fnode("outer", 0, 0),
      fnode("region", 500, 200, { type: "group", w: 700, h: 600 }),
      fnode("inner1", 50, 100, { parent: "region" }),
      fnode("inner2", 300, 300, { parent: "region" }),
    ];
    const edges = [
      fedge("e0", "inner1", "inner2", "sequential"),
      // cross-scope (outer is root, inner1 is a child): never a chain link
      fedge("x0", "outer", "inner1", "sequential"),
    ];
    const out = alignSpine(nodes, edges, "TD");
    expect(anchorX(out, "inner2")).toBe(anchorX(out, "inner1"));
    expect(out.find((n) => n.id === "inner1")!.position.x).toBe(50); // x0 moved nothing
  });

  it("LR: aligns the icon ROW (y); end dots align their vertical center", () => {
    // Layers separate on x (LR's flow axis) like real ELK output — the clearance
    // guard must not see successive layers as crowding.
    const nodes = [
      fnode("head", 0, 100),
      fnode("region", 400, 300, { type: "group", w: 400, h: 500 }),
      fnode("fin", 900, 250, { type: "end", w: 46, h: 46 }),
    ];
    const edges = [fedge("e0", "head", "region", "sequential"), fedge("e1", "region", "fin", "end")];
    const out = alignSpine(nodes, edges, "LR");
    const region = out.find((n) => n.id === "region")!;
    const fin = out.find((n) => n.id === "fin")!;
    expect(region.position.y + ICON_ROW_Y).toBe(100 + ICON_ROW_Y);
    expect(fin.position.y + 23).toBe(100 + ICON_ROW_Y);
    expect(region.position.x).toBe(400); // LR shifts only y
  });

  it("an already-straight chain is a no-op that preserves node identity", () => {
    const nodes = [fnode("a", 100, 0), fnode("b", 100, 200), fnode("c", 100, 400)];
    const edges = [fedge("e0", "a", "b", "sequential"), fedge("e1", "b", "c", "sequential")];
    const out = alignSpine(nodes, edges, "TD");
    expect(out[0]).toBe(nodes[0]);
    expect(out[1]).toBe(nodes[1]);
    expect(out[2]).toBe(nodes[2]);
  });

  it("a pure sequential CYCLE terminates and aligns to one member", () => {
    const nodes = [fnode("a", 100, 0), fnode("b", 300, 200), fnode("c", 500, 400)];
    const edges = [
      fedge("e0", "a", "b", "sequential"),
      fedge("e1", "b", "c", "sequential"),
      fedge("e2", "c", "a", "sequential"),
    ];
    const out = alignSpine(nodes, edges, "TD");
    const xs = new Set(out.map((n) => anchorX(out, n.id)));
    expect(xs.size).toBe(1);
  });

  it("duplicate flow edges between one pair count as ONE connection (degrees stay pure)", () => {
    const nodes = [fnode("a", 100, 0), fnode("b", 300, 200)];
    const edges = [fedge("e0", "a", "b", "sequential"), fedge("e0b", "a", "b", "sequential")];
    const out = alignSpine(nodes, edges, "TD");
    expect(anchorX(out, "b")).toBe(anchorX(out, "a"));
  });
});

// ---- integration: the pass is wired into layoutGraph ----------------------

function rfnode(id: string, over: Partial<RFNode> = {}): RFNode {
  return {
    id,
    ref: { node_id: id, ancestor_path: [], port: null },
    kind: "shell",
    purpose: "",
    params: [],
    io: null,
    loop: null,
    batch: null,
    parent: null,
    source: null,
    is_decision: false,
    is_terminal: false,
    is_transform: false,
    output_shape: null,
    cached_prefix: null,
    is_group_host: false,
    unexpanded: null,
    annotations: {},
    ...over,
  };
}

function rfgroup(id: string, over: Partial<RFGroup> = {}): RFGroup {
  return { id, kind: "workflow", parent: null, host: null, members: [], nesting_depth: 0, annotations: {}, ...over };
}

function rfedge(id: string, source: string, target: string, kind: EdgeKind): RFEdge {
  return {
    id,
    source,
    target,
    kind,
    label: null,
    output_field: null,
    input_name: null,
    shadowed: false,
    condition: null,
    output_path: [],
  };
}

describe("layoutGraph — the spine pass is wired in (real ELK)", () => {
  it("TD: a chain through an EXPANDED region keeps every icon column on one line", async () => {
    // The staircase repro shape: leaf → sub-workflow region → leaf. The region is
    // port-less (compound crash), so without the pass ELK center-anchors it and
    // the trunk jogs by ~half the region width at both ends.
    const graph: RFGraph = {
      nodes: [
        rfnode("before"),
        rfnode("host", { kind: "workflow", is_group_host: true }),
        rfnode("body", { parent: "g0" }),
        rfnode("after"),
      ],
      edges: [rfedge("e0", "before", "host", "sequential"), rfedge("e1", "host", "after", "sequential")],
      groups: [rfgroup("g0", { host: "host", members: ["body"] })],
    };
    const { nodes, edges } = buildFlow(graph, { density: "compact", direction: "TD", collapsed: new Set() });
    const laidOut = await layoutGraph(nodes, edges, "TD");
    const byId = new Map(laidOut.map((n) => [n.id, n]));
    const col = (id: string): number => byId.get(id)!.position.x + ICON_COL_X;
    expect(Math.abs(col("g0") - col("before"))).toBeLessThanOrEqual(1);
    expect(Math.abs(col("after") - col("before"))).toBeLessThanOrEqual(1);
  });
});
