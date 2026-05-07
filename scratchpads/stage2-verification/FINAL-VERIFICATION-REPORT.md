# Task 159 Prompt Caching - Final Verification Report

Verification date: 2026-05-06
Verifier role: adversarial verification specialist
Repo: `/Users/andfal/projects/pflow-feat-prompt-caching`
External music workflow repo inspected read-only: `/Users/andfal/projects/music-generation/workflows/lyrics-generator/`
Paid provider spend used: approximately `$0.088 / $4.00`

## Executive summary

The prompt-caching implementation is not ready to call fully verified.

The core provider mechanism works on real Anthropic Haiku smokes: `prompt_cache` renders, provider cache reads/writes appear in telemetry, and reruns are cheaper. However, the agent-facing verification surfaces still have important failures:

- Analyzer savings math can emit impossible negative savings percentages.
- Partial `--only` traces can produce misleading recommendations and savings projections.
- Reports for memo hits mix actual zero paid cost with historical provider cost.
- `pflow guide caching` is stale and omits several warning IDs agents need.
- Music workflow analyzer recommendations include non-actionable cache edits that are below provider token thresholds.
- Dynamic batch traces preserve useful per-item telemetry, but analyzer model accounting for that paid music run is wrong.
- `--only` plus multi-output workflows can stream a skipped output and dump huge intermediate JSON to stdout.

The implementation has good foundations, but the remaining issues are primarily analyzer correctness, report cost semantics, and agent UX.

## Critical context for the next agent

Prompt caching has two separate cache layers:

- Provider prompt caching: `prompt_cache:` / `## Cache` cause pflow to render provider-specific cache markers into LLM requests. This changes provider billing and is exact-model scoped.
- Pflow memo cache: pflow can skip node execution and reuse prior outputs. `cache: false` and `--no-cache` affect this layer, not provider prompt-cache rendering.

Do not conflate these. Several findings matter because the UI mixes "paid this run" with historical provider cost, or because disabling pflow memo cache must not disable provider prompt caching.

Provider cache scope is exact-model scoped. A cache read for `anthropic/claude-haiku-4-5` does not prove anything for `anthropic/claude-sonnet-*`, and Gemini's implicit cache can fire without explicit `prompt_cache:`. That is why wrong analyzer model accounting is serious, especially for dynamic batch nodes where each item can resolve a different model.

Prompt-cache economics are asymmetric:

- First run can cost more because cache writes are priced differently.
- Reruns within TTL are where savings appear.
- Small chunks below provider token minimums do not cache at all.

Therefore negative "savings" is not automatically a bug, but presenting negative first-run cost as "savings", emitting impossible savings percentages, or recommending below-threshold cache blocks as actionable edits is a bug. The analyzer must distinguish "write premium", "no useful provider cache", and "rerun savings".

Partial traces from `--only` are not whole-workflow evidence. They are useful verification tools, but analyzer output must label them as partial and avoid full-workflow confidence claims. Mixing one executed node with memo/projection rows can create convincing but false cost conclusions.

Agent UX is part of correctness for this task. A command passing is not enough. The output must tell a new agent:

- what happened,
- why it matters,
- which warning ID applies,
- whether the edit is actionable,
- which exact file/node/model is involved,
- and what command or edit to do next.

When output is technically true but leads an agent to make a useless edit, copy wrong syntax, trust wrong model/cost data, or rerun an expensive workflow unnecessarily, that is a Task 159 failure.

## Trust boundary

Verified:

- Local automated suite pass/fail status.
- Prompt-cache provider behavior against live Anthropic Haiku.
- `cache: false` / `--no-cache` does not suppress provider `prompt_cache`.
- Report generation includes cache sections for real provider calls.
- Trace autoload drift behavior.
- Music `song-creator` and `chorus-chooser` free validation/dry-run/analyze-cache surfaces.
- Narrow paid `chorus-chooser --only generate-chorus-options` real run.

Assumed correct:

- Historical Stage 2 Haiku song-creator traces named in the README remain valid spec-target evidence.
- External music workflow content should not be edited during this verification pass.

