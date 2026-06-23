// @vitest-environment jsdom
//
// Focused pins for the camera state machine. GraphView.test.tsx covers the
// chip-click follows end-to-end (instant layout stub), but it cannot
// DISCRIMINATE click-time from paint-time fits — the exact distinction behind
// the 2026-06-12 "first click landed wrong, second landed right" bug. Here
// paintEpoch is a plain prop, so the deferral is directly observable.
//
// @xyflow/react is replaced with a STABLE module-level instance (the
// candidate-3 harness lesson: fitView/getNodes sit in effect dep arrays, so
// fresh identities per render would re-fire the paint-follow effect and
// consume the pending follow before the epoch bump it waits for).

import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

const fitViewSpy = vi.hoisted(() => vi.fn());
const rf = vi.hoisted(() => ({ renderedIds: [] as string[] }));
vi.mock("@xyflow/react", () => {
  const instance = {
    fitView: fitViewSpy,
    getNodes: () => rf.renderedIds.map((id) => ({ id })),
  };
  return {
    useReactFlow: () => instance,
    useNodesInitialized: () => true,
  };
});

import { useCameraNavigation } from "./useCameraNavigation";
import { DEFAULT_VIEW } from "../utils/viewParams";

type Args = Parameters<typeof useCameraNavigation>[0];

const makeProps = (over: Partial<Args> = {}): Args => ({
  status: "ready",
  paintEpoch: 0,
  graph: null,
  workflow: "wf",
  direction: "LR",
  initialView: DEFAULT_VIEW,
  ioPorts: null,
  focus: null,
  setFocus: vi.fn(),
  setSelectedId: vi.fn(),
  clearHover: vi.fn(),
  ...over,
});

/** The follow fit aimed at `id` (vs the whole-graph view fit, which has no nodes). */
const followCalls = (id: string): number =>
  fitViewSpy.mock.calls.filter((c) => (c[0] as { nodes?: { id: string }[] } | undefined)?.nodes?.[0]?.id === id).length;

