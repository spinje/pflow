# Task 159 Post-Fix Closure Verification

Verification date: 2026-05-07
Verifier: Codex
Repo: `/Users/andfal/projects/pflow-feat-prompt-caching`
External workflow repo inspected/executed: `/Users/andfal/projects/music-generation/workflows/lyrics-generator/`

## Executive Summary

Task 159 is substantially improved from the final verification report, but I
would not call this PR merge-ready without either fixing or explicitly accepting
the issues below.

Provider prompt caching is mechanically verified on the real music workflow:
the full `song-creator` run reached 52 LLM calls before a downstream review
timeout, and the trace recorded provider cache writes/reads:

- `cache_creation_input_tokens` total: `25949`
- `cache_read_input_tokens` total: `79705`
- models observed: `anthropic/claude-haiku-4-5`, `gemini/gemini-2.5-flash-lite`,
  `gemini/gemini-3-flash-preview`

The fixes from briefs 01-05 are also visible in current output:

- No impossible negative savings percentages on the checked-in Haiku rerun trace.
- Partial trace analysis is labeled as partial and suppresses workflow-design recommendations.
- Dynamic batch trace analysis preserves concrete observed model sets and call counts.
- Memo-hit report pages now use `Paid this run` / source-cost semantics on current pages.
- `--only` target routing and degraded-success exit policy are implemented.
- Below-threshold suggestions are no longer rendered as paste-ready cache blocks.
- Sub-workflow cache suggestions render exact pflow syntax such as `${concept}`.
- `pflow guide caching` lists all 20 live catalog IDs.

Remaining blockers are mostly report hygiene, analyzer cost semantics around
heterogeneous dynamic batches, static lint, and the external music workflow
timeout.

## Issues Found

### Issue 1 — Failed reports can retain stale per-node pages from older runs

Severity: high
Area: report UX / correctness
Status: reproducible in this verification pass

The full `song-creator` provider run failed at node `craft-reviews`, and the
new `summary.md` correctly reports only 10 executed nodes and `Status: failed`.
However, the report directory still contains downstream node pages from an older
successful run.

Evidence:

```text
new summary:
/Users/andfal/.pflow/reports/song-creator/summary.md
mtime: 2026-05-07 13:19:55

stale pages:
/Users/andfal/.pflow/reports/song-creator/11-format-craft-reviews.md
mtime: 2026-05-05 11:52:44

/Users/andfal/.pflow/reports/song-creator/14-generate-suno-prompt.md
mtime: 2026-05-05 11:52:44
```

Impact:

An agent inspecting `/Users/andfal/.pflow/reports/song-creator` after a failed
run can open pages for nodes that did not execute in the current run. Some stale
pages show successful LLM calls, prompts, cached systems, and costs, which can
contradict the current summary.

Expected:

Report generation should either clear the target report directory before
writing a new run, write to a unique run-specific report path, or mark/remove
stale pages so they cannot be mistaken for current-run evidence.

### Issue 2 — Complete dynamic-batch trace can compare actual full cost to a partial hypothetical

Severity: medium-high
Area: analyzer cost semantics / dynamic heterogeneous batch
Status: reproducible in this verification pass

Analyzing the successful full `chorus-chooser` trace showed correct model truth,
but the summary reported actual-vs-no-cache as a cost increase:

```json
{
  "actually_paid_usd": 0.2878332,
  "no_cache_hypothetical_usd": 0.222586,
  "actual_vs_no_cache_delta": {
    "amount_usd": 0.0652472,
    "kind": "cost_increase"
  },
  "heterogeneous_model_node_paths": ["generate-chorus-options"]
}
```

The delta amount equals the traced cost of `generate-chorus-options`
(`0.0652472`). That suggests the no-cache hypothetical excluded the
heterogeneous dynamic batch row while `actually_paid_usd` included it.

Impact:

For a complete trace with no declared provider cache in `chorus-chooser`, a
reader can be told the actual run cost more than "no cache" even though the
comparison appears to be across different row sets. This is the same class of
truthfulness issue Task 159 has been closing: a cost delta must compare like
with like, or be `null` with a reason.

