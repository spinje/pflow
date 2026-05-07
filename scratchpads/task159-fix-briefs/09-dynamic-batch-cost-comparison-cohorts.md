# Task 159 Fix Brief 09 — Dynamic Batch Cost Comparison Cohorts

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/POST-FIX-CLOSURE-REPORT.md`

## Purpose

This brief captures a remaining analyzer cost-semantics issue around complete
traces that include heterogeneous dynamic batch rows.

The next agent should research the current cost model and trace indexing before
editing. The likely problem is a cohort mismatch: actual trace cost includes
dynamic heterogeneous batch calls, while no-cache projections exclude them.
Confirm this in code and tests before selecting a fix.

Final-code simplicity matters more than a tiny patch. The right solution should
make it hard for future agents to compare unlike cost cohorts by accident.

## Issue Covered

Post-fix closure Issue 2:

> Complete dynamic-batch trace can compare actual full cost to a partial
> hypothetical.

Severity in closure report: medium-high
Area: analyzer cost semantics / dynamic heterogeneous batch

## Plain-Language Problem

The analyzer now correctly preserves observed models and call counts for
dynamic batch traces. However, one aggregate cost comparison can still be
misleading.

For the full successful `chorus-chooser` trace:

- `actually_paid_usd` includes all traced LLM calls, including the dynamic batch
  node `generate-chorus-options`.
- `no_cache_hypothetical_usd` appears to exclude that heterogeneous dynamic
  batch row because it cannot be priced as one static model.
- `actual_vs_no_cache_delta` then compares the full actual cost to a partial
  no-cache hypothetical.

That produces a cost increase equal to the dynamic batch row's actual cost. The
math is internally explainable, but the UX is not honest because it compares
different cohorts.

## Current Evidence

From `scratchpads/stage2-verification/POST-FIX-CLOSURE-REPORT.md`:

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

The closure report notes that `0.0652472` equals the traced cost of
`generate-chorus-options`. That strongly suggests:

- actual cost includes `generate-chorus-options`;
- no-cache hypothetical excludes `generate-chorus-options`;
- the delta compares unlike sets.

Trust boundary:

- The full `chorus-chooser` run completed successfully and produced a complete
  trace.
- The analyzer's observed model set and call counts were positive verification
  results.
- This issue is only about aggregate cost comparison semantics.

## Reproduction

Real trace from closure verification:

```text
/Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260507-131010.json
```

Workflow:

```text
/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md
```

Analyze:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260507-131010.json \
  --format=json
```

Do not rerun providers unless the user approves. The existing trace should be
enough for most investigation.

If the external trace is unavailable, build a synthetic trace fixture with:

- one static LLM row that can be projected;
- one dynamic heterogeneous batch row with observed trace cost and observed
  models;
- complete trace coverage.

Expected reproduction signal:

- `trace_coverage = "complete"`;
- heterogeneous row appears in actual trace cost;
- projection excludes the heterogeneous row;
- `actual_vs_no_cache_delta` compares those two totals instead of becoming
  unavailable/partial or cohort-aligned.

## Most Relevant Code Areas

Start here:

- `src/pflow/core/cache_analysis/analyze.py`
  - `PerCallRow.model_is_heterogeneous`
  - `PerCallRow.observed_models`
  - `_build_trace_execution_index(...)`
  - `_build_per_call_row(...)`
  - `_build_summary(...)`
  - `_cost_delta(...)`
- `src/pflow/core/cache_analysis/cost_estimation.py`
  - `compute_projections(...)`
  - `_partition_priced_rows(...)`
  - `compute_actually_paid(...)`
- `src/pflow/core/cache_analysis/render_json.py`
  - summary delta fields
- `src/pflow/core/cache_analysis/render_text.py`
  - summary cost/delta text
- `src/pflow/core/trace_tree.py`
  - current-run actual cost leaves

Current code orientation:

- `compute_projections()` excludes rows where `row.model_is_heterogeneous`.
- `compute_actually_paid()` prefers trace truth and can include all leaves.
- `_build_summary()` computes `actual_vs_no_cache_delta` when
  `trace_coverage == "complete"` by comparing `projections.no_cache_hypothetical_usd`
  to `actually_paid.total_usd`.
- Complete trace coverage currently does not imply projection coverage.

## Relevant Progress-Log Context

Read these sections from
`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`:

- `Stage 2 follow-up — partial trace evidence scope + dynamic batch model truth`
  - Recent fix that preserved observed model sets and call counts.
  - Important: do not regress this verified behavior.
- `Post-segment-4 follow-up: cost wiring + honest loose-ends audit`
  - Introduced the tri-state cost contract.
  - Explains priced / partial / unavailable.
- `Cost-projection fix: Tracks A + B + C`
  - Separates actual trace cost from hypothetical projections.
- `Stage 2 follow-up — Findings #11/#12: post-review fixes`
  - "Honest-unmeasurable beats approximate-and-overstating."
  - Precise math should skip when evidence is not available.
- `Stage 2 follow-up — Findings #9/#10 + phantom-savings: unified below-min-token detection`
  - Reinforces provider/cache granularity and avoiding phantom savings.
- `Stage 2 follow-up — Finding #17: all-memo trace cost is known zero`
  - Current-run actual cost comes from `TraceTree`.
- `POST-FIX-CLOSURE-REPORT.md` Issue 2
  - Source of current evidence.

Also read:

- `src/pflow/core/cache_analysis/CLAUDE.md`
  - cost-estimation and trace-contract sections.

## Research Questions

Answer these before implementing:

1. Which rows are included in:
   - `actually_paid_usd`;
   - `no_cache_hypothetical_usd`;
   - `first_run_with_cache_hypothetical_usd`;
   - `rerun_within_ttl_hypothetical_usd`;
   - `actual_vs_no_cache_delta`?
2. Does `ProjectionBreakdown.partial` currently indicate excluded heterogeneous
   rows, or only rows missing output tokens / pricing among priced rows?
3. Is there a clean way to compute no-cache hypothetical for observed dynamic
   batch calls from trace leaves using their concrete observed models?
4. If not, should aggregate actual-vs-hypothetical comparisons become
   unavailable whenever projections exclude any cost-bearing trace rows?
5. Should per-call rows expose enough information to explain which row caused
   projection unavailability?
6. Should text output explicitly say "actual-vs-no-cache unavailable because
   dynamic heterogeneous batch rows are not projected"?

## Design Options to Discuss

Option A: honest nullability / partial comparison suppression.

- If actual cost includes rows excluded from projections, set
  `actual_vs_no_cache_delta` unavailable with a reason.
- Possibly mark aggregate projections as partial/unavailable.
- Lower implementation risk and aligns with "honest unmeasurable".

Option B: cohort-align by excluding heterogeneous actual cost from
`actual_vs_no_cache_delta`.

- Compare only rows projected on both sides.
- Must clearly label "projected subset", or agents may think it is full-run.
- Risk: easy to create another partial-truth UX if not labeled well.

Option C: project dynamic heterogeneous batch from observed trace leaves.

- Use concrete observed per-item/per-call models and tokens to compute
  no-cache hypothetical for the dynamic batch.
- Most complete, but likely larger and brownfield-only.
- Need careful separation from greenfield/static projections.

The fixing agent should recommend one after reading code. The default
preference should be the simplest final semantic model, not the smallest diff.

## Desired UX Properties

- No aggregate delta compares full actual cost to partial hypothetical cost
  without saying so.
- Complete trace coverage does not imply complete projection coverage unless
  all cost-bearing rows are included in both sides.
- If dynamic heterogeneous rows cannot be projected, the analyzer says so
  directly and uses `null`/unavailable for incompatible aggregate comparisons.
- Observed model truth and call counts from the recent fix remain intact.
- Text and JSON tell the same story.

## Verification Expectations

Add a regression test for complete trace coverage with a heterogeneous dynamic
batch row whose trace cost is nonzero.

Assertions should cover:

- observed models are preserved;
- observed call count is preserved;
- `actual_vs_no_cache_delta` is not a misleading full-run cost increase caused
  by excluding the same row from projections;
- text output makes the limitation visible if the comparison is unavailable or
  partial.

Likely test files:

- `tests/test_core/test_cache_analysis_analyze.py`
- `tests/test_core/test_cache_analysis_renderers.py`
- possibly `tests/test_core/test_cache_analysis_cost_estimation.py`

Manual check against the closure trace if available:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260507-131010.json
```

## Non-Goals

- Do not rerun the paid external workflow unless the user explicitly approves.
- Do not regress partial trace evidence suppression from brief 02.
- Do not start Task 160 structural refactor.
- Do not solve every future dynamic-model projection case unless the research
  shows the final model stays simple.

