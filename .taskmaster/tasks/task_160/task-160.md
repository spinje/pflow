# Task 160: Prompt Cache Analysis Architectural Refactor

## Description

Turn the cache-analysis code from a single 8,570-LOC `analyze.py` monolith into a
deep, navigable package — `pflow.core.prompt_cache_analysis` — whose modules each
own one concern behind a small interface, whose orchestrator reads as a pipeline,
and whose public surface is the only thing a caller needs to learn. The package
name itself disambiguates the two cache concepts pflow has (provider prompt cache
vs. memoization cache). **Zero behavior change**: the analyzer produces
byte-identical text and JSON, the same `--dry-run` nudge, and the same warnings as
before the work began.

This document specifies the **end-state architecture** the refactor aimed for and
the package now embodies. It describes what the package *is*, not the path taken to
get there. The package's own `CLAUDE.md` is the living companion to this spec; the
two should stay in agreement.

## Status

done

## Completed

2026-05-27

## Priority

high (do before any feature work touches the analysis package).

## Problem

The analyzer began life as one file. `core/cache_analysis/analyze.py` was **8,570
LOC**: 210 module-scope functions and 27 type definitions, organized only by
`# ----` comment clusters (A–K). Every consumer, every test, and every reader who
wanted to answer "how does pflow analyze caching?" had to load the whole file. The
file mixed eight unrelated concerns — trace loading, row construction, per-node
warnings, suggested-block synthesis, cross-workflow analysis, discrepancy
prediction, summary aggregation, and three flavors of rendering — with no seam
between any of them.

Two further frictions compounded the monolith:

1. **The package name was ambiguous.** `cache_analysis` collided conceptually with
   pflow's *memoization* cache (`runtime/cache.py`). The package is exclusively
   about *provider prompt caching*; the name didn't say so, and readers conflated
   the two.

2. **No place to put anything.** Because everything lived in one file, new
   cache-analysis work had nowhere natural to land. Helpers accreted; the only
   "design decision" available was where in the 8,570 lines to paste a function.

The goal was a package where the answer to "where is X computed?" is legible from
file names plus `CLAUDE.md` in under a minute, where the orchestrator's value comes
from being the single entry point that hides the pipeline, and where tests cross
the same seam as production callers.

## Target architecture

### Shape

`prompt_cache_analysis/` is **~16,200 LOC across 29 source files** plus three
`CLAUDE.md` docs. The orchestrator is thin; analysis lives in `stages/`; rendering
lives in `rendering/`; shared vocabulary lives in `types.py`; the input bundle and
all ref/memo resolution policy live in `context.py`. LOC figures below are
orientation, not targets — the design decision behind each file is its single
responsibility, not its line count.

```
src/pflow/core/prompt_cache_analysis/
├── __init__.py                  (~160)  public API re-exports — the stable external surface
├── analyze.py                   (~540)  thin orchestrator + orchestration-only glue
├── types.py                     (~930)  public dataclasses, projection algebra, row contract
├── context.py                   (~540)  AnalysisContext: input bundle + ref/memo resolution policy
├── trace_loading.py             (~1000) trace I/O, autoload/listing, indexing, aggregation, drift
├── sub_workflow_walker.py        (~610)  sub-workflow walker data primitive + parameter resolution
├── token_estimation.py           (~690)  trace → memo → estimator → heuristic token hierarchy
├── cost_estimation.py            (~670)  row-level cost projection + actually-paid aggregation
├── below_min_tokens_detector.py   (~200)  shared below-threshold detector
├── warning_catalog.py            (~1460) stable warning IDs, headlines, factories (source of truth)
├── CLAUDE.md
├── rendering/                            read-only projections of CacheAnalysis
│   ├── __init__.py              (~40)   render_json / render_text / summarize re-exports
│   ├── text.py                  (~2450) markdown report; render_text(analysis, *, all_rows, section)
│   ├── json.py                  (~380)  JSON projection (JSON_FORMAT_VERSION = "5.0")
│   ├── views.py                 (~230)  blocking-error + recommended-action projections
│   ├── cross_workflow_edits.py   (~320)  paste-ready cross-workflow cache-block edit text
│   ├── summarize.py             (~130)  one-line dry-run nudge Diagnostic
│   ├── traces_list.py           (~100)  --list-traces output
│   └── CLAUDE.md                        documented direct-test helper surface
└── stages/                               one analytical concern per file, one entry point each
    ├── __init__.py              (1)     intentionally docstring-only (no eager loading)
    ├── per_call_pipeline.py     (~115)  multi-stage orchestrator: rows + warnings + cross-workflow
    ├── row_builder.py           (~1130) PerCallRow construction primitives + shared IR helpers
    ├── warnings.py              (~640)  per-node warning visitors + shadow-cost enrichment
    ├── suggestions.py           (~810)  suggested ## Cache blocks, padding advisories, chunk pricing
    ├── fragmentation.py         (~390)  model/system cache fragmentation detection
    ├── partial_declarations.py   (~350)  incomplete prompt_cache declaration detection
    ├── cross_workflow.py        (~970)  analytical cross-workflow findings
    ├── summary.py               (~600)  summary, confidence, rollups, trace-dependent filtering
    └── discrepancy/
        ├── __init__.py          (~10)   narrow discrepancy re-exports
        ├── predict.py           (~570)  cache-key prediction (runtime imports stay lazy)
        ├── diagnose.py          (~185)  trace discrepancy diagnostics
        └── CLAUDE.md                    documented direct-test helper surface
```

