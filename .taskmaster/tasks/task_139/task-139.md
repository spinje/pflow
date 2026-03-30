# Task 139: CLI Acceptance Test Suite

## Description

Automated end-to-end tests that run real `.pflow.md` workflows through the CLI subprocess and verify exit codes, output structure, and key content. Replaces the manual smoke test baseline process that currently costs hours per structural task.

## Status

not started

## Priority

medium

## Problem

Every structural task (137, 138, 134) requires manually capturing smoke test baselines, running workflows by hand, and eyeballing output diffs. For Task 138 alone, we spent significant time:
- Capturing 14 manual baselines
- Discovering 4 HIGH-risk paths were missing from the initial set
- Recapturing MCP baselines after finding they contained unstable log noise

This cost repeats for every structural task. The current 4,671 tests are mostly unit tests with mocked execution — they verify individual components but not the assembled CLI pipeline. When we added 5 real `ExecutionService.execute_workflow()` tests (the first ever), they immediately revealed an exception contract bug the unit tests missed.

There is no automated way to verify "does `pflow examples/core/minimal.pflow.md` still produce the same output structure after a refactor?"

## Solution

Subprocess-based acceptance tests that run `uv run pflow ...` commands and assert on exit codes + output patterns. Each test exercises a real workflow file through the full CLI pipeline: argument parsing → resolution → validation → compilation → execution → output formatting.

Scope is CLI only. MCP service-layer tests exist separately (`test_execution_workflow.py`). MCP protocol-level testing (starting a server, sending JSON-RPC) is out of scope — complex to set up and MCP isn't the primary interface yet.

**Important**: This is a **research-then-implement** task. The test list in Requirements below is a starting point based on the Task 138 smoke test audit — it is NOT a complete inventory. The implementer must first systematically audit ALL CLI-facing behavior (flags, subcommands, output modes, error paths, feature combinations) to determine what acceptance coverage is actually needed. The 14 baselines from Task 138 were discovered to be incomplete mid-audit — the real surface area is likely larger than what's listed here. Expect the research phase to significantly reshape the test plan.

## Design Decisions

- **Subprocess, not CliRunner**: Use `subprocess.run(["uv", "run", "pflow", ...])` not Click's `CliRunner`. CliRunner runs in-process and doesn't test the actual CLI entry point, logging configuration, or exit code behavior. The existing subprocess test infrastructure (`uv_exe`, `prepared_subprocess_env` fixtures) already handles this.

- **Pattern assertions, not exact output matching**: Assert on stable structural markers (`"✓ Workflow completed"`, `"success": true`, exit code 0) rather than exact output strings. Timing, trace paths, execution IDs, and cache hit counts are unstable — never assert on them.

- **Use existing example workflows**: The `examples/` directory already has workflows covering all major paths. No need to create test-specific workflows except for error cases.

- **No MCP protocol tests**: MCP service-layer behavior is covered by `test_execution_workflow.py` (5 tests added in Task 138 pre-work). Full MCP protocol testing (server ↔ client over stdio) would be valuable in the future when MCP becomes a primary interface, but is disproportionate effort now.

## Dependencies

None. Can be implemented at any time. Most valuable before the next structural task (Task 135).

## Requirements

### Research Phase

Before writing any tests, systematically audit all CLI-facing behavior to determine what acceptance coverage is needed. Areas to investigate:
- All CLI entry points: file execution, named workflow, validate-only, registry run, subcommands
- All output modes: text, JSON, verbose combinations
- All flags and meaningful flag combinations
- Success paths AND error paths for each entry point
- Feature interactions: batch, nested workflows, branching, stdin, file references, `--only`, caching
- What existing example workflows in `examples/` are available as test fixtures

The 14 manual smoke test baselines in `.taskmaster/tasks/task_138/baseline/` provide a starting point — but they were discovered to be incomplete during the Task 138 audit. The research phase will likely uncover paths beyond what those baselines cover.

### Test Properties

- Tests run real CLI commands via subprocess against real workflow files
- Assertions on stable structural markers (exit codes, key output strings, valid JSON structure) — not on timing, trace paths, execution IDs, or cache state
- Tests must be isolated (no shared state, no side effects on the real filesystem)
- Tests must run in the normal `make test` suite without flakiness
- No new dependencies
- No MCP protocol testing (MCP service layer covered separately by `test_execution_workflow.py`)

## Implementation Notes

- Existing subprocess test infrastructure: `uv_exe` and `prepared_subprocess_env` fixtures in `tests/conftest.py`. Read these before starting.
- Existing subprocess test patterns: grep for `subprocess.run` in `tests/` to see how other tests handle this.
- Example workflows: `examples/` directory has workflows exercising most features.
- Read `tests/CLAUDE.md` for test infrastructure documentation, markers, and gotchas.

## Verification

- All ~15-20 tests pass in the normal `make test` run
- Each test completes in < 5 seconds
- Tests catch a real regression when a known-breaking change is applied (verify by temporarily breaking one path)
- Tests are stable across runs (no flaky assertions on timing or cache state)

## References

- Task 138 smoke test baselines: `.taskmaster/tasks/task_138/baseline/` (14 files — these are the manual versions of what this task automates)
- Task 138 MCP service tests: `tests/test_mcp_server/test_execution_workflow.py` (5 tests covering MCP service layer)
- Existing subprocess fixtures: `tests/conftest.py` (`uv_exe`, `prepared_subprocess_env`)
- Existing subprocess tests: grep for `subprocess.run` in `tests/` for patterns
- Task 121 (Workflow Testability) — this task is a focused subset of 121's broader scope
- Example workflows: `examples/` directory
