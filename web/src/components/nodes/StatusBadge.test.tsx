// @vitest-environment jsdom
// The corner run-status badge (Task 173): renders nothing for pending (absent status),
// and a status-classed circle carrying a glyph for each run state. The per-status COLOR
// lives in CSS (not asserted under jsdom); the class + glyph + label are the contract.

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { NodeStatus } from "../../types";
import { StatusBadge } from "./StatusBadge";

afterEach(cleanup);

describe("StatusBadge", () => {
  it("renders nothing for pending (absent status) — an idle canvas stays untouched", () => {
    const { container } = render(<StatusBadge />);
    expect(container.querySelector(".status-badge")).toBeNull();
  });

  it.each<NodeStatus>(["running", "success", "cached", "failed", "stopped"])(
    "renders the %s badge: its status class, a glyph, and a readable label",
    (status) => {
      const { container } = render(<StatusBadge status={status} />);
      const badge = container.querySelector(`.status-badge.status-${status}`);
      expect(badge).toBeTruthy();
      expect(badge?.querySelector("svg")).toBeTruthy();
      expect(badge?.getAttribute("aria-label")).toContain(status);
    },
  );
});
