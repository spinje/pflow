# Task 92 Implementation Progress Log

## 2026-03-16 — Planning and Research Phase

Started as "I want to start planning for removing the planning and repair feature." Searched existing tasks — found Task 92 (Replace Planner with Agent + MCP) was the closest match but scoped as replacement, not removal. No task existed for outright deletion.

### Architecture decision flow (important — captures the reasoning path):

**Discovery replacement options considered:**
- Option A: Plain functions — simplest, ~50-80 lines per function vs ~200-300 per node
- Option B: Service classes — classes with only static methods are just namespaced functions, no benefit
- Option C: Keep as PocketFlow nodes, relocate — keeps unused infrastructure (caching, exec_fallback, shared store)
- Option D (chosen): **Thin wrapper functions with typed dataclasses** — `WorkflowMatch` and `ComponentSelection` dataclasses with explicit fields, `discover_workflow()` and `discover_components()` plain functions

**Where to put discovery — evolved through discussion:**
1. Initially proposed `src/pflow/discovery/` — self-contained new module
2. User asked "do we currently have any similar LLM features?" → found only `smart_filter.py` in `core/`
3. User suggested "maybe all 3 belongs in registry?" → analyzed fit:
   - `smart_filter` + `discover_components` → natural registry fit
   - `discover_workflow` → operates on WorkflowManager, NOT registry. Doesn't fit.
4. User suggested "should we consider a workflow/ folder in core?" → discovered 5 existing `workflow_*` files in `core/` begging to be grouped
5. Final architecture: `core/workflow/` (discovery + existing workflow files) + `registry/` (component discovery + smart_filter + context builders)

**Key decisions made:**
1. **Two-phase approach**: Build replacements for active dependencies first, then delete everything.
2. **Keep discovery features** — `workflow discover` and `registry discover` are useful for MCP agents. Replace PocketFlow nodes with plain functions.
3. **Plain functions over PocketFlow nodes** — Discovery nodes were never composed in flows. Shared store ceremony added no value. Consumers become much simpler (no shared store setup/extraction).
4. **Where things live**: Component discovery → `registry/`, workflow discovery → `core/workflow/`, smart_filter → `registry/`, context builders → `registry/`.
5. **Drop Anthropic SDK** — Only planning used it directly. `llm-anthropic==0.23` natively supports `schema=` for structured output (verified by checking the installed plugin code). The monkey-patch (`install_anthropic_model`) was already dead code in CLI.
6. **Extract `core/workflow/` as separate pre-task** — 46 files + 53 patch() strings is too risky to mix with planning removal. The user suggested doing it as a "separate preparatory task BEFORE the planning removal" which was the right call.
7. **What to drop from discovery functions**: All `cache_planner` infrastructure (consumers never cache), `exec_fallback()`/`CriticalPlanningError` (consumers have own error handling), `_build_llm_kwargs()` multi-provider handling (llm library handles this via plugins), `requirements_result` from shared store (only available in full planner pipeline), `_adapt_prompt_to_context()` (only for cache block splitting).
8. **Prompts stay the same** — Same `.md` prompt files, same template variables, same LLM interaction. Only the scaffolding around them changed.

### Assumption verification (5 parallel subagents — user pushed for this):

The user asked me to "take a step back and think hard" about unverified assumptions before proceeding. This was the right call — several findings corrected the plan.

- `install_anthropic_model` was already dead code in CLI (defined but never called)
- `llm-anthropic==0.23` fully supports `schema=` for structured output
- Removing `anthropic>=0.75` from pyproject.toml doesn't uninstall it (transitive dep via llm-anthropic)
- `context_builder.py` has ZERO deps on rest of planning — clean extraction
- `build_nodes_context` + `build_workflows_context` share 2 helpers with `build_planning_context` (`_process_nodes`, `_get_workflow_manager`)
- No circular dependency risks with any planned moves
- `core/workflow/` extraction blast radius: ~46 unique files, 53 `patch()` string paths in tests
- **Correction**: `build_nodes_context()` and `build_workflows_context()` are ALSO needed (not just `build_planning_context()`) — the new discovery functions need them
- **Correction**: The 3 context builders share 2 private helpers — splitting across registry/ and core/workflow/ works because `_process_nodes` is only shared between the two going to registry/
- 4 non-planning test files import from planning (test_metadata_flow, test_workflow_manager_integration, test_settings_filtering, test_discovery_commands) — these need updating in Phase 1
- The `_install_anthropic_model_if_needed` function in cli/main.py was defined but NEVER CALLED — orphaned when planner was gated

