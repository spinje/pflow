// The chip RAIL — behavior modifiers (loop / batch) as chips straddling the card's
// TOP border, right-aligned (user-picked via the 3-round batch-chip shoot-lab,
// 2026-06-10; plan: task_168/implementation/batch-chip-rail-plan.md). Replaces the
// header batch badge (it squeezed the 2-line description), the category-line ↻ mark,
// and the looped sub-workflow tile-icon swap: identity (tile/category) never mutates —
// behavior is additive chrome on the border.
//
// Visual grammar: ROUND/capsule tinted chips = info; the SQUARE element a GroupNode
// appends (the merged count-expander, `.group-toggle`) is the one button. The rail is
// also the reserved home for future live-overlay STATUS chips (status joins leftmost,
// outranks modifiers).
//
// A dynamic batch shows `×N` (the count is unknowable statically — a future run
// overlay fills the real number); the iterated source rides the tooltip + read panel.

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
 *  so a plain leaf adds zero DOM. */
export function ChipRail({ node, children }: { node: RFNode | null; children?: ReactNode }): JSX.Element | null {
  const loop = node?.loop ?? null;
  const batch = node?.batch ?? null;
  if (!loop && !batch && !children) return null;
  return (
    <span className="chip-rail">
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
