// Canvas-language decoration for the source pane's verbatim `.pflow.md` view.
// Pure (no React, no DOM) so it runs in node-env tests. Produces ONE hast
// ElementContent[] per source line — the source pane renders each line as a
// `.src-line` row, so the line count MUST equal `text.split("\n").length`
// (asserted below in dev). Two tiers:
//   decorateLinesSync(text)            — instant: headings/keys/fence-info
//     colored, fence + PROSE content plain (+ teal refs). No shiki, paints now.
//   buildDecoratedLines(text, hl)      — full: the above, with fence AND prose
//     content highlighted in its grammar (prompt→markdown, command→bash, prose
//     →markdown). Prose is colored markdown SOURCE + teal refs (like prompts).
//
// The scheme is "Canvas language" (the user pick): `- type:` values + node-name
// headings take their canvas KIND color (format.kindColor — one source of
// truth); input/output headings take a faded IO color (CSS .src-io-*); `${refs}`
// are teal; structural keys are muted. Fences and description PROSE stay faithful
// to the file (the ```python lines / the `**bold**` source show), highlighted in
// their grammar — the language word kind-colored, the pflow role word muted.

import type { ElementContent, Properties, Root } from "hast";

import { kindColor } from "../utils/format";
import { codeChildren } from "../utils/highlight";

// A fence info string = optional language word + optional pflow role word.
const ROLE_GRAMMAR: Record<string, string> = { prompt: "markdown", cache: "markdown", command: "bash" };
const LANG_GRAMMAR: Record<string, string> = {
  shell: "bash", sh: "bash", bash: "bash", python: "python", py: "python", json: "json", yaml: "yaml", markdown: "markdown", md: "markdown",
};
// Which fence/value language words map to a node-KIND color (others stay muted).
const LANG_KIND: Record<string, string> = { shell: "shell", bash: "shell", sh: "shell", python: "code", py: "code" };

const REF_RE = /\$\{[^}]+\}/g;

// --- hast helpers ---
const txt = (value: string): ElementContent => ({ type: "text", value });
function span(className: string | string[], children: ElementContent[], style?: string): ElementContent {
  const properties: Properties = { className: Array.isArray(className) ? className : [className] };
  if (style) properties.style = style;
  return { type: "element", tagName: "span", properties, children };
}

/** Split a string into plain text + teal `${ref}` spans. */
function refSegments(text: string): ElementContent[] {
  if (!text.includes("${")) return text ? [txt(text)] : [];
  const out: ElementContent[] = [];
  let last = 0;
  REF_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = REF_RE.exec(text)) !== null) {
    if (m.index > last) out.push(txt(text.slice(last, m.index)));
    out.push(span("src-ref", [txt(m[0])]));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(txt(text.slice(last)));
  return out;
}

/** Wrap every `${ref}` in shiki's hast output (text nodes) with the teal span,
 *  in place — refs inside a prompt/prose are the point, like markRefs. */
function markAllRefs(nodes: ElementContent[]): void {
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    if (!n) continue;
    if (n.type === "element") {
      markAllRefs(n.children);
      continue;
    }
    if (n.type !== "text" || !n.value.includes("${")) continue;
    const segs = refSegments(n.value);
    nodes.splice(i, 1, ...segs);
    i += segs.length - 1;
  }
}

/** The grammar to highlight a fence's CONTENT with: an explicit language word
 *  wins; else infer from the pflow role; else null (plain — text/mermaid). */
export function fenceGrammar(info: string): string | null {
  const parts = info.toLowerCase().split(/\s+/).filter(Boolean);
  for (const p of parts) if (LANG_GRAMMAR[p]) return LANG_GRAMMAR[p];
  for (const p of parts) if (ROLE_GRAMMAR[p]) return ROLE_GRAMMAR[p];
  return null;
}

// A `###`+ heading's color source: a node heading takes its block's `- type:`
// KIND color; an input/output heading (under `## Inputs`/`## Outputs`) takes a
// faded IO color instead — its `type:` is a DATA type (string/integer/…) which
// is not a node kind and would otherwise fall through to grey.
interface HeadingColor {
  kind?: string;
  io?: "input" | "output";
}

type LineSpec =
  | { t: "body"; text: string; headingColor: HeadingColor | null }
  | { t: "prose"; bi: number; ci: number }
  | { t: "fopen"; fence: string; info: string }
  | { t: "fclose"; text: string }
  | { t: "fbody"; fi: number; ci: number };

interface FenceBlock {
  grammar: string | null;
  content: string[];
}

interface ProseBlock {
  content: string[];
}

