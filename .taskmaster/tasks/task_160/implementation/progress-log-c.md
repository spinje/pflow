# Task 160 Implementation Progress Log C

## 2026-05-26 - Phase 0 Pre-flight Baseline

Phase completed: Phase 0 only. No production or test code was changed.

Files read before starting:
- `.taskmaster/tasks/task_160/implementation/implementation-plan-c.md`
- `/private/var/folders/2f/n1_2xwj17z36v7758t4zx6900000gn/T/architecture-review-20260526-210233.html`
- `.taskmaster/tasks/task_160/implementation/progress-log-b.md`
- `.taskmaster/tasks/task_160/implementation/retrospective-and-future-improvements.md`
- `.agents/skills/source-command-refactor/SKILL.md`
- `pflow-sandbox-testing` guidance supplied in the prompt

Prerequisites:
- `.venv/bin/python` exists and is executable.
- `/private/tmp/pflow-test-home` exists.
- `.taskmaster/tasks/task_159/baseline/verify.sh` exists.

Baseline harness:
- Command: `cd .taskmaster/tasks/task_159/baseline && PATH="$PWD/../../../../.venv/bin:$PATH" bash verify.sh 2>&1 | tee /tmp/baseline-pre-polish.log`
- Result: `80 passed, 7 drifted, 0 harness errors`
- Drifted cases match the canonical Plan C set exactly:
  - `03-analyze-cache-modes/07-autoload-prefers-success`
  - `03-analyze-cache-modes/08-autoload-failed-only`
  - `03-analyze-cache-modes/09-autoload-rejected-names-file`
  - `04-warning-catalog/23-cache.batch-prewarm-lower-bound-recommended`
  - `04-warning-catalog/23b-cache.batch-prewarm-lower-bound-recommended-text`
  - `12-real-world-lyrics-generator/04-guide-auto-detect`
  - `15-run-flag-interactions/03-report-with-only`

Metrics captured:
- `src/pflow/core/prompt_cache_analysis/rendering/text.py`: `2417` lines.
- `src/pflow/core/prompt_cache_analysis/stages/row_builder.py`: `1229` lines.
- `src/pflow/core/prompt_cache_analysis/token_estimation.py`: `747` lines.
- `src/pflow/core/prompt_cache_analysis/context.py`: `516` lines.
- Private prompt-cache-analysis imports in tests: `63`.

Package import cheapness:
- Command: `HOME=/private/tmp/pflow-test-home .venv/bin/python -c "import sys; import pflow.core.prompt_cache_analysis; assert 'litellm' not in sys.modules, 'litellm loaded eagerly'; print('OK')"`
- Result: `OK`.
- Deviation from plan: used `.venv/bin/python` instead of `uv run python` because the `pflow-sandbox-testing` guidance documents `uv run` as unreliable in this sandbox. This preserves the same import-cheapness assertion without depending on the unstable `uv` runner.

Subagent use:
- No code-implementer subagents were used. Phase 0 is read-only baseline capture; there was no mechanical implementation work to parallelize.

Key learning:
- Plan C's Phase 0 file-size and private-import assumptions are current on this branch. Unlike Plan B's older baseline, the observed private-import count is exactly the planned `63`, so Phase A's expected drop to about `58` is a valid local metric.

Trust boundary for Phase A:
- Verified: the branch is in the expected pre-polish state; the Task 159 harness is usable with the `.venv/bin` PATH override; baseline drift names are known; package import does not eagerly load `litellm`.
- Assumed correct: Phase A's five `_render_summary` test-site locations remain close enough to the plan to migrate mechanically, but they still need direct grep/read verification before editing.
- Unable to verify in Phase 0: whether Phase A's targeted pytest selector still names all migrated tests. That must be checked after the code change.

## 2026-05-26 - Phase A `render_text(section="summary")`

Phase completed: Phase A only.

