import { describe, expect, it } from "vitest";

import { applyFocus, buildFlow, type BuildOptions } from "./flow";
import {
  branchHandle,
  handleType,
  NODE_IN,
  NODE_OUT,
  outputHandle,
  paramHandle,
  portHandle,
  portTargetHandle,
} from "./handles";
import { layoutGraph } from "./layout";
import type { EdgeKind, RFEdge, RFGraph, RFGroup, RFNode } from "../types";

// ---- fixture builders ---------------------------------------------------

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
    is_group_host: false,
    unexpanded: null,
    annotations: {},
    ...over,
  };
}

function group(id: string, over: Partial<RFGroup> = {}): RFGroup {
  return {
    id,
    kind: "workflow",
    parent: null,
    host: null,
    members: [],
    nesting_depth: 0,
    annotations: {},
    ...over,
  };
}

function edge(id: string, source: string, target: string, kind: EdgeKind, over: Partial<RFEdge> = {}): RFEdge {
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, ...over };
}

const DETAILED: BuildOptions = { density: "detailed", direction: "LR", collapsed: new Set() };
const COMPACT: BuildOptions = { density: "compact", direction: "LR", collapsed: new Set() };
const TD: BuildOptions = { density: "compact", direction: "TD", collapsed: new Set() };

// ---- tests --------------------------------------------------------------

describe("buildFlow — host suppression (H8)", () => {
  // An is_group_host node has no leaf box; its group stands in, and edges into the
  // host re-anchor onto the group.
  const graph: RFGraph = {
    nodes: [
      node("n0"),
      node("n1", { kind: "workflow", is_group_host: true }),
      node("n2", { parent: "g0" }),
    ],
    edges: [edge("e0", "n0", "n1", "sequential")],
    groups: [group("g0", { host: "n1", members: ["n2"] })],
  };

  it("suppresses the host leaf and emits its group", () => {
    const { nodes } = buildFlow(graph, DETAILED);
    expect(nodes.find((n) => n.id === "n1")).toBeUndefined();
    const g = nodes.find((n) => n.id === "g0");
    expect(g?.type).toBe("group");
  });

  it("re-anchors an edge into the host onto the group", () => {
    const { edges } = buildFlow(graph, DETAILED);
    const e = edges.find((e) => e.id === "e0");
    expect(e?.source).toBe("n0");
    expect(e?.target).toBe("g0");
  });
});

describe("buildFlow — a multi-group host re-anchors to its OUTERMOST group (H8)", () => {
  // A dynamic-batch-of-subworkflow host backs TWO groups with the same host: a
  // batch container (outer) and a workflow container (inner, nested in the batch).
  // Both can sit at the same nesting_depth, so outer-selection must use the
  // parent-relationship, not depth alone. An edge into the host lands on the batch.
  const graph: RFGraph = {
    nodes: [
      node("ext"),
      node("host", {
        kind: "workflow",
        is_group_host: true,
        batch: { parallel: false, dynamic: true, as_name: "item", source_ref: "${xs}", count: null, items: null },
      }),
      node("body", { parent: "g_wf" }),
    ],
    edges: [edge("e0", "ext", "host", "sequential")],
    groups: [
      group("g_batch", { kind: "batch", host: "host", parent: null, nesting_depth: 1 }),
      group("g_wf", { kind: "workflow", host: "host", parent: "g_batch", nesting_depth: 1, members: ["body"] }),
    ],
  };

  it("lands the edge on the batch group and titles only the outer group", () => {
    const { nodes, edges } = buildFlow(graph, DETAILED);
    expect(edges.find((e) => e.id === "e0")?.target).toBe("g_batch");
    const batch = nodes.find((n) => n.id === "g_batch");
    const wf = nodes.find((n) => n.id === "g_wf");
    expect(batch?.type).toBe("group");
    expect(wf?.type).toBe("group");
    // Only the outermost group of a multi-group host shows the host title/badges.
    expect(batch?.type === "group" && batch.data.showTitle).toBe(true);
    expect(wf?.type === "group" && wf.data.showTitle).toBe(false);
  });
});

