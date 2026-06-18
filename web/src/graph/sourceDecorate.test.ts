import { describe, expect, it } from "vitest";
import type { ElementContent, Root } from "hast";

import { kindColor } from "../utils/format";
import { buildDecoratedLines, decorateLinesSync, fenceGrammar } from "./sourceDecorate";

// --- hast inspection helpers ---
function textOf(n: ElementContent): string {
  if (n.type === "text") return n.value;
  if (n.type === "element") return n.children.map(textOf).join("");
  return "";
}
const lineText = (line: ElementContent[]): string => line.map(textOf).join("");

function spansWithClass(nodes: ElementContent[], cls: string, out: ElementContent[] = []): ElementContent[] {
  for (const n of nodes) {
    if (n.type !== "element") continue;
    const c = n.properties?.className;
    if (Array.isArray(c) && c.includes(cls)) out.push(n);
    spansWithClass(n.children, cls, out);
  }
  return out;
}
const firstWithClass = (line: ElementContent[], cls: string): ElementContent | undefined => spansWithClass(line, cls)[0];
const styleOf = (n: ElementContent | undefined): string | undefined =>
  n?.type === "element" ? (n.properties?.style as string | undefined) : undefined;

const SAMPLE = [
  "## Steps", // 1
  "", // 2
  "### fetch-data", // 3
  "Fetch data.", // 4
  "- type: shell", // 5
  "", // 6
  "```shell command", // 7
  "echo hi ${repo_dir}", // 8
  "```", // 9
  "", // 10
  "### classify", // 11
  "- type: code", // 12
  "- inputs: { data: \"${fetch-data.stdout}\" }", // 13
].join("\n");

describe("fenceGrammar", () => {
  it("infers grammar from the language word, then the pflow role", () => {
    expect(fenceGrammar("shell command")).toBe("bash");
    expect(fenceGrammar("python code")).toBe("python");
    expect(fenceGrammar("yaml output_schema")).toBe("yaml");
    expect(fenceGrammar("json")).toBe("json");
    // role-only fences (no language word) infer from the role
    expect(fenceGrammar("prompt")).toBe("markdown");
    expect(fenceGrammar("command")).toBe("bash");
    expect(fenceGrammar("cache")).toBe("markdown");
    // no language, no known role → plain
    expect(fenceGrammar("text content")).toBeNull();
    expect(fenceGrammar("mermaid")).toBeNull();
  });
});

describe("decorateLinesSync", () => {
  const lines = decorateLinesSync(SAMPLE);

  it("emits exactly one decorated entry per source line", () => {
    expect(lines.length).toBe(SAMPLE.split("\n").length);
    // text content is preserved verbatim per line
    expect(lineText(lines[0]!)).toBe("## Steps");
    expect(lineText(lines[7]!)).toBe("echo hi ${repo_dir}");
    expect(lineText(lines[12]!)).toBe('- inputs: { data: "${fetch-data.stdout}" }');
  });

  it("colors a `- type: <kind>` value with the canvas kind color, key muted", () => {
    const typeLine = lines[4]!; // "- type: shell"
    expect(firstWithClass(typeLine, "src-key")).toBeTruthy(); // the `type` key
    const tv = firstWithClass(typeLine, "src-type");
    expect(textOf(tv!)).toBe("shell");
    expect(styleOf(tv)).toBe(`color:${kindColor("shell")}`);
  });

  it("colors a `### node` heading by its block's declared type kind", () => {
    const head = lines[2]!; // "### fetch-data" — block has `- type: shell`
    const node = firstWithClass(head, "src-node");
    expect(textOf(node!)).toBe("fetch-data");
    expect(styleOf(node)).toBe(`color:${kindColor("shell")}`);
    // a `## Section` heading reads as a section, not a node
    expect(firstWithClass(lines[0]!, "src-section")).toBeTruthy();
  });

  it("teals every ${ref}, in body values AND inside fence content", () => {
    const inputsRefs = spansWithClass(lines[12]!, "src-ref"); // body dict ref
    expect(inputsRefs.map(textOf)).toEqual(["${fetch-data.stdout}"]);
    const fenceRefs = spansWithClass(lines[7]!, "src-ref"); // ${repo_dir} inside the fence
    expect(fenceRefs.map(textOf)).toEqual(["${repo_dir}"]);
  });

  it("colors the fence info string: language word kind-colored, role word muted", () => {
    const open = lines[6]!; // "```shell command"
    expect(textOf(firstWithClass(open, "src-fence")!)).toBe("```");
    const lang = firstWithClass(open, "src-type");
    expect(textOf(lang!)).toBe("shell");
    expect(styleOf(lang)).toBe(`color:${kindColor("shell")}`);
    expect(textOf(firstWithClass(open, "src-role")!)).toBe("command"); // muted role
  });

  it("renders a prose line plain (+ teal refs) — verbatim, no kind/key chrome", () => {
    const prose = lines[3]!; // "Fetch data." — a description line
    expect(lineText(prose)).toBe("Fetch data.");
    expect(firstWithClass(prose, "src-key")).toBeUndefined();
    expect(firstWithClass(prose, "src-node")).toBeUndefined();
  });
});