### The orchestrator is a thin sequencer

`analyze.py::analyze()` is the integration point and the most-leveraged function in
the package (three production consumers, ~50 test sites). Its interface is one
fact: *calling `analyze(workflow_ir, ...)` produces a `CacheAnalysis`.* The body
reads as a seven-step pipeline, each step one named call into a module that owns the
concern:

1. Build `AnalysisContext` and resolve trace scope (`trace_loading`).
2. Walk sub-workflows (`sub_workflow_walker`).
3. Predict memo cache keys (`stages.discrepancy.predict`).
4. Build per-call rows (`stages.per_call_pipeline`).
5. Emit stage findings (warnings, suggestions, fragmentation, partial declarations,
   cross-workflow, discrepancy).
6. Build the summary and rollups (`stages.summary`).
7. Return `CacheAnalysis`.

What remains in `analyze.py` beyond `analyze()` is orchestration glue with a single
call site each — trace-misalignment recovery, per-call visibility notes, and the
`_run_full_validation` delegation to the unified `WorkflowValidator`. Helpers that
serve a stage live with that stage; no stage module imports a private helper from
`analyze.py`. The orchestrator's depth comes from hiding the pipeline behind one
entry point, not from absorbing helpers.

### `types.py` is the leaf; everything imports from it, it imports from nothing

`types.py` owns the analyzer's public vocabulary — `CacheAnalysis`,
`AnalysisSummary`, `PerCallRow`, `CacheProjection`, `SuggestedBlock`,
`RecommendedAction`, `TraceListEntry` — plus the projection algebra that operates on
those shapes and `invocation_count_for(row)`. It is the cleanest seam in the
package: a true leaf with no analyzer-internal dependencies, safe to import from any
consumer. Public report dataclasses are importable only from `types.py`;
`analyze.py.__all__` deliberately exports only `analyze`, so there is no dual-path
type import.

**One row contract.** `PerCallRow` is constructed only in the projection-object
shape. `__post_init__` is deliberately small — it derives `cached_now_tokens_estimated`
from trace cache-token splits (and, for trace-backed declared-cache rows, from the
trace cacheable-token fallback) and nothing else. It does not synthesize projection
objects from a legacy scalar. Each row exposes four projection objects
(`cache_configured`, `cache_active`, `cache_ready`, `cache_opportunity`); only
`cache_active` feeds headline cost math. Row visibility is a single predicate,
`row.has_real_data`, read by both the analyzer and the renderer.

### Analysis and rendering live behind a clean seam

The cross-workflow stage produces *findings*; turning a finding into paste-ready
cache-block edit text is *rendering*. These are two jobs, so they live in two files:
`stages/cross_workflow.py` (analytical findings) and
`rendering/cross_workflow_edits.py` (edit text). The seam is a single public
function, `format_grouped_body_block`, exchanging plain strings — the render side
does not import `Diagnostic`. The seam dataclasses
(`_SubWorkflowCacheCandidate`, `_SubWorkflowCacheGroup`, `_GroupedConsumerProjection`)
live in `types.py` so both sides import them from the leaf.

`render_text(analysis, *, all_rows=False, section="all")` is the single text entry
point. The `section="summary"` keyword lets a caller render just the `## Summary`
block without reaching into a private helper — the public interface *is* the test
surface for section rendering.

