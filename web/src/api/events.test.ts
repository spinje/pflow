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
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(message) }));
  }

  fail(): void {
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
