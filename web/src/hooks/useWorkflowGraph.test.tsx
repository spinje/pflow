// @vitest-environment jsdom
//
// Paint-pipeline tests for useWorkflowGraph (architecture-review candidate 3,
// Route A: through the hook's EXISTING interface — zero production change).
// The machinery under test is everything AROUND layout — the stale-paint guard,
// the layout cache + its eviction bound, camera anchoring (leaf / io-port /
// edge anchors), paintEpoch, the animated glide, mid-flight cancellation — so
// layoutGraph is mocked as a CONTROLLABLE DEFERRED, never an instant stub:
// every ordering claim below holds while a layout is genuinely in flight.
// ELK itself has real smokes in flow.test.ts / layout.test.ts.
//
// jsdom renders no React Flow DOM and the hook renders none — assertions read
// the hook's returned nodes/edges/paintEpoch/status and the setViewport spy.

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { installReactFlowJsdomMocks } from "../test/rf-jsdom";
import type { FlowNode, LeafData } from "../graph/flow";
import type { EdgeKind, RFEdge, RFGraph, RFGroup, RFNode } from "../types";

// Mock only the network seam; keep the REAL ApiError — the hook's catch arm
// discriminates with `instanceof ApiError`, so a factory that drops the class
// would crash the error path instead of testing it.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, fetchGraph: vi.fn(), fetchCatalog: vi.fn(), fetchSource: vi.fn() };
});
// The controllable deferred — tests resolve/reject pendingLayouts on cue.
vi.mock("../graph/layout", () => ({ layoutGraph: vi.fn() }));
// Partial-mock @xyflow/react ONLY to observe the camera: setViewport records
// its args (the pan assertions) and getViewport serves a test-controlled
// viewport (so zoom-scaling is assertable). Everything else calls through.
const setViewportSpy = vi.hoisted(() => vi.fn());
const viewportRef = vi.hoisted(() => ({ current: { x: 0, y: 0, zoom: 1 } }));
vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  const { useMemo } = await import("react");
  return {
    ...actual,
    useReactFlow: (): ReturnType<typeof actual.useReactFlow> => {
      const inst = actual.useReactFlow();
      // MEMOIZED like the real instance: getViewport/setViewport sit in the
      // hook's decoration-effect dep array — fresh identities every render
      // re-fire the effect after its own paint (setNodes → render → new fns →
      // effect → setNodes…), an infinite loop that starves the worker.
      return useMemo(
        () => ({
          ...inst,
          getViewport: () => ({ ...viewportRef.current }),
          setViewport: (vp: { x: number; y: number; zoom: number }) => {
            setViewportSpy(vp);
            viewportRef.current = vp;
            return Promise.resolve(true);
          },
        }),
        [inst],
      );
    },
  };
});

import { ReactFlowProvider } from "@xyflow/react";
import { ApiError, fetchGraph } from "../api/client";
import { layoutGraph } from "../graph/layout";
import { useWorkflowGraph, type WorkflowGraphView } from "./useWorkflowGraph";

// ---- fixture builders (the flow.test.ts vocabulary) -----------------------

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

function group(id: string, over: Partial<RFGroup> = {}): RFGroup {
  return { id, kind: "workflow", parent: null, host: null, members: [], nesting_depth: 0, annotations: {}, ...over };
}

function edge(id: string, source: string, target: string, kind: EdgeKind, over: Partial<RFEdge> = {}): RFEdge {
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [], ...over };
}

// Two leaves joined by one data edge: in beautiful, focusing "a" (or the edge)
// expands {a, b} — the smallest graph where focus changes the layout state.
const DATA_GRAPH: RFGraph = {
  nodes: [node("a"), node("b", { params: [{ name: "command", value: "${a.stdout}", is_dynamic: true, source: null }] })],
  edges: [edge("e0", "a", "b", "data_flow", { output_field: "stdout", input_name: "command" })],
  groups: [],
};

// A sub-workflow with a nested input port p1 (io member — rendered as a ROW on
// g_wf, never a node) bound by root leaf r0, plus an unrelated leaf "a" for the
// pinned-subject test. Focusing p1 must anchor/expand its OWNER (g_wf).
const NESTED: RFGraph = {
  nodes: [
    node("h0", { kind: "workflow", is_group_host: true }),
    node("m0", { parent: "g_wf" }),
    node("p1", { kind: "input", io: { data_type: null, required: true, default: null }, parent: "g_wf_in" }),
    node("r0"),
    node("a"),
  ],
  edges: [edge("e_b", "r0", "p1", "data_flow", { output_field: "stdout", input_name: "x" })],
  groups: [
    group("g_wf", { host: "h0", members: ["m0"] }),
    group("g_wf_in", { kind: "input_wrapper", parent: "g_wf", members: ["p1"] }),
  ],
};

