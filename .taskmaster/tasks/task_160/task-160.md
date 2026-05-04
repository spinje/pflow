# Task 160: Cache Analysis Architectural Refactor (Post-Task-159 Cleanup)

## Description

Pure-structure refactor of `src/pflow/core/cache_analysis/` after task 159 ships. Splits the 3,293-LOC `analyze.py` orchestrator-plus-everything file into a thin orchestrator + named stage modules + a public types module + a rendering subpackage. Zero behavior change. Goal: make the package navigable for AI agents working on individual stages without re-reading 3k lines of context.

## Status

not started

## Priority

high (do before any feature work touches `cache_analysis/`)

## Problem

Task 159 shipped the cache analysis feature and got us to "feature-complete and verified." Along the way `analyze.py` accreted into a 3,293-LOC file containing nine public dataclasses + the orchestrator + six separable algorithm clusters + small helper utilities. The package overall is 7,865 LOC across 12 source files — most of those 12 files are well-shaped, but the central one is not.

Concrete frictions for an AI agent (or any reader) modifying one stage:

1. **Single-file blast radius.** Changing one cluster (e.g. how greenfield suggested blocks are computed) means scrolling past five other clusters' code in the same file. The clusters share no state beyond the `AnalysisContext` already passed by parameter — they don't *need* to live together.

2. **Public vocabulary lives inside the orchestrator.** The 9 frozen dataclasses (`CacheAnalysis`, `AnalysisSummary`, `PerCallRow`, `RecommendedAction`, `SuggestedBlock`, `SuggestedBlockChunk`, `CrossWorkflowFindings`, `SubWorkflowRollup`, `SubWorkflowRollupEntry`) are the package's public language. They're imported by `view_helpers.py`, `render_text.py`, `render_json.py`, `summarize.py`, `cost_estimation.py`, plus external consumers via `__init__.py`. That every importer reaches into the orchestrator file forces a circular-import workaround at `view_helpers.py:84` (documented in-comment as such).

3. **`analyze.py` cannot pass the deletion test cleanly.** Deleting any single cluster shouldn't reveal "this was just glue" — but with everything in one file, even moving cluster boundaries is invisible. Once each cluster has its own file, the deletion test becomes meaningful.

4. **Tests inherit the same shape.** Test imports reach into 19 distinct private symbols across ~36 sites. `test_renderers.py` has 83 calls to local fixture factories binding to public dataclass constructors. There's a partially-adopted `TraceFixtureBuilder` (3 of 12 test files use it). Test bloat isn't the primary problem here — but a test suite that mirrors a confused source structure compounds the navigation cost.

5. **No CLAUDE.md.** A 7,865-LOC package with no agent-facing index. Every fresh session re-derives the package shape from grep.

## Solution

Restructure the package so each concern owns its file, the public vocabulary has a single home, and the orchestrator is a small composition of named stages:

```
src/pflow/core/cache_analysis/
├── __init__.py                  # public API re-exports
├── CLAUDE.md                    # NEW — package navigation index
│
├── analyze.py                   # ~450 LOC — orchestrator + I/O loaders only
├── types.py                     # NEW — 9 public dataclasses
├── context.py                   # unchanged
├── cross_workflow.py            # unchanged — the WALKER (data primitive, 4 consumers)
├── token_estimation.py          # unchanged
├── cost_estimation.py           # unchanged
├── warning_catalog.py           # unchanged
│
├── stages/                      # NEW — analytical stages (lifted from analyze.py)
│   ├── per_call.py
│   ├── rules.py                 # collapse 4 per-node warning visitors → 1 visit
│   ├── suggestions.py           # absorbs chunk-level pricing helpers
│   ├── padding.py               # absorbs padding_advisor.py + analyze.py's padding glue
│   ├── cross_workflow.py        # the analytical stage (consumes the walker's output)
│   ├── summary.py               # gathers scattered summary-builder helpers
│   └── discrepancy/             # sub-package — the cluster splits cleanly
│       ├── __init__.py
│       ├── predict.py
│       └── diagnose.py
│
└── rendering/                   # NEW — output projections
    ├── __init__.py
    ├── text.py                  # was render_text.py
    ├── json.py                  # was render_json.py
    ├── views.py                 # was view_helpers.py
    └── summarize.py             # moved from top level
```

