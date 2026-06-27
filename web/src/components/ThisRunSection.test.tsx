// @vitest-environment jsdom
//
// Task 173 — the detail panel's "This run" section. Renders ONE node's RunNodeDetail (facts + error +
// input + output) and degrades on a fetch failure (DR-6). The /api/client seam is mocked (no network);
// shiki is stubbed (CodeBlock paints its plain first-pass synchronously) so the rendered text is asserted
// directly.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { ThisRunSection } from "./ThisRunSection";
import type { RFRef, RunNodeDetail } from "../types";

vi.mock("../api/client", () => ({ fetchRunNode: vi.fn() }));
vi.mock("../utils/highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/highlight")>();
  return { ...actual, highlight: vi.fn().mockResolvedValue(null) };
});
import { fetchRunNode } from "../api/client";
const mockFetch = vi.mocked(fetchRunNode);

const REF: RFRef = { node_id: "greet", ancestor_path: [], port: null };

function detail(partial: Partial<RunNodeDetail> = {}): RunNodeDetail {
  return {
    node_type: "shell",
    status: "success",
    duration_ms: 1234,
    cost_usd: null,
    tokens: null,
    error: null,
    input: { command: "echo hi" },
    output: { stdout: "hi" },
    ...partial,
  };
}

afterEach(() => {
  cleanup();
  mockFetch.mockReset();
});

describe("ThisRunSection", () => {
  it("renders the status header (status over the value + duration), input fields, and output", async () => {
    mockFetch.mockResolvedValue(detail());
    render(<ThisRunSection workflow="/wf" runId={null} nodeRef={REF} />);
    await waitFor(() => expect(screen.getByText("Input")).toBeTruthy());
    expect(screen.getByText("status")).toBeTruthy(); // the grey eyebrow
    expect(screen.getByText("success")).toBeTruthy(); // the status value (the header "name")
    expect(screen.getByText("1.2s")).toBeTruthy(); // fmtDuration(1234) in the subtitle (single-sourced with the chip)
    expect(screen.queryByText("type")).toBeNull(); // type dropped — it's already the panel's top header
    expect(screen.getByText("command")).toBeTruthy(); // input field
    expect(screen.getByText("Output")).toBeTruthy();
    expect(screen.getByText("stdout")).toBeTruthy(); // output field
  });

  it("folds cost into the subtitle next to the duration, shows a tokens line, string output as headline", async () => {
    mockFetch.mockResolvedValue(
      detail({
        node_type: "llm",
        cost_usd: 0.0034,
        tokens: { input: 1000, output: 200, cache_read: 800 },
        output: "the answer",
      }),
    );
    render(<ThisRunSection workflow="/wf" runId="r1" nodeRef={REF} />);
    await waitFor(() => expect(screen.getByText("Output")).toBeTruthy());
    expect(screen.getByText(/1\.2s.+\$0\.0034/)).toBeTruthy(); // duration · cost in ONE subtitle node
    expect(screen.getByText(/1[,.]000 in \/ 200 out/)).toBeTruthy(); // tokens line (locale-tolerant)
    expect(screen.getByText("the answer")).toBeTruthy(); // string output
  });

  it("omits cost from the subtitle when the node paid nothing (cached → 0)", async () => {
    mockFetch.mockResolvedValue(detail({ status: "cached", cost_usd: 0 }));
    render(<ThisRunSection workflow="/wf" runId={null} nodeRef={REF} />);
    await waitFor(() => expect(screen.getByText("cached")).toBeTruthy());
    expect(screen.getByText("1.2s")).toBeTruthy(); // subtitle is JUST the duration
    expect(screen.queryByText(/\$/)).toBeNull(); // no cost folded in
  });

  it("renders the error block for a failed node and omits a null output", async () => {
    mockFetch.mockResolvedValue(detail({ status: "failed", error: "boom: exit 1", output: null }));
    render(<ThisRunSection workflow="/wf" runId={null} nodeRef={REF} />);
    await waitFor(() => expect(screen.getByText("Error")).toBeTruthy());
    expect(screen.getByText("failed")).toBeTruthy(); // status value
    expect(screen.getByText("boom: exit 1")).toBeTruthy();
    expect(screen.queryByText("Output")).toBeNull();
  });

  it("degrades to a 'couldn't load' message on a fetch failure, never blanking the panel (DR-6)", async () => {
    mockFetch.mockRejectedValue(new Error("network"));
    render(<ThisRunSection workflow="/wf" runId={null} nodeRef={REF} />);
    expect(await screen.findByText("Couldn't load run detail.")).toBeTruthy();
  });
});
