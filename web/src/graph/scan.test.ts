// Param-text read-scan tests (scan.ts): plain-param sibling reads correcting the
// quiet claim, exercised through buildFlow's observed-read merge, plus
// consumedReadPaths (the read panel's full-depth fact). Split from flow.test.ts
// beside their subject — architecture-review candidate 2, 2026-06-13.

import { describe, expect, it } from "vitest";

import { consumedReadPaths } from "./scan";
import { buildFlow } from "./flow";
import type { NodeRow, OutputRow } from "./rows";
import { DETAILED, edge, group, node } from "./testFixtures";
import type { RFGraph } from "../types";


// The leaf's output rows, recovered from the unified body row list (LeafData.rows
// — the nodeRows model): the same OutputRow objects buildFlow composed, so the
// assertions below still pin the outputRowsFor → LeafData seam.
function leafOutputRows(leaf: { data: { rows: NodeRow[] } }): OutputRow[] {
  return leaf.data.rows.flatMap((r) => (r.kind === "output" ? [r.row] : []));
}

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
    expect(leafOutputRows(leaf)).toEqual([
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
    expect(leafOutputRows(leaf)).toEqual([]);
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
    expect(leafOutputRows(leaf).every((r) => r.quiet)).toBe(true);
  });

  it("an escaped template and a spaced operand are never reads (the grammar gate)", () => {
    // Runtime parity (mirrors scope.py): `$${gen.result.ok}` resolves to the
    // literal text `${gen.result.ok}`, and `${ gen.result.ok }` never resolves
    // at all — neither may un-quiet a row.
    const g: RFGraph = {
      nodes: [
        node("gen", { output_shape: shaped }),
        node("use", {
          params: [
            { name: "a", value: "$${gen.result.ok}", is_dynamic: false, source: null },
            { name: "b", value: "${ gen.result.ok }", is_dynamic: false, source: null },
          ],
        }),
      ],
      edges: [],
      groups: [],
    };
    const { nodes } = buildFlow(g, DETAILED);
    const leaf = nodes.find((n) => n.id === "gen");
    if (leaf?.type !== "node") throw new Error("expected gen");
    expect(leafOutputRows(leaf).every((r) => r.quiet)).toBe(true);
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
    expect(leafOutputRows(leaf).find((r) => r.field === "result.ok")?.quiet).toBe(false);
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
    expect(leafOutputRows(leaf).every((r) => r.quiet)).toBe(true);
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
    expect(leafOutputRows(leaf).every((r) => r.quiet)).toBe(true);
  });
});
