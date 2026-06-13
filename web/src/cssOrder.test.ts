// CSS ORDER TRIPWIRE — index.css has rule pairs with EQUAL specificity where
// source order decides the winner. Reordering them breaks paint silently: no
// type error, no test failure (jsdom computes no cascade), no console warning —
// only a real browser shows the regression. Both pairs below have already
// shipped broken once (caught by eye, 2026-06-12). This test is the same
// meta-test pattern the Python side uses for its import-purity invariants:
// assert the SOURCE, because the runtime can't be observed in CI.
//
// If this test fails, do NOT loosen it — move the rules back. The in-css
// comments next to each rule explain the dependency; keep them with the rules.
// Read via fs, NOT `import raw from "./index.css?raw"`: vitest's CSS stub
// intercepts .css imports before Vite's ?raw handling and returns an empty
// string (verified) — the import compiles everywhere and silently asserts
// nothing. fs reads the real file in the node test env.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const raw = readFileSync(fileURLToPath(new URL("./index.css", import.meta.url)), "utf8");
// Strip comments so a selector mentioned in prose never shadows its rule.
const css = raw.replace(/\/\*[\s\S]*?\*\//g, "");

describe("index.css order-dependent rule pairs", () => {
  it("generic .handle paint comes BEFORE .port-handle (equal specificity — later wins)", () => {
    const generic = css.indexOf(".react-flow__handle.handle");
    const port = css.indexOf(".react-flow__handle.port-handle");
    expect(generic, "the generic .react-flow__handle.handle rule is missing").toBeGreaterThan(-1);
    expect(port, "the .react-flow__handle.port-handle rule is missing").toBeGreaterThan(-1);
    expect(
      generic,
      ".react-flow__handle.port-handle must be defined AFTER the generic " +
        ".react-flow__handle.handle rule: both selectors have equal specificity " +
        "(0,2,0), so source order decides — defined earlier, every io-row dot " +
        "silently renders base grey instead of teal (shipped broken 2026-06-12). " +
        "See the in-css comment above the .port-handle rule.",
    ).toBeLessThan(port);
  });

  it(".node.dimmed comes BEFORE the .hover-mark un-dim rule (equal specificity — later wins)", () => {
    const dimmed = css.indexOf(".node.dimmed");
    const hoverMark = css.indexOf(".node.hover-mark");
    expect(dimmed, "the .node.dimmed rule is missing").toBeGreaterThan(-1);
    expect(hoverMark, "the .node.hover-mark rule is missing").toBeGreaterThan(-1);
    expect(
      dimmed,
      ".node.hover-mark must be defined AFTER .node.dimmed: equal specificity " +
        "(0,2,0), so source order decides whether a hovered chip can un-dim its " +
        "dimmed canvas node (opacity: 1 must win over opacity: 0.18). Defined " +
        "earlier, hover marks on dimmed nodes silently stay dim. See the in-css " +
        "comment above the .node.hover-mark rule.",
    ).toBeLessThan(hoverMark);
  });
});
