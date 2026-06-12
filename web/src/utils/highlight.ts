// THE syntax-highlighting seam: every code-shaped value (params, prompts, fenced
// blocks in rendered markdown) colors through here, and the future `.pflow.md`
// source pane / diff view is this module's next consumer — keep it the ONE place
// that knows shiki. Pure (no React); node-env testable.
//
// Shiki loads lazily as its own Vite chunk (the lazy-ELK pattern, layout.ts):
// type-only static imports + a promise-memoized dynamic import awaited inside an
// already-async path. ONE deviation from the ELK template, deliberate: on
// REJECTION the memo resets, so a transient chunk-load failure (a stale tab
// across a rebuild fetching a 404'd chunk hash) retries on the next call instead
// of disabling highlighting for the whole session — ELK's failure is user-visible
// via the error banner; ours is invisible-by-design, so retry is the honest
// behavior. Every failure degrades to plain text (null), never throws into a
// panel.

import type { ElementContent, Root } from "hast";
import type { HighlighterCore } from "shiki/core";

import { parseTemplate, refMatchesHighlight } from "./format";

/** The grammars the lazy chunk ships. Anything else fails closed to plain text
 *  (`diff` joins when the source pane lands). */
export const HIGHLIGHT_LANGS = ["python", "bash", "json", "yaml", "markdown"] as const;

const THEME = "github-dark-default";

// Shiki tokenizes synchronously on the main thread, and a file-referenced prompt
// can be arbitrarily large — past this, plain text (which already scrolls) wins.
const MAX_HIGHLIGHT_CHARS = 50_000;

let highlighterLoad: Promise<HighlighterCore> | null = null;

const loadHighlighter = (): Promise<HighlighterCore> =>
  (highlighterLoad ??= createHighlighter().catch((err: unknown) => {
    highlighterLoad = null; // transient failure must not poison the session — retry next call
    throw err;
  }));

async function createHighlighter(): Promise<HighlighterCore> {
  // All five grammars load eagerly INSIDE the lazy chunk — one createHighlighterCore
  // call is simpler than per-language laziness when the whole chunk is already lazy.
  // The pure-JS regex engine covers all built-in grammars (no oniguruma WASM).
  const [{ createHighlighterCore }, { createJavaScriptRegexEngine }, python, bash, json, yaml, markdown, theme] =
    await Promise.all([
      import("shiki/core"),
      import("shiki/engine/javascript"),
      import("@shikijs/langs/python"),
      import("@shikijs/langs/bash"),
      import("@shikijs/langs/json"),
      import("@shikijs/langs/yaml"),
      import("@shikijs/langs/markdown"),
      import("@shikijs/themes/github-dark-default"),
    ]);
  return createHighlighterCore({
    themes: [theme.default],
    langs: [python.default, bash.default, json.default, yaml.default, markdown.default],
    engine: createJavaScriptRegexEngine(),
  });
}

/** Highlight `code` to a hast tree, or null whenever plain text should render
 *  instead: unknown language, oversize input, or any load/highlight failure
 *  (warned, never thrown — highlighting is progressive enhancement). */
export async function highlight(code: string, lang: string): Promise<Root | null> {
  if (!(HIGHLIGHT_LANGS as readonly string[]).includes(lang)) return null;
  if (code.length > MAX_HIGHLIGHT_CHARS) {
    // The one degradation that isn't obvious from context (unknown lang is
    // policy; loading resolves itself) — say why this value stays plain.
    console.info(`pflow UI: value too large to highlight (${code.length} > ${MAX_HIGHLIGHT_CHARS} chars) — rendering plain text`);
    return null;
  }
  try {
    const highlighter = await loadHighlighter();
    return highlighter.codeToHast(code, { lang, theme: THEME });
  } catch (err) {
    console.warn(`pflow UI: syntax highlighting unavailable (${lang}) — rendering plain text`, err);
    return null;
  }
}

/** Walk the hast TEXT nodes and wrap every `${...}` segment matching
 *  `highlightRef` in the existing `.ref-mark` <mark>. Returns the COUNT of marks
 *  landed — the caller compares it against the count the plain text yields and
 *  keeps the legacy rendering on a mismatch (a `${ref}` the tokenizer split
 *  across text nodes stays unmarked here by design; partial marking would tell
 *  the user something false, so the fallback is count-based, never cross-node
 *  merging). */
export function markRefs(root: Root, highlightRef: string): number {
  let marks = 0;
  const visit = (node: { children: ElementContent[] }): void => {
    for (let i = 0; i < node.children.length; i++) {
      const child = node.children[i];
      if (!child) continue;
      if (child.type === "element") {
        visit(child);
        continue;
      }
      if (child.type !== "text" || !child.value.includes("${")) continue;
      const segments = parseTemplate(child.value);
      if (!segments.some((s) => s.isRef && refMatchesHighlight(s.text, highlightRef))) continue;
      const replacement: ElementContent[] = segments.map((seg) => {
        const text = seg.isRef ? `\${${seg.text}}` : seg.text;
        if (!seg.isRef || !refMatchesHighlight(seg.text, highlightRef)) return { type: "text", value: text };
        marks++;
        return {
          type: "element",
          tagName: "mark",
          properties: { className: ["ref-mark"] },
          children: [{ type: "text", value: text }],
        };
      });
      node.children.splice(i, 1, ...replacement);
      i += replacement.length - 1;
    }
  };
  visit(root as { children: ElementContent[] });
  return marks;
}

/** The `<code>` element's children inside shiki's output — rendered INSIDE our
 *  own `<pre>` so the container keeps its `pre-wrap` (shiki's nested `<pre>`
 *  would reintroduce UA `white-space: pre` → horizontal scrollbars). */
export function codeChildren(root: Root): ElementContent[] | null {
  const pre = root.children.find((c) => c.type === "element" && c.tagName === "pre");
  if (pre?.type !== "element") return null;
  const code = pre.children.find((c) => c.type === "element" && c.tagName === "code");
  return code?.type === "element" ? code.children : null;
}
