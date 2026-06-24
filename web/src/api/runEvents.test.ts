// @vitest-environment jsdom

// Live execution overlay (Task 173): the run-* SSE dispatch arms of subscribe().
// The envelope is vocabulary-agnostic — run handlers are OPTIONAL — so the guards
// must filter malformed events, route each type to the right handler, never throw
// on garbage, and leave the Point handlers working when an old server sends no run-*
// (back-compat). Mirrors events.test.ts's EventSource mock + message-injection.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { subscribe } from "./events";
import type { RFRef, RunEvent } from "../types";

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

  close(): void {
    this.closed = true;
  }
}

const ref: RFRef = { node_id: "greet", ancestor_path: [], port: null };
const runEvent: RunEvent = { id: 0, ref, status: "running" };

const runHandlers = () => ({
  focus: vi.fn(),
  frame: vi.fn(),
  clear: vi.fn(),
  runSnapshot: vi.fn(),
  runEvents: vi.fn(),
  runComplete: vi.fn(),
  runReset: vi.fn(),
});

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

afterEach(() => vi.unstubAllGlobals());

describe("subscribe — run-* dispatch arms", () => {
  it("run-events: dispatches ONLY the valid events (isRunEvent filters malformed)", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    const source = FakeEventSource.instances[0]!;

    source.emit({
      type: "run-events",
      events: [
        runEvent, // valid
        { id: 1, ref, status: "bogus" }, // bad status → filtered
        { id: 2, ref: { node_id: 4, ancestor_path: [], port: null }, status: "success" }, // bad ref → filtered
        { id: 3, status: "success" }, // missing ref → filtered
        "nonsense", // not even a record → filtered
      ],
    });

    expect(handlers.runEvents).toHaveBeenCalledOnce();
    expect(handlers.runEvents).toHaveBeenCalledWith([runEvent]);
  });

  it("run-snapshot: dispatches the filtered nodes AND the run trailer", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    const source = FakeEventSource.instances[0]!;
    const run = { final_status: "success", nodes_executed: 1 };

    source.emit({ type: "run-snapshot", nodes: [runEvent, { ref, status: "nope" }], run });

    expect(handlers.runSnapshot).toHaveBeenCalledOnce();
    expect(handlers.runSnapshot).toHaveBeenCalledWith([runEvent], run);
  });

  it("run-snapshot with no run field passes run=null (mid-run catch-up, no trailer yet)", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    FakeEventSource.instances[0]!.emit({ type: "run-snapshot", nodes: [runEvent] });

    expect(handlers.runSnapshot).toHaveBeenCalledWith([runEvent], null);
  });

  it("run-complete: dispatches the message itself as the RunComplete trailer", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    FakeEventSource.instances[0]!.emit({ type: "run-complete", final_status: "success", nodes_executed: 3 });

    expect(handlers.runComplete).toHaveBeenCalledOnce();
    expect(handlers.runComplete).toHaveBeenCalledWith(
      expect.objectContaining({ type: "run-complete", final_status: "success", nodes_executed: 3 }),
    );
  });

  it("run-reset: invokes runReset with no args", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    FakeEventSource.instances[0]!.emit({ type: "run-reset" });

    expect(handlers.runReset).toHaveBeenCalledOnce();
    expect(handlers.runReset).toHaveBeenCalledWith();
  });

  it("an UNKNOWN type does not throw and calls no handler", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    const source = FakeEventSource.instances[0]!;

    expect(() => source.emit({ type: "run-something-future" })).not.toThrow();
    for (const fn of Object.values(handlers)) expect(fn).not.toHaveBeenCalled();
  });

  it("a malformed run-events (events not an array) does not throw and calls no run handler", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    const source = FakeEventSource.instances[0]!;

    expect(() => source.emit({ type: "run-events", events: "oops" })).not.toThrow();
    expect(handlers.runEvents).not.toHaveBeenCalled();
  });

  it("an all-malformed run-events still dispatches (with an empty filtered list), never the wrong handler", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    FakeEventSource.instances[0]!.emit({ type: "run-events", events: [{ ref, status: "bogus" }] });

    expect(handlers.runEvents).toHaveBeenCalledWith([]);
    expect(handlers.runSnapshot).not.toHaveBeenCalled();
    expect(handlers.runComplete).not.toHaveBeenCalled();
  });

  it("back-compat: a focus message still dispatches when run handlers are present", () => {
    const handlers = runHandlers();
    subscribe("wf", handlers);
    FakeEventSource.instances[0]!.emit({ type: "focus", target: { kind: "node", ref } });

    expect(handlers.focus).toHaveBeenCalledOnce();
    expect(handlers.focus).toHaveBeenCalledWith({ kind: "node", ref });
    expect(handlers.runEvents).not.toHaveBeenCalled();
  });

  it("back-compat: run-* messages are silently ignored when no run handlers are supplied (Point-only viewer)", () => {
    const handlers = { focus: vi.fn(), frame: vi.fn(), clear: vi.fn() };
    subscribe("wf", handlers);
    const source = FakeEventSource.instances[0]!;

    expect(() => {
      source.emit({ type: "run-events", events: [runEvent] });
      source.emit({ type: "run-snapshot", nodes: [runEvent], run: null });
      source.emit({ type: "run-complete", final_status: "success" });
      source.emit({ type: "run-reset" });
    }).not.toThrow();
    // and the Point arm still works
    source.emit({ type: "clear" });
    expect(handlers.clear).toHaveBeenCalledOnce();
  });
});
