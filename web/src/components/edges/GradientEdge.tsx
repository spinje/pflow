// A rounded-orthogonal control edge (the Tines look: axis-aligned runs, generously
// rounded turns) whose stroke blends sourceColor -> targetColor along the TRUE edge
// direction. We use a `userSpaceOnUse` gradient positioned by the actual source/target
// coords, so the blend follows direction in any orientation (LR/TD, backward,
// re-anchored) with no degenerate-bbox bug (the objectBoundingBox artifact, xyflow
// #4822). Pure styling — handles/anchoring are untouched. No arrowhead: the line flows
// straight into the node's (same-color) border.
//
// The stop list depends on the edge KIND:
//   sequential/branch — blend source→target across the whole length.
//   error/end         — keep the SEMANTIC color (red / faint grey) along the body,
//                       but fade into the node's type color over the last ~FADE_PX
//                       at each node, so the line flows out of / into the
//                       kind-colored connectors instead of clashing. An end edge
//                       fades only at its source — the end-sink side stays faint.
//
// A label is rendered only when present — in practice TD fork edges (a branch's
// outcome rides the edge there; in LR it rides the node's border handle instead).

import { memo, type CSSProperties } from "react";
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, Position, type EdgeProps } from "@xyflow/react";

import type { FlowEdge } from "../../graph/flow";
import { ICON_COL_X, METRICS } from "../../graph/metrics";
import { truncate } from "../../utils/format";

// Mid-path condition labels can be whole expressions — clamp them; the full text
// rides the title tooltip and the read panel's outcome table.
const CONDITION_MAX = 40;

// Vertical zone the outcome label occupies at the target entry (pill height +
// gaps) — the condition pill centers in the descent ABOVE it.
const OUTCOME_CLEAR = 26;

// A TD branch with less horizontal travel than this has no lone rail run worth
// labeling — its midpoint would sit in the shared rail-crossing zone.
const LONE_RUN_MIN = 60;

/** Where the CONDITION pill sits. The path midpoint is the right home when the
 *  edge owns a real horizontal rail run (a side branch — the run belongs to
 *  this edge alone, and smoothstep's label point is its center). The STRAIGHT
 *  child has no run: its midpoint lands ON the crossing of every sibling's
 *  rail (user-caught), so it falls back to the FINAL DESCENT — centered between
 *  the rail and the outcome-label zone at the target entry, a segment owned by
 *  this edge by construction. Other shapes (LR, backward) keep the midpoint. */
export function conditionAnchor(args: {
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  targetPosition: Position;
  pathX: number;
  pathY: number;
}): { x: number; y: number } {
  const { sourceX, sourceY, targetX, targetY, targetPosition, pathX, pathY } = args;
  const noLoneRun = Math.abs(targetX - sourceX) < LONE_RUN_MIN;
  if (targetPosition === Position.Top && targetY > sourceY && noLoneRun) {
    const railY = sourceY + Math.min(RAIL_OFFSET, (targetY - sourceY) / 2);
    // +5: user-tuned — clears the rail corner the centered point still kissed.
    return { x: targetX, y: (railY + targetY - OUTCOME_CLEAR) / 2 + 5 };
  }
  return { x: pathX, y: pathY };
}

// How far the node-color fade reaches into an error/end edge, in px. The gradient
// runs along the straight source→target chord, so offsets are FADE_PX as a fraction
// of the chord length — near an endpoint the path hugs it, so a short fade tracks
// the curve well. Semantic colors come from the CSS vars (set via style, where
// var() resolves) so a palette re-theme can't drift from them.
const FADE_PX = 26;

// Rounded-orthogonal geometry. RAIL_OFFSET puts the first turn just past the source
// (the Tines "trunk splits, then long straight columns into the targets" signature)
// instead of smoothstep's default midpoint turn. It is 2×radius because smoothstep
// clamps every bend to HALF its adjoining segment — a shorter offset STARVES the rail
// corners (they rendered ~12px against the 18px everywhere else; user-caught). Closer
// targets get the halfway point, which IS the stock midpoint — graceful degradation,
// no special threshold. Backward edges keep smoothstep's default wrap routing.
//
// LANE (LR only): in LR a fork's outcomes leave their OWN labeled row handles, so
// funneling them onto one shared rail collapsed distinct lines into one segment
// (user-caught) — each lane turns at its own x. In TD the branches leave ONE point
// (the icon column), so the SHARED rail is the trunk-split look — lane ignored.
const CORNER_RADIUS = METRICS.edgeRadius;
const RAIL_OFFSET = 2 * CORNER_RADIUS;
const LANE_STEP = 8;

export function railCenter(args: {
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  sourcePosition: Position;
  lane?: number;
}): { centerX?: number; centerY?: number } {
  const { sourceX, sourceY, targetX, targetY, sourcePosition } = args;
  if (sourcePosition === Position.Bottom && targetY > sourceY) {
    return { centerY: sourceY + Math.min(RAIL_OFFSET, (targetY - sourceY) / 2) };
  }
  if (sourcePosition === Position.Right && targetX > sourceX) {
    const stagger = (args.lane ?? 0) * LANE_STEP;
    return { centerX: sourceX + Math.min(RAIL_OFFSET + stagger, (targetX - sourceX) / 2) };
  }
  return {};
}