### `AnalysisContext` owns ref and memo resolution policy

`context.py` is the input bundle (workflow IR, parameters, trace, memo cache,
predicted cache keys) and the single home for the resolution machinery every stage
needs:

- `resolve_ref_value(ref)` / `resolve_ref_value_for_projection(ref)` resolve a
  template ref against the analyzer's root workflow.
- `resolve_ref_value_in_workflow(ref, *, workflow_path)` /
  `resolve_ref_value_for_projection_in_workflow(...)` are the workflow-path-parametric
  forms. Sub-workflow boundary findings resolve refs scoped to a parent workflow
  without any stage re-implementing the parameters/memo/trace tier chain.
- `latest_memo_for_node(node_id, *, workflow_path)` is the one home for the memo
  freshness check (predicted-cache-key comparison, `stale_memo_skipped` /
  `stale_memo_uncheckable` accounting). It consumes context self-state, so it is a
  method, not a free function.

`template_resolver()` — the lazy accessor for the runtime `TemplateResolver` — is
defined once here and imported by every stage that needs it.

### Naming and structure carry the disambiguation

- The package is `prompt_cache_analysis`, not `cache_analysis`; the name says it is
  about provider prompt caching, orthogonal to memoization.
- The sub-workflow walker is `sub_workflow_walker.py`, not a second
  `cross_workflow.py`. `find . -name cross_workflow.py` returns exactly one path
  (the analytical stage). The walker name describes what it does.
- `_cache_items` names exactly one function (the suggestions-stage helper); the
  walker-side tuple variant is `_cache_items_as_tuple`.

### The stage dependency graph is a DAG

The multi-stage per-call orchestrator (`_build_per_call_rows_and_warnings`) lives in
its own module, `stages/per_call_pipeline.py`, because it *is* the seam between row
construction, warning emission, and cross-workflow attachment. It imports
`row_builder`, `warnings`, and `cross_workflow` at module top. `row_builder.py` is
strictly row-primitive construction and has no function-body imports from sibling
stages — the import-cycle workarounds that a misplaced orchestrator would force are
gone. The cost API helpers are named to match their already-public export contract
(`aggregate_no_cache_cost`, `aggregate_with_cache_projection`, `row_body_only_cost`,
`row_first_run_with_cache_cost`, `pricing_from_dict`) — no symbols carry an
underscore prefix while `__all__` declares them public.

### The public interface

Package-level imports are the stable external surface; the rest of the package is
implementation:

```python
from pflow.core.prompt_cache_analysis import (
    JSON_FORMAT_VERSION,   # "5.0"
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

External consumers (`cli/commands/analyze_cache.py`, `execution/runner.py`,
`mcp_server/services/execution_service.py`, `runtime/engine/engine.py`,
`nodes/llm/llm.py`, `core/workflow/data_flow.py`) import only through this surface
or through a small, documented set of stable submodule entry points.

### Documented test surfaces

Two private symbol sets are intentionally direct-test surfaces, documented in their
local `CLAUDE.md` rather than promoted to public:

- `stages/discrepancy/CLAUDE.md` lists `_predict_node_cache_key` and the three
  `_format_*_note` helpers as stable test surfaces.
- `rendering/CLAUDE.md` lists the pure-formatter substrate (`_render_summary`,
  `_format_delta_parenthetical`, `_format_cost`, `_cell_calls`, `_indent_message`,
  `_BASELINE_LABELS`).

Documenting the implicit coupling makes it an explicit contract: refactors are free
to rename these, but must update the tests in the same change.

## Design decisions

These are the choices the end-state deliberately makes — and the things it
deliberately leaves alone.

1. **No `projection_algebra.py` extraction.** The projection algebra in `types.py`
   has one consumer path. One adapter is a hypothetical seam; extracting it would add
   interface surface without leverage. The algebra correctly lives next to its
   dataclasses.

2. **No shared `_ir_helpers.py` module.** The IR accessor helpers (`_node_inputs`,
   `_batch_aliases`, `_cache_items`, `_cache_item_names`, `_is_batch_scoped_ref`) are
   heterogeneous and each used heavily within its host stage. They live with their
   primary consumer rather than in a catch-all module.

3. **`cache_overlap.py`'s duplicates of `_batch_aliases` / `_is_batch_scoped_ref`
   stay.** They exist by design to keep the one-way `analyzer → data_flow`
   dependency. Consolidating would create a back-import.

4. **Discrepancy runtime imports stay lazy.** `stages/discrepancy/predict.py`
   lazy-imports `compile_workflow`, `plan_node`, and `create_planner_shared`.
   `prompt_cache_analysis` is imported by `--dry-run` surfaces that must not pay
   ~700ms of LiteLLM startup unless prediction actually runs. `template_resolver()`
   is lazy for the same reason. Package import is cheap: importing
   `prompt_cache_analysis` leaves `litellm` absent from `sys.modules`.

5. **`rendering/text.py` is not section-split.** At ~2,450 LOC it is large but
   cohesive — its section renderers have clean boundaries. Physical decomposition
   would improve navigation without improving interface leverage; it is a separate
   concern.

6. **Private test surfaces are documented, not promoted.** Renaming a surgical
   branch-logic test helper to "public" would over-claim the contract. The honest
   move is a documented Test API section.

7. **`analyze.py` keeps orchestration glue.** `_run_full_validation`,
   trace-misalignment recovery, and a handful of single-call-site helpers stay in the
   orchestrator because they are sequencing, not separable concerns. The orchestrator
   is thin in interface (one entry point), which is the property that matters — not
   minimal in line count.

8. **The two-cache disambiguation is load-bearing documentation.** The package name
   plus the `CLAUDE.md` disambiguation table keep "provider prompt cache" and
   "memoization cache" distinct everywhere a reader might conflate them.

## Behavior preservation (the central invariant)

The entire refactor is structural. The following hold for any workflow + trace
input, before and after:

- `pflow analyze-cache` produces **byte-identical** text output.
- `pflow analyze-cache --json` produces structurally-identical JSON
  (`format_version` unchanged at `"5.0"`).
- `pflow run --dry-run` produces an identical cache-nudge `Diagnostic`.
- Every cache-related warning ID fires under the same conditions.
- All `__all__` exports remain importable from the same package path.
- The analyzer's dependency on the `core/` prompt-cache feature files
  (`prompt_cache.py`, `prompt_refs.py`, `llm_capabilities.py`, `cache_overlap.py`,
  `cache_ttl.py`) stays strictly one-way.

## Verification

The achieved end-state is confirmed by:

- **The Task 159 regression harness** (`.taskmaster/tasks/task_159/baseline/verify.sh`)
  reports `80 passed, 7 drifted, 0 harness errors`. The 7 drifts are pre-existing
  baseline staleness from feature work (PRs #390/#392/#396/#405/#412/#416/#418), not
  caused by this refactor — the same 7 drift on the pre-refactor parent commit. This
  harness is the authoritative byte-level proof of zero behavior change.
- `make test` and `make check` pass (mypy clean over the package's source files,
  ruff, deptry).
- Structural checks:
  - `find src/pflow -name cross_workflow.py` returns one path (the analytical stage).
  - `grep -rn "def _template_resolver" src/pflow/core/prompt_cache_analysis/` returns
    nothing; the one resolver is `context.py::template_resolver`.
  - `from pflow.core.prompt_cache_analysis.sub_workflow_walker import walk_cross_workflow`
    succeeds; the old `...cross_workflow` walker path raises `ImportError`.
  - `from pflow.core.prompt_cache_analysis.analyze import CacheAnalysis` raises
    `ImportError` (types are importable only from `types.py`).
  - Importing `pflow.core.prompt_cache_analysis` leaves `litellm` absent from
    `sys.modules`.
- A reader who has never seen the package can answer "where is X computed?" from file
  names + `CLAUDE.md` in under a minute.

## Dependencies

None.

## References

- `src/pflow/core/prompt_cache_analysis/CLAUDE.md` — the package's living
  self-description; this spec and that file should stay in agreement.
- `src/pflow/core/prompt_cache_analysis/rendering/CLAUDE.md`,
  `.../stages/discrepancy/CLAUDE.md` — documented direct-test surfaces.
- `.claude/skills/improve-codebase-architecture/LANGUAGE.md` — the vocabulary used
  here (Module, Interface, Implementation, Depth, Seam, Adapter, Leverage, Locality;
  the deletion test; "the interface is the test surface").
- `.taskmaster/tasks/task_159/baseline/verify.sh` — the regression harness that
  proves zero behavior change.
