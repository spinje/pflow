// Canvas-language decoration for the source pane's verbatim `.pflow.md` view.
// Pure (no React, no DOM) so it runs in node-env tests. Produces ONE hast
// ElementContent[] per source line — the source pane renders each line as a
// `.src-line` row, so the line count MUST equal `text.split("\n").length`
// (asserted below in dev). Two tiers:
//   decorateLinesSync(text)            — instant: body tokens + fence info
//     colored, fence CONTENT plain (+ teal refs). No shiki, so it paints now.
//   buildDecoratedLines(text, hl)      — full: the above, with fence content
//     highlighted in its INFERRED grammar (prompt→markdown, command→bash, …).
//
// The scheme is "Canvas language" (the user pick): type-values + node-name
// headings take their canvas KIND color (format.kindColor — one source of
// truth), `${refs}` are teal, structural keys are muted. Fences stay faithful
// to the file (the ```python code lines show), with the language word
// kind-colored and the pflow role word (code/command/prompt/…) muted.

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
function span(className: string, children: ElementContent[], style?: string): ElementContent {
  const properties: Properties = { className: [className] };
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
 *  in place — refs inside a prompt are the point, like the markRefs precedent. */
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

type LineSpec =
  | { t: "body"; text: string; headingKind: string | null }
  | { t: "fopen"; fence: string; info: string }
  | { t: "fclose"; text: string }
  | { t: "fbody"; fi: number; ci: number };

interface FenceBlock {
  grammar: string | null;
  content: string[];
}

/** For each `###`+ node heading, the `type:` value declared in its block (the
 *  heading's KIND color). Forward-scan to the next heading; `null` if none. */
function headingKinds(lines: string[]): Map<number, string> {
  const map = new Map<number, string>();
  for (let i = 0; i < lines.length; i++) {
    if (!/^#{3,}\s+\S/.test(lines[i]!)) continue;
    for (let j = i + 1; j < lines.length; j++) {
      if (/^#{1,6}\s/.test(lines[j]!)) break;
      const t = /^\s*[-*]\s+type\s*:\s*(\S+)/.exec(lines[j]!);
      if (t) {
        map.set(i, t[1]!);
        break;
      }
    }
  }
  return map;
}

/** Walk lines into specs (one per source line) + the fence content blocks.
 *  Fences match the PARSER's rule: 3+ of ` or ~, closing only on a same-char
 *  fence of >= length — so a ````prompt block may contain inner ```. */
function scan(text: string): { specs: LineSpec[]; fences: FenceBlock[] } {
  const lines = text.split("\n");
  const heads = headingKinds(lines);
  const specs: LineSpec[] = [];
  const fences: FenceBlock[] = [];
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
    } else {
      specs.push({ t: "body", text: lines[i]!, headingKind: heads.get(i) ?? null });
      i++;
    }
  }
  return { specs, fences };
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

/** Decorate one BODY line (outside any fence). */
function decorateBody(text: string, headingKind: string | null): ElementContent[] {
  const h = /^(#{1,6})(\s*)(.*)$/.exec(text);
  if (h) {
    const [, hashes, sp, rest] = h;
    const out: ElementContent[] = [span("src-hash", [txt(hashes!)])];
    if (sp) out.push(txt(sp));
    if (!rest) return out;
    if (hashes!.length === 1) out.push(span("src-title", [txt(rest)]));
    else if (hashes!.length === 2) out.push(span("src-section", [txt(rest)]));
    else out.push(span("src-node", [txt(rest)], headingKind ? `color:${kindColor(headingKind)}` : undefined));
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

function assemble(specs: LineSpec[], fenceLines: ElementContent[][][]): ElementContent[][] {
  return specs.map((s) => {
    switch (s.t) {
      case "body":
        return decorateBody(s.text, s.headingKind);
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

/** Instant tier: body + fence-info colored, fence content plain (+ teal refs). */
export function decorateLinesSync(text: string): ElementContent[][] {
  const { specs, fences } = scan(text);
  const fenceLines = fences.map((f) => f.content.map(refSegments));
  const lines = assemble(specs, fenceLines);
  assertLineCount(text, lines);
  return lines;
}

/** Full tier: fence content highlighted in its inferred grammar (refs tealed
 *  in markdown fences). Fail-closed per fence — a missing/mismatched shiki
 *  result degrades to plain content (+ refs), never throws, never misaligns. */
export async function buildDecoratedLines(
  text: string,
  highlight: (code: string, lang: string) => Promise<Root | null>,
): Promise<ElementContent[][]> {
  const { specs, fences } = scan(text);
  const fenceLines = await Promise.all(
    fences.map(async (f) => {
      if (f.grammar) {
        const root = await highlight(f.content.join("\n"), f.grammar);
        const shiki = root ? shikiContentLines(root) : null;
        if (shiki && shiki.length === f.content.length) {
          if (f.grammar === "markdown") shiki.forEach(markAllRefs);
          return shiki;
        }
      }
      return f.content.map(refSegments);
    }),
  );
  const lines = assemble(specs, fenceLines);
  assertLineCount(text, lines);
  return lines;
}
