import { describe, expect, it } from "vitest";

import { clampPanelWidth, loadPanelWidth, PANEL_DEFAULT_W, PANEL_MIN_W } from "./panelWidth";

describe("clampPanelWidth", () => {
  it("passes a sane width through, rounded", () => {
    expect(clampPanelWidth(500.4, 1600)).toBe(500);
  });

  it("enforces the hard minimum", () => {
    expect(clampPanelWidth(50, 1600)).toBe(PANEL_MIN_W);
  });

  it("enforces the hard maximum on a huge viewport", () => {
    expect(clampPanelWidth(5000, 4000)).toBe(860);
  });

  it("never exceeds 70% of the viewport (the canvas stays usable)", () => {
    expect(clampPanelWidth(700, 800)).toBe(560);
  });

  it("the viewport cap never undercuts the hard minimum on tiny windows", () => {
    expect(clampPanelWidth(400, 200)).toBe(PANEL_MIN_W);
  });
});

describe("loadPanelWidth", () => {
  it("falls back to the default when storage is unavailable (node env: no window)", () => {
    expect(loadPanelWidth(1600)).toBe(PANEL_DEFAULT_W);
  });
});
