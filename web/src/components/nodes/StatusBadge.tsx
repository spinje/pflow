// The corner run-status badge (Task 173) — an n8n-style overlay at the node's top-right.
// It is the SINGLE per-node run-status surface: it replaced the status border ring (a green
// "done" border read as confusing) AND the ChipRail's formerly-reserved status-chip slot
// (so the rail is now behavior modifiers + the one count-expander button, nothing status).
// Color is set per status in CSS (`.status-badge.status-*`); the glyph is white
// (`currentColor`). Renders nothing for pending (absent status) so an idle canvas is untouched.
import type { NodeStatus } from "../../types";

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
};

export function StatusBadge({ status }: { status?: NodeStatus }): JSX.Element | null {
  if (!status) return null; // pending = absent = no badge
  return (
    <span className={`status-badge status-${status}`} role="img" aria-label={`run status: ${status}`} title={`run status: ${status}`}>
      {GLYPH[status]}
    </span>
  );
}
