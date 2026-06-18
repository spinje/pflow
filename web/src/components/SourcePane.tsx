import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import type { ElementContent } from "hast";

import type { RFGraph, RFNode, SourceFiles } from "../types";
import { buildDecoratedLines, decorateLinesSync } from "../graph/sourceDecorate";
import { highlight } from "../utils/highlight";
import {
  breadcrumbFor,
  fileChainFor,
  nodeAtLine,
  nodeBlockRange,
  sectionBlockRange,
  sectionHeadingLine,
  wrappableLines,
  type Crumb,
} from "../utils/sourceMap";
import { resolveEndpointFlatId } from "../utils/viewParams";

interface SourcePaneProps {
  source: SourceFiles | null;
  sourceError: string | null;
  graph: RFGraph | null;
  selectedNode: RFNode | null;
  // The selected ROOT io card's kind (inputs/outputs) — io selections carry no
  // node, and input ports carry no SourceRef; the sync target is the `##
  // Inputs`/`## Outputs` section heading found in the root file's TEXT.
  selectedIoKind: "input" | "output" | null;
  renderedIds: ReadonlySet<string>;
  workflowName: string;
  // A monotonic counter GraphView bumps when the read panel's source link is
  // clicked: re-assert the selected node's file/line and scroll to it, even
  // when the pane already shows it (the user scrolled away) or browsed to
  // another file via a breadcrumb. The closed→open case is the selectedNode
  // effect's job (the pane mounts already pointed at the node).
  jump: number;
  onNavigate: (focus: string, selectedId?: string | null) => void;
}

interface HighlightCacheEntry {
  text: string;
  lines: ReactNode[];
}

