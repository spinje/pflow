// @vitest-environment jsdom
// EdgePanel render tests — one per variant, fixtures mirroring REAL contract
// shapes (run-from-plan's e2/e3/e12/e14 family + conditional-branching's error
// edge). EdgePanel is a plain component (no React Flow context), so it renders
// directly under jsdom.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { bindingParam } from "../graph/flow";
import { EdgePanel } from "./EdgePanel";
import type { RFEdge, RFGraph, RFNode } from "../types";

afterEach(cleanup);

function node(id: string, over: Partial<RFNode> = {}): RFNode {
  return {
    id,
    ref: { node_id: id, ancestor_path: [], port: null },
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
    is_transform: false,
    output_shape: null,
    is_group_host: false,
    unexpanded: null,
    annotations: {},
    ...over,
  };
}

function edge(id: string, source: string, target: string, kind: RFEdge["kind"], over: Partial<RFEdge> = {}): RFEdge {
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [], ...over };
}

const noop = (): void => {};

function show(graph: RFGraph, edgeId: string, rendered?: string[], onNavigate = noop as (f: string, s?: string | null) => void): void {
  const e = graph.edges.find((x) => x.id === edgeId)!;
  render(
    <EdgePanel
      edge={e}
      graph={graph}
      renderedIds={new Set(rendered ?? graph.nodes.map((n) => n.id))}
      onNavigate={onNavigate}
      onClose={noop}
    />,
  );
}

