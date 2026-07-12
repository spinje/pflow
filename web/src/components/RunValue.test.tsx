// @vitest-environment jsdom
// RunValue — the shared "how a recorded run value displays" component, plus its
// expand-to-modal affordance: the panel box is scroll-capped at 320px, so every
// value carries a ⛶ that opens the SAME content full-screen (portaled overlay,
// un-capped) for reading. Esc / backdrop / × all close it.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RunValue } from "./RunValue";

// The CodeBlock insulation every panel test uses: a real shiki load under jsdom
// setStates after assertions and bleeds across tests via the memoized promise.
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});

afterEach(cleanup);

const LONG = Array.from({ length: 40 }, (_, i) => `report line ${i + 1}`).join("\n");

describe("RunValue expand", () => {
  it("renders the value with an expand button; no modal until clicked", () => {
    render(<RunValue value="short value" label="report" />);
    expect(screen.getByText("short value")).toBeTruthy();
    expect(screen.getByLabelText("Expand report")).toBeTruthy();
    expect(document.querySelector(".value-modal")).toBeNull();
  });

  it("expand opens a full-screen dialog on <body> with the FULL content and the label as title", () => {
    render(<RunValue value={LONG} label="report" />);
    fireEvent.click(screen.getByLabelText("Expand report"));
    const dialog = screen.getByRole("dialog");
    // Portaled OUT of the panel subtree — a panel overflow can't clip it.
    expect(dialog.closest(".value-modal-overlay")!.parentElement).toBe(document.body);
    expect(dialog.textContent).toContain("report line 1");
    expect(dialog.textContent).toContain("report line 40"); // nothing truncated
    expect(screen.getByText("report", { selector: ".value-modal-title" })).toBeTruthy();
  });

  it("a DICT expands to a per-field document — labeled blocks, strings as REAL text (the modal is a reading surface)", () => {
    const value = { report: "line one\nline two\nline three", repo: "pflow" };
    render(<RunValue value={value} label="Inputs" />);
    // The compact box stays JSON (shape-skimmable): the string field is escaped there.
    expect(document.querySelector(".read-param-value")!.textContent).toContain("\\n");
    fireEvent.click(screen.getByLabelText("Expand Inputs"));
    const body = document.querySelector(".value-modal-body")!;
    // One labeled block per top-level key…
    expect([...body.querySelectorAll(".value-doc-name")].map((n) => n.textContent)).toEqual(["report", "repo"]);
    // …and the string field renders with REAL newlines — no JSON `\n` escapes, no quotes.
    expect(body.textContent).toContain("line one\nline two\nline three");
    expect(body.textContent).not.toContain("\\n");
  });

  it("a dict's NON-string fields stay pretty JSON inside their doc block", () => {
    render(<RunValue value={{ findings: [{ file: "a.py" }], total: 1 }} label="Result" />);
    fireEvent.click(screen.getByLabelText("Expand Result"));
    const body = document.querySelector(".value-modal-body")!;
    expect(body.textContent).toContain('"file": "a.py"'); // the array field, still JSON
    expect([...body.querySelectorAll(".value-doc-name")].map((n) => n.textContent)).toEqual(["findings", "total"]);
  });

  it("an ARRAY value keeps the plain JSON modal (no per-field doc)", () => {
    render(<RunValue value={[{ file: "a.py", lines: 812 }]} label="findings" />);
    fireEvent.click(screen.getByLabelText("Expand findings"));
    const body = document.querySelector(".value-modal-body")!;
    expect(body.querySelector(".value-doc-field")).toBeNull();
    expect(body.textContent).toContain('"file": "a.py"');
  });

  it("Escape, the backdrop, and the close button each close the modal", () => {
    render(<RunValue value="v" label="x" />);
    const open = (): void => {
      fireEvent.click(screen.getByLabelText("Expand x"));
    };

    open();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector(".value-modal")).toBeNull();

    open();
    fireEvent.click(document.querySelector(".value-modal-overlay")!);
    expect(document.querySelector(".value-modal")).toBeNull();

    open();
    // A click INSIDE the dialog must NOT close it (backdrop-only rule)…
    fireEvent.click(screen.getByRole("dialog"));
    expect(document.querySelector(".value-modal")).toBeTruthy();
    // …the × does.
    fireEvent.click(screen.getByLabelText("Close"));
    expect(document.querySelector(".value-modal")).toBeNull();
  });
});
