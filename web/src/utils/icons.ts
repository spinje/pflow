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
import placeholder from "../assets/icons/placeholder.svg";
import python from "../assets/icons/python.svg";
import subworkflow from "../assets/icons/subworkflow.svg";
import transform from "../assets/icons/transform.svg";
import { IO_COLOR, isCondition, isTransform } from "./format";
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
 *  CONDITION (fork glyph). Behavior (loop/batch) never swaps the tile — it rides
 *  the border chip rail (ChipRail.tsx, 2026-06-10; retired the old looped-
 *  sub-workflow loop-glyph swap): identity doesn't mutate.
 *  For `llm`, match the provider in its `model` param (`provider/model`); fall
 *  back to a sparkle for dynamic/missing/unknown models. */
export function iconFor(node: RFNode): string {
  if (isCondition(node)) return condition;
  if (isTransform(node)) return transform; // shuffle glyph, cyan -> white (transform.svg)
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
 *  so a batch-of-shell shows the shell glyph — falling back to the sub-workflow
 *  frame when the group has no host node. */
export function groupIconFor(hostNode: RFNode | null): string {
  return hostNode ? iconFor(hostNode) : subworkflow;
}

// The root IO cards' glyphs: an arrow flowing INTO a wall (inputs arrive) / OUT of
// one (outputs leave), stroked in IO_COLOR. Generated data-URIs (like the condition
// icon's color, the glyph can't drift from the identity color in format.ts).
function ioGlyph(kind: "input" | "output"): string {
  const arrow =
    kind === "input"
      ? '<path d="M3 12h11M10 7l5 5-5 5"/><path d="M19 5v14"/>'
      : '<path d="M5 5v14"/><path d="M9 12h11M15 7l5 5-5 5"/>';
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ` +
    `stroke="${IO_COLOR}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${arrow}</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

const IO_ICON = { input: ioGlyph("input"), output: ioGlyph("output") } as const;

/** The root Inputs/Outputs card's tile icon. */
export function ioCardIcon(kind: "input" | "output"): string {
  return IO_ICON[kind];
}