beforeEach(() => {
  fitViewSpy.mockClear();
  rf.renderedIds = [];
  // Default visible; the hidden-tab re-frame tests flip it and must not leak it.
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

const setVisibility = (value: "visible" | "hidden"): void => {
  Object.defineProperty(document, "visibilityState", { configurable: true, value });
};

describe("useCameraNavigation", () => {
  it("a NEW-focus navigate defers the follow to the paint the click produces (paintEpoch), never click time", () => {
    rf.renderedIds = ["n1", "other"];
    const props = makeProps({ focus: "other" });
    const { result, rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear(); // drop the mount view-fit

    act(() => result.current.onNavigate("n1"));
    // Focus moved + hover cleared, but the camera holds: a fit now would aim
    // at the target's PRE-re-layout position.
    expect(props.setFocus).toHaveBeenCalledWith("n1");
    expect(props.clearHover).toHaveBeenCalled();
    expect(fitViewSpy).not.toHaveBeenCalled();

    // The completed paint bumps the epoch — the pending follow fires once.
    rerender({ ...props, paintEpoch: 1 });
    expect(followCalls("n1")).toBe(1);
    // Later paints don't re-fire a consumed follow.
    rerender({ ...props, paintEpoch: 2 });
    expect(followCalls("n1")).toBe(1);
  });

  it("a SAME-focus navigate fits immediately — nothing repaints, positions are already settled", () => {
    rf.renderedIds = ["n1"];
    const { result } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: makeProps({ focus: "n1" }) });
    fitViewSpy.mockClear();

    act(() => result.current.onNavigate("n1"));
    expect(followCalls("n1")).toBe(1);
  });

  it("an io-PORT id resolves to its OWNER card for the follow (a port is never a rendered node)", () => {
    rf.renderedIds = ["g1"];
    const props = makeProps({ ioPorts: new Map([["p1", "g1"]]) });
    const { result, rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    act(() => result.current.onNavigate("p1"));
    rerender({ ...props, paintEpoch: 1 });
    expect(followCalls("g1")).toBe(1);
  });

  it("an unresolvable target arms nothing — no fit on any later paint", () => {
    rf.renderedIds = ["n1"];
    const props = makeProps();
    const { result, rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    act(() => result.current.onNavigate("ghost"));
    rerender({ ...props, paintEpoch: 1 });
    expect(fitViewSpy).not.toHaveBeenCalled();
  });

  it("frames without changing focus, deferring until a revealed target paints", () => {
    rf.renderedIds = [];
    const props = makeProps();
    const { result, rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    act(() => result.current.frameTargets(["n1", "n2"]));
    expect(props.setFocus).not.toHaveBeenCalled();
    expect(props.setSelectedId).not.toHaveBeenCalled();
    expect(fitViewSpy).not.toHaveBeenCalled();

    rf.renderedIds = ["n1", "n2"];
    rerender({ ...props, paintEpoch: 1 });
    expect(fitViewSpy).toHaveBeenCalledWith(
      expect.objectContaining({ nodes: [{ id: "n1" }, { id: "n2" }] }),
    );
  });

  it("frames already-rendered targets immediately", () => {
    rf.renderedIds = ["n1"];
    const { result } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: makeProps() });
    fitViewSpy.mockClear();

    act(() => result.current.frameTargets(["n1"]));

    expect(followCalls("n1")).toBe(1);
  });

  it("a newer immediate frame cancels an older paint-deferred frame", () => {
    rf.renderedIds = ["n2"];
    const props = makeProps();
    const { result, rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    act(() => result.current.frameTargets(["n1"], true));
    act(() => result.current.frameTargets(["n2"]));
    expect(followCalls("n2")).toBe(1);

    rf.renderedIds = ["n1", "n2"];
    rerender({ ...props, paintEpoch: 1 });
    expect(followCalls("n1")).toBe(0);
  });

  it("user navigation cancels an older paint-deferred agent frame", () => {
    rf.renderedIds = ["n2"];
    const props = makeProps({ focus: "n2" });
    const { result, rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    act(() => result.current.frameTargets(["n1"], true));
    act(() => result.current.onNavigate("n2"));
    expect(followCalls("n2")).toBe(1);

    rf.renderedIds = ["n1", "n2"];
    rerender({ ...props, paintEpoch: 1 });
    expect(followCalls("n1")).toBe(0);
  });

  it("re-frames a focus that CHANGED while the tab was hidden, once it returns to visible", () => {
    rf.renderedIds = ["n1", "n2"];
    const props = makeProps({ focus: "n1" });
    const { rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    // Tab hidden, then an agent Point moves focus to n2 — fitView is rAF-throttled,
    // so nothing frames while hidden.
    setVisibility("hidden");
    rerender({ ...props, focus: "n2" });
    expect(followCalls("n2")).toBe(0);

    // Back to visible → the missed focus is framed exactly once.
    setVisibility("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(followCalls("n2")).toBe(1);
  });

  it("an io-PORT focus that changed while hidden re-frames its OWNER card on return", () => {
    rf.renderedIds = ["g1"];
    const props = makeProps({ focus: null, ioPorts: new Map([["p1", "g1"]]) });
    const { rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    setVisibility("hidden");
    rerender({ ...props, focus: "p1" });
    setVisibility("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(followCalls("g1")).toBe(1);
  });

  it("does NOT re-frame when focus changed while VISIBLE — an ordinary tab return leaves the viewport alone", () => {
    rf.renderedIds = ["n1", "n2"];
    const props = makeProps({ focus: "n1" });
    const { rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    rerender({ ...props, focus: "n2" }); // focus moved while visible → the normal follow owns it
    setVisibility("hidden");
    setVisibility("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(followCalls("n2")).toBe(0);
  });

  it("re-frames an EDGE focus that changed while hidden to its rendered endpoints", () => {
    rf.renderedIds = ["n1", "n2"];
    const graph = { nodes: [], edges: [{ id: "e0", source: "n1", target: "n2" }], groups: [] } as unknown as Args["graph"];
    const props = makeProps({ focus: null, graph });
    const { rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    setVisibility("hidden");
    rerender({ ...props, focus: "e0" }); // an agent edge Point while hidden
    setVisibility("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));

    expect(fitViewSpy).toHaveBeenCalledWith(expect.objectContaining({ nodes: [{ id: "n1" }, { id: "n2" }] }));
  });

  it("defers the hidden re-frame until the focused node paints (not-yet-rendered on return)", () => {
    rf.renderedIds = ["other"]; // n2 was revealed while hidden but hasn't painted yet
    const props = makeProps({ focus: "other" });
    const { rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    setVisibility("hidden");
    rerender({ ...props, focus: "n2" }); // pending = n2
    setVisibility("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(followCalls("n2")).toBe(0); // not rendered yet → not fit, pending kept (NOT cleared)

    rf.renderedIds = ["other", "n2"]; // the reveal paints
    rerender({ ...props, focus: "n2", paintEpoch: 1 }); // paintEpoch bump re-runs the re-frame
    expect(followCalls("n2")).toBe(1); // now it lands, exactly once
  });

  it("re-frames an edge endpoint to its rendered REPRESENTATIVE, not the raw (suppressed) flat id", () => {
    // The endpoint `member1` isn't rendered (its leaf box is suppressed); its io-wrapper
    // group `wrap1` is. The re-frame must resolve to the representative like the live path,
    // else an edge touching a sub-workflow/batch host fits the wrong subset (or nothing).
    rf.renderedIds = ["wrap1", "n2"];
    const graph = {
      nodes: [],
      edges: [{ id: "e0", source: "member1", target: "n2" }],
      groups: [{ id: "wrap1", kind: "input_wrapper", host: null, members: ["member1"], parent: null }],
    } as unknown as Args["graph"];
    const props = makeProps({ focus: null, graph });
    const { rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    setVisibility("hidden");
    rerender({ ...props, focus: "e0" });
    setVisibility("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));

    expect(fitViewSpy).toHaveBeenCalledWith(expect.objectContaining({ nodes: [{ id: "wrap1" }, { id: "n2" }] }));
  });

  it("drops a pending re-frame when focus is cleared while visible (no jump to a dismissed node)", () => {
    rf.renderedIds = ["other"]; // the focused node hasn't painted yet, so the re-frame stays pending
    const props = makeProps({ focus: "other" });
    const { rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    fitViewSpy.mockClear();

    setVisibility("hidden");
    rerender({ ...props, focus: "n2" }); // agent Point while hidden → pending = n2
    setVisibility("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(followCalls("n2")).toBe(0); // n2 not painted → pending kept

    rerender({ ...props, focus: null }); // user Clear Focus while visible → pending must clear
    rf.renderedIds = ["other", "n2"]; // n2 finally paints
    rerender({ ...props, focus: null, paintEpoch: 1 });
    expect(followCalls("n2")).toBe(0); // the dismissed node is NOT jumped to
  });

  it("fits the whole view once per workflow|direction|node key — focus restyles never refit; a direction flip does", () => {
    rf.renderedIds = ["n1"];
    const props = makeProps();
    const { rerender } = renderHook((p: Args) => useCameraNavigation(p), { initialProps: props });
    expect(fitViewSpy).toHaveBeenCalledTimes(1);

    rerender({ ...props, paintEpoch: 3, focus: "n1" }); // a click's restyle/paint
    expect(fitViewSpy).toHaveBeenCalledTimes(1);

    rerender({ ...props, direction: "TD" });
    expect(fitViewSpy).toHaveBeenCalledTimes(2);
  });
});
