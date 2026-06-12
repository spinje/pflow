import { describe, expect, it } from "vitest";

import {
  applyFocus,
  buildFlow,
  type BuildOptions,
  COLLAPSED_GROUP_HEIGHT,
  COLLAPSED_GROUP_WIDTH,
  consumedReadPaths,
  expandTargets,
  type FieldReads,
  type FlowEdge,
  type FlowNode,
  HEADER_HEIGHT,
  outputRowsFor,
  rowAnchorsFor,
  rowTouches,
  SELECTED_EDGE_Z,
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
import { CONDITION_COLOR, IO_COLOR, TRANSFORM_COLOR, kindColor } from "../utils/format";
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
    is_transform: false,
    output_shape: null,
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
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [], ...over };
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

describe("buildFlow — LITERAL batches (the invisible-step hole, review-caught 2026-06-11)", () => {
  // Two contract shapes the old `members.length === 0` shell rule swallowed whole:
  // the node lost its only on-canvas representative and every edge touching it was
  // warn-dropped — the workflow shattered into islands at each literal batch step.

  it("a literal-batched LEAF renders as a normal node; its empty batch group stays a shell; spine edges survive", () => {
    // The confirmed repro contract (prep → fan[items ×3] → done): the host ships
    // is_group_host=false (the Python-side fix) + a memberless batch group.
    const graph: RFGraph = {
      nodes: [
        node("n0"),
        node("n1", {
          batch: { parallel: false, dynamic: false, as_name: "item", source_ref: null, count: 3, items: ["alice", "bob", "carol"] },
        }),
        node("n2"),
      ],
      edges: [edge("e0", "n0", "n1", "sequential"), edge("e1", "n1", "n2", "sequential")],
      groups: [group("g0", { kind: "batch", host: "n1", nesting_depth: 1 })],
    };
    const { nodes, edges } = buildFlow(graph, COMPACT);
    const leaf = nodes.find((n) => n.id === "n1");
    expect(leaf?.type).toBe("node"); // the step is VISIBLE (deck + ⧉ ×3 chip ride node.batch)
    expect(nodes.find((n) => n.id === "g0")).toBeUndefined(); // no item groups → still a shell
    expect(edges.find((e) => e.id === "e0")).toMatchObject({ source: "n0", target: "n1" });
    expect(edges.find((e) => e.id === "e1")).toMatchObject({ source: "n1", target: "n2" });
  });

  it("a literal batch OF SUB-WORKFLOWS renders its batch container as the host's representative — incl. truncation-re-anchored edges", () => {
    // The song-creator shape (user-caught): host=true + memberless batch group +
    // host=null item groups WITH members. A literal batch group holding expanded
    // item groups is NOT a shell — real item copies to reveal ("literal batches
    // keep their container"): it renders, carries the host's title/chips, and
    // anchors every edge touching the host. e2 mirrors the TRUNCATION shape
    // (craft-reviews: 5 items → 2 kept groups): the Python side re-anchors
    // hidden-item bindings to the HOST node-level (input_name cleared) — the
    // frontend must give that edge a real anchor too, never drop it.
    const graph: RFGraph = {
      nodes: [
        node("up"),
        node("host", {
          kind: "workflow",
          is_group_host: true,
          batch: {
            parallel: true,
            dynamic: false,
            as_name: "item",
            source_ref: null,
            count: 5,
            items: [{ workflow: "./c.pflow.md" }, { workflow: "./c.pflow.md" }, {}, {}, {}],
          },
        }),
        node("w0", { parent: "gi0" }),
        node("w1", { parent: "gi1" }),
        node("down"),
      ],
      edges: [
        edge("e0", "up", "host", "sequential"),
        edge("e1", "host", "down", "sequential"),
        edge("e2", "up", "host", "data_flow", { output_field: "stdout" }),
      ],
      groups: [
        group("g_batch", { kind: "batch", host: "host", nesting_depth: 1 }),
        group("gi0", { kind: "workflow", parent: "g_batch", nesting_depth: 1, members: ["w0"] }),
        group("gi1", { kind: "workflow", parent: "g_batch", nesting_depth: 1, members: ["w1"] }),
      ],
    };
    const { nodes, edges } = buildFlow(graph, COMPACT);
    expect(nodes.find((n) => n.id === "host")).toBeUndefined(); // host suppressed as before
    const box = nodes.find((n) => n.id === "g_batch");
    expect(box?.type).toBe("group"); // ...but its batch container RENDERS
    if (box?.type === "group") {
      expect(box.data.showTitle).toBe(true); // and represents the host (title + chip rail)
      expect(box.data.hostNode?.id).toBe("host");
    }
    expect(nodes.find((n) => n.id === "gi0")?.parentId).toBe("g_batch"); // items stay INSIDE (no reparenting past a real box)
    // The whole spine + the host-level binding anchor on the box — nothing dropped.
    expect(edges.find((e) => e.id === "e0")?.target).toBe("g_batch");
    expect(edges.find((e) => e.id === "e1")?.source).toBe("g_batch");
    expect(edges.find((e) => e.id === "e2")?.target).toBe("g_batch");
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
      node("io1", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "g0" }),
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

describe("outputRowsFor — the output-row composition (D2/D3/D4)", () => {
  const reads = (m: Record<string, FieldReads>): Map<string, FieldReads> => new Map(Object.entries(m));
  const shape = (keys: Array<[string, string | null]> | null, dataType: string | null = "dict") => ({
    field: "result",
    data_type: dataType,
    keys: keys?.map(([name, t]) => ({ name, data_type: t })) ?? null,
  });

  it("wholesale read + authored keys: parent row renders, keys nest under it (D2)", () => {
    const n = node("g", { output_shape: shape([["summary", "str"], ["n", "int"]]) });
    const rows = outputRowsFor(n, reads({ result: { bare: true, subKeys: ["summary"] } }));
    expect(rows).toEqual([
      { field: "result", label: "result", dataType: "dict", quiet: false, nested: false },
      { field: "result.summary", label: "summary", dataType: "str", quiet: false, nested: true },
      { field: "result.n", label: "n", dataType: "int", quiet: true, nested: true },
    ]);
  });

  it("no bare read + keys known: flat FULL-PATH rows, no parent (D3)", () => {
    const n = node("g", { output_shape: shape([["ok", "bool"], ["rounds", "int"]]) });
    const rows = outputRowsFor(n, reads({ result: { bare: false, subKeys: ["ok"] } }));
    expect(rows).toEqual([
      { field: "result.ok", label: "result.ok", dataType: "bool", quiet: false, nested: false },
      { field: "result.rounds", label: "result.rounds", dataType: "int", quiet: true, nested: false },
    ]);
  });

  it("authored keys with ZERO readers: quiet shape documentation (D4)", () => {
    const n = node("g", { output_shape: shape([["a", "str"]]) });
    const rows = outputRowsFor(n); // no observed reads at all
    expect(rows).toEqual([{ field: "result.a", label: "result.a", dataType: "str", quiet: true, nested: false }]);
  });

  it("keys unknown: parent row + observed sub-reads nested (run-validate's case)", () => {
    const n = node("g"); // output_shape: null — a plain code node, shape not provable
    const rows = outputRowsFor(n, reads({ result: { bare: false, subKeys: ["ok", "round"] } }));
    expect(rows).toEqual([
      { field: "result", label: "result", dataType: null, quiet: true, nested: false },
      { field: "result.ok", label: "ok", dataType: null, quiet: false, nested: true },
      { field: "result.round", label: "round", dataType: null, quiet: false, nested: true },
    ]);
  });

  it("an observed-only key ABSENT from the authored shape still gets an active row (both cases)", () => {
    const n = node("g", { output_shape: shape([["a", "str"]]) });
    // flat case (no bare read): the stale-shape read still lands on a row
    expect(outputRowsFor(n, reads({ result: { bare: false, subKeys: ["mystery"] } }))).toContainEqual({
      field: "result.mystery",
      label: "result.mystery",
      dataType: null,
      quiet: false,
      nested: false,
    });
    // parent-row case (bare read): same key, nested
    expect(outputRowsFor(n, reads({ result: { bare: true, subKeys: ["mystery"] } }))).toContainEqual({
      field: "result.mystery",
      label: "mystery",
      dataType: null,
      quiet: false,
      nested: true,
    });
  });

  it("non-result fields keep single-row behavior and gain sub-rows on sub-reads", () => {
    const n = node("g");
    expect(outputRowsFor(n, reads({ stdout: { bare: true, subKeys: [] } }))).toEqual([
      { field: "stdout", label: "stdout", dataType: null, quiet: false, nested: false },
    ]);
    expect(outputRowsFor(n, reads({ stdout: { bare: false, subKeys: ["x"] } }))).toEqual([
      { field: "stdout", label: "stdout", dataType: null, quiet: true, nested: false },
      { field: "stdout.x", label: "x", dataType: null, quiet: false, nested: true },
    ]);
  });

  it("no outputs at all: no rows", () => {
    expect(outputRowsFor(node("g"))).toEqual([]);
  });

  it("kind-declared types are the LAST fallback: type observed rows, never create one", () => {
    const kindTypes = { stdout: "str", exit_code: "int" };
    // an observed shell read gains the registry's declared type...
    expect(outputRowsFor(node("g"), reads({ stdout: { bare: true, subKeys: [] } }), kindTypes)).toEqual([
      { field: "stdout", label: "stdout", dataType: "str", quiet: false, nested: false },
    ]);
    // ...but an unread declared field (exit_code) creates NO row (no claim)
    expect(outputRowsFor(node("g"), undefined, kindTypes)).toEqual([]);
    // and an authored per-node shape always WINS over the kind map
    const n = node("g", { output_shape: { field: "stdout", data_type: "bytes", keys: null } });
    expect(outputRowsFor(n, reads({ stdout: { bare: true, subKeys: [] } }), kindTypes)).toEqual([
      { field: "stdout", label: "stdout", dataType: "bytes", quiet: false, nested: false },
    ]);
  });

  it("a response-field shape (structured llm) puts rows on `response`, never `result`", () => {
    // The shape names its own port: llm's structured output lands on `response`
    // (the Python side sets field per kind) — rows, quiet flags, and key union
    // all follow shape.field, so a `${ask.response.risk}` read lands correctly.
    const n = node("ask", {
      kind: "llm",
      output_shape: { field: "response", data_type: "object", keys: [{ name: "risk", data_type: "string" }] },
    });
    expect(outputRowsFor(n)).toEqual([
      { field: "response.risk", label: "response.risk", dataType: "string", quiet: true, nested: false },
    ]);
    expect(outputRowsFor(n, reads({ response: { bare: false, subKeys: ["risk"] } }))).toEqual([
      { field: "response.risk", label: "response.risk", dataType: "string", quiet: false, nested: false },
    ]);
  });
});

describe("buildFlow — per-key landing (output_path → the exact key row)", () => {
  const shaped = { field: "result", data_type: "dict", keys: [{ name: "ok", data_type: "bool" }] };
  const graph: RFGraph = {
    nodes: [
      node("gen", { output_shape: shaped }),
      node("use", { params: [{ name: "p", value: "${gen.result.ok}", is_dynamic: true, source: null }] }),
    ],
    edges: [edge("e0", "gen", "use", "data_flow", { output_field: "result", input_name: "p", output_path: ["ok"] })],
    groups: [],
  };

  it("a sub-key ref leaves its exact key row (advanced)", () => {
    const { edges } = buildFlow(graph, DETAILED);
    expect(edges.find((e) => e.id === "e0")?.sourceHandle).toBe(outputHandle("result.ok"));
  });

  it("the edge scan classifies a sub-read as NOT bare — real edges compose the flat D3 rows", () => {
    // The seam between the edge scan and outputRowsFor: a node read ONLY via
    // `${gen.result.ok}` must take the wrapper-collapse shape — no parent
    // `result` row. (Mutation-verified gap: marking sub-reads as bare passed
    // every prior test, because the unit matrix injects FieldReads directly.)
    const { nodes } = buildFlow(graph, DETAILED);
    const leaf = nodes.find((n) => n.id === "gen");
    if (leaf?.type !== "node") throw new Error("expected the gen leaf");
    expect(leaf.data.outputRows).toEqual([
      { field: "result.ok", label: "result.ok", dataType: "bool", quiet: false, nested: false },
    ]);
  });

  it("a 2-deep path lands on its FIRST segment's row (D7)", () => {
    const g: RFGraph = {
      ...graph,
      nodes: [
        node("gen", { output_shape: shaped }),
        node("use", { params: [{ name: "p", value: "${gen.result.a.b}", is_dynamic: true, source: null }] }),
      ],
      edges: [edge("e0", "gen", "use", "data_flow", { output_field: "result", input_name: "p", output_path: ["a", "b"] })],
    };
    const { edges } = buildFlow(g, DETAILED);
    // "a" is observed-only (not in the authored shape) — it still grows a row (union).
    expect(edges.find((e) => e.id === "e0")?.sourceHandle).toBe(outputHandle("result.a"));
  });

  it("a bare (wholesale) ref lands on the parent row, never decomposed (D6)", () => {
    const g: RFGraph = {
      ...graph,
      edges: [edge("e0", "gen", "use", "data_flow", { output_field: "result", input_name: "p", output_path: [] })],
    };
    const { edges } = buildFlow(g, DETAILED);
    expect(edges.find((e) => e.id === "e0")?.sourceHandle).toBe(outputHandle("result"));
  });

  it("rows hidden (beautiful, unexpanded): node-level fallback, never a missing handle", () => {
    const { edges } = buildFlow(graph, COMPACT);
    expect(edges.find((e) => e.id === "e0")?.sourceHandle).toBe(NODE_OUT);
  });

  it("D5 invariant: authored keys with NO reading edges produce quiet rows and ZERO lines", () => {
    const g: RFGraph = { nodes: [node("gen", { output_shape: shaped })], edges: [], groups: [] };
    const { nodes, edges } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "gen");
    if (leaf?.type !== "node") throw new Error("expected the leaf");
    // The composition is fully determined: one flat quiet row, nothing else.
    expect(leaf.data.outputRows).toEqual([
      { field: "result.ok", label: "result.ok", dataType: "bool", quiet: true, nested: false },
    ]);
    // The input graph has zero edges of ANY kind — nothing may be synthesized.
    expect(edges).toHaveLength(0);
  });

  it("graph.kind_output_types reaches the rows through buildFlow (the WIRING, not just the unit)", () => {
    // The unit fallback is pinned above; this guards the one argument in
    // buildFlow that threads the contract field through — deleting it would
    // keep every unit test green (the tested-but-unwired trap).
    const g: RFGraph = {
      nodes: [node("sh", { kind: "shell" }), node("use", { params: [] })],
      edges: [edge("e0", "sh", "use", "data_flow", { output_field: "stdout", input_name: null })],
      groups: [],
      kind_output_types: { shell: { stdout: "str" } },
    };
    const { nodes } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "sh");
    if (leaf?.type !== "node") throw new Error("expected the shell leaf");
    expect(leaf.data.outputRows).toEqual([
      { field: "stdout", label: "stdout", dataType: "str", quiet: false, nested: false },
    ]);
  });
});

describe("buildFlow — plain-param reads correct the quiet claim (no edges, no lines)", () => {
  // `prompt: ${gen.result.ok}` forms NO data-flow edge, so edge-derived quiet
  // wrongly claimed "unconsumed" for prompt-fed keys (user decision 2026-06-10:
  // the param-text scan). The scan only ever flips quiet / extends key unions —
  // it must not create rows or lines.
  const shaped = {
    field: "result",
    data_type: "dict",
    keys: [
      { name: "ok", data_type: "bool" },
      { name: "n", data_type: "int" },
    ],
  };

  it("a sibling prompt ref un-quiets its key row — and still draws NO line (D5)", () => {
    const g: RFGraph = {
      nodes: [
        node("gen", { output_shape: shaped }),
        node("use", {
          kind: "llm",
          params: [{ name: "prompt", value: "Summarize ${gen.result.ok}", is_dynamic: true, source: null }],
        }),
      ],
      edges: [],
      groups: [],
    };
    const { nodes, edges } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "gen");
    if (leaf?.type !== "node") throw new Error("expected gen");
    expect(leaf.data.outputRows).toEqual([
      { field: "result.ok", label: "result.ok", dataType: "bool", quiet: false, nested: false },
      { field: "result.n", label: "result.n", dataType: "int", quiet: true, nested: false },
    ]);
    expect(edges.filter((e) => e.data?.kind === "data_flow")).toHaveLength(0);
  });

  it("never creates a new field row (no edge + no shape → no row = no claim)", () => {
    const g: RFGraph = {
      nodes: [
        node("gen"),
        node("use", { params: [{ name: "p", value: "${gen.stdout}", is_dynamic: true, source: null }] }),
      ],
      edges: [],
      groups: [],
    };
    const { nodes } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "gen");
    if (leaf?.type !== "node") throw new Error("expected gen");
    expect(leaf.data.outputRows).toEqual([]);
  });

  it("a ref inside a quoted COALESCE LITERAL is never a read (the row stays quiet)", () => {
    // `${cfg.text ?? "ask gen.result owner"}`: the quoted fallback contains a
    // space, and a space inside the literal satisfies the root prefix class —
    // without the operand split, `gen`'s result row read as ACTIVE with zero
    // real readers (the inverse of the lie quiet rows prevent; review-caught
    // 2026-06-11). Python's build is immune (scope.py splits operands); the
    // frontend scan must mirror it.
    const g: RFGraph = {
      nodes: [
        node("gen", { output_shape: shaped }),
        node("use", {
          params: [{ name: "note", value: '${cfg.text ?? "ask gen.result owner"}', is_dynamic: true, source: null }],
        }),
      ],
      edges: [],
      groups: [],
    };
    const { nodes } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "gen");
    if (leaf?.type !== "node") throw new Error("expected gen");
    expect(leaf.data.outputRows.every((r) => r.quiet)).toBe(true);
  });

  it("a ref in the NON-literal coalesce operand IS a read (positive control)", () => {
    const g: RFGraph = {
      nodes: [
        node("gen", { output_shape: shaped }),
        node("use", {
          params: [{ name: "note", value: '${gen.result.ok ?? "x"}', is_dynamic: true, source: null }],
        }),
      ],
      edges: [],
      groups: [],
    };
    const { nodes } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "gen");
    if (leaf?.type !== "node") throw new Error("expected gen");
    expect(leaf.data.outputRows.find((r) => r.field === "result.ok")?.quiet).toBe(false);
  });

  it("scope-aware: a same-named node in ANOTHER scope is not marked", () => {
    const g: RFGraph = {
      nodes: [
        node("gen", { output_shape: shaped, parent: "g0" }),
        node("use", { params: [{ name: "p", value: "${gen.result.ok}", is_dynamic: true, source: null }] }),
      ],
      edges: [],
      groups: [group("g0", { kind: "workflow", members: ["gen"] })],
    };
    const { nodes } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "gen");
    if (leaf?.type !== "node") throw new Error("expected gen");
    expect(leaf.data.outputRows.every((r) => r.quiet)).toBe(true);
  });

  it("consumedReadPaths: the panel's consumed list agrees with the canvas (edges + param reads, full depth)", () => {
    // Panel/canvas parity (review-caught 2026-06-11): a key consumed ONLY via a
    // prompt body must list in the panel's "consumed" fact; edge reads keep
    // their untruncated dotted paths; the no-new-claims gate still applies.
    const g: RFGraph = {
      nodes: [
        node("gen", { output_shape: shaped }),
        node("edge-reader", { params: [{ name: "p", value: "${gen.result.a.b}", is_dynamic: true, source: null }] }),
        node("prompt-reader", {
          kind: "llm",
          params: [{ name: "prompt", value: "Use ${gen.result.ok} and ${gen.nope.x}", is_dynamic: true, source: null }],
        }),
      ],
      edges: [
        edge("e0", "gen", "edge-reader", "data_flow", { output_field: "result", input_name: "p", output_path: ["a", "b"] }),
      ],
      groups: [],
    };
    const paths = consumedReadPaths(g);
    // Edge read full-depth; the prompt-only read listed too; `nope` gated out
    // (no edge read, not the authored shape's field — no row = no claim).
    expect(paths.get("gen")).toEqual(["result.a.b", "result.ok"]);
  });

  it("the reader's batch alias never reads a sibling that shares its name", () => {
    const g: RFGraph = {
      nodes: [
        node("item", { output_shape: shaped }),
        node("use", {
          batch: { parallel: false, dynamic: true, as_name: "item", source_ref: "${rows}", count: null, items: null },
          params: [{ name: "p", value: "${item.result.ok}", is_dynamic: true, source: null }],
        }),
      ],
      edges: [],
      groups: [],
    };
    const { nodes } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "item");
    if (leaf?.type !== "node") throw new Error("expected item");
    expect(leaf.data.outputRows.every((r) => r.quiet)).toBe(true);
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

  it("a TRANSFORM code node's edges leave in the transform cyan (the nodeColor seam)", () => {
    const transformGraph: RFGraph = {
      nodes: [node("reshape", { kind: "code", is_transform: true }), node("a", { kind: "code" })],
      edges: [edge("e0", "reshape", "a", "sequential")],
      groups: [],
    };
    const { edges } = buildFlow(transformGraph, COMPACT);
    expect(edges.find((e) => e.id === "e0")?.data?.sourceColor).toBe(TRANSFORM_COLOR);
  });
});

