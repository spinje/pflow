import { describe, expect, it } from "vitest";

import { refsBatchAlias, resolveBatchItems } from "./batchItems";

const ANALYZE_ITEMS = [
  { focus: "emotional", prompt: "Specialist: EMOTIONAL DEPTH." },
  { focus: "details", prompt: "Specialist: SENSORY DETAILS." },
];

describe("refsBatchAlias", () => {
  it("is true only when the value reads the alias", () => {
    expect(refsBatchAlias("${item.prompt}", "item")).toBe(true);
    expect(refsBatchAlias("prefix ${item.x} suffix", "item")).toBe(true);
    expect(refsBatchAlias("${content}", "item")).toBe(false); // a sibling input, not the alias
    expect(refsBatchAlias("${itemized.x}", "item")).toBe(false); // not the alias root
    expect(refsBatchAlias("plain text", "item")).toBe(false);
    expect(refsBatchAlias(42, "item")).toBe(false); // non-string
  });
});

describe("resolveBatchItems", () => {
  it("resolves a pure ${item.field} to each item's value, headed by its other fields", () => {
    const out = resolveBatchItems("${item.prompt}", "item", ANALYZE_ITEMS);
    expect(out).toEqual([
      { label: "focus: emotional", value: "Specialist: EMOTIONAL DEPTH." },
      { label: "focus: details", value: "Specialist: SENSORY DETAILS." },
    ]);
  });

  it("substitutes alias refs inside interpolated text, leaving non-alias refs verbatim", () => {
    const out = resolveBatchItems("Run ${item.focus} using ${shared.cfg}", "item", ANALYZE_ITEMS);
    expect(out?.map((r) => r.value)).toEqual([
      "Run emotional using ${shared.cfg}",
      "Run details using ${shared.cfg}",
    ]);
    // The READ field (`focus`) drops out of the header; the remaining short
    // scalar (`prompt`, here brief) heads the row. In the real case `prompt` is
    // long (>60), so it's excluded and `focus` becomes the header instead.
    expect(out?.map((r) => r.label)).toEqual([
      "prompt: Specialist: EMOTIONAL DEPTH.",
      "prompt: Specialist: SENSORY DETAILS.",
    ]);
  });

  it("resolves deep paths and leaves a missing field's ref verbatim", () => {
    const items = [{ id: 1, cfg: { mode: "fast" } }, { id: 2 }];
    const out = resolveBatchItems("${item.cfg.mode}", "item", items);
    expect(out?.map((r) => r.value)).toEqual(["fast", "${item.cfg.mode}"]); // item[1] has no cfg
    expect(out?.map((r) => r.label)).toEqual(["id: 1", "id: 2"]);
  });

  it("keeps a long scalar out of the header", () => {
    const items = [{ note: "x".repeat(80), prompt: "P" }];
    expect(resolveBatchItems("${item.prompt}", "item", items)?.[0]?.label).toBe("item[0]");
  });

  it("returns null when there is nothing to expand", () => {
    expect(resolveBatchItems("${item.prompt}", "item", null)).toBeNull(); // no items (dynamic batch)
    expect(resolveBatchItems("${item.prompt}", "item", [])).toBeNull();
    expect(resolveBatchItems("${content}", "item", ANALYZE_ITEMS)).toBeNull(); // no alias ref
    expect(resolveBatchItems(42, "item", ANALYZE_ITEMS)).toBeNull(); // a scalar with no leaf
    expect(resolveBatchItems({ GREETING: "${content}", N: 3 }, "item", ANALYZE_ITEMS)).toBeNull(); // dict, no alias ref
  });

  // A batch shell step binds per-item values through `env:` (Task 118) — a dict param.
  const GREET_ITEMS = [
    { name: "ada", greeting: "hi" },
    { name: "bob", greeting: "hey" },
  ];

  it("substitutes the alias in a dict's string leaves, rendered as the param's JSON", () => {
    const out = resolveBatchItems({ GREETING: "${item.greeting}", MODE: "${shared.mode}" }, "item", GREET_ITEMS);
    expect(out).toEqual([
      { label: "name: ada", value: JSON.stringify({ GREETING: "hi", MODE: "${shared.mode}" }, null, 2) },
      { label: "name: bob", value: JSON.stringify({ GREETING: "hey", MODE: "${shared.mode}" }, null, 2) },
    ]);
  });

  it("never substitutes a key, even one that looks like a ref", () => {
    const out = resolveBatchItems({ "${item.name}": "${item.greeting}" }, "item", GREET_ITEMS);
    expect(out?.map((r) => JSON.parse(r.value))).toEqual([{ "${item.name}": "hi" }, { "${item.name}": "hey" }]);
  });

  it("substitutes a leaf nested in a list", () => {
    const out = resolveBatchItems({ args: ["--to", "${item.name}"] }, "item", GREET_ITEMS);
    expect(out?.map((r) => JSON.parse(r.value))).toEqual([{ args: ["--to", "ada"] }, { args: ["--to", "bob"] }]);
    expect(out?.map((r) => r.label)).toEqual(["greeting: hi", "greeting: hey"]); // the read field drops out
  });

  it("renders a non-dict item value via fullValue and labels it by index", () => {
    const out = resolveBatchItems("${item}", "item", ["a", "b"]);
    expect(out).toEqual([
      { label: "item[0]", value: "a" },
      { label: "item[1]", value: "b" },
    ]);
  });
});