Renames are minimised on purpose (paths cost mental energy). Only `padding_advisor.py` disappears (folded). Everything else moves into a subdirectory or stays put.

## Design Decisions

Each decision below has a reason backed by direct verification of the source — see `research/end-state-architecture.md` for the line ranges and call graphs that justify them.

1. **`analyze.py` keeps its name and stays at top level.** Renaming to `pipeline.py` would force every external import path to change for paint. The file simply contains less.

2. **All 9 public dataclasses move to `types.py`** — even though only 5 cross module boundaries today. Once stages exist, all 9 will cross. Co-location lets `view_helpers.py` import its return type without the lazy-import workaround.

3. **`stages/` subdirectory groups algorithmic stages.** Six stages plus a `discrepancy/` sub-package. Name choice: "stages" matches the sequential pipeline metaphor (`analyze()` chains them) and aligns with how the team already discusses the work in implementation logs. Rejected: `analyzers/` (overloads — the package itself is *the* analyzer), `passes/` (connotes independence; ours share `ctx`).

4. **`rendering/` subdirectory groups views.** `text.py`, `json.py`, `views.py` (recommendations + alignment filter), `summarize.py`. Form-over-function objection ("`summarize.py` produces a Diagnostic, not a string") is rejected — conceptually all four consume `CacheAnalysis` and produce something user-facing. Symmetry helps navigation.

5. **`stages/discrepancy/` is a sub-package, not one file.** The 527-LOC discrepancy cluster has exactly ONE call across its internal predict↔diagnose boundary, with a plain `dict[(workflow_path, node_id), str]` as the contract. Splitting into `predict.py` and `diagnose.py` produces two ~250-LOC files with one clear seam — strictly better than one mixed 527-LOC file.

6. **`padding_advisor.py` (63 LOC) folds into `stages/padding.py`.** Only one production consumer. Two-files-for-one-concern is overhead.

7. **`cross_workflow.py` (the walker) stays at top level.** It produces shared data (typed `CrossWorkflowEdge` + `CrossWorkflowResult`) consumed by *four* downstream sites in the orchestrator, not just the cross-workflow analytical stage. It's genuinely shared infrastructure, not a stage helper.

8. **The chunk-level pricing helpers move with `stages/suggestions.py`, NOT into `cost_estimation.py`.** The `_input_rate` / `_estimate_token_savings_usd` / `_savings_for_shared_ref` trio operates at chunk-level (greenfield "what would this ref save?"). `cost_estimation.py` operates at row-level (post-aggregation projections). Different abstractions; the chunk helpers belong with their consumer.

9. **No `RuleBase` / `Rule` class for the `stages/rules.py` collapse.** Four per-node warning visitors become one walk that calls four small functions in sequence. An abstract Rule API is justified at 20+ rules — not at 4. Add the abstraction the day it's earned.

10. **Tests update import paths surgically; no compatibility shims.** ~36 private-symbol import sites in tests. Each is updated as its target moves. Re-export shims in `analyze.py` would hide the refactor and become dead weight; the test coupling is already known and tracked.

11. **External public API is preserved through `__init__.py`.** All four production consumers (`cli/commands/analyze_cache.py`, `execution/runner.py`, `mcp_server/services/execution_service.py`, `core/workflow/data_flow.py`) keep working unchanged. Internal sub-module imports may change for tests; nothing else.

12. **Three small dedups land with the move:** the duplicate `_workflow_short_name` (analyze.py:2911 + render_text.py:721), the dead-in-production `_iter_llm_events` (test-only), and the `_build_recommended_actions` compatibility shim (analyze.py:3219, just delegates to `view_helpers`).

