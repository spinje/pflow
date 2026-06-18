import { describe, expect, it } from "vitest";

import {
  CONDITION_COLOR,
  TRANSFORM_COLOR,
  categoryLabel,
  kindColor,
  nodeColor,
  paramLanguage,
  parseTemplate,
  previewValue,
  stripMarkdown,
} from "./format";
import { HIGHLIGHT_LANGS } from "./highlight";

describe("condition presentation (decision code node = CONDITION pseudo-kind)", () => {
  it("a decision code node presents as CONDITION in the condition color", () => {
    const node = { kind: "code", is_decision: true, is_transform: false };
    expect(categoryLabel(node)).toBe("CONDITION");
    expect(nodeColor(node)).toBe(CONDITION_COLOR);
  });

  it("a non-decision code node keeps the code identity", () => {
    const node = { kind: "code", is_decision: false, is_transform: false };
    expect(categoryLabel(node)).toBe("CODE");
    expect(nodeColor(node)).toBe(kindColor("code"));
  });

  it("the kind gate is defensive: a non-code decider keeps its kind identity", () => {
    // is_decision ⟹ code today (dynamic `next` is code-only) — but if branching
    // ever extends, an llm/shell decider must not present as CONDITION and hide
    // what it runs.
    const node = { kind: "shell", is_decision: true, is_transform: false };
    expect(categoryLabel(node)).toBe("SHELL");
    expect(nodeColor(node)).toBe(kindColor("shell"));
  });
});

