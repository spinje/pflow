// @vitest-environment jsdom
//
// Mount smoke for the full pipeline: fetch (mocked) -> useWorkflowGraph (build +
// layout + focus) -> React Flow render, in jsdom. Proves the component pipeline
// mounts and surfaces a real graph / a real error without throwing — the runtime
// gap that tsc + the production build can't cover. ELK is stubbed here for
// determinism; real ELK layout is covered in graph/flow.test.ts.

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { installReactFlowJsdomMocks } from "../test/rf-jsdom";
import type { FlowNode } from "../graph/flow";
import type { RFGraph, RFNode } from "../types";

// Mock only the network seam; keep the REAL ApiError so the api.ts -> GraphView
// error contract (not a fabricated shape) is what the banner test exercises.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, fetchGraph: vi.fn(), fetchCatalog: vi.fn(), fetchSource: vi.fn(), fetchRuns: vi.fn(), fetchRunNode: vi.fn(), runWorkflow: vi.fn() };
});
const live = vi.hoisted(() => ({
  handlers: null as import("../api/events").PointHandlers | null,
  report: vi.fn(),
  narration: vi.fn(),
}));
vi.mock("../api/events", () => ({
  subscribe: vi.fn((_workflow: string, handlers: import("../api/events").PointHandlers) => {
    live.handlers = handlers;
    return vi.fn();
  }),
  reportInteraction: live.report,
  reportNarration: live.narration,
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
        // jsdom's no-op ResizeObserver also means React Flow never MEASURES a node, so
        // NodeCallout (which returns null until its anchor has a measured rect) could never
        // mount in these tests. Backfill nominal dimensions; positions come from the layout stub.
        getInternalNode: ((id: string) => {
          const node = inst.getInternalNode(id);
          if (!node || node.measured.width != null) return node;
          return { ...node, measured: { width: 220, height: 60 } };
        }) as ReturnType<typeof actual.useReactFlow>["getInternalNode"],
      };
    },
  };
});

