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
//   The chip RAIL is ABSOLUTE on the top-right border in BOTH states (straddling
//   it) so it, too, stays put across the fold: the host's behavior chips (loop /
//   batch — ChipRail.tsx) + the merged COUNT-EXPANDER (`.group-toggle`, the one
//   square element: recursive step count + expand/collapse glyph).
//
// The icon comes from the HOST node via groupIconFor (its kind icon — behavior
// like loop/batch rides the rail chips, never the tile: identity doesn't mutate).
// A host is NOT 1:1 with a group (H8) — only the host's primary (outermost) group
// draws the title/chips. Toggling collapse lives on the expander + double-click;
// body clicks SELECT (design D, GraphView's onNodeClick).

import { type CSSProperties, memo, useEffect } from "react";
import { Handle, type NodeProps, Position, useUpdateNodeInternals } from "@xyflow/react";

import { type FlowNode, ioRowsCount } from "../../graph/flow";
import { NODE_IN, NODE_OUT } from "../../graph/handles";
import { ICON_COL_X, ICON_ROW_Y } from "../../graph/metrics";
import { BATCH_COLOR, kindColor } from "../../utils/format";
import { groupIconFor } from "../../utils/icons";
import type { ContainerKind } from "../../types";
import { useInteraction } from "../interaction";
import { ChipRail } from "./ChipRail";
import { PortRows } from "./PortRows";
import { Connector } from "./WorkflowNode";

// A1 arrows-out / arrows-in (maximize/restore language, 12×12) — the corner
// toggle's glyphs, user-picked via the mockup lab (expand-btn-lab, 2026-06-10).
const GLYPH_EXPAND = "M7.2 1.8 H10.2 V4.8 M10.2 1.8 L6.8 5.2 M4.8 10.2 H1.8 V7.2 M1.8 10.2 L5.2 6.8";
const GLYPH_COLLAPSE = "M6.8 5.2 H10 M6.8 5.2 V2 M10.2 1.8 L6.8 5.2 M5.2 6.8 H2 M5.2 6.8 V10 M1.8 10.2 L5.2 6.8";

type GroupNodeType = Extract<FlowNode, { type: "group" }>;

const KIND_LABEL: Record<ContainerKind, string> = {
  workflow: "sub-workflow",
  batch: "batch",
  input_wrapper: "inputs",
  output_wrapper: "outputs",
};

/** The category line. A literal batch OF SUB-WORKFLOWS composes both facts as
 *  "BATCH-WORKFLOW" (user-decided 2026-06-11): the box is a sub-workflow step
 *  like its dynamic sibling AND a real batch container of item copies — a bare
 *  "BATCH" demoted the step's identity purely because its items were authored
 *  literally. Other batch shapes (hostless / non-workflow hosts) keep the
 *  plain label. */
function groupCategory(kind: ContainerKind, hostKind: string | undefined): string {
  if (kind === "batch" && hostKind === "workflow") return "batch-workflow";
  return KIND_LABEL[kind];
}

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
  const { toggleGroup } = useInteraction();

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

  // Control handles sit on the ICON LINE in BOTH states (user requirement: the
  // trunk flows through the tile whether the container is open or closed) — TD:
  // the icon column, LR: the icon row (in left / out right at the SAME height).
  // layout.ts declares matching ELK ports for COLLAPSED cards; regions stay
  // port-less (compound crash) and smoothstep absorbs the offset.
  const topHandleStyle = direction === "TD" ? { left: ICON_COL_X, top: 5 } : { top: ICON_ROW_Y, left: 5 };
  // right: 5 tucks the OUT terminus under the card — see WorkflowNode.
  const bottomHandleStyle = direction === "TD" ? { left: ICON_COL_X, bottom: 5 } : { top: ICON_ROW_Y, right: 5 };

  // The IDENTICAL header for both states. The TOP (TD) / LEFT (LR) flare draws in
  // both (the edge flows INTO the tile, open or closed); the BOTTOM flare is
  // collapsed-only — an expanded region's tile sits at its top, far from the
  // bottom exit (the same rule as a focus-expanded leaf card). LR has no right
  // tile flare: the tile sits at the card's left, away from the outgoing border.
  // `group-header` adds the absolute-overlay positioning the region needs; on the
  // card the header is the whole card.
  const header = (
    <div className={collapsed ? "node-header" : "node-header group-header"}>
      <div className="node-tile">
        <img className="node-icon-img" src={icon} alt="" />
        {direction === "TD" && hasIncoming && <Connector side="top" />}
        {collapsed && direction === "TD" && hasOutgoing && <Connector side="bottom" />}
        {direction === "LR" && hasIncoming && <Connector side="left" />}
      </div>
      <div className="node-titles">
        <span className="node-category">{groupCategory(group.kind, hostNode?.kind)}</span>
        <span className="node-name" title={title}>
          {hostNode?.purpose || title}
        </span>
      </div>
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
      {direction === "LR" && hasOutgoing && <span className="exit-dot" aria-hidden="true" />}
      {header}
      {/* The border rail: the host's behavior chips (loop/batch — only the primary
          group draws identity chrome) + the merged COUNT-EXPANDER (the count pill
          and the corner button became one element, user-picked F1 via shoot-lab
          2026-06-10: recursive step count + the A1 glyph, rounded-SQUARE — the
          rail's one button among round info chips). Expand/collapse lives ONLY
          here (+ double-click): the card/region body SELECTS like any node
          (design D). stopPropagation is load-bearing — a button click must not
          also focus the container; the dblclick stop keeps a fast double-press
          on the button from ALSO firing the node-level dblclick toggle (net
          no-op flicker). */}
      <ChipRail node={showTitle ? hostNode : null}>
        <span
          className="group-toggle"
          title={`${countLabel} — ${collapsed ? "expand" : "collapse"}`}
          onClick={(e) => {
            e.stopPropagation();
            toggleGroup(id);
          }}
          onDoubleClick={(e) => e.stopPropagation()}
        >
          <span className="toggle-count">{memberCount}</span>
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d={collapsed ? GLYPH_EXPAND : GLYPH_COLLAPSE} />
          </svg>
        </span>
      </ChipRail>
      {/* The workflow's declared IO as rows (PortRows — the leaf-row anatomy).
          COLLAPSED: a two-column area under the header — inputs left, outputs right
          BOTTOM-ANCHORED (ending at the last row: the in→out diagonal, user-decided
          2026-06-10; equals the original one-row stagger whenever counts are
          balanced, and keeps a lopsided card's outputs at its bottom-right corner).
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
              staggerRows={ioRowsCount(inputs.length, outputs.length) - outputs.length}
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
