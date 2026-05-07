# Task 159 Fix Brief 02 — Trace Evidence Scope, `--only`, and Dynamic Batch Model Truth

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`

## Purpose

This brief captures what is known about analyzer output that overstates what a
trace proves. The core issue is evidence provenance: the analyzer currently
mixes static workflow projections, memo/history, and executed trace evidence in
ways that can make partial or dynamic-batch traces look like whole-workflow
truth.

The next agent's job is to research the current code deeply, reproduce the
issues, and discuss design options with the user before implementing. Do not
turn this brief into a mechanical patch list. Prefer a simple final model that
future AI agents can understand over a quick local patch.

There are no shipped users of `analyze-cache`. Compatibility with current
branch-only analyzer JSON is not a constraint. Correct semantics and simple
concepts are.

## Findings Covered

Primary:

- Final verification Finding 4: partial `--only` trace analysis is misleading.
- Final verification Finding 6: paid dynamic batch trace has useful per-item
  telemetry, but analyzer model accounting is wrong.

Related:

- Evidence-provenance part of Finding 9: skipped branch analysis/reporting has
  confusing context. This brief only covers the overlap around executed trace
  evidence versus validation/static warnings. Broader branch/report UX can be a
  separate task if needed.

Keep Finding 7 separate. Finding 7 is about `--only` stdout routing and huge
intermediate output dumps, not analyzer trace evidence.

## Plain-Language Problem

`--only` and `analyze-cache --from-trace` answer different questions.

- `pflow <workflow> --only X --report` asks: what happened when I ran this one
  node/path?
- `pflow analyze-cache <workflow> --from-trace <trace>` asks: what cache-design
  conclusions can I draw from this workflow plus this trace?

A trace produced by `--only answer-1` is useful local evidence for `answer-1`.
It is not whole-workflow evidence for all LLM nodes.

The final verification report found that after running:

```bash
pflow scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --only answer-1 \
  --report \
  --no-cache \
  context="$CTX"
```

and then analyzing that trace:

```bash
pflow analyze-cache scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace <only-trace> \
  --format=json
```

the analyzer output read like it had evidence for the full six-node workflow:

```text
6 LLM nodes using anthropic...
Confidence: medium_from_memo (6 of 6 nodes)
savings_pct_first_run: -1825
aggregate_savings_first_run_usd: -0.004938
```

That is misleading. Only one targeted node ran.

The dynamic batch case is similar but more specific: a paid
`chorus-chooser --only generate-chorus-options` trace correctly recorded eight
batch-item LLM calls with concrete Gemini models, but analyzer JSON reported an
empty model for the executed batch row and a summary model list that included
only `anthropic/claude-haiku-4-5`. That combines real Gemini cost with wrong or
missing exact-model identity.

Prompt caching is exact-model scoped. Losing model truth directly undermines
cache advice.

## Verified Code Facts

These facts were checked by explorer subagents in this session.

### `--only` Trace Scope

- Runtime shared state records `--only` at
  `shared["__execution__"]["only_node"]`.
- CLI JSON success output can include `execution.only_node` and skipped-node
  info.
- Report generation receives `only_node` and `total_nodes` out-of-band and can
  render a skipped count.
- Saved trace JSON does **not** include `only_node`, `nodes_total`, `partial`,
  or `execution_mode`.
- Therefore, `analyze-cache --from-trace <trace>` cannot directly know that a
  trace came from `--only`. It can only infer partialness by comparing executed
  trace nodes against the current workflow IR.
- Analyzer has a row-level signal:
  `PerCallRow.did_not_execute_in_trace`.
- Analyzer does **not** have a first-class analysis-level trace-scope concept
  like `trace_is_partial`, `execution_mode`, `only_node`, `executed_llm_nodes`,
  or `total_llm_nodes`.

### Dynamic Batch Model Truth

- Runtime LLM usage is written by `LLMNode.post()` into `shared["llm_usage"]`.
- Batch execution stores per-item telemetry under:
  - `batch_items[*].node_output`
  - `batch_items[*].llm_call`
  - `batch_items[*].llm_prompt`
  - `batch_items[*].llm_response`
  - `batch_items[*].llm_system`
- The parent batch event usually has no top-level `llm_call`; concrete calls
  live under `batch_items[*].llm_call`.
- `TraceTree` treats batch items as first-class walked events and
  `iter_llm_leaves()` yields those per-item calls.
- Trace-level `llm_summary.models_used` is correct for the paid chorus trace.
- Analyzer loses model detail in `_build_trace_execution_index()` by indexing
  calls as `(workflow_path, node_id)` and using `setdefault()`. Dynamic batch
  items all share the parent node id, so only one item-level call survives in
  that map.
- `_build_per_call_row()` then sees `model: ${item.model}` and deliberately
  sets `model=""`, `model_is_heterogeneous=True`.
- Summary `models_in_use` is built from static row models and excludes
  heterogeneous rows, so traced concrete per-item models do not contribute.

### Skipped Branch / Warning Provenance

- `cache_chunks_skipped` is only recorded on executed LLM calls. That evidence
  is trustworthy runtime trace evidence.
- Top-level trace warnings combine runtime warnings and validation warnings.
- Report currently labels trace top-level warnings as runtime warnings.
- Static validation/lint warnings can mention nodes that did not execute in a
  branch. That is not necessarily wrong, but the source/provenance must be
  clear.
- Analyzer discrepancy construction appears to pass workflow path where the
  JSON field name says trace path in at least one context.

## Current Evidence

From `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`:

### Finding 4 Evidence

Observed targeted trace:

```text
Trace: /Users/andfal/.pflow/debug/workflow-trace-8ba27c20-smoke-with-cache-20260506-230837.json
Cost: $0.0008
Command used --only answer-1
```

Analyzer output included:

```text
6 LLM nodes using anthropic...
Confidence: medium_from_memo (6 of 6 nodes)
savings_pct_first_run: -1825
aggregate_savings_first_run_usd: -0.004938
actionable_opportunities: 1
```

Expected behavior from the report:

- identify the trace as partial,
- avoid whole-workflow savings claims,
- avoid recommendations based on non-executed calls unless clearly marked as
  projections.

### Finding 6 Evidence

Paid targeted music run:

```text
Workflow: /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md
Command used --only generate-chorus-options --report --no-cache
Trace: /Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260506-232059.json
Cost: $0.066948
Progress: generate-chorus-options... 8/8
```

Trace truth:

```text
llm_summary.models_used:
  gemini/gemini-2.5-flash-lite
  gemini/gemini-3-flash-preview
