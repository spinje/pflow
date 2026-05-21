# Task 160: Cache Analysis Architectural Refactor

## Description

Pure-structure refactor of `src/pflow/core/cache_analysis/` → `src/pflow/core/prompt_cache_analysis/`. Splits the 8,570-LOC `analyze.py` into a thin orchestrator + named stage modules + a public types module + a rendering subpackage. Renames the package to disambiguate from pflow's memoization cache (the #1 documented source of agent confusion). Zero behavior change. Goal: make the package navigable for AI agents working on individual stages without loading 8,570 lines.

## Status

not started

## Priority

high (do before any feature work touches the analysis package)

## Problem

Task 159 shipped prompt caching and subsequent follow-up work (7 commits, PRs #390–#418) grew `analyze.py` from 3,293 to 8,570 LOC. The file now contains 210 module-scope functions, 27 type definitions, and 11 named clusters. The package overall is 15,943 LOC across 14 source files.

Concrete frictions:

1. **analyze.py is MUST-READ for every scenario.** Scenario analysis across 6 representative tasks (add a warning, fix a fragmentation bug, change cost projections, add a renderer section, fix a discrepancy false positive, add a projection component) shows analyze.py is MUST-READ for all 6. A developer working on fragmentation detection (350 LOC of relevant code) must load 8,570 lines.

2. **Public vocabulary trapped inside the orchestrator.** 20 public frozen dataclasses (the package's public language) are defined at the top of analyze.py. Every consumer that imports a dataclass imports the entire 8,570-LOC file. This forces a circular-import workaround in `view_helpers.py`.

3. **Package name is ambiguous.** `cache_analysis` could mean "analyzing the [memoization] cache." The CLAUDE.md opens with a disambiguation section because the name doesn't self-document. The package is exclusively about LLM provider prompt caching.

4. **Cluster F is 3,072 LOC with 13 sub-groups.** Five independent analytical concerns (row construction, warnings, suggestions, fragmentation, partial declarations) are co-located with shared utilities. A change to any one concern requires navigating past the other four.

## Solution

Rename the package and restructure so each concern owns its file, the public vocabulary has a single home, and the orchestrator is a composition of named stages.

### Target layout

```
src/pflow/core/prompt_cache_analysis/
├── __init__.py                  # public API re-exports
├── CLAUDE.md                    # package navigation index
│
├── types.py                     # NEW ~1,000 LOC — 20 public dataclasses + projection helpers
├── trace_loading.py             # NEW ~830 LOC — trace I/O + indexing + aggregation
├── analyze.py                   # SHRUNK ~900 LOC — orchestrator + row assembly pipeline
│
├── context.py                   # unchanged (335 LOC)
├── cross_workflow.py            # unchanged (447 LOC) — the WALKER (shared infrastructure)
├── token_estimation.py          # unchanged (747 LOC)
├── cost_estimation.py           # unchanged (667 LOC)
├── below_min_tokens_detector.py # unchanged (201 LOC)
├── warning_catalog.py           # unchanged (1,463 LOC)
│
├── stages/                      # NEW — analytical stages (lifted from analyze.py)
│   ├── __init__.py
│   ├── row_builder.py           # ~920 LOC — PerCallRow construction + projections + shared IR helpers
│   ├── warnings.py              # ~630 LOC — per-node warning visitors
│   ├── suggestions.py           # ~570 LOC — suggested blocks + template refs + pricing + padding
│   ├── fragmentation.py         # ~350 LOC — model/system cache fragmentation detection
│   ├── partial_declarations.py  # ~315 LOC — partial cache declaration detection
│   ├── cross_workflow.py        # ~1,315 LOC — cross-workflow analytical findings
│   ├── summary.py               # ~520 LOC — summary builder + confidence + gemini note
│   └── discrepancy/             # sub-package — predict/diagnose split
│       ├── __init__.py
│       ├── predict.py           # ~450 LOC — cache key prediction (lazy runtime imports)
│       └── diagnose.py          # ~265 LOC — discrepancy diagnosis
│
└── rendering/                   # NEW — output projections (moved from top level)
    ├── __init__.py
    ├── text.py                  # was render_text.py (2,423 LOC)
    ├── json.py                  # was render_json.py (377 LOC)
    ├── views.py                 # was view_helpers.py (261 LOC)
    ├── summarize.py             # was summarize.py (132 LOC)
    └── traces_list.py           # was render_traces_list.py (96 LOC)
```

### Cluster-to-file mapping

Verified against the current 8,570-LOC `analyze.py` structure (see `research/architecture.md` for full dependency analysis).

| Cluster | Current lines | LOC | Destination |
|---------|---------------|-----|-------------|
| Dataclasses + projection helpers (A) | 126–972 | ~1,000 | **types.py** |
| Orchestrator (B) | 979–1306 | ~328 | stays in **analyze.py** |
| Memo cache construction (C) | 1309–1346 | ~38 | **trace_loading.py** |
| Trace loading (D) | 1347–1716 | ~370 | **trace_loading.py** |
| Pipeline helpers (E) | 1717–2949 | ~1,233 | split: trace helpers → **trace_loading.py**, row assembly → stays in **analyze.py** |
| Per-node analysis (F) | 2950–6022 | ~3,072 | split across 5 **stages/** files (see below) |
| Cross-workflow walking (G) | 6023–7336 | ~1,314 | **stages/cross_workflow.py** |
| Trace discrepancy (H) | 7337–8050 | ~714 | **stages/discrepancy/** |
| Confidence aggregation (I) | 8051–8081 | ~31 | **stages/summary.py** |
| Summary builder (J) | 8082–8527 | ~446 | **stages/summary.py** |
| Gemini note (K) | 8528–8570 | ~43 | **stages/summary.py** |

Cluster F sub-group mapping:

| Sub-group | LOC | Destination |
|-----------|-----|-------------|
| F1: Row construction | ~240 | stages/row_builder.py |
| F2: Cross-wf projection | ~140 | stages/row_builder.py |
| F3: Provider utils | ~40 | stages/row_builder.py |
| F4: Batch prefix/tail | ~155 | stages/row_builder.py |
| F5: Projection builders | ~300 | stages/row_builder.py |
| F6: Token estimation | ~195 | stages/row_builder.py |
| F7: Warning visitors | ~560 | stages/warnings.py |
| F8: Node utilities | ~70 | stages/row_builder.py (shared IR helpers) |
| F9: Suggested blocks | ~295 | stages/suggestions.py |
| F10: Template refs | ~90 | stages/suggestions.py |
| F11: Body cleanup | ~60 | stages/suggestions.py |
| F12: Cost/savings/fragmentation | ~540 | split: fragmentation → stages/fragmentation.py, pricing helpers → stages/suggestions.py |
| F13: Partial declarations | ~315 | stages/partial_declarations.py |
| padding_advisor.py (63 LOC) | ~63 | folded into stages/suggestions.py |

## Design Decisions

Each decision is backed by verification against the current codebase — see `research/architecture.md` for the dependency data.

1. **Package renamed from `cache_analysis` to `prompt_cache_analysis`.** The current name is the #1 documented source of agent confusion (CLAUDE.md opens with a disambiguation section). The package is exclusively about LLM provider prompt caching, not pflow's memoization cache. CLI command `pflow analyze-cache` stays as-is.

2. **`analyze.py` keeps its name and stays at top level.** Renaming to `pipeline.py` would force every external import path to change for paint. The file simply contains less.

3. **All 20 public frozen dataclasses move to `types.py`** along with the projection helpers (Cluster A — zero outbound dependencies), `invocation_count_for` (part of PerCallRow contract, called from 6 clusters), and `_safe_pct` (trivial arithmetic utility). Private dataclasses (6 total) stay with their stage files. This breaks the circular import workaround in view_helpers.py.

4. **`trace_loading.py` absorbs trace I/O + trace indexing + trace aggregation.** Clusters C and D have near-zero outbound dependencies. The trace indexing helpers (`_build_trace_execution_index`, `_collect_trace_llm_call_lists`, `_aggregate_trace_llm_calls`) logically belong with trace data processing. `_edge_child_paths` (called from 4 clusters) moves here as shared trace infrastructure.

5. **`_detect_candidate_subsets` stays in the orchestrator (analyze.py), NOT in row_builder.py.** Moving it to row_builder would create the only import cycle in the entire decomposition: `row_builder → suggestions → row_builder`. It decides *which subsets* to analyze — orchestration, not construction. Keeping it in the orchestrator eliminates the cycle entirely.

6. **Shared IR accessors (`_node_inputs`, `_batch_aliases`, `_cache_items`, `_cache_item_names`, `_is_batch_scoped_ref`) live in `stages/row_builder.py`.** These are pure dict accessors (~30 LOC total) called from 3-6 modules each. row_builder.py is their primary consumer. Other stages import them from there. This avoids creating a separate helpers file while maintaining a clear import direction (all edges flow toward row_builder or types, never back).

7. **`stages/` subdirectory groups analytical stages.** 8 stage files plus a `discrepancy/` sub-package. Each stage has 1-2 entry points called from the orchestrator. Name choice: "stages" matches the sequential pipeline metaphor.

8. **`rendering/` subdirectory groups output projections.** Five files (text, json, views, summarize, traces_list). Without grouping, the top level would have ~24 files after adding stages/. The import depth cost is one segment; the navigation benefit is real — a reader working on analysis logic can ignore rendering/ entirely.

9. **`stages/discrepancy/` is a sub-package.** The 714-LOC cluster has exactly one call across its internal predict→diagnose boundary, with a plain `dict[(workflow_path, node_id), str]` as the contract. Two ~350-LOC files with one clear seam.

10. **`stages/cross_workflow.py` stays as one 1,315-LOC file.** It's a coherent concern with one entry point (`_build_cross_workflow_findings`). The formatting logic (690 LOC) is tightly coupled to the candidate data structures. Deletion test passes strongly. Split later if it grows.

11. **`padding_advisor.py` (63 LOC) folds into `stages/suggestions.py`.** Only one production consumer (`_emit_padding_advisories`). Two-files-for-one-concern is overhead.

12. **No re-export shims.** Test imports update surgically as their targets move. Shims hide the refactor and accumulate.

13. **Lazy imports in discrepancy stay lazy.** Verified: the `__init__.py` → `summarize` → `analyze` import chain does NOT eagerly import LiteLLM. The discrepancy cluster's lazy runtime imports (plan_node, compile_workflow, create_planner_shared) only fire when called. `stages/__init__.py` re-exporting from discrepancy is safe.

14. **`TemplateResolver` import becomes lazy.** `analyze.py:65` eagerly imports `TemplateResolver` from `pflow.runtime`. `context.py` and `token_estimation.py` already do this lazily. Whichever stage file inherits the import should make it lazy for consistency.

15. **Prompt cache feature files stay flat in `core/`.** The 5 feature files (`prompt_cache.py`, `prompt_refs.py`, `llm_capabilities.py`, `cache_overlap.py`, `cache_ttl.py`, 1,115 LOC total) have a clean one-way dependency with the analysis package. Moving them into a parent folder would add nesting for runtime consumers (nodes/llm, runtime/engine) with no benefit.

## Dependencies

- **Task 159 must be merged first.** This task is a follow-up cleanup. ✅ Task 159 is merged.

## Requirements

### Package rename
- `from pflow.core.cache_analysis import X` continues to work OR all consumers are updated to `from pflow.core.prompt_cache_analysis import X`.
- All 5 production consumers updated.
- All 18 test files updated.

### Public API stability
- All names currently re-exported from the package's `__init__.py` continue to be importable from the same package path (with the new name).
- The 5 production consumers work without modification beyond the package rename:
  - `cli/commands/analyze_cache.py` — `analyze, render_json, render_text, list_traces_for_workflow, JSON_FORMAT_VERSION`
  - `execution/runner.py` — `analyze, summarize_from_analysis`
  - `mcp_server/services/execution_service.py` — `analyze, render_json`
  - `core/workflow/data_flow.py` — `warning_catalog.make_diagnostic`
  - `nodes/llm/llm.py` — `below_min_tokens_detector.*, warning_catalog.make_diagnostic`
  - `runtime/engine/engine.py` — `below_min_tokens_detector.*, context.AnalysisContext, token_estimation.*, warning_catalog.make_diagnostic`

### Behavior preservation
- `pflow analyze-cache` produces byte-identical text output for any given workflow + trace input.
- `pflow analyze-cache --json` produces structurally-identical JSON (`format_version` unchanged).
- `pflow run --dry-run` cache nudge produces an identical `Diagnostic`.
- Every cache-related warning ID continues to fire in the same conditions.

### Structure
- `analyze.py` final size ≤ 1,100 LOC (target ~900).
- `types.py` exists and contains all 20 public frozen dataclasses; no public dataclasses remain in `analyze.py`.
- No module imports `from .analyze import X` at function scope (the circular-import workaround is gone).
- `stages/` directory contains exactly the analytical stages enumerated in Solution.
- `rendering/` directory contains exactly the output projections enumerated in Solution.
- `padding_advisor.py` no longer exists; its content lives in `stages/suggestions.py`.
- No import cycles exist in the module graph (verified: all edges are one-directional after DD#5).

### Documentation
- `prompt_cache_analysis/CLAUDE.md` exists and covers: module structure, public API, the orchestrator → stages → rendering pipeline, runtime → analyzer trace contract, where to add a new warning.
- `core/CLAUDE.md` updated to reference the renamed package.
- The disambiguation section ("pflow has TWO independent cache concepts") is preserved but simplified since the name now self-documents.

### Tests
- Test imports updated to reflect new package name and new module paths.
- `make test` passes.
- `make check` passes (mypy, ruff).
- No test dropped without replacement coverage through the public API.

## Implementation Notes

### Phase ordering (sequential, one PR)

Run `make test && make check` after each phase as a checkpoint.

**Phase 1 — Package rename + types.py extraction**
Rename `cache_analysis/` → `prompt_cache_analysis/`. Extract types.py. Update all imports (production + test). This is the prerequisite for everything else.

**Phase 2 — trace_loading.py extraction**
Move trace I/O (Clusters C+D), trace indexing helpers, trace aggregation helpers, and `_edge_child_paths` to trace_loading.py.

**Phase 3 — rendering/ subdirectory**
Move 5 rendering files into rendering/. Update imports.

**Phase 4 — Self-contained stages**
Extract stages that have near-zero outbound dependencies: summary.py (J+I+K), discrepancy/ (H), cross_workflow.py (G).

**Phase 5 — Cluster F decomposition**
The highest-risk phase. Extract row_builder.py, warnings.py, suggestions.py (absorbs padding_advisor.py), fragmentation.py, partial_declarations.py. Shared IR helpers go in row_builder.py.

**Phase 6 — Test cleanup + documentation**
Update remaining test imports. Write CLAUDE.md. Update core/CLAUDE.md. Finalize `__init__.py` re-exports.

### Verification approach

1. Before starting: capture reference outputs for at least 3 workflows (greenfield, with-cache, with-trace). Save text and JSON outputs.
2. After each phase: `make test && make check`.
3. After phase 5: diff reference outputs. Text diff should be empty. JSON diff should be empty modulo `analyzed_at`.
4. After phase 5: run `pflow run --dry-run` on a workflow with cache nudge and confirm identical Diagnostic.

### Import graph (verified cycle-free)

```
types.py             ← everything (leaf, no outgoing stage imports)
trace_loading.py     ← cross_workflow, discrepancy, orchestrator (leaf)
row_builder.py       ← warnings, suggestions, partial_decl, cross_workflow
suggestions.py       ← partial_decl, cross_workflow, warnings, orchestrator
warnings.py          ← orchestrator only
partial_decl.py      ← orchestrator only
cross_workflow.py    ← orchestrator only
summary.py           ← orchestrator only
discrepancy/         ← orchestrator only
```

### Verified non-issues (do NOT try to fix these)

1. **`_cache_validator_findings` is NOT duplicating data_flow.py.** It's a ~46 LOC adapter that calls `validate_data_flow()`, filters to `cache.*` IDs, and enriches with `affected_workflow`. DD#20 is honored.
2. **Lazy imports in discrepancy are NOT a smell.** They prevent 700ms LiteLLM startup on `--dry-run`. Verified safe.
3. **There is NO duplicate cache-key predictor.** Both `--dry-run` and the discrepancy stage call the same primitives (`plan_node`, `create_planner_shared`).
4. **Pricing helpers should NOT merge into `cost_estimation.py`.** Different abstraction levels: chunk-level (greenfield "what would this save?") vs row-level (post-aggregation projections).
5. **`cross_workflow.py` (the walker) is NOT shallow.** It has 4 distinct consumers. Genuinely shared infrastructure.
6. **Prompt cache feature files are cleanly separated.** One-way dependency, no refactoring needed.

### Production consumers (complete, verified list)

| Consumer | Imports | Notes |
|----------|---------|-------|
| `cli/commands/analyze_cache.py` | `analyze`, `render_json`, `render_text`, `list_traces_for_workflow`, `render_traces_list_json`, `render_traces_list_text`, `JSON_FORMAT_VERSION` | Package-level + sub-module |
| `execution/runner.py` | `analyze`, `summarize_from_analysis` | Package-level |
| `mcp_server/services/execution_service.py` | `analyze`, `render_json` | Package-level |
| `core/workflow/data_flow.py` | `warning_catalog.make_diagnostic` | Direct sub-module (2 import sites) |
| `nodes/llm/llm.py` | `below_min_tokens_detector.*`, `warning_catalog.make_diagnostic` | Direct sub-module |
| `runtime/engine/engine.py` | `below_min_tokens_detector.*`, `context.AnalysisContext`, `token_estimation.*`, `warning_catalog.make_diagnostic` | Direct sub-module |

### Test landscape (current state)

- 18 test files, 31,288 LOC total
- 29 unique private symbols imported from analyze.py across 57 import sites in 5 test files
- 6 unique private symbols imported from render_text.py across 15 import sites in 2 test files
- 1 unique private symbol imported from context.py across 2 import sites in 1 test file

## Verification

- All requirements above hold.
- `make test` and `make check` pass with no behavior-related test edits.
- Reference output diffs are empty for text and JSON (modulo `analyzed_at`).
- The `--dry-run` cache nudge produces an identical Diagnostic.
- A reader who has never seen the package can find "where is X computed?" by reading file names + CLAUDE.md, in under 60 seconds.

## References

- Architecture review HTML: generated during the design conversation (2026-05-21)
- Detailed dependency analysis: `research/architecture.md`
- Task 159 (prompt caching feature): `.taskmaster/tasks/task_159/task-159.md`
- Follow-up work that grew analyze.py: PRs #390, #392, #396, #405, #412, #416, #418
- Design conversation braindump: `starting-context/braindump-2026-05-04-design-conversation.md` (historical — some insights still apply, specific code references are stale)
