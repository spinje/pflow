// IO presentation tests: ports as rows on their OWNER node (group / root IO
// card) and the root cards joining the control skeleton. Split from
// flow.test.ts beside their subject (io.ts) — architecture-review candidate 2,
// 2026-06-13.

import { describe, expect, it } from "vitest";

import { applyFocus, expandTargets } from "./focus";
import { buildFlow } from "./flow";
import { NODE_IN, NODE_OUT, portHandle, portTargetHandle } from "./handles";
import { IO_COLOR } from "../utils/format";
import { COMPACT, DETAILED, edge, group, node } from "./testFixtures";
import type { RFGraph, RFNode } from "../types";

describe("buildFlow — IO ports are rows on their OWNER node (group / root IO card)", () => {
  function ioInput(id: string, name: string, required = false): RFNode {
    return node(id, {
      kind: "input",
      io: { data_type: "string", required, default: null },
      parent: "g_in",
      ref: { node_id: name, ancestor_path: [], port: "in" },
    });
  }
  // A NESTED workflow's wrapper (parent = the workflow group): its rows live on
  // the GROUP node — no separate table node exists.
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

  it("a nested wrapper's ports ride the GROUP node's data; no per-port nodes, no table node", () => {
    for (const view of [DETAILED, COMPACT]) {
      const { nodes } = buildFlow(graph, view);
      expect(nodes.find((n) => n.id === "g_in")).toBeUndefined(); // no table node
      expect(nodes.find((n) => n.id === "inA")).toBeUndefined(); // not a separate node
      const wf = nodes.find((n) => n.id === "g_wf");
      expect(wf?.type === "group" ? wf.data.inputs.map((p) => p.name) : []).toEqual(["repo_dir", "plan"]);
      // an OPEN region always shows its rows — BOTH densities (an open container
      // hiding its inputs reads as "has none"; beautiful hides only the EDGES)
      expect(wf?.type === "group" ? wf.data.ioRowsVisible : null).toBe(true);
    }
  });

  it("a COLLAPSED card keeps the leaf showBody rule: rows in advanced / focus-expanded only", () => {
    const collapsed = new Set(["g_wf"]);
    const beau = buildFlow(graph, { ...COMPACT, collapsed });
    const card = beau.nodes.find((n) => n.id === "g_wf");
    expect(card?.type === "group" ? card.data.ioRowsVisible : null).toBe(false);
    const adv = buildFlow(graph, { ...DETAILED, collapsed });
    const advCard = adv.nodes.find((n) => n.id === "g_wf");
    expect(advCard?.type === "group" ? advCard.data.ioRowsVisible : null).toBe(true);
  });

  it("advanced: re-anchors each port's edge onto its OWN row handle on the group, keeping original endpoints", () => {
    const { edges } = buildFlow(graph, DETAILED);
    // input FEEDS a consumer → its row's source handle (a group -> own-child edge)
    const e0 = edges.find((e) => e.id === "e0");
    expect(e0?.source).toBe("g_wf");
    expect(e0?.sourceHandle).toBe(portHandle("inA"));
    expect(e0?.data?.from).toBe("inA"); // original endpoint kept for focus
    expect(e0?.data?.to).toBe("body");
    // a binding RECEIVES into the same input → its row's TARGET handle
    const bind = edges.find((e) => e.id === "bind");
    expect(bind?.target).toBe("g_wf");
    expect(bind?.targetHandle).toBe(portTargetHandle("inA"));
  });

  it("rows hidden (collapsed card, beautiful) → IO edges land node-level; focus-expanded → row", () => {
    // An OPEN region shows rows in both densities, so the hidden case is the
    // COLLAPSED card in beautiful: the binding lands on the card's node handle —
    // never a handle that doesn't render.
    const collapsed = new Set(["g_wf"]);
    const beau = buildFlow(graph, { ...COMPACT, collapsed });
    expect(beau.edges.find((e) => e.id === "bind")?.targetHandle).toBe(NODE_IN);
    // ...and rows visible per-OWNER when the collapsed card is focus-expanded
    const expanded = buildFlow(graph, { ...COMPACT, collapsed, expanded: new Set(["g_wf"]) });
    expect(expanded.edges.find((e) => e.id === "bind")?.targetHandle).toBe(portTargetHandle("inA"));
    // beautiful OPEN region: rows render and the binding lands on the row — but the
    // line itself stays default-hidden (the skeleton rule governs LINES, not rows)
    const open = buildFlow(graph, COMPACT);
    expect(open.edges.find((e) => e.id === "bind")?.targetHandle).toBe(portTargetHandle("inA"));
    expect(open.edges.find((e) => e.id === "bind")?.hidden).toBe(true);
  });

  it("beautiful: clicking ONE port reveals only its line + highlights its row on the group", () => {
    expect(buildFlow(graph, COMPACT).edges.filter((e) => e.data?.kind === "data_flow").every((e) => e.hidden)).toBe(true);

    // The real pipeline: focus derives the expansion set (the hook), the build
    // re-runs with it (rows render, parallel bindings keep distinct row handles),
    // THEN applyFocus decorates — never applyFocus on an unexpanded build.
    const built = buildFlow(graph, { ...COMPACT, expanded: expandTargets(graph, "inA") });
    const focused = applyFocus(built.nodes, built.edges, "inA");
    expect(focused.edges.find((e) => e.id === "e0")?.hidden).toBe(false); // repo_dir's line revealed
    expect(focused.edges.find((e) => e.id === "e1")?.hidden).toBe(true); // plan's stays hidden
    const wf = focused.nodes.find((n) => n.id === "g_wf");
    expect(wf?.type === "group" ? wf.data.focusedPortId : null).toBe("inA");
  });

  it("focusing the consumer reveals all of its input lines", () => {
    const built = buildFlow(graph, { ...COMPACT, expanded: expandTargets(graph, "body") });
    const focused = applyFocus(built.nodes, built.edges, "body");
    expect(focused.edges.find((e) => e.id === "e0")?.hidden).toBe(false);
    expect(focused.edges.find((e) => e.id === "e1")?.hidden).toBe(false);
  });

  it("expandTargets: an IO endpoint expands its OWNER so the line can land on the row", () => {
    // focusing the consumer pulls the group (the rows' owner) into the set
    expect(expandTargets(graph, "body")).toEqual(new Set(["body", "g_wf"]));
    // focusing a single port expands the owner + the consumer on the far end
    expect(expandTargets(graph, "inA")).toEqual(new Set(["g_wf", "body", "feeder"]));
  });

  it("expandTargets: `pinned` (the open panel's subject) stays in the set wherever focus goes", () => {
    // The 2026-06-12 chip-navigation bug: focus moves to the chip's target while
    // the panel stays on the old subject — without the pin, the card being read
    // contracted mid-read whenever the new focus's scan didn't reach it.
    // Self only: the pin adds the subject's card, never its neighborhood.
    expect(expandTargets(graph, "feeder", "body")).toEqual(new Set(["feeder", "g_wf", "body"]));
    // A pinned CONTAINER pins the card itself (its io rows render — it was
    // selected, so its panel is open).
    expect(expandTargets(graph, null, "g_wf")).toEqual(new Set(["g_wf"]));
    // A pinned EDGE id pins nothing (the matching focus arm expands endpoints).
    expect(expandTargets(graph, null, "e0").size).toBe(0);
  });
});