Not verified:

- Full paid `song-creator` rerun.
- Full paid `chorus-chooser` run through scoring and final selection.
- MCP parity, which the README explicitly marked out of scope.

## Commands run

### Initial required reading

Read:

```bash
sed -n '1,260p' scratchpads/stage2-verification/README.md
rg -n "Progress-log reading list|RUN-HAIKU|Finding|music|song-creator|chorus-chooser" scratchpads/stage2-verification/README.md
sed -n '<referenced sections>' .taskmaster/tasks/task_159/implementation/implementation-progress-log.md
```

Purpose: establish the verification plan, trust boundaries, historical provider evidence, and paid-run criteria.

### Help and CLI surface

```bash
.venv/bin/pflow --help
```

Result: exit `0`. Confirmed relevant surfaces: `--only`, `--no-cache`, `--report`, `--validate-only`, `--dry-run`, `--output-format json`, and `analyze-cache`.

### Automated gates

Main non-e2e gate:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e"
```

Result: `6281 passed`.

Full e2e gate, as documented, failed 5 tests due sandbox/Homebrew `uv` subprocess behavior:

- `test_litellm_not_imported_by_cli_main`
- `test_progress_streams_before_downstream_nodes_complete`
- `test_cli_save_subprocess_with_overlap_exits_nonzero`
- `test_thinking_temperature_mismatch_pflow_save_subprocess_exits_nonzero`
- `test_dry_run_json_mode_emits_no_stderr`

Filtered e2e rerun excluding those sandbox-affected subprocess tests:

Result: `18 passed, 18 skipped`.

Quality checks:

```bash
.venv/bin/ruff check
.venv/bin/ruff format --check
.venv/bin/mypy src
.venv/bin/deptry src
```

Results:

- `ruff check` failed with 38 lint issues in tests, mostly `RUF043` and `RUF059`.
- `ruff format --check` passed.
- `mypy src` passed.
- `deptry src` passed.

Focused cache sweep:

Result after excluding the two sandbox/Homebrew-uv save subprocess tests: `883 passed, 2 deselected`.

### Free CLI/analyzer checks

Representative commands used:

```bash
.venv/bin/pflow guide caching
.venv/bin/pflow analyze-cache scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md --format=json
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --dry-run context="$CTX"
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --report context="$CTX"
.venv/bin/pflow analyze-cache <trace-or-workflow> --format=json
.venv/bin/pflow save <temp-workflow>
```

Additional targeted checks covered:

- `cache: false` and `--no-cache` separation.
- Memo hash stability for workflows without `prompt_cache`.
- `prewarm: true` advisory behavior in `analyze-cache` / `--dry-run`.
- Blocking errors versus recommended actions in JSON and text output.
- `--report` sections `## Cached System` and `## Cache telemetry`.
- JSON fields: `blocking_errors[]`, `recommended_actions[]`, per-call raw telemetry, node/invocation summary fields, stale field names.
- Stale trace autoload drift gate and explicit `--from-trace` bypass.
- All-memo trace cost accounting.
- Child workflow cache recommendation IDs.

### Live Anthropic Haiku provider smoke

