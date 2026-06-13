// The two resizable side panes — source (left) and the read/edge/io panel
// (right) — as one state machine: widths, drag/reset callbacks, persistence,
// and the symmetric re-clamp. The pure clamp math stays in utils/panelWidth.ts;
// the drag gesture lives in components/PanelResizer.tsx.

import { useCallback, useEffect, useState } from "react";

import { clampPanelWidth, loadPanelWidth, PANEL_DEFAULT_W, savePanelWidth } from "../utils/panelWidth";

const SOURCE_WIDTH_KEY = "pflow-ui:source-w";

export interface PanelPair {
  panelWidth: number;
  sourceWidth: number;
  onPanelResize: (w: number) => void;
  onPanelReset: () => void;
  onSourceResize: (w: number) => void;
  onSourceReset: () => void;
}

// The two side panes share one symmetric clamp: the source pane always
// reserves the right panel's persisted width (a later selection can mount it
// without a drag), and the right panel reserves the OPEN source pane.
export function usePanelPair(sourceOpen: boolean): PanelPair {
  const [panelWidth, setPanelWidth] = useState(() => loadPanelWidth(window.innerWidth));
  const [sourceWidth, setSourceWidth] = useState(() => loadPanelWidth(window.innerWidth, SOURCE_WIDTH_KEY));
  const panelReserved = sourceOpen ? sourceWidth : 0;
  const sourceReserved = panelWidth;
  const onPanelResize = useCallback(
    (w: number) => setPanelWidth(clampPanelWidth(w, window.innerWidth, panelReserved)),
    [panelReserved],
  );
  const onPanelReset = useCallback(
    () => setPanelWidth(clampPanelWidth(PANEL_DEFAULT_W, window.innerWidth, panelReserved)),
    [panelReserved],
  );
  const onSourceResize = useCallback(
    (w: number) => setSourceWidth(clampPanelWidth(w, window.innerWidth, sourceReserved)),
    [sourceReserved],
  );
  const onSourceReset = useCallback(
    () => setSourceWidth(clampPanelWidth(PANEL_DEFAULT_W, window.innerWidth, sourceReserved)),
    [sourceReserved],
  );
  useEffect(() => savePanelWidth(panelWidth), [panelWidth]);
  useEffect(() => savePanelWidth(sourceWidth, SOURCE_WIDTH_KEY), [sourceWidth]);
  // Re-clamp whenever either width / the open-state changes AND on window
  // resize (review-caught: both panes are flex no-shrink, so without a resize
  // re-clamp a window shrink crushes the canvas to 0 with no recovery short of
  // re-dragging a handle). Converges: each pass is non-increasing and bounded.
  useEffect(() => {
    const reclamp = (): void => {
      setPanelWidth((prev) => clampPanelWidth(prev, window.innerWidth, sourceOpen ? sourceWidth : 0));
      setSourceWidth((prev) => clampPanelWidth(prev, window.innerWidth, panelWidth));
    };
    reclamp();
    window.addEventListener("resize", reclamp);
    return () => window.removeEventListener("resize", reclamp);
  }, [panelWidth, sourceOpen, sourceWidth]);

  return { panelWidth, sourceWidth, onPanelResize, onPanelReset, onSourceResize, onSourceReset };
}
