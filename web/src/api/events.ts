// Live interaction seam: SSE carries Point commands down to the Viewer while
// deliberate user interactions travel back as fire-and-forget JSON POSTs.

import type { InteractionReport, NodeStatus, PointTarget, RFRef, RunComplete, RunEvent } from "../types";

export interface PointHandlers {
  focus: (target: PointTarget) => void;
  frame: (target: PointTarget) => void;
  clear: () => void;
  // Task 175: the agent switches an already-open Viewer to a specific past run (the run id, not a graph
  // target). Applied by the frontend's existing selectRun (honors its re-pick guard); a stale id surfaces
  // the run-not-found path.
  selectRun: (runId: string) => void;
  // Task 174: the agent's narration — a persistent caption + optional audio clip anchored at the target.
  // The stamped point message precedes it on the same SSE queue and owns camera/selection; say only
  // annotates. OPTIONAL like the run handlers, so pre-existing PointHandlers literals stay valid (additive).
  say?: (target: PointTarget, caption: string, audioUrl: string | null) => void;
}

// Live execution overlay (Task 173) — optional run-event arms on the same vocabulary-agnostic
// envelope. A viewer that doesn't care about runs simply omits these; an old server that never
// sends run-* messages leaves them silent. The server tails the trace file; the viewer only renders.
export interface RunHandlers {
  runSnapshot: (nodes: RunEvent[], run: RunComplete | null, stopped: boolean, stale: boolean) => void; // catch-up; `stopped` = the run already died, `stale` = recorded against a different workflow version (both for late subscribe)
  runEvents: (events: RunEvent[]) => void; // a batched poll's node deltas
  runComplete: (run: RunComplete) => void; // the run banner
  runReset: () => void; // a newer run started (or the tailer switched files) — clear prior statuses
  runNotFound: () => void; // a pinned `&run=` id matched no trace (stale bookmark / rotated file) — DR-1
  runStopped: () => void; // an incomplete run's writer-lock went free (crash/kill) — flock death-detection
  runStale: () => void; // the pinned run was recorded against a different workflow version (Task 173 replay) — reaches the present subscriber, whose snapshot predates the latch
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

const RUN_STATUSES: ReadonlySet<string> = new Set<NodeStatus>(["running", "success", "cached", "failed"]);

function isRunEvent(value: unknown): value is RunEvent {
  return isRecord(value) && isRef(value.ref) && typeof value.status === "string" && RUN_STATUSES.has(value.status);
}

function asRunComplete(value: unknown): RunComplete | null {
  // Our own server's run.complete payload — accept any record (fields are all optional on RunComplete).
  return isRecord(value) ? (value as RunComplete) : null;
}

const RETRY_MS = 1000; // localhost single-user: a fixed beat beats exponential backoff's moving parts

/**
 * Subscribe one Viewer to Point + run-overlay commands. TWO separate concerns share the state below:
 *
 * - RECOVERY (unchanged): native EventSource auto-reconnect is unreliable for backgrounded/slept/frozen
 *   tabs (it may stay in CONNECTING and never re-register). On any `onerror` we explicitly drop the dead
 *   source and reopen after a fixed delay — trigger-agnostic, recovering from server restart, sleep/wake,
 *   network blip and tab freeze uniformly, without ever reading `readyState` or `visibilityState`.
 * - PRESENCE (Issue #539): a graph tab holds a persistent SSE and browsers cap ~6 connections per origin
 *   over HTTP/1.1, so several open tabs starve new ones. We CLOSE the source when the tab is hidden (freeing
 *   its slot) and reopen when it's shown. Only `open()`'s gate reads `visibilityState`; recovery stays
 *   visibility-agnostic. That single `open()` chokepoint (guarded on `source`/`stopped`/hidden) keeps at
 *   most one live EventSource and one pending reconnect across every hide/show/error interleave.
 *
 * A reopened (or brand-new) tab catches up: the server replays the run `snapshot()`, the latched Point, and
 * the latched run selection (`select-run`) — each epoch-deduped on its own baseline (re-based when the
 * server's `boot_id` changes on restart) so it adopts newer agent state without clobbering the user's own.
 */
// Issue #539 latch dedup: the highest epoch this browser session has applied per workflow and channel
// (`point` = focus/frame/clear; `run` = select-run — orthogonal state, so separate baselines), plus the
// server identity they count against. MODULE scope, not per-subscription (user-caught, Task 171 testing):
// GraphView re-subscribes on every run switch, and a per-subscription baseline made the server's latched
// select-run replay look new on each of those — a steered tab could then never manually switch runs (the
// replay re-applied the steer, reverting every pick, until a server restart). Keyed by workflow because
// ONE process-wide counter stamps every workflow's latches: a flat baseline would let workflow A's high
// epoch wrongly reject workflow B's older-but-unseen latched command after an SPA navigation.
const appliedByWorkflow = new Map<string, { point: number; run: number }>();
let serverBootId: string | null = null;

/** Test-only: clear the module-level epoch baselines (they deliberately survive re-subscribes). */
export function _resetEpochBaselines(): void {
  appliedByWorkflow.clear();
  serverBootId = null;
}

export function subscribe(
  workflow: string,
  handlers: PointHandlers & Partial<RunHandlers>,
  runId?: string | null,
): () => void {
  let source: EventSource | null = null;
  let connId: string | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  // This workflow's shared baseline object (created on first subscribe, then mutated in place so every
  // past and future subscription for the workflow reads/bumps the same state). A replayed latch with
  // epoch <= its channel's baseline is skipped — idempotent catch-up, no clobber.
  const applied = appliedByWorkflow.get(workflow) ?? { point: 0, run: 0 };
  appliedByWorkflow.set(workflow, applied);

  const reportVisibility = (): void => {
    if (connId === null) return;
    void fetch("/api/visibility", {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conn_id: connId, visibility: visibility() }),
    }).catch(() => undefined);
  };

  // True if a latched command on this channel should be applied — i.e. it is not a replay this Viewer has
  // already superseded — bumping the channel's baseline when it is. A missing/non-number epoch (old server,
  // or a direct test emit) always admits and never bumps. Callers gate this AFTER payload validation, so a
  // malformed message never bumps the baseline.
  const admitEpoch = (rawEpoch: unknown, channel: "point" | "run"): boolean => {
    const epoch = typeof rawEpoch === "number" ? rawEpoch : null;
    if (epoch !== null && epoch <= applied[channel]) return false;
    if (epoch !== null) applied[channel] = epoch;
    return true;
  };

  const dropSource = (): void => {
    // Null `source` so open()'s single-flight gate can reconnect; a closed EventSource never fires onerror
    // again (WHATWG), so no stale handler reaches a later source.
    source?.close();
    source = null;
    connId = null;
  };

  // Release the slot (hidden) or tear down for good (unsubscribe); also cancel any pending reconnect so a
  // hidden/torn-down tab can't reconnect behind our back.
  const close = (): void => {
    if (retry !== null) clearTimeout(retry);
    retry = null;
    dropSource();
  };

  const open = (): void => {
    // Single chokepoint: never a second live source, and never connect while hidden — so a queued reconnect
    // can't resurrect a backgrounded tab and a background-tab mount stays dormant until first shown. This is
    // the ONLY place connection PRESENCE reads visibility; RECOVERY (onerror below) stays trigger-agnostic.
    if (stopped || source !== null || visibility() === "hidden") return;
    const params = new URLSearchParams({ workflow, visibility: visibility() });
    if (runId) params.set("run", runId); // Task 173 DR-1: pin this Viewer to one run (replay / one of N)
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
        // A restarted server restarts its (process-wide) epoch counter at 1; reset EVERY workflow's
        // channel baselines when its `boot_id` changes so a reconnecting tab doesn't skip the new
        // process's lower-numbered commands. In place, never `clear()` — live subscriptions hold
        // references to their workflow's baseline object.
        if (typeof message.boot_id === "string" && message.boot_id !== serverBootId) {
          serverBootId = message.boot_id;
          for (const baseline of appliedByWorkflow.values()) {
            baseline.point = 0;
            baseline.run = 0;
          }
        }
        connId = message.conn_id;
        // A reconnect reopens with the original URL, whose visibility value may
        // now be stale. Correct every newly registered connection immediately;
        // do not wait for another visibility transition.
        reportVisibility();
      } else if (message.type === "clear") {
        if (admitEpoch(message.epoch, "point")) handlers.clear();
      } else if ((message.type === "focus" || message.type === "frame") && isTarget(message.target)) {
        if (admitEpoch(message.epoch, "point")) handlers[message.type](message.target);
      } else if (message.type === "say" && isTarget(message.target) && typeof message.caption === "string") {
        // Task 174: no admitEpoch gate — say is transient, never latched/replayed (the point message
        // that precedes it on the same queue carries the epoch and steers camera/selection).
        handlers.say?.(message.target, message.caption, typeof message.audio_url === "string" ? message.audio_url : null);
      } else if (message.type === "select-run" && typeof message.run === "string") {
        // Task 175: switch the open Viewer to the broadcast run id. Issue #539: latched + epoch-deduped on
        // its own channel, so the agent can steer a backgrounded/returning window, not just a live one.
        if (admitEpoch(message.epoch, "run")) handlers.selectRun(message.run);
      } else if (message.type === "run-events" && Array.isArray(message.events)) {
        handlers.runEvents?.(message.events.filter(isRunEvent));
      } else if (message.type === "run-snapshot" && Array.isArray(message.nodes)) {
        // `=== true` at this seam: an old server / unpinned snapshot that omits `stopped`/`stale_version`
        // yields `false`, not `undefined`, keeping the handler's boolean params strict (tsc).
        handlers.runSnapshot?.(
          message.nodes.filter(isRunEvent),
          asRunComplete(message.run),
          message.stopped === true,
          message.stale_version === true,
        );
      } else if (message.type === "run-complete") {
        const run = asRunComplete(message);
        if (run) handlers.runComplete?.(run);
      } else if (message.type === "run-reset") {
        handlers.runReset?.();
      } else if (message.type === "run-not-found") {
        handlers.runNotFound?.();
      } else if (message.type === "run-stopped") {
        handlers.runStopped?.();
      } else if (message.type === "run-stale") {
        handlers.runStale?.();
      }
    };

    source.onerror = (): void => {
      // Any drop (restart/sleep/blip/freeze). Tear down the dead source and reopen against the live server —
      // do NOT trust native retry, do NOT read readyState/visibilityState here. dropSource() nulls `source`
      // (else open()'s gate would deadlock reconnection); the `retry === null` guard + the wrapper (which
      // nulls `retry` before reopening) keep at most one reconnect pending, timed from the first drop.
      dropSource();
      if (!stopped && retry === null) {
        retry = setTimeout(() => {
          retry = null;
          open();
        }, RETRY_MS);
      }
    };
  };

  open(); // no-ops if the tab starts hidden — onVisibilityChange opens it when first shown
  // PRESENCE keys on visibility (close-on-hidden frees the 6-per-origin slot, reopen on show); RECOVERY
  // (onerror) never does.
  const onVisibilityChange = (): void => {
    if (visibility() === "hidden") close();
    else open();
  };
  document.addEventListener("visibilitychange", onVisibilityChange);

  return () => {
    stopped = true;
    document.removeEventListener("visibilitychange", onVisibilityChange);
    close();
  };
}

// Playback beacon (Task 174 pacing): tell the server what the audio element ACTUALLY did with a
// `say` clip — "started" re-anchors the pacing rendezvous to real playback, "blocked" flags an
// autoplay-refused (silent) window so the CLI's next --say warns the agent, "ended" frees the
// next --say from waiting. Fire-and-forget like reportInteraction; never awaited.
export function reportNarration(audioUrl: string, event: "started" | "blocked" | "ended"): void {
  const audioId = audioUrl.split("/").pop();
  if (!audioId) return;
  void fetch("/api/narration", {
    method: "POST",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_id: audioId, event }),
  }).catch(() => undefined);
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
