# Prompt Cache Analysis Module

Static and trace-based analysis of a workflow's LLM provider prompt-cache plan.
This package powers:

- `pflow analyze-cache`
- the `pflow run --dry-run` cache nudge
- the MCP `analyze_cache` tool

The analyzer reads workflow IR plus optional execution trace/memo evidence and
emits a `CacheAnalysis` value plus cache-related `Diagnostic`s.

## Disambiguation: Two Cache Concepts

| Concept | Per-node field | Substrate | Effect |
|---|---|---|---|
| **Memoization** | `cache: bool` | `runtime/cache.py::MemoizationCache` SQLite at `~/.pflow/cache/cache.db` | Skips pflow node execution entirely on memo hits |
| **Provider prompt cache** | `prompt_cache: [...]` plus `## Cache` chunks | `core/prompt_cache.py` and the LLM adapter | Sends provider cache markers so the LLM provider can reuse a prompt prefix |

`prompt_cache_analysis/` is only about provider prompt caching. The CLI
`--no-cache` flag controls memoization and is orthogonal to this package.

The two layers meet in two places:

- declared `prompt_cache` content participates in the memo config hash so a
  workflow upgraded to provider prompt caching does not reuse stale memo output;
- the discrepancy stage predicts memo config hashes and compares them with trace
  events to detect analyzer/runtime divergence.

## Cache-Key Namespaces

| Name | Meaning | Owner |
|---|---|---|
| Memo config hash | MD5 of resolved per-node config. Decides pflow memo hits. | `runtime/engine/instrumentation.py::compute_node_config` |
| Provider prompt cache key | MD5 of rendered provider cache-block bytes. Sent to OpenAI for sticky routing. | `nodes/llm/llm.py::_build_openai_cache_kwargs` |
| Provider token counts | `cache_creation_input_tokens` and `cache_read_input_tokens` from trace events. | Runtime LLM adapter, normalized by `core.llm_usage` |

Do not conflate provider prompt-cache keys with pflow memo config hashes.

## Module Structure

```
src/pflow/core/prompt_cache_analysis/
├── __init__.py                  # public API re-exports
├── analyze.py                   # thin orchestrator and orchestration-only helpers
├── types.py                     # public dataclasses, projection helpers, row contract helpers
├── trace_loading.py             # trace I/O, autoload/listing, trace indexing, trace aggregation
├── context.py                   # AnalysisContext input bundle
├── sub_workflow_walker.py       # sub-workflow walker data primitive
├── token_estimation.py          # trace -> memo -> estimator -> heuristic token hierarchy
├── cost_estimation.py           # row-level cost projection and actually-paid aggregation
├── below_min_tokens_detector.py # shared below-threshold detector
├── warning_catalog.py           # stable warning catalog and factories
├── rendering/
│   ├── CLAUDE.md                # documented direct-test helper surface
│   ├── __init__.py              # render_json/render_text/summarize public re-exports
│   ├── json.py                  # JSON projection of CacheAnalysis
│   ├── text.py                  # text projection and section renderers
│   ├── cross_workflow_edits.py  # paste-ready cross-workflow cache-block edit text
│   ├── traces_list.py           # trace-list text/JSON projection
│   ├── summarize.py             # one-line dry-run nudge Diagnostic
│   └── views.py                 # blocking/recommended action projections
└── stages/
    ├── __init__.py              # intentionally docstring-only
    ├── row_builder.py           # PerCallRow construction primitives (row + IR helpers; orchestration moved out)
    ├── per_call_pipeline.py     # multi-stage orchestrator: rows + warnings + cross-workflow attachment
    ├── warnings.py              # per-node warning visitors and shadow-cost enrichment
    ├── suggestions.py           # suggested blocks, padding advisories, chunk pricing helpers
    ├── fragmentation.py         # model/system cache fragmentation detection
    ├── partial_declarations.py  # incomplete prompt_cache declaration detection
    ├── cross_workflow.py        # analytical cross-workflow findings
    ├── summary.py               # summary, confidence, rollups, trace-dependent filtering
    └── discrepancy/
        ├── __init__.py          # narrow discrepancy re-exports
        ├── CLAUDE.md            # documented direct-test helper surface
        ├── predict.py           # cache-key prediction with lazy runtime imports
        └── diagnose.py          # trace discrepancy diagnostics
```

## Public API

Package-level imports are the stable external surface:

