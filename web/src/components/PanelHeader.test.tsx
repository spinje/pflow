// @vitest-environment jsdom
// PanelHeader — the shared single-subject panel header (ReadPanel + IoPanel): a
// node avatar (tile + native icon, kind-colored) + a category eyebrow + the name
// as a NAVIGATE button (re-centers the camera). Pins: the name stays the panel's
// <h2> heading (so getByRole("heading") survives the redesign), clicking it
// navigates, and an absent onNavigate degrades to plain (non-button) text.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { PanelHeader } from "./PanelHeader";

afterEach(cleanup);

describe("PanelHeader", () => {
  it("renders the avatar, eyebrow and name; the name is the <h2> heading", () => {
    render(
      <PanelHeader
        icon="/icons/bash.svg"
        color="#3fb950"
        eyebrow="shell"
        name="session_context"
        onNavigate={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("shell")).toBeTruthy();
    // The name survives as the panel heading (the redesign keeps the <h2>).
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("session_context");
    // The tile carries the kind color via the --chip-c var.
    const tile = document.querySelector<HTMLElement>(".panel-head-tile");
    expect(document.querySelector<HTMLElement>(".panel-head")?.style.getPropertyValue("--chip-c")).toBe("#3fb950");
    expect(tile?.querySelector("img")?.getAttribute("src")).toBe("/icons/bash.svg");
  });

  it("navigates when the name is clicked (re-center gesture)", () => {
    const onNavigate = vi.fn();
    render(
      <PanelHeader icon="/i.svg" color="#fff" eyebrow="shell" name="session_context" onNavigate={onNavigate} onClose={() => {}} />,
    );
    screen.getByText("session_context").click();
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it("renders a plain (non-button) name when onNavigate is absent", () => {
    render(<PanelHeader icon="/i.svg" color="#fff" eyebrow="workflow inputs" name="lyrics-generator" onClose={() => {}} />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("lyrics-generator");
    expect(document.querySelector(".panel-head-nav")).toBeNull();
  });

  it("closes via the ✕ button", () => {
    const onClose = vi.fn();
    render(<PanelHeader icon="/i.svg" color="#fff" eyebrow="shell" name="n" onClose={onClose} />);
    screen.getByTitle("Close").click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
