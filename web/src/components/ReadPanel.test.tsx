// @vitest-environment jsdom
// ReadPanel — the source-link affordance: the node's file:line opens the source
// pane (and scrolls it to that line). Rendered without graph/onNavigate so the
// ConnectionSections (which need the Interaction context) stay out of the way —
// this suite pins only the source link.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ReadPanel } from "./ReadPanel";
import type { RFNode } from "../types";

afterEach(cleanup);

function node(overrides: Partial<RFNode> = {}): RFNode {
  return {
    id: "n1",
    ref: { node_id: "session_context", ancestor_path: [], port: null },
    kind: "shell",
    purpose: "",
    params: [],
    io: null,
    loop: null,
    batch: null,
    parent: null,
    source: { file: "/w/prompt-caching-multi-chunk.pflow.md", line: 77 },
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

describe("ReadPanel — source link", () => {
  it("renders file:line as a button that opens the source pane on click", () => {
    const onOpenSource = vi.fn();
    render(<ReadPanel node={node()} onOpenSource={onOpenSource} onClose={() => {}} />);
    const link = screen.getByText("prompt-caching-multi-chunk.pflow.md:77");
    expect(link.tagName).toBe("BUTTON");
    link.click();
    expect(onOpenSource).toHaveBeenCalledTimes(1);
  });

  it("renders the source line as plain text when onOpenSource is absent", () => {
    render(<ReadPanel node={node()} onClose={() => {}} />);
    expect(screen.getByText("prompt-caching-multi-chunk.pflow.md:77").tagName).toBe("P");
  });
});
