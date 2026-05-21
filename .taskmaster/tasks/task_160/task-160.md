# Task 160: Prompt Cache Analysis Architectural Deepening

## Description

Deepen the `pflow.core.prompt_cache_analysis` package along seams that have been earned by usage but not yet collapsed: thin the orchestrator to a true sequencer, remove the legacy `PerCallRow` bridge that spans producers and consumers, separate cross-workflow analysis from its rendering, parametrize `AnalysisContext` to absorb a duplicated 188-LOC resolution chain, and align the cost API's naming with its already-public export contract. Zero behavior change.

## Status

not started

## Priority

high (do before any feature work touches the analysis package)

## Problem

The package has well-named files along stage boundaries, but six concrete frictions remain — each verified by reading the code, each one a place where the implementation has diverged from the package's own stated intent.

1. **`analyze.py` is thick where its CLAUDE.md says it should be thin.** The file's CLAUDE.md says `analyze()` "should stay small and read as orchestration." Today the `analyze()` body alone is 330 LOC across 17 inline sub-steps, and the file is 1,095 LOC total. The remaining 632 LOC are helpers, every one of which has a CLAUDE-blessed home elsewhere in the package. A reader who wants to understand "how does pflow analyze caching?" must load the full file.

2. **The `PerCallRow` legacy bridge is debt acknowledged in its own docstring.** `PerCallRow.__post_init__` (types.py:404) admits: *"A large helper-test surface still instantiates PerCallRow with the old cacheable scalar."* The bridge synthesizes new projection objects from the legacy `cacheable_tokens_estimated` scalar. It costs ~158 LOC across two files:
   - `types.py:403-485` (~82 LOC) — the synthesis in `__post_init__`
   - `stages/row_builder.py:321-366` (~46 LOC) — `_apply_cross_workflow_projection`, producing the legacy scalar
   - `stages/row_builder.py:369-398` (~30 LOC) — `_clamp_legacy_cacheable_projection`, clamping the legacy scalar

3. **The cross-workflow analytical stage mixes analysis with rendering, and the seam is suspiciously clean.** `stages/cross_workflow.py` is 1,344 LOC. ~270 LOC of `_format_*` helpers produce paste-ready cache-block edit text. The seam between analysis and rendering is exactly one call (`_emit_sub_workflow_cache_findings` → `format_grouped_body_block`), passing three frozen dataclasses; the render side does not import `Diagnostic` (it returns plain strings embedded via `make_diagnostic(body_block=...)`). That cleanness is the signal of a real seam.

4. **`AnalysisContext` is workflow-path-locked, forcing a 188-LOC mirror cluster.** `AnalysisContext.resolve_ref_value` uses `self.workflow_path` only. Sub-workflow boundary analysis needs to resolve refs scoped to a different (parent) workflow, so `stages/cross_workflow.py:399-595` re-implements the entire parameters/memo/trace resolution chain — six functions, 188 LOC, with `workflow_path` as a parameter. Its docstring identifies the duplication explicitly: *"Cross-workflow analog to AnalysisContext._resolve_from_memo (which keys on self.workflow_path)."*

5. **The cost API contradicts itself on contract.** `cost_estimation.py:__all__` declares four helpers public: `_aggregate_no_cache_cost`, `_aggregate_with_cache_projection`, `_row_body_only_cost`, `_row_first_run_with_cache_cost`. They are exported with leading underscores. Tests import them across what looks like a "private" boundary; the export contract has been public the whole time. The naming says "internal" while `__all__` says "public" — one of them is wrong.

6. **Hidden duplications and a name collision.**
   - `_template_resolver()` is byte-identical across four files (`stages/row_builder.py:51`, `stages/warnings.py:37`, `stages/cross_workflow.py:27`, `stages/discrepancy/predict.py:21`).
   - `_cache_items` is defined in both the package's root walker (`tuple` return) and `stages/suggestions.py` (`list` return) — same conceptual operation, two adapters with diverging return types.
   - The walker module and the analytical stage are both named `cross_workflow.py` at different package levels; co-imports in `analyze.py:53-54` and ~50 `importlib.import_module(...)` test sites have to disambiguate by dotted path and by local-name conventions (`cross_module` vs. `cross_stage_module`).

