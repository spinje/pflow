# Braindump: CLI Acceptance Test Suite (Task 139)

## Where I Am

Task 139 was created during pre-implementation prep for Task 138 (Shared Execution Pipeline). The task spec is written and comprehensive. No implementation started. This braindump captures the context that led to the task and gotchas the implementer will hit.

## User's Mental Model

The user thinks about testing in terms of **reducing the manual verification tax on structural tasks**. Their exact framing: *"What if I had a comprehensive 'manual testing suite' that would actually run pflow.md files from the cli... and verify the results."* And: *"remove strain for manual regression tests for each new feature."*

They had considered this before but hadn't pulled the trigger. What pushed it over the line was the Task 138 audit experience — we spent significant conversation time:
1. Discovering the original 10 smoke test baselines missed 4 HIGH-risk paths
2. Manually capturing those baselines
3. Recapturing MCP baselines after finding they contained unstable log noise
4. Finding that `ExecutionService.execute_workflow()` had zero test coverage
5. Writing 5 MCP service-layer tests that immediately found an exception contract bug

The user's reaction to learning MCP had zero execution test coverage was pointed: *"and how are we 'testing' this for mcp?"* — they clearly see the gap between "4,671 tests pass" and "does the thing actually work end-to-end."

The user explicitly asked whether this counts as "integration tests" or something else — they care about where it fits in the testing taxonomy. I called them "acceptance tests" which felt right: they verify the user/agent-facing contract, not internal implementation.

**Unstated priority**: The user wants pflow to be confidently modifiable by AI agents. Every structural task (137, 138, 134, 135) requires understanding whether it broke anything visible. The acceptance suite makes that question answerable automatically instead of manually.

## Key Insights

### The 14 baselines are a starting point, not the answer

The 14 smoke test baselines in `.taskmaster/tasks/task_138/baseline/` show the scenarios we identified during the Task 138 audit. We started with 10 and discovered 4 more were missing mid-audit. The real surface area is likely larger — the implementing agent should treat these as inspiration for research, not as a complete spec.

MCP baselines (13, 14) are already covered by `test_execution_workflow.py` (service-layer tests). The CLI baselines map roughly to subprocess tests but the agent should discover the right set through their own audit.

### Gotchas discovered during Task 138 baseline work

- Some example workflows have side effects (e.g., writing files to CWD) or external dependencies (HTTP calls). The implementer needs to investigate each example workflow before using it as a test fixture.
- `prepared_subprocess_env` isolates HOME but the implementer should verify what it does and doesn't isolate (CWD, network, logging).
- MCP baselines contained unstable INFO log lines that made diffs useless — we had to recapture with logging suppressed. CLI subprocess tests may have similar stability concerns with verbose output, trace file paths, timing, and cache hit counts.

### `prepared_subprocess_env` and LLM mocking

NEEDS VERIFICATION: Does `prepared_subprocess_env` set `PYTEST_CURRENT_TEST` in the subprocess environment? If not, the subprocess might attempt real LLM calls. The `mock_llm_calls` autouse fixture only works in-process (it patches `llm.get_model`). For subprocess tests, the guard in `src/pflow/core/llm_config.py` checks `os.getenv("PYTEST_CURRENT_TEST")` — if this env var isn't forwarded to the subprocess, LLM nodes would try to call real APIs.

For the acceptance suite, this shouldn't matter because none of the test workflows use LLM nodes. But if anyone adds an LLM workflow test later, they'll hit this.

## Assumptions & Uncertainties

ASSUMPTION: All example workflows in `examples/` are stable and don't depend on external state beyond what `prepared_subprocess_env` provides. Some might depend on network access (HTTP nodes) or specific env vars.

ASSUMPTION: The `uv_exe` fixture correctly finds `uv` in all CI/development environments. If it can't find `uv`, the tests skip — this is correct behavior.

UNCLEAR: Whether `--verbose` output is stable enough to assert on. Verbose mode shows node-level execution details that might vary with caching, timing, etc. Might be better to just assert exit 0 for verbose.

UNCLEAR: How to test `--only <node>` — need to know a valid node ID from one of the example workflows. The implementer should read `examples/core/conditional-branching.pflow.md` and pick a node ID.

NEEDS VERIFICATION: Whether the `--no-cache` flag produces meaningfully different output from a normal run. If the only difference is "cached" vs "executed" in the node status, the test just needs exit 0.

## Unexplored Territory