### Comprehensive scratchpad docs created:
- `scratchpads/planning-removal/00-master-plan.md`
- `scratchpads/planning-removal/01-core-workflow-extraction.md`
- `scratchpads/planning-removal/02-phase1-relocate-dependencies.md`
- `scratchpads/planning-removal/03-phase2-deletion.md`

---

## 2026-03-16 — Pre-task: core/workflow/ Extraction (PR #121)

Executed by a separate agent using the `01-core-workflow-extraction.md` spec. Moved 6 files (`workflow_manager.py`, `workflow_save_service.py`, `workflow_validator.py`, `workflow_data_flow.py`, `workflow_status.py`, `skill_service.py`) into `core/workflow/` subdirectory. All 53 patch() strings updated. Merged as PR #121.

---

## 2026-03-16 — Phase 1: Relocate Dependencies

Executed by a separate agent using the `02-phase1-relocate-dependencies.md` spec. Verified all 10 steps completed correctly:

1. `parse_structured_response` → `core/llm_utils.py` ✅
2. `smart_filter.py` → `registry/smart_filter.py` ✅
3. Context builders → `registry/context_builder.py` ✅
4. `build_workflows_context` → `core/workflow/context.py` ✅
5. Prompt loader → `core/prompt_utils.py`, prompts moved ✅
6. `discover_workflow()` plain function created ✅
7. `discover_components()` plain function created ✅
8. `install_anthropic_model` removed, `anthropic>=0.75` dropped ✅
9. Tests rewritten for new discovery functions ✅
10. CLAUDE.md files updated ✅

Committed as `08a0081b` on `refactor/remove-planning-and-repair` branch. 39 files changed, +2,449/-465 lines.

### Phase 1 execution details

Approach: steps 1-2 first (quick wins), validated with `make test && make check`, then steps 3-7 (harder), then 8-10 (cleanup). Each group validated before proceeding.

**Steps 1-2** (`parse_structured_response` move + `smart_filter` move): Straightforward file moves + import updates. Single consumer each. Tests passed immediately. Validated the approach.

**Steps 3-4** (context builder extraction): The trickiest part. `planning/context_builder.py` is 1,392 lines with ~27 functions. Cherry-picked ~20 functions into `registry/context_builder.py`, dropped ~7 dead ones (`_load_saved_workflows`, `_load_single_workflow`, `_validate_workflow_fields`, `_format_template_variables`, `_format_single_parameter`, `_format_interface_item`, `_format_param_line`, `_extract_input_keys`). Key cleanup: removed `_get_workflow_manager()` singleton (callers pass `WorkflowManager` as parameter or create fresh instances), removed mock detection hack (`hasattr(_load_saved_workflows, "_mock_name")`). `build_workflows_context` went to `core/workflow/context.py` with its 5 helpers — clean split since `_process_nodes()` was only shared between the two functions going to `registry/`.

**Steps 5-7** (prompt utils + discovery functions): Created `core/prompt_utils.py` by adapting `planning/prompts/loader.py` — changed `load_prompt()` to accept a `Path` parameter instead of using `Path(__file__).parent`. Discovery functions collapsed the PocketFlow node lifecycle (prep/exec/post) into single functions. Dropped all caching, `_build_llm_kwargs()`, `_adapt_prompt_to_context()`, `exec_fallback()`. Used `model.prompt(text, schema=PydanticModel)` directly — the `llm` library handles provider differences via plugins.

**Step 8** (`install_anthropic_model` removal): Removed from `mcp_server/main.py` startup and deleted dead `_install_anthropic_model_if_needed()` from `cli/main.py`. Removed `anthropic>=0.75` from `pyproject.toml`, added `DEP003 = ["anthropic"]` to deptry config (transitive dep still imported by gated planning code).

**Step 9** (test rewrites): Discovery command tests (`test_discovery_commands.py`) fully rewritten — mocks changed from `WorkflowDiscoveryNode.run` / `ComponentBrowsingNode.run` (shared store manipulation) to `discover_workflow` / `discover_components` (return typed dataclasses). Used `unittest.mock.patch` on source modules since CLI uses lazy imports. 11 new tests written for discovery functions (6 for `discover_workflow`, 5 for `discover_components`).

