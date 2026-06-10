// orderForkSiblings: a fork's targets follow their BRANCH-EDGE order (the code's
// if/elif/else chain order) instead of Steps-declaration order, so the first
// condition lands leftmost and the spatial ordinals read in code order.
//
// layoutWithWatchdog: a silent ELK worker (no reply, no error — the observed
// 2026-06-10 focus-deep-link hang) must never hang the canvas: the watchdog
// rescues the layout on the bundled main-thread ELK.

import type { ELK, ElkNode } from "elkjs/lib/elk.bundled.js";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FlowNode } from "./flow";
import { layoutWithWatchdog, orderForkSiblings, WORKER_TIMEOUT_MS } from "./layout";

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

describe("layoutWithWatchdog", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("passes a healthy engine's result straight through", async () => {
    const laid = { id: "root", children: [] } as ElkNode;
    const elk = { layout: vi.fn().mockResolvedValue(laid) } as unknown as ELK;
    await expect(layoutWithWatchdog(elk, { id: "root" })).resolves.toBe(laid);
  });

  it("propagates a rejecting engine (the existing error-banner path)", async () => {
    const elk = { layout: vi.fn().mockRejectedValue(new Error("boom")) } as unknown as ELK;
    await expect(layoutWithWatchdog(elk, { id: "root" })).rejects.toThrow("boom");
  });

  it("rescues a SILENT engine on the main thread and terminates its worker", async () => {
    vi.useFakeTimers();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const terminate = vi.fn();
    const silent = { layout: () => new Promise(() => {}), terminateWorker: terminate } as unknown as ELK;
    const root: ElkNode = { id: "root", children: [{ id: "a", width: 10, height: 10 }], edges: [] };

    const pending = layoutWithWatchdog(silent, root);
    await vi.advanceTimersByTimeAsync(WORKER_TIMEOUT_MS + 1);
    vi.useRealTimers(); // the bundled fallback needs real timers to settle

    const out = await pending;
    expect(out.children?.[0]?.x).toBeTypeOf("number"); // a real layout happened
    expect(terminate).toHaveBeenCalled();
    expect(warn).toHaveBeenCalledOnce();
  });
});
