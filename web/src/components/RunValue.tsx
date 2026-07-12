// One recorded run value, rendered text-or-JSON in the panel's scroll-capped CodeBlock (Task 175). The
// SINGLE home for "how a recorded run value displays" — shared by the node detail panel's "This run"
// section (ThisRunSection) and the IO panel's per-port "this run" block (IoPanel), which had drifting
// copies of this string-vs-JSON decision. A string renders as plain text; anything else as pretty JSON.
//
// The ⛶ expand rides CodeBlock; `label` titles the modal. The modal is a READING surface (the compact
// box already answers "what shape is this"), so a DICT expands to a per-field document — each top-level
// key a labeled block, string values as real text (real newlines, not JSON `\n` escapes), everything
// else pretty JSON. Top-level only (the observed pain is realized-input/output dicts wrapping long
// strings); arrays and deeper nesting stay JSON until a real case hurts. This lives HERE and not in
// CodeBlock because only RunValue still holds the structured value — and because authored params must
// render exactly as authored (a literal `\n` in a code param is content, never a newline).
import { CodeBlock } from "./CodeBlock";

export function RunValue({ value, label }: { value: unknown; label?: string }): JSX.Element {
  const isString = typeof value === "string";
  return (
    <CodeBlock
      code={isString ? value : JSON.stringify(value, null, 2)}
      lang={isString ? "text" : "json"}
      expandLabel={label}
      modalBody={isPlainDict(value) ? <ValueDoc value={value} /> : undefined}
    />
  );
}

function isPlainDict(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// The dict-as-document modal body: one labeled block per top-level field, each
// rendered by the same string-vs-JSON rule as the compact box.
function ValueDoc({ value }: { value: Record<string, unknown> }): JSX.Element {
  return (
    <>
      {Object.entries(value).map(([name, field]) => (
        <div className="value-doc-field" key={name}>
          <span className="value-doc-name">{name}</span>
          <CodeBlock
            code={typeof field === "string" ? field : JSON.stringify(field, null, 2)}
            lang={typeof field === "string" ? "text" : "json"}
            expandLabel={null}
          />
        </div>
      ))}
    </>
  );
}
