// The floating chrome rail (rounded capsule) anchored to the LEFT
// EDGE OF THE CANVAS — so it rides just right of the source pane when that's open
// and floats at the far left when it's closed (GraphView renders it inside
// .canvas, which is position:relative). ACTIONS & TOGGLES only, never a node
// palette (read-only viewer). Mode SELECTORS stay in the Toolbar as labeled pills.
//
// Toggle icons speak the CANVAS language and light up on enable: the markdown
// glyph for the source pane (muted → white when open), the sub-workflow glyph for
// expanding sub-workflow containers (muted → magenta when any are open). Both
// assets are fixed-color SVGs, so the muted state is a CSS grayscale/dim filter
// (.rail-icon) lifted on .active — see index.css.
import type { ReactNode } from "react";
import markdownIcon from "../assets/icons/markdown.svg";
import subworkflowIcon from "../assets/icons/subworkflow.svg";
import { RailSearch } from "./RailSearch";
import type { RFNode } from "../types";

interface RailProps {
  sourceOpen?: boolean;
  showSourceToggle?: boolean;
  // groupCount is the COLLAPSIBLE group total (the toggle hides at 0); openCount
  // drives the enabled/colored state (any group expanded → magenta).
  groupCount: number;
  openCount: number;
  focused: boolean;
  // The searchable subjects (steps + container hosts); null/empty hides search.
  searchNodes?: readonly RFNode[];
  onSourceOpen?: (open: boolean) => void;
  onCollapseAll: () => void;
  onExpandAll: () => void;
  onClearFocus: () => void;
  onSelectNode?: (node: RFNode) => void;
}

interface RailButtonProps {
  label: string;
  // Optional second tooltip line — supplementary STATE under the action label
  // (e.g. the sub-workflow toggle's "N/M open" readout), muted below the label.
  detail?: string;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}

// A custom hover tooltip (the dark chip to the right of the icon) replaces the
// native `title`: it can carry a muted second `detail` line and is styled in the
// chrome palette. The action stays on `aria-label` for assistive tech.
function RailButton({ label, detail, active, onClick, children }: RailButtonProps): JSX.Element {
  return (
    <button
      className={"rail-button" + (active ? " active" : "")}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
    >
      {children}
      <span className="rail-tip">
        <span className="rail-tip-label">{label}</span>
        {detail && <span className="rail-tip-detail">{detail}</span>}
      </span>
    </button>
  );
}

export function Rail(props: RailProps): JSX.Element | null {
  const showSearch = Boolean(props.searchNodes && props.searchNodes.length > 0 && props.onSelectNode);
  const showSource = Boolean(props.showSourceToggle && props.onSourceOpen);
  const showGroups = props.groupCount > 0;
  const groupsExpanded = props.openCount > 0;

  // Nothing to offer (e.g. the error state) → no empty capsule. The back nav
  // lives in the Toolbar, so the rail is purely search + contextual toggles + focus.
  if (!showSearch && !showSource && !showGroups && !props.focused) return null;

  return (
    <nav className="rail" aria-label="Workflow controls">
      {showSearch && <RailSearch nodes={props.searchNodes!} onSelect={props.onSelectNode!} />}
      {showSearch && (showSource || showGroups || props.focused) && <div className="rail-sep" />}

      {showSource && (
        <RailButton
          label={props.sourceOpen ? "Hide source" : "Show source"}
          active={props.sourceOpen}
          onClick={() => props.onSourceOpen?.(!props.sourceOpen)}
        >
          <img className="rail-icon" src={markdownIcon} alt="" />
        </RailButton>
      )}

      {showGroups && (
        // ONE sub-workflow toggle: muted glyph → click expands all → magenta;
        // magenta → click collapses all → muted. The "N/M open" readout rides this
        // button's tooltip as a second line, keeping partial states legible.
        <RailButton
          label={groupsExpanded ? "Collapse sub-workflows" : "Expand sub-workflows"}
          detail={`${props.openCount}/${props.groupCount} open`}
          active={groupsExpanded}
          onClick={groupsExpanded ? props.onCollapseAll : props.onExpandAll}
        >
          <img className="rail-icon" src={subworkflowIcon} alt="" />
        </RailButton>
      )}

      {props.focused && (
        <>
          {(showSource || showGroups) && <div className="rail-sep" />}
          <RailButton label="Clear focus" onClick={props.onClearFocus}>
            <svg
              width={18}
              height={18}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.7}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <circle cx="12" cy="12" r="9" />
              <line x1="9" y1="9" x2="15" y2="15" />
              <line x1="15" y1="9" x2="9" y2="15" />
            </svg>
          </RailButton>
        </>
      )}
    </nav>
  );
}
