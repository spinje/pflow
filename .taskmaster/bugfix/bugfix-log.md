<!-- ===== BUGFIX ENTRY START ===== -->

## [BUGFIX] Test suite reset user registry and erased MCP tools — 2025-09-01

Meta:
- id: BF-20250901-test-registry-reset
- area: tests
- severity: data-loss
- status: fixed
- versions: uncommitted (working tree)
- affects: all test runs, user's ~/.pflow/registry.json, synced MCP tools
- owner: ai-agent
- links: tests/conftest.py, tests/test_integration/test_metrics_integration.
- session_id: 8185f1f8-8b2d-4e14-b9b6-44ed2a5cdafb

Summary:
- Problem: Running `make test` erased all MCP tool registrations from user's registry.
- Root cause: Autouse test fixtures called `Registry()` without path (defaulting to `~/.pflow/registry.json`), then `update_from_scanner()` which completely replaces registry contents.
- Fix: Added global test isolation fixture that patches Registry/SettingsManager/MCPServerManager to use temp directories; removed problematic autouse fixtures.

Repro:
- Steps:
  1) Have MCP tools synced in registry
  2) Run test suite
  3) Check registry after tests
- Commands:
  ```bash
  # Before fix - check MCP tools exist
  grep -c "mcp-slack" ~/.pflow/registry.json  # Output: 8

  # Run tests
  make test

  # After tests - MCP tools gone
  grep -c "mcp-slack" ~/.pflow/registry.json  # Output: 0
  ```
- Expected vs actual:
  - Expected: User's registry unchanged after tests
  - Actual: MCP tool registrations erased, only core nodes remain

Implementation:
- Changed files:
  - `tests/conftest.py`: Added `isolate_pflow_config` fixture with recursion guard
  - `tests/test_cli/test_dual_mode_stdin.py`: Removed autouse fixture, fixed tautological assertions
  - `tests/test_cli/test_workflow_save.py`: Removed autouse fixture, added pipe test
  - `tests/test_core/test_workflow_validator.py`: Removed autouse fixture, updated tests
  - `tests/test_integration/test_workflow_outputs_namespaced.py`: Removed autouse fixture
  - `tests/test_integration/test_metrics_integration.py`: Added `exist_ok=True`, fixed variable shadowing
- Key edits:
  - Global fixture patches init methods to use temp paths
  - Graceful degradation: Registry required (pytest.fail), others optional (None if missing)
  - Constructor signatures preserved with `*args, **kwargs` for future compatibility
  - Recursion guard with `_initializing` set prevents infinite loop
  - Reuses Registry's existing `_auto_discover_core_nodes()` logic
  - Directory creation uses `parents=True, exist_ok=True` to prevent conflicts
- Tests: All originally problematic tests pass, full suite passes (1679 tests), added pipe test

Verification:
- Manual:
  ```bash
  # After fix - MCP tools preserved
  grep -c "mcp-slack" ~/.pflow/registry.json  # Output: 8 (preserved)

  # Tests still pass
  uv run pytest tests/test_cli/test_dual_mode_stdin.py  # PASSED
  ```
- CI: Full test suite passes without modifying user registry

Risks & rollbacks:
- Risk flags: Test isolation, auto-discovery logic, fixture initialization order
- Rollback plan: Remove `isolate_pflow_config` fixture, revert to explicit temp paths in individual tests