describe("buildFlow — a decision's END edge is its reserved 'end' outcome (continue-or-stop gates)", () => {
  // The check-validate shape: one forward outcome + a stop arm. The end edge is
  // listed FIRST in the contract to prove "end" still reads LAST among the rows.
  const gate: RFGraph = {
    nodes: [node("dec", { is_decision: true, kind: "code" }), node("work"), node("end0", { kind: "end" })],
    edges: [
      edge("eEnd", "dec", "end0", "end", { condition: "if ok · else" }),
      edge("eGo", "dec", "work", "branch", { label: "work", condition: "elif round < cap" }),
    ],
    groups: [],
  };

  it("'end' joins branchLabels LAST, with its condition on the rows (advanced)", () => {
    const { nodes } = buildFlow(gate, DETAILED);
    const dec = nodes.find((n) => n.id === "dec");
    expect(dec?.type === "node" ? dec.data.branchLabels : null).toEqual(["work", "end"]);
    expect(dec?.type === "node" ? dec.data.branchConditions : null).toEqual({
      work: "elif round < cap",
      end: "if ok · else",
    });
  });

  it("LR: the end edge leaves the 'end' outcome row; TD stays on the icon column", () => {
    const lr = buildFlow(gate, COMPACT);
    const lrEnd = lr.edges.find((e) => e.id === "eEnd");
    expect(lrEnd?.sourceHandle).toBe(branchHandle("end"));
    expect(handleType(lrEnd?.sourceHandle ?? "")).toBe("source");
    expect(buildFlow(gate, TD).edges.find((e) => e.id === "eEnd")?.sourceHandle).toBe(NODE_OUT);
  });

  it("the end condition follows the pill/row split: TD pill, LR row, quiet in beautiful", () => {
    const pillShown = (built: { edges: { id: string; data?: { conditionShown?: boolean } }[] }): boolean =>
      built.edges.find((e) => e.id === "eEnd")?.data?.conditionShown === true;
    expect(pillShown(buildFlow(gate, { density: "detailed", direction: "TD", collapsed: new Set() }))).toBe(true);
    expect(pillShown(buildFlow(gate, DETAILED))).toBe(false); // LR: the row is the home
    expect(pillShown(buildFlow(gate, COMPACT))).toBe(false); // beautiful skeleton stays quiet
    const expandedLR = buildFlow(gate, { ...COMPACT, expanded: new Set(["dec"]) });
    const dec = expandedLR.nodes.find((n) => n.id === "dec");
    expect(dec?.type === "node" ? dec.data.branchConditions.end : null).toBe("if ok · else");
  });

  it("clicking the end dot reveals why flow stopped — TD edge pill, LR source row", () => {
    const td = buildFlow(gate, TD);
    const focused = applyFocus(td.nodes, td.edges, "end0");
    expect(focused.edges.find((e) => e.id === "eEnd")?.data?.conditionRevealed).toBe(true);
    expect(focused.edges.find((e) => e.id === "eGo")?.data?.conditionRevealed).toBeUndefined();

    const lr = buildFlow(gate, COMPACT);
    const lrFocused = applyFocus(lr.nodes, lr.edges, "end0");
    expect(lrFocused.edges.find((e) => e.id === "eEnd")?.data?.conditionRevealed).toBeUndefined();
    const dec = lrFocused.nodes.find((n) => n.id === "dec");
    expect(dec?.type === "node" ? dec.data.revealedConditions : null).toEqual({ end: "if ok · else" });
  });

  it("a NON-decision's END edge is untouched: no outcome row, node-level handle", () => {
    const staticEnd: RFGraph = {
      nodes: [node("a", { kind: "code" }), node("end0", { kind: "end" })],
      edges: [edge("e0", "a", "end0", "end")],
      groups: [],
    };
    const { nodes, edges } = buildFlow(staticEnd, DETAILED);
    const a = nodes.find((n) => n.id === "a");
    expect(a?.type === "node" ? a.data.branchLabels : null).toEqual([]);
    const e0 = edges.find((e) => e.id === "e0");
    expect(e0?.sourceHandle).toBe(NODE_OUT);
    expect(e0?.data?.outcome).toBeUndefined();
  });

  it("a decision END edge with condition=null STILL carries outcome 'end' (is_decision gates, not condition presence)", () => {
    // Extraction is fail-closed: a gate whose stop-arm condition could not be
    // parsed ships condition=null — yet it IS a decision and its END edge IS the
    // "end" outcome. toFlowEdge used condition presence as the decision test
    // (review-caught 2026-06-11): the outcome silently vanished from EdgeData
    // while branchLabels/EdgePanel still treated it as an outcome.
    const unparsed: RFGraph = {
      nodes: [node("dec", { is_decision: true, kind: "code" }), node("work"), node("end0", { kind: "end" })],
      edges: [
        edge("eEnd", "dec", "end0", "end"), // condition: null (fail-closed bail)
        edge("eGo", "dec", "work", "branch", { label: "work" }),
      ],
      groups: [],
    };
    const { nodes, edges } = buildFlow(unparsed, DETAILED);
    expect(edges.find((e) => e.id === "eEnd")?.data?.outcome).toBe("end");
    const dec = nodes.find((n) => n.id === "dec");
    expect(dec?.type === "node" ? dec.data.branchLabels : null).toEqual(["work", "end"]); // the faint LR end row renders
  });
});

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

