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

/** Subscribe one Viewer. EventSource reconnects automatically after transport failures. */
export function subscribe(workflow: string, handlers: PointHandlers): () => void {
  const params = new URLSearchParams({ workflow, visibility: visibility() });
  const source = new EventSource(`/api/events?${params.toString()}`);
  let connId: string | null = null;

  const reportVisibility = (): void => {
    if (connId === null) return;
    void fetch("/api/visibility", {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conn_id: connId, visibility: visibility() }),
    }).catch(() => undefined);
  };

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
      // EventSource reconnects with its original URL, whose visibility value
      // may now be stale. Correct every newly registered connection
      // immediately; do not wait for another visibility transition.
      reportVisibility();
    } else if (message.type === "clear") {
      handlers.clear();
    } else if ((message.type === "focus" || message.type === "frame") && isTarget(message.target)) {
      handlers[message.type](message.target);
    }
  };

  document.addEventListener("visibilitychange", reportVisibility);

  return () => {
    document.removeEventListener("visibilitychange", reportVisibility);
    source.close();
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
