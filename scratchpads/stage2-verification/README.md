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

## Final verification plan

Use this order when closing Task 159. It reflects the implementation log
through 2026-05-06, including the Stage 2 follow-up fixes after the original
provider-cache smoke tests.

### Handoff trust boundary

The two handoff docs change how to interpret this final pass:

- **Verified**: the provider mechanism already met the spec target on real
  Anthropic Haiku song-creator traces (`RUN-HAIKU-FINAL` = 48% fresh input
  reduction, `RUN-HAIKU-RERUN` = ~99% rerun reduction). Do not spend money
  re-proving this unless runtime prompt rendering, telemetry, trace cost
  accounting, or the external lyrics-generator workflow changed.
- **Primary remaining risk**: agent-facing UX and integration drift. Read full
  `analyze-cache`, `--report`, guide, and JSON output; do not truncate with
  `head`, because blocking errors and notes often appear below the first
  screen.
- **Agent UX is a first-class verification target**: a check does not pass
  just because the command exits correctly. The output must tell a new agent
  what happened, why it matters, and what concrete edit or next command to run.
  Treat confusing wording, hidden caveats, stale terminology, missing warning
  IDs, or ambiguous savings as verification failures.
- **Provider truth**: Anthropic is the clean verification path. Gemini has
  implicit cache that can fire without explicit `prompt_cache:`, so it is good
  for compatibility checks but bad for spec-target proof.
- **Model truth**: provider cache scope is exact-model scoped, not
  provider-family scoped. Any mixed-model verification must preserve this
  distinction.
- **Finding #1 current contract**: Anthropic `reasoning_effort:
  low|medium|high` with static `temperature != 1.0` is now expected to fail
  validation via `llm.thinking-temperature-mismatch`. Do not expect pflow to
  silently normalize the temperature.
- **Out of scope for this final pass**: MCP parity. The CLI/analyzer/trace
  surfaces below are the verification target.

### Progress-log reading list

The README is runnable on its own, but a final-verification agent should read
these progress-log sections first to understand the trust boundaries behind
the expected output:

- `Segment 2 — Memo-hash gate (2026-04-29)` — why rendered
  `prompt_cache:` content must affect memo hashes, while no-`prompt_cache`
  workflows keep their old hash.
- `Segment 3 — Rendering + Prewarm + Trace (2026-04-29)` and
  `Post-segment-3 adversarial CLI verification + 2 bug fixes` — cache
  rendering, prewarm, trace fields, and the dotted-path cache-rendering bug.
- `Segment 4 — Analyzer + Docs (2026-04-29)` and
  `Post-segment-4 follow-up: cost wiring + honest loose-ends audit` —
  analyzer output shape, tri-state cost rules, and why `$0` vs unavailable is
  load-bearing UX.
- `Detect prompt-body / prompt_cache overlap (2026-05-04)` — why duplicated
  cached chunks in prompt bodies are blocking errors.
- `Stage 2 follow-up — ## Cached System in --report (trace 2.2.0)` — current
  trace/report visibility contract and the 2.x consumer gate.
- `Stage 2.1 follow-up — Anthropic 1h cost double-charge (2026-05-05)` —
  Haiku 1h TTL pricing expectation.
- `Stage 2 verification — comprehensive UX + spec-target audit (2026-05-05)`
  — source of truth for the real-provider proof, Gemini confounding, and the
  original 21 findings.
- `Stage 2 follow-up — Finding #1: thinking + temperature validate-time check`
  — current Anthropic reasoning/temperature contract.
- `Stage 2 follow-up — Findings #11/#12: exact-model fragmentation + lone-write
  penalty` and its `post-review fixes` section — exact-model scoping and
  honest-unmeasurable behavior.
- `Stage 2 follow-up — Finding #6: split blocking errors from recommendations`
  — current text/JSON severity split.
- `Stage 2 follow-up — Findings #4/#5: per-call cache telemetry surfaces` —
  current `--report` and JSON telemetry expectations.
- `Test-suite performance triage and isolation cleanup (2026-05-06)` —
  current `make test` / `make test-e2e` split and why sandbox commands differ.
- `Stage 2 follow-up — Findings #9/#10 + phantom-savings: unified
  below-min-token detection` and `post-implementation review + tightening` —
  below-min runtime warnings, provider-aware wording, phantom-savings
  suppression, and missing-telemetry guard.
- `Stage 2 follow-up — Finding #8: drift-aware analyze-cache auto-load` —
  stale-trace/manual drift expectations.
- `Stage 2 follow-up — Finding #7: LLM node count vs invocation count` —
  batch/node/invocation summary expectations.
- `Stage 2 status check — Findings #3, #14, #16` — sub-workflow cost
  attribution, thinking-temperature validation, and skipped-chunk status.
- `Stage 2 follow-up — Finding #21: child-scoped sub-workflow cache
  recommendations` — child-owned cache declaration behavior.
