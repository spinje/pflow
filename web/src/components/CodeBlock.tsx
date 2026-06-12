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
      if (highlightRef) {
        // The count rule: swap only when every plain-text mark landed in the
        // hast (expected === 0 means marks add nothing, so the swap is free).
        const expected = parseTemplate(code).filter((s) => s.isRef && refMatchesHighlight(s.text, highlightRef)).length;
        if (markRefs(root, highlightRef) !== expected) return;
      }
      const children = codeChildren(root);
      if (children) setHighlighted({ key, nodes: children });
    });
    return () => {
      cancelled = true;
    };
  }, [code, lang, highlightRef, key]);

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
      {highlightRef
        ? parseTemplate(code).map((seg, i) => {
            if (!seg.isRef) return seg.text;
            return refMatchesHighlight(seg.text, highlightRef) ? (
              <mark className="ref-mark" key={i}>{`\${${seg.text}}`}</mark>
            ) : (
              `\${${seg.text}}`
            );
          })
        : code}
    </pre>
  );
}