describe("buildFlow — collapse re-anchors, never drops (H6/W1)", () => {
  const graph: RFGraph = {
    nodes: [node("n0"), node("n1", { parent: "g0" })],
    edges: [edge("e0", "n0", "n1", "data_flow", { output_field: "result" })],
    groups: [group("g0", { members: ["n1"] })],
  };

  it("hides members of a collapsed group but keeps the edge, re-anchored to the group", () => {
    const { nodes, edges } = buildFlow(graph, { ...DETAILED, collapsed: new Set(["g0"]) });
    expect(nodes.find((n) => n.id === "n1")).toBeUndefined();
    const g = nodes.find((n) => n.id === "g0");
    expect(g).toBeDefined();
    const e = edges.find((e) => e.id === "e0");
    expect(e?.source).toBe("n0");
    expect(e?.target).toBe("g0"); // additive: degraded to the group, not dropped
    // The re-anchored target attaches at group/node level — never a hidden member's
    // param handle (which would float, silently dropping the line).
    expect(e?.targetHandle).toBe(NODE_IN);
  });

  it("expands again with no collapsed set", () => {
    const { nodes } = buildFlow(graph, DETAILED);
    expect(nodes.find((n) => n.id === "n1")).toBeDefined();
  });
});

describe("buildFlow — data-flow lines land on param rows (H6)", () => {
  const graph: RFGraph = {
    nodes: [
      node("n0", { params: [{ name: "x", value: "1", is_dynamic: false, source: null }] }),
      node("n1", { params: [{ name: "prompt", value: "${a.x}", is_dynamic: true, source: null }] }),
    ],
    edges: [
      edge("e0", "n0", "n1", "data_flow", { output_field: "result", input_name: "prompt" }),
      edge("e1", "n0", "n1", "data_flow", { output_field: "result", input_name: null }),
    ],
    groups: [],
  };

  it("detailed: a matched input_name lands on the param handle; a null one falls back to node level", () => {
    const { edges } = buildFlow(graph, DETAILED);
    const matched = edges.find((e) => e.id === "e0");
    expect(matched?.sourceHandle).toBe(outputHandle("result"));
    expect(matched?.targetHandle).toBe(paramHandle("prompt"));
    const nodeLevel = edges.find((e) => e.id === "e1");
    expect(nodeLevel?.targetHandle).toBe(NODE_IN);
    expect(nodeLevel?.sourceHandle).toBe(outputHandle("result"));
  });

  it("compact: data-flow uses node-level handles and is hidden by default", () => {
    const { edges } = buildFlow(graph, COMPACT);
    const e = edges.find((e) => e.id === "e0");
    expect(e?.sourceHandle).toBe(NODE_OUT);
    expect(e?.targetHandle).toBe(NODE_IN);
    expect(e?.hidden).toBe(true); // beautiful skeleton — revealed only on focus
  });

  it("falls back to node level when input_name names no existing param (never a missing handle)", () => {
    // input_name is best-effort/lossy — it can name a param the on-canvas node does
    // not render. The guard must degrade to NODE_IN, not emit a handle id that
    // React Flow would float (silently dropping the line).
    const g: RFGraph = {
      nodes: [node("n0"), node("n1", { params: [{ name: "prompt", value: "x", is_dynamic: false, source: null }] })],
      edges: [edge("e0", "n0", "n1", "data_flow", { input_name: "ghost" })],
      groups: [],
    };
    const { edges } = buildFlow(g, DETAILED);
    expect(edges.find((e) => e.id === "e0")?.targetHandle).toBe(NODE_IN);
  });
});

