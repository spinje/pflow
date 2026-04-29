"""Task 159 Spike 3: Anthropic per-TTL pricing precision via litellm.completion_cost().

Goal: verify whether litellm.completion_cost() distinguishes 1.25x (5-min TTL)
from 2x (1-hour TTL) for cache-write events. Plan E.1 trusts LiteLLM to
distinguish; if not, a _normalize override is needed.

Anthropic per-TTL cache-write multipliers:
  - 5-min TTL: 1.25x base input rate
  - 1-hour TTL: 2.00x base input rate

Expected cost ratio (1h / 5m): ~1.4-1.7 — depends on prefix-to-full-token ratio.
Reads and non-cached portions wash to ~1; only the write portion differs.
"""
import json
import os

from pflow.core.settings import SettingsManager

for k, v in (SettingsManager().load().env or {}).items():
    if v and k not in os.environ:
        os.environ[k] = v

import litellm  # noqa: E402

# Disable LiteLLM's debug retry chatter
litellm.suppress_debug_info = True


def make_filler(target_tokens: int, salt: str) -> str:
    paragraph = (
        f"[SALT={salt}] Etiam ultricies nisi vel augue. Curabitur ullamcorper "
        "ultricies nisi. Nam eget dui. Etiam rhoncus. Maecenas tempus, tellus "
        "eget condimentum rhoncus, sem quam semper libero, sit amet adipiscing "
        "sem neque sed ipsum. Nam quam nunc, blandit vel, luctus pulvinar, "
        "hendrerit id, lorem. Maecenas nec odio et ante tincidunt tempus. "
        "Donec vitae sapien ut libero venenatis faucibus. Nullam quis ante. "
        "Etiam sit amet orci eget eros faucibus tincidunt. Duis leo. Sed "
        "fringilla mauris sit amet nibh. Donec sodales sagittis magna. Sed "
        "consequat, leo eget bibendum sodales, augue velit cursus nunc.\n\n"
    )
    target_chars = target_tokens * 4
    out = ""
    while len(out) < target_chars:
        out += paragraph
    return out


def usage_dict(response: object) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "__dict__"):
        return vars(usage)
    return dict(usage)


PREFIX_5M = make_filler(2000, "task-159-spike-3-5m-2026-04-29")
# Slight variation forces fresh write (avoids hitting the 5m entry as a read).
PREFIX_1H = PREFIX_5M + " VARIANT_FOR_FRESH_WRITE_1H_TTL"
MODEL = "anthropic/claude-sonnet-4-5"

print(f"PREFIX_5M char length: {len(PREFIX_5M)}")
print(f"PREFIX_1H char length: {len(PREFIX_1H)}")
print(f"MODEL: {MODEL}")
print()


# -----------------------------------------------------------------------------
# Call 1: cache write with default 5-min TTL (omit ttl key per Anthropic docs)
# -----------------------------------------------------------------------------
print("=" * 72)
print("CALL 1 — cache write, 5-min TTL (default, no explicit ttl key)")
print("=" * 72)
r_5m = litellm.completion(
    model=MODEL,
    messages=[
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": PREFIX_5M,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {"role": "user", "content": "Respond with one word."},
    ],
)
usage_5m = usage_dict(r_5m)
print("Usage:")
print(json.dumps(usage_5m, indent=2, default=str))

cost_5m = litellm.completion_cost(completion_response=r_5m)
print(f"\ncompletion_cost (5m): ${cost_5m:.8f}")
print()


# -----------------------------------------------------------------------------
# Call 2: cache write with 1h TTL — extended cache header required
# -----------------------------------------------------------------------------
print("=" * 72)
print("CALL 2 — cache write, 1h TTL (explicit ttl='1h')")
print("=" * 72)
r_1h = litellm.completion(
    model=MODEL,
    messages=[
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": PREFIX_1H,
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                }
            ],
        },
        {"role": "user", "content": "Respond with one word."},
    ],
    extra_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"},
)
usage_1h = usage_dict(r_1h)
print("Usage:")
print(json.dumps(usage_1h, indent=2, default=str))

cost_1h = litellm.completion_cost(completion_response=r_1h)
print(f"\ncompletion_cost (1h): ${cost_1h:.8f}")
print()


# -----------------------------------------------------------------------------
# Comparison
# -----------------------------------------------------------------------------
print("=" * 72)
print("COMPARISON")
print("=" * 72)
print(f"5m cost: ${cost_5m:.8f}")
print(f"1h cost: ${cost_1h:.8f}")
if cost_5m > 0:
    ratio = cost_1h / cost_5m
    print(f"Ratio (1h / 5m): {ratio:.4f}")
    print()
    if ratio >= 1.3:
        print("VERDICT: LiteLLM distinguishes per-TTL pricing (ratio >= 1.3).")
        print("         Plan E.1 trusts LiteLLM — CONFIRMS encoded decision.")
    elif ratio <= 1.1:
        print("VERDICT: LiteLLM treats per-TTL writes as equivalent.")
        print("         Plan E.1 needs _normalize override — CONTRADICTS.")
    else:
        print(f"VERDICT: AMBIGUOUS (ratio {ratio:.4f} in dead zone 1.1-1.3).")
        print("         Surface to user before declaring outcome.")
else:
    print("VERDICT: 5m cost is zero — re-run needed.")