Lessons & heuristics:
- Lessons learned:
  - `Registry.update_from_scanner()` completely replaces registry, doesn't merge
  - Autouse fixtures are dangerous when they modify global state
  - Multiple fixtures creating same directory need `exist_ok=True`
  - Reuse existing code logic (Registry's auto-discovery) rather than duplicating in tests
  - Monkeypatch patches must preserve signatures with `*args, **kwargs` for future compatibility
  - Use graceful degradation: fail hard only on required imports, skip optional ones
  - Test assertions should check behavior, not rely on tautologies (avoid `or exit_code == 0`)
- Heuristics to detect recurrence:
  - Grep for `Registry()` without explicit path in test files
  - Check for autouse fixtures that might modify user files
  - Monitor `~/.pflow/` modification times during test runs
  - Look for patches without `*args, **kwargs` signature preservation
  - Search for tautological assertions that always pass
- Related pitfalls: Test isolation is critical for user data safety

Follow-ups:
- Consider making Registry.update_from_scanner() merge instead of replace
- Add warning if Registry detects it's using default path in test environment

<!-- ===== BUGFIX ENTRY END ===== -->

<!-- ===== BUGFIX ENTRY START ===== -->

## [BUGFIX] Test slowdown from per-test isolation and uv subprocess init; brittle CLI stdout assertions — 2025-09-02

Meta:
- id: BF-20250902-test-slowdown-cli-stdout
- area: tests, cli
- severity: perf, reliability
- status: fixed
- versions: uncommitted (working tree)
- affects: full test suite runtime, CLI subprocess tests, shell-node behavioral expectations
- owner: ai-agent
- links: tests/conftest.py, tests/test_cli/test_dual_mode_stdin.py, tests/test_cli/test_workflow_save.py, tests/test_nodes/test_shell/test_improved_behavior.py, tests/test_nodes/test_shell/test_auto_handling.py

Summary:
- Problems:
  - The suite regressed from ~7s to ~11–12s after adding ~100–200 tests and a per-test isolation fixture. A portion of the increase came from uv-based child process startup and subprocess registry initialization in CLI tests.
  - A CLI test asserted that stdout must be non-empty on success. With the updated CLI behavior (and aligned with shell-node principles), empty stdout is a valid outcome for a successful workflow.
- Root causes:
  - Autouse function-scoped isolation runs on every test and adds small overhead that aggregates at scale.
  - CLI subprocess tests invoked `uv run pflow` and called `pflow registry list` just to initialize a registry, adding ~0.2–0.3s per affected test.
  - Test over-specification: using stdout content to infer success rather than exit code.
- Fixes:
  - Replaced `uv run pflow` with `sys.executable -m pflow.cli.main_wrapper` to remove uv startup overhead while preserving true CLI routing.
  - Wrote a precomputed registry file directly in the subprocess HOME instead of spawning a child process to run `pflow registry list`.
  - Adjusted assertion to accept empty stdout when exit code is 0 in real CLI test; mirrors shell-node principle that "empty results are valid".
  - Reduced a 0.3s sleep to a ≤100ms polling loop in a shell timeout test.

Repro:
- Steps:
  1) Run `uv run pytest --durations=50` before changes; note many top slots are uv-based CLI tests and ~0.3s sleep.
  2) CLI tests rely on `uv run pflow` and subprocess registry init; suite totals ~12.17s.
  3) A CLI subprocess test fails if stdout is empty despite exit code 0.
- Expected vs actual:
  - Expected: fast, deterministic tests; successful workflows indicated by exit code 0; empty stdout allowed.
  - Actual: slower suite due to uv startup per test and unnecessary subprocess registry init; brittle stdout assertion.

Implementation:
- Changed files:
  - `tests/conftest.py`:
    - Added `precomputed_core_registry_nodes` (session-scoped) using Registry internals in a test-only context.
    - Updated `_create_registry_patcher` to write precomputed nodes on first load for test registries.
    - Reworked `prepared_subprocess_env` (module-scoped) to write a minimal registry JSON directly and set HOME/vars; removed uv-based init.
  - `tests/test_cli/test_dual_mode_stdin.py` and `tests/test_cli/test_workflow_save.py`:
    - Switched to `sys.executable -m pflow.cli.main_wrapper` for subprocess execution.
    - Relaxed assertion to rely on `returncode == 0`; empty stdout is valid. Kept optional verbose pattern when specific output is required.
  - `tests/test_nodes/test_shell/test_improved_behavior.py`:
    - Replaced `time.sleep(0.3)` with short polling loop to confirm termination.
  - `tests/test_nodes/test_shell/test_auto_handling.py`:
    - Security lint: restored permissions with `0o700` instead of `0o755` during cleanup.

Verification:
- Before: 1736 passed, 3 skipped in 12.17s (local); CLI suite ~1.9s.
- After: 1761 passed, 3 skipped in 10.04s; CLI suite ~1.17s. `make check` fully green (ruff, mypy, deptry, mkdocs).

Risks & rollbacks:
- Risk flags: relying on `main_wrapper` as the CLI entry point for subprocess tests; precomputing registry nodes relies on stable Registry APIs.
- Rollback plan: revert to `uv run pflow` and subprocess `registry list` if CLI invocation changes; revert registry precompute to on-demand scanning if APIs change.

