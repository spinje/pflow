import type { Density, Direction } from "../graph/flow";

interface ToolbarProps {
  title: string;
  density: Density;
  direction: Direction;
  // Collapse control (user-chosen design 2026-06-10: buttons + count). groupCount is
  // the COLLAPSIBLE group total; the whole control hides when a workflow has none.
  groupCount: number;
  openCount: number;
  focused: boolean;
  sourceOpen?: boolean;
  showSourceToggle?: boolean;
  onDensity: (d: Density) => void;
  onDirection: (d: Direction) => void;
  onSourceOpen?: (open: boolean) => void;
  onCollapseAll: () => void;
  onExpandAll: () => void;
  onClearFocus: () => void;
  onBack: () => void;
}

export function Toolbar(props: ToolbarProps): JSX.Element {
  return (
    <header className="toolbar">
      <button className="link-button" onClick={props.onBack} title="Back to the workflow catalog">
        ← catalog
      </button>
      <h1 className="toolbar-title" title={props.title}>
        {props.title}
      </h1>

      <div className="toolbar-group" role="group" aria-label="density">
        <button className={props.density === "detailed" ? "active" : ""} onClick={() => props.onDensity("detailed")}>
          advanced
        </button>
        <button className={props.density === "compact" ? "active" : ""} onClick={() => props.onDensity("compact")}>
          beautiful
        </button>
      </div>

      <div className="toolbar-group" role="group" aria-label="direction">
        <button className={props.direction === "LR" ? "active" : ""} onClick={() => props.onDirection("LR")}>
          LR
        </button>
        <button className={props.direction === "TD" ? "active" : ""} onClick={() => props.onDirection("TD")}>
          TD
        </button>
      </div>

      {props.showSourceToggle && props.onSourceOpen && (
        <div className="toolbar-group" role="group" aria-label="source">
          <button className={props.sourceOpen ? "active" : ""} onClick={() => props.onSourceOpen?.(!props.sourceOpen)}>
            source
          </button>
        </div>
      )}

      {/* The disabled states carry the extremes (fully open / fully closed); the count
          disambiguates every mixed state in between. */}
      {props.groupCount > 0 && (
        <>
          <div className="toolbar-group" role="group" aria-label="groups">
            <button title="Collapse all groups" disabled={props.openCount === 0} onClick={props.onCollapseAll}>
              ⊟
            </button>
            <button title="Expand all groups" disabled={props.openCount === props.groupCount} onClick={props.onExpandAll}>
              ⊞
            </button>
          </div>
          <span className="toolbar-count" title="Expanded groups">
            {props.openCount}/{props.groupCount} open
          </span>
        </>
      )}
      {props.focused && (
        <button className="link-button" onClick={props.onClearFocus}>
          clear focus
        </button>
      )}
    </header>
  );
}
