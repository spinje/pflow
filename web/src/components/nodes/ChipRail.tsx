// Behavior modifiers (loop / batch) render as chips on the card border, keeping
// node identity in the tile and category unchanged.
//
// Visual grammar: ROUND/capsule tinted chips = info; the SQUARE element a GroupNode
// appends (the merged count-expander, `.group-toggle`) is the one button. Live
// run status belongs to the corner StatusBadge, not this rail.
//
// A dynamic batch shows `×N` because its count is unavailable from the authored
// graph; the iterated source rides the tooltip + read panel.

import type { ReactNode } from "react";

import type { RFNode } from "../../types";

function loopTitle(loop: NonNullable<RFNode["loop"]>): string {
  const cap = loop.cap != null ? ` (at most ${loop.cap} iterations)` : "";
  return `loops ${loop.polarity} ${loop.condition}${cap}`;
}

function batchTitle(batch: NonNullable<RFNode["batch"]>): string {
  const mode = batch.parallel ? "parallel" : "sequential";
  const over = batch.dynamic ? (batch.source_ref ?? "a dynamic source") : "literal items";
  return `${mode} batch over ${over}`;
}

/** The border rail. Children render AFTER the modifier chips (rightmost slot —
 *  GroupNode appends its merged count-expander there). Renders nothing when empty
 *  so a plain leaf adds zero DOM. `shifted` nudges the rail left so its rightmost
 *  chip / count-expander clears an overhanging corner StatusBadge — passed
 *  only when the node carries a run-status badge, so a badge-less node is unchanged. */
export function ChipRail({
  node,
  children,
  shifted = false,
}: {
  node: RFNode | null;
  children?: ReactNode;
  shifted?: boolean;
}): JSX.Element | null {
  const loop = node?.loop ?? null;
  const batch = node?.batch ?? null;
  if (!loop && !batch && !children) return null;
  return (
    <span className={shifted ? "chip-rail shifted" : "chip-rail"}>
      {loop && (
        <span className="chip chip-loop chip-round" title={loopTitle(loop)}>
          <svg viewBox="0 0 32 32" aria-hidden="true">
            <path
              d="M16 5 a11 11 0 1 0 11 11"
              fill="none"
              stroke="currentColor"
              strokeWidth="3.4"
              strokeLinecap="round"
            />
            <path d="M22.5 5.5 L16.5 2.2 L16.8 9.0 Z" fill="currentColor" />
          </svg>
        </span>
      )}
      {batch && (
        <span className="chip chip-batch" title={batchTitle(batch)}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <rect x="5" y="2" width="9" height="8" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.55" />
            <rect x="2" y="6" width="9" height="8" rx="2" fill="var(--bg-node)" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          {batch.dynamic ? "×N" : `×${batch.count ?? "?"}`}
        </span>
      )}
      {children}
    </span>
  );
}
