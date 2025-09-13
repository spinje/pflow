<!-- ===== BUGFIX ENTRY START ===== -->

## [BUGFIX] Fix stdin hang when piped through grep in non-TTY environments — 2025-01-12

Meta:
- id: BF-20250112-stdin-hang-nontty-grep
- area: cli
- severity: hang
- status: fixed
- versions: uncommitted (working tree)
- affects: Claude Code environment, Docker containers, CI pipelines, piped execution
- owner: ai-agent
- links: src/pflow/core/shell_integration.py, tests/test_core/test_stdin_no_hang.py
- session_id: 6c1662ce-2378-4ed8-aa17-2a981d21d1f0

Summary:
- Problem: `pflow --trace workflow.json 2>&1 | grep "pattern"` hung indefinitely in Claude Code
- Root cause: stdin.read() blocked waiting for EOF when stdin was non-TTY but had no actual data
- Fix: Use select.select() with 0 timeout to check if stdin has data before attempting to read

Repro:
- Steps:
  1) Create a simple workflow JSON file
  2) Run pflow with output piped through grep
  3) Command hangs indefinitely
- Commands:
  ```bash
  cat > /tmp/test.json << 'EOF'
  {
    "ir_version": "0.1.0",
    "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo hello"}}],
    "edges": []
  }
  EOF

  # This hangs before fix:
  uv run pflow --trace /tmp/test.json 2>&1 | grep "hello"
  ```
- Expected vs actual:
  - Expected: Command completes, grep filters output
  - Actual: Command hangs indefinitely waiting for stdin input

Implementation:
- Changed files:
  - `src/pflow/core/shell_integration.py`:
    - Added `stdin_has_data()` function using select.select() to check stdin readiness
    - Updated `read_stdin()` to call `stdin_has_data()` instead of `detect_stdin()`
    - Updated `read_stdin_enhanced()` similarly
  - `src/pflow/core/__init__.py`: Export new `stdin_has_data` function
  - `tests/test_core/test_stdin_no_hang.py`: Added comprehensive tests
- Key edits:
  - `stdin_has_data()` uses `select.select([sys.stdin], [], [], 0)` for non-blocking check
  - Graceful fallback if select() fails on some platforms
  - No longer assumes non-TTY means stdin has data
- Tests: 4 new tests covering hang prevention, function behavior, and grep integration

Verification:
- Manual:
  ```bash
  # After fix - completes immediately:
  uv run pflow --trace /tmp/test.json 2>&1 | grep "hello"
  # Output: hello

  # Test with actual stdin data still works:
  echo "input data" | uv run pflow /tmp/test.json
  ```
- CI: All 1960 tests pass, make check passes

Risks & rollbacks:
- Risk flags: select() behavior varies by platform; stdin detection in different environments
- Rollback plan: Revert stdin_has_data() function, restore direct detect_stdin() calls

Lessons & heuristics:
- Lessons learned:
  - Claude Code environment has stdin/stdout always non-TTY even when not piped
  - sys.stdin.read() blocks indefinitely waiting for EOF if no data available
  - select.select() with 0 timeout provides non-blocking stdin readiness check
  - Test subprocess commands need to account for grep exit codes (0=found, 1=not found)
- Heuristics to detect recurrence:
  - Look for sys.stdin.read() without prior data availability check
  - Watch for hangs when `| grep` or `| jq` used with pflow
  - Check for assumptions that non-TTY always means piped data
- Related pitfalls: Similar issues could affect any CLI tool in containerized/virtualized environments

Follow-ups:
- Consider Windows compatibility testing (select() behavior differs)
- Document behavior in non-standard terminal environments

<!-- ===== BUGFIX ENTRY END ===== -->

<!-- ===== BUGFIX ENTRY START ===== -->

## [BUGFIX] Workflows not saving with json output or -p flag; Clean JSON output for CI/CD — 2025-09-12

Meta:
- id: BF-20250912-workflow-save-json-output
- area: cli
- severity: ux
- status: fixed
- versions: uncommitted (working tree)
- affects: --output-format json, -p flag, piped output, workflow persistence, CI/CD pipelines
- owner: ai-agent
- links: src/pflow/cli/main.py, tests/test_cli/test_workflow_save.py, tests/test_integration/test_metrics_integration.py
- session_id: 92d242fc-23c6-4659-ab65-f81a376bf7a8