## Solution

### Target architecture

**A thin orchestrator.** `analyze.py` reduces to ~250 LOC. The `analyze()` body is the 7-step pipeline its own CLAUDE.md describes — one named function call per stage, no inline state mutation. Three current inline blocks (trace-misalignment recovery, per-call visibility notes, summary enrichment) move to named functions or push down into the stage modules they belong to. Helpers move to their natural homes: parameter resolution to the walker, row-assembly orchestration to `stages/row_builder.py`, drift detection and call counts to `trace_loading.py`, cross-workflow row-level candidates to `stages/cross_workflow.py`. Lazy-import workarounds for inverted cycles disappear with their causes.

**One row contract.** `PerCallRow` is constructed only in the projection-object shape. `__post_init__` shrinks to its essential ~10 LOC `cached_now_tokens_estimated` derivation; the legacy synthesis is gone. `stages/row_builder.py` removes both producer-side bridge functions. `types.py` matches its own docstring's promise: "types here should remain lightweight and safe to import from any analyzer consumer."

**Cross-workflow analysis and rendering live in separate files.** `rendering/cross_workflow_edits.py` (~270 LOC) hosts the `_format_*` helpers and their pure private utilities. The seam is one public function (`format_grouped_body_block`) and three seam dataclasses (`SubWorkflowCacheCandidate`, `SubWorkflowCacheGroup`, `GroupedConsumerProjection`), which move to `types.py` so rendering imports only from types. `_cache_refs_by_consumer` becomes a method on `SubWorkflowCacheGroup`. The vestigial `cw_result` parameter — currently threaded through seven render-side functions for nothing — is removed.

**`AnalysisContext` is workflow-path-parametric.** New methods `resolve_ref_value_in_workflow(ref, workflow_path=...)` and `resolve_ref_value_for_projection_in_workflow(ref, workflow_path=...)` accept the workflow path as a parameter. The cross-workflow stage's 188 LOC of mirror code collapses to delegation; only domain-specific helpers (`_estimate_parent_value_tokens` and child-suffix walking) remain.

**Cost API naming matches its export contract.** The five helpers exposed by `cost_estimation.py:__all__` lose the underscore prefix (`_pricing_from_dict` joins `__all__` first, then the rename). No new public surface; the names align with what the contract already declares. Tests stop importing across a "private" boundary that was never private.

**Hidden duplications resolved.**
- `_template_resolver()` lives once, as a module-level function in `context.py`. All four duplicate copies are removed; every consumer imports from `..context`.
- The package's root walker file is renamed `sub_workflow_walker.py`. There is no longer a file-name collision with the analytical stage; tests stop relying on local-name conventions to keep them apart.
- The walker-side `_cache_items` is disambiguated (renamed or inlined at its two call sites) so the package contains one `_cache_items` function with one return type.

**Documented test surfaces.** `stages/discrepancy/CLAUDE.md` gains a "Test API" section listing `_predict_node_cache_key` (whose docstring already declares it as "kept for direct test callers") and the three `_format_*_note` helpers as stable test surfaces. Implicit coupling becomes explicit contract — no code change, just documentation that matches reality.

**One small UX improvement.** `per_call_row_has_real_data` (currently a free function in `rendering/views.py`, imported by the orchestrator) becomes a `@property` on `PerCallRow`. Both rendering and analyzer call sites read `row.has_real_data`. The orchestrator no longer reaches into rendering.

### Target layout