import { ApiError, fetchGraph, fetchRunNode, fetchRuns, fetchSource, runWorkflow } from "../api/client";
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
  vi.mocked(runWorkflow).mockReset();
  vi.mocked(runWorkflow).mockResolvedValue("spawned-run-1"); // Task 175: returns the run id to pin
  vi.mocked(fetchRuns).mockReset();
  vi.mocked(fetchRuns).mockResolvedValue([]); // RunSelector polls this on mount (the live-clock signal)
  vi.mocked(fetchRunNode).mockReset();
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
        git_root: null,
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

      // Re-pick r1 (already the pinned run): open the Runs menu and click it again. (Filter to the
      // menuitem — the ?run= deep-link's run callout also carries title="r1" in its subtitle.)
      fireEvent.click(screen.getByLabelText("Runs"));
      const menuItem = (await screen.findAllByTitle("r1")).find((el) => el.getAttribute("role") === "menuitem");
      fireEvent.click(menuItem!);

      // The marker SURVIVES the re-select (the bug wiped it; with no re-subscribe nothing refilled it).
      expect(screen.getByLabelText("run status: success")).toBeTruthy();
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("a stale (different-version) pinned replay shows the version banner, and run-reset clears it (Task 173)", async () => {
    // The run-stale broadcast reaches the present subscriber (its snapshot predates the server-side latch),
    // and the snapshot's stale flag covers a late subscriber — both flip the same banner. It is non-blocking
    // (the run still renders); a run-reset (a newer run took over) clears it.
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    vi.mocked(fetchRuns).mockResolvedValue([]);
    window.history.replaceState({}, "", "/?workflow=demo&run=r1");
    try {
      render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
      await waitFor(() => expect(live.handlers).not.toBeNull());
      const run = live.handlers as unknown as RunHandlers;

      // Path 1 — the broadcast arm (present subscriber). Nodes still light: the run renders normally.
      act(() => run.runStale());
      act(() => run.runEvents([{ id: 1, ref: { node_id: "greet", ancestor_path: [], port: null }, status: "success" }]));
      await waitFor(() => expect(screen.getByText(/different version of this workflow/)).toBeTruthy());
      expect(screen.getByLabelText("run status: success")).toBeTruthy();

      // A newer run takes over → the version banner clears (reset path).
      act(() => run.runReset());
      expect(screen.queryByText(/different version of this workflow/)).toBeNull();

      // Path 2 — a late subscriber learns it from the snapshot's stale flag (no broadcast).
      act(() => run.runSnapshot([], null, false, true));
      await waitFor(() => expect(screen.getByText(/different version of this workflow/)).toBeTruthy());
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("a stale + COMPLETED replay marks a node with no recorded state 'unrecorded'; a still-live one does not", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH); // greet + done
    vi.mocked(fetchRuns).mockResolvedValue([]);
    window.history.replaceState({}, "", "/?workflow=demo&run=r1");
    try {
      render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
      await waitFor(() => expect(live.handlers).not.toBeNull());
      const run = live.handlers as unknown as RunHandlers;
      const greetSuccess = { id: 0, ref: { node_id: "greet", ancestor_path: [], port: null }, status: "success" as const };

      // STALE but still LIVE (run=null → no run-complete trailer → not completed): `done` must NOT be marked
      // yet — it could still run. Only the version banner shows.
      act(() => run.runSnapshot([greetSuccess], null, false, true));
      await waitFor(() => expect(screen.getByLabelText("run status: success")).toBeTruthy());
      expect(screen.queryByLabelText("run status: unrecorded")).toBeNull();

      // Now the run COMPLETES (run-complete trailer arrives) → markUnmatched gates on → `done`, with no
      // recorded state, gets the dashed "unrecorded" badge; `greet` keeps its real success.
      act(() => run.runComplete({ final_status: "success", nodes_executed: 1 }));
      await waitFor(() => expect(screen.getByLabelText("run status: unrecorded")).toBeTruthy());
      expect(screen.getByLabelText("run status: success")).toBeTruthy();
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("the 'This run' detail section opens ONLY for a node with a recorded COMPLETION (Task 173)", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    vi.mocked(fetchRuns).mockResolvedValue([]);
    vi.mocked(fetchRunNode).mockResolvedValue({
      node_type: "shell",
      status: "success",
      duration_ms: 5,
      cost_usd: null,
      tokens: null,
      error: null,
      input: { command: "echo hi" },
      output: { stdout: "hi" },
    });
    window.history.replaceState({}, "", "/");
    try {
      render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
      await waitFor(() => expect(live.handlers).not.toBeNull());
      const run = live.handlers as unknown as RunHandlers;
      const selectGreet = () =>
        fireEvent.click(screen.getAllByText("say hi").find((el) => el.className.includes("node-name"))!);

      // RUNNING → selecting the node opens its panel (Params), but NO run-detail section (the badge covers it).
      act(() => run.runEvents([{ id: 1, ref: { node_id: "greet", ancestor_path: [], port: null }, status: "running" }]));
      selectGreet();
      await waitFor(() => expect(screen.getByText("Params")).toBeTruthy());
      expect(screen.queryByText("Output")).toBeNull(); // the section's Output heading is unique to it

      // Now it COMPLETES → the gate opens live, the section mounts + fetches → its "status" header + Output appear.
      act(() => run.runEvents([{ id: 1, ref: { node_id: "greet", ancestor_path: [], port: null }, status: "success" }]));
      await waitFor(() => expect(screen.getByText("status")).toBeTruthy());
      expect(await screen.findByText("Output")).toBeTruthy();
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

// A workflow whose three inputs exercise the WHOLE submit contract end-to-end through
// RunPanel: `topic` (default → prefilled, sent), `name` (required, no default → blank →
// OMITTED, so the pre-flight gives a clean 400 rather than the run getting name=''), and
// `api_key` (SENSITIVE with a default → field stays BLANK despite the default, and is
// OMITTED so the spawned run re-resolves it from settings/env — the secrets boundary).
function input(id: string, name: string, io: NonNullable<RFNode["io"]>): RFNode {
  return {
    id,
    ref: { node_id: name, ancestor_path: [], port: "in" },
    kind: "input",
    purpose: `the ${name}`,
    params: [],
    io,
    loop: null,
    batch: null,
    parent: "g_in",
    source: null,
    is_decision: false,
    is_terminal: false,
    is_group_host: false,
    is_transform: false,
    output_shape: null,
    cached_prefix: null,
    unexpanded: null,
    annotations: {},
  };
}
const GRAPH_WITH_INPUT: RFGraph = {
  nodes: [
    input("in0", "topic", { data_type: "string", required: false, default: "cats", sensitive: false }),
    input("in1", "name", { data_type: "string", required: true, default: null, sensitive: false }),
    // A sensitive input WITH an authored default — the form must NOT prefill the default.
    input("in2", "api_key", { data_type: "string", required: true, default: "should-not-prefill", sensitive: true }),
    ...GRAPH.nodes,
  ],
  edges: GRAPH.edges,
  groups: [
    { id: "g_in", kind: "input_wrapper", parent: null, host: null, members: ["in0", "in1", "in2"], nesting_depth: 0, annotations: {} },
  ],
};

describe("GraphView — Run panel (Task 175)", () => {
  it("the ▶ rail button toggles the Run panel open and closed", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    vi.mocked(fetchRuns).mockResolvedValue([]);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());

    // The ▶ is its own rail control, distinct from the clock ("Runs").
    fireEvent.click(screen.getByLabelText("Run workflow"));
    expect(await screen.findByText(/takes no inputs/i)).toBeTruthy(); // panel mounted (no-input confirm)
    fireEvent.click(screen.getByLabelText("Run workflow"));
    expect(screen.queryByText(/takes no inputs/i)).toBeNull(); // panel closed
  });

  it("the Run panel REPLACES an open selection panel, restoring it on close (one right panel)", async () => {
    // Two no-shrink .read-panels + the source pane would exceed usePanelPair's
    // source-vs-one-right-panel budget and crush the canvas. The run panel shares the
    // one right slot (selectedId preserved underneath), so at most one ever renders.
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    vi.mocked(fetchRuns).mockResolvedValue([]);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());

    // Select a node → its ReadPanel opens (the node's name as the panel <h2>).
    fireEvent.click(screen.getByText("say hi"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "greet" })).toBeTruthy());

    // Open ▶ → the Run panel REPLACES the ReadPanel (selection panel gone).
    fireEvent.click(screen.getByLabelText("Run workflow"));
    expect(await screen.findByText(/takes no inputs/i)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "greet" })).toBeNull();

    // Close ▶ → the preserved selection's ReadPanel returns.
    fireEvent.click(screen.getByLabelText("Run workflow"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "greet" })).toBeTruthy());
    expect(screen.queryByText(/takes no inputs/i)).toBeNull();
  });

  it("submit spawns ONLY the filled+non-sensitive inputs (secrets blank, blanks omitted), then PINS the spawned run + closes", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH_WITH_INPUT);
    vi.mocked(fetchRuns).mockResolvedValue([]);
    // Start PINNED to a past run so the pin SWITCH (r1 → the spawned id) is observable (Task 175).
    window.history.replaceState({}, "", "/?workflow=demo&run=r1");
    try {
      render(<GraphView workflow="demo" onBack={() => {}} />);
      await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());

      fireEvent.click(screen.getByLabelText("Run workflow"));
      // `topic` prefills from its default; `api_key` stays BLANK despite having an
      // authored default — the form never collects a secret (the secrets boundary).
      const topic = (await screen.findByLabelText(/topic/i)) as HTMLInputElement;
      expect(topic.value).toBe("cats"); // its default shows, editable
      expect((screen.getByLabelText(/api_key/i) as HTMLInputElement).value).toBe("");
      expect((screen.getByLabelText(/^name/i) as HTMLInputElement).value).toBe(""); // required, no default → blank
      // Edit `topic` AWAY from its default so it's a genuine user-set value (an UNTOUCHED default is
      // omitted so the run resolves it via CLI precedence — Codex F2, unit-tested in RunPanel.test.tsx).
      fireEvent.change(topic, { target: { value: "dogs" } });

      fireEvent.click(screen.getByRole("button", { name: "▶ Run" }));

      // Faithful to a hand-typed run: only the edited `topic=dogs` rides; `name` (blank required) and
      // `api_key` (sensitive, blank) are OMITTED — NOT sent as empty strings. The pre-flight
      // 400s the missing required `name`; the spawned run re-resolves `api_key` by name.
      await waitFor(() => expect(runWorkflow).toHaveBeenCalledWith("demo", { topic: "dogs" }));
      // PINS the overlay to the run just spawned (?run=<the returned id>) — NOT follow-newest, so it
      // won't revert to an older still-live run when this one finishes. The panel closes.
      await waitFor(() => expect(new URLSearchParams(window.location.search).get("run")).toBe("spawned-run-1"));
      await waitFor(() => expect(screen.queryByRole("button", { name: "▶ Run" })).toBeNull());
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("launching CLEARS the previous completed run's state (no stale flash before the new run lights up)", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    vi.mocked(fetchRuns).mockResolvedValue([]);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
    await waitFor(() => expect(live.handlers).not.toBeNull());

    // A prior run completed while following-newest: a node lit + the run banner showed.
    const run = live.handlers as unknown as RunHandlers;
    act(() => run.runEvents([{ id: 1, ref: { node_id: "greet", ancestor_path: [], port: null }, status: "success" }]));
    act(() => run.runComplete({ final_status: "success", nodes_executed: 1 }));
    await waitFor(() => expect(screen.getByLabelText("run status: success")).toBeTruthy());
    expect(screen.getByText(/Run success/)).toBeTruthy();

    // Launch again. Pinning to the spawned id is a genuine selectRun SWITCH (null → the new id), which
    // tears down + clears the stale run state — so the callout never opens on the LAST run.
    fireEvent.click(screen.getByLabelText("Run workflow"));
    fireEvent.click(await screen.findByRole("button", { name: "▶ Run" }));
    await waitFor(() => expect(runWorkflow).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByLabelText("run status: success")).toBeNull()); // node status cleared
    expect(screen.queryByText(/Run success/)).toBeNull(); // run banner cleared
  });

  it("a spawn failure shows the diagnostics inline and never blanks the canvas (DR-6)", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    vi.mocked(fetchRuns).mockResolvedValue([]);
    vi.mocked(runWorkflow).mockRejectedValue(
      new ApiError(400, [{ message: "Workflow requires input 'name': the greeting target" }]),
    );
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());

    fireEvent.click(screen.getByLabelText("Run workflow"));
    fireEvent.click(await screen.findByRole("button", { name: "▶ Run" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/Workflow requires input 'name'/)).toBeTruthy();
    // The panel stays open (the form shows the error) and the canvas is intact.
    expect(screen.getByText("say hi")).toBeTruthy();
  });
});

