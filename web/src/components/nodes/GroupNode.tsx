// A container (sub-workflow / batch) in its two states — ONE object that folds
// (user-driven redesign, 2026-06-10, picked via shoot-lab mockups):
//
//   COLLAPSED → a real node card with the leaf card's exact anatomy (tile + frame
//     + icon, kind-colored category, name). It IS a node in the parent flow, so it
//     speaks the leaf language: same classes (.node.compact), icon-column handles +
//     connector flares in TD (layout.ts declares matching ELK ports, so trunks run
//     straight through collapsed groups instead of jogging).
//
//   EXPANDED → a region that grows AROUND that same header. The header markup is
//     IDENTICAL in both states (user requirement: icon size/placement/border and
//     the name/description must not move when you open — the region header is the
//     leaf `.node-header`, not a shrunken copy; METRICS.groupHeaderH == nodeHeaderH
//     keeps ELK's content padding in step). Only the wrapper differs (card classes
//     vs region classes) and the TD connector flares are collapsed-only (an
//     expanded region's edges enter at the border center, not the icon column).
//
//   The member-count pill is ABSOLUTE on the top-right border in BOTH states
//   (straddling it like a badge) so it, too, stays put across the fold; its
//   chevron is the collapse affordance (▸ closed / ▾ open).
//
// The icon comes from the HOST node via groupIconFor: a looped sub-workflow shows
// the loop glyph (amber — the LoopEdge color), a batch shows its batched node's
// kind icon. The category line still names the container kind, so the swap costs
// no identity. A host is NOT 1:1 with a group (H8) — only the host's primary
// (outermost) group draws the title/badges. Clicking a group toggles collapse
// (wired in GraphView's onNodeClick).

import { type CSSProperties, memo, useEffect } from "react";
import { Handle, type NodeProps, Position, useUpdateNodeInternals } from "@xyflow/react";

import type { FlowNode } from "../../graph/flow";
import { NODE_IN, NODE_OUT } from "../../graph/handles";
import { ICON_COL_X } from "../../graph/metrics";
import { BATCH_COLOR, kindColor } from "../../utils/format";
import { groupIconFor } from "../../utils/icons";
import type { ContainerKind } from "../../types";
import { NodeBadges } from "./Badges";
import { PortRows } from "./PortRows";
import { Connector } from "./WorkflowNode";

type GroupNodeType = Extract<FlowNode, { type: "group" }>;

const KIND_LABEL: Record<ContainerKind, string> = {
  workflow: "sub-workflow",
  batch: "batch",
  input_wrapper: "inputs",
  output_wrapper: "outputs",
};

// The container's identity color (inline --kind, same mechanism as the leaf card).
// Batch purple must equal the CSS --batch var; workflow magenta comes from the kind
// palette so card, edges, and icon stay one color.
function groupColor(kind: ContainerKind): string {
  return kind === "batch" ? BATCH_COLOR : kindColor("workflow");
}

function unexpandedItemCount(annotations: Record<string, unknown>): number {
  const items = annotations["unexpanded_items"];
  return items && typeof items === "object" ? Object.keys(items as Record<string, unknown>).length : 0;
}

function warningCount(annotations: Record<string, unknown>): number {
  const warnings = annotations["warnings"];
  return Array.isArray(warnings) ? warnings.length : 0;
}