Implemented:
- Added `_RenderSection = Literal["all", "summary"]` and `section: _RenderSection = "all"` to `rendering/text.py::render_text`.
- Added the early `section == "summary"` dispatch to return `_render_summary(analysis)` unchanged.
- Migrated the five `_render_summary(result)` test call sites in `tests/test_core/test_cache_analysis_analyze.py` to `render_text(result, section="summary")`.
- Consolidated existing local `render_text` imports in `test_cache_analysis_analyze.py` to one top-level public import: `from pflow.core.prompt_cache_analysis import render_text`.

Deviations and rationale:
- Consolidated all local `render_text` imports in the touched test file, not only the five summary-adjacent imports. Rationale: the plan explicitly called for one top-level `render_text` import rather than per-test imports; leaving existing local imports would preserve two import styles in the same file after Phase A.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a` failed before hooks could run because the sandbox HOME had no cached hook environment and network is blocked (`pypi.org` name resolution failed while installing `setuptools`).
- `.venv/bin/pre-commit run -a` with the normal cached environment reached the hooks but failed on sandbox permission errors while `end-of-file-fixer` tried to open unrelated hidden metadata files under `.codex/` and `.agents/`. It also formatted/fixed the touched Python test file; after that, changed-file pre-commit and local hook equivalents passed.

Subagent use:
- Used one `code-implementer` subagent for the disjoint mechanical test-file migration in `tests/test_core/test_cache_analysis_analyze.py`.
- Kept the production `rendering/text.py` API change local because it was the critical-path edit and had to match the plan exactly.

Verification:
- `_render_summary` sweep: only comment/docstring hits remain:
  - `tests/test_core/test_cache_analysis_analyze.py`
  - `tests/test_core/test_cache_analysis_renderers.py`
- Private prompt-cache-analysis imports in tests: `63 -> 58`.
- Focused Phase A tests: `5 passed, 181 deselected`.
- Task 159 harness: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 224 source files`.
- `.venv/bin/ruff check .`: passed after the hook-equivalent import cleanup.
- `.venv/bin/ruff format --check .`: passed, `584 files already formatted`.
- `git diff --check`: passed.
- `.venv/bin/pre-commit run --files src/pflow/core/prompt_cache_analysis/rendering/text.py tests/test_core/test_cache_analysis_analyze.py`: passed all applicable hooks.
- Package import cheapness: `HOME=/private/tmp/pflow-test-home .venv/bin/python -c "import sys; import pflow.core.prompt_cache_analysis; assert 'litellm' not in sys.modules; print('OK')"` printed `OK`.

Trust boundary for Phase B:
- Verified: `render_text(result)` remains source-compatible for existing callers; `render_text(result, section="summary")` gives tests the summary section through the public package API; no new baseline drift names were introduced.
- Assumed correct: the remaining `_format_cost` and `_format_delta_parenthetical` private imports are intentional pure-formatter substrate and should be documented in Phase B, not migrated in Phase A.
- Unable to verify in Phase A: full `pre-commit run -a` in this sandbox, because both available invocations fail on environment/sandbox setup before or outside the touched files.

## 2026-05-26 - Phase B Rendering Test Substrate Documentation

Phase completed: Phase B only.

Implemented:
- Added `src/pflow/core/prompt_cache_analysis/rendering/CLAUDE.md`.
- Documented rendering files and the stable direct-test substrate in `rendering/text.py`: `_render_summary`, `_format_delta_parenthetical`, `_format_cost`, `_cell_calls`, `_indent_message`, and `_BASELINE_LABELS`.
- Added the `rendering/CLAUDE.md` line to the parent package tree in `src/pflow/core/prompt_cache_analysis/CLAUDE.md`.

Deviations and rationale:
- Used ASCII `--` instead of typographic dashes in the new markdown. Repository editing guidance defaults to ASCII, and the existing docs do not require typographic punctuation for meaning.
- Did not run full `pre-commit run -a` again. Phase A already demonstrated the sandbox limitation: all-files pre-commit touches unrelated hidden `.codex` / `.agents` metadata files that are not writable in this environment. For Phase B, changed-file pre-commit covered the files actually edited.

