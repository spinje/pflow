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
