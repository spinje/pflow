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

/** Whether a `${...}` ref BODY belongs to `highlightRef`. Matching is per
 *  coalesce OPERAND — `${a.b ?? "fallback"}` matches highlightRef "a.b" (a
 *  whole-text compare never matched coalesce-authored refs): an operand counts
 *  when it equals the ref or extends it with a dot path. */
export function refMatchesHighlight(refBody: string, highlightRef: string): boolean {
  return refBody
    .split("??")
    .map((op) => op.trim())
    .some((op) => op === highlightRef || op.startsWith(`${highlightRef}.`));
}

/** Flatten any internal whitespace runs to single spaces (for one-line previews). */
export function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** Cap a string to `max` chars with a trailing ellipsis. */
export function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

// stripMarkdown is a display DE-NOISER for surfaces that cannot render formatting
// (the 2-line canvas description, title= tooltips) — NOT a markdown parser. It
// hides marker symbols while keeping every character of content; when in doubt it
// under-strips (a stray `*` on the canvas is noise; "2*3" → "23" is corruption).
//
// Emphasis pairing is deliberately MORE conservative than CommonMark:
// - an OPENER must not sit inside a word (CommonMark allows intraword `*`, so
//   the panel italicizes "2*3 and 4*5" — but stripping those asterisks would
//   corrupt arithmetic, and "*.tmp and *.log" must keep its globs);
// - the captured tail is the rule's own non-delimiter class, never bare \S
//   ("use *args and **kwargs" must not pair the first `*` into the `**` —
//   review-caught: \S happily matched a delimiter);
// - content never crosses a blank line (CommonMark parses inlines per
//   paragraph, so pairing across paragraphs would hide markers the panel shows);
// - `_` refuses an intraword CLOSE ("_private_var" keeps its underscores,
//   exactly as CommonMark renders it).
const MD_STRIP_RULES: Array<[RegExp, string]> = [
  [/!\[([^\]]*)\]\([^)]*\)/g, "$1"], // images → alt (before links: same tail shape)
  [/\[([^\]]+)\]\([^)]*\)/g, "$1"], // links → text
  [/^[ \t]{0,3}#{1,6}[ \t]+/gm, ""], // ATX heading markers
  [/^[ \t]*(?:>[ \t]?)+/gm, ""], // blockquote markers (incl. nested >>)
  [/^[ \t]*(?:[-*+]|\d{1,9}\.)[ \t]+/gm, ""], // list markers
  [/(?<![\w*])\*\*(?=\S)((?:[^*\n]|\n(?!\s*\n)|\*(?!\*))*?[^\s*])\*\*(?!\*)/g, "$1"], // **strong**
  [/(?<![\w_])__(?=\S)((?:[^_\n]|\n(?!\s*\n)|_(?!_))*?[^\s_])__(?![\w_])/g, "$1"], // __strong__
  [/(?<![\w*])\*(?=[^\s*])((?:[^*\n]|\n(?!\s*\n))*[^\s*])\*(?!\*)/g, "$1"], // *emphasis*
  [/(?<![\w_])_(?=[^\s_])((?:[^_\n]|\n(?!\s*\n))*[^\s_])_(?![\w_])/g, "$1"], // _emphasis_
];

/** Strip markdown markers for plain-text surfaces (canvas description lines,
 *  tooltips), keeping all content, then collapse whitespace to one line. Never
 *  throws; unpaired/ambiguous markers stay verbatim (under-strip by design). */
