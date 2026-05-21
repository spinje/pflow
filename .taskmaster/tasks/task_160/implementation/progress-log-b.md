# Task 160 Implementation Progress Log B

## 2026-05-21 - Phase 0 Pre-flight Baseline

Phase completed: Phase 0 only. No production or test code was changed.

Baseline harness:
- Command: `PATH="$PWD/.venv/bin:$PATH" bash .taskmaster/tasks/task_159/baseline/verify.sh 2>&1 | tee /tmp/baseline-pre-refactor.log`
- Result: `80 passed, 7 drifted, 0 harness errors`
- Drifted cases captured as the known-drift set:
  - `03-analyze-cache-modes/07-autoload-prefers-success`
  - `03-analyze-cache-modes/08-autoload-failed-only`
  - `03-analyze-cache-modes/09-autoload-rejected-names-file`
  - `04-warning-catalog/23-cache.batch-prewarm-lower-bound-recommended`
  - `04-warning-catalog/23b-cache.batch-prewarm-lower-bound-recommended-text`
  - `12-real-world-lyrics-generator/04-guide-auto-detect`
  - `15-run-flag-interactions/03-report-with-only`

Unit test baseline:
- Used the `pflow-sandbox-testing` guidance instead of raw `make test` / `uv run`.
- Command: `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e" -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete'`
- Result: `7102 passed, 1 skipped`
- Rationale for deviation: the three excluded tests are documented sandbox/tooling failures in `pflow-sandbox-testing`; this preserves the intended non-e2e baseline without treating sandbox subprocess limitations as product failures.

Collected-test reference:
- Command: `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest --collect-only -q 2>&1 | tee /tmp/baseline-collected-tests.log`
- Result: `7155 tests collected`

Quality baseline:
- `uv lock --locked`: passed after escalation because sandboxed uv could not read `/Users/andfal/.cache/uv/...`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a`: passed after escalation because pre-commit needed to fetch hook environments from GitHub.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 223 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.

Package metrics:
- Private prompt-cache-analysis imports in tests: `59`. This differs from the plan's expected `75`, so Phase 1's "reduce by at least 15" target should be interpreted against the observed baseline, not the stale estimate.
- `src/pflow/core/prompt_cache_analysis/analyze.py`: `1095` lines.
- `src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py`: `1344` lines.
- `_template_resolver` duplicates: 4 sites:
  - `stages/cross_workflow.py`
  - `stages/row_builder.py`
  - `stages/warnings.py`
  - `stages/discrepancy/predict.py`

Subagent use:
- No code-implementer subagents were used in Phase 0. This phase was read-only baseline capture with no mechanical implementation work to parallelize. Using an implementer here would add coordination cost without advancing the phase.

Trust boundary for Phase 1:
- Verified: harness works in this sandbox with `.venv/bin` on `PATH`; baseline drift set is known; unit/quality gates are green with the documented sandbox substitutions.
- Assumed correct: the implementation plan's Phase 1 file list remains current enough to start from, but the observed private-import count shows at least one metric in the plan is stale.
- Unable to verify in Phase 0: whether Phase 1 import hoisting has no hidden cycle. That must be verified during Phase 1 with targeted imports and the full harness.

## 2026-05-21 - Phase 1 Foundation Cleanups

Phase completed: Phase 1 only.

Implemented:
- G5: renamed exported cost helpers in `cost_estimation.py`:
  - `_aggregate_no_cache_cost` -> `aggregate_no_cache_cost`
  - `_aggregate_with_cache_projection` -> `aggregate_with_cache_projection`
  - `_row_body_only_cost` -> `row_body_only_cost`
  - `_row_first_run_with_cache_cost` -> `row_first_run_with_cache_cost`
  - `_pricing_from_dict` -> `pricing_from_dict`
- Added `pricing_from_dict` to `cost_estimation.__all__`.
- Updated cost helper tests and internal callers to use the new names.
- G5.4: hoisted stale cost-estimation lazy imports out of stage function bodies.
- G6.1: added canonical `template_resolver()` to `context.py`; removed four duplicate stage-local resolver helpers and updated callers.

Deviations and rationale:
- Cost imports were hoisted as module imports (`cost_estimation.*`) rather than direct function aliases in stage modules. Direct aliases broke existing monkeypatch seams in `test_cache_analysis_per_id_emission.py` where tests patch `cost_estimation.get_model_pricing`; module lookup preserves that test contract while still removing the stale function-body lazy imports.
- The plan's literal lazy-import check (`import pflow.core.prompt_cache_analysis.context` must not load `pflow.runtime.template_resolver`) is not a valid assertion in the current package shape because importing that submodule executes package `__init__`, which imports the analyzer surface and already reaches runtime modules through pre-existing paths. Verified the Phase 1 invariant instead: no stage file imports `TemplateResolver` directly, no `_template_resolver` duplicates remain, and importing the package does not eagerly import `litellm`.
- Private prompt-cache-analysis imports in tests stayed at `59`. The Phase 0 baseline already showed the plan's `75 -> <=60` metric was stale; Phase 1 still removes the misleading underscored cost-helper imports, but that metric no longer moves.
- No code-implementer subagents were used. Phase 1 was a tightly coupled rename/import edit across shared stage modules; parallelizing it would have increased the chance of conflicting import style changes without meaningful time savings.

Verification:
- Task 159 harness after implementation and after formatting: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- Sandbox-safe non-e2e pytest: `7102 passed, 1 skipped`.
- Focused pricing seam regression after import-hoist adjustment: `test_fragmentation_skips_when_any_group_cost_is_none` and `test_write_penalty_fires_for_single_call_with_declared_cache` both pass.
- `uv lock --locked`: passed after escalation for uv home-cache access.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a`: passed after escalation for sandboxed metadata-file writes.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 223 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.
- G6.1 checks:
  - `rg "def _template_resolver|_template_resolver\\(" src/pflow/core/prompt_cache_analysis` returns no matches.
  - `rg "from pflow\\.runtime\\.template_resolver import TemplateResolver" src/pflow/core/prompt_cache_analysis/stages` returns no matches.
  - Importing `pflow.core.prompt_cache_analysis.context` leaves `litellm` absent from `sys.modules`.

