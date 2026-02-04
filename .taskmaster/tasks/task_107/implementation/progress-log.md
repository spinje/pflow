# Task 107: Markdown Workflow Format — Progress Log

## Phase 0.1 — Entry 1: Move PyYAML to main dependencies

Attempting: Add PyYAML>=6.0.0 to main dependencies in pyproject.toml and run uv lock.

Result:
- ✅ Added `PyYAML>=6.0.0` to `[project] dependencies`
- ✅ `uv lock` resolved successfully
- ✅ Added PyYAML to deptry DEP002 ignore list (not yet imported in production code)

Files modified: `pyproject.toml`, `uv.lock`
Status: Phase 0.1 complete.

## Phase 0.2 — Entry 2: Gate planner and repair systems

Attempting: Add if-guards at all planner/repair entry points and skip all related tests.

Result:
- ✅ Gated `_execute_with_planner()` call in cli/main.py:3912-3918 — replaced with user-facing message
- ✅ Gated `auto_repair` in `_initialize_context()` — forces False with warning if flag used
- ✅ Gated `save_repaired_workflow()` in repair_save_handlers.py — early return with warning
- ✅ Gated `_generate_metadata_if_requested()` in cli/commands/workflow.py — returns None with warning
- ✅ Gated `generate_metadata` in mcp_server/tools/execution_tools.py — forced to False
- ✅ Gated `_load_single_workflow()` in planning/context_builder.py — returns None with warning
- ✅ Gated all test_planning/ tests via autouse fixture in conftest.py
- ✅ Gated test_repair_save_handlers.py, test_auto_repair_flag.py, test_repaired_workflow_save.py, test_cache_planner_flag.py via pytestmark
- ✅ Gated test_context_builder_integration.py, test_context_builder_performance.py via pytestmark
- ✅ Updated test_workflow_resolution.py::test_natural_language_fallback to expect gated behavior
- ✅ Skipped test_main.py::test_oversized_workflow_input (planner path unreachable)
- ✅ Skipped test_planner_input_validation.py::test_quoted_prompt_attempts_planner
- ✅ Fixed mypy unused-ignore in context_builder.py (unreachable code after gate)
- ✅ Fixed ruff E402 linting (pytestmark placement after all imports)
- ✅ `make test`: 3552 passed, 507 skipped
- ✅ `make check`: all checks pass

Files modified:
- `src/pflow/cli/main.py`
- `src/pflow/cli/repair_save_handlers.py`
- `src/pflow/cli/commands/workflow.py`
- `src/pflow/mcp_server/tools/execution_tools.py`
- `src/pflow/planning/context_builder.py`
- `tests/test_planning/conftest.py`
- `tests/test_cli/test_repair_save_handlers.py`
- `tests/test_cli/test_auto_repair_flag.py`
- `tests/test_cli/test_repaired_workflow_save.py`
- `tests/test_cli/test_cache_planner_flag.py`
- `tests/test_cli/test_planner_input_validation.py`
- `tests/test_cli/test_workflow_resolution.py`
- `tests/test_cli/test_main.py`
- `tests/test_integration/test_context_builder_integration.py`
- `tests/test_integration/test_context_builder_performance.py`

Status: Fork F0 complete (Phase 0.1 + 0.2). Next: launch fork F0b (parser-core).

## Fork F0b — Entry 3: Parser core (Phase 0.3 + 1.1 + 1.2)

Attempting: Launch Fork F0b to build test utility, markdown parser, and parser tests.

Result:
- ✅ Fork completed successfully (70 tests, 4 real-world round-trip verifications)
- ✅ Created `tests/shared/markdown_utils.py` — ir_to_markdown utility
- ✅ Created `src/pflow/core/markdown_parser.py` — state machine parser (~350 lines)
- ✅ Created `tests/test_core/test_markdown_parser.py` — 70 tests across 15 categories
- ✅ Round-trip verified: minimal, template-variables, webpage-to-markdown, generate-changelog (17 nodes)
- ✅ `make test`: 3622 passed, 507 skipped (70 new parser tests included)
- ✅ `make check`: all pass (ruff, mypy, deptry clean)

Fork progress log: `progress-log-0b-parser-core.md`
Status: Fork F0b complete. Next: launch Phase 2 parallel forks (F1, F2, F5, F6).

## Phase 2 Parallel Forks — Entry 4: F1, F2, F5, F6 (completed in previous session)

Previous session launched F1, F2, F5, F6 in parallel. Session was corrupted before the main agent could log results. Reviewed all fork progress logs to reconstruct state.

Result:
- ✅ F1 (cli-integration) complete — `progress-log-f1-cli-integration.md`
  - `cli/main.py`: 9 integration points updated (path detection, loading, error display, registry lookup, etc.)
  - `cli/commands/workflow.py`: save command updated (removed --description, markdown parsing, content-based save)
  - Note: Pre-existing ruff F841 in gated planner save functions (lines 1204, 1275). `_save_with_overwrite_check` passes markdown_content with `type: ignore` — F3 will fix.
- ✅ F2 (workflow-manager) complete — `progress-log-f2-workflow-manager.md`
  - `workflow_manager.py`: complete rewrite for .pflow.md + frontmatter
  - All 6 `rich_metadata` callers updated to flat metadata access (G9)
  - Note: `test_executor_service.py` has 13 `rich_metadata` references — NOT in F2 scope, needs Phase 3 update.
- ✅ F5 (runtime-executor) complete — `progress-log-f5-runtime-executor.md`
  - `workflow_executor.py`: `_load_workflow_file()` uses `parse_markdown()` instead of `json.load()`
- ✅ F6 (errors-warnings) complete — `progress-log-f6-errors-warnings.md`
  - `ir_schema.py`: JSON examples replaced with markdown syntax
  - `workflow_validator.py`: Layer 7 removed (JSON anti-pattern), replaced with unknown param warning layer (9 tests)

