// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reportInteraction, subscribe } from "./events";
import type { RFRef } from "../types";

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  closed = false;

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  emit(message: unknown): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(message) }));
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
});

afterEach(() => vi.unstubAllGlobals());

describe("subscribe", () => {
  it("validates and dispatches connected/focus/frame/clear messages", () => {
    const handlers = { focus: vi.fn(), frame: vi.fn(), clear: vi.fn() };
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

  it("reports current visibility for every server-supplied connection id", async () => {
    const handlers = { focus: vi.fn(), frame: vi.fn(), clear: vi.fn() };
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