describe("buildFlow — HANDLE-TYPE INVARIANT (the recurring silent-edge-drop bug)", () => {
  // React Flow SILENTLY drops an edge whose sourceHandle is a target-type id (or vice
  // versa) — jsdom can't catch this (it renders no edge DOM), and it bit us twice
  // (the input-binding edge used a source handle as a target). This is the safety net:
  // a graph exercising EVERY handle scheme, asserting buildFlow never crosses a type.
  function rfInput(id: string, name: string): RFNode {
    return node(id, {
      kind: "input",
      io: { data_type: "string", required: false, default: null },
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
      // outputHandle on a dotted KEY-ROW field ("o:result.ok") — the per-key landing's scheme
      edge("sub", "consumer", "dec", "data_flow", { output_field: "result", output_path: ["ok"] }),
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

describe("rowAnchorsFor — row-port geometry (the LR alignment's source of truth)", () => {
  it("leaf body rows: params (left) then outputs (right), branch rows after loop rows (LR)", () => {
    const g: RFGraph = {
      nodes: [
        node("n0", {
          params: [
            { name: "a", value: "1", is_dynamic: false, source: null },
            { name: "b", value: "2", is_dynamic: false, source: null },
          ],
          loop: { condition: "x", polarity: "while", cap: 3 } as RFNode["loop"],
          is_decision: true,
        }),
        node("t1"),
      ],
      edges: [
        edge("e0", "n0", "t1", "branch", { label: "go", output_field: "out" }),
        edge("d0", "n0", "t1", "data_flow", { output_field: "out", input_name: "x" }),
      ],
      groups: [],
    };
    const { nodes: ns } = buildFlow(g, DETAILED); // LR detailed
    const anchors = rowAnchorsFor(ns.find((n) => n.id === "n0")!);
    const byHandle = new Map(anchors.map((a) => [a.handle, a]));
    expect(byHandle.get(paramHandle("a"))).toEqual({ handle: paramHandle("a"), side: "left", y: HEADER_HEIGHT + 13 });
    expect(byHandle.get(paramHandle("b"))?.y).toBe(HEADER_HEIGHT + 26 + 13);
    expect(byHandle.get(outputHandle("out"))).toEqual({ handle: outputHandle("out"), side: "right", y: HEADER_HEIGHT + 2 * 26 + 13 });
    // branch row sits BELOW the two loop rows (condition + cap)
    expect(byHandle.get(branchHandle("go"))?.y).toBe(HEADER_HEIGHT + (2 + 1 + 2) * 26 + 13);
  });

  it("io card rows include the .io-rows chrome; group card outputs are bottom-anchored; regions get none", () => {
    const g: RFGraph = {
      nodes: [
        node("inA", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "g_root" }),
        node("host", { kind: "workflow", is_group_host: true }),
        node("p1", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "g_in" }),
        node("p2", { kind: "input", io: { data_type: null, required: false, default: null }, parent: "g_in" }),
        node("o1", { kind: "output", io: { data_type: null, required: false, default: null }, parent: "g_out" }),
        node("body", { parent: "g_wf" }),
      ],
      edges: [],
      groups: [
        group("g_root", { kind: "input_wrapper", members: ["inA"] }),
        group("g_wf", { kind: "workflow", host: "host", members: ["body"] }),
        group("g_in", { kind: "input_wrapper", parent: "g_wf", members: ["p1", "p2"] }),
        group("g_out", { kind: "output_wrapper", parent: "g_wf", members: ["o1"] }),
      ],
    };
    // BOTH card kinds share ONE row grid: header + chrome + column label + rows
    // (grid parity — when the LR spine aligns two headers, bindings align too).
    const top = HEADER_HEIGHT + METRICS.ioRowsChrome + METRICS.ioLabelH;
    const adv = buildFlow(g, { ...DETAILED, collapsed: new Set(["g_wf"]) });
    const card = rowAnchorsFor(adv.nodes.find((n) => n.id === "g_root")!);
    expect(card).toEqual([{ handle: portHandle("inA"), side: "right", y: top + 13 }]);
    // collapsed group card: inputs left under the column label; the single output is
    // BOTTOM-ANCHORED (stagger = ioRowsCount(2,1) − 1 = 1 row down)
    const grp = rowAnchorsFor(adv.nodes.find((n) => n.id === "g_wf")!);
    const byHandle = new Map(grp.map((a) => [a.handle, a]));
    expect(byHandle.get(portTargetHandle("p1"))).toEqual({ handle: portTargetHandle("p1"), side: "left", y: top + 13 });
    expect(byHandle.get(portTargetHandle("p2"))?.y).toBe(top + 26 + 13);
    expect(byHandle.get(portHandle("o1"))).toEqual({ handle: portHandle("o1"), side: "right", y: top + 26 + 13 });
    // expanded region: NO anchors (an ELK port on a compound node crashes elkjs)
    const open = buildFlow(g, DETAILED);
    expect(rowAnchorsFor(open.nodes.find((n) => n.id === "g_wf")!)).toEqual([]);
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

  it("LR: the SPINE aligns headers on one line, and grid-parity bindings run straight", async () => {
    // Two user-caught jogs (2026-06-10), one fixture. (1) NODES: without ports ELK
    // aligns box CENTERS, so different-height cards wander off the spine — the
    // icon-row ports + the trunk's straightness priority put every header on ONE
    // line (priority 100: weights accumulate, so a 13-binding bundle at 5 each
    // out-voted a lone trunk edge at 10 — measured 233px). (2) BINDINGS between
    // the io card and a collapsed group card share ONE row grid (header + chrome +
    // label + rows — grid parity), so with headers aligned their bindings align
    // row-to-row simultaneously. Leaf↔card bindings have no parity guarantee.
    const g: RFGraph = {
      nodes: [
        node("inA", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "g_in" }),
        node("inB", { kind: "input", io: { data_type: null, required: false, default: null }, parent: "g_in" }),
        node("host", { kind: "workflow", is_group_host: true }),
        node("p1", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "g_wf_in" }),
        node("p2", { kind: "input", io: { data_type: null, required: false, default: null }, parent: "g_wf_in" }),
        node("body", { parent: "g_wf" }),
      ],
      edges: [
        edge("b0", "inA", "p1", "data_flow", { input_name: "p1" }),
        edge("b1", "inB", "p2", "data_flow", { input_name: "p2" }),
      ],
      groups: [
        group("g_in", { kind: "input_wrapper", members: ["inA", "inB"] }),
        group("g_wf", { kind: "workflow", host: "host", members: ["body"] }),
        group("g_wf_in", { kind: "input_wrapper", parent: "g_wf", members: ["p1", "p2"] }),
      ],
    };
    // advanced + collapsed: the io card and the group card both render rows
    const { nodes: ns, edges: es } = buildFlow(g, { ...DETAILED, collapsed: new Set(["g_wf"]) });
    const laidOut = await layoutGraph(ns, es, "LR");
    const byId = new Map(laidOut.map((n) => [n.id, n]));
    // the spine: both card headers on one line (icon-row ports + priority 100)
    expect(Math.abs(byId.get("g_in")!.position.y - byId.get("g_wf")!.position.y)).toBeLessThanOrEqual(1);
    // the bundle: each binding's endpoint y's match (straight line)
    const anchorY = (id: string, handle: string | null | undefined): number => {
      const n = byId.get(id)!;
      const a = rowAnchorsFor(n).find((x) => x.handle === handle);
      expect(a).toBeDefined();
      return n.position.y + a!.y;
    };
    for (const id of ["b0", "b1"]) {
      const e = es.find((x) => x.id === id)!;
      expect(Math.abs(anchorY(e.source, e.sourceHandle) - anchorY(e.target, e.targetHandle))).toBeLessThanOrEqual(1);
    }
  });

  it("LR: different-height detailed leaves still sit header-to-header on the spine", async () => {
    const g: RFGraph = {
      nodes: [
        node("a", { params: [{ name: "x", value: "1", is_dynamic: false, source: null }] }),
        node("b", {
          params: ["p", "q", "r", "s", "t"].map((name) => ({ name, value: "1", is_dynamic: false, source: null })),
        }),
      ],
      edges: [edge("e0", "a", "b", "sequential")],
      groups: [],
    };
    const { nodes: ns, edges: es } = buildFlow(g, DETAILED);
    const laidOut = await layoutGraph(ns, es, "LR");
    const byId = new Map(laidOut.map((n) => [n.id, n]));
    expect(Math.abs(byId.get("a")!.position.y - byId.get("b")!.position.y)).toBeLessThanOrEqual(1);
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
          io: { data_type: null, required: true, default: null },
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
        node("in1", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "gw" }),
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

  it("expandTargets: focusing a CONTAINER expands its IO rows + each binding's far end", () => {
    // Root inputs card (g_root) binds into the sub-workflow g_wf's input port p1;
    // a leaf producer feeds its port p2. Selecting g_wf must expand: g_wf itself
    // (the card grows its two-column IO rows — port owner = the group) AND the far
    // ends (g_root's card rows, the producer's output rows) so revealed lines land
    // row-to-row instead of deduping into one mislabeled node-level line.
    const g: RFGraph = {
      nodes: [
        node("rootIn", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "g_root" }),
        node("producer"),
        node("host", { kind: "workflow", is_group_host: true }),
        node("p1", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "g_wf_in" }),
        node("p2", { kind: "input", io: { data_type: null, required: false, default: null }, parent: "g_wf_in" }),
        node("body", { parent: "g_wf" }),
      ],
      edges: [
        edge("b1", "rootIn", "p1", "data_flow", { input_name: "p1" }),
        edge("b2", "producer", "p2", "data_flow", { output_field: "out", input_name: "p2" }),
      ],
      groups: [
        group("g_root", { kind: "input_wrapper", members: ["rootIn"] }),
        group("g_wf", { kind: "workflow", host: "host", members: ["body"] }),
        group("g_wf_in", { kind: "input_wrapper", parent: "g_wf", members: ["p1", "p2"] }),
      ],
    };
    const expanded = expandTargets(g, "g_wf");
    expect(expanded.has("g_wf")).toBe(true); // the container's own IO rows
    expect(expanded.has("g_root")).toBe(true); // far end: the root IO card's rows
    expect(expanded.has("producer")).toBe(true); // far end: the producer's output rows
  });

  it("IO-touching data lines carry NO floating label (the rows name the fields)", () => {
    const g: RFGraph = {
      nodes: [
        node("in1", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "gw" }),
        node("c1", { params: [{ name: "p", value: "${in1}", is_dynamic: true, source: null }] }),
        node("a"),
        node("b", { params: [{ name: "x", value: "${a.o}", is_dynamic: true, source: null }] }),
      ],
      edges: [
        edge("bind", "in1", "c1", "data_flow", { input_name: "p" }),
        edge("leafy", "a", "b", "data_flow", { output_field: "o", input_name: "x" }),
      ],
      groups: [group("gw", { kind: "input_wrapper", members: ["in1"] })],
    };
    const { edges: es } = buildFlow(g, COMPACT);
    expect(es.find((e) => e.id === "bind")?.label).toBeUndefined(); // io binding — quiet
    expect(es.find((e) => e.id === "leafy")?.label).toBe("o → x"); // leaf-to-leaf keeps it
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

  it("a selected shadowed edge sheds edge-shadowed (35% opacity would fight bright+halo) — and gets it back on clear", () => {
    const g: RFGraph = {
      nodes: [node("a"), node("b")],
      edges: [edge("e_sh", "a", "b", "sequential", { shadowed: true })],
      groups: [],
    };
    const built = buildFlow(g, DETAILED);
    expect(find({ edges: built.edges }, "e_sh").className).toContain("edge-shadowed");
    expect(find(applyFocus(built.nodes, built.edges, "e_sh"), "e_sh").className).not.toContain("edge-shadowed");
    expect(find(applyFocus(built.nodes, built.edges, null), "e_sh").className).toContain("edge-shadowed");
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
