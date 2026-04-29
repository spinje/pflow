"""Task 159 Spike 1b: Gemini ambiguity disambiguator.

Spike 1 showed cache_read_input_tokens > 0 on the COLD A1 call, with no
cache_creation_input_tokens field in the response. That's ambiguous between:
  (a) LiteLLM creates cachedContents as a side-effect, surfaces only reads
      → markers ARE doing work (CONFIRMS encoded decision, different shape)
  (b) Gemini's implicit auto-cache fires regardless of markers
      → markers are silently no-op (CONTRADICTS encoded decision)

This disambiguator runs ONE no-marker call against a FRESH prefix and checks:
- If cache_read_input_tokens == 0 on cold call → markers were doing work (a)
- If cache_read_input_tokens > 0 on cold call → implicit cache fires regardless (b)
"""
import json
import os

from pflow.core.settings import SettingsManager

for k, v in (SettingsManager().load().env or {}).items():
    if v and k not in os.environ:
        os.environ[k] = v

import litellm  # noqa: E402


def make_filler(target_tokens: int, salt: str) -> str:
    """Same generator as spike 1, but with a salt prefix to ensure the content
    is FRESH (no overlap with prior runs' caches)."""
    paragraph_template = (
        f"[SALT={salt}] Pellentesque habitant morbi tristique senectus et netus "
        "et malesuada fames ac turpis egestas. Vestibulum tortor quam, feugiat "
        "vitae, ultricies eget, tempor sit amet, ante. Donec eu libero sit amet "
        "quam egestas semper. Aenean ultricies mi vitae est. Mauris placerat "
        "eleifend leo. Quisque sit amet est et sapien ullamcorper pharetra. "
        "Vestibulum erat wisi, condimentum sed, commodo vitae, ornare sit amet, "
        "wisi. Aenean fermentum, elit eget tincidunt condimentum, eros ipsum "
        "rutrum orci, sagittis tempus lacus enim ac dui. Donec non enim in "
        "turpis pulvinar facilisis. Ut felis. Praesent dapibus, neque id "
        "cursus faucibus, tortor neque egestas augue, eu vulputate magna eros "
        "eu erat. Aliquam erat volutpat. Nam dui mi, tincidunt quis, accumsan "
        "porttitor, facilisis luctus, metus.\n\n"
    )
    target_chars = target_tokens * 4
    out = ""
    while len(out) < target_chars:
        out += paragraph_template
    return out


# Use a unique salt so this prefix has never been sent before.
FRESH_PREFIX = make_filler(5000, "task-159-spike-1b-fresh-2026-04-29")
print(f"FRESH_PREFIX char length: {len(FRESH_PREFIX)}")
print()


def dump_usage(label: str, response: object) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        print(f"{label}: (no usage)")
        return
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
# Disambiguator: NO cache_control marker, fresh prefix, single cold call
# -----------------------------------------------------------------------------
print("=" * 72)
print("DISAMBIGUATOR — fresh prefix, NO cache_control marker, cold call")
print("=" * 72)

response = litellm.completion(
    model="gemini/gemini-2.5-flash",
    messages=[
        {"role": "system", "content": FRESH_PREFIX},
        {"role": "user", "content": "What is 2+2?"},
    ],
)
dump_usage("NO-MARKER cold", response)
