// Small status pills derived from a node's structural facts (unexpanded only).
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
  // No loop/batch badge: those are BEHAVIOR CHIPS on the border rail (ChipRail.tsx,
  // 2026-06-10 — the old header batch pill squeezed the description and duplicated
  // the deck). No decision badge either: a decision presents as the CONDITION
  // pseudo-kind (label/icon/color — utils/format isCondition) and its labeled
  // branch edges draw the fork. The read panel carries `code · condition`.
  const badges: Badge[] = [];
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
