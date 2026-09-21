# Prompt Cache Analysis

`analyze.py::analyze()` powers `analyze-cache`, the dry-run cache nudge, and the
MCP analysis tool. External callers use package-level exports; report dataclasses
live in `types.py`, not `analyze.py`.

## Directory map

```text
prompt_cache_analysis/
├── analyze.py          # Orchestration
├── context.py          # Analysis inputs
├── types.py            # Report contracts
├── trace_loading.py    # Trace evidence
├── stages/             # Analytical stages
│   └── discrepancy/    # Memo-key prediction and diagnosis
└── rendering/          # Output projections
```

## Task Navigation

| Task | Owner |
|---|---|
| Change analysis orchestration | `analyze.py`; input bundle in `context.py::AnalysisContext` |
| Change report shape or row contracts | `types.py`, then JSON projection and renderer tests |
| Add/change a warning or action priority | `warning_catalog.py` and the owning stage/validator |
| Change per-call rows or projections | `stages/row_builder.py` |
| Change row/warning/cross-workflow assembly | `stages/per_call_pipeline.py` |
| Change per-node warnings | `stages/warnings.py` |
| Change suggested blocks, padding, pricing, or ref grouping | `stages/suggestions.py` |
| Change model/system fragmentation or partial declarations | `stages/fragmentation.py`, `stages/partial_declarations.py` |
| Change cross-workflow findings or traversal | `stages/cross_workflow.py`, `sub_workflow_walker.py` |
| Change trace selection, indexing, or aggregation | `trace_loading.py` |
| Change memo-key prediction or discrepancy diagnosis | `stages/discrepancy/CLAUDE.md` |
| Change token/cost estimation | `token_estimation.py`, `cost_estimation.py`; threshold detection in `below_min_tokens_detector.py` |
| Change summary, confidence, or evidence filtering | `stages/summary.py` |
| Change text/JSON/nudge/edit rendering | `rendering/CLAUDE.md` |

Stage dependency constraints and helper ownership live in `stages/CLAUDE.md`.
Stages must not import private helpers from `analyze.py`: orchestration depends
on stages, not the reverse.

## Cache distinctions

This package analyzes **provider prompt caching** (`prompt_cache:` and `## Cache`),
not pflow memoization (`cache:`). `--no-cache` disables memo reads, not provider
prompt caching. Declared cache content participates in memo config hashing, and
the discrepancy stage compares predicted memo keys with execution evidence.

Keep these namespaces distinct:

- Memo config hash → `runtime/engine/instrumentation.py::compute_node_config`;
  decides whether pflow executes a node.
- Provider prompt-cache key → `nodes/llm/llm.py::_build_openai_cache_kwargs`;
  provider routing based on cache-block content.
- Provider cache-token usage → normalized by `core/llm_usage.py`; evidence of
  provider cache writes/reads, not proof of a pflow memo hit.

## Row and cost contracts

`PerCallRow` token fields are per call; workflow totals use
`types.py::invocation_count_for`. **`row.cost_usd` is already cohort paid cost**
from trace evidence, so do not multiply it by invocation count again. Missing
pricing is not zero cost.

`cache_configured` is what runtime is asked to cache before provider gates;
`cache_active` is the subset believed provider-effective. `cache_ready` covers
configured content and direct cache-edit candidates; `cache_opportunity` is
the maximum estimated unrealized per-call upside, including structural-edit
candidates. Only `cache_active` feeds headline cost math. Assembly and
aggregation live in `stages/row_builder.py::_build_cache_projection_components`
and `types.py::aggregate_projection`.

`PerCallRow.__post_init__` must not invent projections from token totals; tests
needing projection state construct `CacheProjection` explicitly.

## Trace Loading

Read trace files through `core.trace_io.load_trace_file`, the current JSONL
reconstruction seam. Storage-format acceptance and the reconstructed trace's
`2.x` format-version check are separate boundaries.

An explicit `--from-trace` path goes through `_load_trace_explicit`: missing or
invalid traces fail loudly. Autoload/listing scans skip unreadable candidates.
Autoload prefers successful/degraded runs but can fall back to failed, incomplete
(including still-running), or paused evidence with a disclosure note. Selection
and model-drift handling live in `trace_loading.py`; row evidence and the analyzer's
misalignment fallback are separate checks. Do not silently ignore a user-selected
invalid trace or treat a running stream as a completed run.

`--list-traces` is discovery: an empty listing exits 0 in text and JSON modes
(`src/pflow/cli/commands/analyze_cache.py`), because having no prior runs is valid.

Evidence filtering belongs in `stages/summary.py`. A failed trace with unexecuted
static rows is a truncated cohort: warnings marked `requires_complete_trace`
are suppressed, while structural IR findings remain. An unexecuted conditional
branch in a successful run is not truncation. Trace notes and summary relationship/
model-drift fields explain evidence limitations.

## Validation Delegation

`analyze.py::_run_full_validation` calls `WorkflowValidator.validate()`.
Cache declaration rules belong in `core/workflow/data_flow.py::_validate_cache_block`;
do not reproduce them in stages. Summary counts and recommended actions select
cache-focused findings through `stages.summary._is_cache_focused` and
`rendering.views._is_cache_focused_for_advisory`.

`warning_catalog.py` owns stable IDs, wording, and action priority. A new ID is an
API decision; do not add one merely to vary wording for an existing condition.

## Rendering import boundary

Keep `rendering/__init__.py` exports lazy. Eager imports create the cycle
`analyze → stages.cross_workflow → rendering → summarize → analyze`.
Renderers project derived analysis; they should not become a second analyzer.