## Dependencies

- **Task 159 (Prompt Caching) must be merged first.** This task is a follow-up cleanup; it would conflict catastrophically with in-flight task 159 verification work. See `progress-log.md` in task 159 for context.

## Requirements

### Public API stability
- All names currently re-exported from `pflow.core.cache_analysis` continue to be importable from the same path.
- All four production consumers (`cli/commands/analyze_cache.py`, `execution/runner.py`, `mcp_server/services/execution_service.py`, `core/workflow/data_flow.py:945`) work without modification.
- Direct sub-module import `from pflow.core.cache_analysis.warning_catalog import make_diagnostic` (used by `data_flow.py`) continues to work.

### Behavior preservation
- `pflow analyze-cache` produces byte-identical text output for any given workflow + trace input.
- `pflow analyze-cache --json` produces structurally-identical JSON (`format_version` unchanged).
- `pflow run --dry-run` cache nudge produces an identical `Diagnostic`.
- Every cache-related warning ID continues to fire in the same conditions.

### Structure
- `analyze.py` final size ≤ 600 LOC (target ~450).
- `types.py` exists and contains all 9 public dataclasses; no public dataclasses remain in `analyze.py`.
- No module imports `from .analyze import X` at function scope (the circular-import workaround is gone).
- `stages/` directory contains exactly the algorithmic stages enumerated in Solution; no leakage.
- `rendering/` directory contains exactly the view projections enumerated in Solution.
- `padding_advisor.py` no longer exists; its content lives in `stages/padding.py`.
- `_workflow_short_name` has exactly one definition (not two).
- `_iter_llm_events` either has a non-test caller or is removed.
- `_build_recommended_actions` compatibility shim in `analyze.py` is removed; callers import from `rendering/views.py` directly.

### Documentation
- `src/pflow/core/cache_analysis/CLAUDE.md` exists, follows the project's CLAUDE.md conventions, and covers (at minimum): module structure, public API, the orchestrator → stages → rendering pipeline, runtime → analyzer trace contract (the trace 2.1.0 fields), where to add a new warning, why `discrepancy/` lazy-imports runtime modules.
- `src/pflow/core/CLAUDE.md` is updated to mention the cache_analysis subpackage if it was missed during task 159.

### Tests
- Test imports updated to reflect new paths (no production code is the source of churn — tests are).
- `make test` passes.
- `make check` passes (mypy, ruff).
- No test is dropped without replacement coverage existing through the public API. The bar is "behavioural coverage preserved," not "every private-helper test preserved."

## Implementation Notes

The mechanical work is described file-by-file in `research/end-state-architecture.md`. Open decisions for the implementer (phasing, walker rename) are captured in `research/migration-plan.md`. Verified non-issues (do NOT try to fix these; they're already correct) are in `research/verified-non-issues.md`.

This task is structural only — zero behavior change is the bar. Anything that looks like a behavior bug discovered along the way is a separate ticket.

## Verification

- All requirements above hold.
- The `make test` and `make check` runs pass on the post-refactor branch with no behavior-related test edits.
- A diff of `pflow analyze-cache` text output against pre-refactor reference traces is empty for at least three workflows (greenfield, with-cache, with-trace).
- A diff of `pflow analyze-cache --json` output is empty (modulo `analyzed_at` timestamp) for the same workflows.
- A reader who has never seen the refactored package can find "where is X computed?" for any X in the public output by reading file names + the new CLAUDE.md, in under 60 seconds.

## References

- Task 159: prompt caching feature that produced the structure being refactored — `.taskmaster/tasks/task_159/task-159.md`
- Architectural research files (this task): `research/end-state-architecture.md`, `research/migration-plan.md`, `research/verified-non-issues.md`
- Project CLAUDE.md conventions: `src/pflow/core/CLAUDE.md` (current example), `architecture/CLAUDE.md` (index)
- The five Explore + pflow-codebase-searcher agent reports that grounded this spec are not preserved as files; their findings are baked into the research docs.