const FENCE_OPEN_RE = /^(`{3,}|~{3,})/;
const HEADING_RE = /^#{1,6}(\s|$)/;
const KEY_RE = /^\s*[-*]\s+[A-Za-z][\w-]*\s*:/;

/** A line that's neither blank, a heading, a `- key:` line, nor a fence open —
 *  i.e. description prose, highlighted as markdown SOURCE (+ teal refs). */
function isProseLine(line: string): boolean {
  return line.trim() !== "" && !HEADING_RE.test(line) && !KEY_RE.test(line) && !FENCE_OPEN_RE.test(line);
}

/** Per `###`+ heading line, how to color it: by enclosing `## Inputs`/`##
 *  Outputs` section (io), else by the `type:` kind declared in its block.
 *  Forward-scan the block to the next heading; absent → no color (grey). */
function headingColors(lines: string[]): Map<number, HeadingColor> {
  const map = new Map<number, HeadingColor>();
  let io: "input" | "output" | null = null;
  for (let i = 0; i < lines.length; i++) {
    const sec = /^##\s+(\S+)/.exec(lines[i]!);
    if (sec) {
      const name = sec[1]!.toLowerCase();
      io = name === "inputs" ? "input" : name === "outputs" ? "output" : null;
      continue; // a `##` line is a section heading, never a node
    }
    if (!/^#{3,}\s+\S/.test(lines[i]!)) continue;
    if (io) {
      map.set(i, { io });
      continue;
    }
    for (let j = i + 1; j < lines.length; j++) {
      if (/^#{1,6}\s/.test(lines[j]!)) break;
      const t = /^\s*[-*]\s+type\s*:\s*(\S+)/.exec(lines[j]!);
      if (t) {
        map.set(i, { kind: t[1]! });
        break;
      }
    }
  }
  return map;
}

/** Walk lines into specs (one per source line) + the fence/prose content blocks.
 *  Fences match the PARSER's rule: 3+ of ` or ~, closing only on a same-char
 *  fence of >= length — so a ````prompt block may contain inner ```. Contiguous
 *  PROSE lines group into a markdown block (broken by headings/keys/blanks —
 *  markdown inlines are per-paragraph). */