Subagent use:
- No code-implementer subagents were used. Phase B was a two-file documentation update with tightly coupled wording; splitting it would add coordination overhead without a meaningful parallel write slice.

Verification:
- Task 159 harness: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- `.venv/bin/pre-commit run --files src/pflow/core/prompt_cache_analysis/rendering/CLAUDE.md src/pflow/core/prompt_cache_analysis/CLAUDE.md`: passed all applicable hooks.
- `git diff --check`: passed.

Trust boundary for Phase C:
- Verified: the Phase B documentation matches the post-Phase-A test surface and explicitly records which remaining private renderer symbols are intentional test substrate.
- Assumed correct: documenting `_render_summary` as implementation substrate is still useful even though new tests should use `render_text(..., section="summary")`; the helper remains the implementation and may still appear in historical comments.
- Unable to verify in Phase B: whether stage-level private helper imports should receive similar documentation. That is outside Phase B and intentionally belongs to later/other work, not the rendering substrate doc.

## 2026-05-26 - Phase C Per-Call Pipeline Extraction

Phase completed: Phase C only.

Implemented:
- Added `src/pflow/core/prompt_cache_analysis/stages/per_call_pipeline.py`.
- Moved `_PerCallRowsResult` and `_build_per_call_rows_and_warnings` from `stages/row_builder.py` to `stages/per_call_pipeline.py`.
- Hoisted the former function-body imports of cross-workflow candidate builders and `_per_node_warnings` to module top in `per_call_pipeline.py`.
- Updated `analyze.py` to import `_build_per_call_rows_and_warnings` and `_PerCallRowsResult` from `stages.per_call_pipeline`, while keeping `_extract_declared_chunks` imported from `stages.row_builder`.
- Left `_extract_declared_chunks` and `_detect_candidate_subsets` in `row_builder.py` per the plan. They are still row/IR primitives; moving them would expand the surface area without breaking the cycle.

Silent-failure audit:
- Direct moved-symbol imports: none in tests; production imports now point to `stages.per_call_pipeline`.
- Dynamic refs: `tests/test_core/test_cache_analysis_per_id_emission.py` imports `stages.row_builder` dynamically only to patch row-builder token/threshold functions; it does not fetch moved symbols.
- `_STAGE_ATTR_MODULES`: no update needed. `per_call_pipeline.py` does not import `estimate_tokens`, `get_min_cache_tokens`, `_estimate_ref_tokens`, `_input_rate`, or `get_default_workflow_model` directly; patched row-builder globals still affect `_build_per_call_row`.
- `caplog` logger string in `test_cache_analysis_analyze.py` remains `stages.row_builder` because the asserted log message is emitted by row-builder row construction, not by the moved orchestrator.

Deviations and rationale:
- Did not update `src/pflow/core/prompt_cache_analysis/CLAUDE.md`'s pipeline wording in Phase C even though the audit surfaced a stale row-builder reference. Rationale: Plan C assigns documentation updates for `per_call_pipeline.py` to Phase F, and Phase C's scope is the structural move plus verification. Touching that doc now would blur phase boundaries.
- Full `pre-commit run -a` still cannot complete in this sandbox because `end-of-file-fixer` tries to open unrelated hidden `.codex` / `.agents` metadata files and receives `PermissionError`. The run did reach ruff and applied one import-order cleanup in the changed production files; changed-file pre-commit passed afterward.

Subagent use:
- Used one `pflow-codebase-searcher` subagent for the Phase C silent-failure audit: moved-symbol refs, dynamic refs, monkeypatch module tuples, caplog logger ownership, and helper locations.
- No code-implementer subagents were used. The implementation write set was a tightly coupled source move across `row_builder.py`, `per_call_pipeline.py`, and `analyze.py`; splitting writers would add conflict risk. The test audit was read-only and parallelized instead.

