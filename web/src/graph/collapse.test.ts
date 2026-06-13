import { describe, expect, it } from "vitest";

import { AUTO_COLLAPSE_NODE_BUDGET, collapsibleGroupIds, initialCollapsed } from "./collapse";
import type { RFGraph, RFGroup, RFNode } from "../types";

function node(id: string, over: Partial<RFNode> = {}): RFNode {
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

function group(id: string, over: Partial<RFGroup> = {}): RFGroup {
  return { id, kind: "workflow", parent: null, host: null, members: [], nesting_depth: 0, annotations: {}, ...over };
}

function graphWith(nodeCount: number, groups: RFGroup[], nodes: RFNode[] = []): RFGraph {
  const filler = Array.from({ length: nodeCount - nodes.length }, (_, i) => node(`f${i}`));
  return { nodes: [...nodes, ...filler], edges: [], groups };
}

describe("collapsibleGroupIds — workflow/batch collapse, IO wrappers never", () => {
  it("excludes input/output wrappers (they render as IO rows, not boxes)", () => {
    const g = graphWith(3, [
      group("gw"),
      group("gb", { kind: "batch", members: ["m1"] }), // literal batch — real items inside
      group("gi", { kind: "input_wrapper" }),
      group("go", { kind: "output_wrapper" }),
    ]);
    expect(collapsibleGroupIds(g)).toEqual(["gw", "gb"]);
  });

  it("excludes SHELL batch groups (decorator shells — buildFlow never renders them)", () => {
    // A dynamic/childless batch group is a decorator shell per shellBatchIds
    // (the single copy of the rule — NOT "no direct members": batch groups never
    // have direct members, which is exactly how the literal-batch hole shipped).
    const g = graphWith(3, [
      group("gw"),
      group("g_shell", { kind: "batch" }), // a batched leaf / dynamic sub-workflow's decorator
    ]);
    expect(collapsibleGroupIds(g)).toEqual(["gw"]);
  });

  it("a LITERAL batch group with expanded item groups IS collapsible (a real box, not a shell)", () => {
    // The song-creator shape (review-caught 2026-06-11): a literal batch of
    // sub-workflows renders its batch container as the host's representative —
    // it must be toggleable and count in the toolbar's N/M.
    const host = node("h0", {
      kind: "workflow",
      is_group_host: true,
      batch: { parallel: true, dynamic: false, as_name: "item", source_ref: null, count: 2, items: [{}, {}] },
    });
    const g = graphWith(
      3,
      [group("g_lit", { kind: "batch", host: "h0" }), group("g_item", { parent: "g_lit", nesting_depth: 1, members: ["m0"] })],
      [host, node("m0", { parent: "g_item" })],
    );
    expect(collapsibleGroupIds(g)).toEqual(["g_lit", "g_item"]);
  });
});

describe("initialCollapsed — big workflows open as an overview", () => {
  const groups = [group("g0"), group("g1", { parent: "g0", nesting_depth: 1 })];

  it("under the budget: opens fully expanded (auto)", () => {
    const g = graphWith(AUTO_COLLAPSE_NODE_BUDGET, groups);
    expect(initialCollapsed(g, null, []).size).toBe(0);
  });

  it("over the budget: opens fully collapsed (auto)", () => {
    const g = graphWith(AUTO_COLLAPSE_NODE_BUDGET + 1, groups);
    expect([...initialCollapsed(g, null, [])].sort()).toEqual(["g0", "g1"]);
  });

  it("collapse=none overrides auto on a big workflow", () => {
    const g = graphWith(AUTO_COLLAPSE_NODE_BUDGET + 1, groups);
    expect(initialCollapsed(g, "none", []).size).toBe(0);
  });

  it("collapse=all overrides auto on a small workflow", () => {
    const g = graphWith(3, groups);
    expect([...initialCollapsed(g, "all", [])].sort()).toEqual(["g0", "g1"]);
  });

  it("a deep-link target's WHOLE ancestor chain stays expanded; siblings stay collapsed", () => {
    // target sits two groups deep (g0 > g1 > target); g2 is an unrelated sibling.
    const g = graphWith(
      AUTO_COLLAPSE_NODE_BUDGET + 1,
      [group("g0"), group("g1", { parent: "g0", nesting_depth: 1 }), group("g2")],
      [node("target", { parent: "g1" })],
    );
    const collapsed = initialCollapsed(g, null, ["target"]);
    expect(collapsed.has("g0")).toBe(false);
    expect(collapsed.has("g1")).toBe(false);
    expect(collapsed.has("g2")).toBe(true);
  });

  it("a deep link by FLAT id protects too, and unresolvable targets are ignored", () => {
    const g = graphWith(
      AUTO_COLLAPSE_NODE_BUDGET + 1,
      [group("g0")],
      [node("n9", { ref: { node_id: "named", ancestor_path: [], port: null }, parent: "g0" })],
    );
    expect(initialCollapsed(g, null, ["n9"]).has("g0")).toBe(false);
    expect(initialCollapsed(g, null, ["ghost", null]).has("g0")).toBe(true);
  });

  it("an EDGE deep link protects BOTH endpoints' ancestor chains (a collapsed endpoint drops the edge → silent no-op)", () => {
    const g: RFGraph = {
      ...graphWith(
        AUTO_COLLAPSE_NODE_BUDGET + 1,
        [group("g0"), group("g1"), group("g2")],
        [node("a", { parent: "g0" }), node("b", { parent: "g1" })],
      ),
      edges: [
        { id: "e7", source: "a", target: "b", kind: "data_flow", label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [] },
      ],
    };
    const collapsed = initialCollapsed(g, null, ["e7"]);
    expect(collapsed.has("g0")).toBe(false); // source's chain
    expect(collapsed.has("g1")).toBe(false); // target's chain
    expect(collapsed.has("g2")).toBe(true); // unrelated stays collapsed
  });
});
