"""Task 159 Spike 2: OpenAI prompt_cache_key parallel-batch routing.

Goal: verify whether N parallel calls with the same prompt_cache_key cluster
on one backend (most subsequent calls hit cache after warm-up) or randomize
(parallel writes still race despite the routing hint).

Encoded plan decision: emit prompt_cache_key whenever subset is non-empty.
Spike informs `pflow guide caching` OpenAI section's empirical guidance.
"""
import concurrent.futures
import hashlib
import json
import os
import time

from pflow.core.settings import SettingsManager

for k, v in (SettingsManager().load().env or {}).items():
    if v and k not in os.environ:
        os.environ[k] = v

import litellm  # noqa: E402


def make_filler(target_tokens: int, salt: str) -> str:
    paragraph = (
        f"[SALT={salt}] In id sapien sit amet justo accumsan tempor. Phasellus "
        "lobortis purus a turpis condimentum, vitae mattis tortor lobortis. "
        "Suspendisse et tellus eu ligula condimentum bibendum. Pellentesque "
        "habitant morbi tristique senectus et netus et malesuada fames ac "
        "turpis egestas. Mauris consectetur, dolor sit amet hendrerit interdum, "
        "lacus magna pellentesque odio, ut tincidunt nibh dui ut nulla. Praesent "
        "sit amet metus mauris. Aliquam erat volutpat. Donec malesuada nibh sed "
        "sapien tristique, vel posuere magna pharetra. Curabitur sodales ipsum "
        "non lectus accumsan, eget feugiat sem rutrum.\n\n"
    )
    target_chars = target_tokens * 4
    out = ""
    while len(out) < target_chars:
        out += paragraph
    return out


PREFIX = make_filler(2000, "task-159-spike-2-2026-04-29")
KEY = hashlib.md5(PREFIX.encode(), usedforsecurity=False).hexdigest()
N = 6  # within OpenAI's documented ~15 RPM soft cap per backend
MODEL = "openai/gpt-4o-mini"

print(f"PREFIX char length: {len(PREFIX)}")
print(f"KEY: {KEY}")
print(f"N parallel calls: {N}")
print(f"MODEL: {MODEL}")
print()


def usage_dict(response: object) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "__dict__"):
        return vars(usage)
    return dict(usage)


def call_one(idx: int) -> tuple[int, dict]:
    response = litellm.completion(
        model=MODEL,
        messages=[
            {"role": "system", "content": PREFIX},
            {"role": "user", "content": f"Item {idx}: respond with one word."},
        ],
        extra_body={"prompt_cache_key": KEY},
    )
    return idx, usage_dict(response)


# -----------------------------------------------------------------------------
# Step 1: Warm the cache with a single sequential call.
# -----------------------------------------------------------------------------
print("=" * 72)
print("WARM-UP — single sequential call to prime cache")
print("=" * 72)
warm_idx, warm_usage = call_one(-1)
print(f"Warm call usage:")
print(json.dumps(warm_usage, indent=2, default=str))
print()


# Brief moment for cache to register on the assigned backend.
time.sleep(2)


# -----------------------------------------------------------------------------
# Step 2: Fan out N parallel calls with the SAME prompt_cache_key.
# -----------------------------------------------------------------------------
print("=" * 72)
print(f"PARALLEL — {N} concurrent calls with same prompt_cache_key")
print("=" * 72)
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
    futures = [pool.submit(call_one, i) for i in range(N)]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]
elapsed = time.time() - start
results.sort()

cache_hits = 0
for idx, usage in results:
    print(f"\n--- Parallel call {idx} ---")
    print(json.dumps(usage, indent=2, default=str))
    cached = (
        usage.get("cache_read_input_tokens", 0)
        or (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        or 0
    )
    if cached and cached > 0:
        cache_hits += 1

print()
print("=" * 72)
print(f"SUMMARY")
print("=" * 72)
print(f"Parallel calls: {N}")
print(f"Cache hits: {cache_hits} / {N}")
print(f"Cache miss: {N - cache_hits} / {N}")
print(f"Wall-clock elapsed: {elapsed:.2f}s")
