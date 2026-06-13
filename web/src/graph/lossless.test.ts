// The frontend NO-INFORMATION-LOSS invariant: buildFlow must give every contract
// node an on-canvas representative and keep every contract edge's connectivity,
// across every structural feature combination × view state.
//
// Why this exists (2026-06-11): the literal-batch invisibility bug (CRITICAL)
// shattered real workflows into islands for a full day while buildFlow's
// "dropped edge — no on-canvas anchor" console.warn fired in production — and no
// test anywhere listened. The Python side has its own no-info-loss test
// (model → RF); this is the missing frontend half (RF → flow). It runs over:
//   1. a SYNTHETIC matrix of the structural shapes (each feature the composition
//      rules interact over), and
//   2. REAL renderer output — committed contract JSON under
//      ../test/fixtures/contracts/, drift-guarded against the live Python
//      renderer by tests/test_core/test_react_flow_contract_fixtures.py — so a
//      hand-built fixture can never encode a bug-compatible shape unnoticed
//      (the synthetic-fixture trap that hid the literal-batch hole).
//
// The invariant deliberately checks SURVIVAL, not exact anchoring (exact landing
// rules have their own pins in flow.test.ts): candidate representatives are
// derived from the contract's own semantics through the PRODUCTION seams
// (shellBatchIds, ioOwners) — never a re-implementation of renderAnchor.

import { describe, expect, it, vi } from "vitest";

import { buildFlow, type BuildOptions, expandTargets, ioOwners, shellBatchIds } from "./flow";
import { collapsibleGroupIds } from "./collapse";
import type { EdgeKind, RFEdge, RFGraph, RFGroup, RFNode } from "../types";
import conditionalBranchingContract from "../test/fixtures/contracts/conditional-branching.json";
import deepResearchContract from "../test/fixtures/contracts/deep-research.json";
import runCycleContract from "../test/fixtures/contracts/run-cycle.json";

// ---- fixture factories (minimal mirrors of flow.test.ts's) ---------------

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

function edge(id: string, source: string, target: string, kind: EdgeKind, over: Partial<RFEdge> = {}): RFEdge {
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [], ...over };
}

const DYNAMIC_BATCH = { parallel: true, dynamic: true, as_name: "item", source_ref: "${xs}", count: null, items: null };
const LITERAL_LEAF_BATCH = { parallel: false, dynamic: false, as_name: "item", source_ref: null, count: 3, items: ["a", "b", "c"] };
const LITERAL_WF_BATCH = { parallel: true, dynamic: false, as_name: "item", source_ref: null, count: 5, items: [{}, {}, {}, {}, {}] };
const LOOP: NonNullable<RFNode["loop"]> = { polarity: "while", condition: "${gate.more}", cap: 3, carry: {} };

// ---- the invariant --------------------------------------------------------

/** Candidate on-canvas representatives for a contract node, by the contract's
 *  own semantics: itself when emitted; an IO node's row OWNER (ioOwners — the
 *  production rule); a suppressed host's non-shell group(s) (shellBatchIds —
 *  the production rule); any emitted ancestor group for collapse-hidden nodes.
 *  A non-empty set = "this node is reachable on canvas somewhere". */
function representativesOf(
  graph: RFGraph,
  emitted: ReadonlySet<string>,
  contractId: string,
): Set<string> {
  if (emitted.has(contractId)) return new Set([contractId]);
  const groupById = new Map(graph.groups.map((g) => [g.id, g]));
  const out = new Set<string>();
  const addAncestorChain = (start: string | null): void => {
    let cur = start;
    while (cur) {
      if (emitted.has(cur)) out.add(cur);
      cur = groupById.get(cur)?.parent ?? null;
    }
  };
  const n = graph.nodes.find((x) => x.id === contractId);
  if (!n) return out;
  if (n.io != null) {
    const owner = ioOwners(graph).ports.get(contractId);
    if (owner != null) {
      if (emitted.has(owner)) out.add(owner);
      else addAncestorChain(groupById.get(owner)?.parent ?? null);
    }
    return out;
  }
  if (n.is_group_host) {
    const shells = shellBatchIds(graph);
    for (const g of graph.groups) {
      if (g.host !== contractId || shells.has(g.id)) continue;
      if (emitted.has(g.id)) out.add(g.id);
      else addAncestorChain(g.parent);
    }
    return out;
  }
  addAncestorChain(n.parent);
  return out;
}

