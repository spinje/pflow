// @vitest-environment jsdom
// GateCallout (Task 176): the kind-switched gate panel content. The client seam is mocked
// (RunPanel.test.tsx pattern) with the REAL ApiError, so the refusal-body contract
// (`.body.refusal` + extras) is what these tests exercise, not a fabricated shape.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  fetchGate: vi.fn(),
  resumeRun: vi.fn(),
}));

import { GateCallout } from "./GateCallout";
import { ApiError, fetchGate, resumeRun } from "../api/client";
import type { GateInfo } from "../types";

const APPROVAL: GateInfo = {
  paused_node_id: "deploy",
  gate_kind: "action_approval",
  gate_request: {
    node_id: "deploy",
    node_type: "shell",
    kind: "action_approval",
    // The preview arrives MASKED server-side — the panel renders it verbatim.
    preview: { command: "./deploy.sh --prod", api_key: "<REDACTED>" },
    question: null,
    options: [],
    recommendation: null,
  },
};

const ESCALATION: GateInfo = {
  paused_node_id: "triage",
  gate_kind: "decision_escalation",
  gate_request: {
    node_id: "triage",
    node_type: "claude-code",
    kind: "decision_escalation",
    preview: {},
    question: "Two migration paths are viable — which one?",
    // The second option has no label — the display falls back to `option 2`
    // (the falsy rule mirrored from core/gate.py::option_labels).
    options: [{ label: "Expand-contract", description: "Slower, zero downtime" }, { note: "no label here" }],
    recommendation: "Expand-contract",
  },
};

afterEach(cleanup);
beforeEach(() => {
  vi.mocked(fetchGate).mockReset();
  vi.mocked(resumeRun).mockReset().mockResolvedValue("attempt-2");
});

describe("GateCallout — approval", () => {
  it("renders the node header + masked preview rows and submits Approve / Deny as {run, approve}", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    const onPinRun = vi.fn();
    render(<GateCallout run="r1" onPinRun={onPinRun} />);

    await waitFor(() => expect(screen.getByText("Run this step?")).toBeTruthy());
    expect(screen.getByText("shell · deploy")).toBeTruthy();
    expect(screen.getByText("command")).toBeTruthy();
    expect(screen.getByText("./deploy.sh --prod")).toBeTruthy();
    expect(screen.getByText("<REDACTED>")).toBeTruthy(); // masked value shown AS masked

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1", approve: "yes" }));
    // 200 → the new attempt pins (the parent's selectRun — the single pin path).
    await waitFor(() => expect(onPinRun).toHaveBeenCalledWith("attempt-2"));
  });

  it("Deny sends approve: 'no' — a clean human no, not a failure", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Deny" }));
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1", approve: "no" }));
  });

  it("disables both buttons while the answer is in flight (double-click guard)", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    vi.mocked(resumeRun).mockReturnValue(new Promise(() => {})); // never settles
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Deny" }) as HTMLButtonElement).disabled).toBe(true);
    expect(resumeRun).toHaveBeenCalledTimes(1);
  });
});

describe("GateCallout — escalation", () => {
  it("renders the question + option buttons and submits the option's LABEL (never the number)", async () => {
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Two migration paths are viable — which one?")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Expand-contract/ }));
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1", choose: "Expand-contract" }));
  });

  it("a label-less option falls back to 'option N' — the shared numbering rule", async () => {
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /option 2/ }));
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1", choose: "option 2" }));
  });

  it("marks the recommended option instead of repeating the recommendation as text", async () => {
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("recommended")).toBeTruthy());
    expect(screen.queryByText(/^Recommended:/)).toBeNull();
  });

  it("free-text answers send the trimmed text; empty/whitespace is blocked client-side", async () => {
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    const input = (await screen.findByLabelText("Free-text answer")) as HTMLInputElement;
    const answer = screen.getByRole("button", { name: "Answer" }) as HTMLButtonElement;

    expect(answer.disabled).toBe(true); // empty → blocked
    fireEvent.change(input, { target: { value: "   " } });
    expect(answer.disabled).toBe(true); // whitespace → still blocked

    fireEvent.change(input, { target: { value: "  do both, staged  " } });
    expect(answer.disabled).toBe(false);
    fireEvent.click(answer);
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1", choose: "do both, staged" }));
  });
});

describe("GateCallout — refusal states (never silence)", () => {
  it("a superseded refusal offers the newer attempt (answered elsewhere, edge ledger #5)", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    vi.mocked(resumeRun).mockRejectedValue(
      new ApiError(409, [{ message: "already answered" }], { refusal: "superseded", newer_execution_id: "run-9" }),
    );
    const onPinRun = vi.fn();
    render(<GateCallout run="r1" onPinRun={onPinRun} />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "View newer attempt" }));
    expect(onPinRun).toHaveBeenCalledWith("run-9");
  });

  it("a stale-workflow refusal asks for an ack, then retries the SAME answer with force: true", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    vi.mocked(resumeRun)
      .mockRejectedValueOnce(
        new ApiError(409, [{ message: "workflow changed" }], { refusal: "stale_workflow", hash_known: true }),
      )
      .mockResolvedValueOnce("attempt-2");
    const onPinRun = vi.fn();
    render(<GateCallout run="r1" onPinRun={onPinRun} />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByText(/workflow file changed since this run paused/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Resume anyway" }));

    await waitFor(() => expect(resumeRun).toHaveBeenLastCalledWith({ run: "r1", approve: "yes", force: true }));
    await waitFor(() => expect(onPinRun).toHaveBeenCalledWith("attempt-2"));
  });

  it("hash_known=false renders the cannot-verify wording (pre-content-hash trace, edge ledger #3)", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    vi.mocked(resumeRun).mockRejectedValue(
      new ApiError(409, [{ message: "no hash" }], { refusal: "stale_workflow", hash_known: false }),
    );
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByText(/Cannot verify the workflow is unchanged/)).toBeTruthy());
  });

  it("any other refusal renders the server's diagnostics inline (DR-6)", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    vi.mocked(resumeRun).mockRejectedValue(
      new ApiError(409, [{ message: "the paused gate needs an answer flag" }], { refusal: "answer_required" }),
    );
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/needs an answer flag/)).toBeTruthy();
    // The panel stays answerable — the buttons are back (submitting reset).
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("a gate-fetch failure renders inline errors, never a blank panel", async () => {
    vi.mocked(fetchGate).mockRejectedValue(new ApiError(404, [{ message: "run r1 is not paused" }]));
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/not paused/)).toBeTruthy();
  });
});