Fresh run:

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --report --no-cache context="$CTX"
```

Result:

- Exit `0`.
- Cost `$0.0140`.
- Trace: `/Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230416.json`.
- `answer-1`: `cache_creation_input_tokens=4938`, `cache_read_input_tokens=0`.
- `answer-2` through `answer-6`: `cache_creation_input_tokens=0`, `cache_read_input_tokens=4938`.

Immediate rerun:

```bash
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --report --no-cache context="$CTX"
```

Result:

- Exit `0`.
- Cost `$0.0046`.
- Trace: `/Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230441.json`.
- All six calls had `cache_creation_input_tokens=0`, `cache_read_input_tokens=4938`.

Memo run:

```bash
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --report context="$CTX"
```

Result:

- Exit `0`.
- All six nodes came from pflow memo cache.
- Analyzer reported `actually_paid_usd: 0.0`.
- Report still showed historical per-node provider costs on cached node pages. See Finding 3.

Targeted `--only` run:

```bash
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --only answer-1 --report --no-cache context="$CTX"
```

Result:

- Exit `0`.
- Cost `$0.0008`.
- Trace: `/Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230837.json`.
- Analyzer on this trace exposed misleading partial-trace behavior. See Finding 4.

`cache: false` provider-cache separation:

```bash
.venv/bin/pflow "$tmpdir/smoke-cache-false.pflow.md" --only answer-1 --report context="$CTX"
.venv/bin/pflow "$tmpdir/smoke-cache-false.pflow.md" --only answer-1 --report context="$CTX"
```

Result:

- Both runs executed the provider call.
- Pflow memo fields remained disabled: `cached=None`, `cache_source=None`, `cache_key=None`.
- Provider cache still worked: `cache_creation_input_tokens=0`, `cache_read_input_tokens=4938`.

### Music workflow free checks

External workflow paths:

```text
/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md
/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md
```

Inputs:

```text
scratchpads/stage2-verification/song-creator/inputs.json
scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json
```

Commands run through a Python wrapper to avoid huge shell command lines:

```bash
.venv/bin/pflow <song-creator> --validate-only concept=... concept_brief=...
.venv/bin/pflow <song-creator> --dry-run concept=... concept_brief=...
.venv/bin/pflow analyze-cache <song-creator> --format=json concept=... concept_brief=...
.venv/bin/pflow analyze-cache <song-creator> concept=... concept_brief=...

.venv/bin/pflow <chorus-chooser> --validate-only concept=... creative_direction=... architecture=... creative_brief=...
.venv/bin/pflow <chorus-chooser> --dry-run concept=... creative_direction=... architecture=... creative_brief=...
.venv/bin/pflow analyze-cache <chorus-chooser> --format=json concept=... creative_direction=... architecture=... creative_brief=...
.venv/bin/pflow analyze-cache <chorus-chooser> concept=... creative_direction=... architecture=... creative_brief=...
```

Output files written under:

```text
/private/tmp/pflow-music-checks/
```

Results:

- `song-validate`: exit `0`.
- `song-dry-run`: exit `0`.
- `song-analyze-json`: exit `0`.
- `song-analyze-text`: exit `0`.
- `chorus-validate`: exit `0`.
- `chorus-dry-run`: exit `0`.
- `chorus-analyze-json`: exit `0`.
- `chorus-analyze-text`: exit `0`.

Key observed music dry-run output:

```text
Dry-run for song-creator.pflow.md: 14 nodes, 1 sub-workflow
Summary (including nested): 0 cached · 22 would execute (10 LLM, 9 code, 3 workflow)
  (10 LLM nodes without cost history)
  (19 nodes without duration history)
  ⚠ 2 opaque sub-workflows — totals above exclude their cost/duration
  ℹ [cache.opportunities-available] Cache: 25 design opportunities available.
```

```text
Dry-run for chorus-chooser.pflow.md: 8 nodes
Summary: 0 cached · 8 would execute (3 LLM, 5 code)
  ℹ [cache.opportunities-available] Cache: 2 design opportunities available.
```

### Music paid targeted sub-workflow

I did not run the full paid music pipeline. The README says existing Haiku song-creator traces already prove the spec target, and the full workflows have meaningful cost. I ran a narrow paid sub-workflow path that was below the approval threshold and specifically exercised dynamic batch/report/trace integration.

Command shape:

```bash
.venv/bin/pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --only generate-chorus-options \
  --report \
  --no-cache \
  concept=... \
  creative_direction=... \
  architecture=... \
  creative_brief=...
