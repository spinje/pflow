// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reportInteraction, subscribe } from "./events";
import type { RFRef } from "../types";

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  emit(message: unknown): void {
    if (this.closed) return; // WHATWG: a closed source dispatches no further events
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(message) }));
  }

  fail(): void {
    // WHATWG: once close() sets readyState=CLOSED, a source never re-fires onerror. The subscribe()
    // single-flight safety leans on this (a stale handler can't reach a later source), so the double
    // must honor it — else the hide/show tests would exercise a browser-impossible interleaving.
    if (this.closed) return;
    this.onerror?.(new Event("error"));
  }

  close(): void {
    this.closed = true;
  }
}

const ref: RFRef = { node_id: "greet", ancestor_path: [], port: null };

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
  // Reset visibility every test: a later test flips it to "hidden" and does not
  // restore it, which would otherwise leak into whatever test runs next.
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

afterEach(() => vi.unstubAllGlobals());

describe("subscribe", () => {
  it("validates and dispatches connected/focus/frame/clear messages", () => {
    const handlers = { focus: vi.fn(), frame: vi.fn(), clear: vi.fn(), selectRun: vi.fn() };
    const unsubscribe = subscribe("folder/wf.pflow.md", handlers);
    const source = FakeEventSource.instances[0]!;
    expect(source.url).toContain("workflow=folder%2Fwf.pflow.md");

    source.emit({ type: "focus", target: { kind: "node", ref } });
    source.emit({ type: "frame", target: { kind: "node", ref } });
    source.emit({ type: "clear" });
    source.emit({
      type: "focus",
      target: {
        kind: "edge",
        source: ref,
        source_field: "result",
        source_path: ["ok"],
        target: { ...ref, node_id: "use" },
        input_name: "value",
      },
    });
    source.emit({ type: "focus", target: { kind: "node", ref: { node_id: 4 } } });
    source.emit({ type: "focus", target: { kind: "edge", source: ref, source_path: [4], target: ref } });

    expect(handlers.focus).toHaveBeenCalledTimes(2);
    expect(handlers.frame).toHaveBeenCalledOnce();
    expect(handlers.clear).toHaveBeenCalledOnce();
    unsubscribe();
    expect(source.closed).toBe(true);
  });

  it("dispatches select-run with the run id, ignoring a missing/non-string run (Task 175)", () => {
    const handlers = { focus: vi.fn(), frame: vi.fn(), clear: vi.fn(), selectRun: vi.fn() };
    const unsubscribe = subscribe("wf", handlers);
    const source = FakeEventSource.instances[0]!;

    source.emit({ type: "select-run", run: "run-abc" });
    source.emit({ type: "select-run" }); // no run → ignored
    source.emit({ type: "select-run", run: 42 }); // non-string run → ignored

    expect(handlers.selectRun).toHaveBeenCalledTimes(1);
    expect(handlers.selectRun).toHaveBeenCalledWith("run-abc");
    unsubscribe();
  });

  it("reports current visibility for every server-supplied connection id", async () => {
    const handlers = { focus: vi.fn(), frame: vi.fn(), clear: vi.fn(), selectRun: vi.fn() };
    const unsubscribe = subscribe("wf", handlers);
    const source = FakeEventSource.instances[0]!;

    document.dispatchEvent(new Event("visibilitychange"));
    expect(fetch).not.toHaveBeenCalled();
    source.emit({ type: "connected", conn_id: "viewer-7" });

    expect(fetch).toHaveBeenCalledWith(
      "/api/visibility",
      expect.objectContaining({
        method: "POST",
        keepalive: true,
        body: JSON.stringify({ conn_id: "viewer-7", visibility: "visible" }),
      }),
    );

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    source.emit({ type: "connected", conn_id: "viewer-8" });
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/visibility",
      expect.objectContaining({
        body: JSON.stringify({ conn_id: "viewer-8", visibility: "hidden" }),
      }),
    );
    unsubscribe();
  });
});

