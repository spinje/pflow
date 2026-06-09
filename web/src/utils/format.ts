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
  workflow: "#a3b18a",
  input: "#94a3b8",
  output: "#ff9eaa",
  end: "#6b7280",
};

const DEFAULT_KIND_COLOR = "#9aa3b5";

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? DEFAULT_KIND_COLOR;
}

// The small category line on a node card (the kind, e.g. "CLAUDE CODE"). Title-ish
// uppercase; the human description (purpose) is the bold line below it.
export function categoryLabel(node: { kind: string }): string {
  return node.kind.replace(/-/g, " ").toUpperCase();
}