```
src/pflow/core/prompt_cache_analysis/
├── __init__.py                          # unchanged
├── CLAUDE.md                            # update: drop "two cross_workflow.py by design" note;
│                                          point references at sub_workflow_walker.py
│
├── analyze.py                           # SHRUNK ~1,095 → ~350 LOC (G1)
│                                          orchestrator + 3 named extraction-points only;
│                                          helpers moved to their natural homes
├── types.py                             # G2 + G3.2 + G1.3:
│                                          - PerCallRow.__post_init__ bridge body removed (~ -70 LOC)
│                                          - PerCallRow.has_real_data @property added (~ +6 LOC)
│                                          - Three seam dataclasses moved IN from stages
│                                            (SubWorkflowCacheCandidate, SubWorkflowCacheGroup,
│                                             GroupedConsumerProjection) (~ +80 LOC)
│                                          net ~890 → ~905 LOC; content finally matches docstring
├── context.py                           # GREW ~335 → ~420 LOC (G4 + G6.1)
│                                          + resolve_ref_value_in_workflow (~30 LOC)
│                                          + resolve_ref_value_for_projection_in_workflow (~30 LOC)
│                                          + module-level template_resolver() (~4 LOC)
│                                          + threading of workflow_path into freshness check
├── trace_loading.py                     # GREW ~914 → ~1,020 LOC (G1.5c)
│                                          + drift detection helpers from analyze.py
│                                          + call-counts helper from analyze.py
├── sub_workflow_walker.py               # RENAMED from cross_workflow.py (G6.2)
│                                          GREW ~447 → ~590 LOC (G1.5a)
│                                          + parameter resolution cluster from analyze.py
│                                            (_build_parameters_by_workflow + 4 helpers)
│                                          - walker-side _cache_items disambiguated (G6.3)
├── cost_estimation.py                   # G5 — internal helpers renamed (no LOC change):
│                                          aggregate_no_cache_cost,
│                                          aggregate_with_cache_projection,
│                                          row_body_only_cost,
│                                          row_first_run_with_cache_cost,
│                                          pricing_from_dict (added to __all__)
├── token_estimation.py                  # unchanged
├── below_min_tokens_detector.py         # unchanged
├── warning_catalog.py                   # unchanged
│
├── stages/
│   ├── __init__.py                      # unchanged
│   ├── row_builder.py                   # G1.5b + G2.3 + G2.4 + G6.1:
│   │                                      + _build_per_call_rows_and_warnings IN (~80 LOC)
│   │                                      + _detect_candidate_subsets IN (~20 LOC)
│   │                                      - _apply_cross_workflow_projection (~ -46 LOC)
│   │                                      - _clamp_legacy_cacheable_projection (~ -30 LOC)
│   │                                      - _template_resolver duplicate (~ -4 LOC)
│   │                                      net ~1,138 → ~1,158 LOC
│   ├── warnings.py                      # G6.1: -_template_resolver duplicate
│   ├── suggestions.py                   # unchanged
│   ├── fragmentation.py                 # unchanged
│   ├── partial_declarations.py          # unchanged
│   ├── cross_workflow.py                # SHRUNK ~1,344 → ~990 LOC (G3 + G4 + G1.5d + G6.1):
│   │                                      - format helpers → rendering/cross_workflow_edits.py
│   │                                                                              (~ -270 LOC)
│   │                                      - mirror resolution cluster collapses to delegation
│   │                                                                  (~ -158 LOC, from 188 LOC)
│   │                                      + row-level candidates IN from analyze.py
│   │                                          (_RowCrossWorkflowCandidate + 4 producers, ~ +177 LOC)
│   │                                      - _template_resolver duplicate (~ -4 LOC)
│   │                                      - cw_result threading vestige (~ -5 LOC)
│   ├── summary.py                       # G1.4: _build_summary signature gains 4 kwargs
│   │                                      (trace_workflow_relationship, drift_count,
│   │                                       sub_workflow_rollup, suggested_run_command)
│   └── discrepancy/
│       ├── __init__.py                  # unchanged
│       ├── CLAUDE.md                    # NEW (G7.1) — "Test API" section listing
│       │                                  _predict_node_cache_key + 3 _format_*_note helpers
│       ├── predict.py                   # G6.1: -_template_resolver duplicate
│       └── diagnose.py                  # unchanged
│
└── rendering/
    ├── __init__.py                      # may re-export from cross_workflow_edits if needed
    ├── text.py                          # unchanged (out of scope here)
    ├── json.py                          # unchanged
    ├── views.py                         # G1.3: -per_call_row_has_real_data (moved to types.py)
    ├── summarize.py                     # unchanged
    ├── traces_list.py                   # unchanged
    └── cross_workflow_edits.py          # NEW ~270 LOC (G3.1) — format helpers extracted
                                           from stages/cross_workflow.py;
                                           single public function format_grouped_body_block
```