```python
from pflow.core.prompt_cache_analysis import (
    JSON_FORMAT_VERSION,
    CacheAnalysis,
    TraceListEntry,
    analyze,
    list_traces_for_workflow,
    render_json,
    render_text,
    summarize,
    summarize_from_analysis,
)
```

Public report dataclasses live in `types.py`. Do not import dataclasses from
`analyze.py`; `analyze.py.__all__` intentionally exports only `analyze`.

## Pipeline

`analyze.py::analyze()` is the integration point. It should stay small and read
as orchestration:

1. Build `AnalysisContext` and resolve trace scope through `trace_loading.py`.
2. Walk sub-workflows through the root `sub_workflow_walker.py` data primitive.
3. Predict memo cache keys through `stages.discrepancy.predict`.
4. Build per-call rows through `stages.per_call_pipeline._build_per_call_rows_and_warnings`.
5. Emit stage findings: warnings, suggested blocks/padding, fragmentation,
   partial declarations, cross-workflow findings, discrepancy diagnostics.
6. Build summary and rollups through `stages.summary`.
7. Return `CacheAnalysis`.

Stage modules may import shared data from `types.py`, trace helpers from
`trace_loading.py`, and row/suggestion helpers where the import graph already
flows one way. Stage modules must not import private helpers from `analyze.py`.

## Types And Row Contract

`types.py` owns the analyzer's public vocabulary: `CacheAnalysis`,
`AnalysisSummary`, `PerCallRow`, `CacheProjection`, `SuggestedBlock`,
`RecommendedAction`, `TraceListEntry`, and related dataclasses.

`PerCallRow` token fields are per-call by contract. Workflow-level consumers
multiply with `invocation_count_for(row)`, which also lives in `types.py`.
`row.cost_usd` is the deliberate exception: it is cohort actually-paid trace
cost, sourced through `AnalysisContext.cost_usd_for_node()` / `TraceTree`, not a
per-call estimate.

Rows expose four projection objects:

- `cache_configured`: what the workflow asks runtime to cache before provider
  gates;
- `cache_active`: configured tokens believed to remain provider-effective;
- `cache_ready`: tokens active/configured/unlockable with a direct cache edit;
- `cache_opportunity`: maximum provable unrealized per-call cache upside.

Only `cache_active` feeds headline cost math.

`PerCallRow.__post_init__` is deliberately small. It only derives
`cached_now_tokens_estimated` from trace cache-token splits or, for
trace-backed declared-cache rows, from the trace cacheable-token fallback. It
must not synthesize projection objects from `cacheable_tokens_estimated`; tests
that need projection state should construct `CacheProjection` values explicitly.

## Trace Loading

`trace_loading.py` owns trace autoload/listing, trace-scope classification,
trace execution indexing, LLM-call aggregation, and trace-warning rehydration.

Trace staleness is represented as:

- `summary.trace_workflow_relationship`
- `summary.trace_model_drift_count`
- trace notes in `analysis.notes`

`pflow analyze-cache <workflow> --list-traces` uses
`list_traces_for_workflow()`, which annotates the would-be autoloaded trace and
model drift. Empty listings exit 0 because "no traces yet" is valid discovery.

## Runtime Trace Contract

The analyzer reads trace fields written by the engine:

| Field | Runtime producer | Analyzer consumer |
|---|---|---|
| `event["cache_source"]` | memo/in-process cache instrumentation | discrepancy diagnosis and trace cost summation |
| `event["cache_key"]` | memo config hash instrumentation | discrepancy diagnosis |
| `event["cache_age_sec"]` | memo-hit instrumentation | trace report display |
| `trace["workflow_path"]` | `WorkflowTraceCollector` | trace autoload/listing and cross-trace correlation |

Traces are written as **JSONL** on disk (Task 133: a `meta` line + one line per event +
`run.complete`/`blobs` trailers) and read through `pflow.core.trace_io.load_trace_file`, which
reconstructs the nested dict described above — the field contract is unchanged. 2.x traces remain
readable when explicitly passed with `--from-trace` (legacy single-object traces too, via dual-read).
Autoload is intentionally stricter and skips traces that do not match the current root workflow/model
context.

## Discrepancy Stage

`stages/discrepancy/` predicts memo cache keys and compares them with trace
events. It reaches into the runtime dry-run planning substrate (`plan_node`,
`create_planner_shared`, `compile_workflow`) and `TraceTree` — those imports stay
lazy so `import pflow.core.prompt_cache_analysis` stays cheap (no eager LiteLLM)
unless prediction actually runs. The prediction ↔ diagnosis seam and its
direct-test surface are documented in `stages/discrepancy/CLAUDE.md`.