Lessons & heuristics:
- Lessons learned:
  - Small per-test work adds up across large suites; prefer session/module scoping and reuse whenever safe.
  - Success should be asserted via exit codes; "empty results are valid" for both shell flows and CLI workflows.
  - Avoid bootstrapping child processes just to initialize state; write known-good minimal files directly in tests.
  - When a CLI has a wrapper entry point, tests should invoke the wrapper module to match real routing behavior.
- Heuristics to detect recurrence:
  - Grep for `subprocess.run([..., "uv", "run", "pflow"` in tests; replace with `sys.executable -m pflow.cli.main_wrapper` unless uv semantics are required.
  - Grep for `registry list` used as a side-effect for test setup.
  - Flag tests that assert non-empty stdout on success without requiring verbose/debug output.
  - Track new `time.sleep(...)` usages > 50ms in tests.

Follow-ups:
- Consider parametrizing similar shell tests to reduce total subprocess count.
- Provide a fast Make target that excludes slow real-subprocess tests for local iteration while keeping them in CI.

<!-- ===== BUGFIX ENTRY END ===== -->


## [BUGFIX] Prevent CLI hangs when piped; resolve declared outputs on print — 2025-09-01

Meta:
- id: BF-20250901-tty-pipes-outputs
- area: cli
- severity: hang
- status: fixed
- versions: uncommitted (working tree)
- affects: pipelines, stdout-piped, --output-format json, planner success path, namespaced outputs
- owner: ai-agent
- links:

Summary:
- Problem: `pflow ... | jq ...` could hang; declared outputs sometimes appeared missing.
- Root cause: Prompt gating only checked stdin TTY (stdout piped still prompted); outputs needed a mapping pass when not pre-populated.
- Fix: Prompt only when stdin AND stdout are TTYs; call `populate_declared_outputs(...)` as a fallback in CLI before printing.

Repro:
- Steps:
  1) Run with stdout piped
- Commands:
  ```bash
  uv run pflow --output-format json "say hello" 2>/dev/null | jq -r '.total_cost_usd'
  ```
- Expected vs actual:
  - Expected: JSON printed, jq extracts a number (or null)
  - Actual (pre-fix): hang (prompt waiting on a non-interactive pipeline)

Implementation:
- Changed files: `src/pflow/cli/main.py`
  - Prompt gating: show save prompt only when `sys.stdin.isatty() and sys.stdout.isatty()`
  - Output handling: in `_try_declared_outputs`, if root keys not present, call `pflow.runtime.output_resolver.populate_declared_outputs(shared, workflow_ir)` then re-check
- Tests: manual verification; consider subprocess/pty e2e for pipe behavior

Verification:
- Manual:
  ```bash
  # File-based, no LLM required
  cat > /tmp/echo.json <<'EOF'
  {
    "ir_version": "0.1.0",
    "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "hello"}}],
    "edges": [],
    "outputs": {"result": {"source": "${echo1.echo}"}}
  }
  EOF

  uv run pflow --output-format json --file /tmp/echo.json 2>/dev/null | jq -r '.result'
  ```
  Output: `hello`
- CI: existing suites remain green

Risks & rollbacks:
- Risk flags: TTY detection; SIGPIPE/EPIPE behavior; namespacing vs root output expectations
- Rollback plan: revert the two hunks in `src/pflow/cli/main.py` (prompt gating and declared output fallback)

Lessons & heuristics:
- Lessons learned:
  - “Interactive” means stdin AND stdout are TTYs; gate prompts on both.
  - With namespacing enabled, declared outputs should include `source` and may require population.
- Heuristics to detect recurrence:
  - Grep for single-ended `isatty()` checks in CLI code paths that might prompt.
  - If `.result` is unexpectedly empty in JSON mode, check `outputs[*].source` and ensure population occurs.
- Related pitfalls: `.taskmaster/knowledge/pitfalls.md#interactive-prompts-in-pipelines-cause-hangs`, `.taskmaster/knowledge/pitfalls.md#declared-outputs-require-explicit-source-when-namespacing-is-on`

Follow-ups:
- Add subprocess/pty e2e tests to simulate real TTY/pipe behavior

<!-- ===== BUGFIX ENTRY END ===== -->
