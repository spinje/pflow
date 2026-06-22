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
  rowAnchorsFor,
} from "./flow";
import {
  branchHandle,
  bindingRowHandle,
  handleType,
  LOOP_ROW,
  NODE_IN,
  NODE_OUT,
  outputHandle,
  paramHandle,
} from "./handles";
import { layoutGraph } from "./layout";
import { METRICS } from "./metrics";
import { CONDITION_COLOR, TRANSFORM_COLOR, kindColor } from "../utils/format";
import type { NodeRow, OutputRow } from "./rows";
import { COMPACT, DETAILED, edge, group, node, TD } from "./testFixtures";
import type { RFGraph, RFNode } from "../types";

// ---- tests --------------------------------------------------------------


// The leaf's output rows, recovered from the unified body row list (LeafData.rows
// — the nodeRows model): the same OutputRow objects buildFlow composed, so the
// assertions below still pin the outputRowsFor → LeafData seam.
function leafOutputRows(leaf: { data: { rows: NodeRow[] } }): OutputRow[] {
  return leaf.data.rows.flatMap((r) => (r.kind === "output" ? [r.row] : []));
}

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
    expect(leafOutputRows(leaf)).toEqual([
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
    expect(leafOutputRows(leaf)).toEqual([
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
    expect(leafOutputRows(leaf)).toEqual([
      { field: "stdout", label: "stdout", dataType: "str", quiet: false, nested: false },
    ]);
  });
});