export function SourcePane({
  source,
  sourceError,
  graph,
  selectedNode,
  selectedIoKind,
  renderedIds,
  workflowName,
  jump,
  onNavigate,
}: SourcePaneProps): JSX.Element {
  const [currentFile, setCurrentFile] = useState<string | null>(null);
  const [activeLine, setActiveLine] = useState<number | null>(null);
  const [missingFile, setMissingFile] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<{ file: string; text: string; lines: ReactNode[] } | null>(null);
  const highlightCache = useRef(new Map<string, HighlightCacheEntry>());
  const lineRefs = useRef(new Map<number, HTMLDivElement>());
  const prevJump = useRef(jump);

  const files = source?.files ?? {};
  const availableFiles = useMemo(() => Object.keys(files).sort(), [files]);
  const displayedFile = currentFile && hasFile(files, currentFile) ? currentFile : null;
  const text = displayedFile ? files[displayedFile]! : null;

  useEffect(() => {
    if (!source) {
      setCurrentFile(null);
      setActiveLine(null);
      setMissingFile(null);
      return;
    }
    const next = initialFile(source);
    setCurrentFile((prev) => (prev && hasFile(source.files, prev) ? prev : next));
  }, [source]);

  useEffect(() => {
    if (!source) return;
    const ref = selectedNode?.source;
    if (!ref?.file) {
      // A selection with no source (edge/io/input) keeps the current file but
      // must not leave a stale could-not-read notice up (review-caught).
      setMissingFile(null);
      return;
    }
    if (!hasFile(source.files, ref.file)) {
      setMissingFile(ref.file);
      return;
    }
    setMissingFile(null);
    setCurrentFile(ref.file);
    // Always set — a null line CLEARS the mark, so a file switch never carries
    // the previous file's line number into the new file (review-caught: the
    // stale line rendered active and got scrolled to as if it were a mapping).
    setActiveLine(ref.line);
  }, [selectedNode, source, source?.files]);

  // A ROOT io card selection syncs to its section heading in the root file —
  // the interface's authored home (io selections set no selectedNode, and the
  // contract gives input ports no SourceRef; the heading comes from the text).
  useEffect(() => {
    if (!source || !selectedIoKind) return;
    const root = source.root;
    if (!root || !hasFile(source.files, root)) return;
    setMissingFile(null);
    setCurrentFile(root);
    setActiveLine(sectionHeadingLine(source.files[root]!, selectedIoKind));
  }, [selectedIoKind, source]);

  // The read panel's source-link JUMP (GraphView bumps `jump`): re-assert the
  // selected node's file + line and scroll to it. The guard makes it act ONLY
  // when `jump` actually changed (the other deps re-run it harmlessly). A
  // SAME-file jump sets no new state, so the scroll effect below won't re-fire
  // — scroll directly (lineRefs are current); a file CHANGE re-renders and the
  // scroll effect (keyed on displayedFile) does the scroll.
  useEffect(() => {
    if (jump === prevJump.current) return;
    prevJump.current = jump;
    const ref = selectedNode?.source;
    if (!source || !ref?.file || !hasFile(source.files, ref.file)) return;
    setMissingFile(null);
    const fileChanged = currentFile !== ref.file;
    setCurrentFile(ref.file);
    setActiveLine(ref.line);
    if (!fileChanged && ref.line != null) {
      lineRefs.current.get(ref.line)?.scrollIntoView?.({ block: "center" });
    }
  }, [jump, source, selectedNode, currentFile]);

  useEffect(() => {
    if (!displayedFile || text == null) return;
    const cached = highlightCache.current.get(displayedFile);
    if (cached?.text === text) {
      setHighlighted({ file: displayedFile, text, lines: cached.lines });
      return;
    }
    setHighlighted((prev) => (prev?.file === displayedFile && prev.text === text ? prev : null));
    let cancelled = false;
    void buildDecoratedLines(text, highlight).then((perLine) => {
      if (cancelled) return;
      const lines = toLineNodes(perLine);
      highlightCache.current.set(displayedFile, { text, lines });
      setHighlighted({ file: displayedFile, text, lines });
    });
    return () => {
      cancelled = true;
    };
  }, [displayedFile, text]);

  // NOT keyed on `highlighted`: the plain→colored upgrade replaces row CONTENT
  // in place (same keys, same positions), and re-centering on it would yank the
  // viewport away from wherever the user scrolled in the interim.
  useEffect(() => {
    if (activeLine == null || displayedFile == null) return;
    lineRefs.current.get(activeLine)?.scrollIntoView?.({ block: "center" });
  }, [activeLine, displayedFile]);

  // Instant tier: body tokens + fence info colored without waiting for shiki
  // (no async, no flash of raw text); the effect above upgrades fence CONTENT to
  // its grammar once shiki resolves.
  const instantLines = useMemo(() => toLineNodes(decorateLinesSync(text ?? "")), [text]);
  const renderedLines = highlighted?.file === displayedFile && highlighted.text === text ? highlighted.lines : instantLines;
  // The owning node's whole authored block gets a barely-visible extent tint;
  // the active line itself keeps the stronger mark on top of it.
  const activeRange = useMemo(() => {
    if (activeLine == null || !graph || !displayedFile || text == null) return null;
    // A `#`/`##` SECTION heading (io-card selections, section-line clicks)
    // tints its whole section — same extent rule as a node's block.
    return sectionBlockRange(text, activeLine) ?? nodeBlockRange(graph, displayedFile, activeLine, text);
  }, [activeLine, graph, displayedFile, text]);
  // Prose wraps at the pane width; fenced code/prompts keep exact layout + scroll.
  const wrappable = useMemo(() => (text != null ? wrappableLines(text) : []), [text]);
  const crumbs = graph && displayedFile ? sourceCrumbs(displayedFile, selectedNode, graph, workflowName) : [];
  const missingNotice = missingFile ? `source for ${fileName(missingFile)} could not be read` : null;

  const selectLine = (line: number): void => {
    setActiveLine(line);
    if (!graph || !displayedFile) return;
    const candidates = nodeAtLine(graph, displayedFile, line);
    for (const candidate of candidates) {
      const flatId = resolveEndpointFlatId(graph, renderedIds, candidate.id);
      if (flatId) {
        onNavigate(flatId, flatId);
        return;
      }
    }
  };

  const clickCrumb = (crumb: Crumb): void => {
    if (crumb.file && hasFile(files, crumb.file)) {
      setCurrentFile(crumb.file);
      setMissingFile(null);
      // A line-less crumb (root/file crumbs) CLEARS the mark — carrying the
      // previous file's line into the new file marks a meaningless row.
      setActiveLine(crumb.line);
    } else if (crumb.file) {
      setMissingFile(crumb.file);
    }
    if (!graph || !crumb.hostContractId) return;
    const flatId = resolveEndpointFlatId(graph, renderedIds, crumb.hostContractId);
    if (flatId) onNavigate(flatId, flatId);
  };

  return (
    <aside className="source-pane">
      <header className="source-pane-header">
        <nav className="source-crumbs" aria-label="Source file breadcrumb">
          {crumbs.length > 0 ? (
            crumbs.map((crumb, index) => (
              <button
                key={`${crumb.label}-${index}`}
                className="source-crumb"
                disabled={!crumb.file && !crumb.hostContractId}
                onClick={() => clickCrumb(crumb)}
                title={crumb.file ?? crumb.label}
              >
                {crumb.label}
              </button>
            ))
          ) : (
            <span className="source-crumb source-crumb-muted">source</span>
          )}
        </nav>
      </header>

      {sourceError && <div className="source-pane-notice error">{sourceError}</div>}
      {missingNotice && <div className="source-pane-notice">{missingNotice}</div>}

      {!source && !sourceError && <div className="source-pane-empty">Loading source…</div>}
      {source && availableFiles.length === 0 && <div className="source-pane-empty">No source file is available for this workflow.</div>}
      {source && availableFiles.length > 0 && !displayedFile && (
        <div className="source-pane-empty">Select a source file from the workflow.</div>
      )}
      {displayedFile && text != null && (
        <div className="source-code" aria-label={displayedFile}>
          {renderedLines.map((line, index) => {
            const lineNumber = index + 1;
            const inBlock = activeRange != null && lineNumber >= activeRange.start && lineNumber <= activeRange.end;
            return (
              <div
                className={`src-line${wrappable[index] ? " src-line-wrap" : ""}${inBlock ? " src-line-block" : ""}${activeLine === lineNumber ? " src-line-active" : ""}`}
                data-line={lineNumber}
                key={lineNumber}
                onClick={() => selectLine(lineNumber)}
                ref={(el) => {
                  if (el) lineRefs.current.set(lineNumber, el);
                  else lineRefs.current.delete(lineNumber);
                }}
              >
                <span className="src-gutter">{lineNumber}</span>
                <span className="src-content">{line}</span>
              </div>
            );
          })}
        </div>
      )}
    </aside>
  );
}

function sourceCrumbs(file: string, selectedNode: RFNode | null, graph: RFGraph, workflowName: string): Crumb[] {
  if (selectedNode?.source?.file === file) return breadcrumbFor(selectedNode, graph, workflowName);
  return fileChainFor(file, graph, workflowName);
}

/** One ReactNode per source line, from the decoration module's per-line hast. */
function toLineNodes(perLine: ElementContent[][]): ReactNode[] {
  return perLine.map((children) => toJsxRuntime({ type: "root", children }, { Fragment, jsx, jsxs }));
}

function initialFile(source: SourceFiles): string | null {
  if (source.root && hasFile(source.files, source.root)) return source.root;
  return Object.keys(source.files).sort()[0] ?? null;
}

function hasFile(files: Record<string, string>, file: string): boolean {
  return Object.prototype.hasOwnProperty.call(files, file);
}

function fileName(file: string): string {
  return file.split(/[\\/]/).pop() ?? file;
}
