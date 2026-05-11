# End-State Architecture

The complete file-by-file plan. Use this as the source of truth for what moves where.

## Source statistics (verified)

- `src/pflow/core/cache_analysis/`: **7,865 LOC across 12 source files**
- `analyze.py`: **3,293 LOC** — the file being decomposed
- Test suite: **11,478 LOC across 12 test files** (`tests/test_core/test_cache_analysis_*.py` × 10, `tests/test_cli/test_analyze_cache.py`, `tests/test_mcp_server/test_analyze_cache_tool.py`)

## Final directory layout

```
src/pflow/core/cache_analysis/
├── __init__.py                  # public API re-exports
├── CLAUDE.md                    # NEW — package navigation index
│
├── analyze.py                   # ~450 LOC final (down from 3,293)
├── types.py                     # NEW — 9 public dataclasses (~294 LOC)
├── context.py                   # unchanged (245 LOC)
├── cross_workflow.py            # unchanged (416 LOC) — the WALKER, shared infrastructure
├── token_estimation.py          # unchanged (419 LOC)
├── cost_estimation.py           # unchanged (561 LOC)
├── warning_catalog.py           # unchanged (1,171 LOC)
│
├── stages/
│   ├── __init__.py
│   ├── per_call.py              # ~410 LOC — PerCallRow assembly
│   ├── rules.py                 # ~254 LOC — collapse 4 per-node visitors → 1 walk
│   ├── suggestions.py           # ~405 LOC — greenfield + chunk-pricing helpers
│   ├── padding.py               # ~106 LOC — absorbs padding_advisor.py + analyze.py glue
│   ├── cross_workflow.py        # ~367 LOC — analytical stage (consumes walker output)
│   ├── summary.py               # ~250 LOC — gathers scattered summary helpers
│   └── discrepancy/
│       ├── __init__.py
│       ├── predict.py           # ~280 LOC
│       └── diagnose.py          # ~247 LOC
│
└── rendering/
    ├── __init__.py
    ├── text.py                  # was render_text.py (1,008 LOC, unchanged)
    ├── json.py                  # was render_json.py (399 LOC, unchanged)
    ├── views.py                 # was view_helpers.py (143 LOC) + the dedup'd _workflow_short_name
    └── summarize.py             # moved from cache_analysis/summarize.py (113 LOC)
```

## Cluster → destination map for `analyze.py`

Source line ranges verified against the file at HEAD of `feat/prompt-caching` branch. LOC estimates rounded.

| # | Cluster | Source lines | LOC | Destination |
|---|---|---|---|---|
| 1 | Public dataclasses (`PerCallRow`, `RecommendedAction`, `SuggestedBlockChunk`, `SuggestedBlock`, `CrossWorkflowFindings`, `SubWorkflowRollupEntry`, `SubWorkflowRollup`, `AnalysisSummary`, `CacheAnalysis`) + private `TraceExecutionIndex` | 81–374 | ~294 | **`types.py`** |
| 2 | Public `analyze()` orchestrator | 382–568 | ~187 | stays in `analyze.py` |
| 3 | Trace + memo I/O loaders (`_default_memo_cache`, `_load_trace_explicit`, `_autoload_trace`, `_resolve_trace_data`, `_extract_declared_chunks`, `_extract_cache_ttl`, `_edge_child_paths`) | 576–756 | ~181 | stays in `analyze.py` |
| 4 | Per-call row assembly (`_build_per_call_rows_and_warnings`, `_build_per_call_row`, `_estimate_row_tokens`, `_tokenize_declared_cache_chunks`, `_resolve_prompt_for_tokenization`, `_extract_unique_refs`, `_build_shared_store_for_refs`, `_detect_candidate_subsets`, `_row_has_real_data_in_analyze`) | 963–1372 | ~410 | **`stages/per_call.py`** |
| 5 | Per-node warning visitors — collapse 4 into 1 walk: `_per_node_warnings`, `_batch_prewarm_recommendations`, `_dynamic_before_static_warnings`, `_opaque_prompt_warnings`, plus helpers `_resolve_through_batch_alias`, `_estimate_batch_size` | 1375–1628 | ~254 | **`stages/rules.py`** |
| 6 | Suggested blocks + chunk-level pricing helpers (`_starter_prose_for_ref`, `_populate_suggested_blocks`, `_collect_llm_template_references`, `_template_root_segment`, `_consolidate_to_root_advisories`, `_collect_consolidate_candidates`, `_group_subpaths_by_root`, `_check_root_for_consolidation`, `_batch_aliases`, `_is_batch_scoped_ref`, `_estimate_chunk_tokens`, `_savings_for_shared_ref`, `_estimate_token_savings_usd`, `_input_rate`, `_safe_pct`) | 1631–1989 + 2082–2127 | ~405 | **`stages/suggestions.py`** |
| 7 | Padding advisories (`_emit_padding_advisories`) + the entire `padding_advisor.py` (`PaddingCandidate`, `compute_padding_advisories`) | analyze.py 1991–2033, padding_advisor.py 1–63 | ~106 | **`stages/padding.py`** |
| 8 | Cache validator findings glue (`_cache_validator_findings`, `_cache_items`, `_cache_item_names`) | 2035–2080 | ~46 | stays in `analyze.py` |
| 9 | Cross-workflow analytical stage (`_build_cross_workflow_findings`, `_cross_workflow_prose_mismatches`, `_ValueFlowCandidate`, `_value_flow_candidate`, `_build_destinations_for_group`, `_emit_value_flow_groups`, `_count_llm_nodes_referencing_path`, `_items_by_name`, `_iter_llm_events`) | 2134–2500 | ~367 | **`stages/cross_workflow.py`** |
| 10 | Discrepancy — predict half (`_predict_cache_keys`, `_predict_one_workflow`, `_PredictScaffold`, `_build_predict_scaffold`, `_predict_node_with_scaffold`, `_predict_node_cache_key`, `_enumerate_compiled_bare_nodes`, `_is_llm_node`) | ~2502–2780 | ~280 | **`stages/discrepancy/predict.py`** |
| 11 | Discrepancy — diagnose half (`_emit_discrepancy_diagnostics`, `_predicted_key_for_event`, `_compute_predicted_label`, `_attribute_root_cause`, `_aggregate_and_cap_discrepancies`) | ~2780–3028 | ~247 | **`stages/discrepancy/diagnose.py`** |
| 12 | Summary builders (scattered): `_build_trace_execution_index`, `_build_sub_workflow_rollup`, `_has_cross_workflow_truncation`, `_count_llm_nodes`, `_build_parameters_by_workflow`, `_resolve_child_input_value`, `_aggregate_confidence`, `_build_summary`, `_unavailable_models_by_workflow`, `_safe_pct_or_none`, `_maybe_append_gemini_note`, `_GEMINI_TELEMETRY_NOTE` | 759–961, 3035–3192, 3194–3211, 3243–3270 | ~250 | **`stages/summary.py`** |
| — | `_build_recommended_actions` (compatibility shim that delegates to `view_helpers`) | 3219–3235 | ~17 | **DELETE** — callers import from `rendering/views.py` directly |
| — | `_workflow_short_name` (duplicate of `render_text.py:721`) | 2911 | small | **DELETE** — single canonical version lives in `rendering/views.py` |

