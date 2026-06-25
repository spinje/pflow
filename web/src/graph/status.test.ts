// Live execution overlay restyle (Task 173): refKey (the stable structural-ref
// status-map key) and applyStatus (the cheap status restyle — identity preserved
// when unchanged so memo'd nodes skip re-render). Pure module, node-env (no jsdom),
// beside its subject like focus.test.ts.

import { describe, expect, it } from "vitest";

import { applyStatus, refKey } from "./focus";
import type { FlowNode, GroupData, LeafData } from "./flow";
import type { NodeRunState, NodeStatus, RFNode, RFRef } from "../types";

// A minimal type-correct RFNode (the contract node every leaf/end FlowNode wraps).
function rfNode(id: string, ref: RFRef): RFNode {
  return {
    id,
    ref,
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

// A minimal type-correct leaf FlowNode — only the fields refKey/applyStatus touch
// (data.node.ref + data.status) need real values; the rest are neutral defaults so
// tsc is satisfied without dragging in the whole build.
function leaf(id: string, ref: RFRef, status?: NodeStatus): FlowNode {
  const data: LeafData = {
    node: rfNode(id, ref),
    density: "compact",
    direction: "LR",
    rows: [],
    branchLabels: [],
    branchConditions: {},
    hasIncoming: false,
    hasOutgoing: false,
    expanded: false,
    dimmed: false,
    focused: false,
    ...(status !== undefined ? { status } : {}),
  };
  return { id, type: "node", position: { x: 0, y: 0 }, data };
}

const ref = (over: Partial<RFRef> = {}): RFRef => ({ node_id: "a", ancestor_path: [], port: null, ...over });

// The overlay status map is keyed ref → NodeRunState (status + optional metrics). These tests exercise the
// status side, so build it from bare [refKey, status] pairs with the metrics left absent.
const statusMap = (entries: [string, NodeStatus][]): Map<string, NodeRunState> =>
  new Map(entries.map(([key, status]) => [key, { status }]));

// FlowNode is a discriminated union; narrow on `node.type` (not `node.data.type`)
// so TS knows `data` is LeafData before reading `status`.
const statusOf = (node: FlowNode): NodeStatus | "NOT_A_NODE" | undefined =>
  node.type === "node" ? node.data.status : "NOT_A_NODE";

const groupStatusOf = (node: FlowNode): NodeStatus | undefined => (node.type === "group" ? node.data.status : undefined);

// A sub-workflow host group: its host leaf is suppressed (is_group_host), so the host renders AS this
// group and applyStatus lights it by the HOST's ref — but only the host's PRIMARY group (showTitle).
function hostGroup(id: string, hostRef: RFRef, opts: { showTitle: boolean; status?: NodeStatus }): FlowNode {
  const data: GroupData = {
    group: { id, kind: "workflow", parent: null, host: "hostflat", members: [], nesting_depth: 0, annotations: {} },
    hostNode: rfNode("hostflat", hostRef),
    collapsed: false,
    showTitle: opts.showTitle,
    direction: "LR",
    density: "compact",
    hasIncoming: false,
    hasOutgoing: false,
    memberCount: 0,
    inputs: [],
    outputs: [],
    ioRowsVisible: false,
    focusedPortId: null,
    dimmed: false,
    focused: false,
    ...(opts.status !== undefined ? { status: opts.status } : {}),
  };
  return { id, type: "group", position: { x: 0, y: 0 }, data };
}

describe("refKey — stable key from a structural ref", () => {
  it("identical structure → identical key (the status-map join must hit)", () => {
    const a = ref({ node_id: "x", ancestor_path: [{ node_id: "wf", batch_index: 2 }], port: "out" });
    const b = ref({ node_id: "x", ancestor_path: [{ node_id: "wf", batch_index: 2 }], port: "out" });
    expect(refKey(a)).toBe(refKey(b));
  });

  it("a different node_id → a different key (two distinct nodes never collide)", () => {
    expect(refKey(ref({ node_id: "a" }))).not.toBe(refKey(ref({ node_id: "b" })));
  });

  it("a different ancestor_path → a different key (same node_id in two scopes stays distinct)", () => {
    const root = ref({ node_id: "step", ancestor_path: [] });
    const nested = ref({ node_id: "step", ancestor_path: [{ node_id: "wf", batch_index: null }] });
    expect(refKey(root)).not.toBe(refKey(nested));
  });

  it("a different batch_index in the path → a different key (two batch iterations stay distinct)", () => {
    const i0 = ref({ node_id: "step", ancestor_path: [{ node_id: "wf", batch_index: 0 }] });
    const i1 = ref({ node_id: "step", ancestor_path: [{ node_id: "wf", batch_index: 1 }] });
    expect(refKey(i0)).not.toBe(refKey(i1));
  });

  it("a different port → a different key", () => {
    expect(refKey(ref({ port: "in" }))).not.toBe(refKey(ref({ port: "out" })));
    expect(refKey(ref({ port: null }))).not.toBe(refKey(ref({ port: "in" })));
  });
});

describe("applyStatus — the run-status restyle pass", () => {
  it("a status keyed by a matching ref lands on that node's data.status", () => {
    const node = leaf("a", ref({ node_id: "a" }));
    const map = statusMap([[refKey(ref({ node_id: "a" })), "running"]]);
    const out = applyStatus([node], map)[0]!;
    expect(statusOf(out)).toBe("running");
  });

  it("threads the run metrics (duration/cost) onto data.runDetail alongside the status (for the badge hover)", () => {
    const node = leaf("a", ref({ node_id: "a" }));
    const map = new Map<string, NodeRunState>([
      [refKey(ref({ node_id: "a" })), { status: "success", durationMs: 1234, costUsd: 0.003 }],
    ]);
    const out = applyStatus([node], map)[0]!;
    expect(statusOf(out)).toBe("success");
    expect(out.type === "node" ? out.data.runDetail : null).toEqual({ durationMs: 1234, costUsd: 0.003 });
  });

  it("an UNCHANGED status preserves object identity (React memo skips it)", () => {
    const node = leaf("a", ref({ node_id: "a" }), "success");
    // Same status the node already carries — the join hits but nothing changes.
    const map = statusMap([[refKey(ref({ node_id: "a" })), "success"]]);
    const out = applyStatus([node], map)[0]!;
    expect(out).toBe(node); // same reference — no needless re-render
  });

  it("a node with no entry and no prior status is unchanged (idle canvas, undefined === undefined)", () => {
    const node = leaf("a", ref({ node_id: "a" }));
    const out = applyStatus([node], new Map())[0]!;
    expect(out).toBe(node);
  });

  it("a CHANGED status returns a NEW object with new data but the same other fields", () => {
    const node = leaf("a", ref({ node_id: "a" }));
    const map = statusMap([[refKey(ref({ node_id: "a" })), "failed"]]);
    const out = applyStatus([node], map)[0]!;
    expect(out).not.toBe(node); // new identity → React re-renders
    expect(out.data).not.toBe(node.data); // fresh data object
    expect(statusOf(out)).toBe("failed");
    expect(out.id).toBe(node.id);
    expect(out.position).toBe(node.position); // untouched fields carried through
  });

  it("clearing a prior status (no entry in the map) changes identity and drops the status", () => {
    const node = leaf("a", ref({ node_id: "a" }), "running");
    const out = applyStatus([node], new Map())[0]!; // a run-reset: status now absent
    expect(out).not.toBe(node);
    expect(statusOf(out)).toBeUndefined();
  });

  it("a HOSTLESS group and end nodes pass through untouched (no host ref to join on)", () => {
    const group: FlowNode = {
      id: "g0",
      type: "group",
      position: { x: 0, y: 0 },
      data: {
        group: { id: "g0", kind: "workflow", parent: null, host: null, members: [], nesting_depth: 0, annotations: {} },
        hostNode: null,
        collapsed: false,
        showTitle: false,
        direction: "LR",
        density: "compact",
        hasIncoming: false,
        hasOutgoing: false,
        memberCount: 0,
        inputs: [],
        outputs: [],
        ioRowsVisible: false,
        focusedPortId: null,
        dimmed: false,
        focused: false,
      },
    };
    const end: FlowNode = {
      id: "e0",
      type: "end",
      position: { x: 0, y: 0 },
      data: { node: rfNode("e0", ref({ node_id: "e0" })), direction: "LR", dimmed: false, focused: false },
    };
    // Even with map entries under their ids' keys, non-node types must pass through untouched.
    const map = statusMap([
      [refKey(ref({ node_id: "g0" })), "running"],
      [refKey(ref({ node_id: "e0" })), "success"],
    ]);
    const out = applyStatus([group, end], map);
    expect(out[0]).toBe(group);
    expect(out[1]).toBe(end);
  });

  it("restyles per node: a matched node changes, an already-correct one keeps identity", () => {
    const a = leaf("a", ref({ node_id: "a" }));
    const b = leaf("b", ref({ node_id: "b" }), "cached");
    const map = statusMap([
      [refKey(ref({ node_id: "a" })), "running"],
      [refKey(ref({ node_id: "b" })), "cached"], // b is already "cached" — must not churn identity
    ]);
    const [outA, outB] = applyStatus([a, b], map) as [FlowNode, FlowNode];
    expect(outA).not.toBe(a); // a changed
    expect(statusOf(outA)).toBe("running");
    expect(outB).toBe(b); // b's status matches the map → identity preserved (no re-render)
  });
});

describe("applyStatus — sub-workflow HOST groups (Task 173 P2)", () => {
  it("lights the host's PRIMARY group by the host's ref (the suppressed host leaf renders AS the group)", () => {
    const hostRef = ref({ node_id: "call-child", ancestor_path: [], port: null });
    const g = hostGroup("g0", hostRef, { showTitle: true });
    const map = statusMap([[refKey(hostRef), "running"]]);
    const out = applyStatus([g], map)[0]!;
    expect(out).not.toBe(g);
    expect(groupStatusOf(out)).toBe("running");
  });

  it("does NOT light a NON-primary group for the same host (showTitle=false → a host backing >1 group lights once)", () => {
    const hostRef = ref({ node_id: "call-child" });
    const secondary = hostGroup("g1", hostRef, { showTitle: false });
    const map = statusMap([[refKey(hostRef), "running"]]);
    expect(applyStatus([secondary], map)[0]).toBe(secondary); // untouched
  });

  it("an unchanged host-group status preserves identity (memo skip)", () => {
    const hostRef = ref({ node_id: "call-child" });
    const g = hostGroup("g0", hostRef, { showTitle: true, status: "success" });
    const map = statusMap([[refKey(hostRef), "success"]]);
    expect(applyStatus([g], map)[0]).toBe(g);
  });

  it("joins on the HOST ref, not the group's flat id — a stale id never lights the wrong group", () => {
    // The status map is keyed by the host's structural ref; the group's own flat id is irrelevant.
    const hostRef = ref({ node_id: "call-child", ancestor_path: [{ node_id: "outer", batch_index: null }] });
    const g = hostGroup("g7", hostRef, { showTitle: true });
    const map = statusMap([[refKey(hostRef), "failed"]]);
    expect(groupStatusOf(applyStatus([g], map)[0]!)).toBe("failed");
  });
});

describe("applyStatus — markUnmatched (Task 173 stale-replay 'no recorded state')", () => {
  it("a joinable node with NO recorded state becomes 'unrecorded' (the dashed badge), not blank", () => {
    const a = leaf("a", ref({ node_id: "a" }));
    const out = applyStatus([a], new Map(), true)[0]!;
    expect(statusOf(out)).toBe("unrecorded");
  });

  it("a node WITH a recorded state keeps it — markUnmatched only fills the gaps", () => {
    const a = leaf("a", ref({ node_id: "a" }));
    const map = statusMap([[refKey(ref({ node_id: "a" })), "success"]]);
    expect(statusOf(applyStatus([a], map, true)[0]!)).toBe("success");
  });

  it("WITHOUT markUnmatched, an unmatched node stays blank (a normal run never marks pending nodes)", () => {
    const a = leaf("a", ref({ node_id: "a" }));
    expect(statusOf(applyStatus([a], new Map(), false)[0]!)).toBeUndefined();
  });

  it("marks an unmatched PRIMARY host group too, but leaves hostless groups / end nodes untouched", () => {
    const primary = hostGroup("g0", ref({ node_id: "call-child" }), { showTitle: true });
    const secondary = hostGroup("g1", ref({ node_id: "call-child" }), { showTitle: false });
    const [outPrimary, outSecondary] = applyStatus([primary, secondary], new Map(), true) as [FlowNode, FlowNode];
    expect(groupStatusOf(outPrimary)).toBe("unrecorded"); // a joinable host with no state → marked
    expect(outSecondary).toBe(secondary); // non-primary group is not a join target → never marked
  });
});
