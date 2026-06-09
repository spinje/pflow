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
import markdown from "../assets/icons/markdown.svg";
import mcp from "../assets/icons/mcp.svg";
import ollama from "../assets/icons/ollama.svg";
import openai from "../assets/icons/openai.svg";
import placeholder from "../assets/icons/placeholder.svg";
import python from "../assets/icons/python.svg";
import type { RFNode } from "../types";

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
  workflow: markdown,
  http: placeholder,
  file: placeholder,
};

/** The icon URL for a node. For `llm`, match the provider in its `model` param
 *  (`provider/model`); fall back to a sparkle for dynamic/missing/unknown models. */
export function iconFor(node: RFNode): string {
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
