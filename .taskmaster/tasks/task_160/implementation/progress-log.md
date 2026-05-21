# Task 160 Implementation Progress

## 2026-05-21 - Phase 1 complete, awaiting review

Scope completed:
- Renamed the package from `src/pflow/core/cache_analysis` to `src/pflow/core/prompt_cache_analysis`.
- Updated production imports, tests, renderer guards, and relevant local documentation/comments to the new package path.
- Extracted public report data structures and small projection helpers into `src/pflow/core/prompt_cache_analysis/types.py`.
- Rewired package exports so external/public consumers import report types from `.types` or package-level exports, while `analyze.py` keeps the orchestration entry point.

Verification:
- Baseline before edits: full non-e2e pytest passed with `7102 passed, 1 skipped`.
- Baseline before edits: `mypy` and `deptry` passed; full `pre-commit run -a` was blocked by sandbox permission errors reading `.codex/agents/*.toml` and `.agents/skills/pflow-sandbox-testing/agents/openai.yaml`.
- Post-edit focused cache-analysis slice passed with `632 passed`.
- Post-edit full non-e2e pytest passed with `7102 passed, 1 skipped`.
- Post-edit quality checks passed: `ruff check src tests`, `ruff format --check src tests`, `mypy`, and `deptry src`.
- Task 159 baseline harness was run before and after. The usable pre-edit run with venv `uv` on `PATH` was `79 passed, 8 drifted`. The post-edit run reported `0 passed, 87 drifted` because committed expected stderr still contains dependency-fetch failure output for `hatchling`, while this environment successfully executed pflow and produced real stdout/stderr. I treated that post-edit result as an invalid oracle for this phase and restored the trace fixture path churn it generated.

Deviations from plan:
- Used filesystem `mv` instead of `git mv` because project memory says not to stage changes unless explicitly instructed. This preserved the same file move in the worktree without mutating the index.
- Moved `_provider_min_state` and `_projection_source_confidence` into `types.py` along with `PerCallRow`, because `PerCallRow.__post_init__` depends on them. Leaving them in `analyze.py` would make the type module depend on the orchestration module or fail at runtime. This keeps the final dependency direction simpler.

Key learnings:
- `PerCallRow` is not passive data; its normalization bridge owns provider-min and projection-confidence behavior, so extracting it requires extracting those helpers too.
- AST-based mechanical extraction does not include decorator lines in `node.lineno`; dataclass decorators had to be preserved explicitly.
- Broad path replacement can corrupt task history if `.taskmaster` is included. I restored accidental task-file edits and limited the final source/test rename to implementation-relevant paths.

Trust boundary:
- Verified: tests and quality checks listed above, no old `pflow.core.cache_analysis` imports remain in `src`, `tests`, or `pyproject.toml`.
- Assumed correct: keeping helper functions importable from `types.py` is acceptable because they are report-shape helpers, not orchestration.
- Unable to verify: Task 159 golden harness behavior after the refactor, because the committed expected outputs in this checkout are stale relative to a successful local execution.

## 2026-05-21 - Phase 2 complete, awaiting review

Scope completed:
- Added `src/pflow/core/prompt_cache_analysis/trace_loading.py` and moved trace loading, trace listing, trace scope resolution, trace execution indexing, trace LLM aggregation, trace-warning rehydration, and default memo-cache construction out of `analyze.py`.
- Updated package exports, CLI `--list-traces` import, and direct tests to import trace-specific helpers from `.trace_loading`.
- Kept `analyze.py` as the orchestrator by importing trace infrastructure from `.trace_loading`; no trace helper imports back from `analyze.py`.

Verification:
- Focused trace smoke: `7 passed`.
- Cache-analysis slice: `787 passed`.
- Full sandbox-compatible pytest initially hit Homebrew `uv` subprocess panics in 4 tests; rerunning the identical checkpoint outside the sandbox passed with `7142 passed, 1 skipped`.
- Quality checks passed: `ruff check src tests`, `ruff format --check src tests`, `mypy src`, and `deptry src`.
- Import sanity passed for package-level `analyze`, `list_traces_for_workflow`, renderers, summarizer, and `_build_trace_execution_index`.
- Additional before/after verification against an archived `HEAD` copy passed: normalized explicit-trace `analyze()` JSON output diffed clean, and normalized `list_traces_for_workflow()` output diffed clean.

