// Live source watch: poll /api/version for the open workflow and fire onChange
// when its .pflow.md source files change on disk. This is the DETECTION half of
// live auto-update; the REACTION (re-fetch /api/graph and rebuild the canvas in
// place — no page reload) lives in useWorkflowGraph. They meet at one trigger,
// so when Task 169's SSE channel lands it can call the same onChange via a push
// instead of this poll, with nothing downstream changing.
//
// Design notes:
// - The first successful poll SEEDS the baseline and never fires onChange — only
//   a CHANGE from the baseline does.
// - Visibility-gated: a backgrounded tab doesn't poll; becoming visible polls
//   immediately so an edit made while hidden is picked up at once.
// - Resilient: a transient fetch failure is swallowed (the loop keeps running).
//   The server never errors /api/version for an invalid workflow, so a failure
//   here means the server is down/restarting, not that the workflow is broken.

import { useEffect, useRef } from "react";

import { fetchVersion } from "../api/client";

export const SOURCE_WATCH_POLL_MS = 1500;

export function useSourceWatch(workflow: string, enabled: boolean, onChange: () => void): void {
  // Hold the latest onChange in a ref so a new callback identity per render
  // doesn't tear down and re-seed the poll (which would lose the baseline).
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    // null = baseline not yet established; the first successful poll sets it.
    let last: string | null = null;
    // Skip a poll while one is already in flight, so overlapping/out-of-order
    // resolutions (a slow fetch, or the visibilitychange poll racing the
    // interval) can't write `last` out of order and fire a spurious reload.
    let inFlight = false;

    const poll = async (): Promise<void> => {
      if (document.hidden || inFlight) return; // skip backgrounded tabs + overlapping polls
      inFlight = true;
      try {
        const fingerprint = await fetchVersion(workflow);
        if (cancelled) return;
        if (last !== null && fingerprint !== last) {
          onChangeRef.current();
        }
        last = fingerprint;
      } catch {
        // transient (server restarting/down) — keep polling, never break
      } finally {
        inFlight = false;
      }
    };

    const onVisible = (): void => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(() => void poll(), SOURCE_WATCH_POLL_MS);
    void poll(); // seed the baseline now

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [workflow, enabled]);
}
