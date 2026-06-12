// The side panel's resizable width: clamp policy + persistence. Pure logic here
// so it tests in node-env; the drag gesture lives in components/PanelResizer.tsx.

export const PANEL_DEFAULT_W = 460;
export const PANEL_MIN_W = 300;
const PANEL_MAX_W = 860;
const STORAGE_KEY = "pflow-ui:panel-w";

/** Clamp a requested panel width: hard min, hard max, and never more than 70%
 * of the viewport (the canvas must stay usable on narrow windows). */
export function clampPanelWidth(width: number, viewport: number): number {
  const max = Math.max(PANEL_MIN_W, Math.min(PANEL_MAX_W, Math.round(viewport * 0.7)));
  return Math.min(max, Math.max(PANEL_MIN_W, Math.round(width)));
}

/** The persisted width, re-clamped against the current viewport; the default
 * when nothing (or garbage) is stored. Storage access is guarded — privacy
 * modes can throw on read. */
export function loadPanelWidth(viewport: number): number {
  try {
    const raw = Number(window.localStorage.getItem(STORAGE_KEY));
    if (Number.isFinite(raw) && raw > 0) return clampPanelWidth(raw, viewport);
  } catch {
    /* storage unavailable — fall through to the default */
  }
  return clampPanelWidth(PANEL_DEFAULT_W, viewport);
}

export function savePanelWidth(width: number): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(width));
  } catch {
    /* storage unavailable — width just won't persist */
  }
}
