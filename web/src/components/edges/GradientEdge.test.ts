// The stops-builder is the load-bearing logic of GradientEdge: it decides where an
// error/end edge's node-color fade ends and its semantic color begins. Pure function,
// node-env — rendering the gradient itself is a real-browser concern (jsdom paints
// no SVG), so the geometry of the stop list is what we pin.

import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { ICON_COL_X } from "../../graph/metrics";
import { conditionAnchor, gradientStops, labelAnchor, railCenter } from "./GradientEdge";

describe("gradientStops", () => {
  it("sequential/branch blend source→target across the whole edge", () => {
    expect(gradientStops("sequential", "#111", "#222", 300)).toEqual([
      { offset: 0, color: "#111" },
      { offset: 1, color: "#222" },
    ]);
  });

  it("error fades node color → red at BOTH ends, ~26px in", () => {
    const stops = gradientStops("error", "#10b981", "#f59e0b", 260);
    expect(stops).toHaveLength(4);
    expect(stops[0]).toEqual({ offset: 0, color: "#10b981" });
    expect(stops[1]!.offset).toBeCloseTo(0.1); // 26/260
    expect(stops[1]!.color).toBe("var(--danger)");
    expect(stops[2]!.offset).toBeCloseTo(0.9);
    expect(stops[2]!.color).toBe("var(--danger)");
    expect(stops[3]).toEqual({ offset: 1, color: "#f59e0b" });
  });

  it("end fades only at the source — the end-sink side stays faint", () => {
    const stops = gradientStops("end", "#10b981", "#whatever", 260);
    expect(stops).toHaveLength(2);
    expect(stops[0]).toEqual({ offset: 0, color: "#10b981" });
    expect(stops[1]!.offset).toBeCloseTo(0.1);
    expect(stops[1]!.color).toBe("var(--text-faint)");
  });

  it("clamps the fade on short edges so the two fades cannot cross", () => {
    const stops = gradientStops("error", "#111", "#222", 20); // 26px fade > half the chord
    expect(stops[1]!.offset).toBeLessThanOrEqual(0.4);
    expect(stops[2]!.offset).toBeGreaterThanOrEqual(0.6);
  });

  it("degenerate zero-length chord still yields valid monotonic offsets", () => {
    const stops = gradientStops("error", "#111", "#222", 0);
    const offsets = stops.map((s) => s.offset);
    expect([...offsets].sort((a, b) => a - b)).toEqual(offsets);
  });
});

describe("railCenter — LR branch lanes fan out; TD keeps the shared trunk rail", () => {
  const base = { sourceX: 100, sourceY: 100, targetX: 400, targetY: 300 };

  it("LR: each lane turns at its own x (distinct rails — user-caught overlap)", () => {
    const xs = [0, 1, 2].map((lane) => railCenter({ ...base, sourcePosition: Position.Right, lane }).centerX);
    expect(new Set(xs).size).toBe(3);
    expect(xs[1]! - xs[0]!).toBeGreaterThan(0);
  });

  it("TD: lane is ignored — a fork's branches share the trunk rail by design", () => {
    const a = railCenter({ ...base, sourcePosition: Position.Bottom, lane: 0 }).centerY;
    const b = railCenter({ ...base, sourcePosition: Position.Bottom, lane: 3 }).centerY;
    expect(a).toBe(b);
  });

  it("LR: the staggered rail still clamps to the halfway point on short hops", () => {
    const close = railCenter({ ...base, targetX: 160, sourcePosition: Position.Right, lane: 5 });
    expect(close.centerX).toBe(100 + (160 - 100) / 2);
  });
});

describe("labelAnchor — the pill sits at the target's entry, just off the node", () => {
  const path = { pathX: 250, pathY: 200 };

  it("TD (top entry): left edge just right of the node's left border, fully above it", () => {
    const a = labelAnchor({ targetX: 300, targetY: 400, targetPosition: Position.Top, ...path });
    // handle sits at the icon column → node left edge, +4px user-tuned nudge
    expect(a.x).toBe(300 - ICON_COL_X + 4);
    expect(a.y).toBeLessThan(400); // a gap above the node, never on it
    expect(a.selfTranslate).toBe("translate(0, -100%)"); // left+bottom edges at the anchor
  });

  it("LR (left entry): sits fully left of the node border, centered on the line", () => {
    const a = labelAnchor({ targetX: 300, targetY: 400, targetPosition: Position.Left, ...path });
    expect(a.x).toBeLessThan(300);
    expect(a.y).toBe(400);
    expect(a.selfTranslate).toBe("translate(-100%, -50%)");
  });

  it("unusual entry side falls back to the path center", () => {
    const a = labelAnchor({ targetX: 300, targetY: 400, targetPosition: Position.Bottom, ...path });
    expect(a).toEqual({ x: 250, y: 200, selfTranslate: "translate(-50%, -50%)" });
  });
});

describe("conditionAnchor — the condition pill sits on a LONE segment, never the rail crossing", () => {
  const path = { pathX: 250, pathY: 140 };

  it("TD straight child (no rail run of its own): centers on the final descent", () => {
    // source bottom y=100, target top y=200 → rail at 100+40=140 (2×radius=40).
    // The path midpoint (140) IS the rail crossing; the pill must sit below it.
    const a = conditionAnchor({ sourceX: 300, sourceY: 100, targetX: 300, targetY: 200, targetPosition: Position.Top, ...path });
    expect(a.x).toBe(300); // on the descent into the target
    expect(a.y).toBeGreaterThan(140); // below the shared fork rail
    expect(a.y).toBeLessThan(200 - 16); // above the outcome label zone
  });

  it("TD side branch (real horizontal run): keeps the midpoint — the run is its own lone segment", () => {
    const a = conditionAnchor({ sourceX: 100, sourceY: 100, targetX: 400, targetY: 200, targetPosition: Position.Top, ...path });
    expect(a).toEqual({ x: 250, y: 140 }); // mid-run, user-preferred over the cramped descent
  });

  it("TD short hop: rail clamps to halfway, pill still strictly between rail and entry", () => {
    const a = conditionAnchor({ sourceX: 300, sourceY: 100, targetX: 300, targetY: 160, targetPosition: Position.Top, ...path });
    expect(a.y).toBeGreaterThan(130); // rail clamped to (160-100)/2 → 130
    expect(a.y).toBeLessThan(160);
  });

  it("LR / backward edges keep the path midpoint", () => {
    const lr = conditionAnchor({ sourceX: 100, sourceY: 100, targetX: 300, targetY: 100, targetPosition: Position.Left, ...path });
    expect(lr).toEqual({ x: 250, y: 140 });
    const backward = conditionAnchor({ sourceX: 300, sourceY: 300, targetX: 300, targetY: 200, targetPosition: Position.Top, ...path });
    expect(backward).toEqual({ x: 250, y: 140 });
  });
});
