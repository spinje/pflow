# TraceTree + Sub-Workflow Rollup Review Handoff

You are reviewing or continuing the staged implementation in
`/Users/andfal/projects/pflow-feat-prompt-caching`.

The original target plan was:

`.taskmaster/tasks/task_159/implementation/fix-plans/tracetree-and-subworkflow-rollup-plan.md`

The current staged state is no longer the old partial vertical slice. A
completion pass was added after that handoff and the progress log now has a
final entry:

`## TraceTree + sub-workflow rollup plan completion pass (2026-05-02)`

Read that progress-log entry before making any changes:

```bash
tail -n 180 .taskmaster/tasks/task_159/implementation/implementation-progress-log.md
```

## Current Status

The implementation is intended to be complete for the plan's load-bearing
behavior, with a few deliberate, documented deviations.

Implemented:

- Shared `TraceTree` traversal primitive.
- Trace-driven `summary.current_cost_per_run_usd`.
- Static sub-workflow LLM row enumeration.
- Analyze-cache JSON major version `3.0`.
- Workflow-scoped per-call rows via `PerCallRow.workflow_path`.
- Workflow-scoped trace execution/cost index keyed by `(workflow_path, node_id)`.
- Phantom-cost suppression via `PerCallRow.did_not_execute_in_trace`.
- Child parameter views for:
  - root parameters passed into child inputs
  - memo-backed parent node outputs passed into child inputs
  - unresolved child inputs remaining honestly unresolved/partial
- Same bare node ids in parent/child workflows preserved separately.
- Workflow-scoped output-token lookup, warning markers, and discrepancy predicted-key lookup.
- Real `SubWorkflowRollupEntry.current_cost_usd` and `cost_without_caching_usd`.
- Text renderer Phase 2c UX:
  - root vs sub-workflow LLM count line
  - per-workflow per-call grouping
  - `(called by <node>)` child headings
  - sub-workflow drill-in commands
  - improved cycle/depth/template-items notes
  - workflow attribution for unpriced child models
  - workflow scope in discrepancy messages
- JSON renderer additions:
  - `per_call[].workflow_path`
  - `per_call[].did_not_execute_in_trace`
  - complete `summary.sub_workflow_rollup`
  - `summary.unavailable_models_by_workflow`
- Committed fixture infrastructure:
  - `tests/fixtures/cache_analysis/parent.pflow.md`
  - `tests/fixtures/cache_analysis/child.pflow.md`
  - `tests/fixtures/cache_analysis/parent-child-trace.json`
  - `tests/fixtures/cache_analysis/parent-child-erroring-trace.json`
  - `tests/shared/trace_fixture_builder.py`
- CliRunner tests for rollup costs, same-id scoped rows, and grouped text/drill-in output.

## Non-Negotiable Architecture Constraints

Keep these intact.

1. **Actual current cost is trace-driven.**

   `summary.current_cost_per_run_usd` must come from:

   `TraceTree.total_cost(descend_sub_workflows=True, include_cached=False, ...)`

   Do not compute actual current cost from IR rows. IR rows over-count erroring
   runs and under-count runtime recursion.

2. **Projection fields are IR-driven.**

   `cost_without_caching_usd`, `aggregate_savings_first_run_usd`, and rerun
   savings come from statically reachable per-call rows.

3. **`TraceTree.cost_for_node(...)` must remain shallow.**

   It must not descend into `sub_workflow_events`; otherwise parent row
   attribution double-counts child LLM cost. Deep rollup belongs to
   `TraceTree.total_cost(...)`.

4. **Workflow-path attribution is input-threaded, not trace-native.**

   Runtime trace events still do not carry `workflow_path`. Analyzer attribution
   threads child paths through `cw_result.edges` / parent workflow node id →
   child workflow path. This is intentionally honest but incomplete for
   runtime-dynamic/template-items cases.

5. **Do not conflate schema namespaces.**

   Analyze-cache JSON is `3.x`. Runtime trace files are still `2.1.0`, and
   trace loader gates should stay `2.x`.

6. **Cached fast-path compatibility is deliberate.**

   Cached events with no `llm_call` and no batch items return `(0.0, "trace")`
   regardless of trace version. This intentionally differs from the old plan's
   2.0-only suggestion because current runtime/tests expect 2.1 cached events
   to report zero actual cost.

## Deliberate Deviations From The Plan

These are not accidental omissions.

