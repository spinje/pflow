# Architecture Analysis — analyze.py decomposition

Verified against the current codebase as of 2026-05-21 (commit 23c1ddb8). Replaces the stale `end-state-architecture.md`, `migration-plan.md`, and `verified-non-issues.md` which were written against a 3,293-LOC version of the file.

## Current state

- `analyze.py`: **8,570 LOC**, 210 module-scope functions, 27 type definitions
- Total package: **15,943 LOC** across 14 source files
- Test suite: **31,288 LOC** across 18 test files
- Production consumers: **6 files** with 15 import lines

## Cluster structure of analyze.py

The file has 11 named clusters separated by `# ----` comments:

| Cluster | Lines | LOC | Outbound deps | Extractability |
|---------|-------|-----|---------------|----------------|
| A: Projection Helpers | 167–327 | 161 | 1 (_safe_pct from F12) | HIGH (moves with types) |
| B: Orchestrator | 979–1306 | 328 | calls everything | stays (integration nexus) |
| C: Memo Cache | 1309–1346 | 38 | 0 | HIGH |
| D: Trace Loading | 1347–1716 | 370 | 2 (E helpers) | HIGH |
| E: Pipeline Helpers | 1717–2949 | 1,233 | 6 (to F, J) | LOW (grab-bag, stays with orchestrator) |
| F: Per-Node Analysis | 2950–6022 | 3,072 | 5 (to A, J) | MEDIUM (13 sub-groups) |
| G: Cross-WF Walking | 6023–7336 | 1,314 | 6 (to E, F, J) | HIGH (coherent concern) |
| H: Trace Discrepancy | 7337–8050 | 714 | 1 (_edge_child_paths) | HIGH |
| I: Confidence Aggregation | 8051–8081 | 31 | 0 | HIGH (absorbs into summary) |
| J: Summary Builder | 8082–8527 | 446 | 1 (_is_cache_focused from F) | MEDIUM |
| K: Gemini Note | 8528–8570 | 43 | 0 | HIGH (absorbs into summary) |

## Cluster F internal structure (3,072 LOC)

| Sub-group | Lines | LOC | Primary consumer |
|-----------|-------|-----|-----------------|
| F1: Row construction | 2955–3195 | 240 | row_builder |
| F2: Cross-wf projection | 3197–3330 | 140 | row_builder |
| F3: Provider utils | 3332–3370 | 40 | row_builder |
| F4: Batch prefix/tail | 3372–3527 | 155 | row_builder |
| F5: Projection builders | 3455–3701 | 300 | row_builder |
| F6: Token estimation | 3703–3897 | 195 | row_builder |
| F7: Warning visitors | 3899–4455 | 560 | warnings |
| F8: Node utilities | 4458–4527, 5442–5447 | 70 | row_builder (shared) |
| F9: Suggested blocks | 4529–4825 | 295 | suggestions |
| F10: Template refs | 4827–4917 | 90 | suggestions |
| F11: Body cleanup | 5449–5505 | 60 | suggestions |
| F12: Cost/savings/fragmentation | 4920–5440, 5960–6021 | 540 | split: fragmentation + suggestions |
| F13: Partial declarations | 5507–5867 | 315 | partial_declarations |

## Import cycle analysis

### Confirmed cycle (resolved)

`row_builder.py ↔ suggestions.py`: `_detect_candidate_subsets` (proposed for row_builder) calls `_cache_item_names` and `_collect_llm_template_references` (in suggestions); `_collect_llm_template_references` calls `_node_inputs` (in row_builder).

**Resolution**: `_detect_candidate_subsets` stays in the orchestrator. It's called from `_build_per_call_rows_and_warnings` — orchestration, not construction.

### Verified cycle-free import graph (post-resolution)

```
types.py             ← everything (leaf)
trace_loading.py     ← cross_workflow, discrepancy, orchestrator (leaf)
row_builder.py       ← warnings, suggestions, partial_decl, cross_workflow
suggestions.py       ← partial_decl, cross_workflow, warnings, orchestrator
warnings.py          ← orchestrator
partial_decl.py      ← orchestrator
cross_workflow.py    ← orchestrator
summary.py           ← orchestrator
discrepancy/         ← orchestrator
```

All edges are one-directional. No cycles.

## Shared utility placement

12 functions called from 3+ clusters. Verified placement:

| Function | LOC | Line | Destination | Callers |
|----------|-----|------|-------------|---------|
| `invocation_count_for` | 15 | 8109 | types.py | 6 clusters + cost_estimation.py |
| `_safe_pct` | 4 | 6017 | types.py | 4 clusters |
| `_node_inputs` | 7 | 3890 | row_builder.py | 6 modules |
| `_batch_aliases` | 5 | 5442 | suggestions.py* | 3 modules |
| `_cache_items` | 8 | 5941 | suggestions.py* | 3 modules |
| `_cache_item_names` | 2 | 5951 | suggestions.py* | 3 modules |
| `_edge_child_paths` | 36 | 1992 | trace_loading.py | 4 modules |
| `_template_root_segment` | 15 | 4903 | suggestions.py | 3 modules |
| `_collect_llm_template_references` | 21 | 4827 | suggestions.py | 3 modules |
| `_estimate_token_savings_usd` | 5 | 6003 | suggestions.py | 5 modules |
| `_input_rate` | 5 | 6010 | suggestions.py | 3 modules |
| `_estimate_chunk_tokens` | 3 | 5955 | suggestions.py | 2 modules |