// ---- harness ---------------------------------------------------------------

interface PendingLayout {
  nodes: FlowNode[];
  resolve: (laid: FlowNode[]) => void;
  reject: (e: unknown) => void;
}
let pendingLayouts: PendingLayout[] = [];

// Position the deferred's nodes: listed ids get their position, the rest (0,0).
const at =
  (positions: Record<string, { x: number; y: number }>) =>
  (nodes: FlowNode[]): FlowNode[] =>
    nodes.map((n) => ({ ...n, position: positions[n.id] ?? { x: 0, y: 0 } }));

async function resolveLayout(index: number, position: (nodes: FlowNode[]) => FlowNode[] = at({})): Promise<void> {
  const p = pendingLayouts[index];
  if (!p) throw new Error(`no pending layout at index ${index} (have ${pendingLayouts.length})`);
  await act(async () => {
    p.resolve(position(p.nodes));
  });
}

// Stable collapsed-set identity: the build memo depends on it by reference.
const NONE: ReadonlySet<string> = new Set();
function view(over: Partial<WorkflowGraphView> = {}): WorkflowGraphView {
  return { density: "compact", direction: "LR", collapsed: NONE, focus: null, selected: null, workflowName: "wf", ...over };
}

const wrapper = ({ children }: { children: ReactNode }): ReactNode => <ReactFlowProvider>{children}</ReactFlowProvider>;

function renderGraph(initial: { workflow: string; view: WorkflowGraphView }) {
  return renderHook(({ workflow, view: v }) => useWorkflowGraph(workflow, v), { initialProps: initial, wrapper });
}

// Mount, let the fetch land, and wait for the first layout request.
async function mountReady(graph: RFGraph, v: WorkflowGraphView = view()): Promise<ReturnType<typeof renderGraph>> {
  vi.mocked(fetchGraph).mockResolvedValue(graph);
  const h = renderGraph({ workflow: "wf", view: v });
  await waitFor(() => expect(pendingLayouts.length).toBe(1));
  return h;
}

// The glide gate reads prefers-reduced-motion; forcing it ON pins the snap path
// in tests where animation is not the subject (the handoff's prescribed lever).
function setReducedMotion(on: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: on && query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

beforeAll(() => installReactFlowJsdomMocks());
beforeEach(() => {
  pendingLayouts = [];
  vi.mocked(fetchGraph).mockReset();
  vi.mocked(layoutGraph).mockReset();
  vi.mocked(layoutGraph).mockImplementation(
    (nodes: FlowNode[]) =>
      new Promise<FlowNode[]>((resolve, reject) => {
        pendingLayouts.push({ nodes, resolve, reject });
      }),
  );
  setViewportSpy.mockClear();
  viewportRef.current = { x: 0, y: 0, zoom: 1 };
});
afterEach(() => {
  vi.unstubAllGlobals(); // rAF stubs from the glide test
  vi.restoreAllMocks(); // the performance.now spy
  installReactFlowJsdomMocks(); // restore the default (no-reduced-motion) matchMedia
});

const expandedOf = (nodes: FlowNode[], id: string): boolean => {
  const n = nodes.find((x) => x.id === id);
  if (!n) throw new Error(`node ${id} not in the painted snapshot`);
  return (n.data as LeafData).expanded;
};

// ---- tests -----------------------------------------------------------------

describe("useWorkflowGraph — stale-paint guard", () => {
  it("a focus that changes the layout state never paints new-focus-on-old-layout; the resolve is ONE paint", async () => {
    const h = await mountReady(DATA_GRAPH);
    await resolveLayout(0);
    expect(h.result.current.status).toBe("ready");
    expect(h.result.current.paintEpoch).toBe(1);
    const painted = h.result.current.nodes;

    // Focus "a" in beautiful: the expansion set {a,b} changes layoutKey. The
    // decoration effect re-fires immediately with the OLD laid snapshot — the
    // guard must skip it entirely (the "shake": one frame of new-focus-on-old-
    // layout), so nothing repaints and paintEpoch does NOT bump (the skipped
    // stale paint is exactly the no-bump case).
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a" }) });
    });
    expect(h.result.current.paintEpoch).toBe(1);
    expect(h.result.current.nodes).toBe(painted); // setNodes never called
    expect(pendingLayouts.length).toBe(2); // the expansion layout IS in flight

    // Resolving the expansion layout produces exactly one visible change,
    // already carrying the focus decoration (a's body expanded).
    await resolveLayout(1);
    expect(h.result.current.paintEpoch).toBe(2);
    expect(expandedOf(h.result.current.nodes, "a")).toBe(true);
  });
});