**Integration test fix**: `test_workflow_manager_integration.py` had 3 patches of `pflow.planning.context_builder._get_workflow_manager` — all removed since the singleton was eliminated. The inner code was over-indented from `with patch(...)` removal — fixed indentation.

### Phase 1 code review and fixes

Two independent reviews evaluated (`scratchpads/code-review-staged-2026-03-16.md` and `scratchpads/code-review-staged-2026-03-16-2.md`). Evaluated 16+ findings total.

**Critical fix — formatter data shape mismatch (C1):**
`format_discovery_result()` expected `workflow["metadata"]["description"]` and `ir["flow"]`, but `WorkflowManager.load()` returns flat `workflow["description"]` and `ir["edges"]`. Description, version, and node flow were **silently omitted** from production output. Test fixtures used the old shape, masking the bug. Fixed `format_workflow_metadata()` to check flat keys first with legacy wrapper fallback. Fixed `format_workflow_flow()` to check `edges` then `flow`. Updated all test fixtures to use production data shapes.

- 💡 **Insight**: This bug existed because the formatter was written for the old planner's data shape, and the test fixtures matched the formatter's expectations rather than production data. An integration test exercising `discover_workflow()` → `format_discovery_result()` with real `WorkflowManager.load()` data would have caught this immediately.

**Other confirmed fixes:**
- Stale doctest imports in `registry/smart_filter.py` (lines 319, 350) — still referenced `pflow.core.smart_filter`
- Redundant `WorkflowManager()` instantiation in CLI and MCP `discover_workflows` — created two instances where one sufficed
- Stale CLAUDE.md references: `cli/CLAUDE.md` still said `pflow.planning.context_builder`, `tests/CLAUDE.md` still showed `_workflow_manager` singleton patch example
- Missing deprecation markers on `planning/context_builder.py` and `planning/utils/llm_helpers.py`
- Missing trailing newlines in copied prompt files
- Redundant truthiness check in `llm_utils.py` (`and expected_type` — always truthy)

**Additional improvements:**
- `WorkflowMatch` and `ComponentSelection` dataclasses made `frozen=True` — prevents accidental mutation of return values
- Normalized import style in `registry/` — `context_builder.py` used relative imports (`from ..core`), `discovery.py` used absolute (`from pflow.core`). Standardized on absolute.

**Disputed findings (not real issues):**
- C2 (repair_service stale import): Gated dead code, Phase 2 deletes entire file
- W-repair (cache_blocks breakage after Anthropic wrapper removal): Triple-gated dead code — CLI force-disables `auto_repair`, MCP hardcodes `enable_repair=False`, planner path unreachable
- W-wf-names (discover_components discards workflow_names): Deliberate documented decision per braindump — re-enabling workflow selection in discovery is a separate decision
- W3 (build_planning_context union return type): Pre-existing pattern, not a regression
- W5 (llm_utils swallows Pydantic validation failures): Verbatim copy from planning, pre-existing behavior

### Phase 1 naming cleanup

Post-review, `build_planning_context` was renamed to `build_component_context` throughout (function, helpers, docstrings). Similarly `planning_context` field on `ComponentSelection` became `component_context`. This better reflects the function's purpose now that it lives in `registry/` and serves component discovery, not planning.

### Manual testing

Verified all affected systems manually against real data:

| Test | Result | What it validates |
|------|--------|-------------------|
| `pflow registry describe shell` | Pass | `build_component_context` relocation works |
| `pflow registry describe http llm write-file` | Pass | Multi-node context building |
| Formatter with real `WorkflowManager.load()` data | Pass | C1 fix — Description, Version, Node Flow all display |
| MCP server startup (`pflow mcp serve`) | Pass | No crash without `install_anthropic_model` |
| `pflow workflow list` | Pass | Workflow management unaffected |
| `pflow workflow save` + `describe` | Pass | Save/load cycle works |

Discovery commands (`workflow discover`, `registry discover`) require LLM API key — covered by mocked unit tests only.

