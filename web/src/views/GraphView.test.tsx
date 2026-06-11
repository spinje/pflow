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
// Partial-mock @xyflow/react ONLY to OBSERVE fitView calls (the camera-follow
// pin): the spy wraps the real instance's fitView and calls through, so every
// other test sees unchanged behavior.
const fitViewSpy = vi.hoisted(() => vi.fn());
vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  return {
    ...actual,
    // jsdom's no-op ResizeObserver means React Flow never "measures" nodes, so
    // the real hook would stay false forever and the effects it gates (fit,
    // focus deep link) would be unreachable in any jsdom test.
    useNodesInitialized: () => true,
    useReactFlow: (): ReturnType<typeof actual.useReactFlow> => {
      const inst = actual.useReactFlow();
      return {
        ...inst,
        fitView: (opts?: Parameters<typeof inst.fitView>[0]) => {
          fitViewSpy(opts);
          return inst.fitView(opts);
        },
      };
    },
  };
});

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
    output_shape: null,
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
    output_shape: null,
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
      output_path: [],
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
  fitViewSpy.mockClear();
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

  it("read panel shows the full consumed paths for the clicked producer", async () => {
    // The panel is the untruncated home of observed reads (D7: canvas rows land
    // one level): clicking a producer lists `output_field[.path…]` full-depth.
    const deepRead: RFGraph = {
      ...GRAPH,
      edges: [
        { ...GRAPH.edges[0]! },
        { ...GRAPH.edges[0]!, id: "e1", output_field: "result", output_path: ["a", "b"], input_name: null },
      ],
    };
    vi.mocked(fetchGraph).mockResolvedValue(deepRead);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());

    fireEvent.click(screen.getByText("say hi")); // select the producer (greet)
    await waitFor(() => expect(screen.getByText("consumed")).toBeTruthy());
    expect(screen.getByText("stdout, result.a.b")).toBeTruthy();
  });

  it("the panel's consumed list includes plain-param (prompt-body) reads — panel/canvas parity", async () => {
    // `prompt: ${greet.stdout}` forms NO contract edge; the canvas already counts
    // it (scanParamReads) — the panel must too, or the two state contradictory
    // facts about the same binding (review-caught 2026-06-11). `stdout` has an
    // edge read here (so the gate admits it); the second ref is prompt-only.
    const promptRead: RFGraph = {
      ...GRAPH,
      nodes: [
        { ...GRAPH.nodes[0]!, output_shape: { field: "result", data_type: "dict", keys: [{ name: "ok", data_type: "bool" }] } },
        {
          ...GRAPH.nodes[1]!,
          params: [{ name: "prompt", value: "Check ${greet.result.ok}", is_dynamic: true, source: null }],
        },
      ],
    };
    vi.mocked(fetchGraph).mockResolvedValue(promptRead);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());

    fireEvent.click(screen.getByText("say hi")); // select the producer (greet)
    await waitFor(() => expect(screen.getByText("consumed")).toBeTruthy());
    // The edge read (stdout) AND the prompt-only read (result.ok) both list.
    expect(screen.getByText("stdout, result.ok")).toBeTruthy();
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

  it("an unexpanded leaf renders its badge — the ONE badge a leaf can carry", async () => {
    // Pins the Badges.tsx → inline-badge consolidation (review cleanup
    // 2026-06-11): no test rendered the leaf badge before, so the "no visual
    // change" claim rested on markup inspection alone.
    const unexp: RFGraph = {
      ...GRAPH,
      nodes: [GRAPH.nodes[0]!, { ...GRAPH.nodes[1]!, kind: "workflow", unexpanded: "depth_limit" }],
      edges: [],
    };
    vi.mocked(fetchGraph).mockResolvedValue(unexp);
    const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
    const badge = container.querySelector(".badge-unexpanded");
    expect(badge?.textContent).toBe("depth limit"); // underscores read as spaces
    expect(badge?.getAttribute("title")).toBe("not expanded: depth_limit");
  });

  it("chip-click camera follow: navigating from the EdgePanel fitViews the resolved node", async () => {
    // The user-caught regression (2026-06-11): an EdgePanel chip naming an
    // off-screen card selected it invisibly — `onNavigate` must bring the
    // target into view. Loaded via the `focus=<flat edge id>` deep link (the
    // GraphView edge arm, previously untested) because jsdom renders no edge
    // DOM to click. Padding/zoom/duration are tunable — only the target id is
    // pinned.
    window.history.replaceState({}, "", "/?focus=e0");
    try {
      vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
      render(<GraphView workflow="demo" onBack={() => {}} />);
      // The deep link selects the edge once nodes are measured: EdgePanel opens
      // with its endpoint chips ("greet" appears only as a chip name — the
      // canvas card shows the purpose, "say hi").
      await waitFor(() => expect(screen.getByText("greet")).toBeTruthy());

      fitViewSpy.mockClear();
      fireEvent.click(screen.getByText("greet")); // the source endpoint chip
      await waitFor(() => expect(fitViewSpy).toHaveBeenCalled());
      const followed = fitViewSpy.mock.calls.some(
        (c) => (c[0] as { nodes?: { id: string }[] } | undefined)?.nodes?.[0]?.id === "n0",
      );
      expect(followed).toBe(true);
    } finally {
      window.history.replaceState({}, "", "/");
    }
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
