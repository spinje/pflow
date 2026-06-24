// The landing view: every saved workflow from the registry (/api/catalog). Click
// one to open its graph. Shown when `pflow ui` is started with no workflow arg.

import { useEffect, useState } from "react";

import { ApiError, fetchCatalog, fetchRuns } from "../api/client";
import { Markdown } from "../components/Markdown";
import type { CatalogItem } from "../types";

export function CatalogView({ onOpen }: { onOpen: (workflow: string) => void }): JSX.Element {
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Task 173 D6: the absolute paths of workflows with a LIVE run, so we can flag them "● running".
  // Its OWN fetch + catch (DR-6) — a runs-fetch failure simply shows no badges, never blanks the catalog.
  const [liveWorkflows, setLiveWorkflows] = useState<ReadonlySet<string>>(() => new Set());

  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e));
      });
    fetchRuns()
      .then((runs) => {
        if (cancelled) return;
        setLiveWorkflows(new Set(runs.filter((r) => r.live && r.workflow_path).map((r) => r.workflow_path as string)));
      })
      .catch(() => undefined); // DR-6: no badge on failure; the catalog itself is unaffected
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="catalog">
      <header className="catalog-header">
        <h1>pflow workflows</h1>
        <p>Pick a workflow to see its structure, wiring, and prompts.</p>
      </header>

      {error && <div className="banner error">Could not load the catalog: {error}</div>}
      {!items && !error && <div className="catalog-empty">Loading…</div>}
      {items && items.length === 0 && (
        <div className="catalog-empty">
          No saved workflows yet. Open one directly with <code>pflow ui path/to/workflow.pflow.md</code>.
        </div>
      )}

      <ul className="catalog-list">
        {items?.map((item) => (
          <li key={item.path}>
            <button className="catalog-item" onClick={() => onOpen(item.name)}>
              <span className="catalog-item-name">
                {item.name}
                {liveWorkflows.has(item.path) && (
                  <span className="catalog-item-running" title="A run is in progress">
                    <span className="run-dot" aria-hidden /> running
                  </span>
                )}
              </span>
              {/* inline-only markdown: bold/code render, block constructs
                  flatten — one row must stay one flowing line */}
              {item.description && (
                <span className="catalog-item-desc">
                  <Markdown text={item.description} inline />
                </span>
              )}
              <span className="catalog-item-path">{item.path}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