describe("EdgePanel — data variant", () => {
  // mirrors run-from-plan e2: happy-check.result → report-commits.impl
  // Production-style ids: flat ids (n1/n2) NEVER equal ref.node_id — an id↔name
  // confusion in the panel must fail here, not pass vacuously (review-caught).
  const graph: RFGraph = {
    nodes: [
      node("n1", { ref: { node_id: "happy-check", ancestor_path: [], port: null }, kind: "claude-code" }),
      node("n2", {
        ref: { node_id: "report-commits", ancestor_path: [], port: null },
        kind: "code",
        params: [{ name: "impl", value: "${happy-check.result}", is_dynamic: true, source: { file: "execute-plan.pflow.md", line: 212 } }],
      }),
    ],
    edges: [edge("e2", "n1", "n2", "data_flow", { output_field: "result", input_name: "impl" })],
    groups: [],
  };

  it("titles the flow statement, names both chips, and shows the landing param with its ${ref} highlighted", () => {
    show(graph, "e2");
    expect(screen.getByText("data flow")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("result → impl");
    expect(screen.getByText("happy-check")).toBeTruthy();
    expect(screen.getByText("report-commits")).toBeTruthy();
    expect(screen.getByText("receives")).toBeTruthy();
    // THIS edge's ref is highlighted inside the param value
    const mark = document.querySelector("mark.ref-mark");
    expect(mark?.textContent).toBe("${happy-check.result}");
    expect(screen.getByText("execute-plan.pflow.md:212")).toBeTruthy();
  });

  it("an interpolated param says which of N references the clicked line is", () => {
    // mirrors e3: three inputs feeding one prompt — one edge per ${ref}
    const g: RFGraph = {
      nodes: [
        node("repo_dir", { kind: "input", io: { data_type: "string", required: true, default: null } }),
        node("plan_path", { kind: "input", io: { data_type: "string", required: true, default: null } }),
        node("chunk", { kind: "code" }),
        node("implement", {
          kind: "claude-code",
          params: [{ name: "prompt", value: "work in ${repo_dir} on ${chunk.body} using ${plan_path}", is_dynamic: true, source: null }],
        }),
      ],
      edges: [
        edge("e3", "repo_dir", "implement", "data_flow", { input_name: "prompt" }),
        edge("e4", "plan_path", "implement", "data_flow", { input_name: "prompt" }),
        edge("e5", "chunk", "implement", "data_flow", { output_field: "body", input_name: "prompt" }),
      ],
      groups: [],
    };
    show(g, "e3");
    // IO source: the port name stands in for the missing output_field
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("repo_dir → prompt");
    expect(screen.getByText(/one of 3 references into/)).toBeTruthy();
    // only THIS edge's ref is marked, not the prompt's other refs
    const marks = [...document.querySelectorAll("mark.ref-mark")].map((m) => m.textContent);
    expect(marks).toEqual(["${repo_dir}"]);
  });

  it("a role-less (re-anchored/deduped) edge falls back to neutral wording — never an empty heading", () => {
    const g: RFGraph = {
      nodes: [node("a"), node("b")],
      edges: [edge("ex", "a", "b", "data_flow")],
      groups: [],
    };
    show(g, "ex");
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("data connection");
  });

  it("parallel bindings between the same pair surface as a bundle count (the rendered line can be a dedupe survivor)", () => {
    const g: RFGraph = {
      nodes: [
        node("a"),
        node("b", {
          params: [
            { name: "x", value: "${a.o}", is_dynamic: true, source: null },
            { name: "y", value: "${a.p}", is_dynamic: true, source: null },
          ],
        }),
      ],
      edges: [
        edge("b1", "a", "b", "data_flow", { output_field: "o", input_name: "x" }),
        edge("b2", "a", "b", "data_flow", { output_field: "p", input_name: "y" }),
      ],
      groups: [],
    };
    show(g, "b1");
    expect(screen.getByText(/one of 2 bindings between these nodes/)).toBeTruthy();
  });

  it("a binding into a workflow output shows the port's io facts (an IO target has no params)", () => {
    const g: RFGraph = {
      nodes: [node("a"), node("pr_url", { kind: "output", io: { data_type: "string", required: false, default: null } })],
      edges: [edge("eo", "a", "pr_url", "data_flow", { output_field: "url" })],
      groups: [],
    };
    show(g, "eo");
    expect(screen.getByText(/workflow output/)).toBeTruthy();
    expect(screen.getByText(/\(string\)/)).toBeTruthy();
  });

  it("a binding into a SUB-WORKFLOW input port resolves through to the HOST step's authored param, highlighted (user-caught)", () => {
    // pair.result → song-creator's concept_brief port: the ${} text lives on the
    // sub-workflow STEP's `inputs:` mapping, NOT on the port (it has no params).
    const g: RFGraph = {
      nodes: [
        node("n3", { ref: { node_id: "pair", ancestor_path: [], port: null }, kind: "code" }),
        node("n4", {
          ref: { node_id: "song-creator", ancestor_path: [], port: null },
          kind: "workflow",
          is_group_host: true,
          params: [
            { name: "workflow", value: "song-creator", is_dynamic: false, source: null },
            {
              name: "inputs",
              value: { concept: "${item}", concept_brief: "${pair.result}" },
              is_dynamic: true,
              source: { file: "fan-out.pflow.md", line: 42 },
            },
          ],
        }),
        node("n5", { ref: { node_id: "concept_brief", ancestor_path: [], port: null }, kind: "input", io: { data_type: "string", required: true, default: null }, parent: "gin" }),
      ],
      edges: [edge("eb", "n3", "n5", "data_flow", { output_field: "result" })],
      groups: [
        { id: "gwf", kind: "workflow", parent: null, host: "n4", members: [], nesting_depth: 0, annotations: {} },
        { id: "gin", kind: "input_wrapper", parent: "gwf", host: null, members: ["n5"], nesting_depth: 1, annotations: {} },
      ],
    };
    show(g, "eb");
    // the host's `inputs` param renders, THIS edge's ref highlighted — not ${item}
    expect(screen.getByText("receives")).toBeTruthy();
    const marks = [...document.querySelectorAll("mark.ref-mark")].map((m) => m.textContent);
    expect(marks).toEqual(["${pair.result}"]);
    expect(screen.getByText("fan-out.pflow.md:42")).toBeTruthy();
    // and the io fact names the port honestly (it is NOT a "workflow output")
    expect(screen.getByText(/sub-workflow input of song-creator/)).toBeTruthy();
  });
});

describe("EdgePanel — branch / end variants", () => {
  // mirrors run-from-plan e12/e14: check-validate forks to fix-tests or ends
  const graph: RFGraph = {
    nodes: [node("check-validate", { kind: "code", is_decision: true }), node("fix-tests", { kind: "claude-code" }), node("__end__", { kind: "end" })],
    edges: [
      edge("e12", "check-validate", "fix-tests", "branch", { label: "fix-tests", condition: "elif round < cap" }),
      edge("e14", "check-validate", "__end__", "end", { condition: "if ok · else" }),
    ],
    groups: [],
  };

  it("branch: outcome title, untruncated condition, and the source's full outcome table with THIS row marked", () => {
    show(graph, "e12");
    expect(screen.getByText("branch · outcome")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("fix-tests");
    expect(screen.getAllByText("elif round < cap").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/all outcomes of check-validate/)).toBeTruthy();
    const marked = document.querySelector(".fact-marked");
    expect(marked?.textContent).toContain("fix-tests");
  });

  it("a DECISION's end edge is its reserved outcome (discriminated by is_decision, NOT condition presence)", () => {
    show(graph, "e14");
    expect(screen.getByText("end · outcome")).toBeTruthy();
    expect(screen.getAllByText("if ok · else").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/all outcomes of check-validate/)).toBeTruthy();
  });

  it("a decision's end edge whose condition extraction failed STAYS an outcome (fail-closed extraction ships condition-less)", () => {
    const g: RFGraph = {
      ...graph,
      edges: [edge("e14", "check-validate", "__end__", "end")], // no condition
    };
    show(g, "e14");
    expect(screen.getByText("end · outcome")).toBeTruthy();
    expect(screen.queryByText("The workflow's final step.")).toBeNull();
  });

  it("a STATIC end edge (non-decision source) is the workflow's final step", () => {
    const g: RFGraph = {
      nodes: [node("last"), node("__end__", { kind: "end" })],
      edges: [edge("ee", "last", "__end__", "end")],
      groups: [],
    };
    show(g, "ee");
    expect(document.querySelector(".read-panel-kind")?.textContent).toBe("end");
    expect(screen.getByText("The workflow's final step.")).toBeTruthy();
  });
});

