# Anthropic Cache Smoke Test — Report

**Date**: 2026-05-01
**Total spend**: ~$0.024 (3 runs across 2 workflows)
**Verdict**: **Cache rendering layer PASS. Analyzer `--from-trace` mode has a real bug class.**

## TL;DR

The cache rendering layer (Segments 2-3 of Task 159) is fully functional —
`cache_control` markers reach Anthropic, cache writes/reads happen at the
expected token volumes, and rerun savings hit the spec target. **Cleared
to proceed to Stage 2.1 (song-creator standalone).**

The smoke test ALSO surfaced a class of bugs in `pflow analyze-cache
--from-trace` mode that affects steady-state usage. Documented below.

## Setup

Two minimal workflows under `scratchpads/stage2-verification/anthropic-smoke/`:

- `smoke-with-cache.pflow.md` — `## Cache` block declaring `${context}`
  + `prompt_cache: [context]` on both LLM nodes.
- `smoke-no-cache.pflow.md` — same prompts inlined; no `## Cache`.
- `reference.md` — 1393-token stable reference body (above Sonnet 4.5's
  1024 minimum cache threshold per DD#32).

Both workflows: 2 sequential LLM calls (`answer-a`, `answer-b`) on
`anthropic/claude-sonnet-4-5`, different questions referencing the same
context.

## Runs

| Run | Workflow | Per-call cache_creation | Per-call cache_read | Total cost | Savings vs baseline |
|---|---|---|---|---|---|
| 1 | no-cache | 0, 0 | 0, 0 | $0.01170 | — |
| 2 | with-cache (first) | **1599**, 0 | 0, **1599** | $0.00874 | **-25.3%** |
| 3 | with-cache (rerun within TTL) | 0, 0 | **1599, 1599** | $0.00314 | **-73.2%** |

### Math check

Run 2 first-call: `cache_creation_input_tokens = 1599` (above Sonnet 4.5's
1024 threshold). Cost = (1599 × $3.75/M write) + (37 normal × $3/M) +
output = $0.00689. ✓ Matches per-call trace cost.

Run 2 second-call: `cache_read_input_tokens = 1599`. Cost = (1599 ×
$0.30/M read) + (29 normal × $3/M) + output = $0.00177. ✓

Run 3: both calls read at 0.1× rate. Per-call $0.00137 / $0.00177. ✓

### Why first-run savings is "only" 25%

With N=2 calls sharing context, mathematical first-run ceiling is ~32%
(one cache write at 1.25× + one read at 0.1× vs two full-cost calls).
The spec's ≥40% target applies to LLM-heavy workflows like
lyrics-generator (6+ calls sharing context per sub-workflow). For 2-call
scenarios, ~25-32% first-run is correct. **Rerun (73%) matches spec's
70%+ target — this is the more important verification gate**, since
rerun savings reflect what the cache layer actually delivers on stable
runs.

## What this verifies

✅ `cache_control` markers reach Anthropic via LiteLLM adapter
✅ Anthropic responds with populated `cache_creation_input_tokens` /
   `cache_read_input_tokens` (no Gemini-style telemetry caveat)
✅ Sequential calls in the same run share cache (call-1 writes, call-2 reads)
✅ Reruns within 5-min TTL hit cache (both calls read)
✅ Cost rates match spec (1.25× write, 0.1× read)
✅ pflow's per-call cost wiring (LiteLLM `completion_cost`) reports correctly
✅ Trace 2.1.0 fields populated: `cache_creation_input_tokens`,
   `cache_read_input_tokens`, `cache_chunks_skipped`, `cache_key`,
   `cost_usd`

## Bugs surfaced (analyzer `--from-trace` mode)

These are **real bugs in v1 surface area** that the smoke test surfaced.
Each affects steady-state agent UX (post-run analysis) — exactly the
scenario the analyzer was designed for.

### Bug A — `cacheable_tokens_estimated` ignores trace data

Per spec line 479: "Per-call table shows actual `cache_creation` /
`cache_read` token counts when trace data is available."

**Actual behavior**: per-call `cacheable_tokens_estimated` reads from the
static literal-template heuristic (`${context}` → ~14 tokens) even when
`data_source: "trace"` and the trace's `cache_creation_input_tokens` /
`cache_read_input_tokens` are populated with real numbers (1599 in this
test).

Both runs (RUN2 first-write, RUN3 cache-read) report
`cacheable_tokens_estimated: 14`, `cache_ratio_pct: 1` despite trace
recording 1599 cached tokens out of 1636 total (98% real ratio).

### Bug B — `cache.below-min-tokens` fires false-positive in trace mode

Detection uses Bug A's broken `cacheable_tokens_estimated` (14 < 1024 →
fires). But trace shows the cache IS WORKING at 1599 tokens (above
threshold). Recommended actions surface "cache_control markers will
silently no-op at the provider" — directly contradicting the trace
evidence in the same report.