*`_batch_aliases`, `_cache_items`, `_cache_item_names` are grouped with suggestions as their primary consumer. `partial_declarations.py` imports them from there.

## Lazy import chain verification

The `--dry-run` → `summarize` → `analyze` import chain does NOT eagerly import LiteLLM:

1. `__init__.py` uses eager re-exports (no lazy mechanism)
2. `analyze.py:65` eagerly imports `TemplateResolver` from `pflow.runtime` — triggers runtime/compilation/engine subsystem but NO LiteLLM
3. `summarize.py:44` eagerly imports `analyze` from `.analyze`
4. The discrepancy cluster's lazy imports (plan_node, compile_workflow, create_planner_shared, Registry) only fire when the functions are called
5. `stages/__init__.py` re-exporting from discrepancy would be safe — Python re-exports don't trigger lazy imports inside the target

**One hygiene item**: `analyze.py:65`'s eager `TemplateResolver` import should become lazy in whichever stage file inherits it, matching `context.py` and `token_estimation.py`'s pattern.

## Prompt cache feature relationship

5 feature files (1,115 LOC total) in `core/`:

| File | LOC | Purpose |
|------|-----|---------|
| `prompt_cache.py` | 503 | Rendering primitives, block builders |
| `prompt_refs.py` | 128 | Template ref classification |
| `llm_capabilities.py` | 169 | Per-model capability table |
| `cache_overlap.py` | 193 | Cache/prompt overlap detection |
| `cache_ttl.py` | 122 | TTL parsing |

**Dependency direction**: strictly one-way. `prompt_cache_analysis/` imports from these files, never the reverse. No refactoring needed. Three private symbols (`_resolve_chunk_value`, `_resolve_static_prefix_for_cache`, `_CHUNK_ABSENT`) from `prompt_cache.py` are imported externally — making them public is a separate follow-up.

## Dataclass inventory (27 type definitions in analyze.py)

### Move to types.py (20 public + 1 TypedDict)

`CacheProjectionComponent`, `CacheProjection`, `CrossWorkflowInputContribution`, `PerCallRow`, `ProjectionExclusion`, `RecommendedAction`, `SuggestedBlockChunk`, `PerNodeThresholdEntry` (TypedDict), `SuggestedBlock`, `CrossWorkflowFindings`, `SubWorkflowRollupEntry`, `SubWorkflowRollup`, `TraceExecutionIndex`, `CostDelta`, `TraceUnexecutedLLMRow`, `TraceListEntry`, `AnalysisSummary`, `CacheAnalysis`

Plus: `_PromptStaticTailFinding` (private, used only by warnings stage — could stay with warnings or go with types; implementer's call).

### Stay with stage files (6 private)

| Dataclass | Stage file |
|-----------|-----------|
| `_PerCallRowsResult` | orchestrator (analyze.py) |
| `_PartialDeclarationFinding` | stages/partial_declarations.py |
| `_RowCrossWorkflowCandidate` | orchestrator (analyze.py) |
| `_SubWorkflowCacheCandidate` | stages/cross_workflow.py |
| `_ChildCacheRefUse` | stages/cross_workflow.py |
| `_GroupedConsumerProjection` | stages/cross_workflow.py |
| `_SubWorkflowCacheGroup` | stages/cross_workflow.py |
| `_PredictScaffold` | stages/discrepancy/predict.py |

## What stays in analyze.py (~900 LOC)

After extraction, the orchestrator contains:

- `analyze()` function (~328 LOC)
- `_build_per_call_rows_and_warnings` + row assembly helpers (~200 LOC)
- `_detect_candidate_subsets` (~30 LOC, kept here to avoid cycle)
- Cross-workflow candidate infrastructure (~160 LOC)
- Parameter resolution: `_build_parameters_by_workflow`, `_resolve_child_input_value` (~150 LOC)
- Model drift: `_detect_per_node_model_drift`, `_row_model_drift` (~80 LOC)
- Shadow enrichment: `_enrich_shadow_warnings_with_costs` (~100 LOC)
- Sub-workflow rollup (~80 LOC)
- Misc IR helpers only used by orchestrator (~50 LOC)
- `_PerCallRowsResult`, `_RowCrossWorkflowCandidate` private dataclasses

These are all single-use functions called only from the orchestrator. They represent the pipeline glue that connects trace loading → stages → summary.
