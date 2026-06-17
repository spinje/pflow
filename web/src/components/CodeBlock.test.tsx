// @vitest-environment jsdom
// CodeBlock render rules: the synchronous first paint is the LEGACY rendering
// (plain text + ref-marks), shiki hast only ever swaps in later, and the swap is
// gated on the mark count. `highlight` is mocked (controllable per test);
// markRefs/codeChildren stay real — they're the pure logic under test here.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import type { Element, Root, Text } from "hast";

import { highlight } from "../utils/highlight";
import { CodeBlock } from "./CodeBlock";

vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn() };
});

afterEach(() => {
  cleanup();
  vi.mocked(highlight).mockReset();
});

const text = (value: string): Text => ({ type: "text", value });
const el = (tagName: string, children: Array<Text | Element>, className?: string[]): Element => ({
  type: "element",
  tagName,
  properties: className ? { className } : {},
  children,
});
/** A shiki-shaped root (pre > code > tokens) around the given token elements. */
const shikiRoot = (...tokens: Array<Text | Element>): Root => ({
  type: "root",
  children: [el("pre", [el("code", tokens)])],
});

describe("CodeBlock", () => {
  it("renders the legacy output SYNCHRONOUSLY — including the ${ref} marks", () => {
    vi.mocked(highlight).mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(<CodeBlock code={"use ${a.b} and ${c.d}"} lang="markdown" highlightRef="a.b" />);
    // no await: the marks are on the FIRST paint
    const marks = [...container.querySelectorAll("mark.ref-mark")].map((m) => m.textContent);
    expect(marks).toEqual(["${a.b}"]);
    expect(container.querySelector("pre.read-param-value")!.textContent).toBe("use ${a.b} and ${c.d}");
  });

  it("lang=null renders exactly the legacy path and never calls highlight", () => {
    const { container } = render(<CodeBlock code="plain value" lang={null} />);
    expect(container.querySelector("pre.read-param-value")!.textContent).toBe("plain value");
    expect(highlight).not.toHaveBeenCalled();
  });

  it("highlighted token spans swap in when the hast arrives", async () => {
    vi.mocked(highlight).mockResolvedValue(shikiRoot(el("span", [text("x = 1")], ["tok"])));
    const { container } = render(<CodeBlock code="x = 1" lang="python" />);
    await waitFor(() => expect(container.querySelector("span.tok")).toBeTruthy());
    expect(container.querySelector("pre.shiki-host")!.textContent).toBe("x = 1");
  });

  it("NO nested <pre>: shiki's pre/code unwrap into our single container", async () => {
    vi.mocked(highlight).mockResolvedValue(shikiRoot(el("span", [text("x = 1")], ["tok"])));
    const { container } = render(<CodeBlock code="x = 1" lang="python" />);
    await waitFor(() => expect(container.querySelector("span.tok")).toBeTruthy());
    // shiki's own <pre> (UA white-space: pre) must not survive inside ours —
    // it would defeat the container's pre-wrap (horizontal scrollbars).
    expect(container.querySelectorAll("pre")).toHaveLength(1);
    expect(container.querySelector("pre")!.className).toContain("read-param-value");
  });

  it("the count rule: a tokenizer-split ref keeps the LEGACY rendering (marks never downgrade)", async () => {
    // Two matching refs in the plain text, but the hast splits the second across
    // text nodes — markRefs lands 1 of 2, so the swap is refused.
    vi.mocked(highlight).mockResolvedValue(shikiRoot(el("span", [text("${a.b} and ${a.")]), el("span", [text("b}")])));
    const { container } = render(<CodeBlock code={"${a.b} and ${a.b}"} lang="markdown" highlightRef="a.b" />);
    await waitFor(() => expect(highlight).toHaveBeenCalled());
    await Promise.resolve(); // flush the resolved-hast microtask
    expect(container.querySelector("pre.shiki-host")).toBeNull();
    const marks = [...container.querySelectorAll("mark.ref-mark")].map((m) => m.textContent);
    expect(marks).toEqual(["${a.b}", "${a.b}"]); // the full legacy marking, untouched
  });

  it("with highlightRef, a fully-markable hast swaps in WITH its marks", async () => {
    vi.mocked(highlight).mockResolvedValue(shikiRoot(el("span", [text("use ${a.b} here")], ["tok"])));
    const { container } = render(<CodeBlock code={"use ${a.b} here"} lang="markdown" highlightRef="a.b" />);
    await waitFor(() => expect(container.querySelector("pre.shiki-host")).toBeTruthy());
    const marks = [...container.querySelectorAll("mark.ref-mark")].map((m) => m.textContent);
    expect(marks).toEqual(["${a.b}"]);
    expect(container.querySelector("span.tok")).toBeTruthy();
  });

  it("teals EVERY ${ref} in a markdown value (no highlightRef) — the canvas language", () => {
    vi.mocked(highlight).mockReturnValue(new Promise(() => {})); // stay on the sync plain path
    const { container } = render(<CodeBlock code={"Use ${a.b} and ${c.d}"} lang="markdown" />);
    expect([...container.querySelectorAll("span.src-ref")].map((s) => s.textContent)).toEqual(["${a.b}", "${c.d}"]);
    expect(container.querySelectorAll("mark.ref-mark")).toHaveLength(0);
  });

  it("with highlightRef in markdown: the selected ref is the bright mark, the rest teal", () => {
    vi.mocked(highlight).mockReturnValue(new Promise(() => {}));
    const { container } = render(<CodeBlock code={"Use ${a.b} and ${c.d}"} lang="markdown" highlightRef="a.b" />);
    expect([...container.querySelectorAll("mark.ref-mark")].map((m) => m.textContent)).toEqual(["${a.b}"]);
    expect([...container.querySelectorAll("span.src-ref")].map((s) => s.textContent)).toEqual(["${c.d}"]);
  });

  it("does NOT teal refs in a code value — shiki owns it (a bash ${VAR} is not a pflow ref)", () => {
    vi.mocked(highlight).mockReturnValue(new Promise(() => {}));
    const { container } = render(<CodeBlock code={"x = ${a.b}"} lang="python" />);
    expect(container.querySelectorAll("span.src-ref")).toHaveLength(0);
    expect(container.querySelector("pre.read-param-value")!.textContent).toBe("x = ${a.b}");
  });

  it("teals refs in the shiki hast once it swaps in (markdown)", async () => {
    vi.mocked(highlight).mockResolvedValue(shikiRoot(el("span", [text("Use ${a.b}")], ["tok"])));
    const { container } = render(<CodeBlock code={"Use ${a.b}"} lang="markdown" />);
    await waitFor(() => expect(container.querySelector("pre.shiki-host")).toBeTruthy());
    expect([...container.querySelectorAll("span.src-ref")].map((s) => s.textContent)).toEqual(["${a.b}"]);
  });
});