### Net file count and LOC

- One new file (`rendering/cross_workflow_edits.py`).
- One new doc (`stages/discrepancy/CLAUDE.md`).
- One file renamed (`cross_workflow.py` → `sub_workflow_walker.py` at package root).
- Package LOC roughly flat (~16,300 → ~16,300). The work is redistribution, not net growth or shrink. The orchestrator drops ~750 LOC; rendering gains ~270; sub_workflow_walker, trace_loading, stages/row_builder absorb the rest; types.py is roughly flat; stages/cross_workflow.py shrinks ~350.

### What stays unchanged

- `AnalysisContext`'s existing Interface and existing methods. The parametric forms extend it; the workflow-path-locked variants remain valid for root-workflow callers.
- `cost_estimation.py`'s structure: two entry points (`compute_projections`, `compute_actually_paid`), three typed result shapes. Only naming changes.
- The discrepancy `predict.py` / `diagnose.py` sub-package split — an exemplar of "one clean seam."
- `stages/fragmentation.py`'s `_detect_cache_fragmentation_by` (a 66-LOC parametric engine with two real adapters) — an exemplar of "two adapters = real seam done right."
- The four-tier token estimation in `token_estimation.py`, the cost tiers in `cost_estimation.py`, the warning catalog, the below-min detector.
- `rendering/text.py` at 2,423 LOC. The file is large but its eight section renderers have clean boundaries; physical decomposition is navigability work, not depth work, and not in scope here.

## Goal Tree

```
deepen prompt_cache_analysis along earned-but-uncollapsed seams
│
├── G1. Thin the orchestrator — analyze.py reads as a 7-step pipeline
│   ├── G1.1 analyze() body has no inline state-mutation blocks; each step is a named call
│   ├── G1.2 Trace-misalignment recovery extracted from the body
│   ├── G1.3 Per-call visibility notes extracted; row.has_real_data property replaces
│   │        the orchestrator's reach into rendering/views.py
│   ├── G1.4 Summary enrichment pushed into _build_summary kwargs
│   ├── G1.5 Helpers relocated to natural homes
│   │   ├── G1.5a Parameter resolution → the walker module
│   │   ├── G1.5b Row-assembly orchestration → stages/row_builder.py
│   │   ├── G1.5c Drift detection + call counts → trace_loading.py
│   │   └── G1.5d Cross-workflow row-level candidates + _RowCrossWorkflowCandidate
│   │             → stages/cross_workflow.py
│   └── G1.6 Lazy-import cycle workarounds disappear (cycle broken at the type level)
│
├── G2. Remove the PerCallRow legacy bridge
│   ├── G2.1 Test fixtures migrated off the legacy cacheable_tokens_estimated
│   │        scalar constructor
│   ├── G2.2 PerCallRow.__post_init__ shrinks to ~10 LOC
│   │        (only cached_now_tokens_estimated derivation)
│   ├── G2.3 _apply_cross_workflow_projection deleted (producer-side bridge)
│   └── G2.4 _clamp_legacy_cacheable_projection deleted (producer-side clamping)
│
├── G3. Split cross-workflow analysis from its rendering
│   ├── G3.1 rendering/cross_workflow_edits.py hosts all _format_* helpers (~270 LOC)
│   ├── G3.2 Three seam dataclasses (SubWorkflowCacheCandidate, SubWorkflowCacheGroup,
│   │        GroupedConsumerProjection) move to types.py
│   ├── G3.3 _cache_refs_by_consumer becomes a method on SubWorkflowCacheGroup
│   ├── G3.4 Vestigial cw_result parameter removed from 7 format functions
│   └── G3.5 Render side does not import Diagnostic; the seam exchanges plain strings
│
├── G4. Parametrize AnalysisContext on workflow_path
│   ├── G4.1 ctx.resolve_ref_value_in_workflow(ref, *, workflow_path) exists
│   ├── G4.2 ctx.resolve_ref_value_for_projection_in_workflow(ref, *, workflow_path) exists
│   ├── G4.3 The 188-LOC mirror cluster in stages/cross_workflow.py
│   │        (_resolve_value_in_workflow_*) collapses to delegation
│   └── G4.4 Existing workflow-path-locked methods preserved
│
├── G5. Align cost API naming with its export contract
│   ├── G5.1 Four helpers already in cost_estimation.py:__all__ lose the underscore
│   ├── G5.2 _pricing_from_dict joins __all__ and is renamed
│   ├── G5.3 All internal callers and tests use the new names
│   └── G5.4 Stale lazy cost_estimation imports at stage call sites hoisted to top-level
│
├── G6. Resolve hidden duplications and collisions
│   ├── G6.1 _template_resolver() lives once, as a module-level function in context.py
│   │        (4 duplicates removed)
│   ├── G6.2 Package's root walker file renamed sub_workflow_walker.py
│   │        (file-name collision gone; ~50 importlib string sites updated)
│   └── G6.3 _cache_items name collision resolved
│        (walker-side renamed or inlined at its 2 call sites)
│
└── G7. Document discrepancy test surfaces
    └── G7.1 stages/discrepancy/CLAUDE.md gains a "Test API" section listing
             _predict_node_cache_key and the three _format_*_note helpers
             as stable test surfaces
```

