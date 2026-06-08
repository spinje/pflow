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

const KIND_GLYPHS: Record<string, string> = {
  shell: "$_",
  http: "🌐",
  llm: "✦",
  file: "📄",
  mcp: "🔌",
  python: "🐍",
  code: "{ }",
  "claude-code": "◆",
  workflow: "▣",
  input: "▸",
  output: "◂",
  end: "■",
};

export function kindGlyph(kind: string): string {
  return KIND_GLYPHS[kind] ?? "●";
}

// One cohesive color per node type — the node's identity. Edges take their source
// node's color (a stepping stone to the deferred source→target gradient). Tuned
// for the dark theme: saturated enough to differentiate, calm enough not to shout.
const KIND_COLORS: Record<string, string> = {
  shell: "#34d399",
  http: "#38bdf8",
  llm: "#a78bfa",
  "claude-code": "#818cf8",
  code: "#fbbf24",
  python: "#fbbf24",
  file: "#2dd4bf",
  mcp: "#f472b6",
  workflow: "#60a5fa",
  input: "#94a3b8",
  output: "#fb7185",
  end: "#6b7280",
};

const DEFAULT_KIND_COLOR = "#9aa3b5";

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? DEFAULT_KIND_COLOR;
}