**Sanity check**: 187 (orchestrator) + 181 (I/O loaders) + 46 (validator glue) + small IR utilities ≈ **450 LOC** remaining in `analyze.py`. 7× reduction from 3,293.

## Rendering subdirectory

| File | Source | LOC | Notes |
|---|---|---|---|
| `rendering/text.py` | move `render_text.py` | 1,008 | No content change. Imports update to use `..types` for dataclasses. |
| `rendering/json.py` | move `render_json.py` | 399 | Same. |
| `rendering/views.py` | move `view_helpers.py` + add canonical `_workflow_short_name` | ~155 | The lazy-import workaround at line 84 disappears (imports `RecommendedAction` from `..types` at module scope). |
| `rendering/summarize.py` | move `summarize.py` | 113 | Imports `analyze` from `..analyze` (or `..` if the package re-exports it). |
| `rendering/__init__.py` | NEW | small | Re-exports `render_text`, `render_json`, `summarize`, `summarize_from_analysis` for the package `__init__.py`. |

## `__init__.py` final shape

The package's `__init__.py` re-exports:

- **Functions**: `analyze`, `summarize`, `summarize_from_analysis`, `render_text`, `render_json`
- **Public dataclasses** (from `types.py`): `CacheAnalysis`, `AnalysisSummary`, `PerCallRow`, `RecommendedAction`, `SuggestedBlock`, `SuggestedBlockChunk`, `CrossWorkflowFindings`, `SubWorkflowRollup`, `SubWorkflowRollupEntry`
- **Constants**: `JSON_FORMAT_VERSION`, `JSON_FORMAT_VERSION_MAJOR`

These match the names production consumers already import. Internals (catalog dicts, `make_diagnostic`, helper functions) remain importable from sub-modules but are not promoted to package root.

## External imports affected

### Production code (must not break)
- `src/pflow/cli/commands/analyze_cache.py:90` — `from pflow.core.cache_analysis import analyze, render_json, render_text` ✅ stable through `__init__.py`
- `src/pflow/execution/runner.py:440` — `from pflow.core.cache_analysis import analyze, summarize_from_analysis` ✅ stable
- `src/pflow/mcp_server/services/execution_service.py:394` — `from pflow.core.cache_analysis import analyze, render_json` ✅ stable
- `src/pflow/core/workflow/data_flow.py:945` — `from pflow.core.cache_analysis.warning_catalog import make_diagnostic` ✅ `warning_catalog.py` doesn't move

