// @vitest-environment jsdom
// ParamBlock's batch-alias expander: a `${item.x}` value on a LITERAL batch
// grows a per-item toggle that reveals the resolved values inline. ParamBlock is
// a plain component (no React Flow context), so it renders directly under jsdom.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ParamBlock } from "./ReadPanel";
import type { BatchSpec, RFParam } from "../types";

// Keep CodeBlock SYNCHRONOUS (highlight → null = legacy plain-text paint), so the
// resolved values are assertable as plain text without an async settle.
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});

afterEach(cleanup);

const param = (over: Partial<RFParam> = {}): RFParam => ({
  name: "prompt",
  value: "${item.prompt}",
  is_dynamic: true,
  source: null,
  ...over,
});

const literalBatch = (over: Partial<BatchSpec> = {}): BatchSpec => ({
  parallel: true,
  dynamic: false,
  as_name: "item",
  source_ref: null,
  count: 2,
  items: [
    { focus: "emotional", prompt: "EMOTIONAL prompt body" },
    { focus: "details", prompt: "DETAILS prompt body" },
  ],
  ...over,
});

describe("ParamBlock — batch-alias expansion", () => {
  it("expands ${item.prompt} into each item's resolved value on click", () => {
    render(<ParamBlock param={param()} kind="llm" batch={literalBatch()} />);
    const toggle = screen.getByRole("button", { name: /2 items/ });
    // collapsed
    expect(screen.queryByText("focus: emotional")).toBeNull();
    expect(screen.queryByText("EMOTIONAL prompt body")).toBeNull();
    // expanded: each item's discriminating-field header + resolved content
    fireEvent.click(toggle);
    expect(screen.getByText("focus: emotional")).toBeTruthy();
    expect(screen.getByText("EMOTIONAL prompt body")).toBeTruthy();
    expect(screen.getByText("focus: details")).toBeTruthy();
    expect(screen.getByText("DETAILS prompt body")).toBeTruthy();
  });

  it("shows no expander when the value does not read the batch alias", () => {
    render(<ParamBlock param={param({ name: "timeout", value: "300", is_dynamic: false })} kind="llm" batch={literalBatch()} />);
    expect(screen.queryByRole("button", { name: /items/ })).toBeNull();
  });

  it("the param's file:line is a LINK carrying the PARAM's own ref when onOpenSource is wired; plain text otherwise", () => {
    const onOpenSource = vi.fn();
    const src = { file: "demo.pflow.md", line: 25 };
    render(<ParamBlock param={param({ name: "command", value: "ls", source: src })} kind="shell" onOpenSource={onOpenSource} />);
    const link = screen.getByText("demo.pflow.md:25");
    expect(link.tagName).toBe("BUTTON");
    fireEvent.click(link);
    expect(onOpenSource).toHaveBeenCalledWith(src);
    cleanup();
    render(<ParamBlock param={param({ name: "command", value: "ls", source: src })} kind="shell" />);
    expect(screen.getByText("demo.pflow.md:25").tagName).toBe("SPAN");
  });

  it("the param value carries the ⛶ expand titled by the PARAM's name (every value box has it)", () => {
    render(<ParamBlock param={param({ name: "code", value: "x = 1" })} kind="code" />);
    fireEvent.click(screen.getByLabelText("Expand code"));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("x = 1");
    expect(screen.getByText("code", { selector: ".value-modal-title" })).toBeTruthy();
  });

  it("shows no expander for a dynamic batch (no literal items to resolve)", () => {
    render(<ParamBlock param={param()} kind="llm" batch={literalBatch({ dynamic: true, items: null })} />);
    expect(screen.queryByRole("button", { name: /items/ })).toBeNull();
  });

  it("shows no expander when no batch is passed (the EdgePanel path)", () => {
    render(<ParamBlock param={param()} kind="llm" />);
    expect(screen.queryByRole("button", { name: /items/ })).toBeNull();
  });
});