- `Stage 2 follow-up — Finding #17: all-memo trace cost is known zero` —
  all-memo rerun cost expectations.

### 1. Automated regression gate

These tests verify the fixed implementation contracts without spending LLM
budget. In a normal local shell, run:

```bash
make test
make test-e2e
make check
```

In Codex sandbox mode, avoid `uv run` and write pflow state under
`/private/tmp`:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -m "not e2e"

HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 \
  --dist=worksteal \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -m e2e

.venv/bin/ruff check
.venv/bin/ruff format --check
.venv/bin/mypy src
.venv/bin/deptry src
```

If the full gate fails, start with this focused cache sweep before debugging
unrelated failures:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  tests/test_core/test_cache_analysis_analyze.py \
  tests/test_core/test_cache_analysis_token_estimation.py \
  tests/test_core/test_cache_analysis_renderers.py \
  tests/test_core/test_cache_analysis_per_id_emission.py \
  tests/test_core/test_cache_analysis_per_id_coverage.py \
  tests/test_core/test_cache_analysis_warnings.py \
  tests/test_core/test_cache_analysis_summarize.py \
  tests/test_core/test_cache_analysis_cross_workflow.py \
  tests/test_core/test_ir_schema_cache.py \
  tests/test_core/test_cache_opt_out_parser.py \
  tests/test_core/test_prompt_cache_validation.py \
  tests/test_core/test_trace_report.py \
  tests/test_cli/test_dry_run.py \
  tests/test_execution/test_plan_cache_nudge.py \
  tests/test_execution/test_plan_drift.py \
  tests/test_execution/test_runner.py \
  tests/test_nodes/test_llm/test_batch_cache_prefix.py \
  tests/test_nodes/test_llm/test_prompt_cache_rendering.py \
  tests/test_runtime/test_cache_opt_out.py \
  tests/test_runtime/test_cache_opt_out_compiler.py \
  tests/test_runtime/test_prompt_cache_compile.py \
  tests/test_runtime/test_prompt_cache_hash.py \
  tests/test_runtime/test_trace_format_2_2.py \
  tests/test_runtime/test_trace_integration.py \
  tests/test_runtime/test_workflow_trace.py
```

### 2. Free CLI UX checks

These catch renderer, validator, guide, JSON, and autoload behavior that unit
tests cover but humans still need to inspect for agent readability. Evaluate
these as UX surfaces, not just command outputs:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow guide caching

HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md \
  --validate-only a="hello" b="world"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md \
  a="hello" b="world"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md \
  --format=json a="hello" b="world"
```

Expected signal:
- `pflow guide caching` says `--no-cache` disables only pflow's memo layer,
  not provider prompt caching.
- `ttl` docs mention only `5m` and `1h`.
- Blocking errors render in `## Blocking errors (must fix before save and run)`.
- JSON has `blocking_errors[]` and `recommended_actions[]`; errors are not
  duplicated into recommendations.

### 3. Analyzer regression checks on scratch fixtures

Run the synthetic fixtures after the automated gate. These are cheap and catch
the fixes most likely to regress through text/JSON drift:

```bash
CTX="$(cat scratchpads/stage2-verification/gemini-smoke/reference.md)"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md \
  --format=json context="$CTX"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/cross-workflow-test/parent.pflow.md \
  --format=json shared_doc="$CTX"
```

Expected signal:
- Mixed-model fixture emits `cache.first-call-write-penalty` when token data is
  measurable. `cache.heterogeneous-models-fragment-cache` may be silent when
  exact shared-chunk token data is unavailable; this is intentional
  honest-unmeasurable behavior, not a failure.
- The checked-in cross-workflow fixture has a child `## Cache`, so it should
  suppress `cache.sub-workflow-cache-undeclared`. To verify the positive #21
  path manually, copy `child.pflow.md`, remove the child `## Cache` block and
  `prompt_cache:` declarations, point `parent.pflow.md` at the copy, then run
  `analyze-cache`; parent `## Cache` must not suppress the child-scoped
  recommendation.
- Suggested blocks include per-node threshold information and allowed TTL
  values.

### 4. Real provider smoke

Only run this if API keys are available. This verifies the actual rendering
layer still reaches providers after all analyzer/report work:

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"

uv run pflow settings llm set-default anthropic/claude-haiku-4-5

uv run pflow scratchpads/stage2-verification/anthropic-haiku/smoke-no-cache.pflow.md \
  --report --no-cache context="$CTX"

uv run pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --report --no-cache context="$CTX"

uv run pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --report --no-cache context="$CTX"
```

Expected signal:
- Fresh with-cache run: one Anthropic cache write plus later cache reads.
- Rerun within TTL: all calls show cache reads.
- `--report` includes `## Cached System`, `## Cache telemetry`, warning IDs
  where applicable, and no stale `memo`/`in_process` implementation wording.