Two false-positive `cache.below-min-tokens` warnings dominate the
Recommended actions section, drowning out any real findings.

### Bug C — Steady-state savings figures meaningless

`Estimated savings if applied: ~$0.00/run (first run); ~$0.00/run on rerun`

Empirical truth from Run 2 vs Run 1: `-$0.0030/run first-run, -$0.0086/run
on rerun`. The analyzer's cost computation uses Bug A's broken
`cacheable_tokens_estimated` so optimized = current → savings = 0.

### Bug D — Greenfield analysis post-run gives WORSE info

Without trace (greenfield, pre-run): no-cache version shows
`Per-call cache report hidden — workflow has no run data yet. Run once,
then re-run analyze-cache for real per-node token estimates and
cacheable projections.` (correct — defers to post-run).

With trace (post-run): no-cache version shows `current_cost: $0.0117`,
`optimized_cost: $0.0117`, `savings_pct: 0%`, `total_cacheable_tokens: 0`.
This is **worse than the pre-run "unavailable"** — agent reads the
post-run analysis and concludes "no caching opportunity here," but the
analyzer ALSO emits `cache.shared-context-undeclared` recommended action.
Self-contradicting output.

### Common root cause

All four bugs share one root: `_estimate_cacheable_tokens` and the
cost-computation pipeline don't read trace `cache_creation_input_tokens`
/ `cache_read_input_tokens` even when trace data is available. The
static heuristic is the only path. Trace gives the analyzer the input
tokens (correctly: `tokens=1636`) but not the cacheable portion.

Fix scope estimate: ~30-50 LOC + tests. Per spec line 479's locked
contract + the pre-existing `data_source: "trace"` confidence labeling,
the data path is conceptually clear: when `data_source == "trace"`,
read `cacheable_tokens_estimated` from
`trace.llm_call.cache_creation_input_tokens + cache_read_input_tokens`.

## Recommendations

### 1. The cache rendering layer is verified — proceed to Stage 2.1

Lyrics-generator song-creator standalone is cleared. The rendering layer
delivers savings as designed. Stage 2.1 will validate the value-prop on
a realistic 6-call workflow (~$1).

### 2. Decide whether to fix Bug A-D before Stage 2.1 or after

**Argument for fixing first**: Stage 2.1 will produce a trace and
immediately run `analyze-cache --from-trace` against it. The same bugs
will surface there — possibly mixed with real findings, hard to triage.
Fixing now means clean Stage 2.1 output.

**Argument for fixing after**: Stage 2.1 might surface MORE issues that
share the same fix shape. Bundle them.

My recommendation: **fix Bug A as a pre-Stage-2.1 baseline cleanup**.
It's the root cause of B/C/D and the smallest scope. After Bug A lands,
B/C/D should partially or fully resolve as side effects. Stage 2.1 then
runs against a clean analyzer surface.

### 3. Surface to user before Stage 2.1

Per the handoff doc: "Surface to the user **before** Stage 2 spending."
The smoke test cost ~$0.024 (under budget), but the bug findings change
the recommended path. Confirming the fix-first approach is a 2-minute
user decision worth surfacing.

## Files

All under `scratchpads/stage2-verification/anthropic-smoke/`:

- `reference.md` — 1393-token stable reference body
- `smoke-with-cache.pflow.md` — workflow with `## Cache` block
- `smoke-no-cache.pflow.md` — control workflow
- `RUN1-no-cache-trace.json` — baseline trace (no caching)
- `RUN2-with-cache-trace.json` — first-write trace
- `RUN3-rerun-trace.json` — rerun trace (both reads)
- `ANALYZE-{with,no}-cache-{pre-run,from-trace}.txt` — analyzer snapshots
- `RUN[1-3]-*-output.txt` — CLI output per run