describe("subscribe reconnect", () => {
  // The logic test (necessary, NOT sufficient — a jsdom FakeEventSource can't prove a
  // real backgrounded/slept tab recovers; that's the real-browser harness's job).
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const handlers = () => ({ focus: vi.fn(), frame: vi.fn(), clear: vi.fn(), selectRun: vi.fn() });

  it("closes the dead source and reopens a fresh one after the retry delay", () => {
    const unsubscribe = subscribe("wf", handlers());
    const first = FakeEventSource.instances[0]!;

    first.fail();
    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1); // not yet — reconnect is scheduled, not immediate

    vi.advanceTimersByTime(1000);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1]!.url).toContain("workflow=wf");
    unsubscribe();
  });

  it("schedules at most one reconnect for repeated errors before the timer fires (churn guard)", () => {
    const unsubscribe = subscribe("wf", handlers());
    const first = FakeEventSource.instances[0]!;

    first.fail();
    first.fail();
    first.fail();
    vi.advanceTimersByTime(1000);

    expect(FakeEventSource.instances).toHaveLength(2); // exactly one new source, not three
    unsubscribe();
  });

  it("re-seeds the connection id and reports visibility after a reconnect", () => {
    const unsubscribe = subscribe("wf", handlers());
    FakeEventSource.instances[0]!.fail();
    vi.advanceTimersByTime(1000);

    FakeEventSource.instances[1]!.emit({ type: "connected", conn_id: "viewer-9" });
    // The reconnected source's `connected` re-seeds connId, so the visibility POST
    // targets the NEW id (not the dead pre-reconnect connection).
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/visibility",
      expect.objectContaining({ body: JSON.stringify({ conn_id: "viewer-9", visibility: "visible" }) }),
    );
    unsubscribe();
  });

  it("cancels a pending reconnect on unsubscribe and never reconnects after teardown", () => {
    const unsubscribe = subscribe("wf", handlers());
    const first = FakeEventSource.instances[0]!;

    first.fail(); // schedules a retry
    unsubscribe(); // must clear it
    vi.advanceTimersByTime(5000);
    expect(FakeEventSource.instances).toHaveLength(1);

    first.fail(); // an error after teardown must not resurrect a connection
    vi.advanceTimersByTime(5000);
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});

describe("subscribe visibility presence (#539)", () => {
  // Close the SSE when hidden (freeing one of the browser's 6-per-origin slots) and reopen on visible.
  const handlers = () => ({ focus: vi.fn(), frame: vi.fn(), clear: vi.fn(), selectRun: vi.fn() });
  const setVisibility = (value: "visible" | "hidden"): void => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value });
    document.dispatchEvent(new Event("visibilitychange"));
  };
  const live = (): FakeEventSource[] => FakeEventSource.instances.filter((s) => !s.closed);

  it("stays dormant when the tab starts hidden, and opens on first show", () => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    const unsubscribe = subscribe("wf", handlers());
    expect(FakeEventSource.instances).toHaveLength(0); // a background-tab mount holds no slot

    setVisibility("visible");
    expect(live()).toHaveLength(1);
    unsubscribe();
  });

  it("closes the source on hidden and reopens a fresh one on visible", () => {
    const unsubscribe = subscribe("wf", handlers());
    const first = FakeEventSource.instances[0]!;

    setVisibility("hidden");
    expect(first.closed).toBe(true); // slot released
    expect(live()).toHaveLength(0);

    setVisibility("visible");
    expect(live()).toHaveLength(1); // reopened
    expect(FakeEventSource.instances).toHaveLength(2);
    unsubscribe();
  });

  it("keeps exactly one live source across rapid hide/show (no duplicates)", () => {
    const unsubscribe = subscribe("wf", handlers());
    setVisibility("hidden");
    setVisibility("visible");
    setVisibility("hidden");
    setVisibility("visible");
    expect(live()).toHaveLength(1);
    unsubscribe();
  });

  it("cancels a pending onerror-reconnect when hidden, and reopens cleanly on show", () => {
    vi.useFakeTimers();
    const unsubscribe = subscribe("wf", handlers());
    FakeEventSource.instances[0]!.fail(); // schedules a reconnect timer
    setVisibility("hidden"); // must cancel it — a hidden tab must not reconnect behind our back
    expect(vi.getTimerCount()).toBe(0); // close() cleared the pending retry (not merely gated by open())
    vi.advanceTimersByTime(5000);
    expect(live()).toHaveLength(0);

    setVisibility("visible");
    expect(live()).toHaveLength(1);
    unsubscribe();
    vi.useRealTimers();
  });
});

