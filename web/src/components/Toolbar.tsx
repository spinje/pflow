import logoUrl from "../assets/logo.png";
import type { Density, Direction } from "../graph/flow";

interface ToolbarProps {
  // title = the workflow basename (display); path = the full path (tooltip).
  title: string;
  path: string;
  density: Density;
  direction: Direction;
  onDensity: (d: Density) => void;
  onDirection: (d: Direction) => void;
  onBack: () => void;
}

// The slim top context bar: a back-to-catalog arrow + workflow title + the two
// MODE selectors as labeled segmented pills (state-legibility wins here — see
// Rail.tsx). Panel toggles, focus, and the "N/M open" readout live on the floating
// Rail; the back nav stays here (matching the reference's top-left breadcrumb).
export function Toolbar(props: ToolbarProps): JSX.Element {
  return (
    <header className="toolbar">
      {/* The pflow mark doubles as the home / back-to-catalog anchor (consolidating the
          old back-arrow): identity + nav in one element, the convention these canvas tools follow. */}
      <button className="toolbar-back" onClick={props.onBack} title="pflow — back to catalog" aria-label="Back to catalog">
        <img className="toolbar-logo" src={logoUrl} alt="pflow" />
      </button>
      <h1 className="toolbar-title" title={props.path}>
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
    </header>
  );
}
