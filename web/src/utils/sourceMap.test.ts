import { describe, expect, it } from "vitest";

import deepResearchContract from "../test/fixtures/contracts/deep-research.json";
import type { RFGraph, RFNode } from "../types";
import { breadcrumbFor, fileChainFor, nodeAtLine, nodeBlockRange, sectionBlockRange, sectionHeadingLine } from "./sourceMap";

const deepResearch = deepResearchContract as RFGraph;
const ROOT_FILE =
  "/Users/andfal/projects/pflow-worktrees/feat-workflow-visualization-static-viewer/examples/nested/deep-research/deep-research.pflow.md";
const ANALYZE_FILE =
  "/Users/andfal/projects/pflow-worktrees/feat-workflow-visualization-static-viewer/examples/nested/deep-research/analyze-source.pflow.md";
const SCORE_FILE =
  "/Users/andfal/projects/pflow-worktrees/feat-workflow-visualization-static-viewer/examples/nested/deep-research/score-section.pflow.md";
const REVIEW_FILE =
  "/Users/andfal/projects/pflow-worktrees/feat-workflow-visualization-static-viewer/examples/nested/deep-research/review-aspect.pflow.md";

function ids(nodes: RFNode[]): string[] {
  return nodes.map((node) => node.id);
}

function node(overrides: Partial<RFNode>): RFNode {
  return {
    id: "n0",
    ref: { node_id: "step", ancestor_path: [], port: null },
    kind: "shell",
    purpose: "",
    params: [],
    io: null,
    loop: null,
    batch: null,
    parent: null,
    source: null,
    is_decision: false,
    is_terminal: false,
    is_group_host: false,
    is_transform: false,
    output_shape: null,
    cached_prefix: null,
    unexpanded: null,
    annotations: {},
    ...overrides,
  };
}

describe("nodeAtLine", () => {
  it("returns the node authored on an exact heading line", () => {
    expect(ids(nodeAtLine(deepResearch, ROOT_FILE, 54))).toEqual(["n4"]);
  });

  it("returns the nearest preceding node between headings", () => {
    expect(ids(nodeAtLine(deepResearch, ROOT_FILE, 60))).toEqual(["n4"]);
  });

  it("returns no candidates before the first authored node in the file", () => {
    expect(nodeAtLine(deepResearch, ROOT_FILE, 1)).toEqual([]);
  });

  it("filters by file", () => {
    expect(nodeAtLine(deepResearch, "/not/a/workflow.pflow.md", 54)).toEqual([]);
  });

  it("returns same-line batch candidates in contract order", () => {
    expect(ids(nodeAtLine(deepResearch, REVIEW_FILE, 22))).toEqual(["n22", "n26"]);
  });

  it("never treats a null source line as line 0", () => {
    const graph: RFGraph = {
      nodes: [node({ source: { file: "/x.pflow.md", line: null } })],
      edges: [],
      groups: [],
    };

    expect(nodeAtLine(graph, "/x.pflow.md", 999)).toEqual([]);
  });
});

