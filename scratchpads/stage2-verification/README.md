# Stage 2 verification fixtures

> **Purpose**: Test fixtures for verifying Task 159 (`## Cache` +
> `prompt_cache:`) end-to-end on real and synthetic workflows. If a
> finding from `.taskmaster/tasks/task_159/implementation/reports/REPORT.md`
> needs re-verification, or a fix needs regression testing, start here.
>
> **Audience**: a future agent who needs to re-run any Stage 2 test
> without re-deriving the methodology. Each test directory has
> standalone instructions below; you should not need to read the
> .pflow.md files to know what they do.

---

## Quick reference

| Directory | What it tests | Cost/run | Provider(s) |
|---|---|---|---|
| `gemini-smoke/` | Mechanism check on Gemini 2.5 Flash (2 calls, 1 cache chunk) | ~$0.001 | Gemini |
| `anthropic-smoke/` | Mechanism check on Anthropic Sonnet 4.5 (2 calls, 1 chunk) | ~$0.024 (3 runs) | Anthropic Sonnet |
| `anthropic-haiku/` | Anthropic Haiku 4.5 mechanism + 1h TTL cost normalization regression | ~$0.05 (3 runs) | Anthropic Haiku |
| `song-creator/` | **Spec-target verification** on motivating workflow (lyrics-generator) | ~$0.20–0.86 | Configurable (Gemini Flash or Haiku) |
| `chorus-chooser/` | Snapshot of analyze-cache greenfield on chorus-chooser sub-workflow | $0 | n/a |
| `mixed-model-test/` | Cross-node mixed-model cache fragmentation (Finding #11) | ~$0.007 | Gemini + Anthropic |
| `cross-workflow-test/` | Cache propagation across sub-workflow boundaries (Finding #21) | ~$0.002 | Gemini |
| `error-ux-tests/` | Validator catalog UX (`cache.order-mismatch`, `cache.invalid-on-non-llm`, `cache.unused-chunk`) | $0 (validate-only) | n/a |
| `ttl-expiry-test/` | TTL expiry attribution (Finding #18 — currently parser-rejected) | $0 (parse error) | n/a |
| `findings/` | Standalone implementation specs for filed findings (now relocated to `.taskmaster/tasks/task_159/implementation/reports/`) | n/a | n/a |

---

## Prerequisites

Most tests require a default LLM model configured. **Always check first**:

```bash
uv run pflow settings llm show
```

For tests that use the default model (smokes, song-creator without
overrides), you'll typically want:
- `gemini/gemini-2.5-flash` for cheap fast tests, OR
- `anthropic/claude-haiku-4-5` for clean spec-target measurement
  (no implicit cache to confound)

Switch with:
```bash
uv run pflow settings llm set-default <model>
```

**API keys**: set `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) and/or
`ANTHROPIC_API_KEY` in your shell env. pflow uses LiteLLM under the hood.

---

## Per-directory instructions

### `gemini-smoke/`

**Files:**
- `smoke-with-cache.pflow.md` — 2 LLM calls share `${context}` via `## Cache`
- `smoke-no-cache.pflow.md` — same prompts inlined (no cache block) — control
- `reference.md` — 1.4k-token MERIDIAN protocol reference body (the cache content)
- `RUN1-no-cache-trace.json`, `RUN2-with-cache-trace.json`, `RUN3-rerun-trace.json`,
  `RUN4-memo-hit-trace.json` — historical traces from earlier session
- `ANALYZE-*.txt` — saved analyze-cache outputs

**What it verifies**: cache_control markers reach Gemini, cache_creation
on call 1, cache_read on call 2, rerun within TTL has both reading.

**Run first time** (writes cache, reads on call 2):
```bash
CTX="$(cat scratchpads/stage2-verification/gemini-smoke/reference.md)"
uv run pflow scratchpads/stage2-verification/gemini-smoke/smoke-with-cache.pflow.md \
  --no-cache context="$CTX"
```

**Rerun within TTL** (5 min default for `## Cache` block) — re-run the
same command within 5 minutes; both calls should show `cache_read_input_tokens > 0`.

**Gotcha**: Gemini's `cache_creation_input_tokens` is always 0/absent
even when caching works. Verify via `cache_read_input_tokens` on call 2
and overall cost reduction.

---

### `anthropic-smoke/`

**Files:**
- `smoke-with-cache.pflow.md`, `smoke-no-cache.pflow.md` — 2-call workflows on
  `anthropic/claude-sonnet-4-5`
- `reference.md` — 1393-token reference body (above Sonnet's 1024 min)
- `RUN1/RUN2/RUN3-*-trace.json` — RUN1 = no-cache control, RUN2 = first
  write+read, RUN3 = rerun within 5min TTL
- `REPORT.md` — earlier session's report with definitive Anthropic data
- `ANALYZE-*.txt` — analyze-cache snapshots

**What it verifies**: same as gemini-smoke but on Anthropic. Sonnet
populates BOTH `cache_creation_input_tokens` AND `cache_read_input_tokens`
correctly (no telemetry asymmetry).

**Run**:
```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-smoke/reference.md)"
uv run pflow scratchpads/stage2-verification/anthropic-smoke/smoke-with-cache.pflow.md \
  --no-cache context="$CTX"
```

For 3-run sequence (no-cache baseline, with-cache fresh, with-cache rerun
within 5min):
```bash
# Run 1 — baseline
uv run pflow scratchpads/stage2-verification/anthropic-smoke/smoke-no-cache.pflow.md \
  --no-cache context="$CTX"
# Run 2 — write cache
uv run pflow scratchpads/stage2-verification/anthropic-smoke/smoke-with-cache.pflow.md \
  --no-cache context="$CTX"
# Run 3 — read cache (within 5 min)
uv run pflow scratchpads/stage2-verification/anthropic-smoke/smoke-with-cache.pflow.md \
  --no-cache context="$CTX"
```

Expected per the earlier report: ~25% first-run, ~73% rerun reduction.

---

### `anthropic-haiku/`

**Files:**
- `smoke-with-cache.pflow.md`, `smoke-no-cache.pflow.md` — 6 LLM calls
  sharing the reference (larger amortization than 2-call smokes)
- `reference.md` — same MERIDIAN reference body
- `RUN-A-no-cache-trace.json` — baseline
- `RUN-B-with-cache-trace.json` — first write + 5 reads
- `RUN-C-rerun-trace.json` — rerun (6 reads)

**What it verifies**: Haiku 4.5 mechanism + the **1h TTL cost
normalization fix** (progress log line 7188). On a 1h TTL block, the
cache_creation should be priced at $2.00/M (Haiku's 1h rate per LiteLLM
metadata), not $4.00/M (the older `_maybe_normalize_anthropic_1h_cost`
override that double-charged).

**Run** (note: Haiku 4.5's cache minimum is **4096 tokens** — same as
Gemini, NOT 1024 like Sonnet):
```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"
uv run pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --no-cache context="$CTX"
```

**Spec target on this shape**:
- First run: ~60% reduction (1 write at 1.25× + 5 reads at 0.1× vs 6 full)
- Rerun within TTL: ~90% reduction (6 reads at 0.1× vs 6 full)

---

### `song-creator/` (the main Stage 2.1 fixture)

**Workflow under test**: `/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md`
(NOT in this repo — lives in the music-generation project).

**Files:**
- `inputs.json` — song-A inputs (concept + concept_brief) extracted from
  the parent lyrics-generator trace's batch_items[2]
- `chorus-chooser-inputs.json` — inputs for chorus-chooser standalone
- `concept.json`, `architecture.md`, `creative_brief.md`,
  `creative_direction.md` — individual fields/responses (mostly auxiliary)
- `RUN1/RUN2/RUN3-*-trace.json` — Gemini Flash runs (RUN1 = no-cache
  baseline, RUN2 = with cache, RUN3 = rerun)
- `RUN-HAIKU1/2/3-trace.json` — Haiku attempts at various stages
  (1 = timeout; 2 = 3 of 7 nodes; 3 = 4 of 7 with score-choruses workaround)
- `RUN-HAIKU-FINAL-trace.json` — **6 of 7 direct nodes done; 48% input
  cost reduction proves spec target on Anthropic**
- `RUN-HAIKU-RERUN-trace.json` — **rerun within TTL; 99% cost reduction**
- `CHORUS-HAIKU-*` — chorus-chooser standalone Haiku attempt
- `ANALYZE-*.txt`, `DRYRUN-*.txt` — saved analyzer/dry-run outputs

**Prerequisites for the workflow itself** (in
`/Users/andfal/projects/music-generation/workflows/lyrics-generator/`):
- `## Cache` block declared in `song-creator.pflow.md` with 5 chunks
  (`${concept}`, `${concept_brief}`, `${creative-direction.response}`,
  `${song-architecture.response}`, `${easter-eggs.response}`)
- 7 per-node `prompt_cache:` declarations
- Prompts cleaned of duplicate references (no `${concept.title}` etc.
  in prompt bodies — those are now in cache)
- `reasoning_effort: none` on score-choruses + 9 review sub-workflows
  + generate-suno-prompt (workaround for Finding #1; revert when
  the pflow translation bug is fixed)

**Run with Haiku** (clean spec-target, ~$0.86 fresh / $0.01 rerun):
```bash
CONCEPT="$(jq -c .concept scratchpads/stage2-verification/song-creator/inputs.json)"
BRIEF="$(jq -r .concept_brief scratchpads/stage2-verification/song-creator/inputs.json)"

uv run pflow settings llm set-default anthropic/claude-haiku-4-5

# RUN-HAIKU-FINAL equivalent (fresh, with cache):
uv run pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md \
  --report --no-cache concept="$CONCEPT" concept_brief="$BRIEF"

# RUN-HAIKU-RERUN equivalent (memo + provider cache combined; cheap):
uv run pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md \
  --report concept="$CONCEPT" concept_brief="$BRIEF"
```

**Run chorus-chooser standalone** (~$0.07–0.30):
```bash
CONCEPT="$(jq -c .concept scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json)"
CD="$(jq -r .creative_direction scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json)"
ARCH="$(jq -r .architecture scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json)"
BRIEF="$(jq -r .creative_brief scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json)"

uv run pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --report --no-cache concept="$CONCEPT" creative_direction="$CD" \
  architecture="$ARCH" creative_brief="$BRIEF"
```

**Gotchas**:
- Pro Preview models (`gemini/gemini-3.1-pro-preview`,
  `anthropic/claude-sonnet-4-5` thinking-mode) often hit the 120s default
  LLM timeout on this workflow. Use Flash/Haiku, or add `timeout: 300`
  to the heavy nodes.
- Memo cache from prior runs persists across sessions. `--no-cache`
  disables memo but NOT explicit `## Cache` (which may still hit if a
  prior run wrote cache within TTL).
- Gemini's automatic implicit cache fires regardless of explicit cache
  declaration. **For clean spec-target measurement, use Anthropic Haiku.**

---

### `chorus-chooser/`

**Files**: `00-analyze-cache-pre-run.txt` only.

**What it is**: a saved analyze-cache greenfield output for the
chorus-chooser sub-workflow standalone. Useful as a reference snapshot
of what the analyzer reports without needing to re-run.

**To regenerate**:
```bash
uv run pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  > scratchpads/stage2-verification/chorus-chooser/00-analyze-cache-pre-run.txt
```

---

### `mixed-model-test/`

**Files:**
- `mixed-model.pflow.md` — 2 LLM nodes, different providers
  (`gemini/gemini-2.5-flash` + `anthropic/claude-haiku-4-5`), both
  reference the same `${context}` via `## Cache`

**What it tests** (Finding #11): **does cache fragment across
non-matching exact models?** Two nodes share `## Cache` declaration
but use different models — pflow should warn that the cache won't
share (each model gets its own namespace), or the analyzer's projected
savings would be misleading. **Currently no warning fires** — that's
the gap to fix.

**Run**:
```bash
CTX="$(cat scratchpads/stage2-verification/gemini-smoke/reference.md)"
uv run pflow scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md \
  --report --no-cache context="$CTX"
```

**What to look for in the trace**:
- gemini-call: `cache_creation: 0`, `cache_read: <N>` (Gemini implicit
  fires regardless)
- haiku-call: `cache_creation: <M>`, `cache_read: 0` (Anthropic clean
  cache_creation telemetry)
- DIFFERENT cache_keys per call (proves separate namespaces)

**Verify analyze-cache silence**:
```bash
uv run pflow analyze-cache scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md \
  context="$CTX"
# Should report 0-1 opportunities, NO `cache.heterogeneous-models-fragment-cache` warning.
# When the fix lands, the warning should fire here.
```

---

### `cross-workflow-test/`

**Files:**
- `parent.pflow.md` — declares `## Cache` with `${shared_doc}`, calls child
- `child.pflow.md` — receives `shared_doc`, ALSO declares its own `## Cache`

**What it tests** (Finding #21): **cache_keys are workflow-scoped**.
Even when parent + child both declare `## Cache` with identical content
and the same model, their cache_keys differ. Cross-workflow cache only
"works" via Gemini's implicit cache (Anthropic wouldn't share).

**Run**:
```bash
DOC="$(cat scratchpads/stage2-verification/gemini-smoke/reference.md)"
uv run pflow scratchpads/stage2-verification/cross-workflow-test/parent.pflow.md \
  --report --no-cache shared_doc="$DOC"
```

**What to look for**:
- parent-call cache_key ≠ child-call cache_key (different workflow scope)
- BUT both got cache_read on Gemini (implicit cache fires regardless)
- On Anthropic: child-call would NOT cache_read (different cache_key,
  no implicit cache compensation)

---

### `error-ux-tests/`

**Files:**
- `order-mismatch.pflow.md` — `prompt_cache: [b, a]` where `## Cache`
  declares `[a, b]` → triggers `cache.order-mismatch`
- `invalid-on-non-llm.pflow.md` — `prompt_cache:` declared on a `type:
  shell` node → triggers `cache.invalid-on-non-llm`
- `unused-chunk.pflow.md` — `## Cache` declares 2 chunks, only 1 is
  referenced by any LLM node → triggers `cache.unused-chunk` warning

**What it verifies**: validator catalog entries fire correctly with
actionable error messages.

**Run** (all are `--validate-only`, no LLM cost):
```bash
uv run pflow scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md \
  --validate-only a="hello" b="world"

uv run pflow scratchpads/stage2-verification/error-ux-tests/invalid-on-non-llm.pflow.md \
  --validate-only context="hello"

uv run pflow scratchpads/stage2-verification/error-ux-tests/unused-chunk.pflow.md \
  --validate-only used_chunk="A" unused_chunk="B"
```

**Bonus**: each of these also trips `cache.prompt-body-duplicates-cache`
because the test prompts intentionally reference the cached chunks
inline — useful for verifying multi-error rendering.

---

### `ttl-expiry-test/`

**Files:**
- `smoke-ttl-1m.pflow.md` — same shape as gemini-smoke but with
  `ttl: 1m`

**Status: PARSER-REJECTED** (Finding #18). pflow only accepts `ttl: 5m`
or `ttl: 1h`:
```
Error: Parse Error
Invalid '- ttl:' value '1m'. Must be '5m' or '1h'.
```

This file is kept as a regression marker — if pflow ever supports
configurable TTL values, this fixture can be revived to verify
`cache.discrepancy.ttl_expiry` attribution end-to-end.

To verify TTL-expiry attribution today, you'd need to set `ttl: 5m`,
run, wait 5+ minutes, then rerun. Bug 9 unit tests already pin this
behavior — empirical re-verification is low-ROI.

---

### `findings/`

Currently empty — was used as the temporary location for
`cache-heterogeneous-models-fragment.md` before the user moved it to
`.taskmaster/tasks/task_159/implementation/reports/`.

If new findings need standalone implementation specs, those should
live in `.taskmaster/tasks/task_159/implementation/reports/`, not here.

---

## Common patterns and gotchas

### Trace location

All traces auto-save to `~/.pflow/debug/workflow-trace-*.json`. To find
the most recent trace for a specific workflow:

```bash
/bin/ls -t ~/.pflow/debug/workflow-trace-*<workflow-name>* | head -1
```

To copy into a test fixture for archival:

```bash
LATEST=$(/bin/ls -t ~/.pflow/debug/workflow-trace-*<name>* | head -1)
cp "$LATEST" scratchpads/stage2-verification/<dir>/RUN-X-trace.json
```

### Inspecting cache telemetry from a trace

The `--report` flag's per-node markdown shows `## Cached System` (the
system prefix) but **not the per-call cache numbers**. To see those,
drop to jq on the trace:

```bash
jq '[.. | objects | select(.llm_call != null) | {node_id, model: .llm_call.model, input: .llm_call.input_tokens, cache_creation: .llm_call.cache_creation_input_tokens, cache_read: .llm_call.cache_read_input_tokens, cost: .llm_call.cost_usd}]' \
  <trace.json>
```

### Sum total spend (excluding double-counting)

LLM-call leaves only — avoids parent-event wrappers that re-aggregate
their children's costs:

```bash
jq '[.. | objects | select(.llm_call != null and .cached != true) | .llm_call.cost_usd] | {sum: add, count: length}' \
  <trace.json>
```

### `--validate-only` first, always

Before any paid LLM run, run `--validate-only` to catch:
- `cache.prompt-body-duplicates-cache` (overlap between cached chunks
  and prompt body — silently nullifies caching)
- `cache.order-mismatch` (per-node `prompt_cache:` order doesn't match
  `## Cache` block)
- `cache.invalid-on-non-llm` (cache field on non-LLM node)

A 5-second `--validate-only` saves $0.50+ debugging a broken cache config.

### Default model affects cost dramatically

```bash
uv run pflow settings llm show
```

| Model | Per-call cost (5k input) | Cache benefit visibility |
|---|---|---|
| `gemini/gemini-2.5-flash` | ~$0.0015 | Muddied (implicit cache fires regardless) |
| `gemini/gemini-2.5-flash-lite` | ~$0.0008 | Same as Flash |
| `anthropic/claude-haiku-4-5` | ~$0.005 | **Clean — no implicit cache** |
| `anthropic/claude-sonnet-4-5` | ~$0.015 | Clean |
| `gemini/gemini-3.1-pro-preview` | ~$0.013 | 120s timeouts on large prompts |

**For clean spec-target measurement, default to Anthropic Haiku.**

### Memo cache cross-session

pflow's memo cache persists across CLI sessions. A "fresh" run isn't
truly fresh if a prior run wrote memos for the same node+inputs. Two
mitigations:
- `--no-cache` flag disables memo for that run (does NOT clear memo
  storage)
- Vary inputs slightly (e.g., add a timestamp to context) to bust
  memo keys

---

## When tests should be re-run

Re-run tests when:
- A finding's fix lands in pflow (regression check) — run the
  corresponding test directory's commands and compare to the historical
  trace
- The trace format bumps (3.0.0 etc.) — verify all auto-load paths
- A new provider or model is added — run smoke tests on it
- A user reports a Stage 2 finding looks different in production —
  re-run to compare

**Don't re-run** for:
- General sanity checks — Stage 1 unit tests cover the contract
- Performance verification — these tests are correctness-focused, not
  perf benchmarks
- Spec target re-validation — RUN-HAIKU-FINAL + RUN-HAIKU-RERUN are
  definitive; re-running burns budget without new evidence

---

## Companion docs

- `.taskmaster/tasks/task_159/implementation/reports/REPORT.md` — the
  21-finding catalogue from Stage 2 verification
- `.taskmaster/tasks/task_159/implementation/reports/cache-heterogeneous-models-fragment.md` — implementation spec for Finding #11 (uses `mixed-model-test/` fixture)
- `.taskmaster/tasks/task_159/implementation/handoffs/stage2-findings-fix-decision.md` — agent handoff for the next planning + fix-implementation session
- `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md` — full task history
