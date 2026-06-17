// Auto layout-direction policy: the direction a workflow OPENS in when the URL carries
// no explicit `direction=` (the sibling of graph/collapse.ts's auto-collapse). LR
// (left-to-right, the n8n reading order) is the default and right for the vast
// majority — linear and branchy workflows read best horizontally. But a DENSE pipeline
// lays out in LR as a long horizontal chain whose ${ref} data dependencies thread back
// THROUGH every intervening card; TD gives those dependencies vertical gutters to run
// in. Measured edges-drawn-through-an-unrelated-box (advanced density, fully expanded,
// via a real-browser crossing probe):
//
//   workflow                   data/nodes   LR        TD
//   execute-plan               129/64 = 2.0   58%      —
//   run-from-plan (harness)    152/82 = 1.85  55%      8%
//   generate-changelog-simple   39/26 = 1.5   42%      —
//   orchestrate                 33/28 = 1.2   13%   (stays LR)
//   deep-research               30/29 = 1.0   10%   (stays LR)
//   conditional-branching        1/7 = 0.14    0%   (stays LR)
//
// DATA-EDGE DENSITY is the predictor — a dense LOOPLESS workflow (changelog-simple) is
// as bad as the looped ones, and a sparse LOOPED one (orchestrate) is fine, so loops
// are NOT the signal (they only correlate because looped workflows tend to be dense).
// Conservative by design: only the clearly-bad (>~40%) cases flip; LR's modest cases
// are left alone. An explicit `direction=` URL param always wins (like `collapse=`), and
// the toolbar toggle re-flips at will — this only chooses the INITIAL default.

import type { Direction } from "./flow";
import type { RFGraph } from "../types";

// Below this node count, direction is cosmetic (the chain is short either way) — keep
// the LR default; guards a tiny-but-dense workflow from flipping on the ratio alone.
export const DENSE_NODE_FLOOR = 16;

// Data edges per node above which the horizontal LR chain threads its dependencies back
// through the cards. The corpus splits cleanly here: 1.18/1.03 stay LR, 1.5+ flip TD.
export const DENSE_DATA_PER_NODE = 1.4;

/** The direction a workflow opens in when the URL has no `direction=`: TD for a dense,
 *  non-trivial pipeline (LR would thread its data dependencies through the cards), LR
 *  otherwise. Pure (no React) so it unit-tests node-env, like the rest of graph/. */
export function autoDirection(graph: RFGraph): Direction {
  const nodeCount = graph.nodes.length;
  if (nodeCount < DENSE_NODE_FLOOR) return "LR";
  const dataEdges = graph.edges.reduce((n, e) => (e.kind === "data_flow" ? n + 1 : n), 0);
  return dataEdges / nodeCount >= DENSE_DATA_PER_NODE ? "TD" : "LR";
}
