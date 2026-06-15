// Row-model tests: outputRowsFor (the D2/D3/D4 composition) and rowAnchorsFor
// (the LR row-port geometry). Split from flow.test.ts beside their subject
// (rows.ts) — architecture-review candidate 2, 2026-06-13.

import { describe, expect, it } from "vitest";

import { HEADER_HEIGHT, leafSize, nodeRows, outputRowsFor, paramRowsFor, type RefRow, ROW_HEIGHT, ROW_PADDING, rowAnchorsFor } from "./rows";
import type { FieldReads } from "./scan";
import { buildFlow } from "./flow";
import { branchHandle, LOOP_ROW, outputHandle, paramHandle, portHandle, portTargetHandle } from "./handles";
import { METRICS } from "./metrics";
import { DETAILED, edge, group, node } from "./testFixtures";
import type { LoopSpec, RFGraph, RFNode } from "../types";

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

describe("nodeRows — the unified body row list (the lockstep, now mechanical)", () => {
  // A node exercising EVERY row kind: two params (the second receiving two refs
  // → per-ref sub-rows), a cached-prefix chunk before `prompt`, an authored
  // output shape, and a capped loop.
  const loop: LoopSpec = { polarity: "until", condition: "${self.result.ok}", cap: 3, carry: {} };
  const subject = node("n1", {
    kind: "llm",
    params: [
      { name: "model", value: "gpt", is_dynamic: false, source: null },
      { name: "prompt", value: "${a.stdout} and ${b.stdout}", is_dynamic: true, source: null },
    ],
    output_shape: { field: "response", data_type: "str", keys: null },
    loop,
  });
  const refRows = new Map<string, RefRow[]>([
    ["prompt", [
      { handle: "bind:prompt:a.stdout", name: null, ref: "a.stdout" },
      { handle: "bind:prompt:b.stdout", name: null, ref: "b.stdout" },
    ]],
    ["prompt_cache", [{ handle: "bind:prompt_cache:c.response", name: null, ref: "c.response" }]],
  ]);
  const paramRows = paramRowsFor(subject, refRows);
  const outputRows = outputRowsFor(subject);
  const rows = nodeRows(subject, paramRows, outputRows);

  it("orders the body: left column (paramRowsFor order) -> outputs -> loop-condition -> loop-cap", () => {
    expect(rows.map((r) => r.kind)).toEqual([
      "param", // model
      "ref", // cached prefix (single chunk -> flat row, before prompt)
      "param", // prompt
      "ref", // prompt sub-row 1 (>=2 refs)
      "ref", // prompt sub-row 2
      "output", // response
      "loop-condition",
      "loop-cap",
    ]);
  });

  it("attaches each row's handle as data (params/outputs/loop-condition)", () => {
    expect(rows[0]).toEqual({ kind: "param", param: subject.params[0], targetHandle: paramHandle("model") });
    const output = rows.find((r) => r.kind === "output");
    expect(output).toEqual({ kind: "output", row: outputRows[0], sourceHandle: outputHandle("response") });
    const cond = rows.find((r) => r.kind === "loop-condition");
    expect(cond).toEqual({ kind: "loop-condition", loop, targetHandle: LOOP_ROW });
  });

  it("emits the loop-cap row ONLY when a cap is set", () => {
    const uncapped = node("n2", { loop: { ...loop, cap: null } });
    const kinds = nodeRows(uncapped, paramRowsFor(uncapped, undefined), []).map((r) => r.kind);
    expect(kinds).toEqual(["loop-condition"]);
  });

  it("leafSize counts exactly the nodeRows list — the render/size lockstep, pinned mechanically", () => {
    const size = leafSize("detailed", "LR", rows, [], false);
    expect(size.height).toBe(HEADER_HEIGHT + rows.length * ROW_HEIGHT + ROW_PADDING);
    // And the anchors advance one slot per row: the LAST anchored row (the output,
    // index 5) sits at its exact slot even though loop rows follow it.
    const flowNode = {
      type: "node" as const,
      id: "n1",
      position: { x: 0, y: 0 },
      data: {
        node: subject, density: "detailed" as const, direction: "LR" as const, rows,
        branchLabels: [], branchConditions: {}, hasIncoming: false, hasOutgoing: false,
        expanded: false, dimmed: false, focused: false,
      },
    };
    const anchors = rowAnchorsFor(flowNode);
    const outputAnchor = anchors.find((a) => a.handle === outputHandle("response"));
    expect(outputAnchor?.y).toBe(HEADER_HEIGHT + 5 * ROW_HEIGHT + ROW_HEIGHT / 2);
    // Loop rows anchor nothing (the self-loop never enters ELK) but the label-less
    // rule still holds: every handle-bearing row got exactly one anchor.
    expect(anchors).toHaveLength(6); // 2 params + 3 refs + 1 output
  });
});
