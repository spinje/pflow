"""Shared helpers for task-158 Phase 0 spike scripts.

Run each spike with:
    uv run --with litellm==1.83.7 python scratchpads/task-158-spike/spike_<n>_*.py

Or the full suite via run_spikes.sh.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def load_keys_from_llm_cli() -> dict[str, str]:
    """Pull keys from Simon Willison's llm CLI into a dict.

    Mirrors what env vars LiteLLM reads natively.
    """
    mapping = {
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    out: dict[str, str] = {}
    for llm_name, env_name in mapping.items():
        try:
            result = subprocess.run(
                ["uv", "run", "llm", "keys", "get", llm_name],
                capture_output=True,
                text=True,
                check=True,
                cwd=str(Path(__file__).parent.parent.parent),
            )
            out[env_name] = result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Could not load {llm_name} key: {e.stderr.strip()}", file=sys.stderr)
    return out


def inject_keys_into_env() -> None:
    """Inject all three keys into os.environ. Idempotent."""
    for name, value in load_keys_from_llm_cli().items():
        if value and name not in os.environ:
            os.environ[name] = value


def silence_litellm() -> None:
    """Suppress LiteLLM's default chatter so spike output stays readable.

    We test all the documented knobs here — the spike records which ones work.
    """
    import litellm
    import logging

    # The documented knobs (varies across versions)
    litellm.suppress_debug_info = True
    litellm.set_verbose = False
    # Undocumented internal flag used in some versions:
    if hasattr(litellm, "_turn_on_debug"):
        try:
            litellm._turn_on_debug = False  # type: ignore[assignment]
        except Exception:
            pass
    # Lower all litellm loggers to WARNING
    for name in list(logging.Logger.manager.loggerDict):
        if name.startswith("LiteLLM") or name.startswith("litellm"):
            logging.getLogger(name).setLevel(logging.WARNING)


def stable_context_block(target_tokens: int = 1500) -> str:
    """Generate a deterministic text block big enough to trigger Anthropic caching.

    Anthropic's cache threshold is 1024 tokens for Sonnet/Opus, 2048 for Haiku.
    This returns ~1500 tokens of repeating stable prose to land safely above
    Sonnet's threshold. The bytes are bit-identical across calls, which is what
    prefix caching requires.
    """
    # Roughly 1 token ~ 3.5 chars for English prose; target ~6000 chars for 1500 tokens.
    paragraph = (
        "The pflow workflow engine orchestrates multi-step LLM pipelines declared "
        "in a custom markdown format. Each workflow file defines a directed graph of "
        "nodes — shell, python, http, llm, mcp, file — that communicate through a "
        "shared store. Nodes are atomic and focused on business logic; the engine "
        "handles retries, branching, batch fan-out, nested sub-workflows, and "
        "observability through a structured trace file written after every run. "
        "The LLM node is currently built on Simon Willison's llm library, which "
        "unifies Anthropic, Gemini, and OpenAI under a small plugin interface. "
        "Task 158 replaces that foundation with LiteLLM to unlock provider-level "
        "prompt caching — a feature the llm-anthropic plugin does not expose. "
        "Prompt caching is prefix-based: Anthropic caches the longest shared "
        "prefix and charges 1.25x or 2x on writes versus 0.1x on reads. Gemini's "
        "cachedContents API trades a 90% read discount for an hourly storage cost. "
        "OpenAI caches automatically at and above 1024 tokens with no markers "
        "required. The design goal is that pflow never modifies the text the LLM "
        "sees — cache blocks only add content-block structure and cache_control "
        "metadata without rewriting bytes. This spike verifies that LiteLLM "
        "passes cache_control cleanly across all three providers and that the "
        "usage response populates cache_creation_input_tokens and "
        "cache_read_input_tokens fields predictably. "
    )
    # Concatenate until well above target.
    # Each paragraph is ~380 words, ~500 tokens. 3x should land near 1500 tokens.
    block = (paragraph + "\n\n") * 4
    return block


def dump_usage(label: str, response) -> dict:
    """Extract a readable usage dict from a LiteLLM ModelResponse."""
    usage = response.usage
    out = {}
    for field in [
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ]:
        out[field] = getattr(usage, field, None)
    # OpenAI nests cached count under prompt_tokens_details
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        out["prompt_tokens_details.cached_tokens"] = getattr(details, "cached_tokens", None)
    # LiteLLM's cost annotation (if it computed it)
    hidden = getattr(response, "_hidden_params", {}) or {}
    if isinstance(hidden, dict) and "response_cost" in hidden:
        out["response_cost_litellm"] = hidden["response_cost"]
    print(f"[USAGE {label}]", json.dumps(out, indent=2, default=str))
    return out


def banner(msg: str) -> None:
    print("\n" + "=" * 72)
    print(msg)
    print("=" * 72)


if __name__ == "__main__":
    # smoke test: load keys, print which ones landed
    keys = load_keys_from_llm_cli()
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        status = "SET" if keys.get(name) else "MISSING"
        print(f"{name}: {status}")
    block = stable_context_block()
    print(f"context block chars: {len(block)}")
