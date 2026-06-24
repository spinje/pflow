// @vitest-environment jsdom
//
// Task 173 D6: the catalog "● running" badge. A workflow with a LIVE run (matched by path) is flagged;
// others aren't; and a runs-fetch failure (DR-6) degrades to no badge without blanking the catalog.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { CatalogView } from "./CatalogView";
import type { RunInfo } from "../types";

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  fetchCatalog: vi.fn(),
  fetchRuns: vi.fn(),
}));
import { fetchCatalog, fetchRuns } from "../api/client";
const mockCatalog = vi.mocked(fetchCatalog);
const mockRuns = vi.mocked(fetchRuns);

function liveRun(path: string): RunInfo {
  return {
    run_id: "r",
    workflow_name: "x",
    workflow_path: path,
    start_time: "2026-01-01T00:00:00",
    complete: false,
    final_status: null,
    live: true,
    only_node: null,
    trace_file: "t.json",
  };
}

afterEach(() => {
  cleanup();
  mockCatalog.mockReset();
  mockRuns.mockReset();
});

describe("CatalogView running badge", () => {
  it("flags ONLY the workflow with a live run, matched by path", async () => {
    mockCatalog.mockResolvedValue([
      { name: "alpha", description: "", path: "/alpha.pflow.md" },
      { name: "beta", description: "", path: "/beta.pflow.md" },
    ]);
    mockRuns.mockResolvedValue([liveRun("/alpha.pflow.md")]); // only alpha is live
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy());
    const badges = await screen.findAllByText("running");
    expect(badges).toHaveLength(1); // exactly one workflow flagged — beta is not
  });

  it("a runs-fetch failure shows no badge but never blanks the catalog (DR-6)", async () => {
    mockCatalog.mockResolvedValue([{ name: "alpha", description: "", path: "/alpha.pflow.md" }]);
    mockRuns.mockRejectedValue(new Error("scan failed"));
    render(<CatalogView onOpen={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("alpha")).toBeTruthy()); // catalog still renders
    expect(screen.queryByText("running")).toBeNull(); // no badge, no crash
  });
});
