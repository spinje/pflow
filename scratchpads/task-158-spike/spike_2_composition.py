"""Spike 2 — composition matrix on Anthropic Opus.

Tests how cache_control composes with:
  - extended thinking (thinking_budget, thinking_effort)
  - structured output (response_format with JSON schema)
  - both together

Opus 4.5 is expensive (~$15/M input, ~$75/M output), so we keep prompts
small and max_tokens modest. Expect ~$0.10 total budget for this spike.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    banner,
    dump_usage,
    inject_keys_into_env,
    silence_litellm,
    stable_context_block,
)

inject_keys_into_env()
silence_litellm()

import litellm  # noqa: E402


OPUS = "anthropic/claude-opus-4-5"
SONNET = "anthropic/claude-sonnet-4-5"


def base_messages(system_block: str, user_msg: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_block,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {"role": "user", "content": user_msg},
    ]


def scenario(label: str, model: str, system_block: str, user_msg: str, extra: dict) -> dict:
    banner(f"{label} — {model}")
    print(f"  extra kwargs: {json.dumps(extra, default=str)}")
    # Anthropic rule: temperature must be 1 when thinking is enabled.
    temperature = 1.0 if "thinking" in extra else 0.0
    try:
        t0 = time.time()
        r = litellm.completion(
            model=model,
            messages=base_messages(system_block, user_msg),
            temperature=temperature,
            max_tokens=2048,
            **extra,
        )
        dt = time.time() - t0
        u = dump_usage(label, r)
        print(f"  latency: {dt:.2f}s")
        content = r.choices[0].message.content
        print(f"  content type: {type(content).__name__}")
        if isinstance(content, str):
            print(f"  content preview: {content[:200]!r}")
        else:
            # list of blocks?
            print(f"  content (non-str): {content!r}")
        # Thinking shows up on Anthropic as .message.reasoning_content usually
        msg = r.choices[0].message
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            prev = (str(reasoning)[:200] + "...") if len(str(reasoning)) > 200 else str(reasoning)
            print(f"  reasoning_content (preview): {prev}")
        # Return for summary
        return {
            "usage": u,
            "latency_s": dt,
            "content_type": type(content).__name__,
            "has_reasoning_content": reasoning is not None,
        }
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def main() -> None:
    system_block = stable_context_block()

    # --- Scenario A: cache + extended thinking via thinking_effort ---------
    # Use Sonnet (cheaper) first — it supports extended thinking too.
    # Opus 4.5 supports thinking_effort per spec note.
    results: dict[str, dict] = {}

    # A1: cache + thinking_effort on Sonnet
    results["cache_plus_thinking_effort_sonnet"] = scenario(
        "cache + thinking_effort=low (Sonnet)",
        SONNET,
        system_block,
        "Explain the cache_control mechanism in one sentence. Respond with the single word OK after.",
        {"thinking": {"type": "enabled", "budget_tokens": 1024}},
    )

    # A2: cache + thinking_effort on Opus (verifies the plan's 'thinking_effort
    # precedence' note — per the spec, Opus 4.5 supports both thinking_effort
    # and thinking_budget and thinking_effort MUST be checked first).
    results["cache_plus_thinking_effort_opus"] = scenario(
        "cache + thinking (budget) (Opus)",
        OPUS,
        system_block,
        "Respond with exactly the word OK.",
        {"thinking": {"type": "enabled", "budget_tokens": 1024}},
    )

    # --- Scenario B: cache + structured output --------------------------------
    # LiteLLM accepts response_format with JSON schema on Anthropic (translated
    # to Anthropic's tool-use behind the scenes).
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["OK", "FAIL"]},
            "reason": {"type": "string"},
        },
        "required": ["status", "reason"],
        "additionalProperties": False,
    }

    results["cache_plus_schema_sonnet"] = scenario(
        "cache + response_format (Sonnet)",
        SONNET,
        system_block,
        "Return a JSON object with status=OK and a one-sentence reason.",
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "reply",
                    "schema": schema,
                    "strict": True,
                },
            }
        },
    )

    # --- Scenario C: cache + thinking + schema all three ---------------------
    results["cache_plus_thinking_plus_schema_opus"] = scenario(
        "cache + thinking + response_format (Opus)",
        OPUS,
        system_block,
        "Return a JSON object with status=OK and a one-sentence reason.",
        {
            "thinking": {"type": "enabled", "budget_tokens": 1024},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "reply",
                    "schema": schema,
                    "strict": True,
                },
            },
        },
    )

    banner("SPIKE 2 SUMMARY")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
