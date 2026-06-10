// Small status pills derived from a node's structural facts (batch / unexpanded).
// Visual policy lives here, not in the contract — the payload ships these as plain
// facts (task-168.md "predicates baked in Python, visual policy in TS"). A badge
// earns its place only when NOTHING else on the canvas shows the fact.

import type { RFNode } from "../../types";

interface Badge {
  label: string;
  cls: string;
  title?: string;
}

function badgesFor(node: RFNode): Badge[] {
  // No loop badge: the loop-back arc (synthesized in flow.ts, drawn by LoopEdge) is
  // the loop's visual, with the condition/cap on its label. Full detail in the read
  // panel. A redundant header pill would just add clutter.
  const badges: Badge[] = [];
  if (node.batch) {
    const count = node.batch.dynamic ? "×N" : `×${node.batch.count ?? "?"}`;
    const where = node.batch.dynamic ? node.batch.source_ref ?? "dynamic" : "literal items";
    badges.push({
      label: `${node.batch.parallel ? "parallel " : ""}batch ${count}`,
      cls: "badge-batch",
      title: `over ${where}`,
    });
  }
  // No decision badge (same reasoning as the loop badge): a decision presents as
  // the CONDITION pseudo-kind (label/icon/color — utils/format isCondition) and its
  // labeled branch edges draw the fork. The read panel carries `code · condition`.
  if (node.unexpanded) {
    badges.push({
      label: node.unexpanded.replace(/_/g, " "),
      cls: "badge-unexpanded",
      title: `not expanded: ${node.unexpanded}`,
    });
  }
  return badges;
}

export function NodeBadges({ node, max }: { node: RFNode; max?: number }): JSX.Element | null {
  let badges = badgesFor(node);
  if (badges.length === 0) return null;
  const overflow = max != null && badges.length > max ? badges.length - max : 0;
  if (max != null) badges = badges.slice(0, max);
  return (
    <div className="badges">
      {badges.map((b) => (
        <span key={b.label} className={`badge ${b.cls}`} title={b.title}>
          {b.label}
        </span>
      ))}
      {overflow > 0 && <span className="badge badge-more">+{overflow}</span>}
    </div>
  );
}