describe("buildFlow — two refs into one param yield two lines", () => {
  // "${a.x} and ${b.y}" produces two data-flow edges, both landing on the same row.
  const graph: RFGraph = {
    nodes: [
      node("a"),
      node("b"),
      node("t", { params: [{ name: "prompt", value: "${a.x} and ${b.y}", is_dynamic: true, source: null }] }),
    ],
    edges: [
      edge("e0", "a", "t", "data_flow", { output_field: "x", input_name: "prompt" }),
      edge("e1", "b", "t", "data_flow", { output_field: "y", input_name: "prompt" }),
    ],
    groups: [],
  };

  it("keeps both edges, both on the prompt handle", () => {
    const { edges } = buildFlow(graph, DETAILED);
    const onPrompt = edges.filter((e) => e.target === "t" && e.targetHandle === paramHandle("prompt"));
    expect(onPrompt).toHaveLength(2);
    expect(new Set(onPrompt.map((e) => e.source))).toEqual(new Set(["a", "b"]));
  });
});

describe("buildFlow — density governs edge density (beautiful = control skeleton)", () => {
  const graph: RFGraph = {
    nodes: [
      node("a"),
      node("b", { params: [{ name: "x", value: "${a.out}", is_dynamic: true, source: null }] }),
    ],
    edges: [
      edge("seq", "a", "b", "sequential"),
      edge("df", "a", "b", "data_flow", { output_field: "out", input_name: "x" }),
    ],
    groups: [],
  };

  const dataFlow = (edges: ReturnType<typeof buildFlow>["edges"]) => edges.find((e) => e.id === "df");

  it("advanced shows data-flow (not hidden)", () => {
    expect(dataFlow(buildFlow(graph, DETAILED).edges)?.hidden).toBe(false);
  });

  it("beautiful keeps control flow visible but hides data-flow by default", () => {
    const { edges } = buildFlow(graph, COMPACT);
    expect(edges.find((e) => e.id === "seq")?.hidden).toBe(false);
    expect(dataFlow(edges)?.hidden).toBe(true);
  });

  it("beautiful labels the data line with what flows; advanced uses node rows (no label)", () => {
    const g: RFGraph = {
      nodes: [node("a"), node("b", { params: [{ name: "data", value: "${a.out}", is_dynamic: true, source: null }] })],
      edges: [edge("df", "a", "b", "data_flow", { output_field: "stdout", input_name: "data" })],
      groups: [],
    };
    expect(buildFlow(g, COMPACT).edges.find((e) => e.id === "df")?.label).toBe("stdout → data");
    expect(buildFlow(g, DETAILED).edges.find((e) => e.id === "df")?.label).toBeUndefined();
  });
});

describe("applyFocus — reveals the focused node's data-flow in beautiful mode", () => {
  const graph: RFGraph = {
    nodes: [
      node("a"),
      node("b", { params: [{ name: "x", value: "${a.o}", is_dynamic: true, source: null }] }),
      node("c", { params: [{ name: "y", value: "${a.o}", is_dynamic: true, source: null }] }),
    ],
    edges: [
      edge("ab", "a", "b", "data_flow", { output_field: "o", input_name: "x" }),
      edge("ac", "a", "c", "data_flow", { output_field: "o", input_name: "y" }),
    ],
    groups: [],
  };

  it("hidden by default; focusing b reveals only b's data line, c's stays hidden", () => {
    const built = buildFlow(graph, COMPACT);
    expect(built.edges.every((e) => e.data?.kind !== "data_flow" || e.hidden)).toBe(true);

    const focused = applyFocus(built.nodes, built.edges, "b");
    expect(focused.edges.find((e) => e.id === "ab")?.hidden).toBe(false); // incident to b
    expect(focused.edges.find((e) => e.id === "ac")?.hidden).toBe(true); // not incident
  });

  it("clearing focus re-hides the revealed data line", () => {
    const built = buildFlow(graph, COMPACT);
    const cleared = applyFocus(built.nodes, built.edges, null);
    expect(cleared.edges.every((e) => e.data?.kind !== "data_flow" || e.hidden)).toBe(true);
  });
});

