// @vitest-environment jsdom
// RunProgress render tests (Task 175): the miniature canvas-spine inside the run callout — kind-colored
// tiles + gradient connectors, grey while pending, plus per-node meta + the run outcome.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RunProgress } from "./RunProgress";
import type { ProgressStep } from "../graph/flow";

afterEach(cleanup);

const step = (name: string, over: Partial<ProgressStep> = {}): ProgressStep => ({
  id: `n_${name}`,
  name,
  kind: "shell",
  isDecision: false,
  isTransform: false,
  batchCount: null,
  status: "pending",
  durationMs: null,
  ...over,
});

describe("RunProgress", () => {
  it("renders one spine tile per step with the status class + duration/status meta", () => {
    render(
      <RunProgress
        steps={[
          step("fetch", { status: "success", durationMs: 400 }),
          step("transform", { status: "running" }),
          step("validate", { status: "pending" }),
        ]}
        banner={null}
      />,
    );
    const rows = document.querySelectorAll(".run-spine-step");
    expect(rows.length).toBe(3);
    expect(document.querySelectorAll(".run-spine-tile").length).toBe(3);
    expect(rows[0]!.className).toContain("status-success");
    expect(rows[1]!.className).toContain("status-running");
    // a timed terminal step shows its duration; running/pending show the status word.
    expect(screen.getByText("400ms")).toBeTruthy();
    expect(screen.getByText("running")).toBeTruthy();
    expect(screen.getByText("pending")).toBeTruthy();
  });

  it("colors a pending tile muted grey and an active tile its node identity color (grey → color IS the progress)", () => {
    render(<RunProgress steps={[step("done", { status: "success" }), step("waiting", { status: "pending" })]} banner={null} />);
    const [activeTile, pendingTile] = document.querySelectorAll(".run-spine-tile");
    // jsdom normalizes the inline color to rgb(): the pending grey #5b616b → rgb(91, 97, 107).
    expect(pendingTile!.getAttribute("style")).toContain("rgb(91, 97, 107)"); // the pending grey
    expect(activeTile!.getAttribute("style")).not.toContain("rgb(91, 97, 107)"); // colored, not grey
  });

  it("renders the pulsing inner core ONLY for a running step (tiles are hollow otherwise)", () => {
    render(
      <RunProgress steps={[step("a", { status: "running" }), step("b", { status: "success" }), step("c")]} banner={null} />,
    );
    // The running tile blinks its INSIDE (a full-color core); non-running tiles stay hollow (no core).
    const cores = document.querySelectorAll(".run-spine-tile-core");
    expect(cores.length).toBe(1);
    const runningStep = document.querySelector(".run-spine-step.status-running");
    expect(runningStep!.querySelector(".run-spine-tile-core")).toBeTruthy();
  });

  it("makes each step name a button that calls onSelectStep with the step's flat id (scroll-to + select)", () => {
    const onSelectStep = vi.fn();
    render(<RunProgress steps={[step("fetch"), step("report")]} banner={null} onSelectStep={onSelectStep} />);
    fireEvent.click(screen.getByRole("button", { name: /fetch/i }));
    expect(onSelectStep).toHaveBeenCalledWith("n_fetch"); // step.id, the flat node id onNavigate takes
  });

  it("renders plain (no button) when onSelectStep is absent", () => {
    render(<RunProgress steps={[step("fetch")]} banner={null} />);
    expect(screen.queryByRole("button", { name: /fetch/i })).toBeNull();
  });

  it("appends ×N for a batched step (the static batch count from the contract)", () => {
    render(<RunProgress steps={[step("proc", { batchCount: 10, status: "running" })]} banner={null} />);
    expect(screen.getByText("×10")).toBeTruthy();
  });

  it("shows 'Running…' before completion and the run outcome (+ counts) once the banner arrives", () => {
    const { rerender } = render(<RunProgress steps={[step("a", { status: "running" })]} banner={null} />);
    expect(screen.getByText("Running…")).toBeTruthy();
    rerender(
      <RunProgress steps={[step("a", { status: "success" })]} banner={{ final_status: "success", nodes_executed: 4 }} />,
    );
    // The outcome text is the left span; the status class lives on the row.
    const outcome = screen.getByText(/Run success · 4 nodes/).closest(".run-progress-outcome");
    expect(outcome?.className).toContain("run-success");
  });

  it("shows the total run wall-clock bottom-right (from the banner's duration_ms)", () => {
    render(
      <RunProgress
        steps={[step("a", { status: "success", durationMs: 100 })]}
        banner={{ final_status: "success", nodes_executed: 4, duration_ms: 1843 }}
      />,
    );
    expect(screen.getByText("1.8s")).toBeTruthy(); // fmtDuration(1843); distinct from the step's 100ms
  });

  it("surfaces failures in the outcome line", () => {
    render(
      <RunProgress
        steps={[step("a", { status: "failed" })]}
        banner={{ final_status: "failed", nodes_executed: 2, nodes_failed: 1 }}
      />,
    );
    expect(screen.getByText(/Run failed · 2 nodes · 1 failed/)).toBeTruthy();
  });

  it("stamps the overall-run-status badge (the node round badge) at the outcome line, by run outcome", () => {
    // running (no banner) → the spinner badge; success → ✓; failed → !; degraded → amber stopped (no
    // NodeStatus for degraded — the closest badge; the outcome TEXT carries the exact word).
    const badge = (): Element | null => document.querySelector(".run-progress-outcome .status-badge");
    const { rerender } = render(<RunProgress steps={[step("a", { status: "running" })]} banner={null} />);
    expect(badge()?.className).toContain("status-running");
    rerender(<RunProgress steps={[step("a", { status: "success" })]} banner={{ final_status: "success", nodes_executed: 1 }} />);
    expect(badge()?.className).toContain("status-success");
    rerender(<RunProgress steps={[step("a", { status: "failed" })]} banner={{ final_status: "failed", nodes_executed: 1, nodes_failed: 1 }} />);
    expect(badge()?.className).toContain("status-failed");
    rerender(<RunProgress steps={[step("a", { status: "success" })]} banner={{ final_status: "degraded", nodes_executed: 1 }} />);
    expect(badge()?.className).toContain("status-stopped");
  });
});
