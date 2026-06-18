// The search box at the top of the floating rail — find a node by name (or
// description) in the current workflow and jump to it. The ONE rail item that
// expands in place: the magnifier opens a popover with an input + a
// ranked results list. Selecting a result REVEALS it (GraphView expands the node's
// collapsed ancestor chain) then focuses + cameras — so a node buried in a
// collapsed sub-workflow is still reliably reachable. Read-only navigation; never
// a creation surface.
import { useEffect, useMemo, useRef, useState } from "react";
import { categoryLabel, nodeColor } from "../utils/format";
import { iconFor } from "../utils/icons";
import type { RFNode } from "../types";

const MAX_RESULTS = 20;

// The open shortcut, platform-labelled (the chord is metaKey OR ctrlKey either way).
const SHORTCUT = typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.platform || "") ? "⌘K" : "Ctrl+K";

// node_id prefix (0) > node_id substring (1) > purpose substring (2); capped. A
// stable sort keeps graph order within a score band.
function rankMatches(nodes: readonly RFNode[], query: string): RFNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored: { node: RFNode; score: number }[] = [];
  for (const n of nodes) {
    const name = n.ref.node_id.toLowerCase();
    const purpose = (n.purpose ?? "").toLowerCase();
    let score = -1;
    if (name.startsWith(q)) score = 0;
    else if (name.includes(q)) score = 1;
    else if (purpose.includes(q)) score = 2;
    if (score >= 0) scored.push({ node: n, score });
  }
  scored.sort((a, b) => a.score - b.score);
  return scored.slice(0, MAX_RESULTS).map((s) => s.node);
}

export function RailSearch({
  nodes,
  onSelect,
}: {
  nodes: readonly RFNode[];
  onSelect: (node: RFNode) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useMemo(() => rankMatches(nodes, query), [nodes, query]);

  // Reset the highlighted row whenever the result set changes.
  useEffect(() => setActive(0), [query]);

  // Focus the input when the popover opens.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Close on click-away — a pure popover, no backdrop stealing canvas clicks.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent): void => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Cmd/Ctrl+K toggles the palette from anywhere (preventDefault stops Chrome's
  // omnibox grab). The chord can't collide with text entry — typing "k" alone is
  // untouched. Re-binds on `open` so the toggle reads the current state, not a stale one.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        if (open) {
          setOpen(false);
          setQuery("");
        } else {
          setOpen(true);
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const close = (): void => {
    setOpen(false);
    setQuery("");
  };

  const select = (node: RFNode): void => {
    onSelect(node);
    close();
  };

  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      const node = results[active];
      if (node) select(node);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  };

  return (
    <div className="rail-search" ref={containerRef}>
      <button
        className={"rail-button" + (open ? " active" : "")}
        title={`Search nodes (${SHORTCUT})`}
        aria-label="Search nodes"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
      >
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
          <circle cx="11" cy="11" r="7" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      </button>

      {open && (
        <div className="rail-search-popover">
          <div className="rail-search-field">
            <input
              ref={inputRef}
              className="rail-search-input"
              type="text"
              placeholder="Find a node…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
            />
            {query === "" && <kbd className="rail-search-kbd">{SHORTCUT}</kbd>}
          </div>
          {query.trim() !== "" && results.length === 0 && <div className="rail-search-empty">No matching nodes</div>}
          {results.length > 0 && (
            <ul className="rail-search-results">
              {results.map((node, i) => (
                <li key={node.id}>
                  <button
                    className={"rail-search-result" + (i === active ? " active" : "")}
                    style={{ "--chip-c": nodeColor(node) } as React.CSSProperties}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => select(node)}
                  >
                    <span className="edge-chip-tile">
                      <img src={iconFor(node)} alt="" />
                    </span>
                    <span className="rail-search-result-name">{node.ref.node_id}</span>
                    <span className="rail-search-result-cat">{categoryLabel(node)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