- 💡 **Insight**: Inputs didn't appear in formatter output because `WorkflowManager.load()` returns `ir` with only `nodes`/`edges` — inputs are parsed from the markdown `## Inputs` section but stored as workflow-level metadata, not inside the IR. The formatter's `format_workflow_inputs_outputs(ir)` correctly handles this when inputs ARE present in the IR dict. This is a pre-existing data flow issue, not introduced by our changes.

---

## 2026-03-16 — Phase 2: Delete Planning, Repair, and Gated Code

### Step 1-2: File deletions
- `git rm -rf src/pflow/planning/` — 32 files removed
- `git rm` repair files: `repair_service.py`, `workflow_diff.py`, `repair_save_handlers.py`
- `git rm -rf tests/test_planning/` — 68 test files removed
- `git rm` individual test files: `test_repair_service.py`, `test_auto_repair_flag.py`, `test_cache_planner_flag.py`, etc.

### Step 3: Gated code cleanup (3 parallel agents)

**Agent 1 — `workflow_execution.py`**: Rewrote from 642 to 83 lines. Removed all repair infrastructure (9 internal functions, repair imports, `enable_repair`/`repair_model`/`resume_state`/`original_request` parameters). Also updated callers: `cli/main.py` (removed repair params from execute_workflow call), `mcp_server/execution_service.py` (removed `enable_repair=False`). Deleted `test_loop_detection.py` and `test_checkpoint_resume.py`. Rewrote `test_workflow_execution.py`.

**Agent 2 — Small files**: Stubbed `generate_workflow_metadata()`, deleted `update_ir()`, removed `--generate-metadata` flag, cleaned `workflow_trace.py` diff import, deleted `PlannerError` class, emptied conftest files, removed `_is_fixable_error` TODO.

**Agent 3 — `cli/main.py`**: Largest cleanup (~654 lines removed). Removed PlannerError branch, `auto_repair` parameter threading through 4 functions, `_save_repaired_workflow()`, 13 planner-only dead code functions, 7 Click options, planner dispatch section. Down from ~3,978 to ~3,324 lines.

- 💡 **Insight**: Agent 3 took longest (~9 min) because cli/main.py is ~3,900 lines and the edits were deeply interdependent. Giving it exact line numbers and verified content was critical.

### Step 4: CLAUDE.md cleanup

Did this myself (not delegated) — I have the full context of what changed and why. Updated 15 files:
- Root `CLAUDE.md`, `cli/CLAUDE.md`, `core/CLAUDE.md`, `core/workflow/CLAUDE.md`
- `execution/CLAUDE.md`, `mcp_server/CLAUDE.md`, `mcp_server/services/CLAUDE.md`
- `runtime/CLAUDE.md`, `tests/CLAUDE.md`, `tests/test_cli/CLAUDE.md`
- `tests/shared/README.md`
- `.claude/agents/code-implementer.md`, `test-writer-fixer.md`, `pflow-codebase-searcher.md`
- Prompt frontmatter in `discovery.md` and `component_browsing.md`

- 💡 **Insight**: Should NOT have tried delegating CLAUDE.md updates to implementer agents — they had no context of what was removed or why. The user correctly stopped me and said "this is your job."

### Step 5: Code review findings

Two external reviews were provided. Evaluated 11 findings:

**Confirmed and fixed:**
1. `examples/runtime_feedback_demo.py` imported deleted module → deleted
2. `scripts/tools/test_prompt_accuracy.py` targeted removed trees → deleted
3. `repaired_workflow_ir` field on `ExecutionResult` → removed
4. `_is_fixable_error()` + `"fixable"` key → removed (method + 2 set sites)
5. `execution/CLAUDE.md` stale repair gotchas → cleaned
6. `analyze.py` repair event handling → removed (old traces not worth supporting)
7. Metrics planner fields + `is_planner` threading → removed from `metrics.py`, `instrumented_wrapper.py`, `workflow_trace.py`

**Disputed (not real issues):**
- Empty `test_integration/conftest.py` — standard practice
- `generate_workflow_metadata()` stub — clean API placeholder
- Dead code in `cli/rerun_display.py` — not found by subagent

Test fixes: 25 tests broke from metrics/is_planner removal. Fixed by test-writer-fixer agent — deleted 5 planner-only tests, updated 20 others.

### Step 6: Deep cleanup pass (separate agent)

A separate agent did a thorough repo-wide search for stale planner/repair references across all files (76 files touched). Key changes:

