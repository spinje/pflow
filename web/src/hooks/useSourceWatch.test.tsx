// @vitest-environment jsdom
//
// The live-source-watch poll: it SEEDS a baseline on the first poll and fires
// onChange only on a CHANGE, is visibility-gated, swallows transient errors, and
// stops on unmount / when disabled. Detection only — the in-place reaction (the
// re-fetch + rebuild) lives in useWorkflowGraph and is pinned in its own test.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

vi.mock("../api/client", () => ({ fetchVersion: vi.fn() }));

import { fetchVersion } from "../api/client";
import { SOURCE_WATCH_POLL_MS, useSourceWatch } from "./useSourceWatch";

const mockedFetchVersion = vi.mocked(fetchVersion);

function setHidden(hidden: boolean): void {
  Object.defineProperty(document, "hidden", { value: hidden, writable: true, configurable: true });
}

// Flush the in-flight poll's microtasks (fetchVersion resolution) without
// advancing the interval clock.
const flush = (): Promise<void> => act(async () => { await vi.advanceTimersByTimeAsync(0); });
// Advance one poll interval AND flush the poll it fires.
const tick = (): Promise<void> => act(async () => { await vi.advanceTimersByTimeAsync(SOURCE_WATCH_POLL_MS); });

beforeEach(() => {
  vi.useFakeTimers();
  setHidden(false);
  mockedFetchVersion.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useSourceWatch", () => {
  it("seeds a baseline on the first poll, then fires onChange only on a CHANGE", async () => {
    mockedFetchVersion.mockResolvedValue("v1");
    const onChange = vi.fn();
    renderHook(() => useSourceWatch("wf", true, onChange));

    await flush(); // the seed poll resolves
    expect(mockedFetchVersion).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled(); // baseline, not a change

    await tick(); // same fingerprint → no fire
    expect(onChange).not.toHaveBeenCalled();

    mockedFetchVersion.mockResolvedValue("v2");
    await tick(); // changed → fire once
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("does not poll at all when disabled (pflow ui --no-watch)", async () => {
    mockedFetchVersion.mockResolvedValue("v1");
    const onChange = vi.fn();
    renderHook(() => useSourceWatch("wf", false, onChange));
    await flush();
    await tick();
    expect(mockedFetchVersion).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("skips polling while the tab is hidden, and polls immediately when it becomes visible", async () => {
    mockedFetchVersion.mockResolvedValue("v1");
    const onChange = vi.fn();
    setHidden(true);
    renderHook(() => useSourceWatch("wf", true, onChange));
    await flush();
    await tick();
    expect(mockedFetchVersion).not.toHaveBeenCalled(); // hidden → no baseline yet

    setHidden(false);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockedFetchVersion).toHaveBeenCalled(); // visible → immediate poll
  });

  it("swallows a transient fetch error and keeps polling", async () => {
    mockedFetchVersion.mockResolvedValue("v1");
    const onChange = vi.fn();
    renderHook(() => useSourceWatch("wf", true, onChange));
    await flush(); // baseline v1

    mockedFetchVersion.mockRejectedValueOnce(new Error("server restarting"));
    await tick(); // rejects → swallowed, baseline unchanged, loop survives
    expect(onChange).not.toHaveBeenCalled();

    mockedFetchVersion.mockResolvedValue("v2");
    await tick(); // recovers and detects the change
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("stops polling after unmount", async () => {
    mockedFetchVersion.mockResolvedValue("v1");
    const onChange = vi.fn();
    const { unmount } = renderHook(() => useSourceWatch("wf", true, onChange));
    await flush();
    const before = mockedFetchVersion.mock.calls.length;
    unmount();
    await tick();
    expect(mockedFetchVersion.mock.calls.length).toBe(before);
  });
});