batch_items[*].llm_call contains model, tokens, cost_usd, cache telemetry.
```

Analyzer JSON:

```text
summary.models_in_use: ["anthropic/claude-haiku-4-5"]
per_call[generate-chorus-options].model: ""
per_call[generate-chorus-options].cost_usd: 0.06694800000000001
```

This means analyzer combined real traced Gemini cost with wrong or missing model
identity.

## Reproduction Commands

Use sandbox-safe invocation where possible.

### Partial `--only` Trace

```bash
CTX="$(cat scratchpads/stage2-verification/anthropic-haiku/reference.md)"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --only answer-1 \
  --report \
  --no-cache \
  context="$CTX"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/anthropic-haiku/smoke-with-cache.pflow.md \
  --from-trace <only-trace-path> \
  --format=json \
  context="$CTX"
```

### Dynamic Batch Trace

Use the existing paid trace if present:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --from-trace /Users/andfal/.pflow/debug/workflow-trace-e1a6206b-chorus-chooser-20260506-232059.json \
  --format=json
```

If the trace is unavailable, decide with the user before spending provider
budget. The report says this run cost `$0.0669`.

## Most Relevant Code Areas

Start here, read before editing.

### `--only` and Trace Production

- `src/pflow/runtime/engine/engine.py`
  - `parse_only_path()`
  - `WorkflowEngine._run_inner()`
  - `WorkflowEngine._execute_node()`
  - shared-state `__execution__["only_node"]`
- `src/pflow/runtime/workflow_trace.py`
  - `WorkflowTraceCollector.record_node_execution()`
  - `WorkflowTraceCollector.save_to_file()`
  - trace fields currently written.
- `src/pflow/cli/commands/run.py`
  - `--only` option handling.
  - trace/report saving.
- `src/pflow/core/trace_report.py`
  - report receives `only_node` and `total_nodes` out-of-band.

### Analyzer Trace Consumption

- `src/pflow/cli/commands/analyze_cache.py`
  - CLI entry.
- `src/pflow/core/cache_analysis/analyze.py`
  - `analyze()`
  - `_resolve_trace_data()`
  - `_build_trace_execution_index()`
  - `_build_per_call_rows_and_warnings()`
  - `_build_per_call_row()`
  - `_aggregate_confidence()`
  - `_build_summary()`
- `src/pflow/core/trace_tree.py`
  - `TraceTree.walk()`
  - `TraceTree.iter_llm_leaves()`
  - `TraceTree.iter_actual_cost_events()`
- `src/pflow/core/cache_analysis/cost_estimation.py`
  - row exclusion rules for `did_not_execute_in_trace`
  - projections versus actual paid cost.
- `src/pflow/core/cache_analysis/render_json.py`
  - current JSON exposes `per_call[].did_not_execute_in_trace`, but no
    analysis-level trace scope.
- `src/pflow/core/cache_analysis/render_text.py`
  - current text can mark per-row non-execution.