Expected:

If heterogeneous dynamic rows are excluded from projections, aggregate fields
that compare projections with actual trace cost should either exclude the same
rows from both sides or render `unavailable` with an explicit reason.

### Issue 3 — `trace_unexecuted_llm_nodes` is ambiguous for multi-workflow traces

Severity: low-medium
Area: analyzer JSON / multi-workflow context
Status: reproducible in this verification pass

The failed `song-creator` trace analysis correctly entered partial evidence
mode, but `summary.trace_unexecuted_llm_nodes` listed repeated bare node IDs:

```json
[
  "generate-suno-prompt",
  "review",
  "review",
  "review",
  "review",
  "review",
  "review",
  "review",
  "review",
  "review",
  "rewrite-craft"
]
```

The repeated `review` entries come from different child review workflows.
Detailed `per_call` rows include workflow paths, but the summary field does not.

Impact:

This is not as severe as stale reports or wrong cost deltas, but it weakens the
agent-facing JSON contract for multi-workflow traces. A summary-level consumer
cannot tell which child workflows did not execute without joining against
`per_call`.

Expected:

Summary unexecuted-node fields should include disambiguating workflow path or
node path, or use objects rather than bare node IDs for cross-workflow analyses.

### Issue 4 — Full `song-creator` music workflow does not complete end to end

Severity: medium
Area: external workflow / provider runtime readiness
Status: reproducible in this verification pass

The full provider-backed `song-creator` run was explicitly approved by the user
and executed with `--report --no-cache`. It failed after about 9 minutes:

```text
exit=1
WorkflowExecutor failed at .../reviews/review-rhyme.pflow.md
Sub-workflow failed ... node 'review':
LLM call timed out after 120.0s.
Model: anthropic/claude-haiku-4-5.
At: node 'craft-reviews'
```

Trace:

```text
/Users/andfal/.pflow/debug/workflow-trace-40235f89-song-creator-20260507-131955.json
```

Report:

```text
/Users/andfal/.pflow/reports/song-creator
```

Trace summary:

```json
{
  "final_status": "failed",
  "nodes_executed": 10,
  "nodes_failed": 1,
  "failed_node_ids": ["craft-reviews"],
  "llm_summary": {
    "total_calls": 52,
    "total_input_tokens": 321252,
    "total_output_tokens": 87988,
    "total_cost_usd": 0.609526
  }
}
```

This appears to be an external workflow timeout configuration issue: the
`review-rhyme.pflow.md` review node has no explicit `timeout`, so it uses the
default 120s. It may not be a Task 159 code bug, but it blocks the requested
full music-generation end-to-end verification.

### Issue 5 — Static lint gate is not clean

Severity: medium
Area: release hygiene
Status: reproducible

`ruff check` fails with 38 issues in tests. The failures are mostly `RUF043`
and `RUF059`, matching the prior final verification report.

Representative files:

- `tests/test_execution/test_workflow_resolver_contract.py`
- `tests/test_mcp_server/test_execution_workflow.py`
- `tests/test_mcp_server/test_plan_workflow.py`
- `tests/test_runtime/test_instrumented_wrapper.py`
- `tests/test_runtime/test_prepare_inputs_coercion.py`
- `tests/test_runtime/test_trace_integration.py`

Other static checks pass:

- `ruff format --check`: passed
- `mypy src`: passed
- `deptry src`: passed

## Positive Verification Results

### Guide and catalog

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow guide caching
```

Result: exit `0`.

Observed:

- Guide clearly distinguishes pflow memo cache from provider prompt caching.
- `--no-cache` is documented as memo-layer only.
- TTL docs list only `5m` and `1h`.
- The guide's warning-ID table includes all 20 live catalog IDs:
  `cache.*` IDs plus `llm.thinking-temperature-mismatch`.

### Haiku rerun trace cost semantics

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace scratchpads/stage2-verification/anthropic-haiku/RUN-C-rerun-trace.json \
  --format=json
```

Result: exit `0`.

Observed:

```json
{
  "actually_paid_usd": 0.0046188,
  "no_cache_hypothetical_usd": 0.031284,
  "first_run_with_cache_hypothetical_usd": 0.014001,
  "rerun_within_ttl_hypothetical_usd": 0.0046188,
  "first_run_delta": {"kind": "savings", "pct_of_baseline": 55},
  "rerun_delta": {"kind": "savings", "pct_of_baseline": 85},
  "actual_vs_no_cache_delta": {"kind": "savings", "pct_of_baseline": 85}
}
```

This fixes the prior impossible negative percentage behavior and the
Anthropic trace token double-counting.

### Partial trace evidence

Used a synthetic one-node partial trace derived from the checked-in Haiku rerun
trace.

Result: exit `0`.

Observed:

- `summary.trace_coverage = "partial"`
- `summary.evidence_scope = "partial_trace_executed_subset"`
- `trace_llm_nodes_executed = 1`
- `trace_llm_nodes_static = 6`
- `recommended_actions = []`
- `suggested_blocks = []`
- Text says: `Evidence: partial trace (1 of 6 LLM nodes executed)`
- Text says: `Workflow-design recommendations suppressed for partial trace evidence.`

### Order-mismatch fixture

Command:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md \
  --format=json a=hello b=world
```

Result: exit `0`.

Observed:

- `blocking_errors[]` contains `cache.order-mismatch` and
  `cache.prompt-body-duplicates-cache`.
- `scope_workflow` is the actual workflow path, not `<unknown>`.
- Text separates blocking errors from recommended actions.

### Music workflow free checks

Commands were run through a Python wrapper using checked-in JSON inputs.

Results:

- `song-creator --validate-only`: exit `0`
- `song-creator --dry-run`: exit `0`
- `chorus-chooser --validate-only`: exit `0`
- `chorus-chooser --dry-run`: exit `0`
- `song-creator analyze-cache --format=json`: exit `0`
- `song-creator analyze-cache` text: exit `0`
- `chorus-chooser analyze-cache --format=json`: exit `0`
- `chorus-chooser analyze-cache` text: exit `0`

Observed:

- `chorus-chooser` now renders only `cache.opaque-prompt` as an actionable
  recommendation.
- The prior below-threshold `concept.core_idea` paste-ready suggested block is
  suppressed.
- Notes explain that shared refs were found but no paste-ready provider-cache
  edit is actionable under current model/token evidence.
- `song-creator` sub-workflow cache recommendation uses `${concept}` for the
  child `## Cache` syntax and bare `concept` for child `prompt_cache:`.

### Full `chorus-chooser` provider run

Command shape:

```bash
.venv/bin/pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --report --no-cache \
  concept=... creative_direction=... architecture=... creative_brief=...
```

Result: exit `0`.

Output:

```text
Workflow completed in 90.559s
Cost: $0.2878
Trace: /Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260507-131010.json
Report: /Users/andfal/.pflow/reports/chorus-chooser
```

Trace summary:

```json
{
  "final_status": "success",
  "nodes_executed": 8,
  "nodes_failed": 0,
  "llm_summary": {
    "total_calls": 43,
    "total_input_tokens": 104205,
    "total_output_tokens": 51510,
    "models_used": [
      "anthropic/claude-haiku-4-5",
      "gemini/gemini-2.5-flash-lite",
      "gemini/gemini-3-flash-preview"
    ],
    "total_cost_usd": 0.287833
  }
}
```

Analyzer on the trace:

- `trace_coverage = "complete"`
- `evidence_scope = "complete_trace"`
- `observed_models_in_trace` includes Haiku and both Gemini models.
- `generate-chorus-options.observed_call_count = 8`
- `score-choruses.observed_call_count = 34`
- `select-chorus.observed_call_count = 1`
- `recommended_actions` contains only `cache.opaque-prompt`.

See Issue 2 for the aggregate cost-comparison problem on this same trace.

### Full `song-creator` provider run

Command shape:

```bash
.venv/bin/pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md \
  --report --no-cache concept=... concept_brief=...
```

Result: exit `1`.

