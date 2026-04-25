"""Spike 1 — cache mechanics across Anthropic, Gemini, OpenAI.

Verifies:
- Message structure that LiteLLM accepts for cache_control on system messages.
- cache_creation_input_tokens populates on first call.
- cache_read_input_tokens populates on second identical call.
- Anthropic ≥1024 token threshold.
- Gemini: single-cached-block architectural limit (confirm last marker honored).
- OpenAI: cache_control treated as no-op (auto-caching at ≥1024).
"""

from __future__ import annotations

import json
import os
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


def one_provider(label: str, model: str, system_block: str, extra_kwargs: dict | None = None) -> dict:
    """Make two identical calls; return usage stats from both.

    System block is passed as LiteLLM's content-block array with cache_control.
    """
    banner(f"{label} — {model}")

    messages = [
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
        {"role": "user", "content": "Reply with exactly the word OK and nothing else."},
    ]

    extra = extra_kwargs or {}
    first_usage = None
    second_usage = None
    # TWO calls back-to-back. Second must be bit-identical message-wise.
    try:
        t0 = time.time()
        r1 = litellm.completion(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=10,
            **extra,
        )
        t1 = time.time()
        first_usage = dump_usage("call-1", r1)
        print(f"  latency-1: {t1 - t0:.2f}s")
        print(f"  content-1 type: {type(r1.choices[0].message.content).__name__}")
        print(f"  content-1 value: {r1.choices[0].message.content!r}")
    except Exception as e:
        print(f"[{label}] call-1 FAILED: {type(e).__name__}: {e}")
        return {"error_call_1": f"{type(e).__name__}: {e}"}

    # Small pause so we're not slammed and to make the "second call" distinct.
    time.sleep(1.0)

    try:
        t0 = time.time()
        r2 = litellm.completion(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=10,
            **extra,
        )
        t1 = time.time()
        second_usage = dump_usage("call-2", r2)
        print(f"  latency-2: {t1 - t0:.2f}s")
    except Exception as e:
        print(f"[{label}] call-2 FAILED: {type(e).__name__}: {e}")
        return {"first": first_usage, "error_call_2": f"{type(e).__name__}: {e}"}

    return {"first": first_usage, "second": second_usage}


def main() -> None:
    system_block = stable_context_block()
    print(f"system block chars: {len(system_block)} (expect ~5500)")

    results: dict[str, dict] = {}

    # Anthropic Sonnet — cheapest cache-capable model; 1024 token threshold.
    results["anthropic_sonnet"] = one_provider(
        "Anthropic Sonnet 4.5",
        "anthropic/claude-sonnet-4-5",
        system_block,
    )

    # Gemini 2.5 Flash — cheapest Gemini cache-capable model.
    results["gemini_flash"] = one_provider(
        "Gemini 2.5 Flash",
        "gemini/gemini-2.5-flash",
        system_block,
    )

    # OpenAI gpt-4o-mini — automatic caching; cache_control should be no-op or translated.
    results["openai_4o_mini"] = one_provider(
        "OpenAI gpt-4o-mini",
        "openai/gpt-4o-mini",
        system_block,
    )

    banner("SPIKE 1 SUMMARY")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
