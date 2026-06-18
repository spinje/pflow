// The side panel's resizable width: clamp policy + persistence. Pure logic here
// so it tests in node-env; the drag gesture lives in components/PanelResizer.tsx.

export const PANEL_DEFAULT_W = 460;
export const PANEL_MIN_W = 300;
export const CANVAS_MIN_W = 320;
const PANEL_MAX_W = 860;
const STORAGE_KEY = "pflow-ui:panel-w";

/** Clamp a requested pane width: hard min, hard max, and enough remaining
 * viewport for the other reserved column plus a usable canvas. */
export function clampPanelWidth(width: number, viewport: number, reserved = 0): number {
  const available = Math.max(PANEL_MIN_W, viewport - reserved - CANVAS_MIN_W);
  const max = Math.max(PANEL_MIN_W, Math.min(PANEL_MAX_W, Math.round(available)));
  return Math.min(max, Math.max(PANEL_MIN_W, Math.round(width)));
}

/** The persisted width, re-clamped against the current viewport; the default
 * when nothing (or garbage) is stored. Storage access is guarded — privacy
 * modes can throw on read. */
export function loadPanelWidth(viewport: number, key = STORAGE_KEY, reserved = 0): number {
  try {
    const raw = Number(window.localStorage.getItem(key));
    if (Number.isFinite(raw) && raw > 0) return clampPanelWidth(raw, viewport, reserved);
  } catch {
    /* storage unavailable — fall through to the default */
  }
  return clampPanelWidth(PANEL_DEFAULT_W, viewport, reserved);
}

export function savePanelWidth(width: number, key = STORAGE_KEY): void {
  try {
    window.localStorage.setItem(key, String(width));
  } catch {
    /* storage unavailable — width just won't persist */
  }
}