export const GroupNode = memo(function GroupNode({ id, data }: NodeProps<GroupNodeType>): JSX.Element {
  const {
    group,
    hostNode,
    collapsed,
    showTitle,
    direction,
    hasIncoming,
    hasOutgoing,
    memberCount,
    inputs,
    outputs,
    ioRowsVisible,
    focusedPortId,
    dimmed,
    focused,
  } = data;
  const targetPos = direction === "LR" ? Position.Left : Position.Top;
  const sourcePos = direction === "LR" ? Position.Right : Position.Bottom;

  // Collapse toggles move the control handles (region border-center ↔ card icon
  // column), and IO rows appearing/disappearing adds/removes per-row handles;
  // without a re-measure React Flow keeps stale handle coords and the re-anchored
  // edges fly to the origin.
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, collapsed, direction, ioRowsVisible, updateNodeInternals]);

  const kindStyle = { "--kind": groupColor(group.kind) } as CSSProperties;
  const unexpanded = unexpandedItemCount(group.annotations);
  const warnings = warningCount(group.annotations);
  const icon = groupIconFor(hostNode);
  const title = hostNode?.ref.node_id ?? KIND_LABEL[group.kind];
  const countLabel = `${memberCount} node${memberCount === 1 ? "" : "s"}`;

  // TD control handles sit on the icon column in BOTH states (user requirement:
  // the trunk flows through the tile whether the container is open or closed) —
  // layout.ts declares matching ELK ports so the column aligns icon-to-icon.
  const topHandleStyle = direction === "TD" ? { left: ICON_COL_X, top: 5 } : undefined;
  const bottomHandleStyle = direction === "TD" ? { left: ICON_COL_X, bottom: 5 } : undefined;

  // The IDENTICAL header for both states. The TOP flare draws in both (the edge
  // flows INTO the tile, open or closed); the BOTTOM flare is collapsed-only — an
  // expanded region's tile sits at its top, far from the bottom exit (the same
  // rule as a focus-expanded leaf card). `group-header` adds the absolute-overlay
  // positioning the region needs; on the card the header is the whole card.
  const header = (
    <div className={collapsed ? "node-header" : "node-header group-header"}>
      <div className="node-tile">
        <img className="node-icon-img" src={icon} alt="" />
        {direction === "TD" && hasIncoming && <Connector side="top" />}
        {collapsed && direction === "TD" && hasOutgoing && <Connector side="bottom" />}
      </div>
      <div className="node-titles">
        <span className="node-category">{KIND_LABEL[group.kind]}</span>
        <span className="node-name" title={title}>
          {hostNode?.purpose || title}
        </span>
      </div>
      {showTitle && hostNode && <NodeBadges node={hostNode} max={1} />}
      {unexpanded > 0 && (
        <span className="badge badge-unexpanded" title="literal batch items that failed to expand">
          {unexpanded} unexpanded
        </span>
      )}
      {warnings > 0 && (
        <span className="badge badge-warning" title="child warnings">
          {warnings} warning{warnings === 1 ? "" : "s"}
        </span>
      )}
    </div>
  );

  const classes = collapsed ? ["node", "compact", "group-card", `group-${group.kind}`] : ["group", `group-${group.kind}`];
  // A batched sub-workflow presents as a SUB-WORKFLOW with batch (its shell batch
  // group is never rendered) — the host's batch spec lights the card's deck.
  if (collapsed && hostNode?.batch) classes.push("batched");
  if (ioRowsVisible) classes.push("has-io"); // full-width dividers + row areas
  if (dimmed) classes.push("dimmed");
  if (focused) classes.push("focused");

  return (
    <div className={classes.join(" ")} style={kindStyle}>
      <Handle id={NODE_IN} type="target" position={targetPos} className="handle node-handle" style={topHandleStyle} />
      <Handle id={NODE_OUT} type="source" position={sourcePos} className="handle node-handle" style={bottomHandleStyle} />
      {header}
      <span className="count-pill group-pill">
        <span className="chev">{collapsed ? "▸" : "▾"}</span>
        {countLabel}
      </span>
      {/* The workflow's declared IO as rows (PortRows — the leaf-row anatomy).
          COLLAPSED: a two-column area under the header — inputs left, outputs right
          staggered one row down (the in→out diagonal, user-decided 2026-06-10).
          Only the OUTER scope can carry edges here (internal edges self-loop-drop),
          so input rows are receive-only and output rows feed-only.
          EXPANDED: inputs become the LEFT SIDEBAR (layout.ts reserves the column as
          ELK left padding, so the body's first layer starts BESIDE it) and outputs
          the bottom-right strip — the collapsed diagonal stretched around the body.
          Region rows bridge both scopes (outer = parent, inner = body) → "both". */}
      {ioRowsVisible && collapsed && (
        <div className="io-rows io-rows-cols">
          {inputs.length > 0 && (
            <PortRows ports={inputs} kind="input" handles="receive" focusedPortId={focusedPortId} label="INPUTS" />
          )}
          {outputs.length > 0 && (
            <PortRows
              ports={outputs}
              kind="output"
              handles="feed"
              focusedPortId={focusedPortId}
              label="OUTPUTS"
              stagger={inputs.length > 0}
            />
          )}
        </div>
      )}
      {ioRowsVisible && !collapsed && inputs.length > 0 && (
        <div className="group-io-in">
          <PortRows ports={inputs} kind="input" handles="both" focusedPortId={focusedPortId} label="INPUTS" />
        </div>
      )}
      {ioRowsVisible && !collapsed && outputs.length > 0 && (
        <div className="group-io-out">
          <PortRows ports={outputs} kind="output" handles="both" focusedPortId={focusedPortId} label="OUTPUTS" />
        </div>
      )}
    </div>
  );
});
