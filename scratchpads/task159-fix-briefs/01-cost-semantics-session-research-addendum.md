# Task 159 Cost Semantics Session Research Addendum

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Read together with: `scratchpads/task159-fix-briefs/01-cost-semantics-negative-savings.md`

## Purpose

This addendum records what was verified in the follow-up research session after
reading Fix Brief 01. It intentionally does not restate the original brief's
background. It adds:

- exact reproduction results from checked-in Haiku traces,
- the newly identified Anthropic trace token-accounting mismatch,
- partial-trace behavior observed from a synthetic `--only`-shaped trace,
- design implications and trust boundaries for the next implementation agent.

## Files Read In This Session

Verified:

- `scratchpads/task159-fix-briefs/01-cost-semantics-negative-savings.md`
- `scratchpads/stage2-verification/README.md`
- `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`
- `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`
  - sections listed by Fix Brief 01
- `src/pflow/core/cache_analysis/CLAUDE.md`
- `src/pflow/core/cache_analysis/analyze.py`
  - `AnalysisSummary`
  - `_build_summary`
  - `_safe_pct_or_none`
  - `_build_per_call_rows_and_warnings`
  - `_per_node_warnings`
  - `_build_trace_execution_index`
  - `_estimate_row_tokens`
  - suggested-block / threshold helpers
- `src/pflow/core/cache_analysis/cost_estimation.py`
  - `compute_projections`
  - `compute_actually_paid`
  - `_aggregate_first_run_savings`
  - `_aggregate_rerun_savings`
- `src/pflow/core/cache_analysis/render_text.py`
- `src/pflow/core/cache_analysis/render_json.py`
- `src/pflow/core/cache_analysis/view_helpers.py`
- `src/pflow/core/cache_analysis/summarize.py`
- `src/pflow/core/cache_analysis/warning_catalog.py`
- `src/pflow/core/cache_analysis/below_min_tokens_detector.py`
- `src/pflow/core/llm_client.py`
  - `_normalize`
  - `_maybe_normalize_anthropic_1h_cost`
- `src/pflow/core/llm_providers.py`
- `src/pflow/runtime/workflow_trace.py`
- selected tests:
  - `tests/test_core/test_cache_analysis_analyze.py`
  - `tests/test_core/test_cache_analysis_cost_estimation.py`
  - `tests/test_core/test_cache_analysis_summarize.py`
  - `tests/test_core/test_cache_analysis_renderers.py`
  - `tests/test_core/test_cache_analysis_warnings.py`

## Reproduction: Checked-In Haiku Traces

The original brief references live traces under `~/.pflow`. This session used
checked-in traces instead, avoiding provider spend:

- `scratchpads/stage2-verification/anthropic-haiku/RUN-B-with-cache-trace.json`
- `scratchpads/stage2-verification/anthropic-haiku/RUN-C-rerun-trace.json`
- workflow:
  `scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md`

Commands:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace scratchpads/stage2-verification/anthropic-haiku/RUN-B-with-cache-trace.json \
  --format=json | jq '.summary'

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace scratchpads/stage2-verification/anthropic-haiku/RUN-C-rerun-trace.json \
  --format=json | jq '.summary'