describe("agent say callout (Task 174 + persistent-captions follow-up)", () => {
  // jsdom has no Audio/play() — stub a class whose play() returns a FRESH deferred promise per call
  // (the real HTMLMediaElement contract), so tests can resolve (autoplay allowed) or reject
  // (blocked / pause-aborted) each attempt on cue: resolvePlay(n)/rejectPlay(e, n) settle call n.
  // pause() does NOT fire onended (the real contract) — interruption transitions are driven by
  // startClip's sweep, natural finishes by fireEnded().
  class FakeAudio {
    static instances: FakeAudio[] = [];
    readonly src: string;
    onended: (() => void) | null = null;
    private readonly settlers: Array<{ res: () => void; rej: (e: unknown) => void }> = [];
    play = vi.fn(
      () =>
        new Promise<void>((res, rej) => {
          this.settlers.push({ res, rej });
        }),
    );
    pause = vi.fn();
    resolvePlay(call = 0): void {
      this.settlers[call]!.res();
    }
    rejectPlay(error: unknown, call = 0): void {
      this.settlers[call]!.rej(error);
    }
    fireEnded(): void {
      this.onended?.();
    }
    constructor(src: string) {
      this.src = src;
      FakeAudio.instances.push(this);
    }
  }

  beforeEach(() => {
    FakeAudio.instances = [];
    live.narration.mockClear();
    vi.stubGlobal("Audio", FakeAudio);
    // Earlier tests leak `?run=` into the URL through the component's own syncUrl (see the note at
    // the density test above) — which would open the RUN callout here too. Start clean.
    window.history.replaceState({}, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  const mountWithGraph = async (): Promise<void> => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
    await waitFor(() => expect(live.handlers).not.toBeNull());
  };
  const say = (caption: string, audioUrl: string | null = "/api/audio/x", ref = GRAPH.nodes[0]!.ref): void =>
    act(() => live.handlers!.say!({ kind: "node", ref }, caption, audioUrl));
  const boxOf = (caption: string): HTMLElement => screen.getByText(caption).closest(".node-callout")! as HTMLElement;
  const replayButtons = (): HTMLElement[] => screen.queryAllByRole("button", { name: "↻ Replay" });

  it("anchors a persistent caption and starts the clip — no Replay button while playing", async () => {
    await mountWithGraph();
    say("this is the LLM call");

    expect(screen.getByText("this is the LLM call")).toBeTruthy();
    expect(screen.getByText("Agent")).toBeTruthy(); // the callout chrome title
    expect(FakeAudio.instances).toHaveLength(1);
    expect(FakeAudio.instances[0]!.src).toBe("/api/audio/x");
    expect(FakeAudio.instances[0]!.play).toHaveBeenCalledOnce();
    // Pins the sweep excluding its OWN key: a just-started box must be "playing", not "done".
    expect(replayButtons()).toHaveLength(0);
  });

  it("swaps the equalizer for Replay in one fixed slot (shimmer + no resize) when the clip ends", async () => {
    await mountWithGraph();
    say("speaking now");
    const box = boxOf("speaking now");
    // While playing: the box shimmers, the affordance slot holds the (non-clickable) equalizer,
    // and there is NO Replay button — the swap, not an appear/disappear, is what avoids the resize.
    expect(box.classList.contains("say-playing")).toBe(true);
    expect(box.querySelector(".say-eq")).toBeTruthy();
    expect(replayButtons()).toHaveLength(0);

    act(() => FakeAudio.instances[0]!.fireEnded());
    const done = boxOf("speaking now");
    // Finished → shimmer off, equalizer gone, Replay now occupies the SAME slot.
    expect(done.classList.contains("say-playing")).toBe(false);
    expect(done.querySelector(".say-eq")).toBeNull();
    expect(replayButtons()).toHaveLength(1);
  });

  it("a caption-only box never shimmers (nothing is playing)", async () => {
    await mountWithGraph();
    say("just words", null);
    expect(boxOf("just words").classList.contains("say-playing")).toBe(false);
  });

  it("a caption-only say renders a persistent box with no clip and no dead Replay button", async () => {
    await mountWithGraph();
    say("just the words", null);

    expect(screen.getByText("just the words")).toBeTruthy();
    expect(FakeAudio.instances).toHaveLength(0);
    // status "done" + null audioUrl must not render a Replay button (nothing to replay).
    expect(replayButtons()).toHaveLength(0);
  });

  it("an edge-target say anchors at the target-side endpoint and shows the caption", async () => {
    await mountWithGraph();
    act(() =>
      live.handlers!.say!(
        {
          kind: "edge",
          source: GRAPH.nodes[0]!.ref,
          source_field: "stdout",
          source_path: [],
          target: GRAPH.nodes[1]!.ref,
          input_name: "command",
        },
        "this wire",
        null,
      ),
    );
    expect(screen.getByText("this wire")).toBeTruthy();
  });

  it("the close button dismisses the caption and pauses the clip", async () => {
    await mountWithGraph();
    say("dismiss me");
    const clip = FakeAudio.instances[0]!;

    // The say callout's OWN ✕ (scoped via the caption — the run callout shares the shell class).
    fireEvent.click(boxOf("dismiss me").querySelector(".node-callout-close")!);

    expect(screen.queryByText("dismiss me")).toBeNull();
    expect(clip.pause).toHaveBeenCalled();
  });

  it("a blocked autoplay shows the unlock button; the gesture starts the clip fresh", async () => {
    await mountWithGraph();
    say("locked out");
    const clip = FakeAudio.instances[0]!;
    await act(async () => {
      clip.rejectPlay(new Error("NotAllowedError"));
      await Promise.resolve();
    });
    const unlock = await screen.findByRole("button", { name: "▶ Play narration" });

    fireEvent.click(unlock); // startClip: the gesture creates a FRESH Audio for the same url

    const replayClip = FakeAudio.instances[1]!;
    expect(replayClip.src).toBe("/api/audio/x");
    expect(replayClip.play).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "▶ Play narration" })).toBeNull(); // playing now
    expect(screen.getByText("locked out")).toBeTruthy(); // the caption stays
  });

  it("a second say to the SAME target replaces just that box, pauses the prior clip, and the stale AbortError never flips it to blocked (currency guard)", async () => {
    await mountWithGraph();
    say("first line");
    say("second line");
    const [first, second] = [FakeAudio.instances[0]!, FakeAudio.instances[1]!];

    expect(screen.queryByText("first line")).toBeNull();
    expect(screen.getByText("second line")).toBeTruthy();
    expect(first.pause).toHaveBeenCalled();

    // The browser rejects the FIRST clip's in-flight play() with AbortError as a microtask AFTER the
    // second clip started (pause() aborted it). With autoplay allowed on the second clip, the unlock
    // button must stay ABSENT — an unguarded catch would show it while the second clip plays.
    await act(async () => {
      first.rejectPlay(new DOMException("interrupted", "AbortError"));
      second.resolvePlay();
      await Promise.resolve();
    });
    expect(screen.queryByRole("button", { name: "▶ Play narration" })).toBeNull();
  });

  it("says to DIFFERENT targets coexist as separate boxes; closing one leaves the other", async () => {
    await mountWithGraph();
    say("box one");
    say("box two", "/api/audio/y", GRAPH.nodes[1]!.ref);

    expect(screen.getByText("box one")).toBeTruthy();
    expect(screen.getByText("box two")).toBeTruthy();

    fireEvent.click(boxOf("box one").querySelector(".node-callout-close")!);
    expect(screen.queryByText("box one")).toBeNull();
    expect(screen.getByText("box two")).toBeTruthy();
  });

  it("a new say flips the interrupted box to done — replayable, not lost", async () => {
    await mountWithGraph();
    say("interrupted");
    say("interrupter", "/api/audio/y", GRAPH.nodes[1]!.ref);

    expect(FakeAudio.instances[0]!.pause).toHaveBeenCalled();
    // The interrupted box grew a Replay button (done); the interrupter is playing (no button on it).
    expect(within(boxOf("interrupted")).getByRole("button", { name: "↻ Replay" })).toBeTruthy();
    expect(replayButtons()).toHaveLength(1);
  });

  it("a clip that finishes naturally grows a Replay button that starts it again", async () => {
    await mountWithGraph();
    say("finished line");
    const clip = FakeAudio.instances[0]!;
    await act(async () => {
      clip.resolvePlay();
      await Promise.resolve();
    });
    expect(replayButtons()).toHaveLength(0); // still playing

    act(() => clip.fireEnded());
    fireEvent.click(screen.getByRole("button", { name: "↻ Replay" }));

    expect(FakeAudio.instances).toHaveLength(2); // replay re-creates the Audio
    expect(FakeAudio.instances[1]!.play).toHaveBeenCalledOnce();
    expect(replayButtons()).toHaveLength(0); // playing again
  });

  it("a replay whose clip was evicted (play rejects) expires the button but keeps the caption", async () => {
    await mountWithGraph();
    say("old news");
    act(() => FakeAudio.instances[0]!.fireEnded());
    fireEvent.click(screen.getByRole("button", { name: "↻ Replay" }));

    const replayClip = FakeAudio.instances[1]!;
    await act(async () => {
      replayClip.rejectPlay(new Error("NotSupportedError")); // 404 — evicted from the server LRU
      await Promise.resolve();
    });

    expect(replayButtons()).toHaveLength(0); // expired
    expect(screen.queryByRole("button", { name: "▶ Play narration" })).toBeNull();
    expect(screen.getByText("old news")).toBeTruthy(); // the caption is the baseline — it stays
  });

  it("replaying one box while another is playing finishes the playing one (never stuck 'playing')", async () => {
    await mountWithGraph();
    say("box A");
    act(() => FakeAudio.instances[0]!.fireEnded()); // A done → Replay
    say("box B", "/api/audio/y", GRAPH.nodes[1]!.ref); // B playing

    fireEvent.click(within(boxOf("box A")).getByRole("button", { name: "↻ Replay" }));

    expect(FakeAudio.instances[1]!.pause).toHaveBeenCalled(); // B's clip paused...
    expect(within(boxOf("box B")).getByRole("button", { name: "↻ Replay" })).toBeTruthy(); // ...and B is done, not stuck
    expect(within(boxOf("box A")).queryByRole("button", { name: "↻ Replay" })).toBeNull(); // A playing again
  });

  it("playback beacons report started and ended truthfully", async () => {
    await mountWithGraph();
    say("beacon check");
    const clip = FakeAudio.instances[0]!;
    await act(async () => {
      clip.resolvePlay();
      await Promise.resolve();
    });
    expect(live.narration).toHaveBeenCalledWith("/api/audio/x", "started");

    act(() => clip.fireEnded());
    expect(live.narration).toHaveBeenCalledWith("/api/audio/x", "ended");
  });

  it("an autoplay-blocked play beacons 'blocked'; an expired replay does NOT", async () => {
    await mountWithGraph();
    say("silent window");
    const clip = FakeAudio.instances[0]!;
    await act(async () => {
      clip.rejectPlay(new Error("NotAllowedError"));
      await Promise.resolve();
    });
    expect(live.narration).toHaveBeenCalledWith("/api/audio/x", "blocked");

    live.narration.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "▶ Play narration" }));
    const replayClip = FakeAudio.instances[1]!;
    await act(async () => {
      replayClip.rejectPlay(new Error("NotSupportedError")); // evicted clip, not a silent window
      await Promise.resolve();
    });
    expect(live.narration).not.toHaveBeenCalledWith("/api/audio/x", "blocked");
  });

  it("closing the playing box beacons 'ended' so the next say need not wait it out", async () => {
    await mountWithGraph();
    say("stop talking");
    fireEvent.click(boxOf("stop talking").querySelector(".node-callout-close")!);
    expect(live.narration).toHaveBeenCalledWith("/api/audio/x", "ended");
  });

  it("the agent's clear verb dismisses ALL boxes and pauses; a bare focus does not", async () => {
    await mountWithGraph();
    say("sticky caption");
    say("second box", "/api/audio/y", GRAPH.nodes[1]!.ref);
    const playing = FakeAudio.instances[1]!;

    // A bare focus (no --say) leaves the boxes alone — captions persist until dismissed (locked).
    act(() => live.handlers!.focus({ kind: "node", ref: GRAPH.nodes[1]!.ref }));
    expect(screen.getByText("sticky caption")).toBeTruthy();
    expect(screen.getByText("second box")).toBeTruthy();
    expect(playing.pause).not.toHaveBeenCalled();

    act(() => live.handlers!.clear());
    expect(screen.queryByText("sticky caption")).toBeNull();
    expect(screen.queryByText("second box")).toBeNull();
    expect(playing.pause).toHaveBeenCalled();
  });

  it("unmounting the view pauses a playing clip (Back to catalog must stop the voice)", async () => {
    vi.mocked(fetchGraph).mockResolvedValue(GRAPH);
    const { unmount } = render(<GraphView workflow="demo" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByText("say hi")).toBeTruthy());
    await waitFor(() => expect(live.handlers).not.toBeNull());
    act(() => live.handlers!.say!({ kind: "node", ref: GRAPH.nodes[0]!.ref }, "leaving now", "/api/audio/x"));
    const clip = FakeAudio.instances[0]!;
    expect(clip.pause).not.toHaveBeenCalled();

    unmount();

    expect(clip.pause).toHaveBeenCalled();
  });

  it("a stale target ref drops the say silently — no callout, no clip", async () => {
    await mountWithGraph();
    act(() => live.handlers!.say!({ kind: "node", ref: { node_id: "vanished", ancestor_path: [], port: null } }, "ghost", "/api/audio/x"));

    expect(screen.queryByText("ghost")).toBeNull();
    expect(screen.queryByText("Agent")).toBeNull();
    expect(FakeAudio.instances).toHaveLength(0);
  });
});