Post-fork verification (`make test` / `make check`):
- `make test`: 3364 passed, 230 failed, 507 skipped, 7 errors — failures expected (tests still write JSON)
- `make check`: ruff passes, mypy has 3 errors in `workflow_save_service.py` (old save() signature — F3's responsibility)

Files modified (combined across F1, F2, F5, F6):
- `src/pflow/cli/main.py`
- `src/pflow/cli/commands/workflow.py`
- `src/pflow/core/workflow_manager.py`
- `src/pflow/core/ir_schema.py`
- `src/pflow/core/workflow_validator.py`
- `src/pflow/runtime/workflow_executor.py`
- `src/pflow/execution/formatters/workflow_describe_formatter.py`
- `src/pflow/execution/formatters/discovery_formatter.py`
- `src/pflow/execution/formatters/history_formatter.py`
- `src/pflow/planning/context_builder.py`
- `tests/test_core/test_ir_schema.py`
- `tests/test_core/test_ir_schema_output_suggestions.py`
- `tests/test_core/test_json_string_template_validation.py`
- `tests/test_execution/formatters/test_history_formatter.py`

Status: F1, F2, F5, F6 all complete. Next: launch F3 (save-service) and F4 (mcp-integration) in parallel.

## F3 + F4 — Entry 5: Save service + MCP integration

Launched F3 (save-service) and F4 (mcp-integration) in parallel.

Result:
- ✅ F3 (save-service) complete — `progress-log-f3-save-service.md`
  - `workflow_save_service.py`: `_load_from_file()` uses parse_markdown(), `save_workflow_with_options()` signature changed to `(name, markdown_content, *, force, metadata)`
  - mypy clean, ruff clean
- ✅ F4 (mcp-integration) complete — `progress-log-f4-mcp-integration.md`
  - `resolver.py`: markdown detection per D12, 3-tuple preserved (G2)
  - `execution_tools.py`: removed `description`/`generate_metadata` params from `workflow_save` tool
  - `execution_service.py`: save flow restructured (G8) — parses once, uses IR for validation/display, preserves original markdown content for save. Removed dead code (`_load_and_validate_workflow_for_save`, `_generate_metadata_if_requested`).
  - 💡 F4 did NOT use `resolve_workflow()` for the save path — it does its own content detection because `resolve_workflow()` discards original content (only returns IR). This is correct per the plan.
- ✅ Fixed F1→F3 caller TODO in `cli/commands/workflow.py:331` — changed `workflow_ir=markdown_content` to `markdown_content=markdown_content`, removed `description=""` arg and `type: ignore` comment
- ✅ Fixed ruff C901 in `resolver.py` — extracted `_resolve_by_name()` helper to reduce complexity from 12 to under 10

Post-fork verification:
- `make check`: all pass (ruff, mypy, deptry clean)
- `make test`: 3350 passed, 251 failed, 507 skipped, 7 errors — all failures are Phase 3 scope (tests still write JSON)

Files modified (combined across F3, F4, + trivial fixes):
- `src/pflow/core/workflow_save_service.py`
- `src/pflow/mcp_server/utils/resolver.py`
- `src/pflow/mcp_server/tools/execution_tools.py`
- `src/pflow/mcp_server/services/execution_service.py`
- `src/pflow/cli/commands/workflow.py` (trivial fix — keyword rename)

Status: F3 + F4 complete. All Phase 2 coding forks done. Next: smoke test gate (Phase 2.9).

## Phase 2.9 — Entry 6: Smoke test gate

Attempted: Full workflow lifecycle verification end-to-end using a hand-crafted `smoke-test.pflow.md`.

### Bug found: missing `normalize_ir()` on saved workflow load path

When executing a saved workflow (`pflow smoke-test`), validation failed with `'ir_version' is a required property`. Root cause: `_try_load_workflow_from_registry()` in `cli/main.py` calls `wm.load_ir()` but never calls `normalize_ir()` on the result. The file loading path (`_try_load_workflow_from_file`) does call `normalize_ir()` at line 184, but the saved workflow path skipped it.

**Fix**: Added `normalize_ir(ir)` calls inside `_try_load_workflow_from_registry()` for both the direct name match and the `.pflow.md` extension-stripped match. This was a pre-existing latent bug — in JSON mode, the metadata wrapper always included `ir_version`, so it was never triggered. With markdown, the parser correctly omits `ir_version` (per Decision 20: let `normalize_ir()` add it), exposing the missing call.

**File modified**: `src/pflow/cli/main.py` (lines 198-211)

### Smoke test results

| # | Test | Result |
|---|------|--------|
| 1 | `pflow smoke-test.pflow.md greeting="hello"` — execute from file | ✅ Executed, output correct |
| 2 | `pflow --validate-only smoke-test.pflow.md` — validate-only | ✅ "Workflow is valid" |
| 3 | `pflow workflow save smoke-test.pflow.md --name smoke-test` — save | ✅ Saved to `~/.pflow/workflows/smoke-test.pflow.md` with frontmatter |
| 4 | `pflow smoke-test greeting="saved workflow works"` — execute saved | ✅ Executed (after normalize_ir fix) |
| 5 | `pflow workflow list` — list workflows | ✅ Shows `smoke-test` with description from H1 prose |
| 6 | `pflow workflow describe smoke-test` — describe | ✅ Shows inputs, outputs, execution history, last params |
| 7 | `pflow old-workflow.json` — JSON rejection | ✅ Fails with "not found" (minor: could say "JSON no longer supported" — low priority, Phase 3) |

### Insights from smoke testing

1. **Save preserves original markdown content**: The saved file at `~/.pflow/workflows/smoke-test.pflow.md` has correct YAML frontmatter prepended (`created_at`, `updated_at`, `version`) followed by the exact original markdown body unchanged. Frontmatter/body split works correctly.

2. **`update_metadata()` works**: After executing the saved workflow, `workflow describe` showed `Runs: 1 time`, `Last: ...`, `Status: ✓ Success`, `Last Parameters: greeting=saved workflow works`. This confirms frontmatter read-modify-write cycle preserves the body while updating metadata fields.

3. **Description extraction works**: `workflow list` showed the H1 prose ("A minimal workflow to verify the markdown format pipeline works end-to-end.") as the description. This is extracted from the markdown content during `load()`, not stored separately.

4. **The `_try_load_workflow_from_file` vs `_try_load_workflow_from_registry` asymmetry**: These two paths have different normalize_ir behavior. The file path always normalizes. The registry path did not. Now fixed, but Phase 3 fork agents should be aware this pattern may recur if new load paths are added.

5. **Edge generation confirmed**: The single-node workflow got no edges (correct — `[{"from": n[i], "to": n[i+1]}]` produces `[]` for a single node). Multi-node workflows from the parser tests confirm edge generation works for chains.

### `make check` after smoke test fix

All pass (ruff, mypy, deptry clean).

Status: **Phase 2.9 smoke test gate PASSED.** All Phase 2 work complete. Ready for Phase 3 forks.

## Resumption Checkpoint

**Current state — Phase 2 complete:**
- Fork F0 ✅ Phase 0.1 (PyYAML dep) + Phase 0.2 (planner/repair gating)
- Fork F0b ✅ Phase 0.3 + 1.1 + 1.2 (test utility + parser + parser tests)
- Fork F1 ✅ Phase 2.1 + 2.1b (CLI integration)
- Fork F2 ✅ Phase 2.2 + 2.2b (WorkflowManager + rich_metadata flattening)
- Fork F3 ✅ Phase 2.3 (save service)
- Fork F4 ✅ Phase 2.4 + 2.5 (MCP integration)
- Fork F5 ✅ Phase 2.6 (runtime executor)
- Fork F6 ✅ Phase 2.7 + 2.8 (error messages + unknown param warnings)
- Phase 2.9 ✅ Smoke test gate passed (with normalize_ir bug fix)
- `make check`: all pass
- `make test`: ~3350 passed, ~251 failed, 507 skipped, 7 errors

**All production code is updated.** The ~251 test failures are ALL from tests that still write JSON workflows to disk or assert on JSON-era behavior. These are Phase 3 scope.

### Test failure categories (for Phase 3 fork assignment)

| Category | Files | Approx. failures | Notes |
|----------|-------|-------------------|-------|
| CLI tests writing JSON | test_main.py, test_workflow_output_handling.py, test_validate_only.py, test_validation_before_execution.py, test_shell_stderr_warnings.py, test_shell_stderr_display.py, test_workflow_output_source_simple.py, test_dual_mode_stdin.py, test_enhanced_error_output.py | ~150 | Use `ir_to_markdown()` from `tests/shared/markdown_utils.py` to convert IR dicts to `.pflow.md` |
| CLI workflow resolution | test_workflow_resolution.py | ~5 | `.json` extension stripping → `.pflow.md`, plus new test for markdown extension |
| CLI JSON error handling | test_json_error_handling.py | ~5 | Rename to `test_parse_error_handling.py`, rewrite for markdown parse errors |
| Integration tests | test_workflow_manager_integration.py, test_workflow_outputs_namespaced.py, test_sigpipe_regression.py, test_metrics_integration.py, test_e2e_workflow.py | ~40 | WorkflowManager signature changes, JSON→markdown, rich_metadata→flat |
| Executor service | test_executor_service.py | ~13 | Constructs workflows via old JSON WorkflowManager, saves, then reads raw JSON with `json.load()` and checks `saved_data["rich_metadata"]["last_execution_params"]`. Needs: (1) write `.pflow.md` not `.json`, (2) flat metadata structure (no `rich_metadata` wrapper), (3) read with YAML frontmatter parsing not `json.load()`. See F2 progress log "Note for main agent" section. |
| Runtime tests | test_workflow_executor/test_*.py, test_nested_template_e2e.py | ~10 | JSON file loading → markdown |
| Core tests | test_workflow_manager_update_ir.py | ~8 | Tests dead code (update_ir gated). Consider skipping. |
| Shell smart handling | test_shell_smart_handling.py | ~10 | Writes JSON workflows to disk |
| Stdin no hang | test_stdin_no_hang.py | ~1 | Writes JSON workflow. F6 noted this fails due to F1's `.json` rejection — expected. |

### Key patterns for Phase 3 forks

1. **`ir_to_markdown(ir_dict)`** from `tests/shared/markdown_utils.py` converts any IR dict to valid `.pflow.md` content. This is the primary tool for test migration.
2. **`write_workflow_file(ir_dict, path)`** writes a `.pflow.md` file to disk. Use instead of `json.dump()`.
3. **File extension**: All `tmp_path / "workflow.json"` → `tmp_path / "workflow.pflow.md"`.
4. **CLI invocations**: All `runner.invoke(main, ["workflow.json"])` → `runner.invoke(main, ["workflow.pflow.md"])`.
5. **Error assertions**: `"Invalid JSON"` → markdown parse errors. `".json"` in help text → `".pflow.md"`.
6. **WorkflowManager.save()**: Old `save(name, ir_dict, description)` → new `save(name, markdown_content, metadata)`. Tests constructing metadata with `rich_metadata` wrapper → flat structure.
7. **`normalize_ir()` is called by CLI on all load paths** (file + registry). Tests that construct IR dicts directly and pass to execution still need `normalize_ir()` or must include `ir_version` in the dict.

### Operational notes for fork launches

- `pflow fork-session` works (F3 and F4 completed via it). F4 had a false start (background task created but no output) — retrying succeeded. Cold start takes ~2-3 minutes for context loading.
- The `pflow` alias points to the main repo (`/Users/andfal/projects/pflow`), NOT this worktree. Fork-session uses the main repo's code (JSON-based), which is fine — the fork inherits our worktree as its cwd and modifies files here.
- For test verification during forks: forks should NOT run `make test` (other forks may be modifying files concurrently). Only the main agent runs `make test` after all forks complete.

**Next:** Launch Phase 3 forks (F7-F13). Per the plan: F7 (examples-core) first to prime the cache, then F8-F13 in parallel.

## Phase 3 — Entry 7: Example conversions and test migration

### Phase 3.1: Example conversions (F7, F8, F9)

- F7 (examples-core): 5 files converted, originals deleted. Enriched with companion .md documentation content.
- F8 (examples-real): 4 complex workflows converted (17-node generate-changelog, batch configs, etc.). JSON originals deleted.
- F9 (examples-rest+invalid): 19 remaining examples converted, 8 new invalid .pflow.md files created. Old invalid .json/.md deleted.
- Companion .md files (advanced/*.md) still present — enrichment deferred.

### Phase 3.3: Test migration

Fork-session approach hit context window limit ("Prompt is too long") after ~12 fork launches. Switched to test-writer-fixer subagents for remaining test files.

Completed via fork-session:
- F10 (test-cli-heavy): 75 passed, 1 skipped — test_workflow_output_handling.py, test_main.py, test_dual_mode_stdin.py
- F11b (test-cli-output): 39 passed — test_shell_stderr_warnings.py, test_enhanced_error_output.py, test_workflow_output_source_simple.py, test_validation_before_execution.py, test_shell_stderr_display.py
- F13b (test-runtime-nodes): 61 passed — test_shell_smart_handling.py, test_workflow_executor/*.py, test_stdin_no_hang.py

In progress via test-writer-fixer subagents:
- F11a: test_workflow_save_cli.py, test_workflow_resolution.py, test_validate_only.py, test_workflow_save.py, test_workflow_save_integration.py, test_json_error_handling.py (rename)
- F12: test_workflow_manager_integration.py, test_e2e_workflow.py, test_metrics_integration.py, test_sigpipe_regression.py, test_workflow_outputs_namespaced.py
- F13a: test_workflow_manager.py, test_executor_service.py, test_workflow_save.py (MCP), test_workflow_save_service.py, test_workflow_manager_update_ir.py (skip)

Status: Waiting for 3 test-writer-fixer subagents to complete. After they finish: run make test + make check, then Phase 3.4 (validation tests).

## Session Resumption — Entry 8: Assessment + fork-session fix

Resumed session. Ran `make test` + `make check` to assess state after previous session's partial completion.

**Test state**: 52 failed, 3540 passed, 517 skipped. Failures in 4 files:
- `test_ir_examples.py` (15) — references old `.json` examples (Phase 3.4 scope)
- `test_executor_service.py` (11) — old save API + `rich_metadata` wrapper
- `test_mcp_server/test_workflow_save.py` (10) — old `ExecutionService.save_workflow()` signature
- `test_workflow_save_integration.py` (4 ruff lint issues)

**`make check`**: 4 ruff errors (S108, SIM105) in `test_workflow_save_integration.py`, 2 files needing format.

F11a and F12 from previous session completed successfully. F13a (executor_service, MCP workflow save, workflow_manager) did not complete.

### Fix: fork-session workflow stdin piping

The fork-session workflow embedded `${prompt}` directly in a shell command string (`claude -p "...${prompt}..."`). Special characters (backticks, quotes, `$`) in prompts broke shell parsing — likely the root cause of "prompt too long" failures in the previous session.

**Fix**: Changed the `fork` node to pipe the prompt via `stdin` instead of embedding it in the command. The prompt now goes through pflow's Python-side template resolution into subprocess stdin, bypassing shell interpretation entirely.

- Updated `~/.pflow/workflows/fork-session.json`
- Updated `~/.pflow/workflows/fork-session.pflow.md`
- Tested with simple prompt and prompt containing backticks, `$HOME`, quotes, code blocks — all passed.

Status: Ready to fix remaining 52 test failures (4 files). Next: launch parallel test-writer-fixer agents.

## Entry 9: Final test fixes via fork-session (52 → 0 failures)

Launched 4 parallel fork-session agents to fix all remaining test failures:

### Round 1 (4 forks in parallel)

| Fork | File | Result |
|------|------|--------|
| b578e23 | `tests/test_cli/test_workflow_save_integration.py` | ✅ Fixed 4 ruff lint issues (S108: hardcoded /tmp paths → tmp_path fixture; SIM105: try-except-pass → contextlib.suppress) |
| b030c08 | `tests/test_core/test_ir_examples.py` | ✅ Rewrote for .pflow.md examples (23 tests). Removed JSON-specific tests, added markdown-specific validation tests. |
| b553c41 | `tests/test_execution/test_executor_service.py` | ✅ Migrated 12 tests: old save API → new save(name, markdown_content), .json → .pflow.md, rich_metadata → flat frontmatter |
| b530659 | `tests/test_mcp_server/test_workflow_save.py` | ✅ Migrated 11 tests: old ExecutionService.save_workflow(workflow=dict, description=) → new save_workflow(workflow=markdown_str) |

Post-round-1 state: 12 failed, 3584 passed, 517 skipped. Two more files needed fixing.

### Round 2 (2 forks in parallel)

| Fork | File | Result |
|------|------|--------|
| b2d2cd2 | `tests/test_core/test_workflow_save_service.py` | ✅ Migrated 10 tests: load_and_validate_workflow with .pflow.md files, save_workflow_with_options new signature (name, markdown_content, *, force, metadata) |
| bc894fe | `tests/test_docs/test_example_validation.py` | ✅ Rewrote for .pflow.md: scans *.pflow.md, parses with parse_markdown(), catches MarkdownParseError for invalid examples |

### Final verification

- `make test`: **3597 passed, 516 skipped, 0 failed**
- `make check`: **all pass** (ruff, ruff-format, mypy, deptry clean)

Files modified in this entry:
- `tests/test_cli/test_workflow_save_integration.py`
- `tests/test_core/test_ir_examples.py`
- `tests/test_execution/test_executor_service.py`
- `tests/test_mcp_server/test_workflow_save.py`
- `tests/test_core/test_workflow_save_service.py`
- `tests/test_docs/test_example_validation.py`

Status: **Phase 3 complete (all phases 0–3 done).** All production code updated, all examples converted, all tests migrated. Next: Phase 4 (CLI integration testing + documentation polish).

## Entry 10: Phase 4.2 — CLI integration testing + extension error polish

### CLI integration test results

| # | Test | Result |
|---|------|--------|
| 1 | `pflow examples/core/minimal.pflow.md` — execute from file | ✅ Executed, 0.4s |
| 2 | `pflow --validate-only examples/core/minimal.pflow.md` | ✅ "Workflow is valid" |
| 3 | `pflow workflow save ... --name phase4-test --force` | ✅ Saved with frontmatter |
| 4 | `pflow phase4-test` — execute saved workflow by name | ✅ Executed |
| 5 | `pflow workflow list` | ✅ Shows phase4-test with H1 description |
| 6 | `pflow workflow describe phase4-test` | ✅ Shows runs, status, inputs/outputs |
| 7 | `pflow old-workflow.json` — JSON rejection | ✅ (after fix, see below) |
| 8 | `pflow "generate a changelog"` — gated planner | ✅ Shows gated message with `.pflow.md` example |
| 9 | `pflow nonexistent.pflow.md` — missing file | ✅ "not found" error |
| 10 | `pflow --validate-only examples/invalid/missing-type.pflow.md` | ✅ Error with line number + suggestion |

### Bug fixes during integration testing

**Bug 1: Error messages duplicated.** Running `pflow old-workflow.json` printed the error twice. Root cause: `_handle_named_workflow()` in `cli/main.py` re-called `resolve_workflow()` when `workflow_ir` was `None` from a parse error, triggering the error message a second time. Fix: added `and source != "parse_error"` guard at line 3446.

**Bug 2: Bare `workflow.md` not recognized as file path.** `is_likely_workflow_name()` checked `.json` and `.pflow.md` but not `.md`. So `pflow workflow.md` fell through to the invalid planner input handler instead of the file path handler. Fix: added `.md` to the extension check at line 3623.

**Bug 3 (fork): Wrong extension errors missing.** Launched fork to add explicit error messages when users pass `.json` or `.md` files. Fork added: (1) `.json` rejection before file existence check in `_try_load_workflow_from_file()`, (2) `.md` (non `.pflow.md`) rejection with rename suggestion, (3) fallback hints in `_handle_workflow_not_found()`.

**Test fix:** Updated `test_parse_error_handling.py` assertion from `.pflow.md format instead` to `.pflow.md format` to match the actual error wording.

### Final verification

- `make test`: **3597 passed, 516 skipped, 0 failed**
- `make check`: **all pass** (ruff, ruff-format, mypy, deptry clean)

Files modified:
- `src/pflow/cli/main.py` (3 changes: parse_error guard, .md in is_likely_workflow_name, fork changes for extension errors)
- `tests/test_cli/test_parse_error_handling.py` (assertion string fix)

Status: Phase 4.2 (CLI integration testing) complete. Phase 4.1 (make test + make check) complete.

## Resumption Checkpoint

**Current state — Phases 0–4.2 complete:**

| Phase | Status | Notes |
|-------|--------|-------|
| 0.1 PyYAML dep | ✅ | Fork F0 |
| 0.2 Planner/repair gating | ✅ | Fork F0 |
| 0.3 Test utility (ir_to_markdown) | ✅ | Fork F0b |
| 1.1 Markdown parser | ✅ | Fork F0b (~350 lines, 70 tests) |
| 1.2 Parser tests | ✅ | Fork F0b |
| 2.1 CLI integration | ✅ | Fork F1 |
| 2.2 WorkflowManager rewrite | ✅ | Fork F2 |
| 2.3 Save service | ✅ | Fork F3 |
| 2.4-2.5 MCP integration | ✅ | Fork F4 |
| 2.6 Runtime executor | ✅ | Fork F5 |
| 2.7-2.8 Error messages + unknown param warnings | ✅ | Fork F6 |
| 2.9 Smoke test gate | ✅ | Manual (with normalize_ir bug fix) |
| 3.1 Example conversions | ✅ | Forks F7, F8, F9 |
| 3.2 Invalid examples | ✅ | Fork F9 |
| 3.3 Test migration | ✅ | Forks F10-F13 + test-writer-fixer agents |
| 3.4 Validation tests | ✅ | Forks for test_ir_examples.py, test_example_validation.py |
| 4.1 Quality checks | ✅ | 3597 passed, 516 skipped, 0 failed |
| 4.2 CLI integration testing | ✅ | 10/10 scenarios verified + 3 bug fixes |
| 4.3 MCP tool testing | ⏭️ Skipped | Lower priority, covered by unit tests |
| 4.4 Documentation | **TODO** | CLAUDE.md entries, tests/shared/README.md |
| 5 Agent instructions | **TODO** | Collaborative with user |

### What's left

**Phase 4.4 — Documentation (small, can be forked):**
- Add `src/pflow/core/CLAUDE.md` entry for `markdown_parser.py`
- Update `tests/shared/README.md` with `markdown_utils` documentation
- Update code comments referencing JSON workflow files (grep for remaining `.json` references in comments/docstrings)

**Phase 5 — Agent instructions (collaborative with user):**
- Update `src/pflow/cli/resources/cli-agent-instructions.md` (~13 JSON references → .pflow.md)
- Update `src/pflow/cli/resources/cli-basic-usage.md` if applicable
- This phase is done collaboratively — not autonomous

### Key facts for the next agent

1. **All production code is updated.** The markdown parser, CLI, WorkflowManager, save service, MCP, runtime executor, error messages, and unknown param warnings are all working.
2. **All tests pass.** 3597 passed, 516 skipped (planner/repair tests gated per Decision 26).
3. **All examples converted.** 30+ `.json` → `.pflow.md` in `examples/`. 8 new invalid `.pflow.md` files.
4. **The parser is at `src/pflow/core/markdown_parser.py`.** ~350 lines, state machine, 70 tests.
5. **The test utility is at `tests/shared/markdown_utils.py`.** `ir_to_markdown()` and `write_workflow_file()` for test migration.
6. **Save preserves original markdown content.** No IR-to-markdown serialization. Frontmatter is prepended on save, stripped on load.
7. **WorkflowManager metadata is flat** (no `rich_metadata` wrapper). All callers updated.
8. **Error messages are markdown-native** with line numbers and suggestions.
9. **Extension error UX:** `.json` → "no longer supported, use .pflow.md", `.md` → "rename to .pflow.md"
10. **`pflow fork-session`** works for launching forked agents. Forks inherit full conversation context. Use `run_in_background=true` for parallel launches.

## Entry 11: Phase 4.4 — Documentation updates (CLAUDE.md files)

Launched 6 parallel forks to update CLAUDE.md files across the codebase for JSON→markdown migration accuracy.

### Fork results

| Fork | Area | Files changed | Summary |
|------|------|---------------|---------|
| A (b0d608c) | Root + architecture | 2 | Root: 6 fixes (project overview, file listings, planner→gated, examples, run command). Architecture: 3 fixes (JSON→markdown references, historical marker). |
| B (b279c3d) | src/pflow/core | 1 | 18 fixes + added markdown_parser.py section. WorkflowManager signatures, storage format, file paths, examples, design decisions all updated. |
| C (bba1850) | src/pflow/cli | 1 | 15 fixes. Gating markers on --auto-repair/--no-update/planner/repair/--generate-metadata. .json→.pflow.md. Function names, signatures, flow diagrams updated. |
| D (b77036a) | src/pflow/mcp_server (4 files) | 2 of 4 | mcp_server/CLAUDE.md: 3 fixes (removed deleted params, updated resolver). utils/CLAUDE.md: 2 fixes (.json→.pflow.md, json.loads→parse_markdown). services/ and tools/ needed no changes. |
| E (bef6aaa) | execution + runtime + planning | 3 of 4 | execution/CLAUDE.md: 3 fixes (stale function, gated update_ir, repair gating). runtime/CLAUDE.md: 4 fixes (JSON IR→workflow IR, .pflow.md). planning/CLAUDE.md: gating notice. formatters/ needed no changes. |
| F (bb52a8c) | tests + shared/README | 3 | tests/CLAUDE.md: 2 fixes (markdown_utils listing, JSON→IR). test_cli/CLAUDE.md: 3 fixes (gating, .pflow.md). shared/README.md: added markdown_utils documentation. |

### Verification

- `make test`: **3597 passed, 516 skipped, 0 failed**
- `make check`: **all pass** (ruff, ruff-format, mypy, deptry clean)

Files modified: 12 CLAUDE.md files + 1 README.md across the codebase.

Status: **Phase 4.4 complete.** All documentation updated. Only Phase 5 (agent instructions — collaborative with user) remains.

## Entry 12: Test quality audit + stale .json reference sweep

### Test quality audit (4 parallel test-writer-fixer subagents)

Verified all 516 skipped tests are legitimate (572 planner/repair gating + 63 pre-existing LLM API key skips, zero suspicious). Then audited all ~38 migrated test files across 4 parallel agents:

| Agent | Scope | Result |
|-------|-------|--------|
| CLI Critical (7 files) | test_main, workflow_save*, validate_only, resolution, parse_error | Clean — 112 tests, no issues |
| CLI Secondary (8 files) | output_handling, dual_mode_stdin, stderr, enhanced_error, validation | Clean — 94 tests, no issues |
| Integration (5 files) | e2e, workflow_manager_integration, sigpipe, metrics, outputs | Clean — 57 tests, no issues |
| Core/Runtime/MCP (16 files) | workflow_manager, ir_schema, executor_service, mcp_save, runtime | Clean — all pass, no issues |

**No deleted important tests. No weakened assertions. No dropped edge cases.**

### Stale .json reference sweep (3 parallel forks)

Grepped entire codebase for remaining `workflow.json` / `.json` workflow references. Found 44 stale references across production code, MCP resources, and architecture docs. Launched 3 forks:

| Fork | Area | Fixes |
|------|------|-------|
| b4b08e9 | Production code | 12 fixes: user_errors.py, workflow_save_formatter.py, context_builder.py, repair_save_handlers.py |
| bdc839d | MCP resources | 9 fixes: server.py instruction string, instruction_resources.py CLI examples and save syntax |
| bc44e7d | Architecture docs | 23 fixes: architecture.md (16), simple-nodes.md (1), shell-pipes.md (4), vision/ (2) |

**Legitimate .json references verified and left alone:** trace files, settings.json, registry.json, cache files, CLI .json rejection checks, template_validator example paths.

### Verification

- `make test`: **3597 passed, 516 skipped, 0 failed**
- `make check`: **all pass** (ruff, ruff-format, mypy, deptry clean)

Status: **Phases 0-4 fully complete.** Only Phase 5 (agent instructions — collaborative with user) remains.

## Resumption Checkpoint

**Current state — ALL phases except Phase 5 complete:**

| Phase | Status |
|-------|--------|
| 0.1 PyYAML dep | ✅ |
| 0.2 Planner/repair gating | ✅ |
| 0.3 Test utility (ir_to_markdown) | ✅ |
| 1.1-1.2 Markdown parser + tests | ✅ |
| 2.1-2.8 All integration (CLI, WM, save, MCP, runtime, errors) | ✅ |
| 2.9 Smoke test gate | ✅ |
| 3.1-3.4 Examples + tests + validation | ✅ |
| 4.1 Quality checks (make test + make check) | ✅ |
| 4.2 CLI integration testing (10 scenarios) | ✅ |
| 4.4 Documentation (CLAUDE.md + README) | ✅ |
| Audit: skipped tests | ✅ All legitimate |
| Audit: test quality | ✅ No issues |
| Audit: stale .json references | ✅ All fixed |
| **5 Agent instructions** | **TODO — collaborative with user** |

### What Phase 5 needs

Update these two files (collaborative with user — not autonomous):
- `src/pflow/cli/resources/cli-agent-instructions.md` — ~13 JSON references → .pflow.md format, update workflow examples, remove --description from save examples
- `src/pflow/cli/resources/cli-basic-usage.md` — check for JSON workflow references

These files are what agents see when running `pflow instructions usage`. The user wants to review changes since they directly affect LLM authoring experience.

### Key facts for the next agent

1. **All production code updated.** Parser, CLI, WorkflowManager, save service, MCP, runtime, errors — all working.
2. **All tests pass.** 3597 passed, 516 skipped. All skips verified legitimate.
3. **All test quality verified.** 4 parallel audits found zero issues across 38 migrated files.
4. **All documentation updated.** 12 CLAUDE.md files + README + architecture docs + MCP resources.
5. **All stale .json references fixed.** 44 fixes across production code, MCP, and docs.
6. **make check passes.** ruff, ruff-format, mypy, deptry all clean.
7. **Parser:** `src/pflow/core/markdown_parser.py` (~350 lines, 70 tests).
8. **Test utility:** `tests/shared/markdown_utils.py` (`ir_to_markdown()`, `write_workflow_file()`).
9. **Save preserves original markdown.** Frontmatter prepended on save, stripped on load.
10. **Metadata is flat** (no `rich_metadata` wrapper).
11. **Phase 5 is the ONLY remaining work.** Two files, collaborative with user.

## Entry 13: MCP integration testing + real workflow verification

Tested the full MCP tool interface and real saved workflows end-to-end.

### MCP tool tests (10/10 passed)

Validated all workflow-facing MCP tools: `workflow_validate` (raw content, file path, invalid content), `workflow_save` (raw content, file path), `workflow_describe`, `workflow_list`, `workflow_execute` (saved name, file path, raw content with inputs/outputs/params). All passed.

### Saved workflow verification

All saved `.pflow.md` workflows in `~/.pflow/workflows/` (with frontmatter from prior JSON-era executions) validate, load, describe, and execute correctly. Tested `directory-file-lister` (execute), `release-announcements` (describe with full metadata), and validated all 4 complex workflows.

### Real workflow execution: release-announcements (8 nodes, 3 batch stages)

Executed via CLI — all 8 nodes succeeded (51s, $0.14): extract-changelog → draft-announcements (3 batch) → critique-announcements (3 batch) → improve-announcements (3 batch) → post-to-slack → post-to-discord → save-x-post → format-output.

Parsed IR verified byte-for-byte identical between `.pflow.md` and `.json` versions.

### Pre-existing bug found: batch workflows fail through MCP

Same workflow fails through MCP `workflow_execute` with "Unresolved variables in parameter 'prompt'" (no variables listed). Root cause: MCP path (`enable_repair=False`) skips template validation, which has a side effect of registering batch context variables (`item`, `__index__`). CLI has `_validate_before_execution()` that triggers this registration; MCP path does not. **Not caused by markdown migration** — pre-existing on main with JSON. Filed as [GitHub issue #79](https://github.com/spinje/pflow/issues/79).

### MCP agent instructions gap identified

Both `pflow://instructions` and `pflow://instructions/sandbox` MCP resources are entirely JSON-based — all workflow examples, save commands, and building guides use JSON format. Any agent following these instructions would produce workflows that fail on save. Deferred to after Phase 5 CLI instruction updates per user decision.

Status: Phase 4 fully complete including MCP verification. Phase 5 (CLI agent instructions — collaborative with user) remains.

## Entry 14: Nested workflow validation fixes + edge case verification

### Nested workflow validation was broken (pre-existing)

Tested `type: workflow` nodes end-to-end via CLI. Found two pre-existing issues:

1. **`WorkflowValidator._validate_node_types()`** rejected `workflow` as "Unknown node type" because it's handled by the compiler, not registered in the node registry. Fix: added `compiler_special_types` allowlist.

2. **`TemplateValidator._extract_node_outputs()`** didn't register outputs from `output_mapping` on workflow nodes, causing `${process.mapped_key}` to fail template validation. Fix: added `output_mapping` registration block that mirrors the compiler's existing logic.

Both fixes are small (5-10 lines each) but critical — without them, any workflow using `type: workflow` fails validation.

### Other fixes

3. **output_mapping missing key warning** in `workflow_executor.py:post()`: When a child_key from output_mapping doesn't exist in child storage, now logs a warning with available keys (filtered to exclude internal `_pflow_*` and `__*__` keys).

4. **Stdin error message** in `cli/main.py:3168`: Replaced stale JSON format example with `.pflow.md` markdown format.

### Tests added

- `test_workflow_node_type_bypasses_registry` — regression guard for the allowlist
- `test_workflow_output_mapping_resolves_in_templates` — regression guard for output_mapping in template validation

### Deferred to Task 59

Tested 4 failure modes for nested workflows (missing params, wrong param names, wrong output keys, no mappings). Found several agent-facing UX issues:
- Tracebacks shown to agents in compilation errors
- Wrong param_mapping doesn't suggest available child inputs
- Relative path resolution broken for top-level `workflow_ref` (missing `_pflow_workflow_file` in initial shared store)
- Error message stacking in deeply nested failures

Full details in braindump: `.taskmaster/tasks/task_59/starting-context/braindump-nested-workflow-gaps.md`

### Pre-existing bug confirmed

GitHub issue #79 (batch workflows fail through MCP) — found during MCP testing in Entry 13, not related to markdown migration.

### Verification

- `make test`: **3599 passed, 516 skipped, 0 failed**
- `make check`: **all pass** (ruff, ruff-format, mypy, deptry clean)

Files modified:
- `src/pflow/core/workflow_validator.py` (allowlist)
- `src/pflow/runtime/template_validator.py` (output_mapping registration)
- `src/pflow/runtime/workflow_executor.py` (missing key warning)
- `src/pflow/cli/main.py` (stdin error message)
- `tests/test_core/test_workflow_validator.py` (2 new tests)

Status: All verification complete. Phase 5 (CLI agent instructions — collaborative with user) is the only remaining work for Task 107.

## Entry 15: Fix trace filenames + workflow_name cleanup

### Problem

Trace filenames were always generic (`workflow-trace-YYYYMMDD-HHMMSS.json`) because `WorkflowTraceCollector` was initialized with `ir_data.get("name", "workflow")` — the IR dict never has a `name` field. Pre-existing bug, not caused by markdown migration.

### Fix

Three changes to `cli/main.py`:

1. **`_setup_workflow_execution()`**: For file-based workflows, derive `workflow_name` from filename stem and store in `ctx.obj["workflow_name"]`. Previously this key was only set for saved workflows.

2. **`execute_workflow()` call**: Changed `WorkflowManager` gate from `if workflow_name` to `if ctx.obj.get("workflow_source") == "saved"`. Necessary because `workflow_name` is now set for all sources, but metadata updates only apply to saved workflows.

3. **Trace collector init**: Simplified to `ctx.obj.get("workflow_name", "workflow")` — works for both sources.

### Key design decision

`workflow_name` is now always set (derived from filename or save name). The decision of whether to create a `WorkflowManager` for metadata updates is gated on `workflow_source == "saved"`, not on whether a name exists. One key, one meaning.

### Verification

- File workflow: `pflow examples/core/minimal.pflow.md` → trace `workflow-trace-minimal-...`, no metadata update attempted
- Saved workflow: `pflow directory-file-lister` → trace `workflow-trace-directory-file-lister-...`, metadata updated
- `make test`: 3599 passed, 516 skipped, 0 failed
- `make check`: all pass

Files modified:
- `src/pflow/cli/main.py` (3 edits)
- `src/pflow/cli/CLAUDE.md` (1 edit — updated ctx.obj docs for workflow_name/workflow_source)

Status: Phase 5 (CLI agent instructions — collaborative with user) is the only remaining work for Task 107.

## Entry 16: Final JSON syntax sweep + stdin example

Swept all production code for remaining user-facing JSON workflow syntax via pflow-codebase-searcher audit.

Fixes:
- `src/pflow/nodes/python/python_code.py` — module docstring JSON example → markdown
- `src/pflow/core/llm_config.py:454` — error message JSON node definition → markdown
- `src/pflow/runtime/template_validator.py:1539-1542` — shell multi-stdin fix suggestion JSON examples → markdown
- `tests/test_core/test_llm_config_workflow_model.py` — 2 test assertions updated for new format
- `examples/core/stdin-echo.pflow.md` — new example demonstrating `- stdin: true` piped input

Remaining JSON workflow syntax is only in MCP agent instruction files (Phase 5 scope) and internal docstrings (ir_schema.py, batch_node.py — low priority).

Verified: piped stdin (`echo "hello" | pflow stdin-echo.pflow.md`) and `--validate-only` on saved workflow names both work.

- `make test`: 3599 passed, 516 skipped, 0 failed
- `make check`: all pass

Status: Phase 5 (agent instructions — collaborative with user) is the only remaining work.

## Entry 17: Phase 5 — cli-agent-instructions.md update + review

### What was done

Updated `src/pflow/cli/resources/cli-agent-instructions.md` — all 6 passes from the implementation plan in `scratchpads/phase5-agent-instructions/implementation-plan.md` were applied by a code-implementer subagent, then reviewed chunk-by-chunk by the main agent.

### Issues found and fixed during review

1. **"All Template Patterns" section still had JSON `"params": {...}` block** — Pass 3.6 was missed by the implementing agent. Replaced with markdown format showing params inside `### node` context.

2. **Inline vs code block guideline was wrong** — initial replacement used key count (5+ keys) as the threshold. User correctly pointed out it's nesting depth that matters, not count. Rewrote guideline: "Inline `- key: value` for flat params and simple nesting. `yaml param_name` code block for deep nesting or batch config."

3. **`yaml headers` and `yaml body` code blocks for flat structures** — the `fetch-with-auth` node in the Node Creation patterns section used `yaml headers` (3 flat keys) and `yaml body` (2 flat keys) as code blocks. These contradicted the guideline. Converted to inline `- headers:` and `- body:` nesting.

4. **`yaml batch` code blocks for simple batch config** — three batch examples used `yaml batch` code blocks for 1-3 flat keys (`items`, `parallel`, `max_concurrent`). Converted to inline `- batch:` nesting. Left two complex batch examples (inline arrays of objects) as `yaml batch` code blocks. Updated key rules to reflect that batch can be inline or code block.

### Parser fix needed: inline `- batch:` routing

The parser currently only routes `batch` to the top-level node field from `yaml batch` code blocks. If an agent writes `- batch:` inline, it goes to `params.batch` (wrong). The parser needs a small fix (~3 lines) to also extract `batch` from inline params to top-level, same as it does for `type`.

**What to fix**: In `src/pflow/core/markdown_parser.py`, function `_build_node_dict()`, add a `batch` pop from `all_params` to top-level `node["batch"]` — same pattern as the `type` extraction at line 695-696. Also add parser tests for inline `- batch:` routing.

**Why this matters**: The agent instructions now show `- batch:` inline for simple cases. Without the parser fix, agents following the instructions would produce workflows where batch config silently goes to `params.batch` instead of top-level `batch`, causing batch processing to not work.

**Priority**: Must be fixed before these instructions go live. Small, isolated change.

Files modified:
- `src/pflow/cli/resources/cli-agent-instructions.md` (Phase 5 updates + 4 review fixes)

Status: Phase 5 cli-agent-instructions.md complete pending parser fix for inline batch routing. Still need to check `cli-basic-usage.md`.

## Entry 18: Phase 5 — Philosophy and terminology polish

Collaborative review with user on cli-agent-instructions.md. Three changes:

1. **"Why pflow exists" reframed**: Combined with format framing — now defines pflow as "executable documentation" (`.pflow.md` reads like a runbook, prose = intent, params = behavior, code blocks = execution).

2. **"Edges" terminology removed throughout**: Renamed to "step order" consistently — philosophy section, teaching section (lines 65-173), misunderstandings, Key Success Factors. Agents never write edges, so the term was confusing.

3. **Quick Wins updated**: Dropped two niche items (`Prefer: wait=60`, auto-JSON-parsing) in favor of two format-relevant wins ("Step order = execution order", "Templates reach any previous step").

Also fixed: stale `show_structure` command reference → `registry run`, "Step 12" → "Step 11", Phase numbering gap (1→3 → 1→2), `//` comments → `#`.

Files modified: `src/pflow/cli/resources/cli-agent-instructions.md`

Status: Phase 5 cli-agent-instructions.md content complete pending parser fix for inline batch routing. Still need to check `cli-basic-usage.md`.

## Entry 19: Parser fix — inline `- batch:` routing to top-level

### Problem

The parser only routed `batch` to top-level `node["batch"]` from `yaml batch` code blocks (in `_route_code_blocks_to_node()`). Inline `- batch:` with YAML nesting went to `params.batch` instead — meaning batch processing silently wouldn't work for agents following the updated instructions that show `- batch:` inline for simple cases.

### Fix (2 production edits)

1. **`_build_node_dict()`** (line 709-711): Added `batch` pop from `all_params` to `node["batch"]`, same pattern as the existing `type` extraction. This ensures inline `- batch:` routes to the correct top-level field.

2. **`_check_param_code_block_conflicts()`** (line 653): Removed the `batch` exclusion from the duplicate check. Previously `batch` was excluded because inline went to `params` and code block went to `node` (different targets). Now both target `node["batch"]`, so having both is a genuine conflict and should error.

### Tests added (3 new)

- `test_inline_batch_to_top_level` — nested YAML `- batch:` with `items` + `parallel` routes to top-level, not params
- `test_inline_batch_simple_to_top_level` — simple `- batch:` with just `items` routes correctly
- `test_inline_and_code_block_batch_is_error` — both inline and `yaml batch` code block on same node raises `MarkdownParseError`

### Stale test fix

`test_instructions.py` assertion "Two Fundamental Concepts - Edges vs Templates" → "Step Order vs Templates" to match Entry 18's rename.

### Verification

- `make test`: 3602 passed, 516 skipped, 0 failed
- `make check`: all pass (ruff, ruff-format, mypy, deptry clean)

Files modified:
- `src/pflow/core/markdown_parser.py` (2 edits)
- `tests/test_core/test_markdown_parser.py` (3 new tests)
- `tests/test_cli/test_instructions.py` (1 assertion fix)

Status: Parser fix complete. Phase 5 cli-agent-instructions.md fully unblocked. Still need to check `cli-basic-usage.md`.

## Entry 20: Phase 5 — cli-basic-usage.md check + agent-friendly command output

### cli-basic-usage.md

Checked `src/pflow/cli/resources/cli-basic-usage.md` — no JSON workflow references found. File only references workflow execution by name, `pflow instructions create`, and `registry run/describe/discover`. No changes needed. **Phase 5 complete.**

### Agent-friendly command output (post-Task-107 polish)

Implemented plan from `scratchpads/agent-friendly-command-output/implementation-plan.md` — add `.pflow.md` usage snippets to command outputs so agents know how to use nodes in workflows.

#### Round 1: Initial implementation (5 changes)

1. **`context_builder.py`**: Added `_format_usage_snippet()` with 6 hardcoded rich templates (shell, llm, code, http, claude-code, write-file) + generic fallback for MCP/others. Inserted after outputs in `_format_node_section_enhanced()`. Covers `registry describe`, `registry discover`, MCP `registry_describe`, and the planner.
2. **`mcp.py`**: Added `.pflow.md` snippet to `pflow mcp info` output.
3. **`node_output_formatter.py`**: Added template reference examples to `registry run --structure` output.
4. **`workflow_list_formatter.py`**: Fixed empty case — was referencing gated planner (`pflow "your task"`), now shows `.pflow.md` file creation + save command.
5. **`registry.py`**: Removed dead `describe` command at line 366 (overridden by `describe_nodes` at line 867).

Fixed 3 test assertions for the workflow list empty case text change.

#### Round 2: Review fixes (6 issues)

Review identified 6 issues. All fixed:

| # | Issue | Fix |
|---|-------|-----|
| 1 | `_CODE_BLOCK_PARAMS` dead code | Removed — `_RICH_SNIPPETS` approach is better |
| 2 | `node_output_formatter.py` misleading `- response: ${step-name.response}` format | Removed entirely — teaches wrong pattern (left side should be consuming param, not source path). Existing "Use these paths" line is sufficient now that `registry describe` shows full snippets. |
| 3 | LLM snippet `- model: model-name` useless to agents | Removed — agents should use smart default per cli-agent-instructions.md |
| 4 | Generic MCP snippet: every string param gets `${previous-step.response}` | First param now gets literal `value` (typically a target like channel/path), subsequent get template refs |
| 5 | `mcp.py` snippet placeholder inconsistency with `context_builder.py` | Updated to match — first param literal, subsequent template refs |
| 6 | No tests for snippet generation | Added 6 tests in `TestUsageSnippets` class in `test_registry_describe.py` |

### Verification

- `make test`: **3608 passed, 516 skipped, 0 failed**
- `make check`: **all pass** (ruff, ruff-format, mypy, deptry clean)

Files modified:
- `src/pflow/planning/context_builder.py` (snippet function + rich templates)
- `src/pflow/cli/mcp.py` (mcp info snippet)
- `src/pflow/cli/registry.py` (dead code removal)
- `src/pflow/execution/formatters/node_output_formatter.py` (added then removed misleading reference)
- `src/pflow/execution/formatters/workflow_list_formatter.py` (empty case fix)
- `tests/test_cli/test_registry_describe.py` (6 new snippet tests)
- `tests/test_cli/test_workflow_commands.py` (2 assertion fixes)
- `tests/test_execution/formatters/test_workflow_list_formatter.py` (1 assertion fix)

Status: **All Task 107 work complete.** Phase 5 done (cli-agent-instructions.md + cli-basic-usage.md). Agent-friendly command output implemented and reviewed. 3608 passed, 516 skipped, 0 failed.

## Entry 21: User-facing docs update (docs/ directory)

### Full docs migration (Option A from plan)

All 12 files with JSON workflow examples in `docs/` were updated to use `.pflow.md` markdown format. ~40 JSON workflow syntax examples converted across node references, how-it-works guides, CLI references, and guides. Changelog entry was skipped per plan.

### Philosophical framing edits

Added "executable documentation" framing to two files:

1. **`docs/index.mdx`**: New "Workflows are documentation" section between "How pflow helps" and "Two ways to run workflows". Four sentences: `.pflow.md` is markdown that executes, renders as documentation on GitHub, runs as pipeline with pflow. No separate docs to maintain.

2. **`docs/guides/using-pflow.mdx`**: Reframed line 11 from "markdown files with a simple structure" to "readable documents that double as executable pipelines" — acknowledges readability and rendering everywhere (GitHub, editors, markdown viewers) without disrupting the "your agent handles it" message.

Files modified:
- `docs/index.mdx`
- `docs/guides/using-pflow.mdx`
- ~10 other docs files (JSON→markdown migration by prior session)

Status: All Task 107 work complete including user-facing documentation.

## Entry 22: Architecture folder audit + updates

### Investigation

Launched 3 parallel `pflow-codebase-searcher` agents to audit `architecture/` for stale JSON workflow references, outdated code patterns, and stale inline examples. Found ~40+ stale references across 8 files.

### Fixes (4 parallel forks)

| Fork | Files | Changes |
|------|-------|---------|
| A | `overview.md`, `pflow-pocketflow-integration-guide.md`, `core-concepts/shared-store.md` | 19 edits: format refs → .pflow.md, "JSON Workflows" section → "Markdown Workflows", planner → "gated", validation layer count fixed, IR context note on shared-store examples |
| B | `guides/json-workflows.md`, `reference/ir-schema.md` | Deprecation notice on json-workflows.md, IR clarifying note on ir-schema.md, all example file refs .json → .pflow.md, invalid examples updated to actual 8 markdown files |
| C | `reference/template-variables.md` | 5 CLI commands .json → .pflow.md, 6 repair gating notes, clarifying note about IR format vs authored format |
| D | `architecture/architecture.md`, `guides/mcp-guide.md` | New markdown_parser.py docs section, validation layers updated, repair gating strengthened, MCP parameter changes noted, metadata frontmatter documented, 2 workflow examples converted to .pflow.md |

### Verification

- `make test`: **3608 passed, 516 skipped, 0 failed**
- `make check`: **all pass** (ruff, ruff-format, mypy, deptry clean)

Files modified:
- `architecture/overview.md`
- `architecture/pflow-pocketflow-integration-guide.md`
- `architecture/core-concepts/shared-store.md`
- `architecture/guides/json-workflows.md`
- `architecture/guides/mcp-guide.md`
- `architecture/reference/ir-schema.md`
- `architecture/reference/template-variables.md`
- `architecture/architecture.md`

Status: Architecture folder fully updated. All Task 107 work complete.

## Entry 23: PR review fix — `_parse_warnings` schema violation

PR review (PR #80) identified that `_parse_warnings` was injected into `result.ir`, but the IR schema has `additionalProperties: False`. Any workflow with a near-miss section (e.g., `## Output`) would fail schema validation instead of producing a warning.

Fix: Added `warnings: list[str]` field to `MarkdownParseResult`. Warnings now live on the result object, not in the IR dict.

Files modified:
- `src/pflow/core/markdown_parser.py` (dataclass field + assignment)
- `tests/test_core/test_markdown_parser.py` (read from `result.warnings`)

- `make test`: 3609 passed, 516 skipped, 0 failed
- `make check`: all pass

Status: Fix complete. PR ready for merge.