1. **Dynamic/template-items sub-workflow attribution remains limited.**

   Because trace events do not carry workflow paths, the analyzer cannot fully
   attribute dynamic child workflow paths without a trace schema/runtime change.
   The cross-workflow walker now emits a note explaining:

   - current cost remains trace-driven and reflects actual execution
   - per-call/projection rows under-cover those dynamic child calls
   - providing resolved inputs or inline static batch items enables static enumeration

2. **Root-edit advisories remain root-only by design.**

   `_populate_suggested_blocks`, `_emit_padding_advisories`, and
   `_consolidate_to_root_advisories` intentionally operate on root rows only
   because they generate edits for the analyzed file's `## Cache` block.

   Child workflow edit recommendations are intentionally handled by the renderer
   drill-in section:

   ```text
   pflow analyze-cache child.pflow.md
   ```

   Do not blindly migrate those helpers to all workflows unless you also design
   how parent-scope output should propose edits across multiple files.

3. **Cycle/template-items committed fixture files were not added.**

   The plan listed them as “if practical”. The current code covers the behavior
   through cross-workflow note text/unit paths and renderer tests. The committed
   parent/child and erroring-trace fixtures cover the production-shape cost and
   phantom-row paths.

4. **Backward-compatible bare predicted-key lookup remains.**

   `_predicted_key_for_event(...)` still accepts old bare `node_id` maps in
   addition to `(workflow_path, node_id)` maps. Existing tests monkeypatch
   `_predict_cache_keys` with bare maps; removing the fallback requires updating
   those tests so discrepancy emission remains genuinely covered.

5. **One inherited Python-compat issue was fixed opportunistically.**

   `src/pflow/execution/plan.py` had a `match` statement that ruff rejected for
   this repo's Python target. It was replaced with equivalent `if` branches.

## Important Implementation Details

### Trace Execution Index

`src/pflow/core/cache_analysis/analyze.py` now builds `TraceExecutionIndex`.

It tracks:

- `costs_by_key`
- `llm_calls_by_key`
- `executed_keys`
- `workflows_with_trace`
- `current_cost_by_workflow`
- `partial_workflows`

This separation matters. Trace events may have token/cacheable evidence but no
`cost_usd`; those events must still feed Track A/B/C token data. Do not collapse
LLM-call indexing into cost indexing.

### Phantom-Cost Suppression

Rows are marked `did_not_execute_in_trace=True` when:

- the workflow path has trace data
- the row's `(workflow_path, node_id)` is absent from executed trace keys

`cost_estimation._partition_rows(...)` skips those rows so recomputed costs do
not inflate actual/projection aggregates. The row remains visible in JSON/text.

### Child Parameter Views

`_build_parameters_by_workflow(...)` resolves child workflow inputs using the
parent workflow's `AnalysisContext`, not raw root parameters. This preserves:

- workflow input roots: current `--inputs` win
- node output roots: memo lookup through `AnalysisContext.resolve_ref_value`
- empty/unresolved values: stay unavailable via `_normalize_empty`

`AnalysisContext.parameters_for_workflow(...)` returns `{}` for unknown child
paths rather than falling back to root parameters. This avoids false resolution
against the wrong workflow scope.

### Sub-Workflow Rollup Costs

`_build_sub_workflow_rollup(...)` computes:

- `current_cost_usd` from traced child leaves grouped by workflow path
- `cost_without_caching_usd` from each workflow's per-call rows

`sub_workflow_rollup` remains `None` for single-workflow analysis. A non-`None`
rollup with `truncated=True` indicates cross-workflow traversal stopped at a
cycle/depth boundary.

### Renderer Scope

Text grouping and warning markers are keyed by `(workflow_path, node_id)`.
Discrepancy messages include `workflow_path_short`; `make_diagnostic(...)`
backfills it for legacy direct callers/tests so old helper usage does not fail.

## Files Worth Reviewing

Production:

- `src/pflow/core/trace_tree.py`
- `src/pflow/core/cache_analysis/analyze.py`
- `src/pflow/core/cache_analysis/context.py`
- `src/pflow/core/cache_analysis/cost_estimation.py`
- `src/pflow/core/cache_analysis/cross_workflow.py`
- `src/pflow/core/cache_analysis/render_json.py`
- `src/pflow/core/cache_analysis/render_text.py`
- `src/pflow/core/cache_analysis/warning_catalog.py`
- `src/pflow/core/cache_analysis/token_estimation.py`
- `src/pflow/core/trace_report.py`
- `src/pflow/runtime/workflow_trace.py`
- `src/pflow/execution/result.py`
- `src/pflow/execution/plan.py`

