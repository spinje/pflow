"""Spike — capture exact BadRequestError text from Anthropic when a caller
sets temperature=0.0 with thinking enabled.

Question being investigated (Task 158 Phase A code review, item 9):
  Does pflow need to pre-validate the temperature+thinking constraint, or
  is LiteLLM's pass-through error already actionable enough on its own?

Models tested:
  - anthropic/claude-opus-4-5
  - anthropic/claude-sonnet-4-5
  - anthropic/claude-sonnet-4-6
  - anthropic/claude-haiku-4-5

For each model, we:
  1. Call with temperature=0.0 + thinking enabled → expect BadRequestError
     (the failure case the user would hit)
  2. Capture the exception type, status_code, llm_provider, and message
  3. Print verbatim so we can judge agent-actionability of the raw error

Cost: ~$0 — failed requests don't consume tokens.
"""

from __future__ import annotations

import os
import sys

import litellm
import litellm.exceptions

litellm.suppress_debug_info = True

# Load env vars from pflow settings if not already set
if not os.environ.get("ANTHROPIC_API_KEY"):
    try:
        from pflow.core.settings import SettingsManager

        env = SettingsManager().list_env(mask_values=False)
        for k, v in env.items():
            if k not in os.environ and v and v.strip():
                os.environ[k] = v
    except Exception as e:
        print(f"Could not load pflow settings: {e}", file=sys.stderr)

if not os.environ.get("ANTHROPIC_API_KEY"):
    print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
    sys.exit(1)


MODELS = [
    "anthropic/claude-opus-4-5",
    "anthropic/claude-sonnet-4-5",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-haiku-4-5",
]


def try_call(model: str, temperature: float, thinking_enabled: bool) -> None:
    """Try one call; print outcome (success or error)."""
    print(f"\n{'=' * 78}")
    print(f"MODEL:       {model}")
    print(f"TEMPERATURE: {temperature}")
    print(f"THINKING:    {'enabled (budget=2048)' if thinking_enabled else 'disabled'}")
    print("-" * 78)

    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word OK."}],
        "temperature": temperature,
        "max_tokens": 4096,  # must be > thinking budget
        "stream": False,
    }
    if thinking_enabled:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": 2048}

    try:
        response = litellm.completion(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        print(f"OK — text={text!r}")
    except litellm.exceptions.BadRequestError as e:
        print(f"BadRequestError")
        print(f"  status_code:  {getattr(e, 'status_code', '?')}")
        print(f"  llm_provider: {getattr(e, 'llm_provider', '?')}")
        print(f"  model:        {getattr(e, 'model', '?')}")
        print(f"  message:")
        for line in str(e).splitlines():
            print(f"    {line}")
    except Exception as e:
        print(f"OTHER EXCEPTION: {type(e).__name__}")
        print(f"  message: {e}")


def main() -> None:
    print("Spike 6 — Anthropic temperature+thinking BadRequestError messages\n")
    print("Goal: judge whether LiteLLM's pass-through error is actionable enough")
    print("for an agent to fix without pflow-side pre-validation.")

    for model in MODELS:
        # The failure case
        try_call(model, temperature=0.0, thinking_enabled=True)

    print(f"\n{'=' * 78}")
    print("Spike complete. Review the message text above.")


if __name__ == "__main__":
    main()