```

Result:

- Exit `0`.
- Duration about `30.01s`.
- Cost `$0.0669`.
- Progress: `generate-chorus-options... 8/8`.
- Trace: `/Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260506-232059.json`.
- Report: `/Users/andfal/.pflow/reports/chorus-chooser`.
- Target report: `/Users/andfal/.pflow/reports/chorus-chooser/02-generate-chorus-options/summary.md`.

Trace summary:

```text
final_status: success
nodes_executed: 2
nodes_failed: 0
llm_summary.total_calls: 8
llm_summary.total_input_tokens: 51574
llm_summary.total_output_tokens: 18053
llm_summary.models_used: ["gemini/gemini-2.5-flash-lite", "gemini/gemini-3-flash-preview"]
llm_summary.total_cost_usd: 0.066948
```

Analyzer from that trace:

```bash
.venv/bin/pflow analyze-cache /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260506-232059.json
```

Result: exit `0`, but exposed Findings 6 and 7.

## Findings

### Finding 1 - `pflow guide caching` is stale versus warning catalog

Severity: medium
Area: agent UX / documentation
Status: reproducible

Problem:

`pflow guide caching` does not mention several warning/action IDs that appear in analyzer/runtime output. Agents are instructed to use warning IDs as anchors for fixes. Missing IDs make the guide less useful exactly when an agent hits an issue.

Missing IDs observed by comparing the guide to the cache warning catalog:

```text
cache.consolidate-to-root-recommended
cache.first-call-write-penalty
cache.heterogeneous-models-fragment-cache
cache.prompt-body-duplicates-cache
cache.prompt-body-shadows-cache
llm.thinking-temperature-mismatch
```

Reproduce:

```bash
.venv/bin/pflow guide caching
rg -n "CACHE_WARNING_CATALOG|cache\\.first-call|cache\\.heterogeneous|llm\\.thinking-temperature" src tests
```

Expected:

The guide should teach every warning ID an agent is expected to act on, or clearly point to a generated/current catalog.

Actual:

The guide omits multiple live IDs.

Impact:

Agents see an analyzer or runtime warning, then the official guide lacks the matching remediation context.

### Finding 2 - Analyzer emits impossible negative savings percentages

Severity: high
Area: cost accounting / analyzer correctness
Status: reproducible

Problem:

Analyzing real Haiku rerun traces produced impossible negative savings percentages, for example:

```text
savings_pct_first_run: -845
savings_pct_rerun: -641
```

The text view hides some of these values, but JSON consumers will see them.

Reproduce:

```bash
.venv/bin/pflow analyze-cache scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230441.json \
  --format=json
```

Expected:

Savings percentages should be bounded and meaningful. If the analyzer cannot compute a trustworthy percentage, the value should be `null` with a reason.

Actual:

Negative percentages appear even when the rerun demonstrably costs less.

Impact:

Downstream agents or tools may treat the cache plan as harmful or nonsensical. This directly violates the requirement that analyzer output be agent-usable.

### Finding 3 - Memo-hit reports show historical provider costs on cached node pages

Severity: medium-high
Area: report UX / trace cost semantics
Status: reproducible

Problem:

For all-memo traces, the summary table reports cached nodes as `$0.0000`, and analyzer correctly reports `actually_paid_usd: 0.0`. However, individual cached node report pages still show historical provider costs under `Status: success [cached]`.

Reproduce:

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --report context="$CTX"
.venv/bin/pflow analyze-cache scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md --from-trace <memo-trace> --format=json
```

Observed:

- Trace: `/Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230801.json`.
- Analyzer: `actually_paid_usd: 0.0`.
- Per-node report pages still display historical costs such as `$0.0003` / `$0.0008`.

Expected:

Cached report pages should clearly separate:

- paid this run: `$0.0000`
- historical source cost, if shown at all

Actual:

Historical provider cost appears in a place that reads like current-run cost.

Impact:

Users cannot trust report cost lines without knowing internal semantics.

### Finding 4 - Partial `--only` trace analysis is misleading

Severity: high
Area: analyzer correctness / `--only` integration
Status: reproducible

Problem:

Analyzing a trace from `--only answer-1` treated the workflow as if all six LLM nodes were available and mixed executed trace data with memo/non-executed rows. It produced nonsensical negative savings and recommendations.

Reproduce:

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"
.venv/bin/pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --only answer-1 \
  --report \
  --no-cache \
  context="$CTX"

.venv/bin/pflow analyze-cache scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230837.json \
  --format=json