function expectLossless(graph: RFGraph, view: BuildOptions, label: string): void {
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  try {
    const { nodes, edges } = buildFlow(graph, view);
    // 1. The production warn IS the silent-loss detector — in tests it fails.
    const dropped = warnSpy.mock.calls.filter((c) => String(c[0]).includes("dropped edge"));
    expect(dropped, `${label}: buildFlow warn-dropped edges: ${dropped.map((c) => String(c[0])).join("; ")}`).toEqual([]);

    const emitted = new Set(nodes.map((n) => n.id));
    // 2. Every non-IO contract node has a representative (IO nodes are rows —
    //    their reachability is their owner's, asserted through their edges).
    for (const n of graph.nodes) {
      if (n.io != null) continue;
      expect(
        representativesOf(graph, emitted, n.id).size,
        `${label}: node ${n.id} (${n.ref.node_id}) has NO on-canvas representative`,
      ).toBeGreaterThan(0);
    }
    // 3. Every contract edge's connectivity survives: some flow edge of the same
    //    kind connects a representative of its source to one of its target —
    //    unless both endpoints share a representative (a legitimate internal
    //    drop: collapsed into one box / host self-loop).
    for (const e of graph.edges) {
      const src = representativesOf(graph, emitted, e.source);
      const tgt = representativesOf(graph, emitted, e.target);
      expect(src.size, `${label}: edge ${e.id} source ${e.source} unrepresentable`).toBeGreaterThan(0);
      expect(tgt.size, `${label}: edge ${e.id} target ${e.target} unrepresentable`).toBeGreaterThan(0);
      if ([...src].some((s) => tgt.has(s))) continue; // internal — a correct drop
      const survives = edges.some((f) => f.data != null && f.data.kind === e.kind && src.has(f.source) && tgt.has(f.target));
      expect(survives, `${label}: edge ${e.id} ${e.source}->${e.target} (${e.kind}) LOST — no flow edge connects their representatives`).toBe(true);
    }
  } finally {
    warnSpy.mockRestore();
  }
}

/** Every view state worth sweeping: both densities × both directions, plus the
 *  collapse-all overview and a focus-expanded build (the states that re-anchor). */
function viewStates(graph: RFGraph): Array<{ view: BuildOptions; state: string }> {
  const base: Array<{ view: BuildOptions; state: string }> = [];
  for (const density of ["detailed", "compact"] as const) {
    for (const direction of ["LR", "TD"] as const) {
      base.push({ view: { density, direction, collapsed: new Set() }, state: `${density}/${direction}` });
    }
  }
  const allCollapsed = new Set(collapsibleGroupIds(graph));
  if (allCollapsed.size > 0) {
    base.push({ view: { density: "compact", direction: "TD", collapsed: allCollapsed }, state: "collapse-all" });
  }
  const focusable = graph.nodes.find((n) => n.io === null && !n.is_group_host && n.kind !== "end");
  if (focusable) {
    base.push({
      view: { density: "compact", direction: "LR", collapsed: new Set(), expanded: expandTargets(graph, focusable.id) },
      state: `expanded(${focusable.ref.node_id})`,
    });
  }
  return base;
}

function sweep(name: string, graph: RFGraph): void {
  it(`${name}: no node or edge is silently lost in any view state`, () => {
    for (const { view, state } of viewStates(graph)) {
      expectLossless(graph, view, `${name}[${state}]`);
    }
  });
}

// ---- 1. the synthetic structural matrix -----------------------------------

