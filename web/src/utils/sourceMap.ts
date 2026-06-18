import type { AncestorStepRef, RFGraph, RFNode } from "../types";

export interface Crumb {
  label: string;
  file: string | null;
  line: number | null;
  hostContractId: string | null;
}

export function nodeAtLine(graph: RFGraph, file: string, line: number): RFNode[] {
  let bestLine: number | null = null;
  const matches: RFNode[] = [];

  for (const node of graph.nodes) {
    const source = node.source;
    if (!source || source.file !== file || source.line == null || source.line > line) continue;
    if (bestLine == null || source.line > bestLine) {
      bestLine = source.line;
      matches.length = 0;
    }
    if (source.line === bestLine) matches.push(node);
  }

  return matches;
}

export interface LineRange {
  start: number;
  end: number;
}

/** The block of authored lines belonging to the node that owns `line` in
 *  `file` — from its `###` heading down to the line before the next construct.
 *  The contract ships START lines only, so the end derives from (a) the next
 *  node/output source line in the SAME file and (b) `#`/`##` section headings
 *  found in the text (so the last step's block stops before `## Outputs`) —
 *  fenced regions are skipped when scanning for (b): a prompt fence legally
 *  contains `## Rules` at line start. Trailing blank lines are trimmed.
 *  Null when no node owns the line. All line numbers 1-based inclusive. */
export function nodeBlockRange(graph: RFGraph, file: string, line: number, text: string): LineRange | null {
  const start = nodeAtLine(graph, file, line)[0]?.source?.line;
  if (start == null) return null;
  const lines = text.split("\n");
  let end = lines.length;
  for (const node of graph.nodes) {
    const s = node.source;
    if (!s || s.file !== file || s.line == null || s.line <= start) continue;
    end = Math.min(end, s.line - 1);
  }
  let inFence = false;
  for (let i = start; i < end; i += 1) {
    const t = lines[i] ?? "";
    if (t.startsWith("```")) {
      inFence = !inFence;
      continue;
    }
    if (!inFence && /^#{1,2}\s/.test(t)) {
      end = i; // index i = 1-based line i+1; the block ends on the line before it
      break;
    }
  }
  while (end > start && (lines[end - 1] ?? "").trim() === "") end -= 1;
  // The queried line can fall PAST the owner's block (a blank separator, the
  // next `##` section heading): no honest extent exists — never tint the
  // previous node's block for a line it doesn't contain.
  if (line > end) return null;
  return { start, end };
}

/** The SECTION block at a `#`/`##` heading line: the heading down to the line
 *  before the next `#`/`##` heading (so `## Inputs` tints THROUGH its `###`
 *  declarations until `## Steps`), fence-aware, trailing blanks trimmed. Null
 *  when `line` isn't an unfenced section heading — the node-block rule applies
 *  there instead. Same extent semantics as nodeBlockRange, for io-card
 *  selections and section-heading clicks. */
export function sectionBlockRange(text: string, line: number): LineRange | null {
  const lines = text.split("\n");
  let inFence = false;
  // Walk from the top so the fence state AT `line` is known, not guessed.
  for (let i = 0; i < line - 1; i += 1) {
    if ((lines[i] ?? "").startsWith("```")) inFence = !inFence;
  }
  if (inFence || !/^#{1,2}\s/.test(lines[line - 1] ?? "")) return null;
  let end = lines.length;
  for (let i = line; i < lines.length; i += 1) {
    const t = lines[i] ?? "";
    if (t.startsWith("```")) {
      inFence = !inFence;
      continue;
    }
    if (!inFence && /^#{1,2}\s/.test(t)) {
      end = i;
      break;
    }
  }
  while (end > line && (lines[end - 1] ?? "").trim() === "") end -= 1;
  return { start: line, end };
}

/** The 1-based line of the `## Inputs` / `## Outputs` section heading in a
 *  file's text (fence-aware — a prompt legally contains `## Outputs` at line
 *  start), or null. Input PORTS carry no SourceRef in the contract, so the
 *  section heading IS the io card's authored home. */
export function sectionHeadingLine(text: string, kind: "input" | "output"): number | null {
  const heading = new RegExp(`^##\\s+${kind}s\\s*$`, "i");
  let inFence = false;
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i += 1) {
    const t = lines[i] ?? "";
    if (t.startsWith("```")) {
      inFence = !inFence;
      continue;
    }
    if (!inFence && heading.test(t)) return i + 1;
  }
  return null;
}