describe("breadcrumbFor", () => {
  it("builds a nested workflow chain and disambiguates host score from output port score", () => {
    const evaluate = deepResearch.nodes.find((n) => n.id === "n14");
    expect(evaluate).toBeDefined();

    const crumbs = breadcrumbFor(evaluate!, deepResearch, "deep-research");

    expect(crumbs.map((crumb) => crumb.label)).toEqual(["deep-research", "analyze-sources", "score", "score-section"]);
    expect(crumbs.map((crumb) => crumb.hostContractId)).toEqual([null, "n3", "n10", null]);
    expect(crumbs.map((crumb) => crumb.file)).toEqual([ROOT_FILE, ROOT_FILE, ANALYZE_FILE, SCORE_FILE]);
    expect(crumbs.map((crumb) => crumb.line)).toEqual([null, 39, 29, null]);
  });

  it("walks the selected node's own ancestor_path when its file is invoked from two hosts", () => {
    // Pins the breadcrumbFor fix: a child file invoked from TWO host steps must
    // crumb the invocation the selected node is actually in. Delegating to the
    // file-based fileChainFor would pick the FIRST invocation in contract order
    // (check-a) — wrong for a member of check-b.
    const rootFile = "/wf/root.pflow.md";
    const helperFile = "/wf/helper.pflow.md";
    const hostA = node({
      id: "h-a",
      ref: { node_id: "check-a", ancestor_path: [], port: null },
      is_group_host: true,
      source: { file: rootFile, line: 10 },
    });
    const hostB = node({
      id: "h-b",
      ref: { node_id: "check-b", ancestor_path: [], port: null },
      is_group_host: true,
      source: { file: rootFile, line: 20 },
    });
    const memberOfCheckA = node({
      id: "m-a",
      ref: { node_id: "run", ancestor_path: [{ node_id: "check-a", batch_index: null }], port: null },
      source: { file: helperFile, line: 5 },
    });
    const memberOfCheckB = node({
      id: "m-b",
      ref: { node_id: "run", ancestor_path: [{ node_id: "check-b", batch_index: null }], port: null },
      source: { file: helperFile, line: 5 },
    });
    const graph: RFGraph = { nodes: [hostA, hostB, memberOfCheckA, memberOfCheckB], edges: [], groups: [] };

    // The trap is real: the file-based chain picks check-a (first in contract order).
    expect(fileChainFor(helperFile, graph).map((crumb) => crumb.label)).toEqual(["root", "check-a", "helper"]);

    const crumbs = breadcrumbFor(memberOfCheckB, graph);

    expect(crumbs.map((crumb) => crumb.label)).toEqual(["root", "check-b", "helper"]);
    expect(crumbs.map((crumb) => crumb.hostContractId)).toEqual([null, "h-b", null]);
    expect(crumbs[1]!.file).toBe(rootFile);
    expect(crumbs[1]!.line).toBe(20);
  });

  it("resolves the host crumb past an io node sharing the same node_id and ancestor_path", () => {
    // Pins ancestorHost's is_group_host / port == null filters: _add_inputs runs
    // before steps, so an io INPUT node with the same node_id sits FIRST in
    // contract order. Without the filters the crumb would resolve to the io node
    // (no source, wrong contract id).
    const rootFile = "/wf/root.pflow.md";
    const childFile = "/wf/process.pflow.md";
    const ioInput = node({
      id: "io-1",
      kind: "input",
      ref: { node_id: "process", ancestor_path: [], port: "in" },
      is_group_host: false,
      source: null,
    });
    const host = node({
      id: "h-1",
      ref: { node_id: "process", ancestor_path: [], port: null },
      is_group_host: true,
      source: { file: rootFile, line: 12 },
    });
    const member = node({
      id: "m-1",
      ref: { node_id: "step", ancestor_path: [{ node_id: "process", batch_index: null }], port: null },
      source: { file: childFile, line: 3 },
    });
    const graph: RFGraph = { nodes: [ioInput, host, member], edges: [], groups: [] };

    const crumbs = breadcrumbFor(member, graph);

    expect(crumbs.map((crumb) => crumb.label)).toEqual(["root", "process", "process"]);
    expect(crumbs[1]!.hostContractId).toBe("h-1");
    expect(crumbs[1]!.file).toBe(rootFile);
    expect(crumbs[1]!.line).toBe(12);
  });
});

describe("fileChainFor", () => {
  it("returns the root-only chain for the root file", () => {
    expect(fileChainFor(ROOT_FILE, deepResearch, "deep-research")).toEqual([
      { label: "deep-research", file: ROOT_FILE, line: null, hostContractId: null },
    ]);
  });

  it("returns the first invocation chain for a nested file", () => {
    expect(fileChainFor(ANALYZE_FILE, deepResearch, "deep-research").map((crumb) => crumb.label)).toEqual([
      "deep-research",
      "analyze-sources",
      "analyze-source",
    ]);
  });

  it("returns the first invocation chain for a repeated batch child file", () => {
    const crumbs = fileChainFor(REVIEW_FILE, deepResearch, "deep-research");

    expect(crumbs.map((crumb) => crumb.label)).toEqual(["deep-research", "reviews", "review-aspect"]);
    expect(crumbs.map((crumb) => crumb.hostContractId)).toEqual([null, "n5", null]);
  });

  it("falls back to the root-only chain for an orphan served file", () => {
    expect(fileChainFor("/tmp/orphan.pflow.md", deepResearch, "deep-research")).toEqual([
      { label: "deep-research", file: ROOT_FILE, line: null, hostContractId: null },
    ]);
  });
});