```

Observed for `RUN-B-with-cache-trace.json`:

```json
{
  "actually_paid_usd": 0.023947,
  "no_cache_hypothetical_usd": 0.060982,
  "first_run_with_cache_hypothetical_usd": 0.043699,
  "rerun_within_ttl_hypothetical_usd": 0.0343168,
  "savings_pct_first_run": -82,
  "savings_pct_rerun": -43,
  "aggregate_savings_first_run_usd": 0.017283,
  "aggregate_savings_rerun_usd": 0.0266652
}
```

Observed for `RUN-C-rerun-trace.json`:

```json
{
  "actually_paid_usd": 0.0046188,
  "no_cache_hypothetical_usd": 0.060912,
  "first_run_with_cache_hypothetical_usd": 0.043629,
  "rerun_within_ttl_hypothetical_usd": 0.0342468,
  "savings_pct_first_run": -845,
  "savings_pct_rerun": -641,
  "aggregate_savings_first_run_usd": 0.017283,
  "aggregate_savings_rerun_usd": 0.0266652
}
```

The original impossible percentages are reproducible from checked-in data.

## Root Cause Verified: Invalid Percentage Anchor

The immediate root cause is in `_build_summary(...)`:

```python
savings_anchor = (
    actually_paid.total_usd if actually_paid.total_usd is not None else projections.no_cache_hypothetical_usd
)
cohort_first_run_savings = (
    savings_anchor - projections.first_run_with_cache_hypothetical_usd
    if savings_anchor is not None and projections.first_run_with_cache_hypothetical_usd is not None
    else None
)
cohort_rerun_savings = (
    savings_anchor - projections.rerun_within_ttl_hypothetical_usd
    if savings_anchor is not None and projections.rerun_within_ttl_hypothetical_usd is not None
    else None
)
savings_pct_first_run = _safe_pct_or_none(cohort_first_run_savings, savings_anchor)
savings_pct_rerun = _safe_pct_or_none(cohort_rerun_savings, savings_anchor)
```

This asks an invalid question whenever the trace already includes provider
cache reads:

> "How much does hypothetical rerun/first-run cache cost save compared with
> what this already-discounted trace actually paid?"

For `RUN-C-rerun`, the trace actually paid about `$0.0046`, while the analyzer's
rerun projection is about `$0.0342`. Subtracting the latter from the former
guarantees a large negative number even though provider caching demonstrably
worked.

Trust boundary:

- Verified: using `actually_paid_usd` as the percent anchor for these
  projection fields is invalid.
- Assumed: old JSON field names are not API-stable because Fix Brief 01 states
  analyzer backward compatibility is not a constraint.

## New Finding: Anthropic Trace Input Tokens Are Likely Double-Counted

This session found an issue not called out explicitly in Fix Brief 01:
`_estimate_row_tokens(...)` appears to double-count Anthropic cache tokens for
current trace data.

Current code:

```python
input_tokens = int(trace_llm_call["input_tokens"])
provider = detect_provider(trace_llm_call.get("model") or model)
if provider is not None and provider.splits_cache_from_input_tokens:
    cache_creation = int(trace_llm_call.get("cache_creation_input_tokens") or 0)
    cache_read = int(trace_llm_call.get("cache_read_input_tokens") or 0)
    input_tokens = input_tokens + cache_creation + cache_read
```

`ProviderInfo.splits_cache_from_input_tokens=True` for Anthropic. The comment
says Anthropic `input_tokens` excludes cache portions. The checked-in Haiku
traces contradict that assumption.

Evidence from `RUN-C-rerun-trace.json`:

```text
answer-1 input_tokens=4974 cache_read_input_tokens=4938 output_tokens=51 cost_usd=0.0007848
answer-2 input_tokens=4967 cache_read_input_tokens=4938 output_tokens=80 cost_usd=0.0009228
...
```

Rough rendered prompt+cached-system size by character count is around
`4500 tokens`, matching `input_tokens` around `4970`. If `input_tokens`
excluded the cached prefix, it would be near the prompt-only size, not near
the full system+prompt size.

The cost also matches "input_tokens includes cache tokens" math:

For a rerun read event:

```text
non_cache_tokens = input_tokens - cache_read_tokens
cost = non_cache_tokens * input_rate
     + cache_read_tokens * cache_read_rate
     + output_tokens * output_rate
```

Using Haiku rates from `get_model_pricing("anthropic/claude-haiku-4-5")`:

```text
input_rate = 1e-6
output_rate = 5e-6
cache_read_rate = 1e-7
1h write_rate = 2e-6
```

The computed totals from the trace:

```text
RUN-C rerun:
  correct no-cache estimate from trace tokens: ~$0.031284
  correct rerun estimate:                     ~$0.0046188
  actual trace paid:                          ~$0.0046188

Current analyzer:
  no-cache hypothetical:                      ~$0.060912
  rerun hypothetical:                         ~$0.0342468
