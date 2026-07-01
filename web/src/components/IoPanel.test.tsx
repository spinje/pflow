// @vitest-environment jsdom
// IoPanel render tests — the workflow-interface panel a root IO card opens.
// Production-style divergent ids (flat n*/g* never equal ref.node_id), the
// EdgePanel fixture convention: an id↔name confusion must fail, not pass
// vacuously.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { IoPanel } from "./IoPanel";
import type { RFEdge, RFGraph, RFGroup, RFNode, RFRef, RunNodeDetail } from "../types";

// Task 175 — the per-port "this run" value fetch (mirrors ThisRunSection's mock of the same seam).
vi.mock("../api/client", () => ({ fetchRunNode: vi.fn() }));
// Same insulation as EdgePanel/GraphView: a port description with a fenced
// block would mount CodeBlock and run the real shiki load under jsdom —
// setState after assertions + cross-test bleed through the memoized promise.
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});
import { fetchRunNode } from "../api/client";
const mockFetch = vi.mocked(fetchRunNode);

afterEach(cleanup);

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
    cached_prefix: null,
    is_group_host: false,
    unexpanded: null,
    annotations: {},
    ...over,
  };
}

function edge(id: string, source: string, target: string, kind: RFEdge["kind"], over: Partial<RFEdge> = {}): RFEdge {
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [], ...over };
}

function group(id: string, kind: RFGroup["kind"], over: Partial<RFGroup> = {}): RFGroup {
  return { id, kind, parent: null, host: null, members: [], nesting_depth: 0, annotations: {}, ...over };
}

const noop = (): void => {};

// A root workflow: two inputs (one described + defaulted optional, one bare
// required), one output sourced from a producer's result.summary.
const graph: RFGraph = {
  nodes: [
    node("n1", {
      ref: { node_id: "topic", ancestor_path: [], port: "in" },
      kind: "input",
      purpose: "What to research.",
      io: { data_type: "string", required: true, default: null },
      parent: "g0",
    }),
    node("n2", {
      ref: { node_id: "limit", ancestor_path: [], port: "in" },
      kind: "input",
      io: { data_type: "integer", required: false, default: 5 },
      parent: "g0",
    }),
    node("n3", {
      ref: { node_id: "report", ancestor_path: [], port: "out" },
      kind: "output",
      purpose: "Concise summary of the run.",
      // No authored `type:` — the entry's type must DERIVE from the producer's
      // shape (never the old "any" filler).
      io: { data_type: null, required: false, default: null },
      source: { file: "lyrics-generator.pflow.md", line: 12 },
      parent: "g1",
    }),
    node("n4", { ref: { node_id: "research", ancestor_path: [], port: null }, kind: "llm" }),
    node("n5", {
      ref: { node_id: "summary-report", ancestor_path: [], port: null },
      kind: "code",
      output_shape: { field: "result", data_type: "dict", keys: [{ name: "summary", data_type: "str" }] },
    }),
  ],
  edges: [
    edge("e1", "n1", "n4", "data_flow", { input_name: "prompt" }),
    edge("e2", "n1", "n5", "data_flow", { input_name: "prompt" }),
    edge("e3", "n5", "n3", "data_flow", { output_field: "result", output_path: ["summary"] }),
  ],
  groups: [
    group("g0", "input_wrapper", { members: ["n1", "n2"] }),
    group("g1", "output_wrapper", { members: ["n3"] }),
  ],
};

function show(
  groupId: string,
  over: {
    rendered?: string[];
    markedPortId?: string | null;
    onNavigate?: (f: string, s?: string | null) => void;
    hasRunContext?: boolean;
    runId?: string | null;
    completedRunId?: string | null;
  } = {},
): void {
  const g = graph.groups.find((x) => x.id === groupId)!;
  render(
    <IoPanel
      group={g}
      graph={graph}
      workflowName="lyrics-generator"
      workflow="lyrics-generator"
      runId={over.runId ?? null}
      hasRunContext={over.hasRunContext ?? false}
      completedRunId={over.completedRunId ?? null}
      renderedIds={new Set(over.rendered ?? graph.nodes.map((n) => n.id))}
      markedPortId={over.markedPortId ?? null}
      onNavigate={over.onNavigate ?? noop}
      onClose={noop}
    />,
  );
}