Summary:
- Problem: Workflows never saved in non-interactive modes; JSON output polluted with stderr messages; no workflow metadata in output
- Root cause: OutputController.should_show_prompts() returned False for non-interactive modes; stderr messages broke JSON parsers
- Fix: Added --save/--no-save flag with auto-save; unified JSON structure with workflow metadata; eliminated stderr in JSON/p modes

Repro:
- Steps:
  1) Generate workflow with json output or -p flag
  2) Check if workflow was saved and JSON is clean
- Commands:
  ```bash
  echo "Test" | uv run pflow --output-format json "write hello to file.txt" 2>&1 | jq .
  # Before: Parse error due to stderr messages mixed with JSON
  ls ~/.pflow/workflows/*.json  # No new workflow saved
  ```
- Expected vs actual:
  - Expected: Clean JSON output, workflow saved automatically
  - Actual: Mixed stderr/stdout broke parsers, no save

Implementation:
- Changed files:
  - `src/pflow/cli/main.py`:
    - Added --save/--no-save flag (default: --save)
    - Created unified JSON structure with success/error status
    - Added workflow metadata to JSON output (name, action: created/reused/unsaved)
    - Created helper functions to eliminate code duplication:
      - `_get_default_workflow_metadata()`: Default unsaved metadata
      - `_create_workflow_metadata()`: Factory with validation
      - `_extract_workflow_node_count()`: Extract only workflow nodes
    - Modified error handling to output JSON in JSON mode
    - Suppressed all stderr output in JSON/-p modes
    - Fixed UserFriendlyError attribute access (title/explanation/suggestions)
  - `tests/test_cli/test_workflow_save.py`:
    - Updated tests for new save behavior
  - `tests/test_integration/test_metrics_integration.py`:
    - Updated assertions for new JSON structure
- Key edits:
  - JSON always includes `"success"`, `"result"`, `"workflow"` keys
  - Metrics at top level: `"duration_ms"`, `"total_cost_usd"`, `"nodes_executed"`
  - `nodes_executed` only counts workflow nodes (excludes planner nodes)
  - Error output uses same JSON structure with `"error"` object
  - `-p` flag outputs ONLY result value (no wrapper/metadata)

Verification:
- Manual:
  ```bash
  # Clean JSON output with workflow metadata
  echo "Test" | uv run pflow --output-format json "write hello to test.txt" 2>/dev/null | jq .
  {
    "success": true,
    "result": {...},
    "workflow": {"name": "file-writer", "action": "reused"},
    "duration_ms": 123.45,
    "total_cost_usd": 0.001,
    "nodes_executed": 1  // Only workflow nodes, not planner
  }

  # Clean -p output (just result)
  echo "Test" | uv run pflow -p "write hello to test.txt"
  Successfully wrote to '/path/to/test.txt'
  ```
- CI: All 1956 tests pass; make check passes (fixed mypy and ruff issues)

Risks & rollbacks:
- Risk flags: Breaking change to JSON output structure (but no users yet)
- Rollback plan: Revert JSON structure changes, restore old metrics placement

Lessons & heuristics:
- Lessons learned:
  - CI/CD pipelines need pure stdout (no stderr pollution)
  - JSON output must be consistent for success and error cases
  - Code duplication leads to maintenance issues - use helper functions
  - Type annotations catch bugs early (mypy found attribute misuse)
  - UserFriendlyError uses title/explanation/suggestions, not what/why/how
  - Metrics should distinguish workflow vs planner node counts
  - Test expectations should match production (removed unused found_any variable)
- Heuristics to detect recurrence:
  - Test JSON output with `2>&1 | jq .` to catch stderr pollution
  - Always check both success and error JSON structures
  - Run `make check` to catch type and linting issues early
  - Look for repeated code patterns that should be helper functions
  - Watch for unused variables after refactoring (ruff catches these)
- Related pitfalls: Mixed stdout/stderr breaks parsers; inconsistent JSON structures; type mismatches

Follow-ups:
- Document JSON output schema in API documentation
- Consider versioning JSON output format for future compatibility
- Add integration tests for CI/CD pipeline scenarios

<!-- ===== BUGFIX ENTRY END ===== -->

<!-- ===== BUGFIX ENTRY START ===== -->