## Validation Delegation

`analyze.py::_run_full_validation` calls the unified
`WorkflowValidator.validate()` pipeline. The analyzer does not reimplement cache
structural validation.

Canonical cache validation emitters live in `core/workflow/data_flow.py`:

| Warning ID | Producer |
|---|---|
| `cache.invalid-on-non-llm` | non-LLM prompt_cache rejection |
| `cache.order-mismatch` | per-node declaration ordering |
| `cache.unused-chunk` | top-level unused cache chunk |
| `cache.prompt-body-duplicates-cache` | prompt/cache overlap |
| `cache.prompt-body-shadows-cache` | prompt/cache shadowing |
| `llm.thinking-temperature-mismatch` | thinking/temperature compatibility |

The analyzer preserves domain focus at the aggregation/rendering boundary:
`stages.summary._is_cache_focused` drives summary counts and
`rendering.views._is_cache_focused_for_advisory` drives action lists.

## Rendering

Read-only projections of `CacheAnalysis`; `rendering/CLAUDE.md` has the per-file
map and the documented formatter test surface. Two package-level cycle invariants
worth not breaking:

- `rendering/__init__.py` re-exports lazily (via `__getattr__`). An eager
  re-export creates an `analyze → stages.cross_workflow → rendering → summarize →
  analyze` cycle. Keep it lazy.
- `rendering/views.py` imports `RecommendedAction` from `types.py` at module
  scope; that earlier circular-import workaround is gone — don't reintroduce it.

## Warning Catalog

`warning_catalog.py` is the source of truth for stable warning IDs, headlines,
message templates, and recommended-action priority. `Diagnostic.id` is the
dedup key when present; legacy diagnostics without an ID still dedup by message.

Adding a new warning ID is an API decision and needs design review. Do not add a
new ID just to vary wording when an existing ID describes the same condition.

## External Consumers

| Consumer | Imports |
|---|---|
| `cli/commands/analyze_cache.py` | package-level `analyze`, `render_json`, `render_text`; direct `rendering.traces_list`; direct `trace_loading.list_traces_for_workflow` |
| `execution/runner.py` | package-level `analyze`, `summarize_from_analysis` |
| `mcp_server/services/execution_service.py` | package-level `analyze`, `render_json` |
| `core/workflow/data_flow.py` | `warning_catalog.make_diagnostic` |
| `nodes/llm/llm.py` | below-min detector and warning catalog |
| `runtime/engine/engine.py` | below-min detector, context, token estimation, warning catalog |

## Where To Add A New Feature

| Goal | Edit |
|---|---|
| Add or change the public report shape | `types.py`, then `rendering/json.py` and renderer tests |
| Add a cache-related warning | `warning_catalog.py`, the owning stage or `data_flow.py`, plus per-ID tests |
| Change per-call row construction or projection components | `stages/row_builder.py` |
| Change per-call pipeline orchestration (row + warning + cross-workflow assembly) | `stages/per_call_pipeline.py` |
| Change per-node warning visitors | `stages/warnings.py` |
| Change suggested `## Cache` blocks, padding advisories, chunk pricing, or template-ref grouping | `stages/suggestions.py` |
| Change model/system fragmentation findings | `stages/fragmentation.py` |
| Change incomplete `prompt_cache:` declaration detection | `stages/partial_declarations.py` |
| Change analytical cross-workflow findings | `stages/cross_workflow.py` |
| Change cross-workflow recommendation edit text | `rendering/cross_workflow_edits.py` |
| Change sub-workflow walking semantics | root `sub_workflow_walker.py` |
| Change trace autoload, trace listing, trace aggregation, or trace execution indexing | `trace_loading.py` |
| Change discrepancy prediction | `stages/discrepancy/predict.py` |
| Change discrepancy diagnosis | `stages/discrepancy/diagnose.py` |
| Change summary counts, confidence, trace-dependent filtering, or rollups | `stages/summary.py` |
| Change rendered text output | `rendering/text.py` |
| Change rendered JSON output | `rendering/json.py` |
| Change dry-run nudge text | `rendering/summarize.py` |

## See Also

- `.taskmaster/tasks/task_159/task-159.md` - prompt caching feature spec.
- `.taskmaster/tasks/task_160/` - structural refactor plan and progress log.
- `src/pflow/core/workflow/CLAUDE.md` - structural cache validation.
- `src/pflow/runtime/CLAUDE.md` - runtime cache-key prediction substrate.