Verification:
- Cycle/import check: `HOME=/private/tmp/pflow-test-home .venv/bin/python -c "import sys; import pflow.core.prompt_cache_analysis; assert 'litellm' not in sys.modules; print('package imports cheap, no litellm; cycle clean')"` passed.
- Function-body sibling import checks: no `row_builder.py` or `per_call_pipeline.py` function-body imports from `.cross_workflow` or `.warnings`.
- Moved-symbol location check: only `stages/per_call_pipeline.py` defines `_PerCallRowsResult` and `_build_per_call_rows_and_warnings`.
- Focused per-call selector: `10 passed, 176 deselected`.
- Related per-id/renderer suites: `357 passed`.
- Task 159 harness: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- Full sandbox-safe pytest: `7106 passed, 1 skipped`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 225 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.
- `.venv/bin/pre-commit run --files src/pflow/core/prompt_cache_analysis/analyze.py src/pflow/core/prompt_cache_analysis/stages/row_builder.py src/pflow/core/prompt_cache_analysis/stages/per_call_pipeline.py`: passed all applicable hooks.
- `git diff --check`: passed.
- File shape:
  - `stages/per_call_pipeline.py`: `115` lines.
  - `stages/row_builder.py`: `1128` lines.

Trust boundary for Phase D:
- Verified: the stage dependency graph no longer needs the two lazy imports in `row_builder.py`; production package import is cycle-clean and still cheap; no test patch or caplog string needed retargeting for the moved symbols.
- Assumed correct: keeping `_detect_candidate_subsets` in `row_builder.py` remains the right boundary because it calls `_extract_declared_chunks` and supports row-construction candidate selection, not pipeline orchestration.
- Unable to verify in Phase C: whether the parent package `CLAUDE.md` documentation should be updated immediately. The stale reference is known, but the plan deliberately reserves those documentation edits for Phase F.

## 2026-05-26 - Phase D Tokenizer Wrapper Collapse

Phase completed: Phase D only.

Implemented:
- Replaced the inlined body of `tokenize_prompt_region(...)` with a wrapper around `_tokenize_prompt_region_with_resolver(..., use_projection_resolver=False)`.
- Replaced the inlined body of `tokenize_prompt_region_lower_bound(...)` with a wrapper around `_tokenize_prompt_region_lower_bound_with_resolver(..., use_projection_resolver=False)`.
- Preserved the existing public signatures, return types, `__all__` entries, and contract docstrings.
- Left the two projection public functions unchanged because they were already wrappers over the same private helpers with `use_projection_resolver=True`.

Diff-check result:
- Compared public exact tokenizer vs `_tokenize_prompt_region_with_resolver`: differences were signature/name/docstring and `build_shared_store_for_refs(..., use_projection_resolver=...)` only.
- Compared public lower-bound tokenizer vs `_tokenize_prompt_region_lower_bound_with_resolver`: differences were signature/name/docstring and `build_shared_store_for_refs(..., use_projection_resolver=...)` only.
- No test monkeypatch or `mock.patch` targets reference the four public tokenizer functions.

Deviations and rationale:
- Net LOC is `747 -> 707`, not the plan's approximate `~640`. The plan assumed all four public functions still duplicated implementation bodies, but direct inspection showed the two projection variants were already thin wrappers before Phase D. Collapsing the two remaining inline copies is the complete safe scope for this phase; forcing further LOC reduction would require changing private implementations or unrelated code.
- Full `pre-commit run -a` still cannot complete in this sandbox because `end-of-file-fixer` hits permission errors on unrelated hidden `.codex` / `.agents` metadata files. It also added a trailing newline to unrelated staged `scratchpads/task-160-phase9/basic-output.txt` before failing; I did not revert that file because it is outside Phase D's scope and appears to be part of pre-existing staged scratchpad work.

Subagent use:
- No code-implementer subagents were used. Phase D was a single-file mechanical collapse where the critical decision was the local diff equivalence check; parallelizing the write would add risk without a disjoint work slice.