```

So the analyzer projections are inflated because each row becomes roughly
`input_tokens + cache_read_tokens`, about double the real total input.

Trust boundary:

- Verified from checked-in Haiku traces: adding `cache_read_input_tokens` to
  `input_tokens` produces impossible row sizes and inflated projections.
- Verified from runtime code: `llm_client._normalize()` stores LiteLLM
  `usage.prompt_tokens` as `input_tokens` without normalizing an explicit
  `billed_input_tokens` or `non_cache_input_tokens` field.
- Unable to verify in this session: whether all current Anthropic/LiteLLM
  versions behave this way for every model and TTL. Before changing provider
  metadata globally, add tests around actual normalized usage shape or make
  trace math derive from cost/token consistency defensively.

## Important Caveat: RUN-B Fresh Trace Predates A Pricing Fix

`RUN-B-with-cache-trace.json` appears to predate the Haiku 1h double-charge
fix described in the progress log.

For `answer-1`:

```text
input_tokens=4974
cache_creation_input_tokens=4938
output_tokens=51
cost_usd=0.020043
```

Using the current intended Haiku 1h write rate:

```text
non_cache = 4974 - 4938 = 36
expected write cost ~= 36*1e-6 + 4938*2e-6 + 51*5e-6 = 0.010167
```

But the trace records about `$0.020043`, roughly double. This lines up with
the earlier progress-log section about spurious Haiku 1h double-charging.

Implication:

- `RUN-C-rerun-trace.json` is strong evidence for token semantics because read
  pricing matches exactly.
- `RUN-B-with-cache-trace.json` is useful to reproduce bad analyzer output, but
  should not be treated as a current pricing oracle for first-write cost.

## Text Rendering Hides the Bad Percent Fields

Text output for the rerun trace does not render `savings_pct_*`, but it still
shows inflated hypothetical costs:

```text
Actually paid (trace):       ~$0.0046 (trace)
Cost without caching:        ~$0.06
Cost on rerun (within TTL):  ~$0.03
Estimated savings if applied: ~$0.02/run (first run); ~$0.03/run on rerun
```

With corrected trace-token interpretation, `Cost without caching` should be
around `$0.0313`, and `Cost on rerun` should be around `$0.0046`.

Trust boundary:

- Verified: JSON exposes impossible percentages.
- Verified: text hides percentages but still inherits inflated projection atoms.

## Partial-Trace Verification

The checked-in repository does not include the exact `--only answer-1` trace
from the verification report. This session created a synthetic partial trace by
copying `RUN-B-with-cache-trace.json` and retaining only the first node event.

Command used:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
src = Path('scratchpads/stage2-verification/anthropic-haiku/RUN-B-with-cache-trace.json')
out = Path('/private/tmp/pflow-partial-answer1-trace.json')
data = json.loads(src.read_text())
data['nodes'] = data['nodes'][:1]
data['nodes_executed'] = 1
if 'llm_summary' in data:
    call = data['nodes'][0]['llm_call']
    data['llm_summary'] = {
        'total_calls': 1,
        'total_input_tokens': call['input_tokens'],
        'total_output_tokens': call['output_tokens'],
        'models_used': [call['model']],
        'total_cost_usd': call['cost_usd'],
    }
out.write_text(json.dumps(data, indent=2))
print(out)
PY
```

Then:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace /private/tmp/pflow-partial-answer1-trace.json \
  --format=json
