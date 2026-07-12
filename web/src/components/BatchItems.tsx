// The flat batch-items listing: every LITERAL batch item with ALL its fields —
// short scalars inline, long values collapsed to a size pill that expands to the
// full content (colored like the matching param). Complements ParamBlock's
// `${item.x}` expansion: that shows what ONE param resolves to; this shows the
// raw item config, including fields no visible param reads. Items already ride
// the /api/graph payload (file-reference values resolved inline), so this is pure
// display — no fetch, no contract change. A DYNAMIC batch has no static items, so
// the block is absent.

import { useState } from "react";

import { fullValue, paramLanguage } from "../utils/format";
import { CodeBlock } from "./CodeBlock";
import type { BatchSpec } from "../types";

function sizeLabel(text: string): string {
  return text.length >= 1024 ? `${(text.length / 1024).toFixed(1)} KB` : `${text.length} chars`;
}

// Short enough to read on one line (the same 60-char cutoff ParamBlock's header
// uses): scalars yes, a long/multiline string no.
function isInline(value: unknown): value is string | number | boolean {
  if (typeof value === "number" || typeof value === "boolean") return true;
  return typeof value === "string" && value.length <= 60 && !value.includes("\n");
}

/** One field of one item — `name: value` inline, or a `▸ name <size>` disclosure
 *  for a long/object value. `name` is "" for a scalar item (`items: ["a"]`). */
function ItemField({ name, value, kind }: { name: string; value: unknown; kind: string }): JSX.Element {
  const [open, setOpen] = useState(false);
  if (isInline(value)) {
    return (
      <div className="batch-field">
        {name && <span className="batch-field-name">{name}:</span>}{" "}
        <span className="batch-field-val">{String(value)}</span>
      </div>
    );
  }
  const text = fullValue(value);
  const isObject = typeof value === "object" && value !== null;
  return (
    <div className="batch-field">
      <button className="batch-field-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? "▾" : "▸"} {name && <span className="batch-field-name">{name}</span>}{" "}
        <span className="batch-field-size">{isObject ? "{…}" : sizeLabel(text)}</span>
      </button>
      {open && <CodeBlock code={text} lang={paramLanguage(kind, name, value)} expandLabel={name || "item"} />}
    </div>
  );
}

function BatchItem({ item, index, kind }: { item: unknown; index: number; kind: string }): JSX.Element {
  const entries =
    item != null && typeof item === "object" && !Array.isArray(item)
      ? Object.entries(item as Record<string, unknown>)
      : null;
  return (
    <div className="batch-item">
      <div className="batch-item-index">item[{index}]</div>
      <div className="batch-item-fields">
        {entries ? (
          entries.map(([k, v]) => <ItemField name={k} value={v} kind={kind} key={k} />)
        ) : (
          // a scalar/list item (`items: ["a", "b"]`) — its bare value, no field name
          <ItemField name="" value={item} kind={kind} />
        )}
      </div>
    </div>
  );
}

/** The full literal batch config: every item, every field. Collapsed by default
 *  (it can be long). Returns null for a dynamic batch or an empty/absent item
 *  list (nothing static to show). */
export function BatchItemsBlock({ batch, kind }: { batch: BatchSpec; kind: string }): JSX.Element | null {
  const items = batch.dynamic ? null : batch.items;
  const [open, setOpen] = useState(false);
  if (!items || items.length === 0) return null;
  return (
    <section className="batch-block">
      <button className="batch-block-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? "▾" : "▸"} batch items <span className="batch-block-count">{items.length}</span>
      </button>
      {open && (
        <div className="batch-list">
          {items.map((item, i) => (
            <BatchItem item={item} index={i} kind={kind} key={i} />
          ))}
        </div>
      )}
    </section>
  );
}