// BRANCH pills sit at the TARGET's entry point, on the edge's final run just before
// it enters the node (user-chosen 2026-06-10 over the old mid-rail row: with the
// pills mid-rail, a fork's outcomes read as one detached strip; at the entry they
// label the node they pick). Error/other labels stay at the PATH CENTER — an error
// handler isn't an outcome you pick, so its pill rides the edge like before. TD:
// the line enters the top at the icon column (ICON_COL_X from the node's left
// edge), and the pill's LEFT edge aligns with the node's left border (user-chosen
// over centering on the line); LR: the line enters the left border, so the pill
// sits just left of it. The self-translate aligns the pill's nearest EDGE
// (left+bottom / right) to the anchor, so pill size never overlaps the node.
const LABEL_GAP = 6;
// Nudge the TD branch label right of the node's left border (user-tuned: the bare
// text starting flush with the border read as part of the card outline).
const LABEL_NUDGE_X = 4;

export function labelAnchor(args: {
  targetX: number;
  targetY: number;
  targetPosition: Position;
  pathX: number;
  pathY: number;
}): { x: number; y: number; selfTranslate: string } {
  const { targetX, targetY, targetPosition, pathX, pathY } = args;
  if (targetPosition === Position.Top) {
    return { x: targetX - ICON_COL_X + LABEL_NUDGE_X, y: targetY - LABEL_GAP, selfTranslate: "translate(0, -100%)" };
  }
  if (targetPosition === Position.Left) {
    return { x: targetX - LABEL_GAP, y: targetY, selfTranslate: "translate(-100%, -50%)" };
  }
  // Unusual entry side (re-anchored/backward cases) — fall back to the path center.
  return { x: pathX, y: pathY, selfTranslate: "translate(-50%, -50%)" };
}

export type GradientStop = { offset: number; color: string };

export function gradientStops(kind: string | undefined, from: string, to: string, chordLen: number): GradientStop[] {
  if (kind === "error" || kind === "end") {
    const semantic = kind === "error" ? "var(--danger)" : "var(--text-faint)";
    // Clamp so the two fades can't cross on a short edge (each stays in its half).
    const t = chordLen > 0 ? Math.min(FADE_PX / chordLen, 0.4) : 0.4;
    if (kind === "error") {
      return [
        { offset: 0, color: from },
        { offset: t, color: semantic },
        { offset: 1 - t, color: semantic },
        { offset: 1, color: to },
      ];
    }
    return [
      { offset: 0, color: from },
      { offset: t, color: semantic },
    ];
  }
  return [
    { offset: 0, color: from },
    { offset: 1, color: to },
  ];
}

export const GradientEdge = memo(function GradientEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  label,
}: EdgeProps<FlowEdge>): JSX.Element {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: CORNER_RADIUS,
    ...railCenter({ sourceX, sourceY, targetX, targetY, sourcePosition, lane: data?.lane }),
  });
  const gradientId = `grad-${id}`;
  const from = data?.sourceColor ?? "var(--accent)";
  const to = data?.targetColor ?? "var(--accent)";
  const chordLen = Math.hypot(targetX - sourceX, targetY - sourceY);
  const stops = gradientStops(data?.kind, from, to, chordLen);
  const isBranchPill = data?.kind === "branch" && label != null;
  const anchor = isBranchPill
    ? labelAnchor({ targetX, targetY, targetPosition, pathX: labelX, pathY: labelY })
    : { x: labelX, y: labelY, selfTranslate: "translate(-50%, -50%)" };
  return (
    <>
      <defs>
        <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" x1={sourceX} y1={sourceY} x2={targetX} y2={targetY}>
          {stops.map((s, i) => (
            <stop key={i} offset={`${s.offset * 100}%`} style={{ stopColor: s.color }} />
          ))}
        </linearGradient>
      </defs>
      <BaseEdge id={id} path={edgePath} style={{ stroke: `url(#${gradientId})`, strokeWidth: selected ? METRICS.edgeStroke + 1 : METRICS.edgeStroke }} />
      {(label || data?.condition) && (
        <EdgeLabelRenderer>
          {/* The pill's FILL takes its edge's color via --label-c (error = the semantic
              red, else the target node's color — the line's color where it arrives);
              text stays white. A BRANCH pill additionally gets the `branch` class:
              its ordinal number + border speak the condition orange (--decision — the
              fork is the condition node's act) while the fill stays node-colored. */}
          {label && (
            <div
              className={`edge-label nodrag nopan${isBranchPill ? " branch" : ""}`}
              style={
                {
                  transform: `${anchor.selfTranslate} translate(${anchor.x}px, ${anchor.y}px)`,
                  "--label-c": data?.kind === "error" ? "var(--danger)" : to,
                } as CSSProperties
              }
            >
              {label}
            </div>
          )}
          {/* The CONDITION that selects this outcome ("if len(items) > 5" / "else"),
              extracted from the decision node's code (RFEdge.condition). It rides
              MID-PATH — the outcome label stays at the target entry — as a standard
              edge pill (white text) tinted condition orange, and is only in `data`
              when it should render (advanced, or the condition node is
              focus-expanded; see EdgeData.condition in flow.ts). */}
          {data?.condition &&
            (() => {
              const at = conditionAnchor({ sourceX, sourceY, targetX, targetY, targetPosition, pathX: labelX, pathY: labelY });
              return (
                <div
                  className="edge-label nodrag nopan"
                  title={data.condition}
                  style={
                    {
                      transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)`,
                      "--label-c": "var(--decision)",
                    } as CSSProperties
                  }
                >
                  {truncate(data.condition, CONDITION_MAX)}
                </div>
              );
            })()}
        </EdgeLabelRenderer>
      )}
    </>
  );
});