Deviations from plan:
- Moved `_resolve_trace_scope` and related scope helpers in Phase 2 even though Step 2.1 only names trace I/O/indexing explicitly. The plan's later cleanup table assigns `_resolve_trace_scope` to `trace_loading`, and leaving it in `analyze.py` would preserve test dependence on trace internals inside the orchestrator.
- Moved `_is_llm_node` with trace loading because `_resolve_current_workflow_model_set` depends on it; importing it from `analyze.py` would create the exact reverse edge this phase is meant to avoid.
- Made the `TemplateResolver` dependency inside `_resolve_ir_static_model_for_node` lazy while moving it, matching the plan's lazy-import hygiene item and avoiding a new module-scope runtime import in `trace_loading.py`.

Key learnings:
- Trace listing is not just file I/O; it depends on static model comparison across nested workflows, so `trace_loading.py` necessarily has a one-way dependency on the cross-workflow walker.
- The trace execution index is the producer boundary for per-call trace token normalization. Keeping aggregation beside trace walking makes that contract easier to find and prevents row-building code from owning trace telemetry semantics.

Trust boundary:
- Verified: no remaining direct imports of `list_traces_for_workflow`, `_resolve_trace_scope`, `_build_trace_execution_index`, or `_resolve_current_workflow_model_set` from `.analyze` in `src` or `tests`.
- Assumed correct: moving `_is_llm_node` into `trace_loading.py` is acceptable until Phase 5 creates a better home for shared IR helpers; this avoids duplication and import cycles now.
- Unable to verify: Task 159 golden harness remains unusable as a phase oracle for the stale-expected-output reason documented in Phase 1.

## 2026-05-21 - Phase 3 complete, awaiting review

Scope completed:
- Moved the five renderer modules into `src/pflow/core/prompt_cache_analysis/rendering/`: `text.py`, `json.py`, `views.py`, `summarize.py`, and `traces_list.py`.
- Added `rendering/__init__.py` with the planned public re-exports for `render_json`, `render_text`, `summarize`, and `summarize_from_analysis`; trace-list renderers remain direct imports from `rendering.traces_list`.
- Updated package exports, CLI trace-list imports, tests, and internal relative imports to the new rendering paths.

Verification:
- Import sanity passed for package-level analyzer/render/summarize/list-trace exports plus direct `rendering.traces_list` and `rendering.views` imports.
- Focused renderer/analyzer tests passed: `548 passed`.
- Cache-analysis CLI/MCP/core slice passed: `798 passed`.
- Sandbox near-full pytest hit 4 Homebrew `uv` subprocess panics; the same command rerun outside the sandbox passed with `7142 passed, 1 skipped`.
- Quality checks passed: `ruff check src tests`, `ruff format --check src tests`, `mypy src`, and `deptry src`. The first incremental mypy run had stale cache state for the deleted root `render_json.py`; `mypy --no-incremental src` passed and refreshed the cache, then the normal `mypy src` run passed.

Deviations from plan:
- Made `analyze.py` import `per_call_row_has_real_data` lazily inside `analyze()` instead of at module scope. Reason: importing `rendering.views` at module import time executes `rendering/__init__.py`, which re-exports `summarize`; `summarize.py` imports `analyze`, creating a partial-initialization cycle. The lazy import keeps the final public rendering exports and avoids a new cycle.
- Used the `pflow-sandbox-testing` command style instead of literal `make test && make check`, because the documented sandbox guidance says `uv`/`make` can panic before Python starts here. This is a verification substitution, not a skipped gate: pytest, ruff, mypy, and deptry all ran.
- Did not spawn code-implementer subagents for this phase. The write scope was one tightly coupled module move plus import rewiring; splitting it would create overlapping edits in the same import surfaces without meaningful parallelism.

Key learnings:
- Moving `views.py` under a package with public re-exports changes import-order behavior even though the code body is unchanged; package `__init__` execution is an integration point that needed explicit verification.
- The renderer package boundary is now clean for consumers: public render functions come from `prompt_cache_analysis` or `prompt_cache_analysis.rendering`, while trace-list rendering stays intentionally narrower.