**Renames (semantic cleanup — all references consistently updated):**
- `CriticalPlanningError` → `CriticalDiscoveryError` (class in `core/exceptions.py` + 4 consumers in `cli/discovery_errors.py`)
- `build_planning_context` → `build_component_context` (function + all callers in `cli/registry.py`, `mcp_server/registry_service.py`, `registry/discovery.py` + tests)
- `planning_context` → `component_context` (field on `ComponentSelection` dataclass + all consumers)
- `_handle_invalid_planner_input` → `_handle_invalid_workflow_input` (function + caller in `cli/main.py`)
- `planner_llm_calls` → `seeded_llm_calls`, `planner_cache_chunks` → `cache_chunks` (internal parameter names in dead code path)

**Dead code removal (repair artifacts in surviving files):**
- `__modified_nodes__` / `repaired` tracking removed from: `display_manager.py`, `execution_state.py`, `success_formatter.py`, `error_formatter.py`, `instrumented_wrapper.py`, `cli/main.py`
- `__non_repairable_error__` flag removed from `instrumented_wrapper.py`
- `record_repair_attempt()` / `record_repair_llm_call()` removed from `workflow_trace.py`
- `show_repair_start()` / `show_repair_issue()` / `show_repair_result()` removed from `display_manager.py`
- `_is_modified` check removed from progress callback in `instrumented_wrapper.py`

**Comment/docstring updates (76 files total):**
- "trigger repair" → "workflow error handling can respond" in git/llm/mcp node comments
- "planner" → "discovery" or removed in docstrings across cli, runtime, mcp_server
- Architecture docs, scripts, and user-facing docs cleaned

**Stale test removed:**
- `test_oversized_workflow_input_shows_clear_size_limit_error` in `test_main.py` — skipped with reason "Gated pending Task 107". The test validated a 100KB size check in `_validate_and_join_workflow_input()`, which was deleted with the planner dispatch path. Natural language input now hits `_handle_invalid_workflow_input()` immediately — there's no size validation because there's no planner to send it to. The CLI flow is: multi-word input → `is_likely_workflow_name()` returns False (has spaces) → `_handle_invalid_workflow_input()` → "not a known workflow" error.

4 additional repair-related tests deleted: `test_repaired_nodes_must_be_marked`, `test_batch_line_includes_repaired_tag`, `test_repaired_node_unchanged`, `test_repaired_flag`.

### Final state

- `make test`: 4,068 passed, 0 skipped, 0 failures
- `make check`: all green (ruff, mypy, deptry)
- Zero `pflow.planning` references in `src/` or `tests/`
- Zero `repaired` / `__modified_nodes__` / `is_planner` references in production code
- Net deletion: ~40,000+ lines across all phases

---

## Key Learnings

### Subagent management

1. **Scratchpad planning docs were essential.** The 4-document plan (`00-master-plan.md` through `03-phase2-deletion.md`) with exact file paths, line numbers, and blast radius analysis made the multi-agent execution reliable.

2. **Verify assumptions with parallel subagents before planning.** Five parallel searchers caught critical facts (install_anthropic_model was dead code, llm-anthropic supports schema=, no circular deps) that changed the plan.

3. **Separate mechanical refactors from semantic changes.** The `core/workflow/` extraction (46 files, purely mechanical) was correctly isolated from the planning removal. Each was testable independently.

4. **Don't delegate context-heavy documentation to agents.** CLAUDE.md updates require understanding WHY things changed, not just WHAT files exist. The implementer agents had no context and would have done a poor job.

5. **`patch()` strings in tests are the silent killer.** Regular imports fail loudly. Patch strings silently mock nothing. Always grep for string-based paths after any module move.

6. **Code reviews caught real issues across both phases.** Phase 2: orphaned example file, dead `_is_fixable_error()`, `repaired_workflow_ir` field. Phase 1: formatter data shape mismatch (C1) — description, version, and node flow silently missing from production output. Both would have shipped without review.

7. **Give subagents exact, verified information — not guesses.** First attempt at Phase 2 agents was rejected by the user: "when using subagent make sure to use full context and clear instructions without ambiguity and isolated tasks." I was throwing vague "around line X" references instead of reading the files first and giving precise content. After reading the actual code, the second attempt succeeded.