describe("buildFlow — ROOT IO wrappers become standalone IO cards", () => {
  function rootInput(id: string, name: string, required = false): RFNode {
    return node(id, {
      kind: "input",
      io: { data_type: "string", required, default: null },
      parent: "g_in",
      ref: { node_id: name, ancestor_path: [], port: "in" },
    });
  }
  function rootOutput(id: string, name: string, description = ""): RFNode {
    return node(id, {
      kind: "output",
      io: { data_type: null, required: false, default: null },
      parent: "g_out",
      purpose: description,
      ref: { node_id: name, ancestor_path: [], port: "out" },
    });
  }
  const graph: RFGraph = {
    nodes: [
      rootInput("inA", "repo_dir", true),
      rootInput("inB", "plan"),
      node("worker", { params: [{ name: "x", value: "${repo_dir}", is_dynamic: true, source: null }] }),
      rootOutput("outA", "result", "the final result"),
    ],
    edges: [
      edge("e0", "inA", "worker", "data_flow", { input_name: "x" }),
      edge("e1", "worker", "outA", "data_flow", { output_field: "stdout" }),
    ],
    groups: [
      group("g_in", { kind: "input_wrapper", members: ["inA", "inB"] }),
      group("g_out", { kind: "output_wrapper", members: ["outA"] }),
    ],
  };

  it("emits one IO card per root wrapper (wrapper id kept), rows visible per the showBody rule", () => {
    const adv = buildFlow(graph, { ...DETAILED, workflowName: "my-flow" });
    const card = adv.nodes.find((n) => n.id === "g_in");
    expect(card?.type).toBe("io");
    if (card?.type !== "io") throw new Error("expected io card");
    expect(card.data.kind).toBe("input");
    expect(card.data.workflowName).toBe("my-flow");
    expect(card.data.ports.map((p) => p.name)).toEqual(["repo_dir", "plan"]);
    expect(card.data.rowsVisible).toBe(true);
    // outputs surface their authored description (purpose) on the port
    const out = adv.nodes.find((n) => n.id === "g_out");
    expect(out?.type === "io" ? out.data.ports[0]?.description : null).toBe("the final result");

    // beautiful: a quiet compact card — no rows, smaller box
    const beau = buildFlow(graph, COMPACT);
    const compactCard = beau.nodes.find((n) => n.id === "g_in");
    expect(compactCard?.type === "io" ? compactCard.data.rowsVisible : null).toBe(false);
    expect(compactCard?.height).toBeLessThan(card.height ?? 0);
  });

  it("advanced: IO edges land on the card's row handles; beautiful: node-level until focus-expanded", () => {
    const adv = buildFlow(graph, DETAILED);
    expect(adv.edges.find((e) => e.id === "e0")?.source).toBe("g_in");
    expect(adv.edges.find((e) => e.id === "e0")?.sourceHandle).toBe(portHandle("inA"));
    expect(adv.edges.find((e) => e.id === "e1")?.target).toBe("g_out");
    expect(adv.edges.find((e) => e.id === "e1")?.targetHandle).toBe(portTargetHandle("outA"));

    const beau = buildFlow(graph, COMPACT);
    expect(beau.edges.find((e) => e.id === "e0")?.sourceHandle).toBe(NODE_OUT);
    // clicking the card (its wrapper id) expands it AND its consumers
    expect(expandTargets(graph, "g_in")).toEqual(new Set(["g_in", "worker"]));
    const expanded = buildFlow(graph, { ...COMPACT, expanded: expandTargets(graph, "g_in") });
    expect(expanded.edges.find((e) => e.id === "e0")?.sourceHandle).toBe(portHandle("inA"));
  });
});

