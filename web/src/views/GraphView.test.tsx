// @vitest-environment jsdom
//
// Mount smoke for the full pipeline: fetch (mocked) -> useWorkflowGraph (build +
// layout + focus) -> React Flow render, in jsdom. Proves the component pipeline
// mounts and surfaces a real graph / a real error without throwing — the runtime
// gap that tsc + the production build can't cover. ELK is stubbed here for
// determinism; real ELK layout is covered in graph/flow.test.ts.

import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { installReactFlowJsdomMocks } from "../test/rf-jsdom";
import type { FlowNode } from "../graph/flow";
import type { RFGraph } from "../types";

// Mock only the network seam; keep the REAL ApiError so the api.ts -> GraphView
// error contract (not a fabricated shape) is what the banner test exercises.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, fetchGraph: vi.fn(), fetchCatalog: vi.fn(), fetchSource: vi.fn(), fetchRuns: vi.fn() };
});
const live = vi.hoisted(() => ({
  handlers: null as import("../api/events").PointHandlers | null,
  report: vi.fn(),
}));
vi.mock("../api/events", () => ({
  subscribe: vi.fn((_workflow: string, handlers: import("../api/events").PointHandlers) => {
    live.handlers = handlers;
    return vi.fn();
  }),
  reportInteraction: live.report,
}));
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

