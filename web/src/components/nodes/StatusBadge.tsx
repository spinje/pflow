// The corner run-status badge (Task 173) — an n8n-style overlay at the node's top-right.
// It is the SINGLE per-node run-status surface: it replaced the status border ring (a green
// "done" border read as confusing) AND the ChipRail's formerly-reserved status-chip slot
// (so the rail is now behavior modifiers + the one count-expander button, nothing status).
// Color is set per status in CSS (`.status-badge.status-*`); the glyph is white
// (`currentColor`). Renders nothing for pending (absent status) so an idle canvas is untouched.
// HOVER detail: a custom chip (`.status-badge-tip`, styled like the rail's `.rail-tip` chrome chip) carries a
// friendly status verb + the run's duration/cost (from `detail`) — replaces the bare native `title` tooltip.
// The `aria-label` stays the stable "run status: <status>" (the essential a11y fact; the chip is aria-hidden).
import type { NodeStatus, RunDetail } from "../../types";

function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
}

function fmtCost(usd: number): string {
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

// The badge's hover text — a friendly verb, plus duration/cost where we have them (success/failed). The
// special states explain themselves (no metrics to show); `cached` reused a prior result.
export function runStatusLabel(status: NodeStatus, detail?: RunDetail): string {
  switch (status) {
    case "running":
      return "Running…";
    case "cached":
      return "Cached — reused a prior result";
    case "stopped":
      return "Stopped — the run's process exited before this node finished";
    case "unrecorded":
      return "No recorded state — recorded against a different version of the workflow";
    case "success":
    case "failed": {
      const parts = [status === "success" ? "Succeeded" : "Failed"];
      if (detail?.durationMs != null) parts.push(fmtDuration(detail.durationMs));
      if (detail?.costUsd != null && detail.costUsd > 0) parts.push(fmtCost(detail.costUsd));
      return parts.join(" · ");
    }
  }
}

// One shared check glyph for both success and cached (grey vs green is the differentiator).
const CHECK = (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 13l4 4 10-11" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const GLYPH: Record<NodeStatus, JSX.Element> = {
  // running — two arrows (CSS-rotated into a spin); the "show what's running" signal.
  running: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 11a8 8 0 0 0-13.7-4.2L4 9" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 5v4h4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 13a8 8 0 0 0 13.7 4.2L20 15" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M20 19v-4h-4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  success: CHECK,
  cached: CHECK,
  failed: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 6.5v7.5" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="12" cy="17.6" r="1.45" fill="currentColor" />
    </svg>
  ),
  // stopped — the run's process died while this node was still running (flock liveness).
  stopped: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="7" y="7" width="10" height="10" rx="2.2" fill="currentColor" />
    </svg>
  ),
  // unrecorded — a stale replay has no recorded state for this node (renamed/new since, or an untaken
  // branch in that version). A dashed dash: "no data for this version", muted so it never reads as a status.
  unrecorded: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeDasharray="3.5 3.5" />
    </svg>
  ),
};

export function StatusBadge({ status, detail }: { status?: NodeStatus; detail?: RunDetail }): JSX.Element | null {
  if (!status) return null; // pending = absent = no badge
  return (
    <span className={`status-badge status-${status}`} role="img" aria-label={`run status: ${status}`}>
      {GLYPH[status]}
      {/* Custom hover chip (mirrors the rail's `.rail-tip`) — the run-status + duration/cost detail in the
          canvas chrome style, not the bare OS `title` tooltip. aria-hidden: the status is on aria-label. */}
      <span className="status-badge-tip" aria-hidden="true">
        {runStatusLabel(status, detail)}
      </span>
    </span>
  );
}
