import { describe, expect, it } from "vitest";

import { CONDITION_COLOR, categoryLabel, kindColor, nodeColor, parseTemplate, previewValue } from "./format";

describe("condition presentation (decision code node = CONDITION pseudo-kind)", () => {
  it("a decision code node presents as CONDITION in the condition color", () => {
    const node = { kind: "code", is_decision: true };
    expect(categoryLabel(node)).toBe("CONDITION");
    expect(nodeColor(node)).toBe(CONDITION_COLOR);
  });

  it("a non-decision code node keeps the code identity", () => {
    const node = { kind: "code", is_decision: false };
    expect(categoryLabel(node)).toBe("CODE");
    expect(nodeColor(node)).toBe(kindColor("code"));
  });

  it("the kind gate is defensive: a non-code decider keeps its kind identity", () => {
    // is_decision ⟹ code today (dynamic `next` is code-only) — but if branching
    // ever extends, an llm/shell decider must not present as CONDITION and hide
    // what it runs.
    const node = { kind: "shell", is_decision: true };
    expect(categoryLabel(node)).toBe("SHELL");
    expect(nodeColor(node)).toBe(kindColor("shell"));
  });
});

describe("parseTemplate", () => {
  it("splits a multi-ref string into literal + ref segments", () => {
    const segments = parseTemplate("${a.x} and ${b.y}");
    const refs = segments.filter((s) => s.isRef).map((s) => s.text);
    expect(refs).toEqual(["a.x", "b.y"]);
    expect(segments.some((s) => !s.isRef && s.text.includes("and"))).toBe(true);
  });

  it("treats a pure literal as a single non-ref segment", () => {
    expect(parseTemplate("just text")).toEqual([{ text: "just text", isRef: false }]);
  });

  it("treats a pure ref as a single ref segment", () => {
    expect(parseTemplate("${only}")).toEqual([{ text: "only", isRef: true }]);
  });
});

describe("previewValue", () => {
  it("summarizes containers and collapses long strings", () => {
    expect(previewValue([1, 2, 3])).toBe("[3 items]");
    expect(previewValue({ a: 1, b: 2 })).toBe("{a, b}");
    expect(previewValue(null)).toBe("null");
    expect(previewValue(42)).toBe("42");
    expect(previewValue("x".repeat(200)).endsWith("…")).toBe(true);
  });
});
