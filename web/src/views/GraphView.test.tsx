// @vitest-environment jsdom
//
// Mount smoke for the full pipeline: fetch (mocked) -> useWorkflowGraph (build +
// layout + focus) -> React Flow render, in jsdom. Proves the component pipeline
// mounts and surfaces a real graph / a real error without throwing — the runtime
// gap that tsc + the production build can't cover. ELK is stubbed here for
// determinism; real ELK layout is covered in graph/flow.test.ts.

import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { installReactFlowJsdomMocks } from "../test/rf-jsdom";
import type { FlowNode } from "../graph/flow";
import type { RFGraph } from "../types";

// Mock only the network seam; keep the REAL ApiError so the api.ts -> GraphView
// error contract (not a fabricated shape) is what the banner test exercises.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, fetchGraph: vi.fn(), fetchCatalog: vi.fn() };
});
// Stub ELK so the component test is deterministic; overridable per-test.
vi.mock("../graph/layout", () => ({ layoutGraph: vi.fn() }));

import { ApiError, fetchGraph } from "../api/client";
import { layoutGraph } from "../graph/layout";
import { GraphView } from "./GraphView";

const layoutStub = async (nodes: FlowNode[]): Promise<FlowNode[]> =>
  nodes.map((n) => ({ ...n, position: { x: 0, y: 0 } }) as FlowNode);

const GRAPH: RFGraph = {
  nodes: [
    {
      id: "n0",
      ref: { node_id: "greet", ancestor_path: [], port: null },
      kind: "shell",
      purpose: "say hi",
      params: [{ name: "command", value: "echo hi", is_dynamic: false, source: null }],
      io: null,
      loop: null,
      batch: null,
      parent: null,
      source: { file: "/wf.pflow.md", line: 3 },
      is_decision: false,
      is_terminal: false,
      is_group_host: false,
    is_transform: false,
      unexpanded: null,
      annotations: {},
    },
    {
      id: "n1",
      ref: { node_id: "done", ancestor_path: [], port: null },
      kind: "shell",
      purpose: "",
      params: [{ name: "command", value: "${greet.stdout}", is_dynamic: true, source: null }],
      io: null,
      loop: null,
      batch: null,
      parent: null,
      source: null,
      is_decision: false,
      is_terminal: true,
      is_group_host: false,
    is_transform: false,
      unexpanded: null,
      annotations: {},
    },
  ],
  edges: [
    {
      id: "e0",
      source: "n0",
      target: "n1",
      kind: "data_flow",
      label: null,
      output_field: "stdout",
      input_name: "command",
      shadowed: false,
      condition: null,
    },
  ],
  groups: [],
};

beforeAll(() => installReactFlowJsdomMocks());
beforeEach(() => {
  cleanup();
  vi.mocked(fetchGraph).mockReset();
  vi.mocked(layoutGraph).mockReset();
  vi.mocked(layoutGraph).mockImplementation(layoutStub);
});

describe("GraphView mount", () => {
  it("mounts the full pipeline and renders nodes; advanced reveals the ${ref} chip", async () => {
    // What jsdom CAN verify: the fetch→build→layout→render pipeline mounts and the
    // node components draw. (jsdom renders no edge DOM, so edge/handle integrity is
    // NOT testable here — it's covered by the handle-type invariant in flow.test.ts.)
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    render(<GraphView workflow="demo" onBack={() => {}} />);

    // Toolbar title is available before the graph resolves.
    expect(screen.getByText("demo")).toBeTruthy();

    // Both densities show the description: n0's purpose ("say hi"), and n1 falls back
    // to its node_id ("done") since it has no purpose.
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
    expect(screen.getByText("done")).toBeTruthy();

    // Advanced adds the body: the dynamic param's ${ref} connection chip.
    fireEvent.click(screen.getByText("advanced"));
    await waitFor(() => expect(screen.getByText("greet.stdout")).toBeTruthy());
  });

  it("shows a structured banner on a real ApiError, not a blank canvas", async () => {
    // Reject with the REAL ApiError so this pins the api.ts -> GraphView contract.
    vi.mocked(fetchGraph).mockRejectedValue(new ApiError(422, [{ message: "unknown node type 'frob'" }]));
    render(<GraphView workflow="broken" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText(/unknown node type 'frob'/)).toBeTruthy());
  });

  it("container clicks: body SELECTS (read panel, no toggle); the corner button TOGGLES (design D)", async () => {
    const mkNode = (over: Partial<RFGraph["nodes"][number]>): RFGraph["nodes"][number] =>
      ({ ...GRAPH.nodes[0]!, ref: { node_id: over.id ?? "x", ancestor_path: [], port: null }, ...over }) as RFGraph["nodes"][number];
    const grouped: RFGraph = {
      nodes: [
        mkNode({ id: "h0", kind: "workflow", purpose: "run the core", is_group_host: true, params: [] }),
        mkNode({ id: "m0", purpose: "inner step", parent: "g0", params: [] }),
      ],
      edges: [],
      groups: [{ id: "g0", kind: "workflow", parent: null, host: "h0", members: ["m0"], nesting_depth: 0, annotations: {} }],
    };
    vi.mocked(fetchGraph).mockResolvedValue(grouped);
    const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("inner step")).toBeTruthy());

    // The corner button TOGGLES: the member disappears (collapse re-runs the build)
    // and selecting did NOT happen (no read panel).
    const toggle = container.querySelector(".group-toggle");
    expect(toggle).toBeTruthy();
    fireEvent.click(toggle!);
    await waitFor(() => expect(screen.queryByText("inner step")).toBeNull());
    expect(container.querySelector(".read-panel")).toBeNull();

    // The card BODY selects: read panel opens on the HOST node, container stays collapsed.
    fireEvent.click(screen.getByText("run the core"));
    await waitFor(() => expect(container.querySelector(".read-panel")).toBeTruthy());
    expect(screen.getByRole("heading", { name: "h0" })).toBeTruthy();
    expect(screen.queryByText("inner step")).toBeNull(); // still collapsed — select didn't open it

    // The button expands it back.
    fireEvent.click(container.querySelector(".group-toggle")!);
    await waitFor(() => expect(screen.getByText("inner step")).toBeTruthy());
  });

  it("surfaces a layout failure as an error banner, not a permanent 'Laying out…' (C1)", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    vi.mocked(layoutGraph).mockReset();
    vi.mocked(layoutGraph).mockRejectedValue(new Error("elk exploded"));

    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText(/could not lay out this workflow/i)).toBeTruthy());
    expect(screen.queryByText("Laying out…")).toBeNull();
    consoleError.mockRestore();
  });
});