Trust boundary:
- Verified: no old direct root renderer module import paths remain in `src` or `tests`; only valid local imports inside `rendering/` remain.
- Assumed correct: leaving renderer-related doc/comment references such as `render_text.py` and `view_helpers.py` for Phase 6 documentation cleanup is acceptable because Phase 3's plan scope is code/test imports, not docs.
- Unable to verify: Task 159 golden harness remains unusable as a phase oracle for the stale-expected-output reason documented in Phase 1.

## 2026-05-21 - Phase 4 complete, awaiting review

Scope completed:
- Added `src/pflow/core/prompt_cache_analysis/stages/` with docstring-only `__init__.py`.
- Extracted summary aggregation into `stages/summary.py`, including confidence aggregation, trace-coverage classification, trace-dependent warning filtering, cost deltas, run-command formatting, and the Gemini note.
- Extracted discrepancy prediction/diagnosis into `stages/discrepancy/predict.py`, `stages/discrepancy/diagnose.py`, and a narrow subpackage `__init__.py` re-export. Runtime/planner imports remain lazy in `predict.py`.
- Extracted cross-workflow analytical findings into `stages/cross_workflow.py`.
- Updated private tests that directly exercised moved helpers to import the new stage modules.

Verification:
- Focused analyzer/per-ID/renderer tests passed: `532 passed`.
- Core cache-analysis suite passed: `756 passed`.
- CLI/MCP cache-analysis slice passed: `801 passed`.
- `test_sub_workflow_resolver.py` passed after retargeting moved helper imports: `15 passed`.
- Sandbox-compatible near-full pytest passed with uv-subprocess panic cases excluded: `7120 passed, 19 skipped`.
- Quality checks passed: `ruff check src tests`, `ruff format --check src tests`, `mypy src`, and `deptry src`.

Deviations from plan:
- Kept the Phase 4 cross-workflow back-edge to `analyze.py` as a module-level temporary import, but expanded it beyond the three helpers named in the plan to include `_total_observed_invocations`. Reason: row-level cross-workflow projection infrastructure remains in `analyze.py` until Phase 5 and still shares the same candidate helpers. Duplicating those helpers would create behavior drift; importing them keeps one implementation until their final homes exist.
- Imported `_build_cross_workflow_findings` lazily inside `analyze()` instead of at module scope. Reason: `stages/cross_workflow.py` temporarily imports helpers from `analyze.py`; a module-scope orchestrator import would create an import-time cycle before those helpers are defined.
- Updated test monkeypatch targets for moved private helpers instead of adding compatibility shims to `analyze.py`. Reason: the task explicitly rejects shims, and tests should follow the new module ownership.
- Did not use code-implementer subagents. Reason: Phase 4 is a single-file extraction with overlapping edits to `analyze.py` import/call boundaries; parallel workers would have conflicting write scopes and no clean integration boundary.
- Did not rerun the Task 159 golden harness. Reason: previous phase logs establish that the committed expected outputs in this checkout are stale relative to successful local execution, making the harness an invalid oracle here. I used focused behavioral tests plus the broad sandbox-compatible pytest run instead.

Key learnings:
- `summary.py` required `..cost_estimation` lazy imports after moving one package level deeper; a straight textual move left `.cost_estimation` pointing at the wrong package.
- Several tests intentionally monkeypatch private helper modules. Moving stage ownership means those tests must patch the stage module that now owns the behavior, especially discrepancy prediction and cross-workflow threshold helpers.
- `stages/cross_workflow.py` cannot be fully cycle-free until Phase 5 moves shared IR helpers and pricing/suggestion helpers out of `analyze.py`; the current back-edge is explicit and temporary.

Trust boundary:
- Verified: extracted modules import cleanly; all verification commands listed above pass; `TemplateResolver` use in extracted cross-workflow and prediction stages is lazy.
- Assumed correct: keeping the temporary cross-workflow back-edge through Phase 4 is acceptable because Phase 5 is explicitly responsible for moving those shared helpers to their final homes.
- Unable to verify: literal `make test && make check` and the Task 159 golden harness, due the documented sandbox `uv` panics and stale golden expected outputs.