describe("nodeBlockRange", () => {
  // Two steps at lines 3 and 9; text with a fenced prompt containing a `##`
  // (which must NOT bound the block) and a real `## Outputs` section after the
  // last step (which MUST).
  const text = [
    "# Demo", //            1
    "", //                  2
    "### first", //         3
    "", //                  4
    "```prompt", //         5
    "## Rules inside", //   6
    "```", //               7
    "", //                  8
    "### second", //        9
    "", //                 10
    "- type: shell", //    11
    "", //                 12
    "## Outputs", //       13
    "", //                 14
    "### out", //          15
  ].join("\n");
  const graph: RFGraph = {
    nodes: [
      node({ id: "n1", ref: { node_id: "first", ancestor_path: [], port: null }, source: { file: "/wf.pflow.md", line: 3 } }),
      node({ id: "n2", ref: { node_id: "second", ancestor_path: [], port: null }, source: { file: "/wf.pflow.md", line: 9 } }),
    ],
    edges: [],
    groups: [],
  };

  it("extends from the heading to the line before the next node, trimming trailing blanks", () => {
    // first's block: heading 3 → next node at 9 bounds it to 8; the fenced
    // `## Rules inside` must not cut it short; blank line 8 trims away.
    expect(nodeBlockRange(graph, "/wf.pflow.md", 3, text)).toEqual({ start: 3, end: 7 });
  });

  it("a body-line click maps to the owning node's full block", () => {
    expect(nodeBlockRange(graph, "/wf.pflow.md", 6, text)).toEqual({ start: 3, end: 7 });
  });

  it("the last step's block stops before a `##` section heading, not at EOF", () => {
    // second's block: heading 9 → the `## Outputs` heading at 13 bounds it to
    // 12; blank line 12 trims to 11.
    expect(nodeBlockRange(graph, "/wf.pflow.md", 9, text)).toEqual({ start: 9, end: 11 });
  });

  it("returns null when no node owns the line", () => {
    expect(nodeBlockRange(graph, "/wf.pflow.md", 1, text)).toBeNull();
    expect(nodeBlockRange(graph, "/other.pflow.md", 3, text)).toBeNull();
  });
});

describe("sectionHeadingLine", () => {
  const text = ["# Demo", "", "## Inputs", "", "### topic", "", "## Steps", "", "### gen", "", "```prompt", "## Outputs inside a fence", "```", "", "## Outputs", "", "### out"].join("\n");

  it("finds the Inputs and Outputs section headings", () => {
    expect(sectionHeadingLine(text, "input")).toBe(3);
    expect(sectionHeadingLine(text, "output")).toBe(15);
  });

  it("a section-looking heading inside a fence never matches", () => {
    // line 12 (`## Outputs inside a fence`) is fenced AND not an exact match;
    // the exact-but-fenced shape is the real trap:
    const fenced = ["```prompt", "## Outputs", "```", "## Outputs"].join("\n");
    expect(sectionHeadingLine(fenced, "output")).toBe(4);
  });

  it("returns null when the section does not exist", () => {
    expect(sectionHeadingLine("# Demo\n### step", "input")).toBeNull();
  });
});

describe("nodeBlockRange — past-block-end honesty", () => {
  it("returns null for a line past the owner's trimmed block (section heading / blank separator)", () => {
    const text = ["### only", "", "body", "", "## Outputs"].join("\n");
    const graph: RFGraph = {
      nodes: [node({ id: "n1", ref: { node_id: "only", ancestor_path: [], port: null }, source: { file: "/wf.pflow.md", line: 1 } })],
      edges: [],
      groups: [],
    };
    expect(nodeBlockRange(graph, "/wf.pflow.md", 3, text)).toEqual({ start: 1, end: 3 });
    // line 5 is the `## Outputs` heading — the block ended at 3; no honest extent
    expect(nodeBlockRange(graph, "/wf.pflow.md", 5, text)).toBeNull();
  });
});

describe("sectionBlockRange", () => {
  const text = ["# Demo", "", "## Inputs", "", "### topic", "", "* a note", "", "## Steps", "", "### gen", "", "```prompt", "## Not a section", "```"].join("\n");

  it("a section heading tints through its declarations until the next section", () => {
    // ## Inputs (3) through `* a note` (7) — the ### topic declaration is
    // INSIDE the section, only the next #/## heading bounds it; blank 8 trims.
    expect(sectionBlockRange(text, 3)).toEqual({ start: 3, end: 7 });
  });

  it("the title heading tints the intro until the first section", () => {
    expect(sectionBlockRange(text, 1)).toEqual({ start: 1, end: 1 });
  });

  it("returns null off-heading and for fenced heading-shaped lines", () => {
    expect(sectionBlockRange(text, 5)).toBeNull(); // ### topic — node territory
    expect(sectionBlockRange(text, 14)).toBeNull(); // fenced "## Not a section"
  });
});