Tests/fixtures:

- `tests/test_core/test_trace_tree.py`
- `tests/test_core/test_cache_analysis_analyze.py`
- `tests/test_core/test_cache_analysis_cost_estimation.py`
- `tests/test_core/test_cache_analysis_renderers.py`
- `tests/test_cli/test_analyze_cache.py`
- `tests/test_mcp_server/test_analyze_cache_tool.py`
- `tests/fixtures/cache_analysis/`
- `tests/shared/trace_fixture_builder.py`

## Verification Already Performed

Use the `pflow-sandbox-testing` skill. In this sandbox, do not trust `make`,
`make check`, or `uv run`; use the existing venv directly.

Commands that were green after the completion pass:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core -q
# 1993 passed, 1 skipped

HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_trace_tree.py tests/test_core/test_cache_analysis_analyze.py tests/test_core/test_cache_analysis_cost_estimation.py tests/test_core/test_cache_analysis_renderers.py tests/test_runtime/test_workflow_trace.py tests/test_core/test_trace_report.py tests/test_core/test_cache_analysis_per_id_emission.py tests/test_core/test_cache_analysis_per_id_coverage.py tests/test_cli/test_analyze_cache.py tests/test_mcp_server/test_analyze_cache_tool.py -q
# 430 passed

HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_cli/test_analyze_cache.py tests/test_mcp_server/test_analyze_cache_tool.py -q
# 26 passed

HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_execution/test_plan_drift.py tests/test_runtime/test_prompt_cache_hash.py -q
# 48 passed

HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check <touched production/test paths>
# clean

HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff format --check <touched production/test paths>
# clean

HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy
# clean, 201 source files

HOME=/private/tmp/pflow-test-home .venv/bin/python -m deptry src
# clean

HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete'
# 6064 passed, 18 skipped
```

If you re-run focused tests, use the corrected focused path:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  tests/test_core/test_trace_tree.py \
  tests/test_core/test_cache_analysis_analyze.py \
  tests/test_core/test_cache_analysis_cost_estimation.py \
  tests/test_core/test_cache_analysis_renderers.py \
  tests/test_runtime/test_workflow_trace.py \
  tests/test_core/test_trace_report.py \
  tests/test_core/test_cache_analysis_per_id_emission.py \
  tests/test_core/test_cache_analysis_per_id_coverage.py \
  tests/test_cli/test_analyze_cache.py \
  tests/test_mcp_server/test_analyze_cache_tool.py \
  -q
```

## Current Worktree Notes

The user stated that all changes are staged. Do not assume unstaged or
untracked files are disposable; inspect before changing.

Earlier pre-existing/user artifacts included:

- `.taskmaster/tasks/task_159/implementation/agent-brief-walker-consolidation.md`
- `.taskmaster/tasks/task_159/implementation/fix-plans/tracetree-and-subworkflow-rollup-plan.md`
- `.taskmaster/tasks/task_159/implementation/handoffs/braindump-2026-05-02-walker-consolidation.md`
- `scratchpads/stage2-verification/gemini-smoke/RUN4-memo-hit-trace.json`

Treat them as user/pre-existing artifacts unless you verify otherwise.

## Suggested Review Checklist

Before approving or continuing:

- Confirm `summary.current_cost_per_run_usd` still uses `TraceTree.total_cost(...)`.
- Confirm `TraceTree.cost_for_node(...)` stays shallow.
- Confirm did-not-execute rows are skipped by cost aggregation.
- Confirm child parameter resolution does not fall back to root parameters for
  unknown child paths.
- Confirm parent/child same-id rows survive in JSON and text.
- Confirm `summary.sub_workflow_rollup.per_workflow[*].current_cost_usd` is
  non-null for the parent-child trace fixture.
- Confirm dynamic/template-items limitations are documented in notes rather
  than silently ignored.
- Confirm root-only recommendation helpers are still intentionally documented,
  not accidentally root-only.
- Re-run at least the focused related suite and quality checks if making any
  edits.

## Remaining Product Follow-Ups

These are future work, not blockers for the current staged implementation:

1. Add trace-native `workflow_path` if precise attribution for dynamic child
   workflows becomes important. That would be a runtime trace schema change.
2. Design multi-file recommendation output if parent-scope analyze-cache should
   propose direct edits to child workflow `## Cache` blocks.
3. Add richer committed cycle/template-items fixtures if future changes touch
   those paths heavily.