8. **One focused task per agent.** The first rejected attempt crammed 10 file edits into one agent. The successful approach: one agent per logical unit (workflow_execution.py rewrite, small file cleanups, cli/main.py cleanup).

### Process

9. **User-driven decision points matter.** Key inflection points where the user changed the direction: (a) "should we consider a workflow/ folder in core?" — led to better architecture than my initial `discovery/` proposal. (b) "take a step back and think hard" — forced assumption verification that caught real issues. (c) "dont outsource this to implementer agents, this is your job" — CLAUDE.md updates require full context.

10. **Commit strategy: user reviews everything.** The user requested all changes be uncommitted for review before committing. We used `git reset HEAD~1` to pull a premature commit back to working directory. This allowed combining Phase 2 + docs cleanup + review fixes into a single reviewable diff.

11. **`__non_repairable_error__` shared store key** was also removed from `instrumented_wrapper.py` as part of the repair cleanup — it was the flag that told the repair system to skip repair for API errors. Without repair, the flag has no consumer.

12. **Test fixtures that match implementation instead of production data hide bugs.** The Phase 1 formatter tests used `{"metadata": {"description": ...}}` (matching what the formatter expected) instead of `{"description": ...}` (what `WorkflowManager.load()` actually returns). Tests passed but production output was broken. Manual testing with real saved workflows caught this.

13. **Evaluate code review findings critically.** Of 16+ findings across two reviews, 7 were confirmed, 5 were disputed (gated dead code, pre-existing patterns, deliberate decisions). Blindly applying all findings would have touched gated code designated for Phase 2 deletion and contradicted documented decisions from the braindump.

14. **Manual testing after relocation catches what unit tests miss.** Running `pflow registry describe shell` and formatting a real `WorkflowManager.load()` dict through the formatter validated the full integration path. The formatter bug (C1) was invisible to unit tests because fixtures didn't match production data.

---

## 2026-03-16 — Post-Phase 2 Code Review and Cleanup

Ran `/code-review --staged` against the full Phase 2 diff (235 files, ~43,600 lines deleted, ~2,400 added). Review written to `scratchpads/code-review-planning-removal.md`. Found 2 critical, 4 warnings, 4 suggestions. User evaluated all findings: 4 confirmed as-is, 2 confirmed with different fix, 1 disputed (S2 — `generate_workflow_metadata()` stub deliberately kept as API placeholder), 4 suggestions accepted.

### Findings and fixes

**[C1+C2] Dead code: `_auto_save_workflow()` and `_prompt_workflow_save()` in `cli/main.py`**

These two functions (~120 lines) were permanent dead code — the planner that called them was deleted, and they would crash if invoked (passing IR dicts to `WorkflowManager.save()` which expects markdown content, confirmed by `type: ignore[arg-type]`). Additionally, `tests/test_cli/test_workflow_save_integration.py` (not in the staged diff) had two tests that imported `_prompt_workflow_save` directly.

Fix: Deleted both functions from `main.py`. Ruff auto-removed the now-unused `WorkflowExistsError, WorkflowValidationError` import. Rewrote the two tests in `test_workflow_save_integration.py` — replaced them with a simpler test that exercises `WorkflowManager` directly (the actual integration point). Ruff auto-removed unused `from unittest.mock import patch` import. Updated the file's FIX HISTORY header.

- 💡 **Insight**: These functions survived Phase 2 because they were marked "GATED: Planner is disabled" — the Phase 2 agent treated "gated" as "don't touch" rather than "delete." The code review caught them by searching for callers and finding zero.

**[W1] "Planning failed" error messages in `cli/main.py`**

`_format_compilation_error_text()` displayed "Planning failed: {e}" for `CompilerCompilationError` at two locations with a comment "Keep as 'Planning failed' for consistency with existing tests and UX." Since the planning system is gone, this is confusing UX.

Fix: Changed both to "Compilation failed: {e}", removed the "keep for consistency" comment. Updated `test_validation_before_execution.py` — the test asserted `"Planning failed" not in combined_output` (negative assertion), so it still passes, but updated the comment and assertion string to match the new wording.

**[W2] Stale CLAUDE.md references to removed classes**