export function stripMarkdown(text: string): string {
  // Code-span CONTENT is shielded first (CommonMark protects it — the marker
  // rules must never see it: `__init__` keeps its dunders while the backticks
  // drop). Spans lift out to placeholders, the rules run, the content restores.
  const spans: string[] = [];
  let s = text.replace(/`([^`\n]+)`/g, (_m, content: string) => {
    spans.push(content);
    return `\u0000${spans.length - 1};`;
  });
  for (const [pattern, replacement] of MD_STRIP_RULES) {
    s = s.replace(pattern, replacement);
  }
  s = s.replace(/\u0000(\d+);/g, (_m, i: string) => spans[Number(i)] ?? "");
  return collapseWhitespace(s);
}

// What language a param VALUE is, for syntax highlighting — fail-closed: null
// means "render as plain text, exactly as before". Branch on the value's TYPE
// first (a dict-authored param ships as a JSON object regardless of name; a
// name like `output_schema` can legally hold a templated STRING), then on the
// few (kind, name) pairs whose string content has a known language. Everything
// else — http bodies, write-file content, mcp params (tool-defined names,
// unenumerable), templates — stays plain. No content sniffing.
export function paramLanguage(kind: string, name: string, value: unknown): string | null {
  if (typeof value === "object" && value !== null) return "json"; // fullValue() renders it as JSON
  if (typeof value !== "string") return null; // the language rules below describe string content
  if (kind === "code" && name === "code") return "python";
  if (kind === "shell" && name === "command") return "bash";
  // Prompts color as markdown SOURCE (VS Code-style), never rendered (user decision).
  if (kind === "llm" && (name === "prompt" || name === "system")) return "markdown";
  if (kind === "claude-code" && (name === "prompt" || name === "system_prompt")) return "markdown";
  return null;
}

/** Present an edge's input_name as a binding label. `prompt_cache` is the
 *  contract's reserved name for a `## Cache` chunk dependency — no param row
 *  exists for it, so the raw sentinel must never reach the user. */
export function bindingLabel(inputName: string): string {
  return inputName === "prompt_cache" ? "cached prefix" : inputName;
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

// TRANSFORM — the second presented pseudo-kind: a code node whose AST provably
// only reshapes data into `result` (RFNode.is_transform — classified FAIL-CLOSED
// in Python; unlike is_decision the frontend cannot derive it, it needs the AST).
// Cyan (user-picked via shoot-lab 2026-06-10): free hue space, clearly apart from
// the muted file/IO teals, shell green, and the warm code/condition family. A pure
// decider sets `next` and is excluded by the classifier, so CONDITION and
// TRANSFORM can never both claim a node — the isCondition-first order below is
// purely defensive.
export const TRANSFORM_COLOR = "#5fd4dd";

type RoleFacts = { kind: string; is_decision: boolean; is_transform: boolean };

export function isCondition(node: { kind: string; is_decision: boolean }): boolean {
  // The kind gate is defensive: should branching ever extend beyond code nodes,
  // an llm/shell decider keeps its kind identity instead of lying.
  return node.is_decision && node.kind === "code";
}

export function isTransform(node: { kind: string; is_transform: boolean }): boolean {
  // Same defensive kind gate as isCondition.
  return node.is_transform && node.kind === "code";
}

/** The node's identity color: its kind color, or the role color for a code node
 *  presenting as CONDITION / TRANSFORM. Drives the card border/tile/category AND
 *  the edge gradients — keep every caller on this, not on raw kindColor(kind). */
export function nodeColor(node: RoleFacts): string {
  if (isCondition(node)) return CONDITION_COLOR;
  if (isTransform(node)) return TRANSFORM_COLOR;
  return kindColor(node.kind);
}

// The small category line on a node card (the kind, e.g. "CLAUDE CODE"). Title-ish
// uppercase; the human description (purpose) is the bold line below it. A code
// node's ROLE replaces its kind (the Tines/n8n model): CONDITION / TRANSFORM.
export function categoryLabel(node: RoleFacts): string {
  if (isCondition(node)) return "CONDITION";
  if (isTransform(node)) return "TRANSFORM";
  return node.kind.replace(/-/g, " ").toUpperCase();
}

/** A node_id presented as a human name (beautiful density): `my-nice-node` →
 *  "My nice node". Dumb and reversible — dashes/underscores become spaces, only
 *  the FIRST character uppercases, all other casing is preserved (`fetch-HTML` →
 *  "Fetch HTML", never "Fetch Html"). Advanced shows the id verbatim (the exact
 *  `${ref}` key); the verbatim id always rides the label's tooltip. */
export function humanizeId(id: string): string {
  const spaced = id.replace(/[-_]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
