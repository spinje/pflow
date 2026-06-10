// The node-icon registry. ONE place to wire a node kind (or LLM provider) to its
// SVG. Icons are vendored brand/tool art (Option B: a neutral tile in the node
// component, the icon in its NATIVE color), imported as URL strings (Vite emits
// them to static/assets and they ship in the wheel via the `artifacts` glob).
//
// Kept separate from format.ts so (a) "add a node icon" is one obvious file, and
// (b) the asset imports stay out of format.ts's wide dependency tree.

import aiLlm from "../assets/icons/ai-llm.svg";
import anthropic from "../assets/icons/anthropic.svg";
import bash from "../assets/icons/bash.svg";
import claude from "../assets/icons/claude.svg";
import gemini from "../assets/icons/gemini.svg";
import mcp from "../assets/icons/mcp.svg";
import ollama from "../assets/icons/ollama.svg";
import openai from "../assets/icons/openai.svg";
import condition from "../assets/icons/condition.svg";
import loop from "../assets/icons/loop.svg";
import placeholder from "../assets/icons/placeholder.svg";
import python from "../assets/icons/python.svg";
import subworkflow from "../assets/icons/subworkflow.svg";
import { isCondition } from "./format";
import type { RFNode } from "../types";

// condition.svg: three hollow rings joined by tapering legs, one in / two out — a
// mini node-graph of what a condition does to the flow. The in-ring is orange
// (CONDITION_COLOR), the out-rings white, and the legs blend orange → white — the
// same source→target idea as the canvas's gradient edges. Cores are transparent
// (evenodd holes), so the tile bg shows through with nothing hardcoded.

// LLM provider (the `provider/model` prefix) → brand icon. Unknown → sparkle.
const PROVIDER_ICON: Record<string, string> = { anthropic, openai, gemini, ollama };

// Node kind → icon. http/file are placeholders until real art lands; code reuses
// the python icon (user's call). llm is resolved from its model param (see iconFor).
const KIND_ICON: Record<string, string> = {
  shell: bash,
  mcp,
  python,
  code: python,
  "claude-code": claude,
  workflow: subworkflow,
  http: placeholder,
  file: placeholder,
};

/** The icon URL for a node. Role precedes kind: a decision code node presents as
 *  CONDITION (fork glyph); a LOOPED sub-workflow presents the loop glyph (its
 *  category line still says SUB-WORKFLOW, so the tile telegraphs behavior at no
 *  identity cost — leaf kinds keep their type icon, the loop U alone marks them).
 *  For `llm`, match the provider in its `model` param (`provider/model`); fall
 *  back to a sparkle for dynamic/missing/unknown models. */
export function iconFor(node: RFNode): string {
  if (isCondition(node)) return condition;
  if (node.kind === "workflow" && node.loop) return loop;
  if (node.kind === "llm") {
    const model = node.params.find((p) => p.name === "model")?.value;
    if (typeof model === "string") {
      const provider = model.split("/")[0]?.toLowerCase();
      if (provider && PROVIDER_ICON[provider]) return PROVIDER_ICON[provider];
    }
    return aiLlm;
  }
  return KIND_ICON[node.kind] ?? placeholder;
}

/** Container-card icon (collapsed group / region header): the host node's icon —
 *  so a batch-of-shell shows the shell glyph, a looped sub-workflow the loop glyph —
 *  falling back to the sub-workflow frame when the group has no host node. */
export function groupIconFor(hostNode: RFNode | null): string {
  return hostNode ? iconFor(hostNode) : subworkflow;
}
