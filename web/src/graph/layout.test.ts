// orderForkSiblings: a fork's targets follow their BRANCH-EDGE order (the code's
// if/elif/else chain order) instead of Steps-declaration order, so the first
// condition lands leftmost and the spatial ordinals read in code order.

import { describe, expect, it } from "vitest";

import type { FlowNode } from "./flow";
import { orderForkSiblings } from "./layout";

const n = (id: string): FlowNode => ({ id, type: "node", position: { x: 0, y: 0 }, data: {} }) as FlowNode;
const branch = (entries: Array<[string, string, number]>): Map<string, { source: string; rank: number }> =>
  new Map(entries.map(([target, source, rank]) => [target, { source, rank }]));

describe("orderForkSiblings", () => {
  it("reorders a fork's targets by branch rank (first `if` first), not list order", () => {
    // Steps order: small, large — but the code's chain assigns large FIRST (rank 0).
    const out = orderForkSiblings([n("small"), n("large")], branch([["small", "dec", 1], ["large", "dec", 0]]));
    expect(out.map((x) => x.id)).toEqual(["large", "small"]);
  });

  it("clusters a fork at its first occurrence; unrelated siblings keep their position", () => {
    const out = orderForkSiblings(
      [n("before"), n("b2"), n("other"), n("b1")],
      branch([["b2", "dec", 1], ["b1", "dec", 0]]),
    );
    // the fork cluster anchors where b2 sat (index 1); b1 joins it, sorted by rank
    expect(out.map((x) => x.id)).toEqual(["before", "b1", "b2", "other"]);
  });

  it("no branch targets → identity", () => {
    const list = [n("a"), n("b"), n("c")];
    expect(orderForkSiblings(list, new Map()).map((x) => x.id)).toEqual(["a", "b", "c"]);
  });

  it("two independent forks keep their own clusters in order", () => {
    const out = orderForkSiblings(
      [n("a2"), n("a1"), n("z2"), n("z1")],
      branch([["a2", "decA", 1], ["a1", "decA", 0], ["z2", "decZ", 1], ["z1", "decZ", 0]]),
    );
    expect(out.map((x) => x.id)).toEqual(["a1", "a2", "z1", "z2"]);
  });
});