- Analyze the freshest trace with `pflow analyze-cache --from-trace <trace>`
  and confirm per-call JSON includes raw
  `cache_creation_input_tokens` / `cache_read_input_tokens`.

### 5. Spec-target check

The historical Haiku song-creator traces already prove the locked target:
`RUN-HAIKU-FINAL` hit 48% fresh input-cost reduction and
`RUN-HAIKU-RERUN` hit about 99% rerun reduction. Re-run the paid
song-creator workflow only if code changes touched runtime prompt rendering,
provider telemetry, trace cost accounting, or the external lyrics-generator
workflow.

If re-run is justified, use Anthropic Haiku, not Gemini, because Gemini's
implicit cache confounds explicit `prompt_cache:` measurement. Before running,
validate the external workflow and inspect that the prior Finding #1
workarounds are no longer needed if `llm.thinking-temperature-mismatch` is
now enforced.

### Manual things worth testing hard

These are the edges the implementation log says were most likely to hide
silent failures:

- **Trace autoload drift**: run `analyze-cache` against a workflow, rename one
  root LLM node or change its static model, then run `analyze-cache` again
  without `--from-trace`. It should silently discard the stale trace. Explicit
  `--from-trace` should still load it.
- **All-memo cost**: run a cached workflow once, then rerun without
  `--no-cache`; `analyze-cache --from-trace` should report
  `actually_paid_usd: 0.0` with tier `trace`, not `null`.
- **Below-min runtime warning**: run a tiny Anthropic cached prompt below that
  model's minimum. It should warn after the run using
  `cache.below-min-tokens`. Missing provider telemetry should not fabricate
  this warning.
- **Skipped chunks**: use a workflow where one `prompt_cache:` chunk is below
  provider minimum or dropped by the renderer. `--report` should surface
  `cache_chunks_skipped`, and `analyze-cache` discrepancy attribution should
  say `chunk_skipped`.
- **Batch language**: analyze one static inline batch and one dynamic batch.
  Summary should distinguish LLM node count from invocation count and expose
  `dynamic_batch_node_count` in JSON when the invocation count is unknown.
- **Sub-workflow attribution**: use parent/child workflows with same node IDs
  in different files. Costs and cache recommendations must be scoped by
  `(workflow_path, node_id)`, not node ID alone.
- **Dry-run cache nudge**: run `--dry-run` on a workflow with actionable cache
  opportunities and confirm `cache.opportunities-available` appears with
  readable savings context. Run it on an already-optimal workflow and confirm
  the nudge is silent.
- **Cache-layer independence**: `cache: false` and `--no-cache` disable pflow
  memo reads only. They must not remove rendered provider `prompt_cache:`
  content, and workflows without `prompt_cache:` must keep their pre-task memo
  hash.
- **Prewarm remains opt-in**: `cache.batch-prewarm-recommended` should be
  advisory in `analyze-cache` / `--dry-run`; plain `pflow run` should not block
  or auto-enable `prewarm: true`.

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
- Finding #1 is now fixed as `llm.thinking-temperature-mismatch`.
  `reasoning_effort: low|medium|high` with static Anthropic
  `temperature != 1.0` should fail validation. If the external workflow
  still carries `reasoning_effort: none` workarounds from the old run,
  treat them as test-era edits, not required cache configuration.

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

**What it tests** (Findings #11/#12): **does cache fragment across
non-matching exact models, and does a lone exact-model cache write get
flagged?** Two nodes share `## Cache` declaration but use different
models, so each exact model has its own provider cache namespace.

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

**Verify analyze-cache**:
```bash
uv run pflow analyze-cache scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md \
  context="$CTX"
```

Expected now:
- `cache.first-call-write-penalty` should fire for the Anthropic single-call
  group when pricing/token evidence is measurable.
- `cache.heterogeneous-models-fragment-cache` should fire only when exact
  shared-chunk token evidence is measurable. If it is silent because the
  shared chunk is unmeasurable, that is the intended honest-unmeasurable
  behavior after the precise per-chunk math fix.

---

### `cross-workflow-test/`

**Files:**
- `parent.pflow.md` — declares `## Cache` with `${shared_doc}`, calls child
- `child.pflow.md` — receives `shared_doc`, ALSO declares its own `## Cache`

**What it tests** (Finding #21): **cache_keys are workflow-scoped** and
child cache declarations are child-owned. Even when parent + child both
declare `## Cache` with identical content and the same model, their
cache_keys differ. Cross-workflow cache only "works" via Gemini's
implicit cache (Anthropic wouldn't share).

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
- `analyze-cache` should not emit `cache.sub-workflow-cache-undeclared` for
  this checked-in fixture because the child has its own `## Cache`. To test
  the positive diagnostic, remove the child cache block in a scratch copy and
  confirm the new ID fires; parent cache must not suppress it.

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
actionable error messages. In `analyze-cache` text output, ERROR-severity
items should render under `## Blocking errors (must fix before save and run)`,
not under `## Recommended actions`.

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