describe("buildFlow — decision forks: labeled border handles (both densities)", () => {
  const graph: RFGraph = {
    nodes: [node("dec", { is_decision: true }), node("a"), node("b")],
    edges: [
      edge("e0", "dec", "a", "branch", { label: "yes" }),
      edge("e1", "dec", "b", "branch", { label: "no" }),
    ],
    groups: [],
  };

  it("each branch leaves its own labeled handle; the node carries the outcome labels", () => {
    const { nodes, edges } = buildFlow(graph, DETAILED);
    expect(edges.find((e) => e.id === "e0")?.sourceHandle).toBe(branchHandle("yes"));
    expect(edges.find((e) => e.id === "e1")?.sourceHandle).toBe(branchHandle("no"));
    const dec = nodes.find((n) => n.id === "dec");
    expect(dec?.type).toBe("node");
    expect(dec?.type === "node" ? dec.data.branchLabels : null).toEqual(["yes", "no"]);
  });

  it("forks stay on their labeled handles in beautiful mode too", () => {
    const { edges } = buildFlow(graph, COMPACT);
    expect(edges.find((e) => e.id === "e0")?.sourceHandle).toBe(branchHandle("yes"));
  });

  it("TD: forks fan from the icon (NODE_OUT) with the outcome label on the edge", () => {
    const { edges } = buildFlow(graph, TD);
    const e0 = edges.find((e) => e.id === "e0");
    expect(e0?.sourceHandle).toBe(NODE_OUT); // through the icon column, not a border handle
    expect(e0?.label).toBe("yes"); // the label rides the edge in TD (no BranchPorts rows)
    // still a source-type handle — the invariant holds
    expect(handleType(e0?.sourceHandle ?? "")).toBe("source");
  });
});

describe("buildFlow — IO ports consolidate into one Inputs node with rows", () => {
  function ioInput(id: string, name: string, required = false): RFNode {
    return node(id, {
      kind: "input",
      io: { data_type: "string", required },
      parent: "g_in",
      ref: { node_id: name, ancestor_path: [], port: "in" },
    });
  }
  const graph: RFGraph = {
    nodes: [
      node("feeder"), // a parent node that binds a value into the input port
      ioInput("inA", "repo_dir"),
      ioInput("inB", "plan", true),
      node("body", { parent: "g_wf", params: [{ name: "x", value: "${repo_dir}", is_dynamic: true, source: null }] }),
    ],
    edges: [
      edge("bind", "feeder", "inA", "data_flow"), // parent -> input port (receives)
      edge("e0", "inA", "body", "data_flow", { input_name: "x" }), // input -> consumer (feeds)
      edge("e1", "inB", "body", "data_flow", { input_name: "x" }),
    ],
    groups: [group("g_wf", { kind: "workflow" }), group("g_in", { kind: "input_wrapper", parent: "g_wf", members: ["inA", "inB"] })],
  };

  it("emits ONE ports node (rows = the ports), no per-port nodes, no wrapper group — both densities", () => {
    for (const view of [DETAILED, COMPACT]) {
      const { nodes } = buildFlow(graph, view);
      const ports = nodes.find((n) => n.id === "g_in");
      expect(ports?.type).toBe("ports");
      expect(ports?.type === "ports" ? ports.data.ports.map((p) => p.name) : []).toEqual(["repo_dir", "plan"]);
      expect(nodes.find((n) => n.id === "inA")).toBeUndefined(); // not a separate node
    }
  });

  it("re-anchors each port's edge onto its OWN row handle, preserving the original endpoints", () => {
    const { edges } = buildFlow(graph, DETAILED);
    // input FEEDS a consumer → its row's source handle
    const e0 = edges.find((e) => e.id === "e0");
    expect(e0?.source).toBe("g_in");
    expect(e0?.sourceHandle).toBe(portHandle("inA"));
    expect(e0?.data?.from).toBe("inA"); // original endpoint kept for focus
    expect(e0?.data?.to).toBe("body");
    // a binding RECEIVES into the same input → its row's TARGET handle (the edges
    // that were missing before — a port has both a feed-out and a receive-in handle)
    const bind = edges.find((e) => e.id === "bind");
    expect(bind?.target).toBe("g_in");
    expect(bind?.targetHandle).toBe(portTargetHandle("inA"));
  });

  it("beautiful: clicking ONE port reveals only its line + highlights its row", () => {
    const built = buildFlow(graph, COMPACT);
    expect(built.edges.filter((e) => e.data?.kind === "data_flow").every((e) => e.hidden)).toBe(true);

    const focused = applyFocus(built.nodes, built.edges, "inA");
    expect(focused.edges.find((e) => e.id === "e0")?.hidden).toBe(false); // repo_dir's line revealed
    expect(focused.edges.find((e) => e.id === "e1")?.hidden).toBe(true); // plan's stays hidden
    const ports = focused.nodes.find((n) => n.id === "g_in");
    expect(ports?.type === "ports" ? ports.data.focusedPortId : null).toBe("inA");
  });

  it("focusing the consumer reveals all of its input lines", () => {
    const built = buildFlow(graph, COMPACT);
    const focused = applyFocus(built.nodes, built.edges, "body");
    expect(focused.edges.find((e) => e.id === "e0")?.hidden).toBe(false);
    expect(focused.edges.find((e) => e.id === "e1")?.hidden).toBe(false);
  });
});

