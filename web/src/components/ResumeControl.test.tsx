// @vitest-environment jsdom
// ResumeControl (Task 176): the failed/interrupted-run Resume arm. The client seam is mocked
// with the REAL ApiError so the refusal-body contract is what's exercised. The show-when
// gating (failed banner / stopped, never paused) is GraphView's and is tested there.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  resumeRun: vi.fn(),
}));

import { ResumeControl } from "./ResumeControl";
import { ApiError, resumeRun } from "../api/client";

afterEach(cleanup);
beforeEach(() => {
  vi.mocked(resumeRun).mockReset().mockResolvedValue("attempt-2");
});

describe("ResumeControl", () => {
  it("↻ Resume POSTs {run} WITHOUT force, and success pins the new attempt", async () => {
    const onPinRun = vi.fn();
    render(<ResumeControl run="r1" onPinRun={onPinRun} />);
    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));
    // No force on the first attempt — force appears ONLY after an explicit ack.
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1" }));
    await waitFor(() => expect(onPinRun).toHaveBeenCalledWith("attempt-2"));
  });

  it("a side-effect refusal shows a dialog naming the node + its type; the ack retries with force", async () => {
    vi.mocked(resumeRun)
      .mockRejectedValueOnce(
        new ApiError(409, [{ message: "side effects may fire again" }], {
          refusal: "side_effect_confirmation",
          node_id: "send-email",
          node_type: "http",
        }),
      )
      .mockResolvedValueOnce("attempt-2");
    const onPinRun = vi.fn();
    render(<ResumeControl run="r1" onPinRun={onPinRun} />);

    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));
    // The dialog is buildable from the refusal alone: node id + registry type + the warning.
    await waitFor(() => expect(screen.getByText("send-email")).toBeTruthy());
    expect(screen.getByText(/\(http\)/)).toBeTruthy();
    expect(screen.getByText(/side effects may fire\s+again/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Resume anyway" }));
    await waitFor(() => expect(resumeRun).toHaveBeenLastCalledWith({ run: "r1", force: true }));
    await waitFor(() => expect(onPinRun).toHaveBeenCalledWith("attempt-2"));
  });

  it("Cancel backs out of the confirm without spawning anything", async () => {
    vi.mocked(resumeRun).mockRejectedValueOnce(
      new ApiError(409, [{ message: "x" }], { refusal: "side_effect_confirmation", node_id: "k", node_type: "shell" }),
    );
    render(<ResumeControl run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "↻ Resume" })).toBeTruthy(); // back to idle
    expect(resumeRun).toHaveBeenCalledTimes(1); // no second spawn
  });

  it("a stale-workflow refusal uses the same ack-then-force pattern", async () => {
    vi.mocked(resumeRun)
      .mockRejectedValueOnce(new ApiError(409, [{ message: "changed" }], { refusal: "stale_workflow", hash_known: true }))
      .mockResolvedValueOnce("attempt-2");
    render(<ResumeControl run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));
    await waitFor(() => expect(screen.getByText(/workflow file changed since this run/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Resume anyway" }));
    await waitFor(() => expect(resumeRun).toHaveBeenLastCalledWith({ run: "r1", force: true }));
  });

  it("a superseded refusal offers the newer attempt instead of a retry", async () => {
    vi.mocked(resumeRun).mockRejectedValue(
      new ApiError(409, [{ message: "already resumed" }], { refusal: "superseded", newer_execution_id: "run-9" }),
    );
    const onPinRun = vi.fn();
    render(<ResumeControl run="r1" onPinRun={onPinRun} />);
    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));
    fireEvent.click(await screen.findByRole("button", { name: "View newer attempt" }));
    expect(onPinRun).toHaveBeenCalledWith("run-9");
  });

  it("other refusals (nothing_to_resume …) render diagnostics inline with NO force affordance", async () => {
    vi.mocked(resumeRun).mockRejectedValue(
      new ApiError(409, [{ message: "nothing left to resume — the run completed" }], { refusal: "nothing_to_resume" }),
    );
    render(<ResumeControl run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/nothing left to resume/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Resume anyway" })).toBeNull();
  });

  it("inline diagnostics render the Diagnostic's suggestions — the HOW is never discarded", async () => {
    // The refusal JSON already carries the fix hint (Diagnostic.to_dict().suggestions); the
    // panel must show it (the RunForm rule — review-caught: the panels dropped it).
    vi.mocked(resumeRun).mockRejectedValue(
      new ApiError(
        409,
        [
          {
            message: "this run was stopped at a gate by a human's deliberate answer",
            suggestions: ["Re-run the workflow and answer the gate, or run it interactively."],
          },
        ],
        { refusal: "gate_stopped" },
      ),
    );
    render(<ResumeControl run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));
    expect(await screen.findByText(/stopped at a gate/)).toBeTruthy();
    expect(screen.getByText(/Re-run the workflow and answer the gate/)).toBeTruthy();
  });
});
