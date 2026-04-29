"""Task 159 Spike 1: Gemini explicit cache_control verification.

Two scenarios:
- A: Verify emitting cache_control to Gemini via LiteLLM actually fires
     `cachedContents` (cache_creation_input_tokens > 0 on call 1, then
     cache_read_input_tokens > 0 on call 2). Distinguish from Gemini's
     IMPLICIT auto-cache (which fires regardless of markers).
- B: Verify Gemini accepts BOTH a system-cache marker AND a user-message-prefix
     marker in the same request without API error.

Model: gemini/gemini-2.5-flash (cheapest, lowest threshold per DD#32).
Prefix needs >= 4096 tokens to reliably exceed explicit-cache minimum.
"""
import json
import os
import time

from pflow.core.settings import SettingsManager

# Inject API keys per progress-log §30 pattern.
for k, v in (SettingsManager().load().env or {}).items():
    if v and k not in os.environ:
        os.environ[k] = v

import litellm  # noqa: E402  (lazy after env is set)


def make_filler(target_tokens: int) -> str:
    """Build a deterministic Lorem-Ipsum-style filler of approximately
    `target_tokens` tokens. Approximation: ~4 chars/token for English prose."""
    paragraph = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
        "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
        "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
        "commodo consequat. Duis aute irure dolor in reprehenderit in voluptate "
        "velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat "
        "cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id "
        "est laborum. Sed ut perspiciatis unde omnis iste natus error sit voluptatem "
        "accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab "
        "illo inventore veritatis et quasi architecto beatae vitae dicta sunt "
        "explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit "
        "aut fugit, sed quia consequuntur magni dolores eos qui ratione voluptatem "
        "sequi nesciunt. Neque porro quisquam est, qui dolorem ipsum quia dolor sit "
        "amet, consectetur, adipisci velit, sed quia non numquam eius modi tempora "
        "incidunt ut labore et dolore magnam aliquam quaerat voluptatem.\n\n"
    )
    # Roughly 4 chars/token — pad to target.
    target_chars = target_tokens * 4
    out = ""
    while len(out) < target_chars:
        out += paragraph
    return out


SYSTEM_PREFIX = make_filler(5000)
USER_PREFIX_B = make_filler(2000)
USER_QUERY = "What is 2+2?"

print(f"SYSTEM_PREFIX char length: {len(SYSTEM_PREFIX)}")
print(f"USER_PREFIX_B char length: {len(USER_PREFIX_B)}")
print()


def dump_usage(label: str, response: object) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        print(f"{label}: (no usage)")
        return
    # Pydantic / dict — use model_dump if available, else fallback.
    if hasattr(usage, "model_dump"):
        data = usage.model_dump()
    elif hasattr(usage, "__dict__"):
        data = vars(usage)
    else:
        data = dict(usage)
    print(f"{label} usage:")
    print(json.dumps(data, indent=2, default=str))
    print()


# -----------------------------------------------------------------------------
# Scenario A: single cache_control marker on system message
# -----------------------------------------------------------------------------
print("=" * 72)
print("SCENARIO A — single system cache_control, two consecutive calls")
print("=" * 72)

messages_A = [
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": SYSTEM_PREFIX,
                "cache_control": {"type": "ephemeral", "ttl": "300s"},
            }
        ],
    },
    {"role": "user", "content": USER_QUERY},
]

print("\n>>> Call A1 (cold)")
response_A1 = litellm.completion(
    model="gemini/gemini-2.5-flash",
    messages=messages_A,
)
dump_usage("A1", response_A1)

# Small wait so the cache entry is registered before the second call.
time.sleep(2)

print(">>> Call A2 (warm, exact byte match)")
response_A2 = litellm.completion(
    model="gemini/gemini-2.5-flash",
    messages=messages_A,
)
dump_usage("A2", response_A2)


# -----------------------------------------------------------------------------
# Scenario B: TWO cache_control markers (system + user-message-prefix)
# -----------------------------------------------------------------------------
print("=" * 72)
print("SCENARIO B — multi-marker (system + user prefix)")
print("=" * 72)

messages_B = [
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": SYSTEM_PREFIX,
                "cache_control": {"type": "ephemeral", "ttl": "300s"},
            }
        ],
    },
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": USER_PREFIX_B,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": USER_QUERY},
        ],
    },
]

print("\n>>> Call B (multi-marker)")
try:
    response_B = litellm.completion(
        model="gemini/gemini-2.5-flash",
        messages=messages_B,
    )
    dump_usage("B", response_B)
    print("B: SUCCESS (no exception, no API error)")
except Exception as exc:
    print(f"B: FAILED with {type(exc).__name__}: {exc}")
