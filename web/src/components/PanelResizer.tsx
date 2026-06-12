import { useCallback } from "react";

interface PanelResizerProps {
  /** Reports the pointer-derived panel width (viewport right edge → pointer);
   * the owner clamps and applies it. */
  onResize: (width: number) => void;
  /** Double-click resets to the default width. */
  onReset: () => void;
}

/** The drag handle between the canvas and the side panel. Zero-width in the
 * flex row (negative margins straddle the panel's left border), so it adds no
 * visual gap — only a col-resize hit area. Pointer capture keeps the drag
 * alive when the pointer outruns the 9px strip. */
export function PanelResizer({ onResize, onReset }: PanelResizerProps): JSX.Element {
  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      const el = e.currentTarget;
      el.setPointerCapture?.(e.pointerId); // optional-call: jsdom has no pointer capture
      const move = (ev: PointerEvent) => onResize(window.innerWidth - ev.clientX);
      const stop = () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", stop);
        el.removeEventListener("pointercancel", stop);
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", stop);
      el.addEventListener("pointercancel", stop);
    },
    [onResize],
  );

  return (
    <div
      className="panel-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
      title="Drag to resize · double-click to reset"
      onPointerDown={onPointerDown}
      onDoubleClick={onReset}
    />
  );
}