```

Observed summary:

```json
{
  "actually_paid_usd": 0.020043,
  "no_cache_hypothetical_usd": 0.010167,
  "first_run_with_cache_hypothetical_usd": 0.015105,
  "rerun_within_ttl_hypothetical_usd": 0.0057228,
  "savings_pct_first_run": 25,
  "savings_pct_rerun": 71,
  "aggregate_savings_first_run_usd": -0.004938,
  "aggregate_savings_rerun_usd": 0.0044442,
  "actionable_opportunities": 6,
  "total_llm_nodes_estimated": 6,
  "total_llm_invocations_estimated": 6
}
```

Per-call row state:

```json
[
  {"node_path": "answer-1", "data_source": "trace", "cost_usd": 0.020043, "did_not_execute_in_trace": false},
  {"node_path": "answer-2", "data_source": "estimator", "cost_usd": null, "did_not_execute_in_trace": true},
  {"node_path": "answer-3", "data_source": "estimator", "cost_usd": null, "did_not_execute_in_trace": true},
  {"node_path": "answer-4", "data_source": "estimator", "cost_usd": null, "did_not_execute_in_trace": true},
  {"node_path": "answer-5", "data_source": "estimator", "cost_usd": null, "did_not_execute_in_trace": true},
  {"node_path": "answer-6", "data_source": "estimator", "cost_usd": null, "did_not_execute_in_trace": true}
]
```

The analyzer does mark absent rows as `did_not_execute_in_trace=True`, and
`compute_projections` excludes those rows from projection cost. That is better
than the Stage 2 report's initial observation, but the UX is still misleading:

- summary still says `6 LLM nodes` and `~6 invocations` without a trace
  coverage caveat;
- confidence is not a clear "partial trace" signal;
- warnings are emitted for non-executed rows.

## Partial-Trace Warning Bug

From the synthetic one-node trace, warnings included five
`cache.below-min-tokens` findings for nodes that did not execute:

```json
{
  "id": "cache.below-min-tokens",
  "node_id": "answer-2",
  "message": "answer-2: declared cache content is ~20 tokens, below anthropic/claude-haiku-4-5's minimum of 4096; cache_control markers will silently no-op at the provider",
  "context": {
    "evidence_kind": "predicted",
    "cacheable_tokens": 20
  }
}
```

There were equivalent warnings for `answer-3` through `answer-6`.

Root cause:

```python
rows.append(row)
warnings.extend(_per_node_warnings(node, row, declared_chunks=declared_chunks, nodes_by_id=nodes_by_id))
```

`_build_per_call_rows_and_warnings(...)` calls `_per_node_warnings(...)` for
every static LLM row, including rows where `row.did_not_execute_in_trace` is
true.

Implication:

- The data model already has a useful row-level flag.
- Warning emission does not respect it.
- For explicit trace analysis, analytical/runtime-evidence warnings should not
  pretend non-executed rows produced evidence.

Suggested principle:

- Static validator findings can still apply to the workflow file.
- Trace-derived or token-estimate warnings for non-executed rows should either:
  - be suppressed, or
  - be moved into a clearly labeled "not executed in this trace; static
    projection only" bucket.

The simpler v1 fix is suppression for `did_not_execute_in_trace` rows.

## Trace Does Not Persist `--only`

Runtime shared state tracks `__execution__["only_node"]`, and CLI/reporting can
render "Stopped after X". However, `WorkflowTraceCollector.save_to_file()` does
not write `only_node` into trace JSON.

Current trace top-level fields:

```python
trace_data = {
    "format_version": TRACE_FORMAT_VERSION,
    "execution_id": self.execution_id,
    "workflow_name": self.workflow_name,
    "workflow_path": self.workflow_path,
    "start_time": self.start_time.isoformat(),
    "end_time": datetime.now().isoformat(),
    "duration_ms": round(duration_ms, 2),
    "final_status": final_status,
    "nodes_executed": len(self.events),
    "nodes_failed": len(failed_node_ids),
    "failed_node_ids": failed_node_ids,
    "nodes": self.events,
}
```

Implication:

- Analyzer can infer partial coverage by comparing static LLM rows to executed
  trace keys.
- Analyzer cannot honestly say "this came from `--only answer-1`" from current
  trace JSON.
- A future additive trace field like `"only_node": "answer-1"` would be useful,
  but it is not required to fix analyzer honesty. It is a separate runtime
  trace-schema enhancement.

## Suggested-Block Below-Threshold Behavior

Tests currently encode the behavior that a below-threshold greenfield
suggested block still renders, but with zero savings and threshold metadata:

- `tests/test_core/test_cache_analysis_analyze.py::test_suggested_block_below_threshold_has_zero_savings_and_threshold_payload`
- `tests/test_core/test_cache_analysis_renderers.py::test_render_text_includes_per_node_threshold_statuses`
- `tests/test_core/test_cache_analysis_renderers.py::test_render_json_includes_per_node_thresholds`

This matches the code after the phantom-savings fixes: the analyzer no longer
assigns positive dollar value to below-threshold suggestions. However, the Stage
2 finding is still valid from an agent-UX perspective: the "Suggested ## Cache
block" section is a concrete edit surface, and a block that immediately says
"BELOW THRESHOLD - cache will not fire as suggested" is not an actionable
recommendation.

Implementation implication:

- Expect test changes if the desired behavior is to suppress the entire block
  when no assigned node clears provider threshold.
- A conservative rule:
  - keep threshold metadata in JSON/text when a block has at least one useful
    provider-cache assignment;
  - suppress the suggested block when zero nodes are eligible;
  - add a note explaining shared refs were found but no provider-cache edit is
    actionable under current model thresholds.

## Design Implications

### 1. Fix Token Accounting Before Reworking Percentages

The percentage bug and token double-count bug interact. If the next agent only
changes percentage anchoring, projection atoms will still be wrong for the
checked-in Haiku traces.

Recommended sequence:

1. Decide/verify the trace token contract for provider cache:
   - Is `llm_call.input_tokens` intended to mean total prompt tokens?
   - Is there a need for a separate `non_cache_input_tokens` or
     `billed_uncached_input_tokens` field?
2. Update analyzer projection math to stop double-counting Anthropic cache
   tokens for current trace shape.
3. Add tests using Haiku-shaped trace rows where:
   - input includes cache read tokens,
   - rerun projection equals actual cost when every call is a cache read,
   - no-cache projection is around `input_tokens * input_rate + output * output_rate`.

Avoid solving this by silently flipping `ProviderInfo.splits_cache_from_input_tokens`
without tests. That field may have been based on earlier LiteLLM behavior or a
provider-specific interpretation. The safer fix may be to normalize trace
tokens at runtime or add explicit derived fields for analyzer use.

### 2. Replace or Null Ambiguous Percent Fields

The current `savings_pct_first_run` and `savings_pct_rerun` fields do not say
which baseline they are percentages of. They become actively misleading when
the trace already includes provider reads or memo hits.

Options:

- Remove/rename fields if analyzer JSON compatibility is not a constraint.
- Or set them to `null` except when they are computed against a same-cohort
  no-cache baseline.

Useful future atoms:

```json
{
  "no_cache_hypothetical_usd": 0.031284,
  "first_run_with_cache_hypothetical_usd": 0.014063,
  "rerun_within_ttl_hypothetical_usd": 0.004619,
  "first_run_delta_usd": 0.017221,
  "first_run_delta_kind": "savings",
  "first_run_savings_pct_of_no_cache": 55,
  "rerun_savings_usd": 0.026665,
  "rerun_savings_pct_of_no_cache": 85,
  "actual_vs_no_cache_delta_usd": 0.026665,
  "actual_vs_no_cache_delta_kind": "savings",
  "actual_vs_no_cache_pct": 85
}
```

Names are illustrative. The key requirement is that each field states its
baseline.

### 3. Distinguish Savings From Cost Increase

Negative deltas are meaningful, but should not be labeled "savings".

Suggested internal helper shape:

```python
@dataclass(frozen=True)
class CostDelta:
    amount_usd: float | None
    pct: int | None
    kind: Literal["savings", "cost_increase", "break_even", "unavailable"]
    baseline: str
    compared_to: str