describe("buildFlow — two refs into one param yield two lines on per-ref sub-rows", () => {
  // "${a.x} and ${b.y}" produces two data-flow edges. A param receiving >=2
  // refs grows a sub-row per ref and each edge lands on ITS row (user design
  // 2026-06-13 — both-on-one-handle made the lines indistinguishable); a
  // single ref keeps landing on the param row itself.
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

  it("each edge lands on its own ref sub-row under the prompt", () => {
    const { edges } = buildFlow(graph, DETAILED);
    expect(edges.find((e) => e.id === "e0")?.targetHandle).toBe(bindingRowHandle("prompt", "a.x"));
    expect(edges.find((e) => e.id === "e1")?.targetHandle).toBe(bindingRowHandle("prompt", "b.y"));
  });

  it("the sub-rows anchor LEFT directly below the prompt row, in ref order", () => {
    const { nodes: ns } = buildFlow(graph, DETAILED);
    const anchors = rowAnchorsFor(ns.find((n) => n.id === "t")!);
    const byHandle = new Map(anchors.map((a) => [a.handle, a]));
    expect(byHandle.get(paramHandle("prompt"))?.y).toBe(HEADER_HEIGHT + 13);
    expect(byHandle.get(bindingRowHandle("prompt", "a.x"))?.y).toBe(HEADER_HEIGHT + 26 + 13);
    expect(byHandle.get(bindingRowHandle("prompt", "b.y"))?.y).toBe(HEADER_HEIGHT + 2 * 26 + 13);
  });

  it("a single-ref param keeps landing on the param row (no sub-row)", () => {
    const single: RFGraph = {
      nodes: [node("a"), node("t", { params: [{ name: "prompt", value: "${a.x}", is_dynamic: true, source: null }] })],
      edges: [edge("e0", "a", "t", "data_flow", { output_field: "x", input_name: "prompt" })],
      groups: [],
    };
    const { nodes: ns, edges } = buildFlow(single, DETAILED);
    expect(edges.find((e) => e.id === "e0")?.targetHandle).toBe(paramHandle("prompt"));
    // and no sub-row anchor exists
    const anchors = rowAnchorsFor(ns.find((n) => n.id === "t")!);
    expect(anchors.some((a) => a.handle === bindingRowHandle("prompt", "a.x"))).toBe(false);
  });

  it("dict-key bindings into one param get per-key sub-rows named by their key", () => {
    const dict: RFGraph = {
      nodes: [
        node("a"),
        node("b"),
        node("t", {
          kind: "code",
          params: [{ name: "inputs", value: { text: "${a.x}", cfg: "${b.y}" }, is_dynamic: true, source: null }],
        }),
      ],
      edges: [
        edge("e0", "a", "t", "data_flow", { output_field: "x", input_name: "text" }),
        edge("e1", "b", "t", "data_flow", { output_field: "y", input_name: "cfg" }),
      ],
      groups: [],
    };
    const { edges } = buildFlow(dict, DETAILED);
    expect(edges.find((e) => e.id === "e0")?.targetHandle).toBe(bindingRowHandle("text", "a.x"));
    expect(edges.find((e) => e.id === "e1")?.targetHandle).toBe(bindingRowHandle("cfg", "b.y"));
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

  it("collapsed data edges keep the dropped id in mergedIds so a Point at it lights the kept line", () => {
    // Two distinct contract data edges between the same nodes that fall back to
    // node-level handles in beautiful collapse to ONE rendered line. The dropped
    // id must survive on mergedIds so an agent Point that the server resolves to
    // it still focuses the kept line — never a "resolvable but shown nothing" no-op.
    const g: RFGraph = {
      nodes: [node("a"), node("b")],
      edges: [
        edge("df0", "a", "b", "data_flow", { output_field: "out", input_name: "x" }),
        edge("df1", "a", "b", "data_flow", { output_field: "out", input_name: "x" }),
      ],
      groups: [],
    };
    const { nodes, edges } = buildFlow(g, COMPACT);
    const dataEdges = edges.filter((e) => e.data?.kind === "data_flow");
    expect(dataEdges).toHaveLength(1);
    expect(dataEdges[0]?.id).toBe("df0");
    expect(dataEdges[0]?.data?.mergedIds).toEqual(["df1"]);

    // Focusing the deduped-away id lights (selects + reveals) the kept line.
    const viaMerged = applyFocus(nodes, edges, "df1").edges.find((e) => e.id === "df0");
    expect(viaMerged?.data?.selected).toBe(true);
    expect(viaMerged?.hidden).toBe(false);
    // The kept id still selects it; an unrelated id does not.
    expect(applyFocus(nodes, edges, "df0").edges.find((e) => e.id === "df0")?.data?.selected).toBe(true);
    expect(applyFocus(nodes, edges, "nope").edges.find((e) => e.id === "df0")?.data?.selected).toBeUndefined();
  });

  it("a cache edge's label presents the reserved prompt_cache name as the cached prefix", () => {
    // A cache edge can never land row-to-row (no param row exists for it), so
    // the beautiful label always shows — the raw sentinel must never reach it.
    const g: RFGraph = {
      nodes: [node("a"), node("b")],
      edges: [edge("df", "a", "b", "data_flow", { output_field: "response", input_name: "prompt_cache" })],
      groups: [],
    };
    expect(buildFlow(g, COMPACT).edges.find((e) => e.id === "df")?.label).toBe("response → cached prefix");
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

describe("the cached-prefix rows — `## Cache` chunk lines land on visible per-chunk handles", () => {
  // Without the rows, cache edges fell back to NODE_IN and merged invisibly into
  // the control trunk at the icon-row entry (user-caught 2026-06-13). The rows
  // derive from incoming input_name="prompt_cache" edges (wired by construction);
  // each row's key is the chunk's authored ref text rebuilt from its edge.
  const cacheGraph = (consumerOver: Partial<RFNode> = {}): RFGraph => ({
    nodes: [
      node("ex", { kind: "llm", params: [{ name: "prompt", value: "extract", is_dynamic: false, source: null }] }),
      node("sum", {
        kind: "llm",
        params: [
          { name: "model", value: "anthropic/x", is_dynamic: false, source: null },
          { name: "prompt", value: "summarize", is_dynamic: false, source: null },
        ],
        ...consumerOver,
      }),
    ],
    edges: [
      edge("seq", "ex", "sum", "sequential"),
      edge("ec", "ex", "sum", "data_flow", { output_field: "response", input_name: "prompt_cache" }),
    ],
    groups: [],
  });
  const multiGraph = (): RFGraph => {
    const g = cacheGraph();
    return {
      ...g,
      nodes: [...g.nodes, node("kb", { kind: "shell" })],
      edges: [
        edge("seq", "ex", "sum", "sequential"),
        edge("ec", "ex", "sum", "data_flow", { output_field: "response", input_name: "prompt_cache" }),
        edge("ec2", "kb", "sum", "data_flow", { output_field: "stdout", input_name: "prompt_cache" }),
      ],
    };
  };

  it("advanced: the cache edge lands on ITS chunk's row, anchored LEFT immediately before the prompt param", () => {
    const { nodes: ns, edges: es } = buildFlow(cacheGraph(), DETAILED);
    expect(es.find((e) => e.id === "ec")?.targetHandle).toBe(bindingRowHandle("prompt_cache", "ex.response"));
    const anchors = rowAnchorsFor(ns.find((n) => n.id === "sum")!);
    const byHandle = new Map(anchors.map((a) => [a.handle, a]));
    // rows: 0 model · 1 the cache row (BEFORE prompt — request order) · 2 prompt
    expect(byHandle.get(paramHandle("model"))?.y).toBe(HEADER_HEIGHT + 13);
    expect(byHandle.get(bindingRowHandle("prompt_cache", "ex.response"))).toEqual({
      handle: bindingRowHandle("prompt_cache", "ex.response"),
      side: "left",
      y: HEADER_HEIGHT + 26 + 13,
    });
    expect(byHandle.get(paramHandle("prompt"))?.y).toBe(HEADER_HEIGHT + 2 * 26 + 13);
  });

  it("a single chunk adds one ROW_HEIGHT; multiple chunks add the ×N label row too (leafSize counts what renders)", () => {
    const plain: RFGraph = { ...cacheGraph(), edges: [edge("seq", "ex", "sum", "sequential")] };
    const without = buildFlow(plain, DETAILED).nodes.find((n) => n.id === "sum")!;
    const one = buildFlow(cacheGraph(), DETAILED).nodes.find((n) => n.id === "sum")!;
    expect((one.height ?? 0) - (without.height ?? 0)).toBe(26);
    const two = buildFlow(multiGraph(), DETAILED).nodes.find((n) => n.id === "sum")!;
    expect((two.height ?? 0) - (without.height ?? 0)).toBe(3 * 26); // label row + 2 chunk rows
  });

  it("multi-chunk: each edge lands on its own row, in prefix (edge) order below the label row", () => {
    const { nodes: ns, edges: es } = buildFlow(multiGraph(), DETAILED);
    expect(es.find((e) => e.id === "ec")?.targetHandle).toBe(bindingRowHandle("prompt_cache", "ex.response"));
    expect(es.find((e) => e.id === "ec2")?.targetHandle).toBe(bindingRowHandle("prompt_cache", "kb.stdout"));
    const anchors = rowAnchorsFor(ns.find((n) => n.id === "sum")!);
    const byHandle = new Map(anchors.map((a) => [a.handle, a]));
    // rows: 0 model · 1 "cached prefix ×2" (no handle) · 2-3 chunk rows · 4 prompt
    expect(byHandle.get(bindingRowHandle("prompt_cache", "ex.response"))?.y).toBe(HEADER_HEIGHT + 2 * 26 + 13);
    expect(byHandle.get(bindingRowHandle("prompt_cache", "kb.stdout"))?.y).toBe(HEADER_HEIGHT + 3 * 26 + 13);
    expect(byHandle.get(paramHandle("prompt"))?.y).toBe(HEADER_HEIGHT + 4 * 26 + 13);
  });

  it("beautiful: rows hidden → the cache edge lands node-level (never a handle that doesn't render)", () => {
    const { edges: es } = buildFlow(cacheGraph(), COMPACT);
    expect(es.find((e) => e.id === "ec")?.targetHandle).toBe(NODE_IN);
  });

  it("beautiful focus-expansion: the expanded consumer's cache edge lands on its row", () => {
    const { edges: es } = buildFlow(cacheGraph(), { ...COMPACT, expanded: new Set(["sum", "ex"]) });
    expect(es.find((e) => e.id === "ec")?.targetHandle).toBe(bindingRowHandle("prompt_cache", "ex.response"));
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
