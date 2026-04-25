"""Spike 5 — exception detection.

pflow's current LLM node exec_fallback at nodes/llm/llm.py:435-452 catches
`UnknownModelError` and `NeedsKeyException` by class-name string matching.
Under LiteLLM, we need the equivalents — preferably detectable via isinstance
on typed exceptions.

Scenarios:
  A. Bad/unknown model name (equivalent to UnknownModelError)
  B. Missing/wrong API key (equivalent to NeedsKeyException)
  C. Bad kwargs (like the temperature-with-thinking rule from spike 2)
  D. A timeout (needs short timeout + heavy request)
  E. What LiteLLM raises for invalid Pydantic-validated params
     (replaces the PATTERN EXCEPTION at llm.py:298-311)
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import banner, inject_keys_into_env, silence_litellm

inject_keys_into_env()
silence_litellm()

import litellm  # noqa: E402


def probe(label: str, fn, *args, **kwargs) -> dict:
    banner(label)
    try:
        fn(*args, **kwargs)
        print("  (did not raise — unexpected)")
        return {"raised": False}
    except Exception as e:
        exc_type_module = type(e).__module__
        exc_type_name = type(e).__qualname__
        mro = [f"{c.__module__}.{c.__qualname__}" for c in type(e).__mro__]
        msg = str(e)
        print(f"  TYPE: {exc_type_module}.{exc_type_name}")
        print(f"  MRO (abbrev):")
        for c in mro[:8]:
            print(f"    {c}")
        # Show a short message preview
        prev = (msg[:300] + "...") if len(msg) > 300 else msg
        print(f"  MSG: {prev!r}")
        # Inspect LiteLLM-specific attributes
        extra = {
            k: getattr(e, k, None)
            for k in ("status_code", "llm_provider", "model", "response", "param")
        }
        extra = {k: v for k, v in extra.items() if v is not None}
        if extra:
            print(f"  ATTRS: {extra}")
        return {
            "raised": True,
            "type": f"{exc_type_module}.{exc_type_name}",
            "mro": mro,
            "msg": prev,
            "attrs": {k: str(v)[:100] for k, v in extra.items()},
        }


def main() -> None:
    results: dict[str, dict] = {}

    # --- A: Unknown model name ---------------------------------------------
    results["bad_model_anthropic_like"] = probe(
        "A1. Unknown model: anthropic/claude-does-not-exist",
        lambda: litellm.completion(
            model="anthropic/claude-does-not-exist",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
        ),
    )

    results["bad_model_unknown_provider"] = probe(
        "A2. Unknown model format: no-such-provider/some-model",
        lambda: litellm.completion(
            model="no-such-provider/some-model",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
        ),
    )

    # --- B: Missing / wrong API key ---------------------------------------
    # Overwrite key with a clearly invalid one.
    bad_key_env = dict(os.environ)
    bad_key_env["ANTHROPIC_API_KEY"] = "sk-ant-invalid-spike-key-1234"
    # pass via kwargs rather than mutating process env permanently
    results["wrong_api_key_anthropic"] = probe(
        "B1. Wrong ANTHROPIC_API_KEY",
        lambda: litellm.completion(
            model="anthropic/claude-sonnet-4-5",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            api_key="sk-ant-invalid-spike-key-1234",
        ),
    )

    # Missing key entirely: use a provider whose key we remove.
    # We save + restore.
    saved_openai = os.environ.pop("OPENAI_API_KEY", None)
    try:
        results["missing_api_key_openai"] = probe(
            "B2. Missing OPENAI_API_KEY (unset env var)",
            lambda: litellm.completion(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10,
            ),
        )
    finally:
        if saved_openai:
            os.environ["OPENAI_API_KEY"] = saved_openai

    # --- C: Bad kwargs / invalid param ------------------------------------
    results["bad_param_temperature_w_thinking"] = probe(
        "C1. temperature=0 with thinking (Anthropic rule violation)",
        lambda: litellm.completion(
            model="anthropic/claude-sonnet-4-5",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=2048,
            temperature=0.0,
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
    )

    # Claim an invalid parameter name outright
    results["bad_param_unknown_kwarg"] = probe(
        "C2. Totally invalid kwarg (not a litellm parameter)",
        lambda: litellm.completion(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            completely_invalid_param_name_xyz="value",
        ),
    )

    # --- D: Timeout --------------------------------------------------------
    results["timeout_tiny"] = probe(
        "D1. timeout=0.001s (forces client-side timeout)",
        lambda: litellm.completion(
            model="anthropic/claude-sonnet-4-5",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            timeout=0.001,
        ),
    )

    # --- E: Summary table of LiteLLM exception surface --------------------
    banner("E. LiteLLM exception classes available")
    exc_classes = {
        name: getattr(litellm.exceptions, name)
        for name in dir(litellm.exceptions)
        if isinstance(getattr(litellm.exceptions, name, None), type)
        and issubclass(getattr(litellm.exceptions, name), BaseException)
    }
    for name, cls in sorted(exc_classes.items()):
        print(f"  {name}: MRO[{cls.__mro__[1].__name__}...]")
    results["_available_exceptions"] = sorted(exc_classes.keys())

    banner("SPIKE 5 SUMMARY")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
