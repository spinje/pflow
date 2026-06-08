// Catch-all so an unexpected render throw (a contract value a component chokes on,
// a React Flow internal error) degrades to a readable banner instead of a blank
// white screen — the "never crash / never a silent empty view" bar. This is the
// last line of defense; the fetch/layout paths surface their own errors inline.

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep the stack for anyone with the devtools console open.
    console.error("pflow UI render error:", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="banner error" style={{ margin: 24 }}>
          <strong>The viewer hit an unexpected error.</strong>
          <p>{this.state.error.message}</p>
          <button onClick={() => window.location.reload()}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}
