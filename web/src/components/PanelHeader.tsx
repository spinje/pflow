// The shared header for the SINGLE-SUBJECT side panels — ReadPanel (a node,
// including a sub-workflow/container HOST node) and IoPanel (the workflow's IO
// interface card). It leads with a large node AVATAR (the canvas tile: a
// kind-colored border + the native-color icon) beside a category eyebrow and
// the subject's name rendered as a NAVIGATE button: clicking re-centers the
// camera on the subject — the Chip's navigate-without-opening gesture
// (components/Chip.tsx), just LARGER (the tile + name outscale the
// references/referenced-by chips below). EdgePanel keeps its own connection
// header (two endpoint chips): an edge has no single subject to avatar.
//
// The name stays the panel's <h2> heading; the navigate affordance is an inner
// <button> (valid: a button is phrasing content inside a heading), so the panel
// keeps its heading semantics while the name becomes clickable.

import type { CSSProperties } from "react";

export function PanelHeader({
  icon,
  color,
  eyebrow,
  eyebrowColor,
  name,
  onNavigate,
  onClose,
}: {
  // The avatar tile's icon URL (iconFor / ioCardIcon) and its kind color (the
  // canvas's --chip-c, driving the tile border — matches the node on canvas).
  icon: string;
  color: string;
  // The category line above the name (the file-mappable kind, or "workflow
  // inputs"); eyebrowColor tints it (IoPanel uses IO_COLOR).
  eyebrow: string;
  eyebrowColor?: string;
  name: string;
  // Absent → the name renders as plain text (no rendered canvas target to focus).
  onNavigate?: () => void;
  onClose: () => void;
}): JSX.Element {
  return (
    <header className="read-panel-header">
      <div className="panel-head" style={{ "--chip-c": color } as CSSProperties}>
        <span className="panel-head-tile">
          <img src={icon} alt="" />
        </span>
        <div className="panel-head-text">
          <span className="read-panel-kind" style={eyebrowColor ? { color: eyebrowColor } : undefined}>
            {eyebrow}
          </span>
          <h2 className="panel-head-name">
            {onNavigate ? (
              <button className="panel-head-nav" onClick={onNavigate} title="Focus this on the canvas">
                {name}
              </button>
            ) : (
              name
            )}
          </h2>
        </div>
      </div>
      <button className="icon-button" onClick={onClose} title="Close">
        ✕
      </button>
    </header>
  );
}