```

Renderers should use the `kind`, not the sign, to choose wording:

- `savings`: "saves $X/run"
- `cost_increase`: "adds $X on first run" or "write premium $X"
- `break_even`: "no meaningful cost change"
- `unavailable`: omit cost claim

This would also prevent dry-run nudge and recommendation rank lines from
reintroducing negative-signed savings.

### 4. Make Trace Coverage Explicit

Add summary-level trace coverage metadata derived from static rows vs executed
trace rows:

```json
{
  "trace_coverage": "partial",
  "trace_llm_nodes_executed": 1,
  "trace_llm_nodes_static": 6,
  "trace_unexecuted_llm_nodes": ["answer-2", "answer-3", "..."]
}
```

Text should say something like:

```text
Trace coverage: partial (1 of 6 LLM nodes executed). Whole-workflow cost
projections are limited to executed trace rows.
```

This can be inferred today without a trace schema bump.

### 5. Suppress Analytical Warnings For Non-Executed Rows

In `_build_per_call_rows_and_warnings(...)`, after constructing the row:

```python
if not row.did_not_execute_in_trace:
    warnings.extend(_per_node_warnings(...))
```

This is likely the simplest correction for the observed partial-trace warning
bug.

Caveat:

- Do not suppress validator findings produced by `_cache_validator_findings`.
  Those are static file correctness findings and remain relevant even when a
  trace is partial.

### 6. Suggested Blocks Need An Actionability Gate

Below-threshold suggested blocks should not be presented as paste-ready edits
when zero assignments can provider-cache.

Minimal behavior change:

- If `eligible_nodes` is empty or fewer than two, do not emit
  `cache.shared-context-undeclared` as a recommended action.
- Consider not emitting a `SuggestedBlock` at all when there are zero eligible
  nodes.
- Add a note instead.

This is a UX/design decision because current tests expect the block to exist.

## Open Questions For User Or Implementer

1. Should analyzer JSON fields be renamed now?
   - Importance: 4
   - Recommendation: yes, because current fields are ambiguous and analyzer
     compatibility is explicitly not a constraint.

2. Should trace schema gain `only_node`?
   - Importance: 2 for this fix; 3 for long-term debugging.
   - Recommendation: defer unless touching trace writer anyway. Inferred
     coverage is enough to make analyzer honest.

3. Should below-threshold suggested blocks be suppressed entirely or kept as
   non-actionable notes?
   - Importance: 3
   - Recommendation: suppress as suggested edits; add a note. A paste-ready
     block that cannot fire is the wrong affordance.

4. Should token accounting be fixed in analyzer only or normalized at runtime?
   - Importance: 4
   - Recommendation: first add analyzer regression tests from existing trace
     shape. Then decide whether runtime should emit a clearer field. Runtime
     normalization is cleaner long-term, but analyzer-local correction is
     likely lower-risk for Task 159.

## Suggested Regression Tests

Add tests before changing behavior.

### Token Accounting

Use a Haiku-shaped `PerCallRow` or trace fixture:

- `input_tokens=4974`
- `cache_read_input_tokens=4938`
- `output_tokens=51`
- model `anthropic/claude-haiku-4-5`

Assert:

- row `input_tokens_estimated` is not `9912`;
- no-cache projection is about `0.005229` for the single row;
- rerun projection is about `0.0007848`;
- six-row rerun projection equals actual trace cost for all-read trace.

### Percentage Semantics

For a rerun trace:

- assert no negative `savings_pct_*` fields are emitted;
- preferably assert renamed percentage fields are computed against
  `no_cache_hypothetical_usd`, or old fields are `None`.

### Partial Trace

Use a synthetic trace with one executed LLM node and static workflow with six
LLM nodes:

- assert non-executed rows have `did_not_execute_in_trace=True`;
- assert summary exposes partial coverage;
- assert no `cache.below-min-tokens` warnings are emitted for non-executed rows;
- assert text warns that trace coverage is partial.

### Below-Threshold Suggested Blocks

Use existing test fixture from
`test_suggested_block_below_threshold_has_zero_savings_and_threshold_payload`,
but update expected behavior:

- no `cache.shared-context-undeclared` recommended action when zero nodes clear
  threshold;
- no paste-ready suggested block when zero nodes clear threshold, or block is
  moved to a clearly non-actionable note if the user chooses that design.

## Final Recommendation

Do not implement a clamp-only fix. The session found two independent causes:

1. invalid savings percentage anchors;
2. inflated Anthropic projection atoms from likely cache-token double counting.

The robust path is:

1. fix/clarify trace token accounting,
2. compute deltas only between comparable cost atoms,
3. rename or null ambiguous savings percentage fields,
4. add explicit partial-trace coverage,
5. suppress trace-analysis warnings for non-executed rows,
6. suppress below-threshold suggested blocks as actionable edits.