describe("useWorkflowGraph — layout cache", () => {
  it("un-focus and re-focus replay cached layouts synchronously — ELK runs exactly twice", async () => {
    const h = await mountReady(DATA_GRAPH);
    await resolveLayout(0);
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a" }) });
    });
    await resolveLayout(1);
    expect(vi.mocked(layoutGraph)).toHaveBeenCalledTimes(2); // base + expansion
    expect(h.result.current.paintEpoch).toBe(2);

    // Un-focus: back to the base key — a synchronous cache hit (the paint lands
    // inside the same act, no deferred to resolve).
    await act(async () => {
      h.rerender({ workflow: "wf", view: view() });
    });
    expect(vi.mocked(layoutGraph)).toHaveBeenCalledTimes(2);
    expect(h.result.current.paintEpoch).toBe(3);
    expect(expandedOf(h.result.current.nodes, "a")).toBe(false);

    // Re-focus: the expansion key is cached too (two focuses with one expansion
    // set share an entry — the key is the derived state, not the focus).
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a" }) });
    });
    expect(vi.mocked(layoutGraph)).toHaveBeenCalledTimes(2);
    expect(h.result.current.paintEpoch).toBe(4);
    expect(expandedOf(h.result.current.nodes, "a")).toBe(true);
    expect(h.result.current.status).toBe("ready");
  });

  it("the cache is bounded: >24 distinct states evict the oldest, recent states stay cached", async () => {
    const h = await mountReady(DATA_GRAPH);
    await resolveLayout(0); // state K0 (call 1)
    // 25 distinct collapse states K1..K25 (calls 2..26): inserting K24 evicts
    // K0, inserting K25 evicts K1 (insertion-order eviction, cap 24).
    for (let i = 1; i <= 25; i++) {
      await act(async () => {
        h.rerender({ workflow: "wf", view: view({ collapsed: new Set([`c${i}`]) }) });
      });
      await resolveLayout(i);
    }
    expect(vi.mocked(layoutGraph)).toHaveBeenCalledTimes(26);

    // K0 was evicted: revisiting it re-runs layout (bounded growth, observable
    // exactly here — an unbounded cache would replay it)...
    await act(async () => {
      h.rerender({ workflow: "wf", view: view() });
    });
    expect(vi.mocked(layoutGraph)).toHaveBeenCalledTimes(27);
    await resolveLayout(26);

    // ...while a recent state is still a hit (a NEW Set with the same content —
    // the cache keys on the derived string, not Set identity).
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ collapsed: new Set(["c25"]) }) });
    });
    expect(vi.mocked(layoutGraph)).toHaveBeenCalledTimes(27);
  });
});