describe("buildFlow — HANDLE-TYPE INVARIANT (the recurring silent-edge-drop bug)", () => {
  // React Flow SILENTLY drops an edge whose sourceHandle is a target-type id (or vice
  // versa) — jsdom can't catch this (it renders no edge DOM), and it bit us twice
  // (the input-binding edge used a source handle as a target). This is the safety net:
  // a graph exercising EVERY handle scheme, asserting buildFlow never crosses a type.
  function rfInput(id: string, name: string): RFNode {
    return node(id, {
      kind: "input",
      io: { data_type: "string", required: false },
      parent: "g_in",
      ref: { node_id: name, ancestor_path: [], port: "in" },
    });
  }
  // feeder → input(bind) → consumer(feed) → dec(seq + data-out) → a/b(branch)
  const graph: RFGraph = {
    nodes: [
      node("feeder"),
      rfInput("inA", "repo_dir"),
      node("consumer", { params: [{ name: "x", value: "${repo_dir}", is_dynamic: true, source: null }] }),
      node("dec", { is_decision: true }),
      node("a"),
      node("b"),
    ],
    edges: [
      edge("bind", "feeder", "inA", "data_flow"), // → portTargetHandle (TARGET) — the bug case
      edge("feed", "inA", "consumer", "data_flow", { input_name: "x" }), // portHandle (src) → paramHandle (tgt)
      edge("out", "consumer", "dec", "data_flow", { output_field: "result" }), // outputHandle (src)
      edge("seq", "consumer", "dec", "sequential"), // NODE_OUT/NODE_IN
      edge("br1", "dec", "a", "branch", { label: "yes" }), // branchHandle (src)
      edge("br2", "dec", "b", "branch", { label: "no" }),
    ],
    groups: [group("g_in", { kind: "input_wrapper", members: ["inA"] })],
  };

  it("every edge's sourceHandle is a source-type id and targetHandle a target-type id", () => {
    for (const view of [DETAILED, COMPACT]) {
      for (const e of buildFlow(graph, view).edges) {
        // handleType throws on an unknown scheme, so a new untyped handle also fails here.
        expect({ id: e.id, source: e.sourceHandle, type: handleType(e.sourceHandle ?? "") }).toMatchObject({
          type: "source",
        });
        expect({ id: e.id, target: e.targetHandle, type: handleType(e.targetHandle ?? "") }).toMatchObject({
          type: "target",
        });
      }
    }
  });
});

