// @vitest-environment jsdom
// Markdown rendering rules: block mode (panels), inline mode (catalog rows), and
// the security stance (raw HTML stays TEXT; images never fetch).

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { highlight } from "../utils/highlight";
import { Markdown } from "./Markdown";

// Keep CodeBlock synchronous (legacy <pre>) — fence ROUTING is what's under
// test here, not shiki output (CodeBlock.test.tsx covers the swap).
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});

afterEach(() => {
  cleanup();
  vi.mocked(highlight).mockClear();
});

describe("Markdown — block mode", () => {
  it("renders bold, code spans, and bullets as ELEMENTS — no literal markers", () => {
    const { container } = render(<Markdown text={"finds **tensions** in `code`\n\n- first\n- second"} />);
    expect(container.querySelector(".md")).toBeTruthy();
    expect(screen.getByText("tensions").tagName).toBe("STRONG");
    expect(screen.getByText("code").tagName).toBe("CODE");
    expect([...container.querySelectorAll("li")].map((li) => li.textContent)).toEqual(["first", "second"]);
    expect(container.textContent).not.toContain("**");
  });

  it("routes a fenced block to CodeBlock with its language", () => {
    const { container } = render(<Markdown text={"intro\n\n```python\nx = 1\n```"} />);
    const pre = container.querySelector("pre.read-param-value");
    expect(pre?.textContent).toBe("x = 1");
    expect(highlight).toHaveBeenCalledWith("x = 1", "python");
  });

  it("an unknown fence language fails closed to plain text (highlight never called)", () => {
    const { container } = render(<Markdown text={"```brainfuck\n+++\n```"} />);
    expect(container.querySelector("pre.read-param-value")?.textContent).toBe("+++");
    expect(highlight).not.toHaveBeenCalled();
  });

  it("SECURITY: raw HTML renders as text, never as elements", () => {
    const { container } = render(<Markdown text={'before <script>alert("x")</script> <b>bold?</b> after'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    // the markup stays VISIBLE as text (react-markdown's skipped-HTML default
    // keeps the surrounding text; the tags themselves render inert)
    expect(container.textContent).toContain("bold?");
  });

  it("links open in a new tab; images render their alt text only (no fetch)", () => {
    const { container } = render(<Markdown text={"[docs](https://x.test) and ![a diagram](https://x.test/i.png)"} />);
    const a = container.querySelector("a");
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toBe("noreferrer");
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("a diagram");
  });
});

describe("Markdown — inline mode (catalog)", () => {
  it("flattens lists and paragraphs to one flow with word separation, keeping inline formatting", () => {
    const { container } = render(<Markdown text={"Intro line.\n\n- **first** item\n- second item\n\n# A header"} inline />);
    expect(container.querySelector(".md")).toBeNull(); // no block wrapper at all
    expect(container.querySelector("p")).toBeNull();
    expect(container.querySelector("li")).toBeNull();
    expect(container.querySelector("h1")).toBeNull();
    expect(screen.getByText("first").tagName).toBe("STRONG");
    // block boundaries become whitespace, never concatenation ("itemsecond")
    const flat = container.textContent!.replace(/\s+/g, " ");
    expect(flat).toContain("first item second item");
    expect(flat).toContain("Intro line.");
    expect(flat).toContain("A header");
  });

  it("links flatten to their text (catalog rows are <button>s) and images to their alt", () => {
    const { container } = render(<Markdown text={"see [the docs](https://x.test) ![icon](https://x.test/i.png)"} inline />);
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("the docs");
    expect(container.textContent).toContain("icon");
  });
});
