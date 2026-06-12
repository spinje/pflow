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
// Keep the read panel's ParamBlocks synchronous: the real shiki load under
// jsdom would land setState after assertions (act warnings + cross-test bleed
// through the memoized highlighter promise). null = legacy plain rendering.
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});
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
import { highlight } from "../utils/highlight";
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

    // Both densities show the description: n0's purpose ("say hi"). n1 has no
    // purpose, so its title line stays empty — identity lives on the NameLabel
    // chrome above the card (beautiful = humanized name, verbatim id on the
    // tooltip).
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
    const nameLabel = screen.getByText("Done");
    expect(nameLabel.className).toContain("node-name-label");
    expect(nameLabel.getAttribute("title")).toBe("done");

    // Advanced adds the body: the dynamic param's ${ref} connection chip.
    fireEvent.click(screen.getByText("advanced"));
    await waitFor(() => expect(screen.getByText("greet.stdout")).toBeTruthy());
  });

  it("a markdown purpose renders STRIPPED on the canvas card and RENDERED in the read panel", async () => {
    // The 2-line-clamped description can't render formatting, so markers are
    // hidden (stripMarkdown); the read panel one click away renders them.
    const md: RFGraph = {
      ...GRAPH,
      nodes: [{ ...GRAPH.nodes[0]!, purpose: "finds **tensions** in `code`" }, GRAPH.nodes[1]!],
    };
    vi.mocked(fetchGraph).mockResolvedValue(md);
    const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("finds tensions in code")).toBeTruthy());
    expect(container.textContent).not.toContain("**");

    fireEvent.click(screen.getByText("finds tensions in code")); // open the read panel
    await waitFor(() => expect(container.querySelector(".read-panel")).toBeTruthy());
    expect(screen.getByText("tensions").tagName).toBe("STRONG");
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
    // The ReadPanel kind→language wiring pin: the shell node's `command` param
    // must reach the highlight seam as bash (paramLanguage fed node.kind).
    expect(highlight).toHaveBeenCalledWith("echo hi", "bash");
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

  it("io card clicks: SELECT opens the interface panel (the toggle died, 2026-06-11); a row click marks its entry; ✕ closes", async () => {
    const ioGraph: RFGraph = {
      nodes: [
        {
          ...GRAPH.nodes[0]!,
          id: "p_in",
          ref: { node_id: "topic", ancestor_path: [], port: "in" },
          kind: "input",
          purpose: "What to research.",
          params: [],
          io: { data_type: "string", required: true, default: null },
          parent: "g_in",
          source: null,
        },
        GRAPH.nodes[0]!, // greet — the consumer
      ],
      edges: [
        {
          id: "e_in",
          source: "p_in",
          target: "n0",
          kind: "data_flow",
          label: null,
          output_field: null,
          input_name: "command",
          shadowed: false,
          condition: null,
          output_path: [],
        },
      ],
      groups: [{ id: "g_in", kind: "input_wrapper", parent: null, host: null, members: ["p_in"], nesting_depth: 0, annotations: {} }],
    };
    vi.mocked(fetchGraph).mockResolvedValue(ioGraph);
    // Pin the density: an earlier test's toolbar click leaks density=advanced
    // into the URL (syncUrl replaceState persists across tests in this file).
    window.history.replaceState({}, "", "/?density=beautiful");
    try {
      const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(screen.getByText("1 input")).toBeTruthy());
      // A SINGLE-port card's title line is that port's description (the leaf
      // description||identity convention — the section itself has none).
      expect(screen.getByText("What to research.")).toBeTruthy();

      // Click the card: panel opens AND (beautiful) the rows focus-expand.
      fireEvent.click(screen.getByText("INPUTS"));
      await waitFor(() => expect(screen.getByText("workflow inputs")).toBeTruthy());
      await waitFor(() => expect(container.querySelector(".io-row")).toBeTruthy());
      // Rows speak the leaf output-row grammar: `name: type` (one vocabulary).
      expect(container.querySelector(".io-row")!.textContent).toContain("topic: string");

      // A second click KEEPS it open — the old toggle-close is gone. (Two "INPUTS"
      // texts exist now: the card category + the expanded rows' column caption.)
      fireEvent.click(screen.getAllByText("INPUTS")[0]!);
      expect(screen.getByText("workflow inputs")).toBeTruthy();

      // A row click marks that port's panel entry (card = whole interface,
      // row = one port — same panel both ways).
      fireEvent.click(container.querySelector(".io-row")!);
      await waitFor(() => expect(container.querySelector(".io-port.marked")).toBeTruthy());

      // ✕ closes the panel like every other panel.
      fireEvent.click(screen.getByTitle("Close"));
      expect(screen.queryByText("workflow inputs")).toBeNull();
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("a NESTED group's IO row click focuses only — no panel auto-opens", async () => {
    const nested: RFGraph = {
      nodes: [
        { ...GRAPH.nodes[0]!, id: "h0", ref: { node_id: "sub", ancestor_path: [], port: null }, kind: "workflow", is_group_host: true, params: [] },
        { ...GRAPH.nodes[0]!, id: "m0", ref: { node_id: "inner", ancestor_path: [{ node_id: "sub", batch_index: null }], port: null }, purpose: "inner step", parent: "g_wf", params: [] },
        {
          ...GRAPH.nodes[0]!,
          id: "p1",
          ref: { node_id: "x", ancestor_path: [{ node_id: "sub", batch_index: null }], port: "in" },
          kind: "input",
          purpose: "",
          params: [],
          io: { data_type: null, required: true, default: null },
          parent: "g_wf_in",
          source: null,
        },
        // A root step binding the port — a NO-edge nested port is click-INERT
        // (the into-nowhere gate, 2026-06-12), so the focus-only assertion
        // needs a genuinely wired row.
        { ...GRAPH.nodes[0]!, id: "r0", ref: { node_id: "feeder", ancestor_path: [], port: null }, params: [] },
      ],
      edges: [{ id: "e_b", source: "r0", target: "p1", kind: "data_flow", label: null, output_field: "stdout", input_name: "x", shadowed: false, condition: null, output_path: [] }],
      groups: [
        { id: "g_wf", kind: "workflow", parent: null, host: "h0", members: ["m0"], nesting_depth: 0, annotations: {} },
        { id: "g_wf_in", kind: "input_wrapper", parent: "g_wf", host: null, members: ["p1"], nesting_depth: 1, annotations: {} },
      ],
    };
    vi.mocked(fetchGraph).mockResolvedValue(nested);
    const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
    // Advanced: the open region's sidebar rows render without any focus.
    fireEvent.click(screen.getByText("advanced"));
    await waitFor(() => expect(container.querySelector(".io-row")).toBeTruthy());

    fireEvent.click(container.querySelector(".io-row")!);
    // Focus landed on the port (the row highlights) but NO panel opened — a
    // nested row's owner panel is the host ReadPanel, a different gesture.
    await waitFor(() => expect(container.querySelector(".io-row.focused")).toBeTruthy());
    expect(container.querySelector(".read-panel")).toBeNull();

    // The into-nowhere gate (2026-06-12): a nested port with NO line in view
    // is click-INERT — focusing it would dim the whole canvas and reveal
    // nothing. Same fixture minus the binding edge.
    cleanup();
    vi.mocked(fetchGraph).mockResolvedValue({ ...nested, edges: [] });
    const inert = render(<GraphView workflow="demo" onBack={() => {}} />);
    fireEvent.click(screen.getByText("advanced"));
    await waitFor(() => expect(inert.container.querySelector(".io-row")).toBeTruthy());
    fireEvent.click(inert.container.querySelector(".io-row")!);
    expect(inert.container.querySelector(".io-row.focused")).toBeNull();
    expect(inert.container.querySelector(".node.dimmed")).toBeNull();
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
