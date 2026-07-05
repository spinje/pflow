// The run-progress content (Task 175): a MINIATURE of the canvas spine — a vertical chain of small
// kind-colored tiles joined by gradient connectors, each muted grey while pending and gaining its node's
// identity color (the SAME `nodeColor` the canvas card uses) as it runs. No icons (too small at this
// scale). Pure presentational; fed by `runSteps` (the same runStatus map the canvas badges use), so it
// lights up live. Lives inside a NodeCallout anchored to the Inputs card.

import { fmtDuration, StatusBadge } from "./nodes/StatusBadge";
import { nodeColor } from "../utils/format";
import type { ProgressStep } from "../graph/flow";
import type { NodeStatus, RunComplete } from "../types";

// A non-banner terminal lifecycle: a run that ended WITHOUT a run.complete trailer — the process was
// killed mid-flight (`stopped`), or a pinned `?run=` resolved to no trace (`not-found`). Threaded from
// GraphView's run-lifecycle flags so the outcome line + badge RESOLVE instead of spinning a fake
// "Running…" forever (the canvas banner already handles these; the callout, a second consumer of the
// same state, must agree). `null` = live / still running.
export type RunOutcome = "stopped" | "not-found" | null;

// The overall-run status badge (the SAME round node badge used at a node's top-right): a spinner while
// running, ✓ on success, ! on failure. A completed run reads its banner; otherwise a terminal `outcome`
// (stopped/not-found) wins over the live spinner. final_status has no NodeStatus for "degraded"
// (succeeded-with-warnings) or "denied" (human's no at a gate, Task 125) — the closest badge for both
// is the amber "stopped"; the outcome TEXT carries the exact word.
function runBadgeStatus(banner: RunComplete | null, outcome: RunOutcome): NodeStatus {
  if (banner) {
    if (banner.final_status === "failed") return "failed";
    if (banner.final_status === "degraded") return "stopped";
    // Task 125: a human denied an approval gate — clean stop, not a failure. Amber like
    // degraded/stopped (the outcome text carries the word "denied"); the success ✓
    // fallthrough below must never render a human's "no" as green.
    if (banner.final_status === "denied") return "stopped";
    // Task 171: a durable gate pause — the run is waiting on a human's answer, not done.
    // Same amber treatment (the outcome text says "paused"); the success ✓ fallthrough
    // must never render a pending question as green.
    if (banner.final_status === "paused") return "stopped";
    return "success";
  }
  if (outcome === "stopped") return "stopped";
  if (outcome === "not-found") return "failed";
  return "running";
}

// Non-kind status colors for inline gradients: pending grey (no token), failed/stopped from the :root
// run-status palette — `var(--danger)`/`var(--status-stopped)` are :root (index.css), so they resolve
// inside the canvas portal AND can't drift from the CSS (single source). A running/success/cached tile
// wears its node's identity color (grey → color IS the progress).
const PENDING_COLOR = "#5b616b";
const FAILED_COLOR = "var(--danger)";
const STOPPED_COLOR = "var(--status-stopped)";

function stepColor(step: ProgressStep): string {
  if (step.status === "pending") return PENDING_COLOR;
  if (step.status === "failed") return FAILED_COLOR;
  if (step.status === "stopped") return STOPPED_COLOR;
  return nodeColor({ kind: step.kind, is_decision: step.isDecision, is_transform: step.isTransform });
}

// The right-hand meta per row: a duration once timed, else the status word (mirrors the terminal).
function stepMeta(step: ProgressStep): string {
  if ((step.status === "success" || step.status === "failed" || step.status === "cached") && step.durationMs != null) {
    return fmtDuration(step.durationMs);
  }
  switch (step.status) {
    case "running":
      return "running";
    case "cached":
      return "cached";
    case "success":
      return "done";
    case "failed":
      return "failed";
    case "stopped":
      return "stopped";
    default:
      return "pending";
  }
}

export function RunProgress({
  steps,
  banner,
  outcome = null,
  onSelectStep,
}: {
  steps: ProgressStep[];
  banner: RunComplete | null;
  // The non-banner terminal lifecycle (stopped / not-found); `null` = live/running. See RunOutcome.
  outcome?: RunOutcome;
  // Click a step name → scroll to + select that node on the canvas (the chip-navigate gesture). Optional
  // so the component renders plain (e.g. in unit tests) when not wired.
  onSelectStep?: (id: string) => void;
}): JSX.Element {
  const colors = steps.map(stepColor);
  return (
    <div className="run-progress">
      <ol className="run-spine">
        {steps.map((step, i) => {
          const color = colors[i]!;
          const below = i < steps.length - 1 ? colors[i + 1]! : null; // the next tile's color (connector OUT)
          return (
            <li key={step.id} className={`run-spine-step status-${step.status}`}>
              <span className="run-spine-rail">
                {/* ONE continuous connector per gap (this tile's center → the next tile's center), drawn
                    UNDER both tiles (tiles paint on top), so there's no seam in the middle and no gap where
                    it meets a tile — and one end-to-end gradient (no midpoint hack). */}
                {below ? (
                  <span className="run-spine-connector" style={{ background: `linear-gradient(180deg, ${color}, ${below})` }} />
                ) : null}
                {/* HOLLOW by default: colored border + OPAQUE dark interior (like the canvas node minus the
                    icon — NOT see-through, so the connector running under it is hidden inside the ring and
                    shows only in the gaps). The RUNNING tile fills its inside with a pulsing full-color core. */}
                <span className="run-spine-tile" style={{ borderColor: color }}>
                  {step.status === "running" && <span className="run-spine-tile-core" style={{ background: color }} />}
                </span>
              </span>
              {onSelectStep ? (
                <button
                  type="button"
                  className="run-spine-name run-spine-name-btn"
                  onClick={() => onSelectStep(step.id)}
                  title={`Go to ${step.name}`}
                >
                  {step.name}
                  {step.batchCount != null ? <span className="run-spine-batch"> ×{step.batchCount}</span> : null}
                </button>
              ) : (
                <span className="run-spine-name">
                  {step.name}
                  {step.batchCount != null ? <span className="run-spine-batch"> ×{step.batchCount}</span> : null}
                </span>
              )}
              <span className="run-spine-meta">{stepMeta(step)}</span>
            </li>
          );
        })}
      </ol>
      {/* The overall run status: the node-style round badge (✓/!/spinner) at the lower-left, beside the
          outcome word; the TOTAL run wall-clock on the right. A completed run reads its banner; a run that
          ended with NO banner (killed → stopped, or a stale ?run= → not-found) reads `outcome` so it never
          spins a fake "Running…" while the canvas banner says otherwise. */}
      <div
        className={`run-progress-outcome run-${banner?.final_status ?? (outcome === "not-found" ? "failed" : outcome) ?? "running"}`}
      >
        <span className="run-progress-outcome-label">
          <StatusBadge status={runBadgeStatus(banner, outcome)} inline />
          <span>
            {banner ? (
              <>
                Run {banner.final_status ?? "running"}
                {typeof banner.nodes_executed === "number" ? ` · ${banner.nodes_executed} nodes` : ""}
                {banner.nodes_failed ? ` · ${banner.nodes_failed} failed` : ""}
              </>
            ) : outcome === "stopped" ? (
              "Run stopped"
            ) : outcome === "not-found" ? (
              "Run not found"
            ) : (
              "Running…"
            )}
          </span>
        </span>
        {banner?.duration_ms != null ? <span className="run-progress-total">{fmtDuration(banner.duration_ms)}</span> : null}
      </div>
    </div>
  );
}
