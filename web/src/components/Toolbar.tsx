import type { Density, Direction } from "../graph/flow";

interface ToolbarProps {
  title: string;
  density: Density;
  direction: Direction;
  hasCollapsed: boolean;
  focused: boolean;
  onDensity: (d: Density) => void;
  onDirection: (d: Direction) => void;
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

      {props.hasCollapsed && (
        <button className="link-button" onClick={props.onExpandAll}>
          expand all
        </button>
      )}
      {props.focused && (
        <button className="link-button" onClick={props.onClearFocus}>
          clear focus
        </button>
      )}
    </header>
  );
}