describe("useWorkflowGraph — paintEpoch", () => {
  it("on the animated path the epoch bumps when the glide LANDS, not when it starts", async () => {
    // moved nodes + ≤ ANIMATE_MAX_NODES + no reduced-motion ⇒ the glide path.
    // rAF is stubbed to a manual queue so the test drives frames explicitly.
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      frames.push(cb);
      return frames.length;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
    vi.spyOn(performance, "now").mockReturnValue(0); // glide t0

    const h = await mountReady(DATA_GRAPH);
    await resolveLayout(0, at({ a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }));
    expect(h.result.current.paintEpoch).toBe(1); // snap paint (no `from` yet)

    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a" }) });
    });
    await resolveLayout(1, at({ a: { x: 50, y: 30 }, b: { x: 200, y: 0 } }));

    // The glide started (one frame scheduled) but the paint has NOT completed.
    expect(frames.length).toBe(1);
    expect(h.result.current.paintEpoch).toBe(1);

    // Mid-glide frame (t=0.5): positions interpolate, still no bump.
    act(() => {
      frames.shift()!(100);
    });
    expect(h.result.current.paintEpoch).toBe(1);
    const aMid = h.result.current.nodes.find((n) => n.id === "a")!;
    expect(aMid.position.x).toBeGreaterThan(0);
    expect(aMid.position.x).toBeLessThan(50);

    // Landing frame (t=1): the EXACT final snapshot + the bump.
    act(() => {
      frames.shift()!(250);
    });
    expect(h.result.current.paintEpoch).toBe(2);
    expect(h.result.current.nodes.find((n) => n.id === "a")!.position).toEqual({ x: 50, y: 30 });
  });

  it("an interrupted glide lands on the final snapshot — nothing strands at an interpolated position", async () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      frames.push(cb);
      return frames.length;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
    vi.spyOn(performance, "now").mockReturnValue(0);

    const h = await mountReady(DATA_GRAPH);
    await resolveLayout(0, at({ a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }));
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a" }) });
    });
    await resolveLayout(1, at({ a: { x: 50, y: 30 }, b: { x: 200, y: 0 } }));

    // Mid-glide…
    act(() => {
      frames.shift()!(100);
    });
    expect(h.result.current.nodes.find((n) => n.id === "a")!.position.x).toBeLessThan(50);

    // …a direction change interrupts. The effect cleanup must land the EXACT
    // final snapshot (the new direction's own layout paints later, and the
    // stale-paint guard skips until it does — interpolated positions would
    // otherwise strand on screen for that whole window).
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a", direction: "TD" }) });
    });
    expect(h.result.current.nodes.find((n) => n.id === "a")!.position).toEqual({ x: 50, y: 30 });
    expect(h.result.current.paintEpoch).toBe(1); // the glide never LANDED — no bump
  });
});

describe("useWorkflowGraph — builtEdgeIds", () => {
  it("is synchronous with the focus-derived build while painted edges lag the async layout", async () => {
    // Two parallel bindings a→b: with rows hidden (beautiful, unexpanded) they
    // DEDUPE to one node-level line (e0 survives, e1 skipped); focusing the
    // deduped edge id expands both endpoints, the rows render, and e1 gets its
    // own handle — in the SAME build that focus triggers. The painted edge set
    // lags one layout round-trip behind, which is why GraphView's edge-selection
    // invalidation consults builtEdgeIds (review-caught 2026-06-11: consulting
    // the painted snapshot cancelled a deep-linked deduped edge mid-expansion).
    const twoBindings: RFGraph = {
      nodes: [
        node("a"),
        node("b", {
          params: [
            { name: "command", value: "${a.stdout}", is_dynamic: true, source: null },
            { name: "other", value: "${a.stdout}", is_dynamic: true, source: null },
          ],
        }),
      ],
      edges: [
        edge("e0", "a", "b", "data_flow", { output_field: "stdout", input_name: "command" }),
        edge("e1", "a", "b", "data_flow", { output_field: "stdout", input_name: "other" }),
      ],
      groups: [],
    };
    const h = await mountReady(twoBindings);
    await resolveLayout(0);
    expect(h.result.current.builtEdgeIds.has("e0")).toBe(true);
    expect(h.result.current.builtEdgeIds.has("e1")).toBe(false); // deduped node-level

    // The deep-link gesture: focus the edge that the unexpanded view deduped.
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "e1" }) });
    });
    // The build the focus itself triggered already carries e1…
    expect(h.result.current.builtEdgeIds.has("e1")).toBe(true);
    // …while the PAINTED snapshot still lacks it (the lag an invalidation
    // reading `edges` would mistake for "this edge no longer exists").
    expect(h.result.current.edges.some((e) => e.id === "e1")).toBe(false);

    await resolveLayout(1);
    expect(h.result.current.edges.some((e) => e.id === "e1")).toBe(true);
  });
});