Four CLAUDE.md files still referenced deleted entities:
- `core/CLAUDE.md`: `CriticalPlanningError` (renamed to `CriticalDiscoveryError` in Phase 2 step 6), `PlannerError` (deleted in Phase 2 step 3)
- `runtime/CLAUDE.md`: `__non_repairable_error__` shared store key (removed), "triggers repair" / "repairable" / "non-repairable" terminology throughout (6 locations), `validate=False` breaks "repair" (repair doesn't exist)

Fix: Updated `core/CLAUDE.md` — `CriticalPlanningError` → `CriticalDiscoveryError`, removed `PlannerError` from specialized error class list. Updated `runtime/CLAUDE.md` — removed `__non_repairable_error__` from shared store key docs, rewrote error categorization section to use neutral "validation errors" / "resource errors" terminology, removed "triggers repair" from template error docs, changed "breaks repair" to "bypasses safety checks."

- 💡 **Insight**: Phase 2 step 4 updated 15 CLAUDE.md files but missed these specific references because the search focused on `planning` / `planner` keywords. The repair terminology (`repairable`, `non-repairable`, `triggers repair`) didn't match those keywords but was equally stale.

**[W3] Empty `TestPlannerIntegration` placeholder class**

`tests/test_integration/test_metrics_integration.py` had an empty class with docstring: "Tests for planner metrics exist in test_planning/ where the planner can be tested directly." The `test_planning/` directory was deleted in Phase 2.

Fix: Deleted the class.

**[W4] Stale test class name `TestBuildExecutionStepsCacheAndRepair`**

`tests/test_execution/test_execution_state.py` — class name and docstring referenced "repair" but the repair test was removed; only the cache test remained.

Fix: Renamed to `TestBuildExecutionStepsCache`, updated docstring.

**[S1] Dead `context="resume"` branch in `display_manager.py`**

`show_execution_start()` accepted a `context` parameter defaulting to `""`. The `context == "resume"` branch was only used by the checkpoint-resume feature (deleted). Single production caller passes no context argument.

Fix: Removed the `context` parameter and the resume branch entirely. Verified no callers pass the argument (only one call site at `cli/main.py:2036`, positional `node_count` only).

**[S3] "REPAIRABLE"/"NOT REPAIRABLE" comments in `instrumented_wrapper.py`**

`_categorize_by_error_code()` had comments labeling validation codes as "REPAIRABLE" and resource codes as "NOT REPAIRABLE" — repair terminology for a function that now only serves API warning detection.

Fix: Changed to "Validation error codes" and "Resource error codes."

**[S4] Architecture docs said "legacy" instead of "removed"**

`architecture/architecture.md` described the natural language path as "Legacy" in 4 places. Since the planner is now deleted (not just deprecated), "legacy" is misleading.

Fix: Changed to "Removed" with past-tense descriptions. Updated the workflow resolution diagram to show "Error with guidance" instead of "Legacy workflow-building path."

### Validation

- All 75 affected tests pass (1.0s)
- `ruff check` clean (auto-fixed 3 unused imports)
- `mypy` clean on all modified source files

### Key learning

15. **"Gated" code can survive deletion passes.** The Phase 2 agent interpreted "GATED: Planner is disabled" comments as "leave alone" rather than "this IS the dead code to remove." A post-deletion code review is necessary to catch these stragglers — the review specifically searched for functions with zero callers, which is how C1 was found.

16. **Repair terminology outlives repair code.** After deleting the repair system, "repairable" / "non-repairable" / "triggers repair" lingered in comments, CLAUDE.md docs, and error messages because these terms weren't in the keyword search patterns used during cleanup. A second pass focused on terminology (not just imports and function references) was needed.

---

## 2026-03-16 — Third Code Review: Runtime Bug Fixes

A third review (`scratchpads/code-review-staged-20260316.md`) found two runtime bugs in the error reporting path. Unlike previous review findings (dead code, stale docs), these were **behavioral bugs** affecting user-visible error messages.

### C1: API warnings lose actionable message

**The bug**: When `InstrumentedNodeWrapper` detects an API warning (e.g., GraphQL 200 with errors, Slack `channel_not_found`), it stores the actionable message in `shared["__warnings__"]` and returns `"error"` to stop the workflow. But `executor_service._build_error_list()` only looks in `shared["error"]` and `shared[node_id]["error"]` — it never checks `__warnings__`. The user sees `"Workflow failed with action: error"` instead of `"API error: Repository not found"`.

**Was this introduced by our refactor?** No — it was pre-existing. The old repair system had `_handle_non_repairable_error()` which surfaced `__warnings__` as errors, but that function was inside the repair loop. Since `enable_repair=False` was always set, the function was never called. The API warning messages were already lost before our refactor.

**Why fix it now?** The user said "why not fix now?" — we're already in the code, we understand the issue, and it's a small fix. Correct.

**Fix**: Added 8 lines to `execute_workflow()` in `workflow_execution.py` — after failed execution, iterate `__warnings__` from `shared_after` and append them as error entries with `source: "api"`, `category: "api_warning"`.

### C2: MCP `"error": null` formatted as the string `"None"`

**The bug**: MCP responses like `{"successful": true, "error": null, "data": {"ok": false, "error": "channel_not_found"}}` have `"error": null` at the top level. `_extract_node_level_error()` checks `"error" in node_output` (truthy — the key exists) then returns `str(node_output["error"])` which is `str(None)` = `"None"`. Same issue in `_extract_error_from_mcp_result()` where parsed JSON has `"error": null`.

**Fix**: Changed both checks from `"error" in dict` to `dict.get("error")` — falsy values (None, empty string, 0) are skipped. Ruff auto-simplified the first one during linting.

### W3: Docs still promise natural language mode

The CLI reference docs (`docs/reference/cli/index.mdx`) had an accordion titled "Natural language mode (experimental)" with an example `pflow "read data.txt and summarize the content"`. This feature was removed — running that command now shows "not a known workflow or command."

**Fix**: Replaced the accordion with an `<Info>` callout explaining there's no built-in natural language mode and that agents build workflows via MCP tools or CLI primitives.

### W4: Planner-era loose test assertions (not fixed)

Two tests in `test_main.py` have comments like "Due to Task 22 implementation bug, parameters with file workflows go through planner" and overly loose assertions (`assert "param1" in result.output or "value1" in result.output or "planner" in result.output.lower()`). These are pre-existing loose assertions — they pass and aren't wrong, just not tight. Out of scope for this refactor.

### Key learning

17. **Pre-existing bugs become your bugs when you touch the seam.** The API warning surfacing was broken before our refactor, but we removed the (dead) code that would have fixed it. A reviewer looking at the execution path after our changes correctly identified that the path now has no way to surface `__warnings__`. Even though we didn't break it, fixing it during this refactor is the right call — we own the execution path now.

18. **Falsy-aware dict checks matter for API data.** `"error" in dict` is almost always wrong for API response parsing — APIs frequently include `"error": null` to indicate no error. Always use `dict.get("error")` to skip falsy values.

---

## 2026-03-16 — High-Value Regression Tests

After the third review found bugs in the error formatting path, I realized existing tests verified API warning *detection* (InstrumentedNodeWrapper level) but NOT that the actionable message survived through *formatting* (executor_service level). This gap is exactly where the bugs were — detection worked, formatting lost the message.

Added 3 tests to `tests/test_execution/test_api_warning_system.py::TestErrorFormattingSurfacesWarnings`:

1. **`test_api_warning_message_reaches_error_list`** — GraphQL 200-with-errors scenario. `__warnings__` populated with "API error: Repository not found". Verifies `_build_error_list()` returns that message, not the generic "Workflow failed with action: error". Protects C1 fix.

2. **`test_mcp_null_error_with_nested_data_error`** — Slack MCP scenario. `{"error": null, "data": {"error": "channel_not_found"}}`. Verifies `_build_error_list()` returns "channel_not_found", not "None". Protects C2 fix (both the null skip and the `data.error` unwrap).

3. **`test_api_warning_takes_priority_over_node_error`** — Both `__warnings__` and node-level error exist for the same node. Verifies the warning wins (it's more actionable). Protects the priority ordering in `_extract_error_info`.

These test at the `WorkflowExecutorService._build_error_list()` level — the exact integration point that was broken. They use the same payload shapes the reviewer used to reproduce the bugs.

### Key learning

19. **Test at the integration seam, not just the unit.** The API warning detection tests at the InstrumentedNodeWrapper level all passed — the bug was in how executor_service consumed the detection results. Writing tests at the boundary between producer (detection) and consumer (formatting) catches bugs that unit tests on either side miss.
