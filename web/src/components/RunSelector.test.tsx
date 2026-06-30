// @vitest-environment jsdom
//
// Task 173 D6: the run selector — lists a workflow's runs and pins one (&run=) or follows newest (null).
// Verifies the run-mark mapping from RAW facts, the lazy fetch-on-open, and the select callbacks. The
// /api/client seam is mocked (no network); the rest is the real component.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { RunSelector } from "./RunSelector";
import type { RunInfo } from "../types";

vi.mock("../api/client", () => ({ fetchRuns: vi.fn() }));
import { fetchRuns } from "../api/client";
const mockFetchRuns = vi.mocked(fetchRuns);

function run(partial: Partial<RunInfo> & { run_id: string }): RunInfo {
  return {
    workflow_name: "wf",
    workflow_path: "/wf.pflow.md",
    start_time: "2026-01-01T00:00:00",
    complete: true,
    final_status: "success",
    live: false,
    only_node: null,
    trace_file: "t.json",
    git_root: null,
    ...partial,
  };
}

afterEach(() => {
  cleanup();
  mockFetchRuns.mockReset();
});

describe("RunSelector", () => {
  it("opens on click, fetches THIS workflow's runs, and marks each by its raw facts", async () => {
    mockFetchRuns.mockResolvedValue([
      run({ run_id: "r-ok" }),
      run({ run_id: "r-live", complete: false, final_status: null, live: true }),
      run({ run_id: "r-stopped", complete: false, final_status: null, live: false }),
      run({ run_id: "r-fail", final_status: "failed" }),
      run({ run_id: "r-only", only_node: "step-b" }),
    ]);
    render(<RunSelector workflow="wf" runId={null} onSelect={vi.fn()} />);

    expect(screen.queryByRole("menu")).toBeNull(); // closed → no fetch yet
    expect(mockFetchRuns).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("Runs"));
    await waitFor(() => expect(screen.getByRole("menu")).toBeTruthy());
    expect(mockFetchRuns).toHaveBeenCalledWith("wf"); // scoped to this workflow

    // Each run's label is derived from the raw facts (running / success / failed / only:<node>).
    expect(screen.getByText("success")).toBeTruthy();
    expect(screen.getByText("running")).toBeTruthy();
    expect(screen.getByText("stopped")).toBeTruthy(); // exact: not live + unfinished (flock)
    expect(screen.getByText("failed")).toBeTruthy();
    expect(screen.getByText("only: step-b")).toBeTruthy();
  });

  it("picking a run pins it (onSelect with its run_id)", async () => {
    const onSelect = vi.fn();
    mockFetchRuns.mockResolvedValue([run({ run_id: "r-ok" }), run({ run_id: "r-fail", final_status: "failed" })]);
    render(<RunSelector workflow="wf" runId={null} onSelect={onSelect} />);

    fireEvent.click(screen.getByLabelText("Runs"));
    fireEvent.click(await screen.findByText("failed"));
    expect(onSelect).toHaveBeenCalledWith("r-fail");
  });

  it("picking 'Live — follow newest' unpins (onSelect with null)", async () => {
    const onSelect = vi.fn();
    mockFetchRuns.mockResolvedValue([run({ run_id: "r-ok" })]);
    render(<RunSelector workflow="wf" runId="r-ok" onSelect={onSelect} />);

    fireEvent.click(screen.getByLabelText("Runs"));
    fireEvent.click(await screen.findByText("Live — follow newest"));
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("the trigger flags a pinned run (active), and an empty list says so", async () => {
    mockFetchRuns.mockResolvedValue([]);
    render(<RunSelector workflow="wf" runId="r-pinned" onSelect={vi.fn()} />);

    expect(screen.getByLabelText("Runs").className).toContain("active"); // pinned → active
    fireEvent.click(screen.getByLabelText("Runs"));
    expect(await screen.findByText("No runs yet for this workflow.")).toBeTruthy();
  });
});
