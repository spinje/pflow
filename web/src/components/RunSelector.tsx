// Task 173 D6: the run selector — the Rail's reserved run-control slot (web/CLAUDE.md). Lists this
// workflow's runs (/api/runs?workflow=X) and PINS one for replay / live-watch via the &run= overlay, or
// follows the newest live run (unpinned, runId === null). Its OWN fetch + catch (DR-6): a runs-fetch
// failure shows an empty list, never breaks the rail.
import { useEffect, useRef, useState } from "react";

import { fetchRuns } from "../api/client";
import type { RunInfo } from "../types";

interface RunSelectorProps {
  workflow: string;
  runId: string | null; // the pinned run, or null = following the newest live run (unpinned)
  onSelect: (runId: string | null) => void;
}

// One run's status mark — composed from the RAW facts (DR-2), mirroring the node status palette
// (running blue · success green · failed red · degraded amber · cached/interrupted grey).
function runMark(run: RunInfo): { glyph: string; cls: string; label: string } {
  if (run.live) return { glyph: "●", cls: "run-live", label: "running" };
  if (!run.complete) return { glyph: "⊗", cls: "run-stale", label: "interrupted" };
  if (run.only_node) return { glyph: "⊘", cls: "run-degraded", label: `only: ${run.only_node}` };
  if (run.final_status === "success") return { glyph: "✓", cls: "run-success", label: "success" };
  if (run.final_status === "degraded") return { glyph: "⊘", cls: "run-degraded", label: "degraded" };
  if (run.final_status === "failed") return { glyph: "✗", cls: "run-failed", label: "failed" };
  return { glyph: "·", cls: "run-stale", label: run.final_status ?? "done" };
}

function shortTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function RunSelector({ workflow, runId, onSelect }: RunSelectorProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  // Fetch lazily on open (and refresh each open) so the list is current without polling.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetchRuns(workflow)
      .then((r) => {
        if (!cancelled) setRuns(r);
      })
      .catch(() => {
        if (!cancelled) setRuns([]); // DR-6: empty on failure; the rail stays alive
      });
    return () => {
      cancelled = true;
    };
  }, [open, workflow]);

  // A transient popover, not a panel: dismiss on an outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const pick = (next: string | null): void => {
    onSelect(next);
    setOpen(false);
  };

  return (
    <div className="run-selector" ref={ref}>
      <button
        className={"rail-button" + (runId ? " active" : "")}
        aria-label="Runs"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <svg
          width={18}
          height={18}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.7}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
        <span className="rail-tip">
          <span className="rail-tip-label">Runs</span>
          <span className="rail-tip-detail">{runId ? "viewing a pinned run" : "following newest"}</span>
        </span>
      </button>

      {open && (
        <div className="run-menu" role="menu">
          <button
            className={"run-menu-item" + (runId === null ? " selected" : "")}
            role="menuitem"
            onClick={() => pick(null)}
          >
            <span className="run-mark run-live">●</span>
            <span className="run-menu-label">Live — follow newest</span>
            {runId === null && <span className="run-menu-check">✓</span>}
          </button>
          {runs.length === 0 && <div className="run-menu-empty">No runs yet for this workflow.</div>}
          {runs.map((run) => {
            const mark = runMark(run);
            return (
              <button
                key={run.run_id}
                className={"run-menu-item" + (runId === run.run_id ? " selected" : "")}
                role="menuitem"
                onClick={() => pick(run.run_id)}
                title={run.run_id}
              >
                <span className={"run-mark " + mark.cls}>{mark.glyph}</span>
                <span className="run-menu-label">
                  {mark.label}
                  <span className="run-menu-time">{shortTime(run.start_time)}</span>
                </span>
                {runId === run.run_id && <span className="run-menu-check">✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