Trust boundary for Phase 2:
- Verified: behavior harness and unit/quality gates are green after Phase 1; cost-helper public names import successfully; resolver duplicates are gone.
- Assumed correct: stage-level module imports from `.. import cost_estimation` remain acceptable architecture because they preserve patchability and avoid reintroducing function-body lazy imports.
- Unable to verify in Phase 1: Phase 2 string-path rename blast radius. It must use the plan's defensive exact-match strategy and preserve `stages.cross_workflow` references.

## 2026-05-21 - Phase 2 Walker Rename + Cache Item Disambiguation

Phase completed: Phase 2 only.

Implemented:
- G6.2: renamed the package-root walker from `src/pflow/core/prompt_cache_analysis/cross_workflow.py` to `src/pflow/core/prompt_cache_analysis/sub_workflow_walker.py`.
- Renamed the mirrored walker test file to `tests/test_core/test_cache_analysis_sub_workflow_walker.py`.
- Updated root-walker imports and exact dotted string references to `pflow.core.prompt_cache_analysis.sub_workflow_walker` while preserving all `pflow.core.prompt_cache_analysis.stages.cross_workflow` analytical-stage references.
- Updated `CLAUDE.md`, `analyze.py` docstring prose, and the markdown parser comment so documentation no longer relies on the old two-`cross_workflow.py` disambiguation.
- G6.3: renamed the walker-local `_cache_items()` helper to `_cache_items_as_tuple()`; the only remaining `_cache_items()` in the package is the list-returning suggestions-stage helper.

Deviations and rationale:
- Used `mv` rather than `git mv` because project instructions forbid staging operations unless explicitly requested. Git still records the delete/add rename shape for review; no commit or index mutation was performed.
- Did not use code-implementer subagents for this phase. The high-risk work was one exact-path rewrite where accidental mutation of `stages.cross_workflow` strings would create silent test-patching failures; a single-writer edit plus targeted sweeps was lower risk than coordinating parallel writers.
- The first baseline harness run omitted the Phase 0/1 `.venv/bin` PATH override and reproduced the known sandbox `uv` panic pattern (`0 passed, 87 drifted`). Reran with `PATH="$PWD/.venv/bin:$PATH"`; the corrected run matched the known baseline drift set.
- Non-escalated `pre-commit run -a` failed on sandbox permissions for hidden `.codex`/`.agents` metadata files, and `ruff` applied import-order fixes. Reran escalated after those fixes; pre-commit passed.

