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
  it("polls THIS workflow's runs and, on open, marks each by its raw facts", async () => {
    mockFetchRuns.mockResolvedValue([
      run({ run_id: "r-ok" }),
      run({ run_id: "r-live", complete: false, final_status: null, live: true }),
      run({ run_id: "r-stopped", complete: false, final_status: null, live: false }),
      run({ run_id: "r-fail", final_status: "failed" }),
      run({ run_id: "r-only", only_node: "step-b" }),
    ]);
    render(<RunSelector workflow="wf" runId={null} onSelect={vi.fn()} />);

    // Polls on mount (Task 175 — the live-clock signal), scoped to THIS workflow; the menu is still closed.
    await waitFor(() => expect(mockFetchRuns).toHaveBeenCalledWith("wf"));
    expect(screen.queryByRole("menu")).toBeNull();

    fireEvent.click(screen.getByLabelText(/^Runs/)); // "Runs" or "Runs (a run is live)" once the live run lands
    await waitFor(() => expect(screen.getByRole("menu")).toBeTruthy());

    // Each run's label is derived from the raw facts (running / success / failed / only:<node>).
    expect(screen.getByText("success")).toBeTruthy();
    expect(screen.getByText("running")).toBeTruthy();
    expect(screen.getByText("stopped")).toBeTruthy(); // exact: not live + unfinished (flock)
    expect(screen.getByText("failed")).toBeTruthy();
    expect(screen.getByText("only: step-b")).toBeTruthy();
  });

  it("pulses the clock blue while a run is live, and not when none is", async () => {
    mockFetchRuns.mockResolvedValue([run({ run_id: "r-live", complete: false, final_status: null, live: true })]);
    render(<RunSelector workflow="wf" runId={null} onSelect={vi.fn()} />);
    // Once the poll lands a live run, the clock gains the pulse class + an "a run is live" label.
    await waitFor(() => expect(screen.getByLabelText(/a run is live/).className).toContain("run-live-pulse"));

    cleanup();
    mockFetchRuns.mockReset();
    mockFetchRuns.mockResolvedValue([run({ run_id: "r-done" })]); // none live
    render(<RunSelector workflow="wf" runId={null} onSelect={vi.fn()} />);
    await waitFor(() => expect(mockFetchRuns).toHaveBeenCalled());
    expect(screen.getByLabelText("Runs").className).not.toContain("run-live-pulse");
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
