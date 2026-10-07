// @vitest-environment jsdom
// GateCallout (Task 176): the kind-switched gate panel content. The client seam is mocked
// (RunPanel.test.tsx pattern) with the REAL ApiError, so the refusal-body contract
// (`.body.refusal` + extras) is what these tests exercise, not a fabricated shape.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

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
    iteration: null, // a non-loop step — the wire always carries the key (core/gate.py)
  },
};

// Task 179: an approval gate raised by a LOOP step at its second iteration.
const LOOP_APPROVAL: GateInfo = {
  paused_node_id: "gated",
  gate_kind: "action_approval",
  gate_request: {
    node_id: "gated",
    node_type: "code",
    kind: "action_approval",
    preview: { iteration: 2 },
    question: null,
    options: [],
    recommendation: null,
    iteration: 2,
  },
};

const ESCALATION: GateInfo = {
  paused_node_id: "triage",
  gate_kind: "decision_escalation",
  gate_request: {
    node_id: "triage",
    node_type: "agent",
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

  it("the eyebrow names the loop iteration for a loop gate — and nothing for a non-loop gate (Task 179)", async () => {
    // A loop gate pauses at EVERY iteration (plan Q6: all pause surfaces show the position or none);
    // the browser's home for it is the eyebrow — no badge, no colour, the same muted mono line.
    vi.mocked(fetchGate).mockResolvedValue(LOOP_APPROVAL);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    expect(await screen.findByText("code · gated · iteration 2")).toBeTruthy();
    cleanup();

    // Absence pair (same medium): a non-loop gate's eyebrow ends at the node id — no trailing
    // "iteration" for the null the wire carries.
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    const eyebrow = await screen.findByText("shell · deploy");
    expect(eyebrow.textContent).toBe("shell · deploy");
    expect(screen.queryByText(/iteration/)).toBeNull();
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
  it("an option click SELECTS — only the Answer button submits, with the option's LABEL (never the number)", async () => {
    // Owner decision 2026-07-12 (after the first real mis-click): an answer consumes the gate
    // token irreversibly, so option cards select and the ONE Answer button is the deliberate
    // submit. An option click alone must never POST.
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Two migration paths are viable — which one?")).toBeTruthy());
    const option = screen.getByRole("button", { name: /Expand-contract/ });
    fireEvent.click(option);
    expect(resumeRun).not.toHaveBeenCalled(); // select, never fire
    expect(option.getAttribute("aria-pressed")).toBe("true");

    // The button label stays STATIC (owner-preferred one-row layout) — the named answer rides
    // the hover tooltip; the highlighted card is the visible confirmation.
    const answer = screen.getByRole("button", { name: "Answer" });
    expect(answer.getAttribute("title")).toBe("Answer with “Expand-contract”");
    fireEvent.click(answer);
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1", choose: "Expand-contract" }));
  });

  it("a label-less option falls back to 'option N' — the shared numbering rule", async () => {
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /option 2/ }));
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1", choose: "option 2" }));
  });

  it("selection and free text are mutually exclusive: typing clears the selection, selecting clears the text", async () => {
    // One submit at the very end — a successful submit leaves `submitting` latched (the panel
    // unmounts in production), so every interaction must precede it.
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    const option = await screen.findByRole("button", { name: /Expand-contract/ });
    const input = screen.getByLabelText("Free-text answer") as HTMLInputElement;

    // Type, then select → the text clears, the option is pressed, the tooltip names the label.
    fireEvent.change(input, { target: { value: "scratch that" } });
    fireEvent.click(option);
    expect(input.value).toBe("");
    expect(option.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Answer" }).getAttribute("title")).toBe(
      "Answer with “Expand-contract”",
    );

    // Select, then type → the selection clears and Answer submits the TEXT.
    fireEvent.change(input, { target: { value: "do both" } });
    expect(option.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    await waitFor(() => expect(resumeRun).toHaveBeenCalledWith({ run: "r1", choose: "do both" }));
  });

  it("marks the recommended option instead of repeating the recommendation as text", async () => {
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("recommended")).toBeTruthy());
    expect(screen.queryByText(/^Recommended:/)).toBeNull();
  });

  it("a non-string question/recommendation renders as text instead of crashing the viewer (#720)", async () => {
    // The shape an unresolved trace blob ref has on the wire. The server resolves these; the panel
    // must still never hand a raw object to React (that throws and blanks the whole viewer).
    const ref = { $pflow_blob: "7fabd35f2de7c0b8a20fa3fc04684300" } as unknown as string;
    vi.mocked(fetchGate).mockResolvedValue({
      ...ESCALATION,
      gate_request: { ...ESCALATION.gate_request, question: ref, recommendation: ref },
    });
    const { container } = render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    await waitFor(() => expect(container.querySelector(".gate-question")?.textContent).toContain("$pflow_blob"));
    expect(container.querySelector(".gate-recommendation")?.textContent).toContain("$pflow_blob");
    expect(screen.getByRole("button", { name: "Answer" })).toBeTruthy(); // the panel stays answerable
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

  it("a stale-workflow refusal shows the server's diagnostic, then retries the SAME answer with force: true", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    vi.mocked(resumeRun)
      .mockRejectedValueOnce(
        new ApiError(
          409,
          [
            {
              message:
                "The workflow was edited since the original run. Resume restores the saved output of 'prep' and resumes at 'gate'.",
              suggestions: ["If you changed only 'gate' or later steps, pass --force to resume."],
            },
          ],
          { refusal: "stale_workflow", hash_known: true },
        ),
      )
      .mockResolvedValueOnce("attempt-2");
    const onPinRun = vi.fn();
    render(<GateCallout run="r1" onPinRun={onPinRun} />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    // The ack panel speaks the server's words (#721), not a UI paraphrase.
    expect(await screen.findByText(/Resume restores the saved output of 'prep' and resumes at 'gate'/)).toBeTruthy();
    expect(screen.getByText(/pass --force to resume/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Resume anyway" }));

    await waitFor(() => expect(resumeRun).toHaveBeenLastCalledWith({ run: "r1", approve: "yes", force: true }));
    await waitFor(() => expect(onPinRun).toHaveBeenCalledWith("attempt-2"));
  });

  it("hash_known=false shows the server's cannot-verify diagnostic (pre-content-hash trace, edge ledger #3)", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    vi.mocked(resumeRun).mockRejectedValue(
      new ApiError(
        409,
        [{ message: "Cannot verify the workflow is unchanged — this run predates workflow-hash tracking." }],
        { refusal: "stale_workflow", hash_known: false },
      ),
    );
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/predates workflow-hash tracking/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Resume anyway" })).toBeTruthy();
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

// #714: whatever answers the gate lives in `.gate-foot`, pinned while the content above it
// scrolls. jsdom computes no layout, so this pins the two halves it CAN see — the DOM split
// (answer controls in the foot, preview/options above it) and the stylesheet's sticky rule;
// the measured "answer row inside the viewport" check is a real-browser screenshot pass.
describe("GateCallout — the answer never scrolls away (#714)", () => {
  const foot = (el: Element): Element | null => el.closest(".gate-foot");

  it("approval: Deny/Approve and their errors sit in the foot; the preview does not", async () => {
    vi.mocked(fetchGate).mockResolvedValue(APPROVAL);
    vi.mocked(resumeRun).mockRejectedValue(
      new ApiError(409, [{ message: "the paused gate needs an answer flag" }], { refusal: "answer_required" }),
    );
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    const approve = await screen.findByRole("button", { name: "Approve" });

    expect(foot(approve)).not.toBeNull();
    expect(foot(screen.getByRole("button", { name: "Deny" }))).not.toBeNull();
    expect(foot(screen.getByText("./deploy.sh --prod"))).toBeNull();

    fireEvent.click(approve);
    expect(foot(await screen.findByRole("alert"))).not.toBeNull();
  });

  it("escalation: the free-text row and Answer sit in the foot; the option cards scroll above it", async () => {
    vi.mocked(fetchGate).mockResolvedValue(ESCALATION);
    render(<GateCallout run="r1" onPinRun={vi.fn()} />);
    const option = await screen.findByRole("button", { name: /Expand-contract/ });

    expect(foot(screen.getByRole("button", { name: "Answer" }))).not.toBeNull();
    expect(foot(screen.getByLabelText("Free-text answer"))).not.toBeNull();
    expect(foot(option)).toBeNull();
  });

  // Read via fs (see cssOrder.test.ts for why not `?raw`); path-joined, because under jsdom
  // the global URL is jsdom's, which node's fileURLToPath rejects.
  const cssRule = (selector: string): string => {
    const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../index.css"), "utf8");
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const rule = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css.replace(/\/\*[\s\S]*?\*\//g, ""));
    expect(rule, `the ${selector} rule is missing from index.css`).not.toBeNull();
    return rule![1]!;
  };

  it("the stylesheet pins the foot: sticky AND a bottom inset (sticky with no inset never sticks)", () => {
    const foot = cssRule(".gate-foot");
    expect(foot).toMatch(/position:\s*sticky/);
    expect(foot).toMatch(/(?:^|[;\s])bottom:\s*-?\d/);
  });

  it("errors in the foot scroll in their own capped box, so a long diagnostic never covers the step", () => {
    const errors = cssRule(".gate-foot .gate-errors");
    expect(errors).toMatch(/max-height:\s*\d/);
    expect(errors).toMatch(/overflow-y:\s*auto/);
  });

  it("the callout header's subtitle (the gated step id) ellipsizes on one line instead of pushing the ✕ out", () => {
    const subtitle = cssRule(".node-callout-subtitle");
    expect(subtitle).toMatch(/min-width:\s*0/);
    expect(subtitle).toMatch(/overflow:\s*hidden/);
    expect(subtitle).toMatch(/text-overflow:\s*ellipsis/);
    expect(subtitle).toMatch(/white-space:\s*nowrap/);
  });
});