Verification:
- Safety checks:
  - `find src/pflow -name "cross_workflow.py"` returns only `src/pflow/core/prompt_cache_analysis/stages/cross_workflow.py`.
  - `src/pflow/core/prompt_cache_analysis/sub_workflow_walker.py` exists; `src/pflow/core/prompt_cache_analysis/cross_workflow.py` is absent.
  - Importing `pflow.core.prompt_cache_analysis.sub_workflow_walker.walk_cross_workflow` succeeds; importing old `pflow.core.prompt_cache_analysis.cross_workflow` raises `ModuleNotFoundError`.
  - `rg` finds no root-walker references to `pflow.core.prompt_cache_analysis.cross_workflow`; protected stage references remain.
- Renamed walker tests: `26 passed`.
- Task 159 harness: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- Sandbox-safe non-e2e pytest after formatting: `7102 passed, 1 skipped`.
- `uv lock --locked`: passed after escalation for uv cache access.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a`: passed after escalation for all-files hook access.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 223 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.

Trust boundary for Phase 3:
- Verified: the root walker has no remaining old import path consumers in `src/` or `tests/`; the analytical stage name is unchanged and still used by tests intentionally.
- Assumed correct: delete/add rename representation is acceptable for review because no commit was requested and the final file contents preserve behavior.
- Unable to verify in Phase 2: whether Phase 3's cross-workflow rendering extraction should re-export anything from `rendering/__init__.py`; that depends on the actual caller surface during Phase 3.

## 2026-05-21 - Phase 3 Cross-Workflow Analysis/Rendering Split

Phase completed: Phase 3 only.

Implemented:
- G3.1: added `src/pflow/core/prompt_cache_analysis/rendering/cross_workflow_edits.py` for paste-ready sub-workflow cache edit text. The single external entry point is `format_grouped_body_block`; all other helpers remain private.
- G3.2: moved `_SubWorkflowCacheCandidate`, `_GroupedConsumerProjection`, and `_SubWorkflowCacheGroup` into `types.py`, preserving package-internal underscore names.
- G3.3: replaced the stage-local `_cache_refs_by_consumer()` free function with `_SubWorkflowCacheGroup.cache_refs_by_consumer()`.
- G3.4: removed the unused `cw_result` parameter from the render-side chain and the emit-side `format_grouped_body_block(...)` call.
- Moved `_workflow_basename()` into `types.py` so both the analysis stage and render helper use one implementation.
- Updated direct helper tests so render helper coverage imports from `rendering.cross_workflow_edits` and candidate fixtures import from `types.py`.

Deviations and rationale:
- Changed `rendering/__init__.py` to lazy-load its existing public exports. Import verification found a cycle introduced by the new normal stage import: `analyze -> stages.cross_workflow -> rendering.cross_workflow_edits -> rendering.__init__ -> summarize -> analyze`. Lazy package exports preserve the existing `from pflow.core.prompt_cache_analysis.rendering import render_text` API while allowing the stage to import the render seam without adding a function-body lazy import.
- Did not re-export `format_grouped_body_block` from `rendering/__init__.py`. The only consumer is the analysis stage; adding it to the package-level rendering API would make an internal seam look public.
- Did not use code-implementer subagents. The phase had one tightly coupled move across the stage/types/rendering boundary plus an import-cycle correction discovered mid-verification. A parallel writer would have increased conflict risk without isolating a genuinely mechanical, disjoint write scope.

Verification:
- Focused helper tests: `2 passed`.
- Affected cache-analysis files: `340 passed`.
- Task 159 harness: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- Sandbox-safe non-e2e pytest: `7102 passed, 1 skipped`.
- `uv lock --locked`: passed after escalation for uv cache access.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a`: passed after escalation for sandboxed metadata-file access; `ruff-format` reformatted one changed file before the successful rerun.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 224 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.
- Phase 3 structural checks:
  - `stages/cross_workflow.py`: `959` lines.
  - `rendering/cross_workflow_edits.py`: `315` lines.
  - `rg "Diagnostic|cw_result" rendering/cross_workflow_edits.py` returns no matches.
  - `_SubWorkflowCacheCandidate`, `_GroupedConsumerProjection`, `_SubWorkflowCacheGroup`, and `_workflow_basename` are defined only in `types.py`.

