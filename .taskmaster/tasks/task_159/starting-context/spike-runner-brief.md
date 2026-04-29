# Task 159 — Spike Runner Brief

> Read this document fully. Confirm understanding before running paid API calls.

## Your role

You run three pre-authorized paid LiteLLM spikes (~$0.30 total budget), record outcomes, update the plan IF any outcome contradicts the encoded decisions, and update the implementing-agent brief to remove the now-completed spike step. Then surface a summary to the user. **You do not implement Task 159.**

## Read order (in full)

1. **`.taskmaster/tasks/task_159/implementation/implementation-plan.md`** — focus on the "Spike contingencies" table near the bottom (search for `# Spike contingencies`). The table maps each spike → encoded plan decision → what plan section to update if outcome contradicts.
2. **`.taskmaster/tasks/task_159/starting-context/agent-handoff.md`** — sections "Concrete substrate (Task 158 leftovers not in the spec)" (LiteLLM version pin) and "Watch-for warnings" (Gemini's dual-mechanism, Anthropic per-TTL pricing precision, OpenAI parallel-batch routing).
3. **`.taskmaster/tasks/task_159/implementation/progress-log.md`** §30 — describes the spike pattern that worked for the Round 3 Anthropic threshold spike (~$0.50, 3 sub-rounds). Use the same shape.
4. **`.taskmaster/tasks/task_159/task-159.md`** — DD#32 (per-model thresholds), DD#37 (OpenAI `prompt_cache_retention`), "Cache Rendering" section's TTL translation table, "Cost Model Reference."

## Pre-flight

- Verify `litellm==1.82.6` is installed (`uv pip show litellm` from project root). Per handoff "Concrete substrate," this version is pinned because 1.83.x hard-pins `click==8.1.8` which broke pflow tests.
- Verify API keys are configured: `uv run pflow settings list` should show ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY (or the Vertex equivalents).
- Confirm budget: ~$0.30 total. If a spike's first attempt costs more than $0.10, surface to user before continuing.

## Spike runner pattern

Each spike is a minimal Python file under `scratchpads/task-159-spike-<name>.py`. Pattern (per progress log §30):

```python
"""Task 159 Spike <N>: <one-line description>."""
import os
import json
from pflow.core.settings import SettingsManager

# Inject API keys per the §30 pattern
for k, v in (SettingsManager().load().env or {}).items():
    if v and k not in os.environ:
        os.environ[k] = v

import litellm  # lazy after env is set

# ... spike body ...

# Print response.usage breakdown for each call
print(json.dumps(response.usage if hasattr(response, "usage") else {}, indent=2, default=str))
```

After each spike: capture stdout to a sibling `.txt` file (e.g., `task-159-spike-1-output.txt`) so the §36 progress-log entry can reference exact numbers without re-running.

---

## Spike 1: Gemini explicit `cache_control` verification

### Goal

Two scenarios:
- **Scenario A**: Verify that emitting `cache_control: {"type": "ephemeral", "ttl": "300s"}` to Gemini via LiteLLM actually fires `cachedContents` (i.e., `cache_creation_input_tokens > 0` on call 1, `cache_read_input_tokens > 0` on call 2). Distinguish from Gemini's IMPLICIT auto-cache (which fires regardless of markers).
- **Scenario B**: Verify Gemini accepts BOTH a system-cache marker AND a user-message-prefix marker in the same request without API error (per the multi-marker collapse caveat).

### Protocol

Use `gemini/gemini-2.5-flash` (cheapest, lowest threshold per DD#32). Need ≥4096 tokens of stable prefix to reliably exceed explicit-cache minimum. Use a long Lorem-Ipsum-style filler (write inline, ~5000 tokens) so cost stays low.

```python
# Scenario A: single cache_control marker on system message
SYSTEM_PREFIX = "<5000-token stable prefix>"
USER_QUERY = "What is 2+2?"

response_A1 = litellm.completion(
    model="gemini/gemini-2.5-flash",
    messages=[
        {"role": "system", "content": [
            {"type": "text", "text": SYSTEM_PREFIX,
             "cache_control": {"type": "ephemeral", "ttl": "300s"}}
        ]},
        {"role": "user", "content": USER_QUERY},
    ],
)
print("A1 usage:", response_A1.usage)

response_A2 = litellm.completion(
    model="gemini/gemini-2.5-flash",
    messages=[<same as A1>],  # exact byte match for cache hit
)
print("A2 usage:", response_A2.usage)
```

```python
# Scenario B: TWO cache_control markers (system + user-message-prefix)
response_B = litellm.completion(
    model="gemini/gemini-2.5-flash",
    messages=[
        {"role": "system", "content": [
            {"type": "text", "text": SYSTEM_PREFIX,
             "cache_control": {"type": "ephemeral", "ttl": "300s"}}
        ]},
        {"role": "user", "content": [
            {"type": "text", "text": "<2000-token stable prefix>",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": USER_QUERY},
        ]},
    ],
)
print("B usage:", response_B.usage)
# Verify: no API error raised. Whether Gemini collapses to last marker is
# secondary; the load-bearing question is "does Gemini reject?"
```

### Expected outcome (encoded decision)

- Scenario A: A1 reports `cache_creation_input_tokens > 0`; A2 reports `cache_read_input_tokens > 0`.
- Scenario B: request returns successfully (no exception, no error response).

### If contradicts (per Spike contingencies table)

- **Scenario A fails (no `cachedContents` fires)**: ship C2 anyway with a documented info note in `analyze-cache` Gemini output. Update F2's `analyze.py` Gemini-detection branch to append the info note: *"Gemini explicit cache_control may not fire `cachedContents` reliably under this LiteLLM version — observed behavior: <describe>. Implicit auto-cache still applies."* Append the exact info-note text to plan F2 section (search for "Gemini" in F2). NO change to C2 emission code.
- **Scenario B fails (Gemini rejects multi-marker request)**: D.1 needs a Gemini-specific gate to skip the auto-batch marker. Update plan D.1 (search for "Multi-marker placement on Anthropic vs Gemini") to add: `if detect_provider(model).name == "gemini" and prep_res.get("system_blocks"): skip user_message_blocks marker insertion`. Flag as v1.x follow-up `cache.gemini-multi-marker`.

### Cost estimate

~$0.05–0.10. If first attempt exceeds $0.10, surface to user.

---

## Spike 2: OpenAI `prompt_cache_key` parallel-batch routing

### Goal

Verify whether 4–8 parallel calls with the same `prompt_cache_key` cluster on one backend (most subsequent calls hit cache after the first writes) OR randomize (parallel writes still race despite the routing hint).

### Protocol

Use `gpt-5-nano` or `gpt-4o-mini` (whichever is cheaper at run time). Need ≥1024 tokens (OpenAI auto-cache threshold).

```python
import hashlib
import concurrent.futures
import time

PREFIX = "<2000-token stable prefix>"
KEY = hashlib.md5(PREFIX.encode(), usedforsecurity=False).hexdigest()
N = 6  # within OpenAI's ~15 RPM soft cap per backend

def call_one(idx: int):
    return litellm.completion(
        model="openai/gpt-4o-mini",
        messages=[
            {"role": "system", "content": PREFIX},
            {"role": "user", "content": f"Item {idx}: respond with one word."},
        ],
        extra_body={"prompt_cache_key": KEY},
    )

# First, warm the cache with a single call
warm = call_one(-1)
print("Warm:", warm.usage)
time.sleep(2)  # give cache a moment

# Then fan out N parallel calls
with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
    results = list(pool.map(call_one, range(N)))
for i, r in enumerate(results):
    print(f"Parallel call {i}:", r.usage)
```

### Expected outcome (encoded decision)

After the warm-up, most parallel calls report `cache_read_input_tokens > 0`. Some may miss due to the documented ~15 RPM soft cap (graceful degradation, not failure). Encoded plan: emit `prompt_cache_key` whenever subset is non-empty (per spec "Cache Rendering" OpenAI bullet).

### If contradicts (per Spike contingencies table)

- **Routing randomizes (most parallel calls miss cache despite same key)**: emit `prompt_cache_key` regardless (it never hurts). Update plan G.2 `pflow guide caching` OpenAI section (search for "OpenAI" in G.2) to add the empirical finding: *"In observed testing, OpenAI's `prompt_cache_key` did not consistently cluster parallel calls. Hit rate degraded under parallel load; serialize-then-fan-out (`prewarm: true`) is recommended for OpenAI batches."* NO change to C3 emission code.

### Cost estimate

~$0.05. If first attempt exceeds $0.10, surface to user.

---

## Spike 3: Anthropic per-TTL pricing precision via `litellm.completion_cost()`

### Goal

Verify whether `litellm.completion_cost()` distinguishes 1.25× (5-minute TTL) from 2× (1-hour TTL) for cache-write events. Plan E.1 trusts LiteLLM to distinguish; if it doesn't, a `_normalize` override is needed.

### Protocol

Use `claude-sonnet-4-5` (1024-token threshold per DD#32). Need ≥1024 tokens of cacheable content.

```python
PREFIX = "<2000-token stable prefix>"

# Call 1: cache write with DEFAULT 5-min TTL (no explicit ttl key — Anthropic's
# documented behavior: omit ttl for 5-min default; do NOT send ttl: "5m")
r_5m = litellm.completion(
    model="anthropic/claude-sonnet-4-5",
    messages=[
        {"role": "system", "content": [
            {"type": "text", "text": PREFIX,
             "cache_control": {"type": "ephemeral"}}
        ]},
        {"role": "user", "content": "Respond with one word."},
    ],
)
cost_5m = litellm.completion_cost(completion_response=r_5m)
print("5-min TTL — usage:", r_5m.usage)
print("5-min TTL — cost:", cost_5m)

# Call 2: cache write with 1h TTL (slight prefix variation forces fresh write,
# avoiding a cache-hit on call 1's entry)
PREFIX_VARIANT = PREFIX + " VARIANT_FOR_FRESH_WRITE"
r_1h = litellm.completion(
    model="anthropic/claude-sonnet-4-5",
    messages=[
        {"role": "system", "content": [
            {"type": "text", "text": PREFIX_VARIANT,
             "cache_control": {"type": "ephemeral", "ttl": "1h"}}
        ]},
        {"role": "user", "content": "Respond with one word."},
    ],
)
cost_1h = litellm.completion_cost(completion_response=r_1h)
print("1h TTL — usage:", r_1h.usage)
print("1h TTL — cost:", cost_1h)

# Compute manually for comparison: if LiteLLM is correct, cost_1h / cost_5m ≈ 1.6
# (2× / 1.25× for cache writes; the read & non-cached portions wash to ~1).
print(f"Ratio (1h/5m): {cost_1h / cost_5m:.3f}")
```

### Expected outcome (encoded decision)

`cost_1h` is meaningfully larger than `cost_5m` (ratio ≈ 1.4–1.7 — depends on the prefix-to-full-token ratio). Plan E.1 trusts LiteLLM's distinguishing; no override needed.

### If contradicts (per Spike contingencies table)

- **`cost_1h ≈ cost_5m` (LiteLLM doesn't distinguish per-TTL)**: add `_normalize` override in `llm_client.py:776-784`. Update plan E.1 (search for "Anthropic per-TTL pricing precision" in plan and the Spike contingencies table) to add the override patch: compute write cost from raw `cache_creation_input_tokens` × per-provider rate (1.25× for 5-min, 2× for 1h) and override `cost_usd` for cache-write events.

### Cost estimate

~$0.10–0.15 (this one's the most expensive because it issues two cache-write requests with substantial prefix). If first attempt exceeds $0.20, surface to user.

---

## After running all three spikes

### Step 1: Write §36 progress log entry

Append to `.taskmaster/tasks/task_159/implementation/progress-log.md`:

```markdown
## 36. Session YYYY-MM-DD — Pre-implementation paid spike outcomes

Three pre-authorized paid spikes (~$0.30 total budget) executed before B1.1.
Each verifies an encoded plan decision; outcomes are recorded against the
plan's "Spike contingencies" table.

### Spike 1 — Gemini explicit cache_control
- **Scenario A** (cachedContents fires under LiteLLM Vertex translation):
  - Call 1 usage: <paste>
  - Call 2 usage: <paste>
  - Outcome: <CONFIRMS / CONTRADICTS> encoded decision.
- **Scenario B** (Gemini accepts multi-marker):
  - Response: <paste>
  - Outcome: <CONFIRMS / CONTRADICTS>.
- **Plan updates** (if any): <list>

### Spike 2 — OpenAI prompt_cache_key parallel-batch routing
- N=<N> parallel calls; cache_read counts: <list>
- Outcome: <CONFIRMS / CONTRADICTS>.
- **Plan updates** (if any): <list>

### Spike 3 — Anthropic per-TTL pricing precision
- 5-min TTL cost: <value>
- 1h TTL cost: <value>
- Ratio: <value>
- LiteLLM distinguishes: <yes/no>.
- Outcome: <CONFIRMS / CONTRADICTS>.
- **Plan updates** (if any): <list>

### Total cost
$<X.XX> across all three spikes.

### Files written
- `scratchpads/task-159-spike-1.py` + `task-159-spike-1-output.txt`
- `scratchpads/task-159-spike-2.py` + `task-159-spike-2-output.txt`
- `scratchpads/task-159-spike-3.py` + `task-159-spike-3-output.txt`

### Next step
B1.1 implementation can now proceed. Implementing agent reads §36 to confirm
spike outcomes; any plan updates from contradictions are already encoded.
```

### Step 2: Apply plan updates per Spike contingencies table

For each contradiction, update the plan section per the table's "if outcome contradicts" column. Each plan update lands in a separate edit:
- Document the change in §36 with a one-line summary AND the plan section that was updated.
- Don't bundle multiple plan updates into one edit — each is a distinct decision change.

If ALL three spikes confirm encoded decisions, the §36 entry says "All three confirm; no plan updates required." Skip Step 2.

### Step 3: Update `implementing-agent-brief.md`

Edit `.taskmaster/tasks/task_159/starting-context/implementing-agent-brief.md`:

- **Replace** the "Before you start coding" section (Agent 1 spike protocol) with a shorter section: *"Spikes are complete (see progress-log.md §36). Verify any plan updates from spike contradictions are reflected in your read of the plan. If §36 reports `<NEEDS USER DECISION>` for any outcome, do NOT proceed — escalate to user."*
- **Update** the "Agent 2+ (B3, C+D+E, F+G)" section to remove the line about waiting for §36 to land — §36 IS landed.
- **Update** the line `Three pre-authorized paid spikes (~$0.30 total) inform the plan` → `Three pre-authorized paid spikes have run (see progress-log.md §36). Plan updates from spike contradictions are encoded.`

### Step 4: Update braindump

Edit `.taskmaster/tasks/task_159/starting-context/braindump-2026-04-28-plan-writing-and-review.md`:

- Find sentences mentioning "three pre-authorized paid spikes (~$0.30 total) per the agent-handoff, records outcomes as a §36 progress-log entry" and similar.
- Update wording to reflect spikes are DONE: e.g., *"three pre-authorized paid spikes ran in §36; outcomes are recorded; plan updates from any contradictions are encoded."*
- Don't rewrite extensively — these are minimal edits.

### Step 5: Surface to user

Post a concise summary:
- "All 3 spikes complete. Total cost: $X.XX."
- "Outcomes: <CONFIRM/CONTRADICT> per spike."
- "Plan updates: <count> sections updated (or 'none required')."
- "Implementing-agent brief updated to reflect spikes-done state."
- "B1.1 ready to start when you say go."

## What you DO NOT do

- Don't run unrelated paid API calls. Stay strictly within the three documented spikes.
- Don't write to plan sections that aren't called out in the Spike contingencies table.
- Don't continue past Spike 1 if Scenario A fails AND Scenario B also fails — surface to user (cumulative cost-benefit shift may warrant re-thinking).
- Don't modify anything in `src/` (you're not implementing the feature; you're just verifying behavior + updating planning docs).
- Don't create new spike scenarios beyond the three documented. If you suspect a 4th spike is warranted, surface to user.

## When you're stuck

- **Spike fails with an unexpected error** (auth, rate limit, model unavailable): surface to user before retrying. Don't burn budget on retries with bad keys.
- **Outcome is ambiguous** (e.g., cache_creation_input_tokens=0 might mean "no cache fired" OR "below threshold and silently no-op"): re-run with a larger prefix (4× the original) before declaring outcome. Document both attempts in §36.
- **LiteLLM behaves differently than the plan assumed**: capture the specific behavior in §36; surface to user. The plan's encoded decisions assumed LiteLLM 1.82.6 behavior — drift is possible.

## End of session

Once §36 is written + plan updates applied + brief updated, surface to user. Do NOT begin B1.1 — that's a different agent's job.
