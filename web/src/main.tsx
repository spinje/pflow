import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { metricsCssVars } from "./graph/metrics";
import "./index.css";

// The stylesheet's geometry (row/header/tile/edge sizes) comes from the SAME
// constants ELK and the components use — injected here, before first paint, so
// index.css never hardcodes a layout-coupled number (see graph/metrics.ts).
for (const [name, value] of Object.entries(metricsCssVars())) {
  document.documentElement.style.setProperty(name, value);
}

const root = document.getElementById("root");
if (!root) throw new Error("missing #root element");

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
