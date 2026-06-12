// @vitest-environment jsdom
// The shared chip module: the data-neighbor derivations, ConnectionSections'
// no-claims rule, and the hover→canvas channel (Interaction.hoverNode). Chips
// are plain components (no React Flow context) — they render under jsdom.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Chip, ConnectionSections, consumersOf, producersOf } from "./Chip";
import { InteractionProvider } from "./interaction";
import type { RFEdge, RFGraph, RFNode } from "../types";

afterEach(cleanup);

// Production-style ids: flat ids (n1/n2) NEVER equal ref.node_id — an id↔name
// confusion must fail here, not pass vacuously (the EdgePanel fixture rule).
function node(id: string, over: Partial<RFNode> = {}): RFNode {
  return {
    id,
    ref: { node_id: id, ancestor_path: [], port: null },
    kind: "shell",
    purpose: "",
    params: [],
    io: null,
    loop: null,
    batch: null,
    parent: null,
    source: null,
    is_decision: false,
    is_terminal: false,
    is_transform: false,
    output_shape: null,
    is_group_host: false,
    unexpanded: null,
    annotations: {},
    ...over,
  };
}

function edge(id: string, source: string, target: string, kind: RFEdge["kind"], over: Partial<RFEdge> = {}): RFEdge {
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [], ...over };
}

const noop = (): void => {};

// gen feeds use-a twice (two fields) and use-b once; a sequential edge and an
// inbound data edge must not count.
const genNode = node("n1", { ref: { node_id: "gen", ancestor_path: [], port: null }, kind: "llm" });
const useANode = node("n2", { ref: { node_id: "use-a", ancestor_path: [], port: null }, kind: "code" });
const useBNode = node("n3", { ref: { node_id: "use-b", ancestor_path: [], port: null }, kind: "code" });
const graph: RFGraph = {
  nodes: [genNode, useANode, useBNode],
  edges: [
    edge("e1", "n1", "n2", "data_flow", { output_field: "response", input_name: "x" }),
    edge("e2", "n1", "n2", "data_flow", { output_field: "response", input_name: "y" }),
    edge("e3", "n1", "n3", "data_flow", { output_field: "response", input_name: "z" }),
    edge("e4", "n1", "n2", "sequential"),
    edge("e5", "n3", "n1", "data_flow", { output_field: "result", input_name: "w" }),
  ],
  groups: [],
};

describe("consumersOf / producersOf", () => {
  it("consumersOf returns data-flow targets deduped, in edge order; ignores sequential and inbound edges", () => {
    expect(consumersOf(graph, "n1").map((n) => n.ref.node_id)).toEqual(["use-a", "use-b"]);
  });

  it("producersOf is the upstream mirror (gen reads from use-b via e5)", () => {
    expect(producersOf(graph, "n1").map((n) => n.ref.node_id)).toEqual(["use-b"]);
    expect(producersOf(graph, "n3").map((n) => n.ref.node_id)).toEqual(["gen"]);
  });

  it("a node with no outgoing data-flow edges has no consumers", () => {
    expect(consumersOf(graph, "n2")).toEqual([]);
  });
});

describe("ConnectionSections", () => {
  it("renders references (upstream) FIRST, then referenced by (downstream), one chip per neighbor", () => {
    render(
      <ConnectionSections node={genNode} graph={graph} renderedIds={new Set(["n1", "n2", "n3"])} onNavigate={noop} />,
    );
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["references (1)", "referenced by (2)"]);
    expect(screen.getByText("use-a")).toBeTruthy();
    expect(screen.getAllByText("use-b").length).toBe(2); // producer of gen AND consumer of gen
  });

  it("an empty direction renders NO section — the no-claims rule (quiet ≠ unconsumed)", () => {
    // use-b (n3): reads from gen (references=1), feeds gen (referenced by=1).
    // use-a (n2): receives only — no outgoing data edges → no "referenced by".
    render(
      <ConnectionSections node={useANode} graph={graph} renderedIds={new Set(["n1", "n2", "n3"])} onNavigate={noop} />,
    );
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["references (1)"]); // no "referenced by" claim
  });
});