function scan(text: string): { specs: LineSpec[]; fences: FenceBlock[]; proseBlocks: ProseBlock[] } {
  const lines = text.split("\n");
  const heads = headingColors(lines);
  const specs: LineSpec[] = [];
  const fences: FenceBlock[] = [];
  const proseBlocks: ProseBlock[] = [];
  let i = 0;
  while (i < lines.length) {
    const open = /^(`{3,}|~{3,})(.*)$/.exec(lines[i]!);
    if (open) {
      const fence = open[1]!;
      const info = open[2]!.trim();
      const fi = fences.length;
      specs.push({ t: "fopen", fence, info });
      const closeRe = new RegExp("^\\" + fence[0] + "{" + fence.length + ",}\\s*$");
      const content: string[] = [];
      i++;
      let ci = 0;
      let closeText: string | null = null;
      while (i < lines.length) {
        if (closeRe.test(lines[i]!)) {
          closeText = lines[i]!;
          break;
        }
        content.push(lines[i]!);
        specs.push({ t: "fbody", fi, ci });
        ci++;
        i++;
      }
      fences.push({ grammar: fenceGrammar(info), content });
      if (closeText !== null) {
        specs.push({ t: "fclose", text: closeText });
        i++;
      }
    } else if (isProseLine(lines[i]!)) {
      const bi = proseBlocks.length;
      const content: string[] = [];
      let ci = 0;
      while (i < lines.length && isProseLine(lines[i]!)) {
        content.push(lines[i]!);
        specs.push({ t: "prose", bi, ci });
        ci++;
        i++;
      }
      proseBlocks.push({ content });
    } else {
      specs.push({ t: "body", text: lines[i]!, headingColor: heads.get(i) ?? null });
      i++;
    }
  }
  return { specs, fences, proseBlocks };
}

function colorValue(key: string, value: string): ElementContent[] {
  if (key === "type") {
    const m = /^(\s*)(\S+)(.*)$/.exec(value);
    if (m) {
      const word = m[2]!;
      return [txt(m[1]!), span("src-type", [txt(word)], `color:${kindColor(word)}`), ...refSegments(m[3]!)];
    }
  }
  return refSegments(value);
}

/** Decorate one BODY line: a heading, a `- key:` line, or a blank. Prose is
 *  handled as markdown blocks (never here). */
function decorateBody(text: string, headingColor: HeadingColor | null): ElementContent[] {
  const h = /^(#{1,6})(\s*)(.*)$/.exec(text);
  if (h) {
    const [, hashes, sp, rest] = h;
    const out: ElementContent[] = [span("src-hash", [txt(hashes!)])];
    if (sp) out.push(txt(sp));
    if (!rest) return out;
    if (hashes!.length === 1) out.push(span("src-title", [txt(rest)]));
    else if (hashes!.length === 2) out.push(span("src-section", [txt(rest)]));
    else if (headingColor?.io) out.push(span(["src-node", `src-io-${headingColor.io}`], [txt(rest)]));
    else out.push(span("src-node", [txt(rest)], headingColor?.kind ? `color:${kindColor(headingColor.kind)}` : undefined));
    return out;
  }
  const b = /^(\s*[-*]\s+)([A-Za-z][\w-]*)(\s*:)(.*)$/.exec(text);
  if (b) {
    const [, lead, key, colon, value] = b;
    return [txt(lead!), span("src-key", [txt(key!)]), txt(colon!), ...colorValue(key!, value!)];
  }
  return refSegments(text);
}

/** Decorate a fence OPEN line: ``` faint, language word kind-colored, pflow
 *  role word muted. Faithful to the file (the ```python code text shows). */
function decorateFenceOpen(fence: string, info: string): ElementContent[] {
  const out: ElementContent[] = [span("src-fence", [txt(fence)])];
  if (!info) return out;
  for (const w of info.split(/(\s+)/)) {
    if (w === "") continue;
    if (/^\s+$/.test(w)) {
      out.push(txt(w));
      continue;
    }
    const kind = LANG_KIND[w.toLowerCase()];
    if (kind) out.push(span("src-type", [txt(w)], `color:${kindColor(kind)}`));
    else out.push(span("src-role", [txt(w)]));
  }
  return out;
}

/** Shiki's per-line children (one ElementContent[] per `.line` span), or null
 *  if the output isn't the expected pre>code>span.line shape. */
function shikiContentLines(root: Root): ElementContent[][] | null {
  const children = codeChildren(root);
  if (!children) return null;
  const lines: ElementContent[][] = [];
  for (const c of children) {
    if (c.type !== "element" || c.tagName !== "span") continue;
    const cls = c.properties?.className ?? c.properties?.class;
    const list = Array.isArray(cls) ? cls : typeof cls === "string" ? cls.split(/\s+/) : [];
    if (list.includes("line")) lines.push(c.children);
  }
  return lines;
}

function assemble(specs: LineSpec[], fenceLines: ElementContent[][][], proseLines: ElementContent[][][]): ElementContent[][] {
  return specs.map((s) => {
    switch (s.t) {
      case "body":
        return decorateBody(s.text, s.headingColor);
      case "prose":
        return proseLines[s.bi]?.[s.ci] ?? [];
      case "fopen":
        return decorateFenceOpen(s.fence, s.info);
      case "fclose":
        return [span("src-fence", [txt(s.text)])];
      case "fbody":
        return fenceLines[s.fi]?.[s.ci] ?? [];
    }
  });
}

function assertLineCount(text: string, lines: ElementContent[][]): void {
  if (import.meta.env?.DEV && lines.length !== text.split("\n").length) {
    console.error(`pflow UI: source decoration produced ${lines.length} lines for a ${text.split("\n").length}-line file — line numbers will be wrong`);
  }
}

/** Instant tier: headings/keys/fence-info colored, fence + prose content plain
 *  (+ teal refs) — no shiki, so it paints without waiting. */
export function decorateLinesSync(text: string): ElementContent[][] {
  const { specs, fences, proseBlocks } = scan(text);
  const fenceLines = fences.map((f) => f.content.map(refSegments));
  const proseLines = proseBlocks.map((b) => b.content.map(refSegments));
  const lines = assemble(specs, fenceLines, proseLines);
  assertLineCount(text, lines);
  return lines;
}

/** Highlight a block's content in `grammar` (markdown blocks get refs tealed),
 *  fail-closed to plain content + teal refs on null / a line-count mismatch —
 *  never throws, never misaligns the per-line count. */
async function highlightBlock(
  content: string[],
  grammar: string | null,
  highlight: (code: string, lang: string) => Promise<Root | null>,
): Promise<ElementContent[][]> {
  if (grammar) {
    const root = await highlight(content.join("\n"), grammar);
    const shiki = root ? shikiContentLines(root) : null;
    if (shiki && shiki.length === content.length) {
      if (grammar === "markdown") shiki.forEach(markAllRefs);
      return shiki;
    }
  }
  return content.map(refSegments);
}

/** Full tier: fence content highlighted in its inferred grammar AND description
 *  prose highlighted as markdown — both with refs tealed, both fail-closed per
 *  block to plain content (+ refs). */
export async function buildDecoratedLines(
  text: string,
  highlight: (code: string, lang: string) => Promise<Root | null>,
): Promise<ElementContent[][]> {
  const { specs, fences, proseBlocks } = scan(text);
  const fenceLines = await Promise.all(fences.map((f) => highlightBlock(f.content, f.grammar, highlight)));
  const proseLines = await Promise.all(proseBlocks.map((b) => highlightBlock(b.content, "markdown", highlight)));
  const lines = assemble(specs, fenceLines, proseLines);
  assertLineCount(text, lines);
  return lines;
}
