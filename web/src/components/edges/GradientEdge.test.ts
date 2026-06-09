// The stops-builder is the load-bearing logic of GradientEdge: it decides where an
// error/end edge's node-color fade ends and its semantic color begins. Pure function,
// node-env — rendering the gradient itself is a real-browser concern (jsdom paints
// no SVG), so the geometry of the stop list is what we pin.

import { describe, expect, it } from "vitest";

import { gradientStops } from "./GradientEdge";

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
