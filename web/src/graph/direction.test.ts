import { describe, expect, it } from "vitest";

import { autoDirection, DENSE_DATA_PER_NODE, DENSE_NODE_FLOOR } from "./direction";
import type { EdgeKind, RFEdge, RFGraph, RFNode } from "../types";

function node(id: string): RFNode {
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
  };
}

function edge(id: string, kind: EdgeKind): RFEdge {
  return { id, source: "a", target: "b", kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [] };
}

/** A graph of `nodeCount` nodes and `dataEdges` data-flow edges (+ some control edges
 *  that must NOT count toward density). */
function graphWith(nodeCount: number, dataEdges: number, controlEdges = 0): RFGraph {
  return {
    nodes: Array.from({ length: nodeCount }, (_, i) => node(`n${i}`)),
    edges: [
      ...Array.from({ length: dataEdges }, (_, i) => edge(`d${i}`, "data_flow")),
      ...Array.from({ length: controlEdges }, (_, i) => edge(`c${i}`, "sequential")),
    ],
    groups: [],
  };
}

describe("autoDirection — dense pipelines open TD, everything else LR", () => {
  it("keeps a small workflow LR however dense (direction is cosmetic at that size)", () => {
    // Below the node floor: ratio 3.0 but still LR.
    expect(autoDirection(graphWith(DENSE_NODE_FLOOR - 1, (DENSE_NODE_FLOOR - 1) * 3))).toBe("LR");
  });

  it("opens a non-trivial DENSE pipeline TD (the harness/changelog class)", () => {
    // 26 nodes, 39 data edges = 1.5/node — the measured generate-changelog-simple shape.
    expect(autoDirection(graphWith(26, 39))).toBe("TD");
    // 82 nodes, 152 data = 1.85 — the plan-to-code harness.
    expect(autoDirection(graphWith(82, 152))).toBe("TD");
  });

  it("keeps a non-trivial SPARSE pipeline LR (deep-research / orchestrate class)", () => {
    expect(autoDirection(graphWith(29, 30))).toBe("LR"); // 1.03/node
    expect(autoDirection(graphWith(28, 33))).toBe("LR"); // 1.18/node
  });

  it("counts ONLY data-flow edges toward density (control edges don't thread)", () => {
    // 20 nodes, 10 data (0.5/node) but 60 control edges — must stay LR despite 70 total.
    expect(autoDirection(graphWith(20, 10, 60))).toBe("LR");
    // The same 20 nodes with 28 data edges (1.4/node) flips, regardless of control count.
    expect(autoDirection(graphWith(20, Math.ceil(20 * DENSE_DATA_PER_NODE), 60))).toBe("TD");
  });

  it("treats the threshold as inclusive (>= flips)", () => {
    const n = 20;
    expect(autoDirection(graphWith(n, Math.ceil(n * DENSE_DATA_PER_NODE)))).toBe("TD");
    expect(autoDirection(graphWith(n, Math.floor(n * DENSE_DATA_PER_NODE) - 1))).toBe("LR");
  });

  it("an empty / node-free graph is LR (no divide-by-zero)", () => {
    expect(autoDirection({ nodes: [], edges: [], groups: [] })).toBe("LR");
  });
});