### Test code (will need updates as part of this task)
- `tests/test_cli/test_analyze_cache.py:106` — package-level imports, stable
- `tests/test_mcp_server/test_analyze_cache_tool.py:17, 70, 101, 125` — package-level + `warning_catalog.CACHE_WARNING_CATALOG`, both stable
- `tests/test_core/test_sub_workflow_resolver.py:309` — `from pflow.core.cache_analysis.analyze import _count_llm_nodes_referencing_path` — **WILL BREAK** when this helper moves to `stages/cross_workflow.py`. Update the import.
- `tests/test_core/test_sub_workflow_resolver.py:310` — `from pflow.core.cache_analysis.cross_workflow import walk_cross_workflow` ✅ stable
- `tests/test_core/test_prompt_cache_validation.py:881` — `warning_catalog.CACHE_WARNING_CATALOG` ✅ stable

### Cache-analysis test files (12 of them, ~36 private-symbol import sites)

A complete audit of which private symbols each test file imports from `analyze.py` and `render_text.py` was done before this spec. Summary by test file:

| Test file | Private imports from analyze.py | Other private |
|---|---|---|
| `test_cache_analysis_analyze.py` | `_aggregate_confidence`, `_build_summary`, `_maybe_append_gemini_note`, `_estimate_row_tokens` (×3), `_build_recommended_actions` (×5), `_build_parameters_by_workflow` | `_render_summary` (×4), `_format_cost` (×2) from render_text |
| `test_cache_analysis_per_id_emission.py` | `_compute_predicted_label`, `_build_predict_scaffold`, `_predict_cache_keys` (×3), `_iter_llm_events` (×2), `_aggregate_and_cap_discrepancies` (×3), `_build_parameters_by_workflow`, `_predict_node_cache_key` | — |
| `test_cache_analysis_cost_estimation.py` | — | `_pricing_from_dict` from cost_estimation |
| `test_cache_analysis_token_estimation.py` | — | `_find_llm_event` from token_estimation |
| `test_cache_analysis_warnings.py` | — | `_compute_distribution_clause` from warning_catalog |

Each import path updates to follow the moved symbol. `_build_recommended_actions` callers update to `from pflow.core.cache_analysis.rendering.views import build_recommended_actions` (the public name; the private shim is deleted).

## Pure dedups landing with the refactor

1. **`_workflow_short_name`** — duplicate at `analyze.py:2911` and `render_text.py:721`. Single canonical version in `rendering/views.py`. Discrepancy diagnose-side imports it from there.
2. **`_iter_llm_events`** — defined in `analyze.py:2456` but used only by tests (no production caller in the cluster after the refactor). Move to a shared test helper or delete and update its test callers to use `TraceTree.iter_llm_leaves` directly.
3. **`_build_recommended_actions`** — `analyze.py:3219` is a 17-LOC compatibility shim that delegates to `view_helpers.build_recommended_actions`. Delete the shim; its callers (5 test sites in `test_cache_analysis_analyze.py`) update to import directly from `rendering/views.py`.

## Discrepancy split: the boundary

The discrepancy cluster (lines ~2502–3028, ~527 LOC) splits cleanly into predict + diagnose because:

- `_emit_discrepancy_diagnostics` makes ONE call into the predict half: `_predict_cache_keys(...)` returns `dict[(workflow_path, node_id), str]` plus a `list[str]` of notes. Pure data.
- `_PredictScaffold` is private to the predict half — never crosses the boundary.
- The diagnose half walks the trace itself (via `TraceTree`) and reads `cw_result.irs_by_workflow` directly — no shared state with predict.
- Reverse calls (diagnose → predict): zero.

After the split:
- `stages/discrepancy/predict.py` exports `_predict_cache_keys` (and optionally `_predict_node_cache_key` for tests).
- `stages/discrepancy/diagnose.py` imports `_predict_cache_keys` at module scope (no lazy import — no cycle).
- `stages/discrepancy/__init__.py` re-exports `_emit_discrepancy_diagnostics` for the orchestrator.

## CLAUDE.md outline

What to include in the new `cache_analysis/CLAUDE.md`:

1. **Module structure** — the directory tree above + one-line purpose per file.
2. **Public API** — what's re-exported from `__init__.py` (matches the list above).
3. **The pipeline** — `analyze()` chains stages in this order: (list them based on actual call sequence in `analyze()`).
4. **Runtime → analyzer trace contract** — the 2.1.0 fields the analyzer reads: `cache_source`, `cache_key`, `cache_age_sec`, `workflow_path`. Reference the schema-of-record in `runtime/workflow_trace.py`.
5. **Where to add a new warning** — (a) catalog entry in `warning_catalog.py`, (b) emit site in the relevant stage, (c) test in the corresponding `tests/test_core/test_cache_analysis_*.py`. Reference DD#27/29 from task-159.md for the "warning IDs are stable forever" contract.
6. **Sub-workflow walking** — `cross_workflow.py` is shared infrastructure (4 consumers in `analyze.py`), not a stage. `stages/cross_workflow.py` is one of those consumers (the analytical one).
7. **Discrepancy stage's lazy imports** — explain why `stages/discrepancy/predict.py` lazy-imports the runtime/execution modules: `cache_analysis.__init__` re-exports `summarize`, called on every `pflow run --dry-run`. Eager runtime imports would add ~700ms LiteLLM startup cost to every dry-run.
