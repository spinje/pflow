// THE component that renders a param/code value in a panel. The synchronous
// first paint is the LEGACY rendering — exactly today's output, including the
// `${ref}` marks when `highlightRef` is set (several EdgePanel tests pin that
// synchronous presence). Shiki's hast only ever SWAPS IN later: highlighting is
// strictly an upgrade, never a downgrade of marks — and with `highlightRef` set
// the swap is GATED on the highlighted tree landing exactly as many marks as the
// plain text carries (a `${ref}` the tokenizer split across text nodes would
// otherwise un-mark the one thing this panel exists to point at). No spinner, no
// Suspense — plain state + effect, like the rest of the app.

import { useEffect, useState } from "react";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import type { ElementContent } from "hast";

import { parseTemplate, refMatchesHighlight } from "../utils/format";
import { codeChildren, highlight, markRefs } from "../utils/highlight";

export function CodeBlock({
  code,
  lang,
  highlightRef,
}: {
  code: string;
  lang: string | null;
  highlightRef?: string;
}): JSX.Element {
  // Markdown (prompts, cached prefix) and plain values teal ALL their refs — the
  // canvas-language treatment the source pane uses. Code/shell/yaml/json values do
  // NOT (shiki owns them; a bash variable is not a pflow ref), exactly as the
  // source pane leaves those fences to their grammar.
  const tealRefs = lang === "markdown" || lang === null;

  // The highlighted tree is keyed by its inputs: a re-render with new props must
  // never paint a stale highlight of the OLD value while the effect catches up.
  const key = `${lang ?? ""}\u0000${highlightRef ?? ""}\u0000${code}`;
  const [highlighted, setHighlighted] = useState<{ key: string; nodes: ElementContent[] } | null>(null);
  const nodes = highlighted?.key === key ? highlighted.nodes : null;

  useEffect(() => {
    if (!lang) return;
    let cancelled = false;
    void highlight(code, lang).then((root) => {
      if (cancelled || !root) return;
      // The count rule (highlightRef only): swap only when every plain-text mark
      // landed in the hast. tealRest decoration is best-effort and never gates.
      const expected = highlightRef ? parseTemplate(code).filter((s) => s.isRef && refMatchesHighlight(s.text, highlightRef)).length : 0;
      const landed = markRefs(root, highlightRef, { tealRest: tealRefs });
      if (highlightRef && landed !== expected) return;
      const children = codeChildren(root);
      if (children) setHighlighted({ key, nodes: children });
    });
    return () => {
      cancelled = true;
    };
  }, [code, lang, highlightRef, key, tealRefs]);

  if (nodes) {
    // ONE <pre> — the hast <code>'s children render inside OUR container so the
    // box recipe (pre-wrap, scroll cap) keeps governing; shiki's own <pre> would
    // nest UA `white-space: pre` and bring back horizontal scrollbars.
    return (
      <pre className="read-param-value shiki-host">
        {toJsxRuntime({ type: "root", children: nodes }, { Fragment, jsx, jsxs })}
      </pre>
    );
  }

  return (
    <pre className="read-param-value">
      {highlightRef != null || tealRefs
        ? parseTemplate(code).map((seg, i) => {
            if (!seg.isRef) return seg.text;
            const t = `\${${seg.text}}`;
            if (highlightRef != null && refMatchesHighlight(seg.text, highlightRef)) {
              return (
                <mark className="ref-mark" key={i}>
                  {t}
                </mark>
              );
            }
            return tealRefs ? (
              <span className="src-ref" key={i}>
                {t}
              </span>
            ) : (
              t
            );
          })
        : code}
    </pre>
  );
}
