// Rendered markdown for AUTHORED prose (descriptions). Workflows are third-party
// content, so the security stance is react-markdown's default: raw HTML is never
// rendered (it stays visible as text — no dangerouslySetInnerHTML anywhere) and
// images never fetch (alt text only).
//
// Two modes from one component:
//   BLOCK (panels)  — full markdown inside a `.md` div; fenced code routes to
//     CodeBlock (the highlight seam), links open in a new tab.
//   INLINE (catalog) — one flowing line: bold/italic/code spans only, every block
//     construct flattens. `unwrapDisallowed` drops disallowed TAGS keeping their
//     children, but the components map does NOT run for unwrapped elements — so
//     `p`/`li` stay ALLOWED and map to a fragment appending a trailing space,
//     otherwise "- first\n- second" concatenates to "firstsecond". `a` flattens
//     to its text (catalog rows are <button>s — a nested <a> is invalid HTML).

import { Children, isValidElement, type ReactElement, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { HIGHLIGHT_LANGS } from "../utils/highlight";
import { CodeBlock } from "./CodeBlock";

function nodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  return "";
}

/** A fenced block: route to CodeBlock with the fence's language — known
 *  grammars highlight, anything else fails closed to plain text. */
function CodeFence({ children }: { children?: ReactNode }): JSX.Element {
  const codeEl = Children.toArray(children).find(isValidElement) as
    | ReactElement<{ className?: string; children?: ReactNode }>
    | undefined;
  const lang = /language-(\S+)/.exec(codeEl?.props.className ?? "")?.[1] ?? "";
  return (
    <CodeBlock
      code={nodeText(codeEl?.props.children).replace(/\n$/, "")}
      lang={(HIGHLIGHT_LANGS as readonly string[]).includes(lang) ? lang : null}
    />
  );
}

const BLOCK_COMPONENTS: Components = {
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  img: ({ alt }) => <>{alt ?? ""}</>, // never fetch remote images from workflow content
  pre: ({ children }) => <CodeFence>{children}</CodeFence>,
};

const INLINE_ALLOWED = ["p", "li", "em", "strong", "del", "code", "a", "img"];

const INLINE_COMPONENTS: Components = {
  // The trailing space IS the block separator (see the header comment).
  p: ({ children }) => <>{children} </>,
  li: ({ children }) => <>{children} </>,
  a: ({ children }) => <>{children}</>,
  // Unwrapping an <img> would yield NOTHING (alt is an attribute, not children).
  img: ({ alt }) => <>{alt ?? ""}</>,
};

export function Markdown({ text, inline = false }: { text: string; inline?: boolean }): JSX.Element {
  if (inline) {
    // No wrapper element at all — the call site is a <span> inside a <button>.
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        allowedElements={INLINE_ALLOWED}
        unwrapDisallowed
        components={INLINE_COMPONENTS}
      >
        {text}
      </ReactMarkdown>
    );
  }
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={BLOCK_COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