describe("useWorkflowGraph — camera anchoring", () => {
  it("an expansion re-layout pans the viewport by the anchor's delta, zoom-scaled", async () => {
    setReducedMotion(true); // snap path — animation is not the subject here
    viewportRef.current = { x: 10, y: 20, zoom: 2 };

    const h = await mountReady(DATA_GRAPH);
    await resolveLayout(0, at({ a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }));
    setViewportSpy.mockClear();

    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a" }) });
    });
    await resolveLayout(1, at({ a: { x: 50, y: 30 }, b: { x: 200, y: 0 } }));

    // Anchor "a" moved by (50, 30); the camera compensates against the CURRENT
    // viewport, scaled by zoom, so the clicked node never moves on screen.
    expect(setViewportSpy).toHaveBeenCalledWith({ zoom: 2, x: 10 - 50 * 2, y: 20 - 30 * 2 });
  });

  it("an io-PORT focus anchors on the port's OWNER group — ports are rows, never rendered nodes", async () => {
    setReducedMotion(true);
    const h = await mountReady(NESTED);
    await resolveLayout(0, at({ g_wf: { x: 0, y: 0 }, r0: { x: 300, y: 0 }, a: { x: 0, y: 200 } }));
    setViewportSpy.mockClear();

    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "p1" }) });
    });
    await resolveLayout(1, at({ g_wf: { x: 40, y: 10 }, r0: { x: 320, y: 0 }, a: { x: 0, y: 200 } }));

    // The pan compensates g_wf's (the owner's) delta. Anchoring on p1 itself
    // resolves no position (io members are rows on their owner, not nodes), the
    // compensation silently no-ops, and the canvas jumps out from under the
    // camera — the 2026-06-12 "zoom to nowhere" bug this test regresses.
    expect(setViewportSpy).toHaveBeenCalledWith({ zoom: 1, x: -40, y: -10 });
  });

  it("an EDGE focus anchors on the edge's rendered source endpoint", async () => {
    setReducedMotion(true);
    const h = await mountReady(DATA_GRAPH);
    await resolveLayout(0, at({ a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }));
    setViewportSpy.mockClear();

    // Selecting the data edge expands both endpoints (a re-layout); the anchor
    // is the edge's flow SOURCE — an edge id itself resolves no node position.
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "e0" }) });
    });
    await resolveLayout(1, at({ a: { x: 25, y: 5 }, b: { x: 200, y: 50 } }));

    expect(setViewportSpy).toHaveBeenCalledWith({ zoom: 1, x: -25, y: -5 });
  });

  it("view changes (direction / density) re-layout WITHOUT a compensating pan", async () => {
    setReducedMotion(true);
    const h = await mountReady(DATA_GRAPH);
    await resolveLayout(0, at({ a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }));
    // Establish an anchor (a focused expansion happened)...
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a" }) });
    });
    await resolveLayout(1, at({ a: { x: 50, y: 30 }, b: { x: 200, y: 0 } }));
    setViewportSpy.mockClear();

    // ...but a DIRECTION change moves everything and must not pan-compensate:
    // those transitions have their own viewport semantics (GraphView's fit).
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a", direction: "TD" }) });
    });
    await resolveLayout(2, at({ a: { x: 500, y: 400 }, b: { x: 0, y: 0 } }));
    expect(setViewportSpy).not.toHaveBeenCalled();

    // Same gate, density arm: switching to advanced re-layouts, still no pan.
    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "a", direction: "TD", density: "detailed" }) });
    });
    await resolveLayout(3, at({ a: { x: 0, y: 0 }, b: { x: 900, y: 900 } }));
    expect(setViewportSpy).not.toHaveBeenCalled();
    expect(h.result.current.status).toBe("ready");
  });
});

describe("useWorkflowGraph — pinned subject", () => {
  it("the open panel's subject stays expanded when chip navigation moves focus to a container", async () => {
    // Reading leaf "a" (selected) and navigating to container g_wf: without the
    // pin, expandTargets' container arm scans only the container's port-level
    // edges and "a" contracts mid-read (the 2026-06-12 fix this regresses).
    const h = await mountReady(NESTED, view({ focus: "a", selected: "a" }));
    await resolveLayout(0);
    expect(expandedOf(h.result.current.nodes, "a")).toBe(true);

    await act(async () => {
      h.rerender({ workflow: "wf", view: view({ focus: "g_wf", selected: "a" }) });
    });
    await resolveLayout(1);

    // Focus moved (the container's binding endpoint r0 expanded with it)…
    expect(expandedOf(h.result.current.nodes, "r0")).toBe(true);
    // …and the pinned subject keeps its body.
    expect(expandedOf(h.result.current.nodes, "a")).toBe(true);
  });
});