describe("Chip hover → canvas highlight (Interaction.hoverNode)", () => {
  function renderChip(target: RFNode, rendered: string[], hoverNode: (id: string | null) => void): void {
    render(
      <InteractionProvider value={{ focusPort: noop, toggleGroup: noop, hoverNode, hoverRow: noop }}>
        <Chip node={target} graph={graph} renderedIds={new Set(rendered)} onNavigate={noop} />
      </InteractionProvider>,
    );
  }

  it("mouse enter marks the RESOLVED flat id; leave clears it", () => {
    const hoverNode = vi.fn();
    renderChip(useANode, ["n1", "n2", "n3"], hoverNode);
    const chip = screen.getByText("use-a").closest("button")!;
    fireEvent.mouseEnter(chip);
    expect(hoverNode).toHaveBeenLastCalledWith("n2");
    fireEvent.mouseLeave(chip);
    expect(hoverNode).toHaveBeenLastCalledWith(null);
  });

  it("a disabled (unrendered-endpoint) chip never fires hover", () => {
    const hoverNode = vi.fn();
    renderChip(useANode, ["n1", "n3"], hoverNode); // n2 not rendered
    const chip = screen.getByText("use-a").closest("button")!;
    expect(chip.disabled).toBe(true);
    fireEvent.mouseEnter(chip);
    fireEvent.mouseLeave(chip);
    expect(hoverNode).not.toHaveBeenCalled();
  });
});

describe("io-port chips — scope prefix + hover", () => {
  // create-songs (n9, hosts group g1) has a nested input port `concept` (n10);
  // the root workflow's own input `sources` (n11) sits in a parentless wrapper.
  const ioGraph: RFGraph = {
    nodes: [
      node("n9", { ref: { node_id: "create-songs", ancestor_path: [], port: null }, kind: "workflow", is_group_host: true }),
      node("n10", {
        ref: { node_id: "concept", ancestor_path: [{ node_id: "create-songs", batch_index: null }], port: "in" },
        kind: "input",
        io: { data_type: "object", required: true, default: null },
      }),
      node("n11", {
        ref: { node_id: "sources", ancestor_path: [], port: "in" },
        kind: "input",
        io: { data_type: "array", required: true, default: null },
      }),
    ],
    edges: [],
    groups: [
      { id: "g1", kind: "workflow", parent: null, host: "n9", members: ["n9"], nesting_depth: 0, annotations: {} },
      { id: "g2", kind: "input_wrapper", parent: "g1", host: null, members: ["n10"], nesting_depth: 1, annotations: {} },
      { id: "g3", kind: "input_wrapper", parent: null, host: null, members: ["n11"], nesting_depth: 0, annotations: {} },
    ],
  };

  function renderIoChip(target: RFNode, hoverNode: (id: string | null) => void = noop): void {
    render(
      <InteractionProvider value={{ focusPort: noop, toggleGroup: noop, hoverNode, hoverRow: noop }}>
        <Chip node={target} graph={ioGraph} renderedIds={new Set(["n9", "g1"])} onNavigate={noop} />
      </InteractionProvider>,
    );
  }

  it("a NESTED port is scope-prefixed with its owner step (create-songs.concept)", () => {
    renderIoChip(ioGraph.nodes[1]!);
    expect(screen.getByText("create-songs.")).toBeTruthy(); // the faint scope span
    expect(screen.getByText("concept")).toBeTruthy();
    expect(screen.getByTitle("input of create-songs")).toBeTruthy();
  });

  it("a ROOT port stays bare (the panel already names the workflow)", () => {
    renderIoChip(ioGraph.nodes[2]!);
    expect(screen.getByText("sources")).toBeTruthy();
    expect(screen.queryByText(/\./)).toBeNull(); // no scope span
    expect(screen.getByTitle("io port")).toBeTruthy();
  });

  it("hovering an io-port chip marks the PORT id (the owner box + row consume it)", () => {
    const hoverNode = vi.fn();
    renderIoChip(ioGraph.nodes[1]!, hoverNode);
    const chip = screen.getByText("concept").closest("button")!;
    fireEvent.mouseEnter(chip);
    expect(hoverNode).toHaveBeenLastCalledWith("n10");
    fireEvent.mouseLeave(chip);
    expect(hoverNode).toHaveBeenLastCalledWith(null);
  });
});