describe("losslessness — synthetic structural matrix", () => {
  sweep("plain chain + data flow", {
    nodes: [
      node("a", { params: [{ name: "command", value: "x", is_dynamic: false, source: null }] }),
      node("b", { params: [{ name: "p", value: "${a.stdout}", is_dynamic: true, source: null }] }),
      node("c"),
    ],
    edges: [
      edge("e0", "a", "b", "sequential"),
      edge("e1", "b", "c", "sequential"),
      edge("e2", "a", "b", "data_flow", { output_field: "stdout", input_name: "p" }),
    ],
    groups: [],
  });

  sweep("decision with branch/error/end", {
    nodes: [node("dec", { kind: "code", is_decision: true }), node("ok"), node("fix"), node("end0", { kind: "end" })],
    edges: [
      edge("e0", "dec", "ok", "branch", { label: "ok", condition: "if ready" }),
      edge("e1", "dec", "fix", "error"),
      edge("e2", "dec", "end0", "end"),
    ],
    groups: [],
  });

  sweep("dynamic batch of a LEAF (decorator shell)", {
    nodes: [node("a"), node("b", { batch: DYNAMIC_BATCH }), node("c")],
    edges: [edge("e0", "a", "b", "sequential"), edge("e1", "b", "c", "sequential")],
    groups: [group("gb", { kind: "batch", host: "b", nesting_depth: 1 })],
  });

  sweep("dynamic batch of a SUB-WORKFLOW (shell + hosted workflow group)", {
    nodes: [
      node("a"),
      node("host", { kind: "workflow", is_group_host: true, batch: DYNAMIC_BATCH, loop: LOOP }),
      node("body", { parent: "g_wf" }),
      node("c"),
    ],
    edges: [
      edge("e0", "a", "host", "sequential"),
      edge("e1", "host", "c", "sequential"),
      edge("e2", "a", "host", "data_flow", { output_field: "stdout" }),
    ],
    groups: [
      group("g_batch", { kind: "batch", host: "host", nesting_depth: 1 }),
      group("g_wf", { kind: "workflow", host: "host", parent: "g_batch", nesting_depth: 1, members: ["body"] }),
    ],
  });

  sweep("LITERAL batch of a LEAF (the 2026-06-11 invisible-step repro)", {
    nodes: [node("a"), node("fan", { batch: LITERAL_LEAF_BATCH }), node("c")],
    edges: [edge("e0", "a", "fan", "sequential"), edge("e1", "fan", "c", "sequential")],
    groups: [group("g0", { kind: "batch", host: "fan", nesting_depth: 1 })],
  });

  sweep("LITERAL batch of SUB-WORKFLOWS incl. truncation-re-anchored edge (song-creator shape)", {
    nodes: [
      node("up"),
      node("host", { kind: "workflow", is_group_host: true, batch: LITERAL_WF_BATCH }),
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
  });

  sweep("nested sub-workflow with IO wrappers + bindings", {
    nodes: [
      node("a"),
      node("host", { kind: "workflow", is_group_host: true }),
      node("in_x", { kind: "input", io: { data_type: "string", required: true, default: null }, parent: "g_in" }),
      node("inner", { parent: "g_wf", params: [{ name: "p", value: "${in_x}", is_dynamic: true, source: null }] }),
      node("out_y", { kind: "output", io: { data_type: null, required: false, default: null }, parent: "g_out" }),
      node("c", { params: [{ name: "q", value: "${host.out_y}", is_dynamic: true, source: null }] }),
    ],
    edges: [
      edge("e0", "a", "host", "sequential"),
      edge("e1", "host", "c", "sequential"),
      edge("e2", "a", "in_x", "data_flow", { output_field: "stdout", input_name: "in_x" }),
      edge("e3", "in_x", "inner", "data_flow", { input_name: "p" }),
      edge("e4", "inner", "out_y", "data_flow", { output_field: "stdout" }),
      edge("e5", "out_y", "c", "data_flow", { input_name: "q" }),
    ],
    groups: [
      group("g_wf", { kind: "workflow", host: "host", members: ["inner"] }),
      group("g_in", { kind: "input_wrapper", parent: "g_wf", members: ["in_x"], nesting_depth: 1 }),
      group("g_out", { kind: "output_wrapper", parent: "g_wf", members: ["out_y"], nesting_depth: 1 }),
    ],
  });
});

// ---- 2. real renderer output (drift-guarded committed contracts) ----------

describe("losslessness — REAL contracts (committed renderer output)", () => {
  const FIXTURES: Array<[string, unknown]> = [
    ["conditional-branching", conditionalBranchingContract],
    ["run-cycle", runCycleContract],
    ["deep-research", deepResearchContract],
  ];
  for (const [name, contract] of FIXTURES) {
    sweep(name, contract as RFGraph);
  }
});