describe("IoPanel — inputs", () => {
  it("titles the workflow, counts the ports, and shows type/required/default/description per entry", () => {
    show("g0");
    expect(screen.getByText("workflow inputs")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("lyrics-generator");
    expect(screen.getByText("2 inputs")).toBeTruthy();
    expect(screen.getByText("topic")).toBeTruthy();
    expect(screen.getByText("string · required")).toBeTruthy();
    expect(screen.getByText("What to research.")).toBeTruthy();
    // The optional input shows its type without the required mark, plus its default.
    expect(screen.getByText("integer")).toBeTruthy();
    expect(screen.getByText("5")).toBeTruthy();
    expect(screen.getByText(/default:/)).toBeTruthy();
  });

  it("the header avatar name navigates to the io card on click (re-center)", () => {
    const onNavigate = vi.fn();
    show("g0", { onNavigate });
    // The name is the panel <h2>; clicking it focuses the io card itself
    // (group id = the rendered card's flat id) — no selectedId, the panel stays.
    screen.getByRole("heading", { level: 2 }).querySelector("button")!.click();
    expect(onNavigate).toHaveBeenCalledWith("g0");
  });

  it("lists consumer chips (deduped) under a 'used by' label and navigates on click; an input with no edges makes NO claim", () => {
    const onNavigate = vi.fn();
    show("g0", { onNavigate });
    // topic feeds research + summary-report — one chip each, labeled with the
    // relationship word, no "unused" text anywhere.
    expect(screen.getByText("used by")).toBeTruthy();
    const research = screen.getByText("research");
    expect(screen.getByText("summary-report")).toBeTruthy();
    research.closest("button")!.click();
    // Navigate-without-opening (2026-06-12): no selectedId argument — the
    // IoPanel stays open; the chip centers + lights its node.
    expect(onNavigate).toHaveBeenCalledWith("n4");
    // limit has zero data-flow edges (e.g. read only in a loop condition — the
    // scan can't see it): no chips row, and no affirmative "unused" claim.
    expect(screen.queryByText(/unused/)).toBeNull();
    expect(document.querySelectorAll(".io-port")[1]!.querySelector(".io-port-uses")).toBeNull();
  });

  it("a markdown-authored description renders as ELEMENTS — no literal markers", () => {
    const g: RFGraph = {
      ...graph,
      nodes: graph.nodes.map((n) => (n.id === "n1" ? { ...n, purpose: "finds **tensions** in `code`" } : n)),
    };
    render(
      <IoPanel
        group={g.groups[0]!}
        graph={g}
        workflowName="lyrics-generator"
        workflow="lyrics-generator"
        runId={null}
        hasRunContext={false}
        completedRunId={null}
        renderedIds={new Set(g.nodes.map((n) => n.id))}
        markedPortId={null}
        onNavigate={noop}
        onClose={noop}
      />,
    );
    expect(screen.getByText("tensions").tagName).toBe("STRONG");
    expect(document.body.textContent).not.toContain("**");
  });

  it("a consumer hidden inside a collapsed container renders a disabled chip", () => {
    show("g0", { rendered: ["g0", "n5"] }); // n4 not rendered
    const research = screen.getByText("research").closest("button")!;
    expect(research.hasAttribute("disabled")).toBe(true);
  });

  it("marks the focused row's entry", () => {
    show("g0", { markedPortId: "n2" });
    const entries = document.querySelectorAll(".io-port");
    expect(entries[0]!.className).not.toContain("marked");
    expect(entries[1]!.className).toContain("marked");
  });
});

describe("IoPanel — outputs", () => {
  it("shows the producer under a 'from' label with the dot-prefixed field it reads, the description, and the source line", () => {
    show("g1");
    expect(screen.getByText("workflow outputs")).toBeTruthy();
    expect(screen.getByText("1 output")).toBeTruthy();
    expect(screen.getByText("report")).toBeTruthy();
    expect(screen.getByText("Concise summary of the run.")).toBeTruthy();
    expect(screen.getByText("from")).toBeTruthy(); // the relationship word
    expect(screen.getByText("summary-report")).toBeTruthy(); // the producer chip
    expect(screen.getByText(".result.summary")).toBeTruthy(); // reads as "from summary-report.result.summary"
    expect(screen.getByText("lyrics-generator.pflow.md:12")).toBeTruthy();
  });

  it("an undeclared output's type DERIVES from the producer's shape — never the 'any' filler", () => {
    show("g1");
    // report authors no `type:`; the edge reads result.summary and the producer's
    // authored shape says that key is `str` (the same resolution order the canvas
    // rows use — producedTypeOf).
    expect(screen.getByText("str")).toBeTruthy();
    expect(screen.queryByText("any")).toBeNull();
  });
});

// Task 175 — each port's value for the in-context run, projected by /api/run-node (server-side).
function detailFor(ref: RFRef): RunNodeDetail {
  const isInput = ref.port === "in";
  return {
    node_type: isInput ? "input" : "output",
    status: "recorded",
    duration_ms: null,
    cost_usd: null,
    tokens: null,
    error: null,
    input: isInput ? { [ref.node_id]: ref.node_id === "topic" ? "AI ethics" : 7 } : {},
    output: isInput ? null : "Final report text",
  };
}

describe("IoPanel — this run", () => {
  afterEach(() => mockFetch.mockReset());

  it("does NOT fetch a run value, and shows no 'this run' block, when no run is in context", () => {
    show("g0", { hasRunContext: false });
    expect(mockFetch).not.toHaveBeenCalled();
    expect(screen.queryByText("this run")).toBeNull();
  });

  it("shows each input port's run value under a 'this run' label when a run is in context", async () => {
    mockFetch.mockImplementation((_wf, _run, ref) => Promise.resolve(detailFor(ref)));
    show("g0", { hasRunContext: true });
    expect(await screen.findByText("AI ethics")).toBeTruthy();
    expect(await screen.findByText("7")).toBeTruthy(); // the run value (7), distinct from the default (5)
    expect(screen.getAllByText("this run")).toHaveLength(2); // one per input port
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("renders an output port's run value", async () => {
    mockFetch.mockImplementation((_wf, _run, ref) => Promise.resolve(detailFor(ref)));
    show("g1", { hasRunContext: true });
    expect(await screen.findByText("Final report text")).toBeTruthy();
  });

  it("shows 'no recorded value' when a port has none for this run (404 / absent / text-mode output)", async () => {
    mockFetch.mockRejectedValue(new Error("404"));
    show("g1", { hasRunContext: true });
    expect(await screen.findByText("no recorded value")).toBeTruthy();
  });

  it("refetches an output port when the run completes (completedRunId change) — a value fetched mid-run appears", async () => {
    // Output ports 404 until run.complete writes json_output, so an open panel first lands on absent…
    mockFetch.mockRejectedValueOnce(new Error("404"));
    const g = graph.groups.find((x) => x.id === "g1")!;
    const io = (completedRunId: string | null): JSX.Element => (
      <IoPanel
        group={g}
        graph={graph}
        workflowName="w"
        workflow="w"
        runId="r1"
        hasRunContext={true}
        completedRunId={completedRunId}
        renderedIds={new Set(graph.nodes.map((n) => n.id))}
        markedPortId={null}
        onNavigate={noop}
        onClose={noop}
      />
    );
    const { rerender } = render(io(null));
    expect(await screen.findByText("no recorded value")).toBeTruthy();
    // …then run.complete arrives → completedRunId changes → the effect refetches, now with the value present.
    mockFetch.mockImplementation((_wf, _run, ref) => Promise.resolve(detailFor(ref)));
    rerender(io("r1"));
    expect(await screen.findByText("Final report text")).toBeTruthy();
  });

  it("does NOT refetch INPUT ports on completion (inputs are t=0-stable — no flash/refetch)", async () => {
    mockFetch.mockImplementation((_wf, _run, ref) => Promise.resolve(detailFor(ref)));
    const g = graph.groups.find((x) => x.id === "g0")!; // two input ports
    const io = (completedRunId: string | null): JSX.Element => (
      <IoPanel
        group={g}
        graph={graph}
        workflowName="w"
        workflow="w"
        runId="r1"
        hasRunContext={true}
        completedRunId={completedRunId}
        renderedIds={new Set(graph.nodes.map((n) => n.id))}
        markedPortId={null}
        onNavigate={noop}
        onClose={noop}
      />
    );
    const { rerender } = render(io(null));
    await screen.findByText("AI ethics"); // both inputs fetched once
    expect(mockFetch).toHaveBeenCalledTimes(2);
    rerender(io("r1")); // run.complete → inputs are gated OUT of the completion epoch → no refetch
    await Promise.resolve();
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });
});
