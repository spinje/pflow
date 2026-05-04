# Verified Non-Issues — Don't Try to Fix These

Six things look like architectural problems on first read but are verified clean. Don't try to "fix" them as part of this refactor — you'll either break correct code or burn time on a non-problem.

## 1. `_cache_validator_findings` is NOT duplicating `data_flow.py`

**What it looks like**: `analyze.py:2035-2080` has a function called `_cache_validator_findings` that returns cache-related diagnostics. Per task 159 DD#20, all cache validation is supposed to live in `data_flow.py`. So is the analyzer re-implementing validation?

**Verified**: No. The function calls `validate_data_flow(workflow_ir, check_inputs=False)` at line 2054, then filters the result to `cache.*` IDs and enriches each diagnostic with `context["affected_workflow"]` for cross-workflow scoping. It emits zero new conditions. ~46 LOC of glue. DD#20 is honored.

**What this means for you**: Move it as-is to wherever it ends up. It needs to keep doing exactly what it does. The workflow-scoping enrichment is load-bearing — the validator can't add it because the validator is workflow-agnostic.

## 2. The discrepancy cluster's lazy imports are NOT a smell

**What it looks like**: `_build_predict_scaffold` lazy-imports five modules at function-scope: `compile_workflow`, `Registry`, `create_planner_shared`, `plan_node`, plus exceptions. Lazy imports usually signal coupling problems.

**Verified**: This is intentional and correct. `cache_analysis.__init__` re-exports `summarize`, which is called on every `pflow run --dry-run`. Top-of-module runtime imports would force every dry-run to pay ~700ms LiteLLM startup cost. The lazy pattern stays.

**What this means for you**: When you move this code to `stages/discrepancy/predict.py`, keep the lazy imports lazy. Adding them to module-scope imports would be a regression.

## 3. There is NO duplicate cache-key predictor

**What it looks like**: The discrepancy stage compiles workflows and runs the planner to predict cache keys. `pflow run --dry-run` does the same. So is the analyzer reimplementing what `--dry-run` already does?

**Verified**: No. Both consumers call the same primitives:
- `runtime/engine/plan_node.py::plan_node()` — the engine's cache-key authority
- `execution/plan.py::create_planner_shared()` — sets up the shared store

In fact, `create_planner_shared` was specifically renamed from `_create_planner_shared` in the task 159 PR to make it public so the analyzer could share it (see `execution/plan.py:464` + the backwards-compat alias at line 503). The substrate is deliberately unified.

**What this means for you**: Don't try to "extract a shared predictor" — there's no duplication to consolidate. Don't move the prediction logic to `runtime/`; keep it in `cache_analysis/stages/discrepancy/predict.py`. The two consumers correctly share the underlying primitives.

## 4. `_build_openai_cache_kwargs` is NOT duplicated

**What it looks like**: An earlier explorer agent claimed this function exists in both `core/llm_client.py` and `nodes/llm/llm.py`, with the llm_client version being dead code.

**Verified**: False positive. Direct grep confirms only one definition: `nodes/llm/llm.py:161`, called from `nodes/llm/llm.py:473`. There is no duplicate in `llm_client.py`.

**What this means for you**: Skip this. There's nothing to dedupe.

## 5. The pricing helpers in `analyze.py` should NOT merge into `cost_estimation.py`

**What it looks like**: `analyze.py` lines 2082-2127 have helpers like `_input_rate`, `_estimate_token_savings_usd`, `_savings_for_shared_ref` that look like pricing logic. `cost_estimation.py` is the package's pricing module. So merge them?

**Verified**: Different abstraction levels.
- `cost_estimation.py` operates on **`PerCallRow` lists** (post-aggregation projections producing `ProjectionBreakdown` and `ActuallyPaidCost`).
- The `analyze.py` helpers operate on **chunks/refs** during greenfield suggested-block discovery ("if this ref were cached, how much would N callsites save?").

Different concerns. `_input_rate` is a thin wrapper around `cost_estimation.get_model_pricing(model).input_rate` — the actual pricing lookup is already in `cost_estimation.py`.

**What this means for you**: These helpers move with their consumer (the suggested-blocks logic) into `stages/suggestions.py`. They do NOT merge into `cost_estimation.py`.

## 6. `cross_workflow.py` (the walker) is NOT shallow infrastructure

**What it looks like**: 416 LOC walker file that produces typed `CrossWorkflowEdge` data. After lifting the cross-workflow analytical stage to `stages/cross_workflow.py`, doesn't the walker become a hollow shell?

**Verified**: No. The walker has FOUR distinct downstream consumers in `analyze.py`:
- `_edge_child_paths(cw_result)` — extracts edge child paths for trace correlation
- `_build_trace_execution_index(trace_data, lookup_path, edge_child_paths)` — uses edge child paths
- `_build_parameters_by_workflow(cw_result, ...)` — cross-workflow parameter resolution
- `_build_cross_workflow_findings(cw_result=cw_result, ...)` — the analytical stage

It's genuinely shared infrastructure, not a stage helper. Folding it into the analytical stage would require the other three consumers to import from a stage file — wrong layer.

**What this means for you**: Keep `cache_analysis/cross_workflow.py` (the walker) at top level. Only the analytical bits (lines 2134-2500 in `analyze.py`) move to `stages/cross_workflow.py`. The walker stays put, unchanged.

## Bonus: things task 159 verified that you don't need to re-verify

Direct reads of every other file in `cache_analysis/` during the design phase confirmed:

- **`context.py` (245 LOC)** — already a deep module: immutable `AnalysisContext` + 4 methods (`trace_event_for`, `cost_usd_for_node`, `resolve_ref_value`, `parameters_for_workflow`). No change needed.
- **`token_estimation.py` (419 LOC)** — already a deep module: 4-tier hierarchy (trace → memo → estimator → heuristic) with asymmetric fall-through. No change needed.
- **`cost_estimation.py` (561 LOC)** — already a deep module: row-level projections + actually-paid + tri-state contract. 561 LOC is *earned* by the math; not a refactor target.
- **`warning_catalog.py` (1,171 LOC)** — single-source-of-truth catalog: 14 frozen catalog rows + factory + dispatch. ~75% data, ~25% logic. Splitting would fragment a SSoT.
- **`render_text.py` (1,008 LOC)** — orchestrator + 7 section renderers with clean seams. Splittable later if it grows; not in scope here.
- **`cache_render.py` (245 LOC, in `core/`, not `cache_analysis/`)** — deep module, single seam for cache rendering at the LiteLLM adapter. Outside this task's scope; do not touch.
- **`trace_tree.py` (359 LOC, in `core/`, not `cache_analysis/`)** — shared trace-walking primitive with 5 consumers across 4 packages. Correct placement. Outside scope.

Engine-side touches from task 159 (`plan_node.py`, `instrumentation.py`, `batch_executor.py`, `engine.py`, `compiler.py`, `cache.py`, `namespaced_store.py`, `workflow_trace.py`) were verified clean during design. Outside this task's scope; do not touch.