**Cross-cutting (Bx) — behavior preservation.** Applies to every goal. Byte-identical text and JSON output; identical `pflow run --dry-run` cache nudge; every warning ID continues to fire under the same conditions. Verified via the Task 159 regression harness.

**Goal independence.** G1–G7 are conceptually independent. Two file-level overlaps exist: G1.5d and G3 both touch `stages/cross_workflow.py`; G2 and G1.5b both touch `stages/row_builder.py`. All other goal pairs are file-disjoint.

## Design Decisions

1. **No `projection_algebra.py` extraction.** The projection algebra in `types.py` (~200 LOC: `aggregate_projection`, `_best_component`, etc.) is real behavior but has one consumer path. Per the deepening criterion, "one adapter means a hypothetical seam." Extracting it would add Interface surface without adding leverage. The algebra correctly lives next to its dataclass.

2. **No shared `_ir_helpers.py` module.** The five IR helpers (`_node_inputs`, `_batch_aliases`, `_cache_items`, `_cache_item_names`, `_is_batch_scoped_ref`) are heterogeneous — node accessors, workflow-IR accessors, and batch predicates — and each is used heavily within its host file. Forcing them into a shared module would add a row to the "Where to add a new feature" table for no real gain.

3. **The cost API change is a rename, not a new public API.** Because `cost_estimation.py:__all__` already exposes the four underscored helpers, the rename closes the gap between contract and convention. No new surface is added.

4. **`_template_resolver()` folds into `context.py`, not a new file.** The lazy-import pattern matches what `context.py` already does internally for its own resolver calls. Adding a `_lazy.py` would grow the file count for a four-line helper.

5. **`AnalysisContext` extends rather than replaces.** The new parametric methods supplement the existing workflow-path-locked methods rather than deprecating them. Root-workflow callers continue to use the simpler form.

6. **The `PerCallRow` bridge is removed only after test fixtures migrate.** The bridge exists because tests construct rows with the legacy scalar. Production callers already use the projection-object shape. The order is: migrate tests → delete bridge → delete producer-side bridge helpers.

7. **Discrepancy substrate's private test imports stay private at the code level.** `_predict_node_cache_key` exists explicitly for tests; the other discrepancy internals (`_pad_inputs_for_prediction`, `_node_references_any`, `_build_predict_scaffold`, `_dummied_cache_chunks`) are surgical branch-logic tests with no observable shape via `analyze()` alone. Documenting them as a stable test surface in CLAUDE.md is the architecturally honest move; renaming them to "public" would over-claim the contract.

