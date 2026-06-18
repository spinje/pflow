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
});

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
