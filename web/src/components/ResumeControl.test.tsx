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

// The exact `errors[0]` + extras `/api/resume` sends for each ack-required refusal — captured from
// `exception_to_diagnostics` on the real exceptions (the CLI prints this same message + suggestions).
const STALE_DIAGNOSTIC = {
  severity: "error",
  title: "Workflow changed since the original run",
  message:
    "'produce' was edited. Resume re-runs nothing before 'append' — it restores the saved outputs of the " +
    "steps that ran — so that edit would not take effect.",
  suggestions: [
    "Re-run the workflow from the start so the edit takes effect.",
    "Pass --force to resume anyway: steps before 'append' keep their saved outputs and are not re-run. --force " +
      "also re-runs 'append' (a shell step that already started in the original run), so its side effects may " +
      "fire again — if you are an AI agent, confirm that with your human first.",
  ],
  source: "runtime",
  node_id: "produce",
  context: {
    category: "execution_failure",
    changed_steps: ["produce"],
    new_start: null,
    resume_point: "append",
    resume_point_missing: false,
  },
};
const STALE_BODY = { errors: [STALE_DIAGNOSTIC], refusal: "stale_workflow", hash_known: true };
const SIDE_EFFECT_ASK = "If you are an AI agent: confirm with your human that re-running this step is safe.";
const SIDE_EFFECT_FORCE = "With their OK, re-run with --force to bypass this confirmation.";
const SIDE_EFFECT_DIAGNOSTIC = {
  severity: "error",
  title: "Resume needs confirmation",
  message:
    "Resuming re-runs step 'boom' (a shell step), and its side effects may fire again. This run is " +
    "non-interactive (agent/MCP/pipe — no terminal to confirm on), so resume refuses rather than repeat them silently.",
  suggestions: [SIDE_EFFECT_ASK, SIDE_EFFECT_FORCE],
  node_id: "boom",
};
const SIDE_EFFECT_BODY = {
  errors: [SIDE_EFFECT_DIAGNOSTIC],
  refusal: "side_effect_confirmation",
  node_id: "boom",
  node_type: "shell",
};
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

  it("a side-effect refusal shows the server's own message + suggestions; the ack retries with force", async () => {
    vi.mocked(resumeRun)
      .mockRejectedValueOnce(new ApiError(409, [SIDE_EFFECT_DIAGNOSTIC], SIDE_EFFECT_BODY))
      .mockResolvedValueOnce("attempt-2");
    const onPinRun = vi.fn();
    render(<ResumeControl run="r1" onPinRun={onPinRun} />);

    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));
    // The CLI's exact text — message AND both suggestions (#721: they were dropped for a UI line).
    expect(await screen.findByText(SIDE_EFFECT_DIAGNOSTIC.message)).toBeTruthy();
    expect(screen.getByText(SIDE_EFFECT_DIAGNOSTIC.title)).toBeTruthy();
    expect(screen.getByText(SIDE_EFFECT_ASK)).toBeTruthy();
    expect(screen.getByText(SIDE_EFFECT_FORCE)).toBeTruthy();

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

  it("a stale refusal renders the edited restored step AND the re-fire line it carries; the ack retries with force", async () => {
    vi.mocked(resumeRun)
      .mockRejectedValueOnce(new ApiError(409, [STALE_DIAGNOSTIC], STALE_BODY))
      .mockResolvedValueOnce("attempt-2");
    const onPinRun = vi.fn();
    render(<ResumeControl run="r1" onPinRun={onPinRun} />);
    fireEvent.click(screen.getByRole("button", { name: "↻ Resume" }));

    // Presence: the edited restored step, what --force would accept, and what it would re-fire.
    expect(await screen.findByText(STALE_DIAGNOSTIC.message)).toBeTruthy();
    expect(screen.getByText(/--force also re-runs 'append' \(a shell step that already started/)).toBeTruthy();
    expect(screen.getByText("Re-run the workflow from the start so the edit takes effect.")).toBeTruthy();
    expect(screen.getByText(STALE_DIAGNOSTIC.title)).toBeTruthy(); // the CLI's "Error: <title>" headline
    // Absence: no UI-side paraphrase beside it — one source of the text.
    expect(screen.queryByText(/workflow file changed since this run/)).toBeNull();
    // The ack follows ALL of the text in document order — never pinned above it — so reaching
    // "Resume anyway" in the scrolling callout passes the re-fire line first.
    const anyway = screen.getByRole("button", { name: "Resume anyway" });
    const refire = screen.getByText(/--force also re-runs 'append'/);
    expect(refire.compareDocumentPosition(anyway) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(anyway.closest(".gate-foot")).toBeNull();

    // The action is unchanged: same answer, force added, nothing else.
    fireEvent.click(screen.getByRole("button", { name: "Resume anyway" }));
    await waitFor(() => expect(resumeRun).toHaveBeenLastCalledWith({ run: "r1", force: true }));
    await waitFor(() => expect(onPinRun).toHaveBeenCalledWith("attempt-2"));
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