Verification:
- Public importability check for all four `tokenize_prompt_region*` functions: passed.
- Token-estimation tests: `47 passed`.
- Task 159 harness: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 225 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.
- `.venv/bin/pre-commit run --files src/pflow/core/prompt_cache_analysis/token_estimation.py`: passed all applicable hooks.
- `.venv/bin/ruff check .`: passed after the all-files hook-equivalent cleanup.
- `.venv/bin/ruff format --check .`: passed, `585 files already formatted`.
- `git diff --check`: passed.
- Package import cheapness: importing `pflow.core.prompt_cache_analysis` leaves `litellm` absent from `sys.modules`.

Trust boundary for Phase E:
- Verified: the public tokenizer API is source-stable and behavior-stable against focused tests and the baseline harness; the two private resolver helpers remain the only implementation bodies for exact and lower-bound prompt-region tokenization.
- Assumed correct: retaining detailed contract bullets on the public wrappers is preferable to moving that reader-facing contract to the private helpers, because runtime code imports the public lower-bound function directly.
- Unable to verify in Phase D: whether the remaining `token_estimation.py` memo freshness mirror can be deleted without new harness drift. That is Phase E's explicit target and must be verified separately.

## 2026-05-26 - Phase E AnalysisContext Memo Freshness Method

Phase completed: Phase E only.

Implemented:
- Added `AnalysisContext.latest_memo_for_node(node_id, *, workflow_path)` in `context.py`.
- Removed module-level `context._latest_memo_for_freshness_check`.
- Rewired `AnalysisContext._resolve_from_memo` and `_resolve_from_memo_in_workflow` to call the new method and rely on its dict-output guard.
- Removed `token_estimation._memo_output_for_freshness_check`.
- Rewired `_llm_usage_field_from_memo` to use `ctx.latest_memo_for_node(...)` when `ctx` is present and direct `memo_cache.get_latest_for_node(...)` when `ctx is None`.
- Preserved the load-bearing `_latest_value_for_ref` `ctx=None` branch and changed only its memo lookup to a direct ctx-less read.

