// @vitest-environment jsdom
// The flat batch-items block: a collapsed disclosure listing every literal item
// with all its fields (short inline, long behind a per-field size pill).

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { BatchItemsBlock } from "./BatchItems";
import type { BatchSpec } from "../types";

// Keep CodeBlock synchronous (highlight → null = legacy plain text) so an
// expanded long field is assertable without an async settle.
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});

afterEach(cleanup);

const LONG = "L".repeat(80);

const batch = (over: Partial<BatchSpec> = {}): BatchSpec => ({
  parallel: true,
  dynamic: false,
  as_name: "item",
  source_ref: null,
  count: 2,
  items: [
    { focus: "emotional", prompt: LONG },
    { focus: "details", prompt: "short" },
  ],
  ...over,
});

describe("BatchItemsBlock", () => {
  it("is collapsed by default and lists items + fields on expand", () => {
    render(<BatchItemsBlock batch={batch()} kind="llm" />);
    // collapsed: just the header
    expect(screen.queryByText("item[0]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /batch items/ }));
    // expanded: both items, the inline short field, and the long field's value hidden behind a pill
    expect(screen.getByText("item[0]")).toBeTruthy();
    expect(screen.getByText("item[1]")).toBeTruthy();
    expect(screen.getByText("emotional")).toBeTruthy(); // inline scalar
    expect(screen.getByText("short")).toBeTruthy(); // the other prompt is short → inline
    expect(screen.queryByText(LONG)).toBeNull(); // long prompt collapsed to a size pill
  });

  it("expands a long field to its full content on click", () => {
    render(<BatchItemsBlock batch={batch()} kind="llm" />);
    fireEvent.click(screen.getByRole("button", { name: /batch items/ }));
    fireEvent.click(screen.getByRole("button", { name: /80 chars/ })); // the long prompt pill
    expect(screen.getByText(LONG)).toBeTruthy();
  });

  it("renders scalar items with no field name", () => {
    render(<BatchItemsBlock batch={batch({ items: ["alpha", "beta"] })} kind="shell" />);
    fireEvent.click(screen.getByRole("button", { name: /batch items/ }));
    expect(screen.getByText("alpha")).toBeTruthy();
    expect(screen.getByText("beta")).toBeTruthy();
  });

  it("renders nothing for a dynamic batch (no static items)", () => {
    const { container } = render(<BatchItemsBlock batch={batch({ dynamic: true, items: null })} kind="llm" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for an empty item list", () => {
    const { container } = render(<BatchItemsBlock batch={batch({ items: [] })} kind="llm" />);
    expect(container.firstChild).toBeNull();
  });
});
