// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Root } from "hast";

import type { RFGraph, RFNode, SourceFiles } from "../types";
import { highlight } from "../utils/highlight";
import { SourcePane } from "./SourcePane";

// Keep the pane synchronous in jsdom. Highlighting is covered by
// utils/highlight tests; this suite pins source-pane state and navigation.
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});

afterEach(cleanup);

const ROOT_FILE = "/workflows/root.pflow.md";
const CHILD_FILE = "/workflows/child.pflow.md";
const ROOT_TEXT = ["# Demo", "", "## Steps", "", "### first", "", "Do first.", "", "### second", "", "Do second."].join("\n");
const CHILD_TEXT = ["# Child", "", "### inner", "", "Do inner."].join("\n");

function node(overrides: Partial<RFNode>): RFNode {
  return {
    id: "n1",
    ref: { node_id: "first", ancestor_path: [], port: null },
    kind: "shell",
    purpose: "",
    params: [],
    io: null,
    loop: null,
    batch: null,
    parent: null,
    source: { file: ROOT_FILE, line: 5 },
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

const firstNode = node({});
const secondNode = node({
  id: "n2",
  ref: { node_id: "second", ancestor_path: [], port: null },
  source: { file: ROOT_FILE, line: 9 },
});
const childNode = node({
  id: "n3",
  ref: { node_id: "inner", ancestor_path: [{ node_id: "child", batch_index: null }], port: null },
  source: { file: CHILD_FILE, line: 3 },
});
const hostNode = node({
  id: "h1",
  ref: { node_id: "child", ancestor_path: [], port: null },
  kind: "workflow",
  source: { file: ROOT_FILE, line: 13 },
  is_group_host: true,
});

const graph: RFGraph = {
  nodes: [firstNode, secondNode, hostNode, childNode],
  edges: [],
  groups: [{ id: "g_child", kind: "workflow", parent: null, host: "h1", members: ["n3"], nesting_depth: 0, annotations: {} }],
};

const source: SourceFiles = {
  root: ROOT_FILE,
  files: {
    [ROOT_FILE]: ROOT_TEXT,
    [CHILD_FILE]: CHILD_TEXT,
  },
};

function renderPane(props: Partial<Parameters<typeof SourcePane>[0]> = {}) {
  const onNavigate = vi.fn();
  const result = render(
    <SourcePane
      source={source}
      sourceError={null}
      graph={graph}
      selectedNode={null}
      selectedIoKind={null}
      renderedIds={new Set(["n1", "n2", "n3", "g_child"])}
      workflowName="root"
      jump={0}
      onNavigate={onNavigate}
      {...props}
    />,
  );
  return { ...result, onNavigate };
}

function sourceLine(container: HTMLElement, line: number): HTMLElement {
  const el = container.querySelector(`.src-line[data-line="${line}"]`);
  expect(el).toBeTruthy();
  return el as HTMLElement;
}

// Crumb labels can collide (the host step and the child file are both named
// "child"), so the lookup disambiguates by the title attribute (crumb.file).
function crumbButton(container: HTMLElement, label: string, title?: string): HTMLElement {
  const match = Array.from(container.querySelectorAll<HTMLElement>("button.source-crumb")).find(
    (el) => el.textContent === label && (title == null || el.getAttribute("title") === title),
  );
  expect(match).toBeTruthy();
  return match!;
}

describe("SourcePane", () => {
  it("renders plain source lines with stable gutter numbers", () => {
    const { container } = renderPane();

    expect(sourceLine(container, 1).textContent).toContain("# Demo");
    expect(sourceLine(container, 5).textContent).toContain("### first");
    expect(sourceLine(container, 5).querySelector(".src-gutter")?.textContent).toBe("5");
  });

  it("decorates body tokens instantly and upgrades fence CONTENT when shiki resolves", async () => {
    const text = ["## Steps", "", "### fetch", "- type: shell", "- inputs: ${data}", "", "```shell command", "echo ${repo}", "```"].join("\n");
    // shiki stub for the one-line fence body "echo ${repo}"
    vi.mocked(highlight).mockResolvedValueOnce({
      type: "root",
      children: [
        {
          type: "element",
          tagName: "pre",
          properties: {},
          children: [
            {
              type: "element",
              tagName: "code",
              properties: {},
              children: [
                {
                  type: "element",
                  tagName: "span",
                  properties: { class: "line" },
                  children: [{ type: "element", tagName: "span", properties: { style: "color:#79c0ff" }, children: [{ type: "text", value: "echo ${repo}" }] }],
                },
              ],
            },
          ],
        },
      ],
    } satisfies Root);
    const { container } = renderPane({ source: { root: ROOT_FILE, files: { [ROOT_FILE]: text } } });

    // Instant tier (no await): section heading, kind-colored type value, muted
    // key, and the teal body ref all reach the DOM before shiki resolves.
    expect(container.querySelector(".src-content .src-section")).toBeTruthy();
    expect(container.querySelector(".src-content .src-type")).toBeTruthy();
    expect(container.querySelector(".src-content .src-key")).toBeTruthy();
    expect(container.querySelector(".src-content .src-ref")).toBeTruthy();

    // Async tier: the fence content line (line 8) starts as instant plain text
    // + a class-only `.src-ref`, then swaps to the shiki token span (inline
    // style) once highlighting resolves — verbatim content preserved.
    expect(sourceLine(container, 8).querySelector("span[style]")).toBeNull();
    await waitFor(() => expect(sourceLine(container, 8).querySelector("span[style]")).toBeTruthy());
    expect(sourceLine(container, 8).textContent).toContain("echo ${repo}");
  });

  it("clicking a node heading line navigates to the resolved rendered node id", () => {
    const { container, onNavigate } = renderPane();

    fireEvent.click(sourceLine(container, 5));

    expect(onNavigate).toHaveBeenCalledWith("n1", "n1");
  });

  it("clicking below the last node maps to the last authored node above that line", () => {
    const { container, onNavigate } = renderPane();

    fireEvent.click(sourceLine(container, 11));

    expect(onNavigate).toHaveBeenCalledWith("n2", "n2");
  });

  it("selected node changes switch files and mark the authored line", async () => {
    const { container, rerender, onNavigate } = renderPane();

    rerender(
      <SourcePane
        source={source}
        sourceError={null}
        graph={graph}
        selectedNode={childNode}
        selectedIoKind={null}
        renderedIds={new Set(["n1", "n2", "n3", "g_child"])}
        workflowName="root"
        jump={0}
        onNavigate={onNavigate}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText(CHILD_FILE)).toBeTruthy());
    expect(sourceLine(container, 3).textContent).toContain("### inner");
    expect(sourceLine(container, 3).className).toContain("src-line-active");
  });

  it("renders the empty state when the server has no files for the workflow", () => {
    renderPane({ source: { root: null, files: {} } });

    expect(screen.getByText("No source file is available for this workflow.")).toBeTruthy();
  });

  it("keeps the previous file visible and reports a missing selected source file", async () => {
    const missingNode = node({ id: "missing", source: { file: "/gone/missing.pflow.md", line: 4 } });
    const { container, rerender, onNavigate } = renderPane();

    rerender(
      <SourcePane
        source={source}
        sourceError={null}
        graph={graph}
        selectedNode={missingNode}
        selectedIoKind={null}
        renderedIds={new Set(["n1", "n2", "n3", "g_child"])}
        workflowName="root"
        jump={0}
        onNavigate={onNavigate}
      />,
    );

    await waitFor(() => expect(screen.getByText("source for missing.pflow.md could not be read")).toBeTruthy());
    expect(sourceLine(container, 5).textContent).toContain("### first");
  });

  it("renders a source error banner without hiding the pane shell", () => {
    renderPane({ source: null, sourceError: "source request failed" });

    expect(screen.getByText("source request failed")).toBeTruthy();
  });

  it("crumb click resolves a suppressed host to its representative group at click time", () => {
    // The host "h1" is NOT in renderedIds (suppressed); its representative
    // group "g_child" IS. The crumb must navigate to the group id, never the
    // raw host contract id.
    const { container, onNavigate } = renderPane({ selectedNode: childNode });

    expect(screen.getByLabelText(CHILD_FILE)).toBeTruthy();
    fireEvent.click(crumbButton(container, "child", ROOT_FILE));

    expect(onNavigate.mock.calls).toEqual([["g_child", "g_child"]]);
  });

  it("crumb click without a rendered representative switches the file without navigating", () => {
    // Neither the host nor its representative group renders (g_child removed):
    // the crumb still switches the displayed file, but never fires a ghost focus.
    const { container, onNavigate } = renderPane({
      selectedNode: childNode,
      renderedIds: new Set(["n1", "n2", "n3"]),
    });

    expect(screen.getByLabelText(CHILD_FILE)).toBeTruthy();
    fireEvent.click(crumbButton(container, "child", ROOT_FILE));

    expect(screen.getByLabelText(ROOT_FILE)).toBeTruthy();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("line click falls through unresolvable candidates to the first rendered one", () => {
    // Two batch copies share heading line 5. The first in contract order is
    // unrendered with no representative group; selectLine must keep iterating
    // and navigate to the second.
    const twinA = node({ id: "copy#0", ref: { node_id: "copy", ancestor_path: [], port: null } });
    const twinB = node({ id: "copy#1", ref: { node_id: "copy", ancestor_path: [], port: null } });
    const twinGraph: RFGraph = { nodes: [twinA, twinB], edges: [], groups: [] };
    const { container, onNavigate } = renderPane({ graph: twinGraph, renderedIds: new Set(["copy#1"]) });

    fireEvent.click(sourceLine(container, 5));

    expect(onNavigate.mock.calls).toEqual([["copy#1", "copy#1"]]);
  });

  it("line click with no resolvable candidate marks the line locally without navigating", () => {
    const twinA = node({ id: "copy#0", ref: { node_id: "copy", ancestor_path: [], port: null } });
    const twinB = node({ id: "copy#1", ref: { node_id: "copy", ancestor_path: [], port: null } });
    const twinGraph: RFGraph = { nodes: [twinA, twinB], edges: [], groups: [] };
    const { container, onNavigate } = renderPane({ graph: twinGraph, renderedIds: new Set() });

    fireEvent.click(sourceLine(container, 5));

    expect(sourceLine(container, 5).className).toContain("src-line-active");
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("applies a selection that arrived before the source finished loading", async () => {
    // Deep-link race: the node is selected while source is still null. Once the
    // source arrives, the sync effect (keyed on `source` too) must switch to the
    // selected node's file and mark its line — a mutant dropping `source` from
    // the effect deps leaves the pane on the root file.
    const { container, rerender, onNavigate } = renderPane({ selectedNode: childNode, source: null });

    expect(screen.getByText("Loading source…")).toBeTruthy();

    rerender(
      <SourcePane
        source={source}
        sourceError={null}
        graph={graph}
        selectedNode={childNode}
        selectedIoKind={null}
        renderedIds={new Set(["n1", "n2", "n3", "g_child"])}
        workflowName="root"
        jump={0}
        onNavigate={onNavigate}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText(CHILD_FILE)).toBeTruthy());
    expect(sourceLine(container, 3).className).toContain("src-line-active");
  });

  it("clearing to a line-less crumb drops the previous file's active line mark", async () => {
    // Selecting the child node marks child line 3; clicking the root crumb
    // (line: null) must NOT leave line 3 of the ROOT file marked — line 3
    // exists in both files, so a stale mark would render as a real mapping.
    const { container, onNavigate } = renderPane({ selectedNode: childNode });

    await waitFor(() => expect(screen.getByLabelText(CHILD_FILE)).toBeTruthy());
    expect(sourceLine(container, 3).className).toContain("src-line-active");

    fireEvent.click(crumbButton(container, "root"));

    expect(screen.getByLabelText(ROOT_FILE)).toBeTruthy();
    expect(container.querySelector(".src-line-active")).toBeNull();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("a source-link JUMP re-asserts the selected node's line after the mark moved", () => {
    // The read panel's source link bumps `jump`; the pane returns to the
    // selected node's line even when the user has clicked elsewhere since.
    const onNavigate = vi.fn();
    const props = {
      source,
      sourceError: null,
      graph,
      selectedNode: firstNode, // ROOT_FILE line 5
      selectedIoKind: null as "input" | "output" | null,
      renderedIds: new Set(["n1", "n2", "n3", "g_child"]),
      workflowName: "root",
      onNavigate,
    };
    const { container, rerender } = render(<SourcePane {...props} jump={0} />);
    expect(sourceLine(container, 5).className).toContain("src-line-active");
    // The user clicks another line — the mark leaves the node's line.
    fireEvent.click(sourceLine(container, 9));
    expect(sourceLine(container, 9).className).toContain("src-line-active");
    expect(sourceLine(container, 5).className).not.toContain("src-line-active");
    // A jump returns the mark to the node's line (selectedNode unchanged).
    rerender(<SourcePane {...props} jump={1} />);
    expect(sourceLine(container, 5).className).toContain("src-line-active");
  });

  it("an explicit jumpTarget wins over the selected node — the IoPanel per-port source link", () => {
    // An io selection sets no selectedNode; the port link carries its OWN
    // file:line as jumpTarget, and the jump lands there.
    const onNavigate = vi.fn();
    const props = {
      source,
      sourceError: null,
      graph,
      selectedNode: firstNode, // ROOT_FILE line 5 — must NOT win
      selectedIoKind: null as "input" | "output" | null,
      renderedIds: new Set(["n1", "n2", "n3", "g_child"]),
      workflowName: "root",
      onNavigate,
    };
    const { container, rerender } = render(<SourcePane {...props} jump={0} jumpTarget={null} />);
    expect(sourceLine(container, 5).className).toContain("src-line-active");
    rerender(<SourcePane {...props} jump={1} jumpTarget={{ file: ROOT_FILE, line: 9 }} />);
    expect(sourceLine(container, 9).className).toContain("src-line-active");
    expect(sourceLine(container, 5).className).not.toContain("src-line-active");
  });

  it("a jumpTarget applies on MOUNT — the closed-pane port-link click (and beats the io-heading sync)", () => {
    // Clicking an IoPanel port link with the pane CLOSED both opens (mounts)
    // the pane and bumps `jump`: the jump must land on the PORT's line, not
    // the io-kind section heading (an io selection sets no selectedNode to
    // re-assert it — this exact miss was browser-caught).
    const { container } = renderPane({
      selectedNode: null,
      selectedIoKind: "output",
      jump: 1,
      jumpTarget: { file: ROOT_FILE, line: 9 },
    });
    expect(sourceLine(container, 9).className).toContain("src-line-active");
  });
});

describe("node block extent", () => {
  it("a selected node marks its heading strongly AND its whole authored block faintly", () => {
    // firstNode's block: heading 5 → bounded by secondNode's heading at 9 →
    // lines 5-8, trailing blank 8 trimmed → 5-7. Heading keeps the strong
    // active mark; the block rows carry the barely-visible extent tint.
    const { container } = renderPane({ selectedNode: firstNode });
    expect(sourceLine(container, 5).className).toContain("src-line-active");
    for (const line of [5, 6, 7]) {
      expect(sourceLine(container, line).className).toContain("src-line-block");
    }
    // The next node's territory is untouched — extent never bleeds across.
    expect(sourceLine(container, 9).className).not.toContain("src-line-block");
    expect(sourceLine(container, 8).className).not.toContain("src-line-block");
  });
});

describe("prose wrapping", () => {
  it("prose lines soft-wrap; fenced code/prompt lines (and the fences) keep exact layout", () => {
    const fenceText = ["### step", "a long description line", "```python code", "x = 1", "```", "after the fence"].join("\n");
    const { container } = renderPane({
      source: { root: ROOT_FILE, files: { [ROOT_FILE]: fenceText } },
    });
    const wrapFlags = [1, 2, 3, 4, 5, 6].map((n) => sourceLine(container, n).className.includes("src-line-wrap"));
    // heading + description + after-fence wrap; the fence delimiters and the
    // code inside stay no-wrap (wrapping would lie about their whitespace)
    expect(wrapFlags).toEqual([true, true, false, false, false, true]);
  });
});

describe("io card selection", () => {
  it("an Inputs/Outputs card selection syncs to its section heading in the root file", () => {
    const ioText = ["# Demo", "", "## Inputs", "", "### topic", "", "## Steps", "", "### first", "", "## Outputs", "", "### out"].join("\n");
    const ioSource: SourceFiles = { root: ROOT_FILE, files: { [ROOT_FILE]: ioText } };
    const { container, rerender, onNavigate } = renderPane({ source: ioSource, selectedIoKind: "input" });
    expect(sourceLine(container, 3).className).toContain("src-line-active"); // ## Inputs
    // the whole section tints — heading through its declarations (### topic at
    // 5), bounded by ## Steps at 7
    for (const line of [3, 4, 5]) {
      expect(sourceLine(container, line).className).toContain("src-line-block");
    }
    expect(sourceLine(container, 7).className).not.toContain("src-line-block");
    // switching the selection to the Outputs card moves the mark
    rerender(
      <SourcePane
        source={ioSource}
        sourceError={null}
        graph={graph}
        selectedNode={null}
        selectedIoKind="output"
        renderedIds={new Set(["n1", "n2", "n3", "g_child"])}
        workflowName="root"
        jump={0}
        onNavigate={onNavigate}
      />,
    );
    expect(sourceLine(container, 11).className).toContain("src-line-active"); // ## Outputs
  });
});
