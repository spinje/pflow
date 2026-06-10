import { describe, expect, it } from "vitest";

import {
  applyFocus,
  buildFlow,
  type BuildOptions,
  COLLAPSED_GROUP_HEIGHT,
  COLLAPSED_GROUP_WIDTH,
  expandTargets,
  type FlowNode,
  HEADER_HEIGHT,
} from "./flow";
import {
  branchHandle,
  handleType,
  LOOP_ROW,
  NODE_IN,
  NODE_OUT,
  outputHandle,
  paramHandle,
  portHandle,
  portTargetHandle,
} from "./handles";
import { layoutGraph } from "./layout";
import { METRICS } from "./metrics";
import { CONDITION_COLOR, IO_COLOR, kindColor } from "../utils/format";
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
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, ...over };
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

describe("buildFlow — a batched sub-workflow IS a sub-workflow WITH batch (H8 + shell skip)", () => {
  // A dynamic-batch-of-subworkflow host backs TWO groups: a batch container with NO
  // direct members (a decorator SHELL) wrapping the workflow container. The shell is
  // never rendered (user decision 2026-06-10: batch is a modifier — deck + ×N badge —
  // not a box to travel through): the workflow group reparents past it, becomes the
  // host's representative (edges/title), and clicking the collapsed card opens the
  // sub-workflow body directly.
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

  it("skips the shell, reparents the workflow group, and re-anchors host edges onto it", () => {
    const { nodes, edges } = buildFlow(graph, DETAILED);
    expect(nodes.find((n) => n.id === "g_batch")).toBeUndefined(); // shell never renders
    expect(edges.find((e) => e.id === "e0")?.target).toBe("g_wf");
    const wf = nodes.find((n) => n.id === "g_wf");
    expect(wf?.type).toBe("group");
    if (wf?.type !== "group") return;
    expect(wf.parentId).toBeUndefined(); // reparented past the shell
    expect(wf.data.showTitle).toBe(true); // the workflow group carries title + batch badge
  });

  it("an empty batch shell around a plain leaf never renders — the leaf is the node", () => {
    // The contract shape for a dynamic batch of a simple node: the leaf renders
    // (not a host), the batch group is empty decoration ("▸ 0 nodes" card bug).
    const plain: RFGraph = {
      nodes: [
        node("a"),
        node("b", {
          batch: { parallel: true, dynamic: true, as_name: "f", source_ref: "${files}", count: null, items: null },
        }),
      ],
      edges: [edge("e0", "a", "b", "sequential")],
      groups: [group("gb", { kind: "batch", host: "b", nesting_depth: 1 })],
    };
    const { nodes, edges } = buildFlow(plain, COMPACT);
    expect(nodes.find((n) => n.id === "gb")).toBeUndefined();
    const leaf = nodes.find((n) => n.id === "b");
    expect(leaf?.type).toBe("node"); // a normal, selectable node — batch rides as deck/badge
    expect(edges.find((e) => e.id === "e0")?.target).toBe("b");
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

describe("buildFlow — collapsed group is a CARD (leaf anatomy, 2026-06-10 redesign)", () => {
  // n0 → host(g0) → n2; g0 nests g1; an IO port and the host itself must not count
  // as steps. The internal edge (inner → deep) re-anchors to g0 on both ends and is
  // dropped — it must NOT light the card's connector flares.
  const graph: RFGraph = {
    nodes: [
      node("n0"),
      node("host", { kind: "workflow", is_group_host: true }),
      node("inner", { parent: "g0" }),
      node("deep", { parent: "g1" }),
      node("io1", { kind: "input", io: { data_type: null, required: true }, parent: "g0" }),
      node("n2"),
      node("iso"),
    ],
    edges: [
      edge("e_in", "n0", "host", "sequential"),
      edge("e_out", "host", "n2", "sequential"),
      edge("e_internal", "inner", "deep", "sequential"),
    ],
    groups: [
      group("g0", { host: "host", members: ["inner", "io1"] }),
      group("g1", { parent: "g0", members: ["deep"], nesting_depth: 1 }),
    ],
  };
  const collapsedTD: BuildOptions = { ...TD, collapsed: new Set(["g0"]) };

  it("sizes the card and carries flow-edge control incidence + recursive step count", () => {
    const { nodes } = buildFlow(graph, collapsedTD);
    const g = nodes.find((n) => n.id === "g0");
    expect(g?.type).toBe("group");
    if (g?.type !== "group") return;
    expect(g.width).toBe(COLLAPSED_GROUP_WIDTH);
    expect(g.height).toBe(COLLAPSED_GROUP_HEIGHT);
    expect(g.data.hasIncoming).toBe(true); // n0 → host re-anchors onto the card
    expect(g.data.hasOutgoing).toBe(true); // host → n2 leaves the card
    // inner + deep; the IO port and the suppressed host are not "steps".
    expect(g.data.memberCount).toBe(2);
  });

  it("a purely-internal edge lights no flare", () => {
    const internalOnly: RFGraph = {
      ...graph,
      edges: [edge("e_internal", "inner", "deep", "sequential")],
    };
    const { nodes } = buildFlow(internalOnly, collapsedTD);
    const g = nodes.find((n) => n.id === "g0");
    if (g?.type !== "group") throw new Error("g0 missing");
    expect(g.data.hasIncoming).toBe(false);
    expect(g.data.hasOutgoing).toBe(false);
  });

  it("focus dims a collapsed card like a leaf, but never an expanded region", () => {
    const collapsedBuild = buildFlow(graph, collapsedTD);
    const dimmedCard = applyFocus(collapsedBuild.nodes, collapsedBuild.edges, "iso").nodes.find((n) => n.id === "g0");
    if (dimmedCard?.type !== "group") throw new Error("g0 missing");
    expect(dimmedCard.data.dimmed).toBe(true);

    const expandedBuild = buildFlow(graph, TD);
    const region = applyFocus(expandedBuild.nodes, expandedBuild.edges, "iso").nodes.find((n) => n.id === "g0");
    if (region?.type !== "group") throw new Error("g0 missing");
    expect(region.data.dimmed).toBe(false);
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


  it("the branch CONDITION rides the edge in TD and the BranchPorts row in LR — advanced or focus-expanded only", () => {
    const withCondition: RFGraph = {
      nodes: [node("dec", { is_decision: true, kind: "code" }), node("a"), node("b")],
      edges: [
        edge("e0", "dec", "a", "branch", { label: "big", condition: "if len(items) > 5" }),
        edge("e1", "dec", "b", "branch", { label: "small", condition: "else" }),
      ],
      groups: [],
    };
    const leafConditions = (built: { nodes: FlowNode[] }, id: string): Record<string, string> | null => {
      const n = built.nodes.find((fn) => fn.id === id);
      return n?.type === "node" ? n.data.branchConditions : null;
    };
    const pillShown = (built: { edges: { id: string; data?: { conditionShown?: boolean } }[] }, id: string): boolean =>
      built.edges.find((e) => e.id === id)?.data?.conditionShown === true;
    // The raw condition ALWAYS rides the edge (so focus can reveal it later)...
    const plain = buildFlow(withCondition, TD);
    expect(plain.edges.find((e) => e.id === "e0")?.data?.condition).toBe("if len(items) > 5");
    // ...but the pill is hidden by default in beautiful (conditionShown false)
    expect(pillShown(plain, "e0")).toBe(false);
    // TD advanced: no rows in TD — the pill shows on the edge
    const tdAdv = buildFlow(withCondition, { density: "detailed", direction: "TD", collapsed: new Set() });
    expect(pillShown(tdAdv, "e0")).toBe(true);
    // LR advanced: the BranchPorts ROW is the condition's home — the edge shows no pill
    // (mid-path pills clipped under cards / floated on backward wraps; user-caught)
    const adv = buildFlow(withCondition, DETAILED);
    expect(pillShown(adv, "e0")).toBe(false);
    expect(leafConditions(adv, "dec")).toEqual({ big: "if len(items) > 5", small: "else" });
    expect(leafConditions(buildFlow(withCondition, COMPACT), "dec")).toEqual({});
    // ...and shown while the condition node is focus-expanded (expansion re-runs build)
    const expanded = buildFlow(withCondition, { ...TD, expanded: new Set(["dec"]) });
    expect(pillShown(expanded, "e0")).toBe(true);
    expect(pillShown(expanded, "e1")).toBe(true);
    const expandedLR = buildFlow(withCondition, { ...COMPACT, expanded: new Set(["dec"]) });
    expect(leafConditions(expandedLR, "dec")).toEqual({ big: "if len(items) > 5", small: "else" });
    expect(pillShown(expandedLR, "e0")).toBe(false);
  });

  it("LR target entries get their outcome label whenever the source's rows show", () => {
    const withCondition: RFGraph = {
      nodes: [node("dec", { is_decision: true, kind: "code" }), node("a"), node("b")],
      edges: [edge("e0", "dec", "a", "branch", { label: "big", condition: "if len(items) > 5" })],
      groups: [],
    };
    // beautiful unfocused: the skeleton stays quiet — no label on the LR edge
    expect(buildFlow(withCondition, COMPACT).edges.find((e) => e.id === "e0")?.label).toBeUndefined();
    // rows showing (advanced / source focus-expanded): the target is labeled, TD-style
    expect(buildFlow(withCondition, DETAILED).edges.find((e) => e.id === "e0")?.label).toBe("big");
    const expanded = buildFlow(withCondition, { ...COMPACT, expanded: new Set(["dec"]) });
    expect(expanded.edges.find((e) => e.id === "e0")?.label).toBe("big");
  });

  it("clicking a branch TARGET reveals its condition — TD on the edge, LR on the source's row (applyFocus)", () => {
    const withCondition: RFGraph = {
      nodes: [node("dec", { is_decision: true, kind: "code" }), node("a"), node("b")],
      edges: [
        edge("e0", "dec", "a", "branch", { label: "big", condition: "if len(items) > 5" }),
        edge("e1", "dec", "b", "branch", { label: "small", condition: "else" }),
      ],
      groups: [],
    };
    // TD: the edge pill above the clicked target
    const built = buildFlow(withCondition, TD);
    const focused = applyFocus(built.nodes, built.edges, "a");
    // the clicked target's own pill reveals; the sibling's does not
    expect(focused.edges.find((e) => e.id === "e0")?.data?.conditionRevealed).toBe(true);
    expect(focused.edges.find((e) => e.id === "e1")?.data?.conditionRevealed).toBeUndefined();
    // clearing focus re-hides it
    const cleared = applyFocus(focused.nodes, focused.edges, null);
    expect(cleared.edges.find((e) => e.id === "e0")?.data?.conditionRevealed).toBeUndefined();

    // LR: the reveal lands on the SOURCE's BranchPorts row instead — an edge pill
    // at the target entry overlapped the clicked card (user-caught)
    const lr = buildFlow(withCondition, COMPACT);
    const lrFocused = applyFocus(lr.nodes, lr.edges, "a");
    expect(lrFocused.edges.find((e) => e.id === "e0")?.data?.conditionRevealed).toBeUndefined();
    const dec = lrFocused.nodes.find((n) => n.id === "dec");
    expect(dec?.type === "node" ? dec.data.revealedConditions : null).toEqual({ big: "if len(items) > 5" });
    const lrCleared = applyFocus(lrFocused.nodes, lrFocused.edges, null);
    const decCleared = lrCleared.nodes.find((n) => n.id === "dec");
    expect(decCleared?.type === "node" ? decCleared.data.revealedConditions : null).toBeUndefined();
  });

  it("a decision CODE node's fan-out leaves in the condition color, not code yellow", () => {
    const conditionGraph: RFGraph = {
      nodes: [node("route", { kind: "code", is_decision: true }), node("a", { kind: "code" })],
      edges: [edge("e0", "route", "a", "branch", { label: "go" })],
      groups: [],
    };
    const { edges } = buildFlow(conditionGraph, COMPACT);
    const e0 = edges.find((e) => e.id === "e0");
    expect(e0?.data?.sourceColor).toBe(CONDITION_COLOR);
    expect(e0?.data?.targetColor).toBe(kindColor("code")); // plain code target stays yellow
  });
});

describe("buildFlow — IO ports are rows on their OWNER node (group / root IO card)", () => {
  function ioInput(id: string, name: string, required = false): RFNode {
    return node(id, {
      kind: "input",
      io: { data_type: "string", required },
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
});

describe("buildFlow — ROOT IO wrappers become standalone IO cards", () => {
  function rootInput(id: string, name: string, required = false): RFNode {
    return node(id, {
      kind: "input",
      io: { data_type: "string", required },
      parent: "g_in",
      ref: { node_id: name, ancestor_path: [], port: "in" },
    });
  }
  function rootOutput(id: string, name: string, description = ""): RFNode {
    return node(id, {
      kind: "output",
      io: { data_type: null, required: false },
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
    return node(id, { kind, io: { data_type: null, required: false }, parent: wrapper });
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

  it("a root cycle (no entry) falls back to the FIRST root step", () => {
    const g: RFGraph = {
      nodes: [rootIO("inA", "g_in", "input"), node("a"), node("b")],
      edges: [edge("e0", "a", "b", "sequential"), edge("e1", "b", "a", "branch", { label: "retry" })],
      groups: [group("g_in", { kind: "input_wrapper", members: ["inA"] })],
    };
    const { edges: es } = buildFlow(g, COMPACT);
    expect(es.find((e) => e.id === "io-flow:g_in->a")).toBeDefined();
    expect(es.filter((e) => e.id.startsWith("io-flow:")).length).toBe(1);
  });

  it("no root wrappers → no io-flow edges (zero-IO workflows unchanged)", () => {
    const g: RFGraph = { nodes: [node("a"), node("b")], edges: [edge("e0", "a", "b", "sequential")], groups: [] };
    expect(buildFlow(g, COMPACT).edges.some((e) => e.id.startsWith("io-flow:"))).toBe(false);
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
      // data.loop is the LABEL switch (loop-row design) — a LEAF edge never carries
      // it; the ↻ row / read panel hold the condition. See the loop-U describe.
      expect(loop?.data?.kind).toBe("loop");
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

describe("loop U — row landing + label policy (2026-06-10 loop-row design)", () => {
  const LOOP = { polarity: "while" as const, condition: "${a.go}", cap: 5, carry: {} };
  const leafGraph: RFGraph = {
    nodes: [node("a", { loop: LOOP })],
    edges: [],
    groups: [],
  };
  const groupGraph: RFGraph = {
    nodes: [node("host", { kind: "workflow", is_group_host: true, loop: LOOP }), node("body", { parent: "g0" })],
    edges: [],
    groups: [group("g0", { host: "host", members: ["body"] })],
  };
  const loopEdge = (edges: { id: string }[]): (typeof edges)[number] | undefined =>
    edges.find((e) => e.id.startsWith("loop:"));

  it("advanced leaf: the U lands ON the ↻ loop-rule row, with no floating label", () => {
    const { nodes, edges } = buildFlow(leafGraph, DETAILED);
    const e = loopEdge(edges) as ReturnType<typeof buildFlow>["edges"][number] | undefined;
    expect(e?.targetHandle).toBe(LOOP_ROW);
    expect(handleType(LOOP_ROW)).toBe("target"); // the silent-drop class
    expect(e?.data?.loop).toBeUndefined(); // the row carries the rule — no pill
    // leafSize counts the loop row: one row, no params/outputs.
    const leaf = nodes.find((n) => n.id === "a");
    expect(leaf?.height).toBeGreaterThan(HEADER_HEIGHT); // body grew for the row
  });

  it("beautiful leaf: a bare U into NODE_IN — the skeleton stays quiet", () => {
    const { nodes, edges } = buildFlow(leafGraph, COMPACT);
    const e = loopEdge(edges) as ReturnType<typeof buildFlow>["edges"][number] | undefined;
    expect(e?.targetHandle).toBe(NODE_IN);
    expect(e?.data?.loop).toBeUndefined();
    expect(nodes.find((n) => n.id === "a")?.height).toBe(HEADER_HEIGHT); // no row in compact
  });

  it("focus-expanded leaf (beautiful) lands on the row like advanced", () => {
    const { edges } = buildFlow(leafGraph, { ...COMPACT, expanded: new Set(["a"]) });
    expect((loopEdge(edges) as { targetHandle?: string } | undefined)?.targetHandle).toBe(LOOP_ROW);
  });

  it("group anchor: floating label in advanced only (regions have no rows)", () => {
    const adv = buildFlow(groupGraph, DETAILED);
    const eAdv = loopEdge(adv.edges) as ReturnType<typeof buildFlow>["edges"][number] | undefined;
    expect(eAdv?.targetHandle).toBe(NODE_IN);
    expect(eAdv?.data?.loop).toEqual(LOOP); // label shows in advanced

    const beau = buildFlow(groupGraph, COMPACT);
    const eBeau = loopEdge(beau.edges) as ReturnType<typeof buildFlow>["edges"][number] | undefined;
    expect(eBeau?.data?.loop).toBeUndefined(); // hidden in beautiful
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

  it("TD: an edge INTO an expanded group lays out (elkjs crashes on compound ports)", async () => {
    // Regression pin: declaring an ELK port on a COMPOUND node and routing an edge
    // to it throws "NEdge must have a source and target NNode specified" under
    // INCLUDE_CHILDREN (found in-browser 2026-06-10 — the in-process smoke above
    // missed it because its group had no incoming edge). Expanded groups must stay
    // port-less; only leaves and collapsed groups join the `portable` set.
    const graph: RFGraph = {
      nodes: [
        node("ext"),
        node("host", { kind: "workflow", is_group_host: true }),
        node("body", { parent: "g0" }),
      ],
      edges: [edge("e0", "ext", "host", "sequential")],
      groups: [group("g0", { host: "host", members: ["body"] })],
    };
    const { nodes, edges } = buildFlow(graph, TD); // expanded (nothing collapsed)
    const laidOut = await layoutGraph(nodes, edges, "TD");
    expect(laidOut).toHaveLength(nodes.length);
    for (const n of laidOut) {
      expect(Number.isFinite(n.position.x)).toBe(true);
    }
  });

  it("advanced region: the inputs SIDEBAR reserves left padding — the body lays out beside it", async () => {
    // The sidebar is ELK left padding (layout.ts groupPadding): the body's first
    // layer starts BESIDE the inputs column, not below it. Also exercises the new
    // hierarchical IO edge shapes (group -> own child, parent node -> group row)
    // against the real option set — the elkjs crash family is option-dependent.
    const graph: RFGraph = {
      nodes: [
        node("feeder"),
        node("host", { kind: "workflow", is_group_host: true }),
        node("inA", {
          kind: "input",
          io: { data_type: null, required: true },
          parent: "g_in",
          ref: { node_id: "x", ancestor_path: [], port: "in" },
        }),
        node("body", { parent: "g_wf", params: [{ name: "p", value: "${x}", is_dynamic: true, source: null }] }),
      ],
      edges: [
        edge("seq", "feeder", "host", "sequential"),
        edge("bind", "feeder", "inA", "data_flow"),
        edge("consume", "inA", "body", "data_flow", { input_name: "p" }),
      ],
      groups: [
        group("g_wf", { kind: "workflow", host: "host", members: ["body"] }),
        group("g_in", { kind: "input_wrapper", parent: "g_wf", members: ["inA"] }),
      ],
    };
    const { nodes, edges } = buildFlow(graph, { ...DETAILED, direction: "TD" });
    const laidOut = await layoutGraph(nodes, edges, "TD");
    const body = laidOut.find((n) => n.id === "body");
    // child positions are parent-relative: the body clears the reserved sidebar
    expect((body?.position.x ?? 0) >= METRICS.ioSidebarW).toBe(true);
  });
});

describe("edge types — every control kind is gradient-stroked (the component owns its color)", () => {
  // error/end included: they fade into the node's type color at the node ends
  // (GradientEdge). If one regressed to "default", CSS would have no stroke for it
  // and the edge would render invisibly.
  const graph: RFGraph = {
    nodes: [node("a", { is_decision: true }), node("b"), node("end0", { kind: "end" })],
    edges: [
      edge("seq", "a", "b", "sequential"),
      edge("br", "a", "b", "branch", { label: "ok" }),
      edge("err", "a", "b", "error"),
      edge("fin", "b", "end0", "end"),
      edge("df", "a", "b", "data_flow"),
    ],
    groups: [],
  };

  it("sequential/branch/error/end → gradient; data_flow → the custom data edge", () => {
    const { edges } = buildFlow(graph, DETAILED);
    for (const id of ["seq", "br", "err", "fin"]) {
      expect(edges.find((e) => e.id === id)?.type).toBe("gradient");
    }
    // DataEdge (not a built-in): it owns the rounded-orthogonal lane geometry AND
    // the stroke. CSS strokes nothing for data_flow anymore, so a regression to a
    // built-in type would render INVISIBLY — this pin is the guard.
    const df = edges.find((e) => e.id === "df");
    expect(df?.type).toBe("data");
    expect(df?.data?.lane).toBeGreaterThanOrEqual(0);
  });

  it("error/end edges carry both endpoint colors for the fade", () => {
    const { edges } = buildFlow(graph, DETAILED);
    const err = edges.find((e) => e.id === "err");
    expect(err?.data?.sourceColor).toBeTruthy();
    expect(err?.data?.targetColor).toBeTruthy();
  });
});

describe("focus-expansion — beautiful cards expand to rows (decided 2026-06-09)", () => {
  // a --seq--> b --data(stdout→data)--> c ; d is a control-only neighbor of c.
  const graph: RFGraph = {
    nodes: [
      node("a"),
      node("b"),
      node("c", { params: [{ name: "data", value: "${b.stdout}", is_dynamic: true, source: null }] }),
      node("d"),
      node("end0", { kind: "end" }),
    ],
    edges: [
      edge("seq", "a", "b", "sequential"),
      edge("df", "b", "c", "data_flow", { output_field: "stdout", input_name: "data" }),
      edge("seq2", "c", "d", "sequential"),
      edge("fin", "d", "end0", "end"),
    ],
    groups: [],
  };

  it("expandTargets: the focused leaf + its data-flow endpoints; control-only neighbors stay compact", () => {
    const targets = expandTargets(graph, "c");
    expect(targets.has("c")).toBe(true); // the clicked node itself
    expect(targets.has("b")).toBe(true); // data-flow endpoint
    expect(targets.has("d")).toBe(false); // control-only neighbor
    expect(targets.has("a")).toBe(false);
    expect(expandTargets(graph, null).size).toBe(0);
  });

  it("expandTargets: end sinks never expand", () => {
    expect(expandTargets(graph, "d").has("end0")).toBe(false);
  });

  it("an expanded card is flagged and takes the advanced box", () => {
    const expanded = expandTargets(graph, "c");
    const { nodes } = buildFlow(graph, { ...COMPACT, expanded });
    const c = nodes.find((n) => n.id === "c");
    const a = nodes.find((n) => n.id === "a");
    expect(c?.type === "node" && c.data.expanded).toBe(true);
    expect(a?.type === "node" && a.data.expanded).toBe(false);
    // advanced box: wider than compact, taller than the fixed header
    expect(c?.width).toBeGreaterThan(a?.width ?? 0);
    expect(c?.height).toBeGreaterThan(a?.height ?? 0);
  });

  it("a data line between two expanded cards lands row-to-row and drops its label", () => {
    const expanded = expandTargets(graph, "c");
    const { edges } = buildFlow(graph, { ...COMPACT, expanded });
    const df = edges.find((e) => e.id === "df");
    expect(df?.sourceHandle).toBe(outputHandle("stdout"));
    expect(df?.targetHandle).toBe(paramHandle("data"));
    expect(df?.label).toBeUndefined(); // the rows themselves name the fields
    // handle types stay correct (the silent-drop class)
    expect(handleType(df!.sourceHandle!)).toBe("source");
    expect(handleType(df!.targetHandle!)).toBe("target");
    // still default-hidden — applyFocus reveals it (it is incident to the focus)
    expect(df?.hidden).toBe(true);
    const revealed = applyFocus(buildFlow(graph, { ...COMPACT, expanded }).nodes, edges, "c");
    expect(revealed.edges.find((e) => e.id === "df")?.hidden).toBe(false);
  });

  it("a half-expanded data line keeps the node-level end AND its label", () => {
    // expand only the TARGET (c): the source side has no visible output row.
    const { edges } = buildFlow(graph, { ...COMPACT, expanded: new Set(["c"]) });
    const df = edges.find((e) => e.id === "df");
    expect(df?.sourceHandle).toBe(NODE_OUT);
    expect(df?.targetHandle).toBe(paramHandle("data"));
    expect(df?.label).toBe("stdout → data");
  });

  it("focus marks which END of a revealed data line the clicked node is on", () => {
    const built = buildFlow(graph, DETAILED);
    // focus the TARGET (c): line solid at c, fading back toward b
    const atTarget = applyFocus(built.nodes, built.edges, "c").edges.find((e) => e.id === "df");
    expect(atTarget?.data?.focusEnd).toBe("target");
    // focus the SOURCE (b): solid at b, fading toward c
    const atSource = applyFocus(built.nodes, built.edges, "b").edges.find((e) => e.id === "df");
    expect(atSource?.data?.focusEnd).toBe("source");
    // clearing focus clears the mark; control edges never carry one
    const cleared = applyFocus(built.nodes, built.edges, null).edges.find((e) => e.id === "df");
    expect(cleared?.data?.focusEnd).toBeUndefined();
    const ctrl = applyFocus(built.nodes, built.edges, "b").edges.find((e) => e.id === "seq");
    expect(ctrl?.data?.focusEnd).toBeUndefined();
  });

  it("parallel data edges at one node get DISTINCT lane offsets; control edges get none", () => {
    // Three bindings out of one node (and two into one consumer) used to share the
    // default 20px stub → pixel-exact overlap into one ambiguous line. The consumer
    // has real param rows so the two parallel lines land on distinct rows (same
    // shape as an Inputs node feeding one consumer's params).
    const g: RFGraph = {
      nodes: [
        node("src"),
        node("c1", {
          params: [
            { name: "a", value: "${src.x}", is_dynamic: true, source: null },
            { name: "b", value: "${src.y}", is_dynamic: true, source: null },
          ],
        }),
        node("c2"),
      ],
      edges: [
        edge("d1", "src", "c1", "data_flow", { input_name: "a" }),
        edge("d2", "src", "c1", "data_flow", { input_name: "b" }),
        edge("d3", "src", "c2", "data_flow", { input_name: "c" }),
        edge("s1", "src", "c1", "sequential"),
      ],
      groups: [],
    };
    const { edges } = buildFlow(g, DETAILED);
    const lanes = ["d1", "d2", "d3"].map((id) => edges.find((e) => e.id === id)?.data?.lane);
    // all assigned, and all distinct (they share the source node)
    expect(lanes.every((l) => typeof l === "number")).toBe(true);
    expect(new Set(lanes).size).toBe(3);
    expect(edges.find((e) => e.id === "s1")?.data?.lane).toBeUndefined();
  });

  it("input_name that is a dict KEY lands on the row of the param containing it", () => {
    // A code node's `inputs: {data: ${b.stdout}}`: the edge builder walks dict-of-
    // string leaves, so input_name is the KEY ("data"), not the param ("inputs").
    // The line must land on the inputs ROW (user-caught: it fell back to the node
    // top). A key whose value is NOT a ${...} string stays node-level (never guess).
    const g: RFGraph = {
      nodes: [
        node("b"),
        node("c", {
          params: [
            { name: "static", value: { data: 42 }, is_dynamic: false, source: null },
            { name: "inputs", value: { data: "${b.stdout}" }, is_dynamic: true, source: null },
          ],
        }),
      ],
      edges: [edge("df", "b", "c", "data_flow", { output_field: "stdout", input_name: "data" })],
      groups: [],
    };
    const { edges } = buildFlow(g, DETAILED);
    const df = edges.find((e) => e.id === "df");
    expect(df?.targetHandle).toBe(paramHandle("inputs"));
    expect(handleType(df!.targetHandle!)).toBe("target");
  });

  it("expansion is ignored in advanced density (everything already shows rows)", () => {
    const { nodes } = buildFlow(graph, { ...DETAILED, expanded: new Set(["c"]) });
    const c = nodes.find((n) => n.id === "c");
    expect(c?.type === "node" && c.data.expanded).toBe(false);
  });

  it("expandTargets: focusing an IO card (wrapper id) expands the consumers of all its member ports", () => {
    const g: RFGraph = {
      nodes: [
        node("in1", { kind: "input", io: { data_type: null, required: true }, parent: "gw" }),
        node("c1", { params: [{ name: "p", value: "${in1}", is_dynamic: true, source: null }] }),
      ],
      edges: [edge("df", "in1", "c1", "data_flow", { input_name: "p" })],
      groups: [group("gw", { kind: "input_wrapper", members: ["in1"] })],
    };
    const viaPortsNode = expandTargets(g, "gw");
    expect(viaPortsNode.has("c1")).toBe(true); // the consumer card expands…
    expect(viaPortsNode.has("in1")).toBe(false); // …the port itself is already a row
    const viaSinglePort = expandTargets(g, "in1");
    expect(viaSinglePort.has("c1")).toBe(true);
  });
});