Trust boundary for Phase 4:
- Verified: output behavior is stable against the Task 159 harness; package-level rendering imports still work; the new render helper imports without cycling; render-side edit text no longer depends on `cw_result`.
- Assumed correct: lazy `rendering.__init__` is acceptable because direct submodule imports are already the dominant internal/test pattern, and package-level exports remain source-compatible.
- Unable to verify in Phase 3: whether Phase 4's `AnalysisContext` parametric methods can delete all mirror resolution helpers without additional test migrations beyond the plan's two named sites.

## 2026-05-21 - Phase 5 Orchestrator Inline-Block Extraction

Phase completed: Phase 5 only. Phase 4 remains unimplemented; this ordering deviation was explicitly requested by the user after the Phase 3 commit.

Implemented:
- G1.2: extracted auto-loaded trace misalignment fallback into `_recompute_after_trace_misalignment()`.
- G1.3: added `PerCallRow.has_real_data`; removed `rendering.views.per_call_row_has_real_data`; removed `rendering.text._row_has_real_data`; updated analyzer and text rendering to use `row.has_real_data`.
- G1.3: extracted the per-call visibility notes block into `_append_per_call_visibility_notes()` at the same pipeline position after `_populate_suggested_blocks()` and before `_emit_padding_advisories()`.
- G1.4: extended `_build_summary()` with `trace_workflow_relationship`, `drift_count`, `sub_workflow_rollup`, and `suggested_run_command` kwargs; removed the outer `replace(summary, ...)` enrichment block from `analyze.py`.
- Updated stale test prose references from `_row_has_real_data` / `replace(summary, ...)` to the new ownership.

Deviations and rationale:
- Skipped Phase 4 only because the user explicitly asked to continue with Phase 5. I verified Phase 5 does not require Phase 4's parametric `AnalysisContext` methods; it touches orchestration, row visibility, and summary ownership instead of the cross-workflow resolution mirror cluster.
- `analyze.py` is `1109` lines rather than the plan's expected `~1015`. The plan's LOC estimate assumes extraction reduces file size, but Phase 5 keeps the extracted helpers in `analyze.py` by design ("No module moves yet"). I tightened `_recompute_after_trace_misalignment()` to read data already owned by `AnalysisContext` instead of re-threading duplicate parameters; further LOC reduction would require Phase 6-style helper relocation, which is intentionally outside Phase 5.
- The plan's named smoke test `test_per_call_hidden_when_no_run_data` no longer exists. I ran the current equivalent focused selector over hidden/greenfield/visibility tests instead.
- Did not use code-implementer subagents. Phase 5 touched tightly coupled call ordering inside `analyze.py` plus matching renderer/type ownership changes; the only mechanical work was small enough that parallel writers would add conflict risk without saving meaningful time.

Verification:
- Focused visibility/summary selector: `33 passed, 345 deselected`.
- Affected analyzer/renderer files: `378 passed`.
- Task 159 harness: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- Sandbox-safe non-e2e pytest: `7102 passed, 1 skipped`.
- `uv lock --locked`: passed after escalation for uv cache access.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a`: passed after escalation for sandboxed metadata-file access.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 224 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.
- Phase 5 structural checks:
  - `rg "from \\.rendering.views" src/pflow/core/prompt_cache_analysis/analyze.py` returns no matches.
  - `rg "def per_call_row_has_real_data" src/pflow/core/prompt_cache_analysis` returns no matches.
  - `rg "def _row_has_real_data" src/pflow/core/prompt_cache_analysis/rendering/text.py` returns no matches.
  - `rg "replace\\(summary" src/pflow/core/prompt_cache_analysis/analyze.py` returns no matches.

Trust boundary for next phase:
- Verified: Phase 5 behavior is stable against the baseline harness and full sandbox-safe tests; `row.has_real_data` is now the single row-visibility predicate used by analyzer and text rendering.
- Assumed correct: preserving Phase 4 for later remains safe because Phase 5 did not modify the mirror resolution helpers that Phase 4 targets.
- Unable to verify in Phase 5: whether Phase 4's test migration count is complete; it was intentionally not started in this phase.
