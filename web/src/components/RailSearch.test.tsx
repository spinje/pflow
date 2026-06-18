// @vitest-environment jsdom
// The rail's search box: open → filter (node_id prefix > substring > purpose) →
// select. A plain component (no React Flow), so it renders under jsdom.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RailSearch } from "./RailSearch";
import type { RFNode } from "../types";

afterEach(cleanup);

// Flat ids (n1/n2) NEVER equal ref.node_id — an id↔name confusion must fail here.
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
    cached_prefix: null,
    is_group_host: false,
    unexpanded: null,
    annotations: {},
    ...over,
  };
}

const nodes: RFNode[] = [
  node("n1", { ref: { node_id: "fetch-image", ancestor_path: [], port: null }, kind: "http", purpose: "download the file" }),
  node("n2", { ref: { node_id: "resize-image", ancestor_path: [], port: null }, kind: "code", purpose: "shrink it" }),
  node("n3", { ref: { node_id: "classify", ancestor_path: [], port: null }, kind: "llm", purpose: "fetch a verdict" }),
];

function open(): HTMLInputElement {
  fireEvent.click(screen.getByRole("button", { name: "Search nodes" }));
  return screen.getByPlaceholderText("Find a node…") as HTMLInputElement;
}

describe("RailSearch", () => {
  it("is closed until the magnifier is clicked", () => {
    render(<RailSearch nodes={nodes} onSelect={vi.fn()} />);
    expect(screen.queryByPlaceholderText("Find a node…")).toBeNull();
    open();
    expect(screen.getByPlaceholderText("Find a node…")).toBeTruthy();
  });

  it("ranks a node_id prefix above a purpose-only match", () => {
    const { container } = render(<RailSearch nodes={nodes} onSelect={vi.fn()} />);
    fireEvent.change(open(), { target: { value: "fetch" } });
    // fetch-image (name prefix, score 0) before classify (purpose 'fetch', score 2)
    const names = Array.from(container.querySelectorAll(".rail-search-result-name")).map((e) => e.textContent);
    expect(names).toEqual(["fetch-image", "classify"]);
  });

  it("a substring match on the name lists every hit; a non-match is excluded", () => {
    const { container } = render(<RailSearch nodes={nodes} onSelect={vi.fn()} />);
    fireEvent.change(open(), { target: { value: "image" } });
    const names = Array.from(container.querySelectorAll(".rail-search-result-name")).map((e) => e.textContent);
    expect(names).toEqual(["fetch-image", "resize-image"]); // classify excluded
  });

  it("clicking a result fires onSelect with that node, then closes", () => {
    const onSelect = vi.fn();
    render(<RailSearch nodes={nodes} onSelect={onSelect} />);
    fireEvent.change(open(), { target: { value: "resize" } });
    fireEvent.click(screen.getByText("resize-image"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0]![0].ref.node_id).toBe("resize-image");
    expect(screen.queryByPlaceholderText("Find a node…")).toBeNull();
  });

  it("Enter selects the highlighted (first) row; Escape closes without selecting", () => {
    const onSelect = vi.fn();
    render(<RailSearch nodes={nodes} onSelect={onSelect} />);
    const input = open();
    fireEvent.change(input, { target: { value: "fetch" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect.mock.calls[0]![0].ref.node_id).toBe("fetch-image");

    const reopened = open();
    fireEvent.change(reopened, { target: { value: "resize" } });
    fireEvent.keyDown(reopened, { key: "Escape" });
    expect(screen.queryByPlaceholderText("Find a node…")).toBeNull();
    expect(onSelect).toHaveBeenCalledTimes(1); // Escape didn't select
  });

  it("a no-match query shows the empty hint, not a stale list", () => {
    render(<RailSearch nodes={nodes} onSelect={vi.fn()} />);
    fireEvent.change(open(), { target: { value: "zzzzz" } });
    expect(screen.getByText("No matching nodes")).toBeTruthy();
  });

  it("Cmd/Ctrl+K toggles the palette from anywhere", () => {
    render(<RailSearch nodes={nodes} onSelect={vi.fn()} />);
    expect(screen.queryByPlaceholderText("Find a node…")).toBeNull();
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    expect(screen.getByPlaceholderText("Find a node…")).toBeTruthy();
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    expect(screen.queryByPlaceholderText("Find a node…")).toBeNull();
  });
});