8. **`cache_overlap.py`'s duplicates of `_batch_aliases` and `_is_batch_scoped_ref` are preserved.** They exist by design to keep the one-way analyzer → `data_flow.py` dependency. Consolidating them would create a back-import.

9. **`rendering/text.py` section-split is out of scope.** Honest framing: the file is cohesive, just large. Physical decomposition improves navigation without improving Interface leverage. Worth doing eventually, but a separate concern.

## Dependencies

None.

## Requirements

Leaves below are indexed by the goal IDs in the Goal Tree.

### G1 — Orchestrator

- **G1.1** The body of `analyze()` reads as a 7-step pipeline: one named function call per pipeline stage, no inline state-mutation blocks.
- **G1.2** Trace-misalignment recovery exists as a named function (e.g. `_recompute_after_trace_misalignment`) — never inline in `analyze()`.
- **G1.3** `PerCallRow` exposes a `has_real_data` `@property`. Both the analyzer's visibility-note generation and rendering read `row.has_real_data`. `per_call_row_has_real_data` is removed from `rendering/views.py`. `analyze.py` does not import from `rendering/*`.
- **G1.4** Summary enrichment is performed inside `_build_summary` via additional kwargs, not via an outer `replace(summary, ...)` in `analyze()`.
- **G1.5** Each helper currently in `analyze.py` lives in its natural home: parameter resolution in the walker module; row-assembly orchestration in `stages/row_builder.py`; drift detection and call counts in `trace_loading.py`; cross-workflow row-level candidates (including `_RowCrossWorkflowCandidate`) in `stages/cross_workflow.py`.
- **G1.6** No `from .stages.cross_workflow import ...` blocks exist inside helper bodies. The cycle is broken at the type level by relocating `_RowCrossWorkflowCandidate` and its producers to `stages/cross_workflow.py`.
- **G1-size** `analyze.py` final size ≤ ~350 LOC.

### G2 — PerCallRow bridge removal

- **G2.1** All test fixtures that constructed `PerCallRow` with the legacy `cacheable_tokens_estimated` scalar are migrated to the projection-object shape.
- **G2.2** `PerCallRow.__post_init__` contains only the `cached_now_tokens_estimated` derivation (~10 LOC). The legacy `cacheable_tokens_estimated`-driven synthesis is gone.
- **G2.3** `_apply_cross_workflow_projection` is deleted from `stages/row_builder.py`. Production rows are constructed only via `_cross_workflow_projection_components`.
- **G2.4** `_clamp_legacy_cacheable_projection` is deleted. Token capping lives only in `_cap_projection_tokens` (types.py).
- **G2-prod** No production caller constructs `PerCallRow` with the legacy scalar shape.

### G3 — Cross-workflow analysis/rendering split

- **G3.1** `rendering/cross_workflow_edits.py` exists and hosts all `_format_*` helpers currently in `stages/cross_workflow.py` plus their pure private utilities. The module exports one public function (`format_grouped_body_block`); its sole caller is `_emit_sub_workflow_cache_findings` in the analytical stage.
- **G3.2** The three seam dataclasses (`SubWorkflowCacheCandidate`, `SubWorkflowCacheGroup`, `GroupedConsumerProjection`) live in `types.py` with package-internal naming.
- **G3.3** `_cache_refs_by_consumer` is a method on `SubWorkflowCacheGroup`. Both analysis and rendering call `group.cache_refs_by_consumer()`.
- **G3.4** `cw_result` is not a parameter of any `_format_*` function.
- **G3.5** The render module does not import `Diagnostic`. The seam exchanges plain strings.

### G4 — AnalysisContext parametric extension

