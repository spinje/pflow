// The run-progress content (Task 175): a MINIATURE of the canvas spine — a vertical chain of small
// kind-colored tiles joined by gradient connectors, each muted grey while pending and gaining its node's
// identity color (the SAME `nodeColor` the canvas card uses) as it runs. No icons (too small at this
// scale). Pure presentational; fed by `runSteps` (the same runStatus map the canvas badges use), so it
// lights up live. Lives inside a NodeCallout anchored to the Inputs card.

import { fmtDuration, StatusBadge } from "./nodes/StatusBadge";
import { nodeColor } from "../utils/format";
import type { ProgressStep } from "../graph/flow";
import type { NodeStatus, RunComplete } from "../types";

// The overall-run status badge (the SAME round node badge used at a node's top-right): a spinner while
// running, ✓ on success, ! on failure. final_status has no NodeStatus for "degraded" (succeeded-with-
// warnings) — the closest badge is the amber "stopped"; the outcome TEXT carries the precise word.
function runBadgeStatus(banner: RunComplete | null): NodeStatus {
  if (!banner) return "running";
  if (banner.final_status === "failed") return "failed";
  if (banner.final_status === "degraded") return "stopped";
  return "success";
}

// Non-kind status colors (literals, for inline gradients): pending grey, failed/stopped overrides. A
// running/success/cached/unrecorded tile wears its node's identity color (grey → color IS the progress).
const PENDING_COLOR = "#5b616b";
const FAILED_COLOR = "#ff6b6b"; // = --danger
const STOPPED_COLOR = "#d29922"; // = --status-stopped

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
  onSelectStep,
}: {
  steps: ProgressStep[];
  banner: RunComplete | null;
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
          outcome word; the TOTAL run wall-clock on the right. One unified line for the running + done states. */}
      <div className={`run-progress-outcome run-${banner?.final_status ?? "running"}`}>
        <span className="run-progress-outcome-label">
          <StatusBadge status={runBadgeStatus(banner)} inline />
          <span>
            {banner ? (
              <>
                Run {banner.final_status ?? "running"}
                {typeof banner.nodes_executed === "number" ? ` · ${banner.nodes_executed} nodes` : ""}
                {banner.nodes_failed ? ` · ${banner.nodes_failed} failed` : ""}
              </>
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
