// A floating callout anchored to a canvas node, in FLOW-space (it pans/zooms WITH the canvas, like a
// node) via ViewportPortal — NOT a side panel and NOT a store node (so it never perturbs the
// contract-driven ELK layout). Placed perpendicular to the spine: TD → left of the anchor, LR → above it
// (mirrors the spine-avoiding Tines layout). On show it frames the camera over anchor ∪ callout.
//
// THE REUSABLE PRIMITIVE (Task 175 + 174): the run-progress stream drops in as children now; Task 174's
// agent "say" bubble reuses the same shell (anchor a styled box to any node + center on it). Content-
// agnostic by design — it owns anchoring + chrome + framing, never what's inside.

import { useEffect, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";
import { useReactFlow, ViewportPortal } from "@xyflow/react";

import type { Direction } from "../graph/flow";

// Nominal callout size in FLOW units — used only to frame the camera generously (the box itself is
// CSS-sized + scrolls); over-framing slightly is fine, clipping the callout is not.
const NOMINAL_W = 320;
const NOMINAL_H = 280;
const GAP = 28;

export function NodeCallout({
  anchorId,
  direction,
  icon,
  title,
  subtitle,
  onClose,
  children,
}: {
  anchorId: string;
  direction: Direction;
  // An optional leading header element (rendered before the title) — the run callout passes the pflow
  // chevrons; the shell stays content-agnostic, so Task 174's "say" bubble can pass its own mark or none.
  icon?: ReactNode;
  title: string;
  // An optional muted header slot between the title and the ✕ (the run callout puts the run id here;
  // Task 174's "say" bubble can use it for a label). Absent → just title + ✕.
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}): JSX.Element | null {
  const { getInternalNode, setCenter } = useReactFlow();
  const anchor = getInternalNode(anchorId);
  // Flow-space rect of the anchor. RF re-measures EVERY node on a beautiful-mode expansion re-layout (any
  // node click), during which the anchor's `measured` transiently goes undefined — dropping to null then
  // would unmount/remount the box (a flicker, user-caught). Cache the last good rect and render at it
  // through the transient; only the very first render (before any measure) has no rect.
  const liveRect =
    anchor && anchor.measured.width != null
      ? {
          x: anchor.internals.positionAbsolute.x,
          y: anchor.internals.positionAbsolute.y,
          w: anchor.measured.width,
          h: anchor.measured.height ?? 0,
        }
      : null;
  const lastRectRef = useRef(liveRect);
  if (liveRect) lastRectRef.current = liveRect;
  const rect = liveRect ?? lastRectRef.current;
  const ready = rect != null;

  // Frame anchor ∪ callout EXACTLY ONCE, on the first measured render after this callout opens — a strict
  // one-shot. It must NOT re-fire on later churn: selecting/deselecting a node (beautiful-mode expansion)
  // re-layouts the canvas, which re-measures every node and transiently flips `ready`; a reactive frame
  // would then yank the camera back to the callout on every click. The ref makes it fire once per mount;
  // a NEW launch remounts the callout (runCalloutOpen false→true) and re-arms it.
  const framedRef = useRef(false);
  useEffect(() => {
    if (framedRef.current || !rect) return;
    framedRef.current = true;
    const bounds =
      direction === "TD"
        ? { x: rect.x - NOMINAL_W - GAP, y: rect.y, width: rect.w + NOMINAL_W + GAP, height: Math.max(rect.h, NOMINAL_H) }
        : { x: rect.x, y: rect.y - NOMINAL_H - GAP, width: Math.max(rect.w, NOMINAL_W), height: rect.h + NOMINAL_H + GAP };
    // Center the anchor ∪ callout region at a FIXED, modest zoom rather than fitBounds (which over-zooms a
    // small region, blowing the compact box up to fill the screen). A predictable zoom keeps the box small
    // and leaves the rest of the canvas in view. Synchronous one-shot (framedRef) — on a `?run=` deep-link
    // load the competing whole-graph mount-fit is suppressed (GraphView passes suppressInitialFit), so this
    // is uncontested; the interactive-pin / launch cases never had a competing fit.
    void setCenter(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2, { zoom: 1.1, duration: 400 });
    // One-shot: read rect/direction/setCenter at fire time; `ready` only re-arms the first-measure case.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  if (!rect) return null;

  // Position perpendicular to the spine, in flow coordinates: TD → left of the anchor; LR → above it
  // (translateY(-100%) so the box's bottom sits a GAP above the anchor top).
  const style: CSSProperties =
    direction === "TD"
      ? { left: rect.x - NOMINAL_W - GAP, top: rect.y }
      : { left: rect.x, top: rect.y - GAP, transform: "translateY(-100%)" };

  return (
    <ViewportPortal>
      {/* `nopan`/`nodrag`: the callout lives inside the RF viewport, whose d3-drag pan handler would
          otherwise swallow the pointer (the ✕ and the step buttons wouldn't click). `nowheel` lets the
          body scroll without zooming the canvas. */}
      <div className="node-callout nopan nodrag nowheel" style={{ position: "absolute", ...style }}>
        <div className="node-callout-head">
          {icon != null ? <span className="node-callout-lead">{icon}</span> : null}
          <span className="node-callout-title">{title}</span>
          {subtitle != null ? <span className="node-callout-subtitle">{subtitle}</span> : null}
          <button className="node-callout-close" onClick={onClose} aria-label="Close" title="Close">
            ✕
          </button>
        </div>
        <div className="node-callout-body">{children}</div>
      </div>
    </ViewportPortal>
  );
}