describe("useWorkflowGraph — lifecycle", () => {
  it("a workflow switch mid-layout discards the stale layout — no paint from the old workflow", async () => {
    const g1: RFGraph = { nodes: [node("old1")], edges: [], groups: [] };
    const g2: RFGraph = { nodes: [node("new1")], edges: [], groups: [] };
    vi.mocked(fetchGraph).mockImplementation(async (w: string) => (w === "wf1" ? g1 : g2));
    const h = renderGraph({ workflow: "wf1", view: view() });
    await waitFor(() => expect(pendingLayouts.length).toBe(1));

    // Switch while wf1's layout is in flight; wf2 requests its own layout.
    await act(async () => {
      h.rerender({ workflow: "wf2", view: view() });
    });
    await waitFor(() => expect(pendingLayouts.length).toBe(2));

    // The stale resolve is discarded: no paint, no epoch, still loading.
    await resolveLayout(0);
    expect(h.result.current.status).toBe("loading");
    expect(h.result.current.paintEpoch).toBe(0);
    expect(h.result.current.nodes).toEqual([]);

    await resolveLayout(1);
    expect(h.result.current.status).toBe("ready");
    expect(h.result.current.nodes.map((n) => n.id)).toEqual(["new1"]);
  });

  it("a layout rejection surfaces as status 'error' with the message — never a stuck 'loading'", async () => {
    const h = await mountReady(DATA_GRAPH);
    await act(async () => {
      pendingLayouts[0]!.reject(new Error("elk exploded"));
    });
    expect(h.result.current.status).toBe("error");
    expect(h.result.current.errors?.[0]?.message).toContain("Could not lay out this workflow");
    expect(h.result.current.errors?.[0]?.message).toContain("elk exploded");
  });
});

describe("useWorkflowGraph — live reload (same workflow, source changed)", () => {
  // The DETECTION (the /api/version poll) lives in useSourceWatch; here the
  // REACTION is pinned: a `reload` bump on the SAME workflow re-fetches and
  // rebuilds IN PLACE, distinct from the workflow-change full reset.
  function renderReloadable(graph: RFGraph, v: WorkflowGraphView = view()) {
    vi.mocked(fetchGraph).mockResolvedValue(graph);
    return renderHook(({ workflow, view: vv, reload }) => useWorkflowGraph(workflow, vv, reload), {
      initialProps: { workflow: "wf", view: v, reload: 0 },
      wrapper,
    });
  }

  it("a reload bump re-fetches and rebuilds IN PLACE — no loading flash, no camera move", async () => {
    const h = renderReloadable(DATA_GRAPH);
    await waitFor(() => expect(pendingLayouts.length).toBe(1));
    await resolveLayout(0, at({ a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }));
    expect(h.result.current.status).toBe("ready");
    setViewportSpy.mockClear();

    // The source changed on disk → a NEW graph object comes back, reload bumps.
    const next: RFGraph = { ...DATA_GRAPH };
    vi.mocked(fetchGraph).mockResolvedValue(next);
    await act(async () => {
      h.rerender({ workflow: "wf", view: view(), reload: 1 });
    });

    // A FRESH layout is requested (the cache was cleared — the structure may
    // differ), but the OLD canvas stays painted: status never flashed to
    // "loading" and the camera was never panned (a reload is not an expansion).
    await waitFor(() => expect(pendingLayouts.length).toBe(2));
    expect(h.result.current.status).toBe("ready");
    expect(setViewportSpy).not.toHaveBeenCalled();

    await resolveLayout(1, at({ a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }));
    expect(h.result.current.status).toBe("ready");
    expect(h.result.current.graph).toBe(next);
    expect(setViewportSpy).not.toHaveBeenCalled();
  });

  it("a reload that fails (mid-edit invalid) keeps the last-good graph + sets reloadError, never the full-screen error", async () => {
    const h = renderReloadable(DATA_GRAPH);
    await waitFor(() => expect(pendingLayouts.length).toBe(1));
    await resolveLayout(0);
    const goodGraph = h.result.current.graph;
    expect(h.result.current.status).toBe("ready");

    vi.mocked(fetchGraph).mockRejectedValue(new ApiError(422, [{ message: "unknown node type" }]));
    await act(async () => {
      h.rerender({ workflow: "wf", view: view(), reload: 1 });
    });

    expect(h.result.current.status).toBe("ready"); // canvas stays up — NOT "error"
    expect(h.result.current.graph).toBe(goodGraph); // last-good preserved
    expect(h.result.current.reloadError).toEqual([{ message: "unknown node type" }]);
    expect(h.result.current.errors).toBeNull();

    // A subsequent VALID save clears reloadError and swaps in the new graph.
    const fixed: RFGraph = { ...DATA_GRAPH };
    vi.mocked(fetchGraph).mockResolvedValue(fixed);
    await act(async () => {
      h.rerender({ workflow: "wf", view: view(), reload: 2 });
    });
    await waitFor(() => expect(pendingLayouts.length).toBe(2));
    await resolveLayout(1);
    expect(h.result.current.reloadError).toBeNull();
    expect(h.result.current.graph).toBe(fixed);
  });
});
