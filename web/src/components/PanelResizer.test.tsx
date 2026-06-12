// @vitest-environment jsdom
// PanelResizer drag tests. jsdom has no pointer capture (setPointerCapture is
// optional-called), but pointer events dispatch fine — the drag math
// (viewport right edge → pointer x) and the reset gesture are pinned here.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";

import { PanelResizer } from "./PanelResizer";

afterEach(cleanup);

function renderResizer(side?: "left" | "right") {
  const onResize = vi.fn();
  const onReset = vi.fn();
  const { container } = render(<PanelResizer onResize={onResize} onReset={onReset} side={side} />);
  const handle = container.querySelector(".panel-resizer")!;
  return { handle, onResize, onReset };
}

describe("PanelResizer", () => {
  it("reports viewport-right-edge minus pointer x while dragging", () => {
    const { handle, onResize } = renderResizer();
    window.innerWidth = 1200;
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 800 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 700 });
    expect(onResize).toHaveBeenCalledWith(500);
  });

  it("reports pointer x directly for a left-side panel", () => {
    const { handle, onResize } = renderResizer("left");
    window.innerWidth = 1200;
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 300 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 420 });
    expect(onResize).toHaveBeenCalledWith(420);
  });

  it("stops reporting after pointerup", () => {
    const { handle, onResize } = renderResizer();
    window.innerWidth = 1200;
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 800 });
    fireEvent.pointerUp(handle, { pointerId: 1 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 600 });
    expect(onResize).not.toHaveBeenCalled();
  });

  it("double-click resets", () => {
    const { handle, onReset } = renderResizer();
    fireEvent.doubleClick(handle);
    expect(onReset).toHaveBeenCalled();
  });
});