describe("buildFlow — root IO cards join the control SKELETON (io-flow edges)", () => {
  // The Inputs card heads the flow (a control-style edge into each entry step) and
  // every terminal's representative runs into the Outputs card — the cards behave
  // like nodes: ELK lays them into the spine and their tiles grow connector flares
  // (incidence flags). NOT contract edges — pure visual policy, drawn in BOTH
  // densities (structure, like forks).
  function rootIO(id: string, wrapper: string, kind: "input" | "output"): RFNode {
    return node(id, { kind, io: { data_type: null, required: false, default: null }, parent: wrapper });
  }
  const chain: RFGraph = {
    nodes: [rootIO("inA", "g_in", "input"), node("first"), node("last", { is_terminal: true }), rootIO("outA", "g_out", "output")],
    edges: [edge("e0", "first", "last", "sequential")],
    groups: [
      group("g_in", { kind: "input_wrapper", members: ["inA"] }),
      group("g_out", { kind: "output_wrapper", members: ["outA"] }),
    ],
  };

  it("Inputs → entry step and terminal → Outputs, as control edges in both densities", () => {
    for (const opts of [COMPACT, DETAILED]) {
      const { nodes: ns, edges: es } = buildFlow(chain, opts);
      const inEdge = es.find((e) => e.id === "io-flow:g_in->first");
      expect(inEdge).toBeDefined();
      expect(inEdge?.type).toBe("gradient");
      expect(inEdge?.hidden).toBeFalsy();
      expect(inEdge?.sourceHandle).toBe(NODE_OUT);
      expect(inEdge?.targetHandle).toBe(NODE_IN);
      expect(inEdge?.data?.kind).toBe("sequential");
      expect(inEdge?.data?.sourceColor).toBe(IO_COLOR);
      const outEdge = es.find((e) => e.id === "io-flow:last->g_out");
      expect(outEdge?.data?.targetColor).toBe(IO_COLOR);

      // Incidence flags drive the flares: the cards AND the entry/terminal steps.
      const flag = (id: string) => {
        const n = ns.find((x) => x.id === id);
        return n && n.type !== "end" ? { in: n.data.hasIncoming, out: n.data.hasOutgoing } : null;
      };
      expect(flag("g_in")).toEqual({ in: false, out: true });
      expect(flag("g_out")).toEqual({ in: true, out: false });
      expect(flag("first")).toEqual({ in: true, out: true });
    }
  });

  it("a terminal sub-workflow host anchors the Outputs edge on its GROUP", () => {
    const g: RFGraph = {
      nodes: [
        rootIO("inA", "g_in", "input"),
        node("host", { kind: "workflow", is_group_host: true, is_terminal: true }),
        node("body", { parent: "g_wf" }),
        rootIO("outA", "g_out", "output"),
      ],
      edges: [],
      groups: [
        group("g_in", { kind: "input_wrapper", members: ["inA"] }),
        group("g_wf", { kind: "workflow", host: "host", members: ["body"] }),
        group("g_out", { kind: "output_wrapper", members: ["outA"] }),
      ],
    };
    const { edges: es } = buildFlow(g, COMPACT);
    expect(es.find((e) => e.id === "io-flow:g_wf->g_out")).toBeDefined();
    // host is also the sole entry — the Inputs edge re-anchors onto the group too
    expect(es.find((e) => e.id === "io-flow:g_in->g_wf")).toBeDefined();
  });

  it("a final leaf FEEDING a declared output still runs into the Outputs card", () => {
    // The lyrics-generator bug (user-caught 2026-06-11): the contract's is_terminal
    // counts DATA_FLOW out-edges, so the most natural authoring shape — the last
    // step's result sourced into a workflow output — read non-terminal and the
    // Outputs card floated with no io-flow edge. Sink-ness is now derived from
    // sequential/branch edges only; the data-flow out-edge must not disqualify.
    const g: RFGraph = {
      nodes: [
        rootIO("inA", "g_in", "input"),
        node("first"),
        node("last", { is_terminal: false }),
        rootIO("outA", "g_out", "output"),
      ],
      edges: [edge("e0", "first", "last", "sequential"), edge("e1", "last", "outA", "data_flow", { output_field: "result" })],
      groups: [
        group("g_in", { kind: "input_wrapper", members: ["inA"] }),
        group("g_out", { kind: "output_wrapper", members: ["outA"] }),
      ],
    };
    const { edges: es } = buildFlow(g, COMPACT);
    expect(es.find((e) => e.id === "io-flow:last->g_out")).toBeDefined();
    // `first` has a forward control successor — it is not a sink.
    expect(es.find((e) => e.id === "io-flow:first->g_out")).toBeUndefined();
  });

  it("a root cycle (no entry, no sink) falls back to FIRST root step in / LAST out", () => {
    const g: RFGraph = {
      nodes: [rootIO("inA", "g_in", "input"), node("a"), node("b"), rootIO("outA", "g_out", "output")],
      edges: [edge("e0", "a", "b", "sequential"), edge("e1", "b", "a", "branch", { label: "retry" })],
      groups: [
        group("g_in", { kind: "input_wrapper", members: ["inA"] }),
        group("g_out", { kind: "output_wrapper", members: ["outA"] }),
      ],
    };
    const { edges: es } = buildFlow(g, COMPACT);
    expect(es.find((e) => e.id === "io-flow:g_in->a")).toBeDefined();
    expect(es.find((e) => e.id === "io-flow:b->g_out")).toBeDefined();
    expect(es.filter((e) => e.id.startsWith("io-flow:")).length).toBe(2);
  });

  it("no root wrappers → no io-flow edges (zero-IO workflows unchanged)", () => {
    const g: RFGraph = { nodes: [node("a"), node("b")], edges: [edge("e0", "a", "b", "sequential")], groups: [] };
    expect(buildFlow(g, COMPACT).edges.some((e) => e.id.startsWith("io-flow:"))).toBe(false);
  });

  it("hasOutgoing is HANDLE-aware: an LR decision's outcomes leave rows, not NODE_OUT", () => {
    // The exit decorations (TD bottom flare, LR exit dot) mark the trunk leaving
    // NODE_OUT — a pure decider's branches leave its labeled BranchPorts rows in
    // LR, so it must NOT light an exit at the icon row.
    const g: RFGraph = {
      nodes: [node("dec", { is_decision: true }), node("a"), node("b"), node("seq")],
      edges: [
        edge("e0", "dec", "a", "branch", { label: "yes" }),
        edge("e1", "dec", "b", "branch", { label: "no" }),
        edge("e2", "seq", "dec", "sequential"),
      ],
      groups: [],
    };
    const { nodes: ns } = buildFlow(g, COMPACT); // LR
    const out = (id: string) => {
      const n = ns.find((x) => x.id === id);
      return n && n.type === "node" ? n.data.hasOutgoing : null;
    };
    expect(out("dec")).toBe(false); // branches leave rows — no icon-row exit
    expect(out("seq")).toBe(true); // the trunk leaves NODE_OUT
  });
});