UNEXPLORED: **Test ordering and parallelism.** These subprocess tests are slower than unit tests (~0.3-1s each). With `pytest-xdist` (4 workers), they'll run in parallel. File-writing side effects (like `hello.txt`) could cause race conditions if multiple tests share CWD. Using `cwd=tmp_path` per test avoids this.

UNEXPLORED: **CI environment differences.** Subprocess tests depend on the actual `pflow` CLI being installed and runnable via `uv run pflow`. In CI, `uv` and the project's virtualenv must be available. The existing subprocess tests presumably handle this, but it's worth checking CI configuration.

CONSIDER: **A smoke test runner script.** The user originally asked about a "manual testing suite." A script that runs all acceptance scenarios and produces a diff-friendly report might be valuable alongside the pytest tests — for when a developer wants to eyeball changes before committing. But this is separate from the pytest-based acceptance suite.

CONSIDER: **Whether to mark tests as `@pytest.mark.serial` or `@pytest.mark.integration`.** The existing test markers include `serial` (must run sequentially) and `integration` (spawns subprocesses). These tests should be `integration`. Whether they need `serial` depends on whether they have shared side effects (see CWD file-writing above).

MIGHT MATTER: **Test execution time budget.** The current suite runs in ~9s (4,671 tests, 4 workers). Adding ~16 subprocess tests at ~0.5s each adds ~2s of wall time (parallelized). This is fine, but if any test involves network calls (batch HTTP), it could dominate.

MIGHT MATTER: **Validate-only JSON output shape.** We discovered during Task 138 audit that the current `--validate-only --output-format json` output is missing warnings (existing bug). The acceptance test for this path documents the current (buggy) behavior. When Task 138 Phase 1 fixes it, the test would need updating to include warnings. This is correct — the test flags the change.

## What I'd Tell Myself

1. **Don't skip the research phase.** We missed 4 HIGH-risk paths in our first pass of 10 baselines during the Task 138 audit. "We think we covered everything" was wrong. The implementing agent needs to audit the CLI surface area systematically before deciding what to test.

2. **The 14 baselines are examples of scenarios, not ground truth.** They show the kind of thing that needs testing. They don't define the complete set. The implementing agent should discover the right set through their own audit.

3. **Get the subprocess infrastructure right first.** Before writing many tests, make sure the isolation, assertion patterns, and stability approach work on a few simple cases.

## Open Threads

1. **MCP protocol testing** — the user explicitly asked about this ("maybe mcp as well but im not sure how to set this up"). Deferred for now. When MCP becomes a primary interface, protocol-level tests (start server, send JSON-RPC, verify responses) would be the next testing investment. The service-layer tests (`test_execution_workflow.py`) bridge the gap for now.

2. **Relationship to Task 121 (Workflow Testability)** — Task 139 is a focused subset of 121's broader scope. 121 includes testing workflows as a user feature (testing node outputs, assertions, expected values). 139 is specifically about testing the pflow CLI itself. They're complementary but distinct.

## Relevant Files & References

- **Baselines (examples, not spec)**: `.taskmaster/tasks/task_138/baseline/*.txt` — 14 files showing example scenario outputs from Task 138 audit
- **Subprocess fixtures**: `tests/conftest.py` — `uv_exe` (line ~varies), `prepared_subprocess_env` (search for it)
- **Existing subprocess tests**: Grep for `subprocess.run` in `tests/` — sparse but patterns exist
- **MCP service-layer tests**: `tests/test_mcp_server/test_execution_workflow.py` — 5 tests added during Task 138 prep, covers MCP separately
- **Example workflows**: `examples/` directory — `core/`, `nested/`, `file-references/`, `invalid/`
- **Test CLAUDE.md**: `tests/CLAUDE.md` — subprocess test fixtures docs, markers, gotchas
- **Task 138 progress log**: `.taskmaster/tasks/task_138/implementation/progress-log.md` — documents the audit that led to this task

## For the Next Agent

**Start by**: Reading the 14 baseline files in `.taskmaster/tasks/task_138/baseline/`. Each one maps to a test. Then read `tests/conftest.py` to understand `prepared_subprocess_env` and `uv_exe`.

**Don't bother with**: MCP protocol testing, creating new example workflows (use existing ones), or testing internal implementation details. This is a surface-level contract test suite.

**The user cares most about**: Reducing the manual verification tax on structural tasks. These tests should be reliable, fast, and stable — not comprehensive. 15-20 tests that catch "the CLI is broken" is the goal, not 100 tests for every edge case.

**Watch out for**: The batch example workflow (might need network), the minimal workflow (writes `hello.txt` to CWD), and the saved workflow test (needs isolated workflows directory setup).

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