import { ApiError, fetchGraph, fetchRuns, fetchSource } from "../api/client";
import type { RunHandlers } from "../api/events";
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
    cached_prefix: null,
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
    cached_prefix: null,
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
  // Pin the SNAP path (force prefers-reduced-motion ON) so the paint-deferred camera
  // follow is DETERMINISTIC. The animated path bumps paintEpoch only when its rAF
  // glide lands; that's fine at ~100ms locally but races the `waitFor` under CI load,
  // so the follow intermittently never fires. Animation is not the subject of these
  // mount/integration tests — same lever useWorkflowGraph.test.tsx's setReducedMotion uses.
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
  vi.mocked(fetchGraph).mockReset();
  vi.mocked(fetchRuns).mockReset();
  vi.mocked(fetchSource).mockReset();
  vi.mocked(fetchSource).mockResolvedValue({
    root: "/wf.pflow.md",
    files: { "/wf.pflow.md": "# Demo\n\n### greet\n\nsay hi\n" },
  });
  vi.mocked(layoutGraph).mockReset();
  vi.mocked(layoutGraph).mockImplementation(layoutStub);
  fitViewSpy.mockClear();
  live.handlers = null;
  live.report.mockReset();
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

  it("re-picking the already-pinned run is a no-op — it must NOT wipe the overlay markers", async () => {
    // Regression (Task 173, RunSelector bug): selectRun cleared runStatus and relied on the SSE effect
    // (deps include runId) to repopulate from the new run's snapshot. But re-picking the SAME run leaves
    // runId UNCHANGED, so the effect never re-fires — the markers were wiped with nothing to refill them.
    // The guard makes re-selecting the current run a no-op. Faithful repro: start pinned to r1, light a
    // node, re-pick r1 from the menu, assert the marker survives.
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    vi.mocked(fetchRuns).mockResolvedValue([
      {
        run_id: "r1",
        workflow_name: "demo",
        workflow_path: "/wf.pflow.md",
        start_time: "2026-06-24T20:00:00Z",
        complete: true,
        final_status: "success",
        live: false,
        only_node: null,
        trace_file: "/t/r1.json",
      },
    ]);
    window.history.replaceState({}, "", "/?workflow=demo&run=r1"); // runId reads ?run= once at mount
    try {
      render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
      await waitFor(() => expect(live.handlers).not.toBeNull());

      // The pinned run's snapshot lights `greet` success — the overlay marker we must not lose.
      const run = live.handlers as unknown as RunHandlers;
      act(() => run.runEvents([{ id: 1, ref: { node_id: "greet", ancestor_path: [], port: null }, status: "success" }]));
      await waitFor(() => expect(screen.getByLabelText("run status: success")).toBeTruthy());

      // Re-pick r1 (already the pinned run): open the Runs menu and click it again.
      fireEvent.click(screen.getByLabelText("Runs"));
      fireEvent.click(await screen.findByTitle("r1"));

      // The marker SURVIVES the re-select (the bug wiped it; with no re-subscribe nothing refilled it).
      expect(screen.getByLabelText("run status: success")).toBeTruthy();
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("source toggle mounts the source pane, and node selection marks that node's authored line", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    window.history.replaceState({}, "", "/");
    try {
      const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
      expect(container.querySelector(".source-pane")).toBeNull();

      fireEvent.click(screen.getByRole("button", { name: "Show source" }));
      await waitFor(() => expect(container.querySelector(".source-pane")).toBeTruthy());

      const canvasNode = screen.getAllByText("say hi").find((el) => el.className.includes("node-name"));
      expect(canvasNode).toBeTruthy();
      fireEvent.click(canvasNode!);
      await waitFor(() => expect(container.querySelector('.src-line-active[data-line="3"]')).toBeTruthy());
      expect(container.querySelector(".source-code")?.getAttribute("aria-label")).toBe("/wf.pflow.md");
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("the source pane's clamp RESERVES the other pane's width — both panes + a usable canvas fit the viewport", async () => {
    // The clamp-reservation wiring (the kind-prop lesson): clampPanelWidth is
    // unit-pinned in panelWidth.test.ts, but a GraphView call site passing
    // reserved=0 survived the suite. Pin the invariant the reservation exists
    // for: sourceW + panelW + CANVAS_MIN_W (320) <= viewport.
    // Viewport 1000 is LOAD-BEARING: at 1200 with the 460 defaults a reserved=0
    // mutant converges to (panel 420, source 460) — 420+460+320 = exactly 1200,
    // coincidentally within budget because the OTHER pane's correct clamp
    // absorbs the violation. At 1000 the same mutant lands a 300/460 split
    // (760 > 1000-320 = 680) — observably broken; correct code converges to
    // 300/300 (600 <= 680).
    const originalInnerWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { value: 1000, writable: true, configurable: true });
    // Clear persisted widths so the 460 defaults apply deterministically
    // (earlier tests' savePanelWidth effects write to the same jsdom storage).
    window.localStorage.removeItem("pflow-ui:panel-w");
    window.localStorage.removeItem("pflow-ui:source-w");
    window.history.replaceState({}, "", "/?source=1");
    try {
      vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
      const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(container.querySelector(".source-pane")).toBeTruthy());

      const graphBody = container.querySelector(".graph-body") as HTMLElement;
      const px = (name: string): number => Number.parseFloat(graphBody.style.getPropertyValue(name));
      await waitFor(() => {
        const sourceW = px("--source-w");
        const panelW = px("--panel-w");
        // The hard floors hold (PANEL_MIN_W)…
        expect(sourceW).toBeGreaterThanOrEqual(300);
        expect(panelW).toBeGreaterThanOrEqual(300);
        // …and the mutual reservation leaves a usable canvas (CANVAS_MIN_W).
        expect(sourceW + panelW).toBeLessThanOrEqual(1000 - 320);
      });
    } finally {
      Object.defineProperty(window, "innerWidth", { value: originalInnerWidth, writable: true, configurable: true });
      window.localStorage.removeItem("pflow-ui:panel-w");
      window.localStorage.removeItem("pflow-ui:source-w");
      window.history.replaceState({}, "", "/");
    }
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

  it("read panel shows the cached prefix template before the prompt (request order)", async () => {
    // RFNode.cached_prefix is the ## Cache block's authored template assembled
    // per consumer (prose + ${var}, prefix order) — the panel shows the prompt
    // as the model will receive it: cached prefix block, THEN prompt.
    const cached: RFGraph = {
      ...GRAPH,
      nodes: [
        { ...GRAPH.nodes[0]! },
        {
          ...GRAPH.nodes[1]!,
          kind: "llm",
          purpose: "summarize it",
          cached_prefix: "Context:\n${greet.stdout}",
          params: [
            { name: "model", value: "anthropic/x", is_dynamic: false, source: null },
            { name: "prompt", value: "Summarize.", is_dynamic: false, source: null },
          ],
        },
      ],
      edges: [
        { ...GRAPH.edges[0]! },
        { ...GRAPH.edges[0]!, id: "ec", kind: "data_flow", output_field: "stdout", input_name: "prompt_cache" },
      ],
    };
    vi.mocked(fetchGraph).mockResolvedValue(cached);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("summarize it")).toBeTruthy());

    fireEvent.click(screen.getByText("summarize it")); // select the consumer
    await waitFor(() => expect(screen.getAllByText("cached prefix").length).toBeGreaterThan(0));
    expect(screen.getByText(/Context:/)).toBeTruthy(); // the assembled template text
    // Panel block order = request order: model, cached prefix, prompt.
    const names = [...document.querySelectorAll(".read-param-name")].map((el) => el.textContent);
    expect(names).toEqual(["model", "cached prefix", "prompt"]);
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

  it("the error branch's toolbar omits the source toggle; a normal render has it", async () => {
    // The error arm renders toolbar(false) — there is no canvas/graph-body to
    // put a source pane beside, so the toggle is gated off. Pin BOTH sides so
    // the assertion can fail in either direction (toggle leaking into the error
    // toolbar, or dying everywhere).
    vi.mocked(fetchGraph).mockRejectedValue(new ApiError(422, [{ message: "unknown node type 'frob'" }]));
    render(<GraphView workflow="broken" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText(/unknown node type 'frob'/)).toBeTruthy());
    // The toolbar itself rendered (density control present) — only the source
    // toggle is absent, not the whole header.
    expect(screen.getByText("advanced")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show source" })).toBeNull();

    // A normal render HAS it — the absence above is the error-branch gate.
    cleanup();
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Show source" })).toBeTruthy();
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

  it("io-port chip camera follow: navigating fitViews the port's OWNER card", async () => {
    // The lyrics-generator bug (2026-06-12): a ReadPanel reference chip naming
    // a sub-workflow's port (`sub.x`) focused an id that is never a rendered
    // node (io members render as ROWS on their owner), so the camera follow
    // silently skipped — and in beautiful the expansion re-layout had no anchor
    // either, so the canvas jumped away ("zoom to nowhere"). The follow must
    // resolve the port to its OWNER card.
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
        { ...GRAPH.nodes[0]!, id: "r0", ref: { node_id: "feeder", ancestor_path: [], port: null }, purpose: "feeds the sub", params: [] },
      ],
      edges: [{ id: "e_b", source: "r0", target: "p1", kind: "data_flow", label: null, output_field: "stdout", input_name: "x", shadowed: false, condition: null, output_path: [] }],
      groups: [
        { id: "g_wf", kind: "workflow", parent: null, host: "h0", members: ["m0"], nesting_depth: 0, annotations: {} },
        { id: "g_wf_in", kind: "input_wrapper", parent: "g_wf", host: null, members: ["p1"], nesting_depth: 1, annotations: {} },
      ],
    };
    vi.mocked(fetchGraph).mockResolvedValue(nested);
    const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("feeds the sub")).toBeTruthy());

    // Select the feeder: its ReadPanel's `referenced by` stack carries the
    // scope-prefixed port chip (`sub.x`).
    fireEvent.click(screen.getByText("feeds the sub"));
    await waitFor(() => expect(container.querySelector(".chip-stack .edge-chip")).toBeTruthy());

    fitViewSpy.mockClear();
    fireEvent.click(container.querySelector(".chip-stack .edge-chip")!);
    await waitFor(() => expect(fitViewSpy).toHaveBeenCalled());
    const followed = fitViewSpy.mock.calls.some(
      (c) => (c[0] as { nodes?: { id: string }[] } | undefined)?.nodes?.[0]?.id === "g_wf",
    );
    expect(followed).toBe(true);
  });

  it("applies live node focus/clear and camera-only frame without reporting agent actions", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(live.handlers).not.toBeNull());
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
    const reportsAfterOpen = live.report.mock.calls.length;

    act(() => live.handlers!.focus({ kind: "node", ref: GRAPH.nodes[0]!.ref }));
    await waitFor(() => expect(container.querySelector(".read-panel")).toBeTruthy());
    expect(live.report).toHaveBeenCalledTimes(reportsAfterOpen);

    act(() => live.handlers!.clear());
    await waitFor(() => expect(container.querySelector(".read-panel")).toBeNull());

    fitViewSpy.mockClear();
    act(() => live.handlers!.frame({ kind: "node", ref: GRAPH.nodes[1]!.ref }));
    await waitFor(() =>
      expect(
        fitViewSpy.mock.calls.some(
          (call) => (call[0] as { nodes?: { id: string }[] } | undefined)?.nodes?.[0]?.id === "n1",
        ),
      ).toBe(true),
    );
    expect(container.querySelector(".read-panel")).toBeNull();
    expect(live.report).toHaveBeenCalledTimes(reportsAfterOpen);
  });

  it("reports deliberate user clicks with structural and flat identity", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());

    fireEvent.click(screen.getByText("say hi"));

    await waitFor(() =>
      expect(live.report).toHaveBeenCalledWith(
        "demo",
        expect.objectContaining({
          type: "node_click",
          target: { kind: "node", flat_id: "n0", ref: GRAPH.nodes[0]!.ref },
          view_state: expect.objectContaining({ focus: "greet" }),
        }),
      ),
    );
  });

  it("resolves and selects a live data-edge descriptor by structural endpoints", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(live.handlers).not.toBeNull());

    const target = {
      kind: "edge" as const,
      source: GRAPH.nodes[0]!.ref,
      source_field: "stdout",
      source_path: [],
      target: GRAPH.nodes[1]!.ref,
      input_name: "command",
    };
    act(() => live.handlers!.focus(target));

    await waitFor(() => expect(container.querySelector(".read-panel")).toBeTruthy());
    expect(screen.getByText("greet")).toBeTruthy();

    // Re-pointing after the user pans must frame immediately: same focus
    // produces no paint epoch for a deferred camera request to wait on.
    fitViewSpy.mockClear();
    act(() => live.handlers!.focus(target));
    await waitFor(() => expect(fitViewSpy).toHaveBeenCalled());
  });

  it("reveals both collapsed endpoint chains before applying a live edge focus", async () => {
    const sourceRef = { node_id: "produce", ancestor_path: [{ node_id: "left", batch_index: null }], port: null } as const;
    const targetRef = { node_id: "consume", ancestor_path: [{ node_id: "right", batch_index: null }], port: null } as const;
    const nested: RFGraph = {
      nodes: [
        { ...GRAPH.nodes[0]!, id: "h0", ref: { node_id: "left", ancestor_path: [], port: null }, kind: "workflow", is_group_host: true, params: [] },
        { ...GRAPH.nodes[0]!, id: "a", ref: { ...sourceRef, ancestor_path: [...sourceRef.ancestor_path] }, purpose: "hidden producer", parent: "ga", params: [] },
        { ...GRAPH.nodes[0]!, id: "h1", ref: { node_id: "right", ancestor_path: [], port: null }, kind: "workflow", is_group_host: true, params: [] },
        { ...GRAPH.nodes[1]!, id: "b", ref: { ...targetRef, ancestor_path: [...targetRef.ancestor_path] }, purpose: "hidden consumer", parent: "gb", params: [] },
      ],
      edges: [
        {
          id: "e_nested",
          source: "a",
          target: "b",
          kind: "data_flow",
          label: null,
          output_field: "stdout",
          input_name: "command",
          shadowed: false,
          condition: null,
          output_path: [],
        },
      ],
      groups: [
        { id: "ga", kind: "workflow", parent: null, host: "h0", members: ["a"], nesting_depth: 0, annotations: {} },
        { id: "gb", kind: "workflow", parent: null, host: "h1", members: ["b"], nesting_depth: 0, annotations: {} },
      ],
    };
    vi.mocked(fetchGraph).mockResolvedValue(nested);
    window.history.replaceState({}, "", "/?collapse=all&density=beautiful");
    try {
      const { container } = render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(live.handlers).not.toBeNull());
      await waitFor(() => expect(screen.queryByText("hidden producer")).toBeNull());

      act(() =>
        live.handlers!.focus({
          kind: "edge",
          source: { ...sourceRef, ancestor_path: [...sourceRef.ancestor_path] },
          source_field: "stdout",
          source_path: [],
          target: { ...targetRef, ancestor_path: [...targetRef.ancestor_path] },
          input_name: "command",
        }),
      );

      await waitFor(() => expect(screen.getByText("hidden producer")).toBeTruthy());
      expect(screen.getByText("hidden consumer")).toBeTruthy();
      expect(container.querySelector(".read-panel")).toBeTruthy();
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
