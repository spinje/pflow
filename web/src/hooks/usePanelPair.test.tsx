// @vitest-environment jsdom
//
// Focused pins for the pane-width state machine. The pure clamp math is pinned
// in utils/panelWidth.test.ts and the clamp-RESERVATION wiring at the component
// level (GraphView.test.tsx, the mutant-calibrated 1000px viewport test); what
// only a hook-level test can reach is the WINDOW-RESIZE re-clamp arm — the
// review-caught bug where both flex no-shrink panes survived a window shrink
// untouched and crushed the canvas to 0 with no recovery short of a re-drag.

import { beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { usePanelPair } from "./usePanelPair";

const setViewport = (w: number): void => {
  Object.defineProperty(window, "innerWidth", { value: w, writable: true, configurable: true });
};

beforeEach(() => {
  window.localStorage.removeItem("pflow-ui:panel-w");
  window.localStorage.removeItem("pflow-ui:source-w");
  setViewport(1400);
});

describe("usePanelPair", () => {
  it("a window shrink re-clamps BOTH panes so a usable canvas survives — and persists the result", () => {
    const { result } = renderHook(() => usePanelPair(true));
    // At 1400 the 460/460 defaults fit (460+460+320 <= 1400) and stay put.
    expect(result.current.panelWidth).toBe(460);
    expect(result.current.sourceWidth).toBe(460);

    act(() => {
      setViewport(1000);
      window.dispatchEvent(new Event("resize"));
    });
    // The symmetric re-clamp converges: hard floors hold and the pair leaves
    // CANVAS_MIN_W (320) of viewport for the canvas.
    expect(result.current.panelWidth).toBeGreaterThanOrEqual(300);
    expect(result.current.sourceWidth).toBeGreaterThanOrEqual(300);
    expect(result.current.panelWidth + result.current.sourceWidth).toBeLessThanOrEqual(1000 - 320);
    // The persistence effects track the re-clamped widths (a reload would
    // otherwise resurrect the pre-shrink pair).
    expect(window.localStorage.getItem("pflow-ui:panel-w")).toBe(String(result.current.panelWidth));
    expect(window.localStorage.getItem("pflow-ui:source-w")).toBe(String(result.current.sourceWidth));
  });

  it("a drag clamps against the OTHER pane only while the source pane is open", () => {
    const open = renderHook(() => usePanelPair(true));
    act(() => open.result.current.onPanelResize(9999));
    // Open source pane (460) reserved: 1400 - 460 - 320 = 620 is the ceiling.
    expect(open.result.current.panelWidth).toBe(620);

    const closed = renderHook(() => usePanelPair(false));
    act(() => closed.result.current.onPanelResize(9999));
    // Nothing reserved: the hard PANEL_MAX_W (860) is the ceiling.
    expect(closed.result.current.panelWidth).toBe(860);
  });
});