Deviation and rationale:
- Added local `try/except` guards around the `token_estimation.py` memo reads after the first full pytest run failed in `test_discrepancy_compile_failure_falls_back_to_observable_only`. The test passes a stub memo cache while `ctx` is present; the deleted helper previously swallowed memo lookup failures and returned `None`. Keeping exception handling at the `token_estimation.py` call sites preserves that behavior without reintroducing the duplicated freshness policy.
- Did not update `context.py`'s module docstring in this phase. Plan C assigns that documentation edit to Phase F, and Phase E's scope is the ownership move plus behavior verification.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a` failed before hooks ran because the sandbox HOME had no cached hook environment and network is blocked while installing hook dependencies from PyPI.
- `.venv/bin/pre-commit run -a` with the normal cached environment reached hooks but failed on sandbox permission errors in unrelated hidden `.codex` / `.agents` metadata during `end-of-file-fixer`. In that same run, ruff and ruff-format passed.

Subagent use:
- Used one `code-implementer` subagent for the disjoint `token_estimation.py` mechanical rewire.
- Kept the `context.py` ownership move local because it was the critical semantic change and needed direct verification against the old helper.

Verification:
- Symbol-gone checks: no definitions of `_memo_output_for_freshness_check` or `_latest_memo_for_freshness_check` remain under `src/pflow/core/prompt_cache_analysis/`.
- `_PREDICTION_SKIPPED` no longer appears in `token_estimation.py`.
- Method-present/import-cheapness check: importing `pflow.core.prompt_cache_analysis` leaves `litellm` absent from `sys.modules`, and `AnalysisContext` has `latest_memo_for_node`.
- Focused regression for the full-suite failure: `1 passed`.
- Token-estimation tests: `47 passed`.
- Memo/stale/prediction analyzer selector: `14 passed, 172 deselected`.
- Task 159 harness: `80 passed, 7 drifted, 0 harness errors`; drifted case names match Phase 0 exactly.
- Full sandbox-safe pytest: `7106 passed, 1 skipped`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 225 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.
- `git diff --check`: passed.
- File shape:
  - `context.py`: `535` lines.
  - `token_estimation.py`: `689` lines.

Trust boundary for Phase F:
- Verified: memo freshness policy has one owner on `AnalysisContext`; stale and uncheckable mutations still flow through the same predicted-cache-key comparison; `token_estimation.py` keeps ctx-less legacy lookup behavior and exception swallowing where tests prove it is reachable.
- Assumed correct: keeping exception swallowing at the `token_estimation.py` call sites is the simplest boundary because context resolution already has its own caller-side logging, and centralizing all exception handling inside `latest_memo_for_node` would make its semantics broader than the old context helper.
- Unable to verify in Phase E: all-files pre-commit in this sandbox, due network setup failure under sandbox HOME and metadata-file permission errors under normal HOME.

## 2026-05-26 - Phase F Documentation And Final Verification

Phase completed: Phase F only. Plan C is complete through its final phase.

Implemented:
- Updated `src/pflow/core/prompt_cache_analysis/CLAUDE.md` so the module tree lists `stages/per_call_pipeline.py`, `row_builder.py` is described as row/IR primitives, pipeline step 4 points at `stages.per_call_pipeline._build_per_call_rows_and_warnings`, and the feature-location table distinguishes row construction from pipeline orchestration.
- Updated `src/pflow/core/prompt_cache_analysis/context.py`'s module docstring from three to four load-bearing methods and documented `AnalysisContext.latest_memo_for_node`.

Deviations and rationale:
- Used `.venv/bin/python` instead of `uv run python` for the final import-cheapness check. Rationale: the pflow sandbox-testing guidance and prior phases show `uv run` is unreliable in this sandbox; the assertion itself is identical.
- `HOME=/private/tmp/pflow-test-home .venv/bin/pre-commit run -a` failed before hooks ran because the sandbox HOME had no cached hook environment and network is blocked while installing hook dependencies from PyPI.
- `.venv/bin/pre-commit run -a` with the normal cached environment reached hooks but failed on sandbox permission errors in unrelated hidden `.codex` / `.agents` metadata during `end-of-file-fixer`. In that same run, ruff and ruff-format passed. Changed-file pre-commit passed for the files touched by Phases E/F and this log.

Subagent use:
- No subagents were used in Phase F. The phase was a tightly scoped documentation update plus verification; there was no disjoint mechanical implementation slice worth parallelizing.

Verification:
- Task 159 final harness: `80 passed, 7 drifted, 0 harness errors`.
- Drift-list diff between `/tmp/baseline-pre-polish.log` and `/tmp/baseline-post-polish.log`: empty diff; the same seven canonical cases drift.
- Full sandbox-safe pytest: `7106 passed, 1 skipped`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/mypy`: passed, `Success: no issues found in 225 source files`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/deptry src`: passed, no dependency issues.
- Private prompt-cache-analysis imports in tests: `58`, meeting the Plan C target of `<= 58`.
- Package import cheapness: importing `pflow.core.prompt_cache_analysis` leaves `litellm` absent from `sys.modules`.
- `git diff --check`: passed.
- Changed-file pre-commit passed for `src/pflow/core/prompt_cache_analysis/CLAUDE.md`, `src/pflow/core/prompt_cache_analysis/context.py`, `src/pflow/core/prompt_cache_analysis/token_estimation.py`, and this progress log.

Final trust boundary:
- Verified: Plan C's selected architectural polish is complete; the public/private renderer test leak count is at target; the per-call pipeline extraction is documented; memo freshness has one owner on `AnalysisContext`; the final baseline oracle has no new drift.
- Assumed correct: the known all-files pre-commit failures are sandbox/environment limitations, not repository regressions, because changed-file hooks, ruff, ruff-format, `git diff --check`, pytest, mypy, deptry, and the baseline harness all pass.
- Unable to verify: a truly clean `pre-commit run -a` in this sandbox, for the same network and hidden metadata permission reasons documented in earlier phases.
