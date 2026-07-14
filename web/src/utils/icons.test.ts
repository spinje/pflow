import { describe, expect, it } from "vitest";

import aiLlm from "../assets/icons/ai-llm.svg";
import claude from "../assets/icons/claude.svg";
import codexDark from "../assets/icons/codex-dark.svg";
import type { RFNode } from "../types";
import { iconFor } from "./icons";

function agentNode(backend?: unknown): RFNode {
  return {
    kind: "agent",
    is_decision: false,
    is_transform: false,
    params: backend === undefined ? [] : [{ name: "backend", value: backend, is_dynamic: false, source: null }],
  } as RFNode;
}

describe("agent icon", () => {
  it("uses the active backend's product identity", () => {
    expect(iconFor(agentNode("claude"))).toBe(claude);
    expect(iconFor(agentNode("codex"))).toBe(codexDark);
  });

  it("falls back to the neutral identity when the backend is unavailable", () => {
    expect(iconFor(agentNode())).toBe(aiLlm);
    expect(iconFor(agentNode("${inputs.backend}"))).toBe(aiLlm);
    expect(iconFor(agentNode("future-backend"))).toBe(aiLlm);
  });
});
