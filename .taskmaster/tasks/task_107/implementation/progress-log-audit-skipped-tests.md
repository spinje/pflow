# Audit: Skipped Tests Verification

## Summary

**Total tests: 4232** (1 failed, 3596 passed, 635 skipped)

**All 635 skipped tests are legitimate.** Zero suspicious skips found.

## Breakdown by Category

### 1. Legitimate gating — Task 107 (Decision 26): 572 tests

All planner/repair tests, gated because their prompts assume JSON workflow format. Re-enable after prompt rewrite.

**Gating mechanism:**
- `tests/test_planning/conftest.py` — autouse fixture `skip_planning_tests()` that calls `pytest.skip("Gated pending markdown format migration (Task 107)")`. This covers ALL tests in `tests/test_planning/` and its subdirectories.
- Individual `pytestmark = pytest.mark.skip(...)` on:
  - `tests/test_cli/test_auto_repair_flag.py` (5 tests)
  - `tests/test_cli/test_cache_planner_flag.py` (4 tests)
  - `tests/test_cli/test_repair_save_handlers.py` (19 tests)
  - `tests/test_cli/test_repaired_workflow_save.py` (7 tests)
  - `tests/test_integration/test_context_builder_integration.py` (12 tests)
  - `tests/test_integration/test_context_builder_performance.py` (8 tests)
  - `tests/test_core/test_workflow_manager_update_ir.py` (9 tests) — tests `update_ir()` which is dead code (only caller was repair, now gated)
- Individual `@pytest.mark.skip(...)` on:
  - `tests/test_cli/test_main.py::test_oversized_workflow_input` (1 test) — size validation is in planner path
  - `tests/test_cli/test_planner_input_validation.py::test_quoted_prompt_attempts_planner` (1 test) — planner invocation test

**Verification:** Every skip reason contains "Gated pending markdown format migration (Task 107)" or "update_ir gated pending markdown format migration (Task 107)". All correspond exactly to the gating plan in the implementation plan (Phase 0.2, Decision D9).

### 2. Pre-existing — LLM integration tests: 63 tests

Tests requiring real API keys, skipped unless `RUN_LLM_TESTS=1` environment variable is set. These existed before Task 107.

**Files:**
- `tests/test_nodes/test_llm/test_llm_integration.py` (9 tests) — "Set RUN_LLM_TESTS=1 to run real LLM tests"
- `tests/test_planning/llm/integration/` (5 files, ~17 tests) — "Skipping LLM tests. Set RUN_LLM_TESTS=1 to run."
- `tests/test_planning/llm/prompts/` (7 files, ~37 tests) — "Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"

**Verification:** All use `pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), ...)`. Note: the planning LLM tests are doubly-skipped — once by the conftest autouse fixture (Task 107 gating), and once by the LLM test skip. Even if the Task 107 gating were removed, these would still skip without the env var.

### 3. Pre-existing — Platform-specific: 0 at current count

A few tests have `@pytest.mark.skipif(platform.system() == "Windows", ...)` but these don't trigger on macOS (the current platform):
- `tests/test_integration/test_sigpipe_regression.py:399`
- `tests/test_nodes/test_shell/test_shell.py:539`
- `tests/test_nodes/test_shell/test_shell_sigpipe.py:174,261`
- `tests/test_cli/test_dual_mode_stdin.py:302,337,475,540,596`

### 4. Suspicious skips: NONE

**Grep for skip markers across all test files** found zero skip annotations that:
- Were added by Task 107 forks outside of planner/repair files
- Have vague or missing reasons
- Skip core functionality tests (workflow execution, save, load, validation)

No fork took a shortcut by skipping a test instead of migrating it.

## One Failing Test (Not Task 107 related)

`tests/test_runtime/test_settings_env_integration.py::test_e2e_realistic_api_key_scenario` — fails because the test expects a mock Replicate API token (`r8_test_token_xyz`) but the user's real environment has a different token set. This is a pre-existing environment-specific issue, not caused by the markdown migration.

## Conclusion

All 635 skipped tests are accounted for:
- **572** = Task 107 planner/repair gating (Decision 26) — intentional, documented
- **63** = Pre-existing LLM API key requirement — unrelated to Task 107
- **0** = Suspicious or incorrectly skipped
