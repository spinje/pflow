// Presentation helpers shared by the node components and the read panel.
// Pure, dependency-free, unit-testable.

export interface TemplateSegment {
  text: string;
  isRef: boolean;
}

const REF_PATTERN = /\$\{([^}]+)\}/g;

/** Split a string into literal/`${ref}` segments so a param value can render as
 *  text + inline connection chips (one chip per ref). */
export function parseTemplate(value: string): TemplateSegment[] {
  const segments: TemplateSegment[] = [];
  let last = 0;
  for (const match of value.matchAll(REF_PATTERN)) {
    const start = match.index ?? 0;
    if (start > last) {
      segments.push({ text: value.slice(last, start), isRef: false });
    }
    segments.push({ text: match[1] ?? "", isRef: true });
    last = start + match[0].length;
  }
  if (last < value.length) {
    segments.push({ text: value.slice(last), isRef: false });
  }
  return segments;
}

/** Flatten any internal whitespace runs to single spaces (for one-line previews). */
export function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** Cap a string to `max` chars with a trailing ellipsis. */
export function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** A compact, single-line preview of any JSON-able param value. */
export function previewValue(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return truncate(collapseWhitespace(value), 80);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `[${value.length} item${value.length === 1 ? "" : "s"}]`;
  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>);
    return `{${keys.slice(0, 3).join(", ")}${keys.length > 3 ? ", …" : ""}}`;
  }
  return String(value);
}

/** Full pretty value for the read panel (objects/arrays as indented JSON). */
export function fullValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return String(value);
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

// One cohesive color per node type — the node's identity. With Option B (neutral
// tile + native-color icon), the kind color drives the category label, the card's
// left accent, and the source→target edge gradient. Softened for the dark theme:
// pastel enough to read as identity, calm enough not to shout (the "neon green" fix).
const KIND_COLORS: Record<string, string> = {
  shell: "#7ee787",
  http: "#7fb4f5",
  llm: "#8fa6f0",
  "claude-code": "#9c89b8",
  code: "#ffd479",
  python: "#ffd479",
  file: "#5ec8b0",
  mcp: "#ff8fab",
  // Sub-workflow magenta (user-picked via shoot-lab, 2026-06-10): vivid enough to
  // mark structure, clearly apart from mcp's salmon-pink and claude-code's violet.
  workflow: "#e26ad8",
  input: "#94a3b8",
  output: "#ff9eaa",
  end: "#6b7280",
};

const DEFAULT_KIND_COLOR = "#9aa3b5";

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? DEFAULT_KIND_COLOR;
}

// CONDITION — a presented pseudo-kind, not a contract kind. Multi-way routing
// (`next: str = ...`) is a code-node-only capability, so `is_decision ⟹ kind=code`
// and presenting the router AS a condition hides nothing (the read panel still says
// `code · condition`). Hot orange: same warm family as code (it IS code) but hotter
// = the router; distinct from loop amber #f0b86c and warn #f0a07a. Keep equal to
// the CSS `--decision` var (index.css), which branch handles/labels tint from.
export const CONDITION_COLOR = "#ffa657";

// Batch container purple — keep equal to the CSS `--batch` var (index.css), which
// batch badges/group tints read. Used where a component needs the literal color
// (inline --kind on a collapsed batch card; CSS var() doesn't resolve there pre-mount).
export const BATCH_COLOR = "#c79bf0";

// IO teal — the root Inputs/Outputs cards' identity. Keep equal to the CSS
// `--data-edge` var: a workflow's IO is pure data plumbing, so the cards wear the
// data-line color. Literal (not var()) for the same minimap/inline-style reasons.
export const IO_COLOR = "#6fbfa8";

export function isCondition(node: { kind: string; is_decision: boolean }): boolean {
  // The kind gate is defensive: should branching ever extend beyond code nodes,
  // an llm/shell decider keeps its kind identity instead of lying.
  return node.is_decision && node.kind === "code";
}

/** The node's identity color: its kind color, or the condition color for a
 *  decision code node. Drives the card border/tile/category AND the edge
 *  gradients — keep every caller on this, not on raw kindColor(kind). */
export function nodeColor(node: { kind: string; is_decision: boolean }): string {
  return isCondition(node) ? CONDITION_COLOR : kindColor(node.kind);
}

// The small category line on a node card (the kind, e.g. "CLAUDE CODE"). Title-ish
// uppercase; the human description (purpose) is the bold line below it. A decision
// code node presents as CONDITION (role replaces kind — the Tines/n8n model).
export function categoryLabel(node: { kind: string; is_decision: boolean }): string {
  if (isCondition(node)) return "CONDITION";
  return node.kind.replace(/-/g, " ").toUpperCase();
}
