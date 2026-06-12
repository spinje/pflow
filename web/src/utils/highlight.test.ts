// The highlight seam, under real shiki (node-env — the pure-JS engine needs no
// DOM). The FAILURE tests run first: the module memoizes its highlighter
// promise, so once a load succeeds the failure path is unreachable in this
// module instance — declaration order is load-bearing here.

import { describe, expect, it, vi } from "vitest";
import type { Element, Root, Text } from "hast";

import { codeChildren, highlight, markRefs } from "./highlight";

// Wrap createHighlighterCore with a controllable failure + attempt counter: a
// rejected CREATION must reset the memo (a stale tab's 404'd chunk is transient
// — the next call must retry, not stay un-highlighted all session).
const state = vi.hoisted(() => ({ attempts: 0, fail: false }));
vi.mock("shiki/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("shiki/core")>();
  return {
    ...actual,
    createHighlighterCore: (opts: Parameters<typeof actual.createHighlighterCore>[0]) => {
      state.attempts++;
      if (state.fail) return Promise.reject(new Error("chunk load failed"));
      return actual.createHighlighterCore(opts);
    },
  };
});

function texts(root: Root): string {
  let out = "";
  const visit = (node: Root | Element): void => {
    for (const child of node.children) {
      if (child.type === "element") visit(child);
      else if (child.type === "text") out += child.value;
    }
  };
  visit(root);
  return out;
}

function countSpans(root: Root): number {
  let n = 0;
  const visit = (node: Root | Element): void => {
    for (const child of node.children) {
      if (child.type === "element") {
        if (child.tagName === "span") n++;
        visit(child);
      }
    }
  };
  visit(root);
  return n;
}

describe("highlight — load failure degrades and retries (order-sensitive: must run before any success)", () => {
  it("a failed load yields null + a warning, is NOT memoized, and the next attempt recovers", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      state.fail = true;
      expect(await highlight("x = 1", "python")).toBeNull();
      expect(warn).toHaveBeenCalledTimes(1);
      // the rejection was not memoized: the second call attempts a fresh load
      expect(await highlight("x = 1", "python")).toBeNull();
      expect(state.attempts).toBe(2);

      state.fail = false;
      const root = await highlight("x = 1", "python");
      expect(root).not.toBeNull();
      expect(state.attempts).toBe(3);
    } finally {
      state.fail = false;
      warn.mockRestore();
    }
  });
});

describe("highlight — real grammars", () => {
  it("python/json/markdown produce hast with token spans and lossless text", async () => {
    for (const [code, lang] of [
      ['def f():\n    return {"a": 1}', "python"],
      ['{"key": [1, 2]}', "json"],
      ["# Title\n\nSome **bold** text", "markdown"],
    ] as const) {
      const root = await highlight(code, lang);
      expect(root).not.toBeNull();
      expect(countSpans(root!)).toBeGreaterThan(0);
      expect(texts(root!)).toBe(code);
    }
  });

  it("an unknown language fails closed to null", async () => {
    expect(await highlight("whatever", "brainfuck")).toBeNull();
  });

  it("oversize input fails closed to null (shiki tokenizes on the main thread)", async () => {
    expect(await highlight("x".repeat(50_001), "python")).toBeNull();
  });

  it("codeChildren unwraps shiki's pre > code so the host <pre> stays ours", async () => {
    const root = await highlight("x = 1", "python");
    const children = codeChildren(root!);
    expect(children).not.toBeNull();
    expect(children!.length).toBeGreaterThan(0);
    // no <pre> survives inside the extracted children
    const hasPre = children!.some((c) => c.type === "element" && c.tagName === "pre");
    expect(hasPre).toBe(false);
  });
});

describe("markRefs — count-based ref marking over hast text nodes", () => {
  const text = (value: string): Text => ({ type: "text", value });
  const span = (...children: Text[]): Element => ({ type: "element", tagName: "span", properties: {}, children });
  const tree = (...children: Array<Text | Element>): Root => ({ type: "root", children });

  function marks(root: Root): string[] {
    const found: string[] = [];
    const visit = (node: Root | Element): void => {
      for (const child of node.children) {
        if (child.type !== "element") continue;
        if (child.tagName === "mark") found.push((child.children[0] as Text).value);
        else visit(child);
      }
    };
    visit(root);
    return found;
  }

  it("wraps every matching ${ref} in a .ref-mark <mark> and returns the count", () => {
    const root = tree(span(text("use ${gen.result} and ${gen.result.ok} here")));
    expect(markRefs(root, "gen.result")).toBe(2);
    expect(marks(root)).toEqual(["${gen.result}", "${gen.result.ok}"]);
    expect(texts(root)).toBe("use ${gen.result} and ${gen.result.ok} here");
  });

  it("returns 0 and leaves the tree untouched when nothing matches", () => {
    const root = tree(span(text("use ${other.field} here")));
    expect(markRefs(root, "gen.result")).toBe(0);
    expect(marks(root)).toEqual([]);
  });

  it("matches per coalesce operand (the shared refMatchesHighlight rule)", () => {
    const root = tree(span(text('${gen.result ?? "fallback"}')));
    expect(markRefs(root, "gen.result")).toBe(1);
    expect(marks(root)).toEqual(['${gen.result ?? "fallback"}']);
  });

  it("a ref split across text nodes stays unmarked — the count exposes it", () => {
    // The tokenizer can split "${a.b}" over two spans; cross-node merging is
    // deliberately NOT attempted — the caller's count comparison catches it.
    const root = tree(span(text("${a.b} and ${a.")), span(text("b}")));
    expect(markRefs(root, "a.b")).toBe(1); // only the intact one
  });

  it("marks land inside real shiki output (integration with highlight)", async () => {
    const root = await highlight("Summarize ${doc.body} briefly", "markdown");
    expect(root).not.toBeNull();
    const landed = markRefs(root!, "doc.body");
    expect(landed).toBe(1);
    expect(marks(root!)).toEqual(["${doc.body}"]);
  });
});