### Dynamic Batch Runtime/Trace

- `src/pflow/nodes/llm/llm.py`
  - `LLMNode.post()` writes `llm_usage`.
- `src/pflow/runtime/engine/batch_executor.py`
  - `_capture_item_trace()`.
- `src/pflow/runtime/workflow_trace.py`
  - `_collect_llm_summary()` uses `TraceTree` and gets models right.

### Skipped Branch / Warning Provenance

- `src/pflow/nodes/llm/llm.py`
  - skipped chunks producer.
- `src/pflow/runtime/workflow_trace.py`
  - copies `llm_usage` into trace.
- `src/pflow/core/trace_report.py`
  - cache telemetry and top-level warning rendering.
- `src/pflow/execution/runner.py`
  - combines runtime and validation warnings before writing trace warnings.
- `src/pflow/core/workflow/validator.py`
  - static validation/lint warnings over whole IR.

## Relevant Progress-Log Context

Read these sections from
`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`:

- `Stage 2 verification — comprehensive UX + spec-target audit`
  - Source of the original 21 findings and exact-model scoping context.
- `Stage 2 follow-up — Finding #7: LLM node count vs invocation count`
  - Existing attempt to distinguish node count from invocation count.
  - Relevant because dynamic batch count is central here.
- `Stage 2 status check — Findings #3, #14, #16`
  - Says `cache_chunks_skipped` is surfaced and participates in discrepancy
    attribution.
- `Stage 2 follow-up — Finding #17: all-memo trace cost is known zero`
  - Relevant to actual trace cost boundaries and cached-event semantics.
- `Stage 2 follow-up — Finding #8: drift-aware analyze-cache auto-load`
  - Existing trace/IR comparison gate. Useful pattern, but it is about drift,
    not partial execution scope.
- `Stage 2 follow-up — Findings #11/#12: exact-model fragmentation + lone-write penalty`
  - Reinforces that cache behavior is exact-model scoped.
- `Stage 2 follow-up — Findings #11/#12: post-review fixes`
  - Notes within-batch heterogeneity was carved out as GH issue #369.
  - Paid verification now shows this carve-out affects real analyzer output.
- `Stage 2 follow-up — Findings #4/#5: per-call cache telemetry surfaces`
  - Raw trace telemetry expectations for JSON/report.
- `Stage 2 follow-up — Finding #21: child-scoped sub-workflow cache recommendations`
  - Useful example of splitting IDs/actions when one diagnostic did too much.

Also read:

- `scratchpads/stage2-verification/README.md`
  - Handoff trust boundary and paid-run guidance.
- `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`
  - Findings 4, 6, 9, and positive results.
- `src/pflow/core/cache_analysis/CLAUDE.md`
  - Current analyzer architecture and Task 160 warning.

## Key Design Options

The user specifically raised a simple option: reject analyzer use on `--only`
traces. This deserves serious consideration.

### Option A — Reject Explicit `--only` Traces in `analyze-cache`

Policy:

- `analyze-cache --from-trace <only-trace>` exits nonzero with a clear
  diagnostic.
- Message explains:
  - trace-backed aggregate analysis requires a whole-workflow trace,
  - this trace was produced by `--only`,
  - use `pflow run --only --report` for local node evidence,
  - run `analyze-cache <workflow>` without `--from-trace` for static guidance,
  - run the full workflow for trace-backed aggregate analysis.

Good:

- Very simple agent mental model.
- Prevents the exact false whole-workflow conclusions.
- Avoids designing partial-evidence semantics before a real need is proven.
- Aligns with a high-quality CLI stance: refuse misleading input rather than
  produce caveated nonsense.

Bad:

- Requires reliably detecting `--only`.
- Existing traces do not store `only_node`, so detection requires either
  inference or adding trace metadata going forward.
- Analyzer loses a potentially useful local-verification mode.
- Branching workflows naturally execute only part of the static graph; avoid
  rejecting valid conditional traces merely because not every static node ran.

Possible clean shape:

- Add explicit trace metadata for future runs, e.g. execution scope/mode.
- Reject only traces that explicitly say they came from `--only`.
- For old traces without metadata, either infer conservatively with a warning or
  leave behavior unchanged temporarily while tests use new fixtures.

### Option B — First-Class Partial Evidence Mode

Policy:

- Analyzer accepts partial traces and splits output into:
  - observed executed subset,
  - full-workflow static projection,
  - non-executed rows,
  - unavailable whole-workflow conclusions.

Good:

- Most helpful long-term if agents frequently use partial paid verification.
- Makes `analyze-cache --from-trace <only-trace>` useful without overclaiming.

Bad:

- More design work.
- Easy to overcomplicate.
- Requires clear data model names so future agents do not inherit a mess.

