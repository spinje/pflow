// The landing view: every saved workflow from the registry (/api/catalog). Click
// one to open its graph. Shown when `pflow ui` is started with no workflow arg.

import { useEffect, useState } from "react";

import { ApiError, fetchCatalog } from "../api/client";
import type { CatalogItem } from "../types";

export function CatalogView({ onOpen }: { onOpen: (workflow: string) => void }): JSX.Element {
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e));
      });
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
              <span className="catalog-item-name">{item.name}</span>
              {item.description && <span className="catalog-item-desc">{item.description}</span>}
              <span className="catalog-item-path">{item.path}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
