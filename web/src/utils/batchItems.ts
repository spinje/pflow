// Resolve a batch-host param value that references the batch alias (`${item.x}`)
// against the literal batch items — so the ReadPanel can EXPAND `${item.prompt}`
// into the actual per-item values. The items already ride the /api/graph payload
// inline (file-reference prompts are resolved into the IR before the graph is
// built, so `batch.items[i].prompt` is the file's CONTENT, not its path) — this
// is pure display logic over data already in hand: no fetch, no contract change.
//
// Only LITERAL batches expand: a dynamic batch's `${item.x}` has no static items
// (its source is a runtime ref), so there is nothing to resolve. Pure + node-env
// testable (no React, no DOM).

import { fullValue } from "./format";

export interface ResolvedBatchItem {
  /** The item's discriminating scalar fields (those NOT read by the value's
   *  alias refs), e.g. `focus: emotional`; falls back to `item[N]`. */
  label: string;
  /** The param value with every `${alias.path}` ref substituted for THIS item;
   *  non-alias refs (`${content}`) stay verbatim — they are not per-item. */
  value: string;
}

// A `${ … }` reference. We only locate refs here; the model already decided which
// ones draw edges. A non-plain inner (spaces, `??`, operators) parses to null and
// is left untouched — fail-open, never a wrong substitution.
const REF_RE = /\$\{([^}]+)\}/g;

function refSegments(inner: string | undefined): string[] | null {
  if (inner === undefined) return null;
  const trimmed = inner.trim();
  if (!/^[A-Za-z_][\w.]*$/.test(trimmed)) return null;
  return trimmed.split(".");
}

function resolvePath(obj: unknown, segs: string[]): unknown {
  let cur: unknown = obj;
  for (const seg of segs) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[seg];
  }
  return cur;
}

function isScalar(v: unknown): v is string | number | boolean {
  return typeof v === "string" || typeof v === "number" || typeof v === "boolean";
}

/** Whether `value` references `${alias…}` at all (so it resolves per item). */
export function refsBatchAlias(value: unknown, alias: string): boolean {
  if (typeof value !== "string") return false;
  for (const m of value.matchAll(REF_RE)) {
    const segs = refSegments(m[1]);
    if (segs && segs[0] === alias) return true;
  }
  return false;
}

/** The item fields the value reads via the alias (`${item.prompt}` → {"prompt"}). */
function aliasFields(value: string, alias: string): Set<string> {
  const fields = new Set<string>();
  for (const m of value.matchAll(REF_RE)) {
    const segs = refSegments(m[1]);
    const field = segs?.[1];
    if (segs && segs[0] === alias && field !== undefined) fields.add(field);
  }
  return fields;
}

/** Head an item by its OTHER short scalar fields — the part that says WHICH
 *  variant this is (the read field is the body, shown below). */
function itemLabel(item: unknown, index: number, readFields: Set<string>): string {
  if (item == null || typeof item !== "object" || Array.isArray(item)) return `item[${index}]`;
  const parts: string[] = [];
  for (const [k, v] of Object.entries(item as Record<string, unknown>)) {
    if (readFields.has(k) || !isScalar(v)) continue;
    const sv = String(v);
    if (sv.length > 60) continue; // a long scalar belongs in the body, not the header
    parts.push(`${k}: ${sv}`);
  }
  return parts.length ? parts.join(", ") : `item[${index}]`;
}

/** Substitute `${alias.path}` refs in `value` with this item's resolved data;
 *  a missing field or a non-alias ref is left verbatim. */
function substitute(value: string, alias: string, item: unknown): string {
  return value.replace(REF_RE, (whole, inner: string) => {
    const segs = refSegments(inner);
    if (!segs || segs[0] !== alias) return whole;
    const resolved = resolvePath(item, segs.slice(1));
    return resolved === undefined ? whole : fullValue(resolved);
  });
}

/** The per-item expansion of a batch-alias param value, or `null` when there is
 *  nothing to expand: the value is not a string, references no alias field, or
 *  there are no literal items (a dynamic batch). */
export function resolveBatchItems(
  value: unknown,
  alias: string,
  items: readonly unknown[] | null | undefined,
): ResolvedBatchItem[] | null {
  if (typeof value !== "string" || !items || items.length === 0) return null;
  if (!refsBatchAlias(value, alias)) return null;
  const readFields = aliasFields(value, alias);
  return items.map((item, i) => ({
    label: itemLabel(item, i, readFields),
    value: substitute(value, alias, item),
  }));
}
