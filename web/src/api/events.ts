// Live interaction seam: SSE carries Point commands down to the Viewer while
// deliberate user interactions travel back as fire-and-forget JSON POSTs.

import type { InteractionReport, PointTarget, RFRef } from "../types";

export interface PointHandlers {
  focus: (target: PointTarget) => void;
  frame: (target: PointTarget) => void;
  clear: () => void;
}

const visibility = (): "visible" | "hidden" => (document.visibilityState === "visible" ? "visible" : "hidden");

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isRef(value: unknown): value is RFRef {
  if (!isRecord(value) || typeof value.node_id !== "string" || !Array.isArray(value.ancestor_path)) return false;
  if (value.port !== null && value.port !== "in" && value.port !== "out") return false;
  return value.ancestor_path.every(
    (step) =>
      isRecord(step) &&
      typeof step.node_id === "string" &&
      (step.batch_index === null || typeof step.batch_index === "number"),
  );
}

function isTarget(value: unknown): value is PointTarget {
  if (!isRecord(value)) return false;
  if (value.kind === "node") return isRef(value.ref);
  return (
    value.kind === "edge" &&
    isRef(value.source) &&
    (value.source_field === null || typeof value.source_field === "string") &&
    Array.isArray(value.source_path) &&
    value.source_path.every((part) => typeof part === "string") &&
    isRef(value.target) &&
    (value.input_name === null || typeof value.input_name === "string")
  );
}

const RETRY_MS = 1000; // localhost single-user: a fixed beat beats exponential backoff's moving parts

/**
 * Subscribe one Viewer to Point commands. Drives its OWN reconnect on drop —
 * native EventSource auto-reconnect is unreliable for backgrounded/slept/frozen
 * tabs (it may stay in CONNECTING and never re-register). On any `onerror` we
 * explicitly close the dead source and reopen a fresh one after a fixed delay,
 * trigger-agnostic: recovers from server restart, sleep/wake, network blip, and
 * tab freeze uniformly, without ever reading `readyState` or `visibilityState`.
 */
export function subscribe(workflow: string, handlers: PointHandlers): () => void {
  let source: EventSource | null = null;
  let connId: string | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const reportVisibility = (): void => {
    if (connId === null) return;
    void fetch("/api/visibility", {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conn_id: connId, visibility: visibility() }),
    }).catch(() => undefined);
  };

  const connect = (): void => {
    if (stopped) return; // defensive: a fired-but-not-yet-cleared timer must not resurrect a connection
    const params = new URLSearchParams({ workflow, visibility: visibility() });
    source = new EventSource(`/api/events?${params.toString()}`);

    source.onmessage = (event: MessageEvent<string>): void => {
      let message: unknown;
      try {
        message = JSON.parse(event.data) as unknown;
      } catch {
        return;
      }
      if (!isRecord(message) || typeof message.type !== "string") return;
      if (message.type === "connected" && typeof message.conn_id === "string") {
        connId = message.conn_id;
        // A reconnect reopens with the original URL, whose visibility value may
        // now be stale. Correct every newly registered connection immediately;
        // do not wait for another visibility transition.
        reportVisibility();
      } else if (message.type === "clear") {
        handlers.clear();
      } else if ((message.type === "focus" || message.type === "frame") && isTarget(message.target)) {
        handlers[message.type](message.target);
      }
    };

    source.onerror = (): void => {
      // Any drop (restart/sleep/blip/freeze). Tear down the dead source and reopen
      // against the live server — do NOT trust native retry, do NOT read readyState.
      // The single-flight guard (retry === null) + close-before-schedule mean at most
      // one reconnect is ever pending and at most one EventSource is ever live.
      source?.close();
      connId = null;
      if (!stopped && retry === null) {
        retry = setTimeout(() => {
          retry = null;
          connect();
        }, RETRY_MS);
      }
    };
  };

  connect();
  // visibilitychange reports visible/hidden ONLY; it never drives reconnection.
  document.addEventListener("visibilitychange", reportVisibility);

  return () => {
    stopped = true;
    if (retry !== null) clearTimeout(retry);
    document.removeEventListener("visibilitychange", reportVisibility);
    source?.close();
    connId = null;
  };
}

/** Report user intent without ever surfacing a transport failure into the UI. */
export function reportInteraction(workflow: string, report: InteractionReport): void {
  void fetch("/api/interaction", {
    method: "POST",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow, ...report }),
  }).catch(() => undefined);
}