### Option C — Add Trace Execution Scope Metadata

Policy:

- Trace producer writes execution-scope metadata such as `mode`, `only_node`,
  maybe total node count or target path.
- Analyzer/report consume this instead of guessing.

Good:

- Clean producer/consumer contract.
- Additive trace fields are usually maintainable.
- Supports either Option A or B.

Bad:

- Does not fully solve old traces.
- Still requires analyzer policy once partialness is known.

### Option D — Fix Dynamic Batch Model Accounting Only

Policy:

- Preserve concrete per-item trace model information in analyzer output and
  summary model accounting.
- Do not address partial trace policy yet.

Good:

- Directly fixes Finding 6.
- Runtime/TraceTree already preserve the needed facts.

Bad:

- Finding 4 remains.
- May reinforce the current mixed evidence model instead of simplifying it.

## Current Recommendation for Research

The likely best final shape is either:

- **Option A + C**: store explicit `--only` scope in new traces and reject those
  traces for `analyze-cache --from-trace`, while keeping `--only --report` as
  the supported local verification surface; or
- **Option B + C** only if the user decides partial trace analysis is worth the
  extra model complexity.

Given the project principle "solve observed problems, not theorized ones",
Option A + C is attractive. The observed problem is misleading aggregate
analysis from partial traces, not a proven need for rich partial-trace cache
design analysis.

The dynamic batch issue still needs a model-truth fix even if `--only` traces
are rejected, because dynamic batch can also appear in full traces. Do not hide
Finding 6 behind the `--only` policy.

## Research Questions for the Next Agent

Answer these before implementation:

1. What exactly should count as an unsupported partial trace?
   - Explicit `--only` only?
   - Any trace with fewer executed LLM nodes than static IR?
   - Something branch-aware?
2. Should new trace metadata be added? If yes, what is the minimal durable
   shape?
3. Should analyzer reject explicit `--only` traces before any analysis, or
   fall back to static analysis with a warning?
4. How should JSON and text surface dynamic batch model sets?
   - Per-call row field?
   - Summary field?
   - Dedicated heterogeneity detail?
5. Should analyzer derive executed model sets from `TraceTree.iter_llm_leaves()`
   when a trace exists?
6. How should validation warnings and runtime warnings be distinguished in
   reports/traces?
7. Does any current test encode the broken assumption that one
   `(workflow_path, node_id)` maps to one LLM call?

## Desired UX Properties

Outcome constraints:

- Partial `--only` trace evidence must not masquerade as whole-workflow truth.
- If `analyze-cache --from-trace` rejects a partial trace, the error should
  tell the agent exactly what command/surface to use instead.
- Dynamic batch rows with trace evidence must not show empty/wrong model
  identity while showing real cost.
- Exact model scoping must be preserved in all analyzer claims.
- Executed trace evidence, static IR projection, validation warnings, and memo
  history should be distinguishable in output or intentionally kept separate.
- Branch-skipped cache chunks should remain visible as executed LLM evidence.
- Static warnings about non-executed branches should not be labeled as runtime
  warnings.

## Test/Verification Expectations

Useful automated test shapes:

- Analyzer on a trace explicitly marked as `--only` should reject or clearly
  enter partial mode, depending on chosen policy.
- Existing report generation for `--only` should still work.
- Dynamic batch trace fixture with two concrete models should preserve model set
  in analyzer JSON/text.
- Cost for dynamic batch should remain the sum of item costs.
- Static/default model rows should not overwrite executed trace model truth.
- Validation warning versus runtime warning source should be distinguishable if
  this brief's Finding 9 overlap is addressed.

Likely test files:

- `tests/test_runtime/test_engine_behavior.py`
- `tests/test_runtime/test_dotted_only_path.py`
- `tests/test_runtime/test_workflow_trace.py`
- `tests/test_core/test_trace_tree.py`
- `tests/test_core/test_cache_analysis_analyze.py`
- `tests/test_core/test_cache_analysis_cost_estimation.py`
- `tests/test_core/test_cache_analysis_renderers.py`
- `tests/test_cli/test_analyze_cache.py`
- `tests/test_core/test_trace_report.py`

Run focused cache-analysis tests before broader gates. Use
`scratchpads/stage2-verification/README.md` for sandbox-safe commands.

## Non-Goals for This Brief

- Do not start Task 160 structural refactor.
- Do not fix `--only` stdout routing dump here; that belongs to a CLI output
  brief.
- Do not build a rich partial-analysis engine unless the user chooses that
  after seeing tradeoffs.
- Do not assume the trace producer is broken for dynamic batch; evidence says
  producer and `TraceTree` preserve the facts.
- Do not reject all traces where not every static node executed; branching
  workflows need careful treatment.