describe("EdgePanel — error / sequential variants", () => {
  it("error: states the semantics the dashed red line never explains", () => {
    const g: RFGraph = {
      nodes: [node("classify", { kind: "llm" }), node("handle-error", { kind: "shell" })],
      edges: [edge("err", "classify", "handle-error", "error", { label: "error" })],
      groups: [],
    };
    show(g, "err");
    expect(screen.getByText("error route")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("on failure → handle-error");
    expect(screen.getByText(/fails — after its retries are exhausted/)).toBeTruthy();
  });

  it("sequential: a shadowed trunk edge surfaces the model's shadowed fact", () => {
    const g: RFGraph = {
      nodes: [node("a"), node("b")],
      edges: [edge("sq", "a", "b", "sequential", { shadowed: true })],
      groups: [],
    };
    show(g, "sq");
    expect(screen.getByText(/also implied by a data dependency/)).toBeTruthy();
  });
});

describe("EdgePanel — endpoint chips resolve-or-disable", () => {
  it("a suppressed group host's chip navigates to its representative group", () => {
    const g: RFGraph = {
      nodes: [node("a"), node("ep-host", { kind: "workflow", is_group_host: true })],
      edges: [edge("e0", "a", "ep-host", "sequential")],
      groups: [{ id: "gwf", kind: "workflow", parent: null, host: "ep-host", members: ["x"], nesting_depth: 0, annotations: {} }],
    };
    const nav = vi.fn();
    show(g, "e0", ["a", "gwf"], nav);
    fireEvent.click(screen.getByText("ep-host"));
    expect(nav).toHaveBeenCalledWith("gwf", "gwf");
  });

  it("an endpoint hidden inside a collapsed ancestor renders a DISABLED chip — visible honesty, no silent no-op", () => {
    const g: RFGraph = {
      nodes: [node("a"), node("hidden-leaf")],
      edges: [edge("e0", "a", "hidden-leaf", "sequential")],
      groups: [],
    };
    show(g, "e0", ["a"]); // hidden-leaf not rendered, no representative
    const chip = screen.getByText("hidden-leaf").closest("button");
    expect(chip?.disabled).toBe(true);
  });

  it("an IO-port chip uses port-focus semantics (focus the row, keep this panel)", () => {
    const g: RFGraph = {
      nodes: [
        node("repo", { kind: "input", io: { data_type: "string", required: true, default: null } }),
        node("b", { params: [{ name: "x", value: "${repo}", is_dynamic: true, source: null }] }),
      ],
      edges: [edge("e0", "repo", "b", "data_flow", { input_name: "x" })],
      groups: [],
    };
    const nav = vi.fn();
    show(g, "e0", ["b"], nav);
    fireEvent.click(screen.getByText("repo"));
    expect(nav).toHaveBeenCalledWith("repo"); // no selectedId argument — panel stays
  });
});

describe("bindingParam — the targetHandleFor mirror", () => {
  it("finds a dict-key binding (input_name is a key inside a dict-valued param)", () => {
    const target = node("t", {
      kind: "code",
      params: [{ name: "inputs", value: { data: "${a.o}", other: 3 }, is_dynamic: true, source: null }],
    });
    expect(bindingParam(target, "data")?.name).toBe("inputs");
  });

  it("ignores a dict key whose value is not a ${} string (degrade, never mis-attribute)", () => {
    const target = node("t", {
      kind: "code",
      params: [{ name: "inputs", value: { data: "plain" }, is_dynamic: false, source: null }],
    });
    expect(bindingParam(target, "data")).toBeNull();
  });
});

describe("EdgePanel — output_path (sub-key) edges read as DISTINCT connections", () => {
  // Two sub-key lines from ONE field gave byte-identical panels before the panel
  // learned output_path (review-caught 2026-06-11). Title, highlight, and bundle
  // entries must all carry the sub-key path.
  const g: RFGraph = {
    nodes: [
      node("n1", { ref: { node_id: "gen", ancestor_path: [], port: null }, kind: "code" }),
      node("n2", {
        ref: { node_id: "use", ancestor_path: [], port: null },
        params: [{ name: "a", value: "use ${gen.result.ok} and ${gen.result.err}", is_dynamic: true, source: null }],
      }),
    ],
    edges: [
      edge("p1", "n1", "n2", "data_flow", { output_field: "result", output_path: ["ok"], input_name: "a" }),
      edge("p2", "n1", "n2", "data_flow", { output_field: "result", output_path: ["err"], input_name: "a" }),
    ],
    groups: [],
  };

  it("the title names the sub-key, not just the field", () => {
    show(g, "p1");
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("result.ok → a");
  });

  it("ONLY this line's ref highlights — never the sibling sub-key of the same field", () => {
    show(g, "p1");
    const marks = [...document.querySelectorAll("mark.ref-mark")].map((m) => m.textContent);
    expect(marks).toEqual(["${gen.result.ok}"]);
  });

  it("bundle entries name the sub-keys, never two identical field rows", () => {
    show(g, "p1");
    expect(screen.getByText(/result\.ok → a, result\.err → a/)).toBeTruthy();
  });
});

describe("EdgePanel — hostless item containers and coalesce refs", () => {
  it("a literal-batch ITEM container's port resolves PAST the hostless group to the batch host (never 'workflow input')", () => {
    const g: RFGraph = {
      nodes: [
        node("n1", { ref: { node_id: "prep", ancestor_path: [], port: null } }),
        node("n2", {
          ref: { node_id: "work", ancestor_path: [], port: null },
          kind: "workflow",
          is_group_host: true,
          params: [{ name: "inputs", value: { x: "${prep.stdout}" }, is_dynamic: true, source: null }],
        }),
        node("n3", { ref: { node_id: "x", ancestor_path: [], port: null }, kind: "input", io: { data_type: null, required: true, default: null }, parent: "g_in" }),
      ],
      edges: [edge("eb", "n1", "n3", "data_flow", { output_field: "stdout" })],
      groups: [
        { id: "g_batch", kind: "batch", parent: null, host: "n2", members: [], nesting_depth: 0, annotations: {} },
        { id: "g_item", kind: "workflow", parent: "g_batch", host: null, members: [], nesting_depth: 1, annotations: {} },
        { id: "g_in", kind: "input_wrapper", parent: "g_item", host: null, members: ["n3"], nesting_depth: 2, annotations: {} },
      ],
    };
    show(g, "eb");
    expect(screen.getByText("receives")).toBeTruthy();
    const marks = [...document.querySelectorAll("mark.ref-mark")].map((m) => m.textContent);
    expect(marks).toEqual(["${prep.stdout}"]);
    expect(screen.getByText(/sub-workflow input of work/)).toBeTruthy();
    expect(screen.queryByText(/workflow input [^o]/)).toBeNull();
  });

  it("a coalesce-authored ref still highlights (matching is per operand)", () => {
    const g: RFGraph = {
      nodes: [
        node("n1", { ref: { node_id: "gen", ancestor_path: [], port: null }, kind: "code" }),
        node("n2", {
          ref: { node_id: "use", ancestor_path: [], port: null },
          params: [{ name: "a", value: '${gen.result ?? "fallback"}', is_dynamic: true, source: null }],
        }),
      ],
      edges: [edge("ec", "n1", "n2", "data_flow", { output_field: "result", input_name: "a" })],
      groups: [],
    };
    show(g, "ec");
    const marks = [...document.querySelectorAll("mark.ref-mark")].map((m) => m.textContent);
    expect(marks).toEqual(['${gen.result ?? "fallback"}']);
  });
});