- **G4.1** `AnalysisContext.resolve_ref_value_in_workflow(ref, *, workflow_path)` exists and resolves a ref against the parameters / memo / trace tier chain scoped to the given workflow path.
- **G4.2** `AnalysisContext.resolve_ref_value_for_projection_in_workflow(ref, *, workflow_path)` exists with the trace-output extension scoped to the given workflow path.
- **G4.3** The six mirror functions in `stages/cross_workflow.py` (`_resolve_value_in_workflow_memo`, `_resolve_value_in_workflow_parameters`, `_resolve_value_in_workflow_trace`, `_trace_node_output_for`, `_resolve_input_at_workflow_node_invocation`, `_resolve_child_suffix_in_value`) are gone or reduced to thin domain-specific helpers (≤ ~30 LOC of remainder, covering `_estimate_parent_value_tokens` and child-suffix walking).
- **G4.4** Existing `AnalysisContext.resolve_ref_value(ref)` and `AnalysisContext.resolve_ref_value_for_projection(ref)` are preserved.
- **G4-memo** `_latest_memo_for_freshness_check` accepts `workflow_path` as a parameter; mutation of `stale_memo_skipped` / `stale_memo_uncheckable` continues to key on `(workflow_path, node_id)`.

### G5 — Cost API naming

- **G5.1** `cost_estimation.py:__all__` lists four names without leading underscores: `aggregate_no_cache_cost`, `aggregate_with_cache_projection`, `row_body_only_cost`, `row_first_run_with_cache_cost`.
- **G5.2** `pricing_from_dict` is in `__all__` (its prior `_pricing_from_dict` form had not been exported).
- **G5.3** All internal callers (`suggestions.py`, `warnings.py`, `summary.py`, `stages/fragmentation.py`, `stages/partial_declarations.py`) and all tests use the new names.
- **G5.4** Stale lazy `from ..cost_estimation import ...` imports inside stage function bodies are hoisted to top-level imports where no genuine load-cost reason exists. Comments claiming a non-existent circular import are removed.

### G6 — Hidden duplications and collisions

- **G6.1** `_template_resolver()` is defined once, as a module-level function in `context.py`. The four stage-file copies are removed. Each importer uses `from ..context import template_resolver`.
- **G6.2** The package's root walker file is named `sub_workflow_walker.py`. All production imports and all `importlib.import_module(...)` test sites use the new dotted path. The CLAUDE.md disambiguation note about "two cross_workflow.py files by design" is removed.
- **G6.3** The walker-side `_cache_items` is renamed (or inlined at its two call sites). The package contains exactly one function named `_cache_items`.
- **G6-preserve** `core/cache_overlap.py`'s copies of `_batch_aliases` and `_is_batch_scoped_ref` are NOT consolidated — they exist by design to keep the one-way analyzer → `data_flow.py` dependency.

### G7 — Test surface documentation

- **G7.1** `stages/discrepancy/CLAUDE.md` exists. It contains a "Test API" section listing as stable test surfaces: `_predict_node_cache_key`, `_format_dynamic_batches_note`, `_format_fidelity_skip_note`, `_format_skipped_workflows_note`.

### Bx — Behavior preservation (cross-cutting)

- **Bx.1** `pflow analyze-cache` produces byte-identical text output for any given workflow + trace input.
- **Bx.2** `pflow analyze-cache --json` produces structurally-identical JSON (`format_version` unchanged at `"5.0"`).
- **Bx.3** `pflow run --dry-run` cache nudge produces an identical `Diagnostic`.
- **Bx.4** Every cache-related warning ID continues to fire under the same conditions.
- **Bx.5** All `__all__` exports from `pflow.core.prompt_cache_analysis` remain importable from the same package path.

## Implementation Notes

### Verified non-issues — do not "fix"

- The projection algebra in `types.py` is leaf logic with one consumer path. Do not extract.
- The five IR helpers in `suggestions.py` and `row_builder.py` are correctly placed near their primary consumers. Do not centralize.
- `cache_overlap.py`'s `_batch_aliases` / `_is_batch_scoped_ref` duplicates exist by design.
- The lazy imports inside `stages/discrepancy/predict.py` (compile_workflow, plan_node, create_planner_shared) are policy — they save ~700ms of LiteLLM startup on dry-run paths. Keep them lazy.
- `rendering/text.py` at 2,423 LOC is cohesive. Section-splitting is out of scope.