describe("input/output heading colors (section-aware)", () => {
  const IO_SAMPLE = [
    "## Inputs", // 1
    "", // 2
    "### repo_dir", // 3
    "Path to the repo.", // 4
    "- type: string", // 5
    "", // 6
    "## Steps", // 7
    "### build", // 8
    "- type: shell", // 9
    "", // 10
    "## Outputs", // 11
    "### pr_url", // 12
  ].join("\n");
  const lines = decorateLinesSync(IO_SAMPLE);

  it("colors an input heading with the faded IO class, NOT an inline kind color", () => {
    const head = lines[2]!; // "### repo_dir" under "## Inputs"
    const node = firstWithClass(head, "src-node");
    expect(textOf(node!)).toBe("repo_dir");
    expect(firstWithClass(head, "src-io-input")).toBeTruthy();
    expect(styleOf(node)).toBeUndefined(); // not kindColor("string") → grey
  });

  it("colors an output heading with the faded IO class", () => {
    expect(firstWithClass(lines[11]!, "src-io-output")).toBeTruthy(); // "### pr_url"
  });

  it("still colors a `## Steps` node heading by its declared kind, no IO class", () => {
    const head = lines[7]!; // "### build" under "## Steps"
    expect(styleOf(firstWithClass(head, "src-node"))).toBe(`color:${kindColor("shell")}`);
    expect(firstWithClass(head, "src-io-input")).toBeUndefined();
    expect(firstWithClass(head, "src-io-output")).toBeUndefined();
  });
});

describe("length-aware fence nesting", () => {
  // A 4-backtick prompt containing an inner ```json is ONE fence; the inner
  // fence is CONTENT, not a close (mirrors the parser's same-length rule).
  const NESTED = ["````prompt", "## Task", "```json", '{"x": 1}', "```", "done", "````", "after"].join("\n");

  it("keeps the count exact and does not close on the inner fence", () => {
    const lines = decorateLinesSync(NESTED);
    expect(lines.length).toBe(NESTED.split("\n").length); // 8
    // the inner ```json line is fence CONTENT (verbatim), not a decorated close
    expect(lineText(lines[2]!)).toBe("```json");
    // "after" is a body line outside the (single) prompt fence
    expect(lineText(lines[7]!)).toBe("after");
  });
});

describe("buildDecoratedLines", () => {
  // a shiki stub: wraps each line of a markdown block in a token span so we can
  // see the swap; returns the right number of `.line` spans.
  const stub = (code: string, lang: string): Promise<Root | null> => {
    const lineSpans: ElementContent[] = code.split("\n").map((l) => ({
      type: "element",
      tagName: "span",
      properties: { className: ["line"] },
      children: [{ type: "element", tagName: "span", properties: { className: [`tok-${lang}`] }, children: [{ type: "text", value: l }] }],
    }));
    return Promise.resolve({
      type: "root",
      children: [
        { type: "element", tagName: "pre", properties: {}, children: [{ type: "element", tagName: "code", properties: {}, children: lineSpans }] },
      ],
    } satisfies Root);
  };

  it("swaps fence content for the shiki result and tealize refs in markdown fences", async () => {
    const src = ["````prompt", "Use ${repo_dir} now", "````"].join("\n");
    const lines = await buildDecoratedLines(src, stub);
    expect(lines.length).toBe(3);
    const content = lines[1]!; // the prompt body line, shiki-highlighted
    expect(spansWithClass(content, "tok-markdown").length).toBe(1); // came from the stub
    expect(spansWithClass(content, "src-ref").map(textOf)).toEqual(["${repo_dir}"]); // refs still tealed
  });

  it("fails closed to plain content when shiki returns null or a line-count mismatch", async () => {
    const src = ["```python code", "x = 1", "y = 2", "```"].join("\n");
    const nullHl = (): Promise<Root | null> => Promise.resolve(null);
    const lines = await buildDecoratedLines(src, nullHl);
    expect(lines.length).toBe(4);
    expect(lineText(lines[1]!)).toBe("x = 1"); // verbatim, no shiki tokens
    expect(spansWithClass(lines[1]!, "tok-python").length).toBe(0);
  });

  it("highlights a prose run as markdown and teals its refs; headings/keys stay canvas", async () => {
    const src = ["## Steps", "Run `make test` for ${repo_dir}.", "- type: shell"].join("\n");
    const lines = await buildDecoratedLines(src, stub);
    expect(lines.length).toBe(3);
    const prose = lines[1]!; // the description line → markdown-highlighted
    expect(spansWithClass(prose, "tok-markdown").length).toBe(1); // shiki markdown ran on prose
    expect(spansWithClass(prose, "src-ref").map(textOf)).toEqual(["${repo_dir}"]); // ref still tealed
    // the `## Steps` heading and `- type:` key keep canvas decoration, never markdown
    expect(spansWithClass(lines[0]!, "tok-markdown").length).toBe(0);
    expect(spansWithClass(lines[2]!, "tok-markdown").length).toBe(0);
    expect(firstWithClass(lines[2]!, "src-key")).toBeTruthy();
  });
});