The run did not complete end to end because `review-rhyme` timed out, but it
did verify the root provider prompt-cache path against the real external
workflow before failing:

```json
{
  "llm_call_count": 52,
  "cache_creation_sum": 25949,
  "cache_read_sum": 79705,
  "total_cost_usd": 0.609526
}
```

## Automated Gates

Focused cache sweep, first run:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest <focused cache files>
```

Result:

```text
900 passed, 2 failed
```

The two failures were the known sandbox/Homebrew `uv` subprocess tests:

- `test_cli_save_subprocess_with_overlap_exits_nonzero`
- `test_thinking_temperature_mismatch_pflow_save_subprocess_exits_nonzero`

Focused cache sweep excluding e2e subprocess tests:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -m "not e2e" <focused cache files>
```

Result:

```text
900 passed, 2 deselected
```

Full non-e2e sandbox gate:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -m "not e2e"
```

Result:

```text
6306 passed
```

Full e2e sandbox gate:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 \
  --dist=worksteal \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -m e2e
```

Result:

```text
5 failed, 18 passed, 18 skipped
```

The five failures are the known sandbox/Homebrew subprocess failures:

- `test_litellm_not_imported_by_cli_main`
- `test_progress_streams_before_downstream_nodes_complete`
- `test_cli_save_subprocess_with_overlap_exits_nonzero`
- `test_thinking_temperature_mismatch_pflow_save_subprocess_exits_nonzero`
- `test_dry_run_json_mode_emits_no_stderr`

Filtered e2e rerun excluding those five:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 \
  --dist=worksteal \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -m e2e \
  -k "not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete and not test_cli_save_subprocess_with_overlap_exits_nonzero and not test_thinking_temperature_mismatch_pflow_save_subprocess_exits_nonzero"
```

Result:

```text
18 passed, 18 skipped
```

Static checks:

```bash
.venv/bin/ruff check
.venv/bin/ruff format --check
.venv/bin/mypy src
.venv/bin/deptry src
```

Results:

- `ruff check`: failed with 38 test lint issues.
- `ruff format --check`: passed.
- `mypy src`: passed.
- `deptry src`: passed.

## Paid Provider Spend This Pass

Approximate provider spend from this verification pass:

```text
full chorus-chooser run: $0.2878
full song-creator failed run: $0.6095
total: $0.8973
```

The user explicitly approved sending local music workflow content and inputs to
external LLM providers before these paid runs were attempted.

## Trust Boundary

Verified:

- Current source behavior for the free CLI/analyzer/guide checks listed above.
- Current provider behavior for standalone `chorus-chooser`.
- Provider prompt-cache writes/reads in a real `song-creator` partial failed run.
- Current sandbox automated gate status.
- Current report-directory stale-file behavior after a failed `song-creator` run.

Assumed:

- Homebrew `uv` e2e failures are sandbox-specific, matching prior reports and
  the repository's `pflow-sandbox-testing` skill.
- `review-rhyme` timeout is an external workflow timeout/default issue, not a
  Task 159 prompt-cache implementation bug.

Unable to verify:

- A fully successful end-to-end `song-creator` run through
  `generate-suno-prompt`; it timed out in the `craft-reviews` batch.
- A provider rerun of full `song-creator` within TTL after a successful full
  first run, because the first run did not complete.

## Merge Readiness Assessment

Task 159 is not cleanly merge-ready yet unless the team explicitly accepts the
remaining issues.

Recommended minimum before merge:

1. Fix report directory staleness after failed or partial runs.
2. Fix or null aggregate cost comparisons when heterogeneous dynamic batch rows
   are excluded from projections.
3. Decide whether duplicate bare node IDs in `trace_unexecuted_llm_nodes` are
   acceptable for this PR or should be changed to workflow-scoped entries.
4. Fix or explicitly defer the external `review-rhyme` timeout before claiming
   full music-generation end-to-end verification.
5. Clean `ruff check` or explicitly accept the unrelated test lint failures.

Task 160 should not start until the behavior issues above are fixed or
explicitly deferred by the user.