describe("subscribe point epoch dedup (#539)", () => {
  // The latch replay is idempotent: a point applies only if strictly newer than the last one shown, so a
  // returning tab catches up to a newer highlight without re-applying (clobbering) what it already has.
  const handlers = () => ({ focus: vi.fn(), frame: vi.fn(), clear: vi.fn(), selectRun: vi.fn() });
  const focus = (epoch?: number) => ({ type: "focus", target: { kind: "node", ref }, ...(epoch !== undefined ? { epoch } : {}) });

  it("applies a point only when its epoch is newer than the last applied", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    source.emit(focus(3)); // 3 > 0 → applied
    source.emit(focus(2)); // stale → skipped
    source.emit(focus(3)); // already applied → skipped
    source.emit(focus(4)); // newer → applied

    expect(h.focus).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("does not re-apply an already-shown latch after a reopen, but catches up to a newer one", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const first = FakeEventSource.instances[0]!;
    first.emit({ type: "connected", conn_id: "v1", boot_id: "boot-A" });
    first.emit(focus(5));
    expect(h.focus).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
    const reopened = FakeEventSource.instances[1]!;
    reopened.emit({ type: "connected", conn_id: "v2", boot_id: "boot-A" }); // SAME server → no baseline reset

    reopened.emit(focus(5)); // the replayed latch it already showed → skipped
    expect(h.focus).toHaveBeenCalledTimes(1);
    reopened.emit(focus(6)); // a point issued while hidden → applied
    expect(h.focus).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("resets the epoch baseline when the server boot_id changes (restart-fence)", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;
    source.emit({ type: "connected", conn_id: "v1", boot_id: "boot-A" });
    source.emit(focus(10));
    expect(h.focus).toHaveBeenCalledTimes(1);

    // Reconnect to a RESTARTED server: new boot_id, and its epoch counter has restarted low.
    source.emit({ type: "connected", conn_id: "v2", boot_id: "boot-B" });
    source.emit(focus(1)); // would be stale vs 10, but the boot_id changed → baseline reset → applied
    expect(h.focus).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("applies a point with no epoch (old server / back-compat) without bumping the baseline", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    source.emit(focus(7)); // baseline → 7
    source.emit(focus()); // no epoch → always applies, does NOT bump the baseline
    source.emit(focus(7)); // still <= 7 → skipped (the epoch-less emit didn't move the baseline)

    expect(h.focus).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("dedups select-run on its own channel (newer steer applies, stale/duplicate skipped)", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    source.emit({ type: "select-run", run: "r1", epoch: 2 }); // applied
    source.emit({ type: "select-run", run: "r0", epoch: 1 }); // stale → skipped
    source.emit({ type: "select-run", run: "r1", epoch: 2 }); // duplicate (replayed latch) → skipped
    source.emit({ type: "select-run", run: "r2", epoch: 3 }); // newer steer → applied

    expect(h.selectRun.mock.calls.map((c) => c[0])).toEqual(["r1", "r2"]);
    unsubscribe();
  });

  it("keeps the point and run dedup baselines independent", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    source.emit(focus(5)); // point channel → 5
    source.emit({ type: "select-run", run: "r1", epoch: 3 }); // run channel: 3 > 0 → applied, NOT skipped
    expect(h.focus).toHaveBeenCalledTimes(1);
    expect(h.selectRun).toHaveBeenCalledTimes(1); // a lower run epoch isn't gated by the higher point epoch
    unsubscribe();
  });
});

describe("subscribe say dispatch (Task 174)", () => {
  // `say` is OPTIONAL on PointHandlers (additive, like the run handlers) — the pre-existing literals
  // above compile untouched; only these tests carry a say mock.
  const handlers = () => ({ focus: vi.fn(), frame: vi.fn(), clear: vi.fn(), selectRun: vi.fn(), say: vi.fn() });

  it("dispatches say with target, caption and audio url", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    source.emit({ type: "say", target: { kind: "node", ref }, caption: "hi", audio_url: "/api/audio/x" });

    expect(h.say).toHaveBeenCalledExactlyOnceWith({ kind: "node", ref }, "hi", "/api/audio/x");
    unsubscribe();
  });

  it("passes a null audio url when audio_url is absent or non-string (caption-only say)", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    source.emit({ type: "say", target: { kind: "node", ref }, caption: "quiet" });
    source.emit({ type: "say", target: { kind: "node", ref }, caption: "garbled", audio_url: 42 });

    expect(h.say.mock.calls.map((c) => c[2])).toEqual([null, null]);
    unsubscribe();
  });

  it("ignores a say with a malformed target or a missing/non-string caption", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    source.emit({ type: "say", target: { kind: "node", ref: { node_id: 4 } }, caption: "bad ref" });
    source.emit({ type: "say", target: { kind: "node", ref } }); // no caption
    source.emit({ type: "say", target: { kind: "node", ref }, caption: 7 });

    expect(h.say).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("is transient — not epoch-gated: a say always dispatches and never bumps the point baseline", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    source.emit({ type: "focus", target: { kind: "node", ref }, epoch: 5 }); // point baseline → 5
    source.emit({ type: "say", target: { kind: "node", ref }, caption: "one" });
    source.emit({ type: "say", target: { kind: "node", ref }, caption: "one" }); // repeats are not deduped
    source.emit({ type: "focus", target: { kind: "node", ref }, epoch: 6 }); // still admitted after says

    expect(h.say).toHaveBeenCalledTimes(2);
    expect(h.focus).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("dispatches an edge-target say (isTarget validates edge descriptors too)", () => {
    const h = handlers();
    const unsubscribe = subscribe("wf", h);
    const target = {
      kind: "edge",
      source: ref,
      source_field: "result",
      source_path: ["ok"],
      target: { ...ref, node_id: "use" },
      input_name: "value",
    };

    FakeEventSource.instances[0]!.emit({ type: "say", target, caption: "this wire", audio_url: "/api/audio/y" });

    expect(h.say).toHaveBeenCalledExactlyOnceWith(target, "this wire", "/api/audio/y");
    unsubscribe();
  });

  it("is silently ignored by a Viewer without a say handler (old frontend / Point-only literal)", () => {
    const h = { focus: vi.fn(), frame: vi.fn(), clear: vi.fn(), selectRun: vi.fn() };
    const unsubscribe = subscribe("wf", h);
    const source = FakeEventSource.instances[0]!;

    expect(() => source.emit({ type: "say", target: { kind: "node", ref }, caption: "hi" })).not.toThrow();
    // and the Point arm still works
    source.emit({ type: "clear" });
    expect(h.clear).toHaveBeenCalledOnce();
    unsubscribe();
  });
});

describe("reportInteraction", () => {
  it("posts JSON with keepalive and swallows transport rejection", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("offline"));

    expect(() =>
      reportInteraction("wf", {
        type: "node_click",
        target: { kind: "node", flat_id: "n3", ref: { ...ref } },
        view_state: { density: "beautiful", direction: "LR", focus: "greet" },
      }),
    ).not.toThrow();
    await Promise.resolve();

    expect(fetch).toHaveBeenCalledWith(
      "/api/interaction",
      expect.objectContaining({ method: "POST", keepalive: true, headers: { "Content-Type": "application/json" } }),
    );
  });
});
