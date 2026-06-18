// Focus-pass tests: applyFocus (dim/reveal/edge selection — the pure restyle),
// expandTargets (the beautiful expansion policy) and rowTouches (the row-hover
// set). Split from flow.test.ts beside their subject (focus.ts) —
// architecture-review candidate 2, 2026-06-13.

import { describe, expect, it } from "vitest";

import { applyFocus, expandTargets, rowTouches, SELECTED_EDGE_Z } from "./focus";
import { buildFlow, type FlowEdge, type FlowNode } from "./flow";
import { LOOP_ROW, NODE_IN, NODE_OUT, outputHandle, paramHandle, portHandle, portTargetHandle } from "./handles";
import { COMPACT, DETAILED, edge, group, node } from "./testFixtures";
import type { RFGraph } from "../types";

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

describe("applyFocus — selecting a CONTAINER selects the whole UNIT (design D)", () => {
  // ext → host(group g0: a → b); iso is unrelated. Selecting g0 must light the
  // group + its descendants + every edge touching them (internal wiring AND the
  // external boundary edge), dim only the rest — and reveal the unit's hidden
  // data lines in beautiful.
  const graph: RFGraph = {
    nodes: [
      node("ext"),
      node("host", { kind: "workflow", is_group_host: true }),
      node("a", { parent: "g0" }),
      node("b", { parent: "g0", params: [{ name: "x", value: "${ext.o}", is_dynamic: true, source: null }] }),
      node("iso"),
    ],
    edges: [
      edge("e_in", "ext", "host", "sequential"),
      edge("e_int", "a", "b", "sequential"),
      edge("e_data", "ext", "b", "data_flow", { output_field: "o", input_name: "x" }),
      edge("e_iso", "iso", "iso2", "sequential"),
    ],
    groups: [group("g0", { kind: "workflow", host: "host", members: ["a", "b"] })],
  };
  const dimmedOf = (r: { nodes: FlowNode[] }, id: string): boolean | null => {
    const n = r.nodes.find((x) => x.id === id);
    return n && n.type !== "end" ? n.data.dimmed : null;
  };
  const isDimmed = (r: { edges: { id: string; className?: string }[] }, id: string): boolean =>
    (r.edges.find((e) => e.id === id)?.className ?? "").includes("edge-dimmed");

  it("expanded region focus: descendants and internal wiring stay lit; outside dims", () => {
    const built = buildFlow({ ...graph, nodes: [...graph.nodes, node("iso2")] }, COMPACT);
    const focused = applyFocus(built.nodes, built.edges, "g0");
    expect(focused.nodes.find((n) => n.id === "g0")?.data.focused).toBe(true);
    expect(dimmedOf(focused, "a")).toBe(false); // descendant — part of the unit
    expect(dimmedOf(focused, "ext")).toBe(false); // boundary-edge endpoint — connected
    expect(dimmedOf(focused, "iso")).toBe(true); // unrelated
    expect(isDimmed(focused, "e_int")).toBe(false); // internal wiring is the unit's
    expect(isDimmed(focused, "e_in")).toBe(false); // external binding
    expect(isDimmed(focused, "e_iso")).toBe(true);
    // the unit's hidden data line reveals (beautiful): ext → b is a boundary edge
    expect(focused.edges.find((e) => e.id === "e_data")?.hidden).toBe(false);
  });

  it("collapsed card focus: the unit degrades to the card + its re-anchored edges", () => {
    const built = buildFlow({ ...graph, nodes: [...graph.nodes, node("iso2")] }, { ...COMPACT, collapsed: new Set(["g0"]) });
    const focused = applyFocus(built.nodes, built.edges, "g0");
    expect(focused.nodes.find((n) => n.id === "g0")?.data.focused).toBe(true);
    expect(dimmedOf(focused, "ext")).toBe(false); // its boundary edges re-anchor onto the card
    expect(dimmedOf(focused, "iso")).toBe(true);
    // the data line re-anchored onto the card reveals
    expect(focused.edges.find((e) => e.id === "e_data")?.hidden).toBe(false);
  });

  it("leaf focus is unchanged by the unit machinery (unit = the focus alone)", () => {
    const built = buildFlow({ ...graph, nodes: [...graph.nodes, node("iso2")] }, COMPACT);
    const focused = applyFocus(built.nodes, built.edges, "ext");
    expect(dimmedOf(focused, "iso")).toBe(true);
    expect(dimmedOf(focused, "a")).toBe(true); // inside the group but NOT connected to ext
    expect(isDimmed(focused, "e_int")).toBe(true);
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

describe("applyFocus — selecting an EDGE (edge-click selection, 2026-06-10)", () => {
  // a feeds b twice (x, y) and c once; a → b is also the sequential trunk. The
  // clicked CONNECTION is the subject: only that edge lights, its endpoints stay
  // full-strength, and everything else — including the endpoints' OTHER edges — dims.
  const graph: RFGraph = {
    nodes: [
      node("a"),
      node("b", {
        params: [
          { name: "x", value: "${a.o}", is_dynamic: true, source: null },
          { name: "y", value: "${a.p}", is_dynamic: true, source: null },
        ],
      }),
      node("c", { params: [{ name: "z", value: "${a.o}", is_dynamic: true, source: null }] }),
    ],
    edges: [
      edge("e_seq", "a", "b", "sequential"),
      edge("e_ab1", "a", "b", "data_flow", { output_field: "o", input_name: "x" }),
      edge("e_ab2", "a", "b", "data_flow", { output_field: "p", input_name: "y" }),
      edge("e_ac", "a", "c", "data_flow", { output_field: "o", input_name: "z" }),
    ],
    groups: [],
  };
  const find = (r: { edges: FlowEdge[] }, id: string): FlowEdge => r.edges.find((e) => e.id === id)!;

  it("a selected CONTROL edge gets selected + zIndex (the identity-bailout case: nothing else in its compare tuple changes)", () => {
    const built = buildFlow(graph, DETAILED);
    const focused = applyFocus(built.nodes, built.edges, "e_seq");
    const sel = find(focused, "e_seq");
    expect(sel.data?.selected).toBe(true);
    expect(sel.zIndex).toBe(SELECTED_EDGE_Z);
    expect(sel.className ?? "").not.toContain("edge-dimmed");
  });

  it("only the connection lights: endpoints stay full-strength, their OTHER edges dim, no node wears the ring", () => {
    const built = buildFlow(graph, DETAILED);
    const focused = applyFocus(built.nodes, built.edges, "e_seq");
    const dimmedOf = (id: string): boolean | null => {
      const n = focused.nodes.find((x) => x.id === id);
      return n && n.type !== "end" ? n.data.dimmed : null;
    };
    expect(dimmedOf("a")).toBe(false);
    expect(dimmedOf("b")).toBe(false);
    expect(dimmedOf("c")).toBe(true);
    expect(find(focused, "e_ab1").className).toContain("edge-dimmed");
    expect(find(focused, "e_ab1").data?.dimmed).toBe(true); // R10: pills dim via data
    expect(find(focused, "e_ac").className).toContain("edge-dimmed");
    expect(focused.nodes.every((n) => n.type === "end" || !n.data.focused)).toBe(true);
  });

  it("moving focus from the edge to its endpoint clears selected/zIndex (re-processing decorated output)", () => {
    const built = buildFlow(graph, DETAILED);
    const first = applyFocus(built.nodes, built.edges, "e_seq");
    const second = applyFocus(first.nodes, first.edges, "a");
    const e = find(second, "e_seq");
    expect(e.data?.selected).toBeUndefined();
    expect(e.zIndex).toBeUndefined();
  });

  it("a selected DATA edge draws solid at both ends: focusEnd explicitly cleared (the ternary would default it to 'target')", () => {
    const built = buildFlow(graph, DETAILED);
    // sanity: a NODE focus sets the directional fade on the same edge
    expect(find(applyFocus(built.nodes, built.edges, "a"), "e_ab1").data?.focusEnd).toBe("source");
    const sel = find(applyFocus(built.nodes, built.edges, "e_ab1"), "e_ab1");
    expect(sel.data?.selected).toBe(true);
    expect(sel.data?.focusEnd).toBeUndefined();
  });

  it("beautiful: a default-hidden data edge stays revealed under its OWN focus; siblings stay hidden", () => {
    const built = buildFlow(graph, COMPACT);
    const focused = applyFocus(built.nodes, built.edges, "e_ac");
    expect(find(focused, "e_ac").hidden).toBe(false);
    expect(find(focused, "e_ab1").hidden).toBe(true);
  });

  it("selecting an LR branch edge reveals ITS condition on the SOURCE's row (the selected edge suppresses its own pill)", () => {
    const g: RFGraph = {
      nodes: [node("dec", { kind: "code", is_decision: true }), node("t1"), node("t2")],
      edges: [
        edge("br1", "dec", "t1", "branch", { label: "go", condition: "if ok" }),
        edge("br2", "dec", "t2", "branch", { label: "stop", condition: "else" }),
      ],
      groups: [],
    };
    const built = buildFlow(g, DETAILED); // LR
    const focused = applyFocus(built.nodes, built.edges, "br1");
    const dec = focused.nodes.find((n) => n.id === "dec");
    expect(dec?.type === "node" ? dec.data.revealedConditions : undefined).toEqual({ go: "if ok" });
  });
});

describe("expandTargets — edge focus expands exactly the two endpoints", () => {
  // Endpoints go straight into the OUTPUT set, never into `foci` — seeding foci
  // would expand both endpoints' entire data neighborhoods (the R6 trap).
  const graph: RFGraph = {
    nodes: [
      node("a"),
      node("b", { params: [{ name: "x", value: "${a.o}", is_dynamic: true, source: null }] }),
      node("c", { params: [{ name: "y", value: "${a.o}", is_dynamic: true, source: null }] }),
      node("d", { params: [{ name: "z", value: "${a.o}", is_dynamic: true, source: null }] }),
    ],
    edges: [
      edge("e_seq", "a", "b", "sequential"),
      edge("e_ab", "a", "b", "data_flow", { output_field: "o", input_name: "x" }),
      edge("e_ac", "a", "c", "data_flow", { output_field: "o", input_name: "y" }),
      edge("e_ad", "a", "d", "data_flow", { output_field: "o", input_name: "z" }),
    ],
    groups: [],
  };

  it("a data-edge focus expands {source, target} — NOT the endpoints' other data partners", () => {
    expect([...expandTargets(graph, "e_ab")].sort()).toEqual(["a", "b"]);
  });

  it("a control-edge focus expands nothing (node-level endpoints already read fine)", () => {
    expect(expandTargets(graph, "e_seq").size).toBe(0);
  });

  it("an IO-port endpoint contributes its OWNER (the line must land on a rendered row)", () => {
    const g: RFGraph = {
      nodes: [
        node("p", { kind: "input", io: { data_type: "string", required: true, default: null } }),
        node("b", { params: [{ name: "x", value: "${p}", is_dynamic: true, source: null }] }),
      ],
      edges: [edge("e_pb", "p", "b", "data_flow", { input_name: "x" })],
      groups: [group("w_in", { kind: "input_wrapper", members: ["p"] })],
    };
    expect([...expandTargets(g, "e_pb")].sort()).toEqual(["b", "w_in"]);
  });
});

describe("rowTouches — the row-hover touch set (reads FLOW edges, not the contract)", () => {
  const flowEdges = [
    { id: "e1", source: "n1", target: "n2", sourceHandle: outputHandle("result"), targetHandle: paramHandle("inputs") },
    { id: "e2", source: "n1", target: "n3", sourceHandle: outputHandle("result"), targetHandle: NODE_IN },
    { id: "e3", source: "n0", target: "n1", sourceHandle: NODE_OUT, targetHandle: paramHandle("prompt") },
    // a loop's self-edge: hovering the loop row must not ring the node itself
    { id: "e4", source: "n1", target: "n1", sourceHandle: NODE_OUT, targetHandle: LOOP_ROW },
  ] as FlowEdge[];

  it("an output row marks every consumer its edges reach AND the edges themselves", () => {
    expect([...rowTouches(flowEdges, "n1", [outputHandle("result")])].sort()).toEqual(["e1", "e2", "n2", "n3"]);
  });

  it("a param row marks its producer + the line", () => {
    expect([...rowTouches(flowEdges, "n1", [paramHandle("prompt")])].sort()).toEqual(["e3", "n0"]);
  });

  it("an io row matches on EITHER of its two handles", () => {
    const ioEdges = [
      { id: "a", source: "g1", target: "x", sourceHandle: portHandle("p9"), targetHandle: NODE_IN },
      { id: "b", source: "y", target: "g1", sourceHandle: NODE_OUT, targetHandle: portTargetHandle("p9") },
    ] as FlowEdge[];
    expect([...rowTouches(ioEdges, "g1", [portHandle("p9"), portTargetHandle("p9")])].sort()).toEqual(["a", "b", "x", "y"]);
  });

  it("a self-edge's LINE lights but its far end never rings; a handle with no edges marks nothing", () => {
    expect([...rowTouches(flowEdges, "n1", [LOOP_ROW])]).toEqual(["e4"]);
    expect(rowTouches(flowEdges, "n1", [paramHandle("ghost")]).size).toBe(0);
  });
});