### Friction points

- **Cycle inversion for the orchestrator thinning.** Moving `_RowCrossWorkflowCandidate` and its producers from `analyze.py` back into `stages/cross_workflow.py` removes the lazy-import workarounds, but the producers depend on `_node_inputs`, `_static_excerpt`, and `_total_observed_invocations` from `stages/row_builder.py`. Verify the import direction stays one-way after the move.
- **`PerCallRow` bridge migration order.** Every test that constructs `PerCallRow(cacheable_tokens_estimated=...)` must be rewritten before the bridge can be deleted. Tests currently rely on `__post_init__` to synthesize projections from the legacy scalar.
- **`_template_resolver()` lazy-import preservation.** The function body must lazy-import `pflow.runtime.template_resolver`; do not hoist that import to module-level in `context.py`. Importing at module load would eagerly load the runtime stack on any context.py import.
- **Walker rename touches string-path sites.** Approximately 50 `importlib.import_module("pflow.core.prompt_cache_analysis.cross_workflow")` calls in `test_cache_analysis_per_id_emission.py` use a string-typed module path and need updating.
- **AnalysisContext parametric methods must not break stale-memo accounting.** `_latest_memo_for_freshness_check` mutates per-instance accumulator sets keyed on `(workflow_path, node_id)`. The parametric form must pass the new workflow_path through to the freshness check; passing `self.workflow_path` would silently mis-attribute staleness.

## Verification

- `make test` and `make check` pass.
- The Task 159 regression harness (`.taskmaster/tasks/task_159/baseline/verify.sh`) reports the same drift count as before this work (currently 80 passed, 7 drifted from pre-existing feature work).
- `pflow analyze-cache` produces byte-identical text and JSON output for unchanged workflows + traces.
- `pflow run --dry-run` cache nudge produces an identical `Diagnostic`.
- `grep -rn "from pflow.core.prompt_cache_analysis.*import _" tests/ --include="*.py" | wc -l` is at least 15 lower than today's count (current: 75; the cost-helper renames eliminate ~15 sites by themselves).
- `find src/pflow -name "cross_workflow.py"` returns one path (the analytical stage).
- `grep -rn "def _template_resolver" src/pflow/core/prompt_cache_analysis/` returns no matches (the helper lives in context.py as `def template_resolver`).
- `wc -l src/pflow/core/prompt_cache_analysis/analyze.py` reports at or below ~350 LOC.
- `wc -l src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py` reports at or below ~1,070 LOC (rendering surface removed).
- The `_resolve_value_in_workflow_*` cluster in `stages/cross_workflow.py` is gone; the file's resolution-side helpers are ≤ ~30 LOC of domain-specific code.
- `uv run python -c "from pflow.core.prompt_cache_analysis.cross_workflow import walk_cross_workflow"` raises `ImportError` (walker moved).
- `uv run python -c "from pflow.core.prompt_cache_analysis.sub_workflow_walker import walk_cross_workflow"` succeeds.
- A reader who has never seen the package can find "where is X computed?" by reading file names + CLAUDE.md, in under 60 seconds.

## References

- `src/pflow/core/prompt_cache_analysis/CLAUDE.md` — the package's own self-description; the spec aligns the implementation with what this file already declares.
- `.claude/skills/improve-codebase-architecture/LANGUAGE.md` — vocabulary used here (Module, Interface, Implementation, Depth, Seam, Adapter, Leverage, Locality).
- `.taskmaster/tasks/task_160/implementation/progress-log.md` — history of the package's prior structural decomposition (the starting state for this work).
- `.taskmaster/tasks/task_160/implementation/retrospective-and-future-improvements.md` — initial critique that surfaced eight insights; verified, revised, and extended by this spec after a full file-by-file read.
- `.taskmaster/tasks/task_159/baseline/verify.sh` — regression harness for zero-behavior-change verification.
