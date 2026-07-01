// One recorded run value, rendered text-or-JSON in the panel's scroll-capped CodeBlock (Task 175). The
// SINGLE home for "how a recorded run value displays" — shared by the node detail panel's "This run"
// section (ThisRunSection) and the IO panel's per-port "this run" block (IoPanel), which had drifting
// copies of this string-vs-JSON decision. A string renders as plain text; anything else as pretty JSON.
import { CodeBlock } from "./CodeBlock";

export function RunValue({ value }: { value: unknown }): JSX.Element {
  const isString = typeof value === "string";
  return <CodeBlock code={isString ? value : JSON.stringify(value, null, 2)} lang={isString ? "text" : "json"} />;
}
