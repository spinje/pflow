// @vitest-environment jsdom
// The corner run-status badge (Task 173): renders nothing for pending (absent status),
// and a status-classed circle carrying a glyph for each run state. The per-status COLOR
// lives in CSS (not asserted under jsdom); the class + glyph + label are the contract.

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { NodeStatus } from "../../types";
import { StatusBadge, runStatusLabel } from "./StatusBadge";

afterEach(cleanup);

describe("runStatusLabel — the badge's friendly hover text", () => {
  it("success/failed get a friendly verb + duration (+ cost when > 0)", () => {
    expect(runStatusLabel("success", { durationMs: 1234, costUsd: 0.0034 })).toBe("Succeeded · 1.2s · $0.0034");
    expect(runStatusLabel("success", { durationMs: 42 })).toBe("Succeeded · 42ms"); // sub-second → ms
    expect(runStatusLabel("failed", { durationMs: 900, costUsd: 0 })).toBe("Failed · 900ms"); // zero cost omitted
  });

  it("the special states explain themselves (no metrics to show)", () => {
    expect(runStatusLabel("running")).toBe("Running…");
    expect(runStatusLabel("cached")).toContain("reused a prior result");
    expect(runStatusLabel("stopped")).toContain("exited before");
    expect(runStatusLabel("unrecorded")).toContain("different version"); // the new badge's "why"
  });
});

describe("StatusBadge", () => {
  it("renders nothing for pending (absent status) — an idle canvas stays untouched", () => {
    const { container } = render(<StatusBadge />);
    expect(container.querySelector(".status-badge")).toBeNull();
  });

  it.each<NodeStatus>(["running", "success", "cached", "failed", "stopped", "unrecorded"])(
    "renders the %s badge: its status class, a glyph, and a readable label",
    (status) => {
      const { container } = render(<StatusBadge status={status} />);
      const badge = container.querySelector(`.status-badge.status-${status}`);
      expect(badge).toBeTruthy();
      expect(badge?.querySelector("svg")).toBeTruthy();
      expect(badge?.getAttribute("aria-label")).toContain(status);
    },
  );

  it("carries the friendly label in a custom hover chip, not the native title", () => {
    const { container } = render(<StatusBadge status="success" detail={{ durationMs: 1234 }} />);
    const badge = container.querySelector(".status-badge");
    // The native `title` is replaced by the styled chip (so it renders in the chrome palette).
    expect(badge?.getAttribute("title")).toBeNull();
    const tip = container.querySelector(".status-badge-tip");
    expect(tip?.textContent?.trim()).toBe("Succeeded · 1.2s");
    expect(tip?.getAttribute("aria-hidden")).toBe("true"); // the status is announced via aria-label
  });
});