```

Observed:

```text
Cost: $0.0008
Trace: /Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230837.json
```

Analyzer output included:

```text
6 LLM nodes using anthropic...
Confidence: medium_from_memo (6 of 6 nodes)
savings_pct_first_run: -1825
aggregate_savings_first_run_usd: -0.004938
actionable_opportunities: 1
```

Expected:

Analyzer should explicitly identify the trace as partial, avoid whole-workflow savings claims, and avoid recommendations based on non-executed calls unless clearly marked as projections.

Actual:

The output reads like full-workflow evidence.

Impact:

`--only` is a first-class targeted testing tool. If analyzer mishandles partial traces, agents can draw the wrong conclusion from narrow verification runs.

### Finding 5 - Music `chorus-chooser` analyzer recommends a cache block that cannot fire

Severity: medium-high
Area: analyzer recommendations / agent UX
Status: reproducible

Problem:

For the real `chorus-chooser` workflow, analyzer recommends adding a `## Cache` block with only `concept.core_idea`, then says the threshold is `25 tokens / 4096` and warns the cache will not fire.

Reproduce:

```bash
.venv/bin/pflow analyze-cache /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  concept=... \
  creative_direction=... \
  architecture=... \
  creative_brief=...
```

Observed text:

```text
Shared context undeclared — declare `concept.core_idea` in ## Cache
...
## Cache
${concept.core_idea}
...
threshold: 25 tokens / 4096 (anthropic/claude-haiku-4-5) BELOW THRESHOLD — cache will not fire as suggested
```

Expected:

Do not recommend a cache block as an actionable edit if the only suggested chunk is below the provider minimum. Either suppress it, downgrade it, or explain that no provider-cache edit is currently useful.

Actual:

Analyzer gives a concrete edit and immediately undercuts it.

Impact:

An agent following the recommendation would add non-functional cache configuration.

### Finding 6 - Paid dynamic batch trace has useful per-item telemetry, but analyzer model accounting is wrong

Severity: high
Area: dynamic batch / analyzer JSON correctness
Status: reproducible

Problem:

The paid `chorus-chooser --only generate-chorus-options` run used Gemini models. Trace telemetry correctly recorded that. Analyzer JSON from the same trace reported `models_in_use: ["anthropic/claude-haiku-4-5"]`, and the executed `generate-chorus-options` per-call row had `model: ""`.

Reproduce:

Run:

```bash
.venv/bin/pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --only generate-chorus-options \
  --report \
  --no-cache \
  concept=... \
  creative_direction=... \
  architecture=... \
  creative_brief=...
```

Then:

```bash
.venv/bin/pflow analyze-cache /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260506-232059.json \
  --format=json
```

Observed trace truth:

```text
llm_summary.models_used:
  gemini/gemini-2.5-flash-lite
  gemini/gemini-3-flash-preview
llm_summary.total_cost_usd: 0.066948
batch_items[*].llm_call contains model, tokens, cost_usd, cache telemetry.
```

Observed analyzer JSON:

```text
summary.models_in_use: ["anthropic/claude-haiku-4-5"]
per_call[generate-chorus-options].model: ""
per_call[generate-chorus-options].cost_usd: 0.06694800000000001
```

Expected:

Analyzer should surface the actual traced batch models or explicitly mark the row as heterogeneous with the concrete model set.

Actual:

Analyzer combines the real cost with the wrong model summary.

Impact:

Prompt-cache behavior is exact-model scoped. Wrong model accounting directly undermines cache analysis.

### Finding 7 - `--only` plus multi-output workflow streams a skipped output and dumps huge intermediate JSON

Severity: medium
Area: CLI UX / `--only` output routing
Status: reproducible

Problem:

The paid `chorus-chooser --only generate-chorus-options` run stopped before declared workflow outputs were produced. CLI warned it was streaming `winning_chorus`, but stdout contained a very large JSON-like intermediate object from `generate-chorus-options`, including full prompts.

Reproduce:

```bash
.venv/bin/pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --only generate-chorus-options \
  --report \
  --no-cache \
  concept=... \
  creative_direction=... \
  architecture=... \
  creative_brief=...
```

Observed stderr:

```text
Workflow declares 6 outputs (winning_chorus, runner_up_choruses, all_scored_text, selection_text, chorus_guide, total_generated). Streaming 'winning_chorus' to stdout.
```

Observed stdout:

Huge JSON-ish object containing `items`, full generated prompts, and `cd_summary`.

Expected:

For `--only`, if the chosen/default output is skipped or unavailable, CLI should say that and either:

- stream the target node output with a clear label, or
- require `-o`, or
- print no stdout unless `--output-format json` is requested.

Actual:

The warning claims one output, while stdout contains another.

Impact:

This is confusing and can leak huge prompt bodies into stdout unexpectedly.

### Finding 8 - Warning-only runtime executions exit with code 2

Severity: medium
Area: CLI contracts / scripting UX
Status: reproducible

Problem:

Some successful executions with cache warnings exited `2`, even though the workflow completed.

Reproduce:

Tiny below-min cache workflow:

```bash
.venv/bin/pflow "$tmpdir/tiny-cache.pflow.md" --report --no-cache
```

Skipped branch fixture:

```bash
.venv/bin/pflow scratchpads/segment3-verification/A5-absent-chunk-via-branching.pflow.md --report --no-cache route=A
```

Observed:

- Workflow completed with warnings.
- Exit code `2`.
- Report status may be `degraded`.

Expected:

If this is intentional, documentation and CLI wording should make clear that warnings are nonzero exits. If not intentional, warning-only successful runs should exit `0`.

Actual:

The behavior is surprising for script users.

Impact:

Automation may treat warning-only prompt-cache advisories as hard failures.

### Finding 9 - Skipped branch analysis/reporting has confusing context

Severity: medium
Area: branch integration / analyzer UX
Status: reproducible

Problem:

The skipped-branch fixture correctly records `cache_chunks_skipped`, but warning/analyzer context is noisy or wrong.

Reproduce:

```bash
.venv/bin/pflow scratchpads/segment3-verification/A5-absent-chunk-via-branching.pflow.md --report --no-cache route=A
.venv/bin/pflow analyze-cache scratchpads/segment3-verification/A5-absent-chunk-via-branching.pflow.md --from-trace /Users/andfal/.pflow/debug/workflow-trace-e3bef1bb-A5-absent-chunk-via-branching-20260506-231045.json --format=json
```

Good observed behavior:

```text
cache_chunks_skipped: ["path-b.stdout"]
Report shows: Skipped chunks (resolved as ABSENT): path-b.stdout
Analyzer emits cache.discrepancy with root_cause: chunk_skipped
```

Bad observed behavior:

- Runtime warnings include a warning for `path-b`, even though that branch did not execute.
- Analyzer discrepancy message uses the workflow path where the JSON trace path is expected.
- Analyzer leaks tiny negative first-run savings for an under-threshold case.

Expected:

Non-executed branches should not produce runtime warnings that read like executed-node problems. Trace context fields should be named and populated accurately.

Actual:

The user sees both useful skipped-chunk evidence and confusing unrelated warnings/context.

Impact:

Branching workflows are exactly where prompt-cache chunk absence matters; confusing context makes fixes harder.

### Finding 10 - `cache.sub-workflow-cache-undeclared` suggestion wording uses `$shared_doc`

Severity: low-medium
Area: agent UX / suggested edit text
Status: reproducible

Problem:

A child sub-workflow cache recommendation uses `$shared_doc` instead of the pflow template syntax `${shared_doc}`.

Reproduce:

Run the child workflow cache recommendation fixture from the README/manual checks:

```bash
.venv/bin/pflow analyze-cache <child-subworkflow-cache-fixture>
```

Observed:

Suggested text contains `$shared_doc`.

Expected:

Suggested edit text should use exact pflow syntax: `${shared_doc}`.

Actual:

The recommendation uses stale or shell-like syntax.

Impact:

Small but important: agents may copy the wrong syntax.

### Finding 11 - `analyze-cache` JSON can lose workflow identity and use `<unknown>`

Severity: low-medium
Area: analyzer JSON / context quality
Status: reproducible

Problem:

`analyze-cache` on an order-mismatch fixture emitted `cache.prompt-body-duplicates-cache` with `scope_workflow: "<unknown>"`, even though the workflow path was known.

Reproduce:

```bash
.venv/bin/pflow analyze-cache scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md --format=json
```

Observed:

```text
scope_workflow: "<unknown>"
message mentions "test-call in <unknown>"
```

Expected:

Known workflow path or basename should be preserved.

Actual:

The analyzer loses identity.

Impact:

Multi-workflow analysis becomes harder to act on.

### Finding 12 - Dry-run cache nudge and actions can render negative-signed savings

Severity: medium
Area: cost UX
Status: reproducible

Problem:

Some dry-run/analyzer outputs render negative-signed dollar amounts in phrases that otherwise say "saves".

Observed examples:

```text
estimated -$0.0036/run
-$0.0016/run
```

Expected:

Do not label a negative delta as savings. Use "added first-run cost", "write premium", or suppress if the recommendation is not beneficial.

Actual:

The wording mixes negative signs with savings language.

Impact:

Agents cannot tell whether an edit saves money or costs money.

## Positive results

The following checks passed and are important:

- Real Anthropic Haiku provider cache writes and reads are present and cost reductions were observed.
- `cache: false` and `--no-cache` only disable pflow memo reads; provider cache still renders.
- Anthropic thinking plus static `temperature != 1.0` fails validation with `llm.thinking-temperature-mismatch`.
- Invalid TTL like `1m` gives a clear parse error.
- Stale trace autoload is drift-aware; explicit `--from-trace` bypasses the gate.
- Analyzer reports all-memo traces as known zero paid cost.
- Blocking errors and recommended actions are separately represented in JSON for tested fixtures.
- Batch summary distinguishes node count from invocation count for static and dynamic batch cases.
- Paid dynamic batch trace stores useful per-item raw telemetry in `batch_items[*].llm_call` and `node_output.results[*].llm_usage`.

## Paid-run decision

I did not run full paid `song-creator` or full paid `chorus-chooser`.

Reasoning:

- The README explicitly says historical Haiku `RUN-HAIKU-FINAL` and `RUN-HAIKU-RERUN` already prove the spec target.
- Full `song-creator` is estimated around `$0.20-$0.86`, and the README says not to spend that unless runtime rendering, telemetry, cost accounting, or the external workflow changed in a way that requires fresh evidence.
- Free music checks already exposed analyzer/UX issues.
- A narrow paid `chorus-chooser --only generate-chorus-options` run cost `$0.0669` and added current-workflow evidence at dynamic-batch/report/trace boundaries.

Total paid spend:

```text
Anthropic Haiku fresh smoke:       ~$0.0140
Anthropic Haiku rerun smoke:       ~$0.0046
Anthropic Haiku --only smoke:      ~$0.0008
cache:false two-call check:        ~$0.0015
tiny below-min live check:         small, included in total estimate
chorus-chooser --only batch smoke:  $0.0669
Total:                             ~$0.088 / $4.00
```

## Recommended fix priorities

1. Fix analyzer math invariants: no impossible negative savings percentages; no "savings" wording for added cost.
2. Make partial `--only` traces first-class: mark partial traces, avoid full-workflow confidence claims, and separate executed trace evidence from projections.
3. Fix model accounting for dynamic heterogeneous batch traces.
4. Clarify report cost semantics for memo hits: paid-this-run versus historical source cost.
5. Suppress or downgrade below-threshold cache block suggestions when no suggested chunk can provider-cache.
6. Update `pflow guide caching` from the live warning catalog or generate the warning section from source.
7. Fix `--only` output routing when declared workflow outputs are skipped.
8. Decide and document whether warning-only successful executions should exit nonzero.

## Final assessment

The core prompt-cache provider path works. The remaining failures are not superficial: they affect whether agents can trust the analyzer, reports, and suggested edits. Because prompt caching is primarily an agent-facing cost/performance feature, misleading recommendations and wrong model/cost summaries should be treated as release blockers or at least as required follow-up fixes before marking Task 159 fully complete.