describe("transform presentation (pure-reshape code node = TRANSFORM pseudo-kind)", () => {
  it("a transform code node presents as TRANSFORM in cyan", () => {
    const node = { kind: "code", is_decision: false, is_transform: true };
    expect(categoryLabel(node)).toBe("TRANSFORM");
    expect(nodeColor(node)).toBe(TRANSFORM_COLOR);
  });

  it("CONDITION wins defensively if both facts ever claim a node", () => {
    // Impossible by construction (the Python classifier excludes next-setters)
    // — but if that invariant ever breaks, the routing role is the louder fact.
    const node = { kind: "code", is_decision: true, is_transform: true };
    expect(categoryLabel(node)).toBe("CONDITION");
    expect(nodeColor(node)).toBe(CONDITION_COLOR);
  });

  it("the kind gate is defensive: a non-code is_transform keeps its kind identity", () => {
    const node = { kind: "shell", is_decision: false, is_transform: true };
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

describe("stripMarkdown (canvas/tooltip de-noiser — hide markers, keep content)", () => {
  it("strips emphasis and code-span markers, keeping the text", () => {
    expect(stripMarkdown("finds **tensions** in `code`")).toBe("finds tensions in code");
    expect(stripMarkdown("an *emphasized* and _underscored_ word")).toBe("an emphasized and underscored word");
    expect(stripMarkdown("__strong__ too")).toBe("strong too");
  });

  it("strips heading, bullet, and blockquote markers and flattens to one line", () => {
    expect(stripMarkdown("# Title\n- first\n- second\n> quoted")).toBe("Title first second quoted");
    expect(stripMarkdown("1. one\n2. two")).toBe("one two");
    expect(stripMarkdown("* star bullet\n+ plus bullet")).toBe("star bullet plus bullet");
  });

  it("renders links as their text and images as their alt", () => {
    expect(stripMarkdown("see [the docs](https://x.test) here")).toBe("see the docs here");
    expect(stripMarkdown("![a diagram](img.png) above")).toBe("a diagram above");
  });

  it("leaves plain text untouched (modulo whitespace collapse)", () => {
    expect(stripMarkdown("just a plain sentence")).toBe("just a plain sentence");
  });

  it("never throws on pathological input; unpaired markers stay verbatim", () => {
    expect(stripMarkdown("**unclosed")).toBe("**unclosed");
    expect(stripMarkdown("")).toBe("");
  });

  // The three corruption pins: stripping must NEVER pair markers that carry
  // meaning. (CommonMark actually emphasizes intraword `*` — "2*3 and 4*5"
  // renders as 2<em>3 and 4</em>5 in the panel — but stripping those stars
  // turns arithmetic into different numbers, so the strip is deliberately more
  // conservative than the renderer: under-strip, never corrupt.)
  it("snake_case identifiers survive", () => {
    expect(stripMarkdown("joins items_list and total_count")).toBe("joins items_list and total_count");
  });

  it("*.py globs survive", () => {
    expect(stripMarkdown("delete *.tmp and *.log files")).toBe("delete *.tmp and *.log files");
  });

  it("2*3 arithmetic survives", () => {
    expect(stripMarkdown("2*3 and 4*5")).toBe("2*3 and 4*5");
  });

  // Review-caught corruption shapes (silent-failures, 2026-06-12):
  it("code-span content is SHIELDED from the marker rules", () => {
    expect(stripMarkdown("calls `__init__` on each item")).toBe("calls __init__ on each item");
    expect(stripMarkdown("wraps in `*emphasis*` markers")).toBe("wraps in *emphasis* markers");
    expect(stripMarkdown("`*args, **kwargs` pass through")).toBe("*args, **kwargs pass through");
  });

  it("a delimiter is never eaten as content (the \\S-tail hole)", () => {
    expect(stripMarkdown("use *args and **kwargs")).toBe("use *args and **kwargs");
  });

  it("underscore never closes intraword (the CommonMark `_` rule)", () => {
    expect(stripMarkdown("_private_var stays whole")).toBe("_private_var stays whole");
  });

  it("emphasis never pairs across a blank line (inlines are per-paragraph)", () => {
    expect(stripMarkdown("**a\n\nb** stays marked")).toBe("**a b** stays marked");
  });
});

describe("paramLanguage (fail-closed: null = render plain, exactly as today)", () => {
  it("any object value is json, regardless of kind or name", () => {
    expect(paramLanguage("llm", "output_schema", { type: "object" })).toBe("json");
    expect(paramLanguage("mcp-github-create_issue", "labels", ["bug"])).toBe("json");
    expect(paramLanguage("http", "headers", { Accept: "json" })).toBe("json");
  });

  it("kind/name pairs with a known string language", () => {
    expect(paramLanguage("code", "code", "result = {}")).toBe("python");
    expect(paramLanguage("shell", "command", "ls -la")).toBe("bash");
    expect(paramLanguage("llm", "prompt", "Write a poem")).toBe("markdown");
    expect(paramLanguage("llm", "system", "You are terse")).toBe("markdown");
    expect(paramLanguage("claude-code", "prompt", "Fix the bug")).toBe("markdown");
    expect(paramLanguage("claude-code", "system_prompt", "Be careful")).toBe("markdown");
  });

  it("branches on the VALUE type, never the name: a string output_schema is plain", () => {
    expect(paramLanguage("llm", "output_schema", "${shared.schema}")).toBeNull();
  });

  it("everything else fails closed to plain text", () => {
    expect(paramLanguage("http", "body", '{"k": 1}')).toBeNull(); // no content sniffing
    expect(paramLanguage("write-file", "content", "def f(): pass")).toBeNull();
    expect(paramLanguage("mcp-slack-post", "text", "hello")).toBeNull();
    expect(paramLanguage("unknown-kind", "anything", "text")).toBeNull();
    expect(paramLanguage("code", "code", 42)).toBeNull(); // non-string scalar
  });

  it("every language the table can emit is a grammar the seam ships (no silent un-highlight drift)", () => {
    const emitted = [
      paramLanguage("any", "any", {}),
      paramLanguage("code", "code", "x"),
      paramLanguage("shell", "command", "x"),
      paramLanguage("llm", "prompt", "x"),
      paramLanguage("claude-code", "system_prompt", "x"),
    ];
    for (const lang of emitted) {
      expect(lang).not.toBeNull();
      expect(HIGHLIGHT_LANGS).toContain(lang);
    }
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