describe("buildFlow — loop arc synthesized from LoopSpec", () => {
  it("adds a self-loop edge on the looped node, in both densities", () => {
    const graph: RFGraph = {
      nodes: [node("n0", { loop: { polarity: "while", condition: "${x.go}", cap: 5, carry: {} } })],
      edges: [],
      groups: [],
    };
    for (const view of [DETAILED, COMPACT]) {
      const loop = buildFlow(graph, view).edges.find((e) => e.type === "loop");
      expect(loop?.source).toBe("n0");
      expect(loop?.target).toBe("n0");
      expect(loop?.data?.loop?.condition).toBe("${x.go}");
    }
  });

  it("draws the loop arc on the GROUP for a looped sub-workflow host", () => {
    const graph: RFGraph = {
      nodes: [
        node("host", {
          kind: "workflow",
          is_group_host: true,
          loop: { polarity: "until", condition: "${done}", cap: null, carry: {} },
        }),
        node("body", { parent: "g0" }),
      ],
      edges: [],
      groups: [group("g0", { host: "host", members: ["body"] })],
    };
    const loop = buildFlow(graph, DETAILED).edges.find((e) => e.type === "loop");
    expect(loop?.source).toBe("g0");
    expect(loop?.target).toBe("g0");
  });
});

describe("buildFlow — end sink (H10)", () => {
  it("renders a kind=end node as an end-type sink with its end edge", () => {
    const graph: RFGraph = {
      nodes: [node("n0", { is_decision: true }), node("end0", { kind: "end" })],
      edges: [edge("e0", "n0", "end0", "end")],
      groups: [],
    };
    const { nodes, edges } = buildFlow(graph, DETAILED);
    expect(nodes.find((n) => n.id === "end0")?.type).toBe("end");
    expect(edges.find((e) => e.id === "e0")?.target).toBe("end0");
  });
});

describe("applyFocus — dims non-neighbors, no re-layout", () => {
  const graph: RFGraph = {
    nodes: [node("n0"), node("n1"), node("n2")],
    // e0 touches the focus (n0); e1 does not — so both dim branches are exercised.
    edges: [edge("e0", "n0", "n1", "sequential"), edge("e1", "n1", "n2", "sequential")],
    groups: [],
  };

  it("focusing n0 keeps n0+n1 lit, dims the unconnected n2, and dims non-incident edges", () => {
    const { nodes, edges } = buildFlow(graph, DETAILED);
    const focused = applyFocus(nodes, edges, "n0");
    const byId = new Map(focused.nodes.map((n) => [n.id, n]));
    expect(byId.get("n0")?.data.focused).toBe(true);
    expect(byId.get("n0")?.data.dimmed).toBe(false);
    expect(byId.get("n1")?.data.dimmed).toBe(false);
    expect(byId.get("n2")?.data.dimmed).toBe(true);
    const edgeById = new Map(focused.edges.map((e) => [e.id, e]));
    expect(edgeById.get("e0")?.className).not.toContain("edge-dimmed"); // incident to n0
    expect(edgeById.get("e1")?.className).toContain("edge-dimmed"); // n1->n2, not incident
  });

  it("clears dim/highlight when focus is null", () => {
    const { nodes, edges } = buildFlow(graph, DETAILED);
    const cleared = applyFocus(applyFocus(nodes, edges, "n0").nodes, edges, null);
    expect(cleared.nodes.every((n) => !n.data.dimmed && !n.data.focused)).toBe(true);
  });
});

describe("layoutGraph — produces positions (ELK smoke)", () => {
  it("lays out a small nested graph without throwing", async () => {
    const graph: RFGraph = {
      nodes: [node("n0"), node("n1", { parent: "g0" })],
      edges: [edge("e0", "n0", "n1", "sequential")],
      groups: [group("g0", { members: ["n1"] })],
    };
    const { nodes, edges } = buildFlow(graph, DETAILED);
    const laidOut = await layoutGraph(nodes, edges, "LR");
    expect(laidOut).toHaveLength(nodes.length);
    // every node got a finite position and a non-zero box
    for (const n of laidOut) {
      expect(Number.isFinite(n.position.x)).toBe(true);
      expect(Number.isFinite(n.position.y)).toBe(true);
      expect((n.width ?? 0) > 0).toBe(true);
    }
  });
});