## [BUGFIX] Registry auto-discovery fails; MCP node exposed in listings — 2025-01-12

Meta:
- id: BF-20250112-registry-autodiscovery-mcp
- area: cli|registry
- severity: ux
- status: fixed
- versions: uncommitted (working tree)
- affects: CLI workflow execution, registry initialization, node listings
- owner: ai-agent
- links: src/pflow/cli/main.py, src/pflow/core/settings.py, tests/test_integration/test_e2e_workflow.py
- session_id: 7c553001-0781-4903-aedc-cec1cd5404b2

Summary:
- Problem: Registry deletion caused outdated error; internal MCPNode appeared in user listings
- Root cause: `_ensure_registry_loaded()` checked file existence before `Registry.load()` auto-discovery; MCPNode in nodes/mcp/ was auto-scanned
- Fix: Call `Registry.load()` directly for auto-discovery; add "mcp" to test node exclusion list

Repro:
- Steps:
  1) Delete ~/.pflow/registry.json
  2) Run any pflow command requiring registry
- Commands:
  ```bash
  mv ~/.pflow/registry.json ~/.pflow/registry.json.backup
  uv run pflow registry list
  ```
- Expected vs actual:
  - Expected: Auto-discovers nodes and lists them
  - Actual: "Error - Node registry not found. Run 'python scripts/populate_registry.py'" (script doesn't exist)

Implementation:
- Changed files:
  - `src/pflow/cli/main.py`: Updated `_ensure_registry_loaded()` to call `Registry.load()` directly
  - `src/pflow/core/settings.py`: Added "mcp" to `known_test_names` set in `_is_test_node()`
  - `tests/test_integration/test_e2e_workflow.py`: Replaced error test with auto-discovery test
- Key edits:
  - Removed premature `registry.registry_path.exists()` check
  - Added try/except around `Registry.load()` with helpful error messages
  - Leveraged existing test node exclusion pattern for MCPNode
- Tests: Added `test_registry_auto_discovery` and `test_registry_load_error`

Verification:
- Manual:
  ```bash
  # Test auto-discovery
  mv ~/.pflow/registry.json ~/.pflow/registry.json.backup
  echo '{"ir_version": "0.1.0", "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo Hello"}}], "edges": []}' > /tmp/test.json
  uv run pflow /tmp/test.json
  ```
  Output: `Hello`
- CI: All 1952 tests pass, including new tests

Risks & rollbacks:
- Risk flags: Registry auto-discovery logic, test node classification
- Rollback plan: Revert `_ensure_registry_loaded()` changes; remove "mcp" from test node list

Lessons & heuristics:
- Lessons learned:
  - Framework methods should handle their own initialization (Registry.load() has auto-discovery)
  - Internal implementation classes need exclusion from user-visible listings
  - Error messages must reference current commands, not deleted scripts
- Heuristics to detect recurrence:
  - Grep for file existence checks before framework initialization calls
  - Check for nodes in src/pflow/nodes/ that shouldn't be user-visible
  - Verify error messages reference valid commands/scripts
- Related pitfalls: Premature validation prevents framework initialization

Follow-ups:
- Consider moving MCPNode outside auto-scanned directories
- Document internal vs user-visible node distinction

<!-- ===== BUGFIX ENTRY END ===== -->

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
  - Shell behavior differs across runners (BSD vs GNU utils); normalize safe non-error exit codes (ls/which/command -v/type) and ensure stderr carries expected messages for deterministic tests.
  - After pre-commit mutations, always re-stage before committing; keep functions under ruff complexity with small helpers.
- Heuristics to detect recurrence:
  - Grep for single-ended `isatty()` checks in CLI code paths that might prompt.
  - If `.result` is unexpectedly empty in JSON mode, check `outputs[*].source` and ensure population occurs.
  - Watch for tests asserting tool-specific stderr/exit codes; prefer normalized, cross-platform behavior in nodes.
- Related pitfalls: `.taskmaster/knowledge/pitfalls.md#interactive-prompts-in-pipelines-cause-hangs`, `.taskmaster/knowledge/pitfalls.md#declared-outputs-require-explicit-source-when-namespacing-is-on`

Follow-ups:
- Add subprocess/pty e2e tests to simulate real TTY/pipe behavior

<!-- ===== BUGFIX ENTRY END ===== -->
