import { describe, expect, it } from "vitest";

import {
  edgeIdForTarget,
  edgeTargetForId,
  flatIdForRef,
  refForFlatId,
  remapCollapsed,
  remapSelection,
  sameRef,
} from "./remap";
import type { AncestorStepRef, RFEdge, RFGraph, RFGroup, RFNode, RFRef } from "../types";

// ---- fixtures --------------------------------------------------------------

function ref(node_id: string, ancestor_path: AncestorStepRef[] = [], port: "in" | "out" | null = null): RFRef {
  return { node_id, ancestor_path, port };
}

function node(id: string, r: RFRef, over: Partial<RFNode> = {}): RFNode {
  return {
    id,
    ref: r,
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

function edge(id: string, source: string, target: string): RFEdge {
  return { id, source, target, kind: "sequential", label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [] };
}

function graph(over: Partial<RFGraph> = {}): RFGraph {
  return { nodes: [], edges: [], groups: [], ...over } as RFGraph;
}

describe("sameRef", () => {
  it("matches on node_id + port + the full ancestor path", () => {
    expect(sameRef(ref("a"), ref("a"))).toBe(true);
    expect(sameRef(ref("a"), ref("b"))).toBe(false);
    expect(sameRef(ref("a", [], "in"), ref("a", [], "out"))).toBe(false);
    const path: AncestorStepRef[] = [{ node_id: "wf", batch_index: 2 }];
    expect(sameRef(ref("a", path), ref("a", path))).toBe(true);
    expect(sameRef(ref("a", path), ref("a", [{ node_id: "wf", batch_index: 3 }]))).toBe(false);
    expect(sameRef(ref("a", path), ref("a", []))).toBe(false);
  });
});

describe("live structural target mapping", () => {
  const sourceRef = ref("gen", [{ node_id: "child", batch_index: 1 }]);
  const targetRef = ref("use");
  const g = graph({
    nodes: [node("n7", sourceRef), node("n2", targetRef), node("n8", ref("host"), { is_group_host: true })],
    edges: [
      {
        ...edge("e3", "n7", "n2"),
        kind: "data_flow",
        output_field: "result",
        output_path: ["ok"],
        input_name: "value",
      },
    ],
    groups: [group("g4", { host: "n8" })],
  });

  it("maps full refs both ways without relying on node_id alone", () => {
    expect(flatIdForRef(g, sourceRef)).toBe("n7");
    expect(flatIdForRef(g, ref("gen", [{ node_id: "child", batch_index: 0 }]))).toBeNull();
    expect(refForFlatId(g, "n7")).toEqual(sourceRef);
    expect(refForFlatId(g, "g4")).toEqual(ref("host"));
  });

  it("matches data edges by original endpoints plus the complete field path", () => {
    const target = {
      kind: "edge" as const,
      source: sourceRef,
      source_field: "result",
      source_path: ["ok"],
      target: targetRef,
      input_name: "value",
    };
    expect(edgeIdForTarget(g, target)).toBe("e3");
    expect(edgeIdForTarget(g, { ...target, source_path: ["error"] })).toBeNull();
    expect(edgeTargetForId(g, "e3")).toEqual(target);
  });
});

describe("remapSelection", () => {
  // Same logical node, RENUMBERED flat id (an insert shifted it n1 -> n2).
  const prev = graph({ nodes: [node("n0", ref("greet")), node("n1", ref("done"))] });
  const next = graph({ nodes: [node("n0", ref("greet")), node("n1", ref("inserted")), node("n2", ref("done"))] });

  it("follows a still-existing node to its NEW flat id (fixes the wrong-node bug)", () => {
    expect(remapSelection(prev, next, "n1")).toBe("n2"); // 'done' moved n1 -> n2
    expect(remapSelection(prev, next, "n0")).toBe("n0"); // 'greet' unchanged
  });

  it("clears a vanished node (fixes the all-dim-canvas dangle)", () => {
    const deleted = graph({ nodes: [node("n0", ref("greet"))] });
    expect(remapSelection(prev, deleted, "n1")).toBeNull(); // 'done' is gone
  });

  it("remaps a selected GROUP via its host's structural ref", () => {
    const p = graph({
      nodes: [node("n0", ref("h")), node("n1", ref("x"))],
      groups: [group("g0", { host: "n0", kind: "workflow" })],
    });
    const q = graph({
      nodes: [node("n0", ref("x")), node("n1", ref("h"))], // host 'h' renumbered n0 -> n1
      groups: [group("g0", { host: "n1", kind: "workflow" })],
    });
    expect(remapSelection(p, q, "g0")).toBe("g0"); // same group id here, but resolved via host ref
    // host vanished -> clear
    const gone = graph({ nodes: [node("n0", ref("x"))], groups: [] });
    expect(remapSelection(p, gone, "g0")).toBeNull();
  });

  it("leaves an edge / unknown id as-is (the edge-invalidation effect owns it)", () => {
    const p = graph({ nodes: [node("n0", ref("a"))], edges: [edge("e0", "n0", "n0")] });
    expect(remapSelection(p, p, "e0")).toBe("e0");
    expect(remapSelection(p, p, "totally-unknown")).toBe("totally-unknown");
  });

  it("passes null through", () => {
    expect(remapSelection(prev, next, null)).toBeNull();
  });
});

describe("remapCollapsed", () => {
  const prev = graph({
    nodes: [node("n0", ref("ha")), node("n1", ref("hb"))],
    groups: [group("g0", { host: "n0", kind: "workflow" }), group("g1", { host: "n1", kind: "batch" })],
  });

  it("follows collapsed containers to their new group ids via host ref", () => {
    // An edit renumbered both hosts and groups.
    const next = graph({
      nodes: [node("n0", ref("new")), node("n1", ref("ha")), node("n2", ref("hb"))],
      groups: [group("g0", { host: "n1", kind: "workflow" }), group("g1", { host: "n2", kind: "batch" })],
    });
    const out = remapCollapsed(prev, next, new Set(["g0", "g1"]));
    expect(out).toEqual(new Set(["g0", "g1"])); // ids happen to match, but resolved by host ref
  });

  it("drops a container that vanished", () => {
    const next = graph({ nodes: [node("n0", ref("ha"))], groups: [group("g0", { host: "n0", kind: "workflow" })] });
    const out = remapCollapsed(prev, next, new Set(["g0", "g1"]));
    expect(out).toEqual(new Set(["g0"])); // g1's host 'hb' is gone
  });

  it("preserves the ORIGINAL set reference when nothing renumbered (no build churn)", () => {
    const same = new Set(["g0", "g1"]);
    expect(remapCollapsed(prev, prev, same)).toBe(same); // identity preserved
  });
});