/** Per-line "may soft-wrap" flags: PROSE (lines outside ``` fences —
 *  descriptions, headings, bullets) wraps at the pane width; fenced content
 *  (code AND prompts) keeps its authored layout and the horizontal scrollbar —
 *  wrapping would misrepresent its whitespace. Fence delimiters count as code. */
export function wrappableLines(text: string): boolean[] {
  let inFence = false;
  return text.split("\n").map((line) => {
    if (line.startsWith("```")) {
      inFence = !inFence;
      return false;
    }
    return !inFence;
  });
}

export function breadcrumbFor(node: RFNode, graph: RFGraph, rootLabel = "root"): Crumb[] {
  const file = node.source?.file;
  if (!file) return fileChainForRoot(graph, rootLabel);
  const root = rootCrumb(graph, rootLabel);
  if (!root.file || file === root.file) return [root];
  // The selected node KNOWS its invocation path — walk ref.ancestor_path, never
  // re-derive from the file (review-caught: a child file invoked from TWO host
  // steps must crumb the invocation the user is actually in; the file-based
  // first-in-contract-order rule is only for the no-selection case below).
  return [root, ...hostCrumbsForPath(node.ref.ancestor_path, graph), fileCrumb(file)];
}

export function fileChainFor(file: string, graph: RFGraph, rootLabel = "root"): Crumb[] {
  const root = rootCrumb(graph, rootLabel);
  if (!root.file || file === root.file) return [root];

  const host = hostForFile(graph, file);
  if (!host) return [root];

  const chain = [root, ...hostCrumbsForPath(host.ref.ancestor_path, graph), hostCrumb(host)];
  return [...chain, fileCrumb(file)];
}

function fileChainForRoot(graph: RFGraph, rootLabel: string): Crumb[] {
  return [rootCrumb(graph, rootLabel)];
}

function rootCrumb(graph: RFGraph, label: string): Crumb {
  return { label, file: rootFile(graph), line: null, hostContractId: null };
}

function fileCrumb(file: string): Crumb {
  return { label: fileLabel(file), file, line: null, hostContractId: null };
}

function hostCrumb(host: RFNode): Crumb {
  return {
    label: host.ref.node_id,
    file: host.source?.file ?? null,
    line: host.source?.line ?? null,
    hostContractId: host.id,
  };
}

function hostCrumbsForPath(path: AncestorStepRef[], graph: RFGraph): Crumb[] {
  const crumbs: Crumb[] = [];
  for (let i = 0; i < path.length; i += 1) {
    const host = ancestorHost(graph, path[i]!, path.slice(0, i));
    if (host) crumbs.push(hostCrumb(host));
  }
  return crumbs;
}

function hostForFile(graph: RFGraph, file: string): RFNode | null {
  for (const node of graph.nodes) {
    const path = node.ref.ancestor_path;
    if (node.source?.file !== file || path.length === 0) continue;
    const host = ancestorHost(graph, path[path.length - 1]!, path.slice(0, -1));
    if (host) return host;
  }
  return null;
}

function ancestorHost(graph: RFGraph, step: AncestorStepRef, prefix: AncestorStepRef[]): RFNode | null {
  return (
    graph.nodes.find(
      (node) =>
        node.is_group_host &&
        node.ref.port == null &&
        node.ref.node_id === step.node_id &&
        samePath(node.ref.ancestor_path, prefix),
    ) ?? null
  );
}

function rootFile(graph: RFGraph): string | null {
  for (const node of graph.nodes) {
    if (node.ref.ancestor_path.length === 0 && node.source?.file) return node.source.file;
  }
  return null;
}

function samePath(a: AncestorStepRef[], b: AncestorStepRef[]): boolean {
  return a.length === b.length && a.every((step, i) => step.node_id === b[i]!.node_id && step.batch_index === b[i]!.batch_index);
}

function fileLabel(file: string): string {
  const base = file.split(/[\\/]/).pop() ?? file;
  return base.endsWith(".pflow.md") ? base.slice(0, -".pflow.md".length) : base;
}
