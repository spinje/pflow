import { afterEach, describe, expect, it, vi } from "vitest";

import { CANVAS_MIN_W, clampPanelWidth, loadPanelWidth, PANEL_DEFAULT_W, PANEL_MIN_W, savePanelWidth } from "./panelWidth";

afterEach(() => vi.restoreAllMocks());

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

  it("reserves the requested peer column plus minimum canvas width", () => {
    expect(clampPanelWidth(700, 1200, 420)).toBe(1200 - 420 - CANVAS_MIN_W);
  });

  it("the viewport cap never undercuts the hard minimum on tiny windows or huge reservations", () => {
    expect(clampPanelWidth(400, 200, 500)).toBe(PANEL_MIN_W);
  });
});

describe("loadPanelWidth", () => {
  it("falls back to the default when storage is unavailable (node env: no window)", () => {
    expect(loadPanelWidth(1600)).toBe(PANEL_DEFAULT_W);
  });

  it("reads and writes using a caller-supplied storage key", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
      },
    });

    savePanelWidth(512, "pflow-ui:source-w");
    expect(loadPanelWidth(1600, "pflow-ui:source-w")).toBe(512);
    expect(loadPanelWidth(1600)).toBe(PANEL_DEFAULT_W);
  });
});
