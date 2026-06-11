// @vitest-environment jsdom
// The border chip rail: behavior modifiers (loop/batch) as chips. Pins the locked
// shoot-lab decisions (2026-06-10): literal batch shows the REAL count (×3), dynamic
// shows ×N with the iterated source in the tooltip (B3 — never a guessed number),
// loop rides the same vocabulary (C2), and a chip-less leaf adds zero DOM.

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { BatchSpec, LoopSpec, RFNode } from "../../types";
import { ChipRail } from "./ChipRail";

afterEach(cleanup);

function makeNode(over: Partial<RFNode>): RFNode {
  return {
    id: "n1",
    ref: { node_id: "step", ancestor_path: [], port: null },
    kind: "llm",
    purpose: "do things",
    params: [],
    io: null,
    loop: null,
    batch: null,
    parent: null,
    source: null,
    is_decision: false,
    is_terminal: false,
    is_group_host: false,
    is_transform: false,
    output_shape: null,
    unexpanded: null,
    annotations: {},
    ...over,
  };
}

const LOOP: LoopSpec = { polarity: "until", condition: "result.done", cap: 5, carry: {} };

function batch(over: Partial<BatchSpec>): BatchSpec {
  return { parallel: true, dynamic: false, as_name: "item", source_ref: null, count: null, items: null, ...over };
}

describe("ChipRail", () => {
  it("renders nothing for a node with no loop and no batch", () => {
    const { container } = render(<ChipRail node={makeNode({})} />);
    expect(container.querySelector(".chip-rail")).toBeNull();
  });

  it("literal batch chip shows the real count; tooltip says literal", () => {
    const node = makeNode({ batch: batch({ count: 3, items: [1, 2, 3] }) });
    const { container } = render(<ChipRail node={node} />);
    const chip = container.querySelector(".chip-batch");
    expect(chip?.textContent).toBe("×3");
    expect(chip?.getAttribute("title")).toBe("parallel batch over literal items");
  });

  it("dynamic batch chip shows ×N with the iterated source in the tooltip", () => {
    const node = makeNode({ batch: batch({ dynamic: true, source_ref: "${check_groups}" }) });
    const { container } = render(<ChipRail node={node} />);
    const chip = container.querySelector(".chip-batch");
    expect(chip?.textContent).toBe("×N");
    expect(chip?.getAttribute("title")).toBe("parallel batch over ${check_groups}");
  });

  it("sequential batch is named in the tooltip, not on the canvas", () => {
    const node = makeNode({ batch: batch({ parallel: false, count: 2, items: [1, 2] }) });
    const { container } = render(<ChipRail node={node} />);
    expect(container.querySelector(".chip-batch")?.getAttribute("title")).toBe("sequential batch over literal items");
  });

  it("loop chip carries the rule in its tooltip; both chips coexist (loop left of batch)", () => {
    const node = makeNode({ loop: LOOP, batch: batch({ dynamic: true, source_ref: "${groups}" }) });
    const { container } = render(<ChipRail node={node} />);
    const chips = [...container.querySelectorAll(".chip")];
    expect(chips.map((c) => [...c.classList].find((cls) => cls.startsWith("chip-")))).toEqual([
      "chip-loop",
      "chip-batch",
    ]);
    expect(chips[0]?.getAttribute("title")).toBe("loops until result.done (at most 5 iterations)");
  });

  it("children (the group expander) render even without chips, in the rightmost slot", () => {
    const { container } = render(
      <ChipRail node={makeNode({})}>
        <span className="group-toggle">7</span>
      </ChipRail>,
    );
    const rail = container.querySelector(".chip-rail");
    expect(rail).not.toBeNull();
    expect(rail?.lastElementChild?.classList.contains("group-toggle")).toBe(true);
  });
});
