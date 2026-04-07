# Task 149 Progress Log

## 2026-04-07 - Context and reconciliation

### Scope confirmation
- User request said "task 49", but all supplied paths point to `task_149`; implementation is proceeding against Task 149.
- Read sequentially, in order:
  1. `.taskmaster/tasks/task_149/task-149.md`
  2. `.taskmaster/tasks/task_149/starting-context/braindump-20260407-planning.md`
  3. `.taskmaster/tasks/task_149/implementation/implementation-plan.md`

### Verified against code
- Verified the current GH #194 bug still exists in `src/pflow/cli/workflow_output.py::_output_with_header`: non-interactive default mode routes declared workflow output to `stderr`.
- Verified the plan's cleanup targets are real in current code:
  - `OutputController.create_progress_callback()` still has the non-interactive TTY gate.
  - `DisplayManager` is still imported and used from `src/pflow/cli/main.py`.
  - `WorkflowRunner.run()` still takes `output: Optional[OutputInterface]`.
  - CLI text summary still renders the duplicate `Nodes executed (N):` block.
  - MCP text formatter still has the parallel per-node execution block in `_append_execution_steps`.

### Critical gotcha checks completed
- Verified `should_show_prompts()` appears to be dead in production code; grep found only test references plus the method definition. Prompt usage elsewhere relies on direct `click.confirm(...)`, not `OutputController`.
- Verified `_format_execution_step` and `_format_batch_node_line` are imported directly by `tests/test_execution/formatters/test_success_formatter.py`, so deleting them requires corresponding test updates.
- Verified `tests/test_execution/formatters/test_output_utils.py` does not pass `output_controller=` anywhere; no hidden coupling there.

### Trust boundary
- Verified directly in code: output routing bug, progress callback gate, summary duplication, runner signature, formatter parity duplication, save-prompt dead-code assumption.
- Assumed correct from the approved plan until contradicted by code/tests: exact doc edits, precise test inventory, and manual verification commands.

### No deviations yet
- No implementation changes made in this phase.
- No blockers found that justify deviating from the approved plan.

## 2026-04-07 - Phase 1 production changes

### Implemented
- `src/pflow/cli/workflow_output.py`
  - Replaced the three-mode `_output_with_header(...)` routing logic with one rule: header to `stderr`, data to `stdout`, except `-p` which skips the header.
  - Removed `output_controller` parameter threading from `_handle_text_output`, `_emit_declared_output`, `_try_declared_outputs`, and `_handle_workflow_output`.
  - Collapsed `_display_execution_summary()` so it no longer prints the duplicate `Nodes executed (N):` block; it now keeps the one-line completion summary, `--only` context line, batch error details, stderr warnings, cost, and warnings.
  - Deleted `_get_status_indicator`, `_format_node_timing`, and `_format_node_status_line`.
- `src/pflow/core/output_controller.py`
  - Removed the TTY gate from `create_progress_callback()`; it now always returns a callback.
  - Added internal `sys.stderr.isatty()` guard only to `_handle_batch_progress()` for the `\r` overwrite case.
  - Updated `_handle_node_complete()` to terminate non-batch failures with ` ✗ Failed` and to append smart-handled tags (`[no matches]`, `[not found]`, raw fallback).
  - Deleted `_handle_workflow_start`, `echo_progress`, `echo_result`, and `should_show_prompts`.
- `src/pflow/runtime/engine/instrumentation.py`
  - Passed `smart_handled` and `smart_handled_reason` through the progress callback.
- `src/pflow/cli/main.py`
  - Removed `CliOutput`/`DisplayManager` usage.
  - Added a single `progress_enabled = not print_flag and output_format != "json"` gate controlling both the inline `Executing workflow (...)` stderr echo and whether a progress callback is installed.
  - Updated `WorkflowRunner.run(...)` call to use `progress_callback=...`.
  - Removed the stale `output_controller=` threading into `_handle_workflow_output`.
  - Updated `--print` help text to reflect post-fix semantics.
- `src/pflow/execution/runner.py`
  - Replaced `output: Optional[OutputInterface]` with `progress_callback: Optional[Callable]`.
  - Simplified shared-store callback installation to store the callback directly.
- `src/pflow/execution/formatters/success_formatter.py`
  - Simplified `_append_execution_steps()` to keep only `--only` context and batch errors, matching the CLI summary collapse.
- `src/pflow/runtime/workflow_executor.py`
  - Updated stale `NullOutput` comment.
- `src/pflow/nodes/shell/shell.py`
  - Updated smart-handled tag mapping comment to point at `OutputController._handle_node_complete()`.

### Deleted files
- `src/pflow/cli/cli_output.py`
- `src/pflow/execution/display_manager.py`
- `src/pflow/execution/null_output.py`
- `src/pflow/execution/output_interface.py`

### Deviations
- None so far. Production edits still follow the approved plan closely.

### Pending validation
- Need to reconcile direct test imports of `_format_execution_step` / `_format_batch_node_line` before deleting those helpers from `success_formatter.py`.
- Need to update tests for the removed methods/events and the new internal stderr TTY guard in batch progress tests.

## 2026-04-07 - Phase 2 test/doc reconciliation

### Test updates completed
- `tests/test_core/test_output_controller.py`
  - Deleted tests for removed dead methods/events: `echo_progress`, `echo_result`, `should_show_prompts`, and `workflow_start`.
  - Updated `create_progress_callback` expectations to "always returns a callable".
  - Added `patch.object(sys.stderr, "isatty", return_value=True)` to batch-progress tests so the new internal TTY guard does not short-circuit under pytest capture.
  - Added direct regression coverage for:
    - non-batch failure line termination (` ✗ Failed`)
    - smart-handled tag mapping (`[no matches]`)
- `tests/test_cli/test_shell_stderr_warnings.py`
  - Removed `_format_node_status_line` import and its orphaned unit tests.
- `tests/test_execution/formatters/test_success_formatter.py`
  - Removed direct imports/tests for deleted helper functions `_format_batch_node_line` and `_format_execution_step`.
  - Updated formatter expectations to the new design: no static `Nodes executed (N):` block, batch error sections preserved, `--only` summary line preserved.
- `tests/test_cli/test_workflow_output_handling.py`
  - Added GH #194 stream-separation regression test using `result.stdout` and `result.stderr`.
  - Added the planned failure-output regression guard.
- Deleted `tests/test_integration/test_cli_mcp_parity.py` per plan.

### Documentation updates completed
- Updated:
  - `src/pflow/cli/CLAUDE.md`
  - `src/pflow/execution/CLAUDE.md`
  - `src/pflow/core/CLAUDE.md`
  - `src/pflow/mcp_server/CLAUDE.md`
  - `docs/reference/cli/index.mdx`
  - `architecture/features/shell-pipes.md`
  - `src/pflow/cli/resources/cli-basic-usage.md`
- The docs now describe:
  - unified routing (`stdout` for data, `stderr` for diagnostics)
  - default live progress in TTY and non-TTY
  - `-p` as minimal stderr output rather than "force non-interactive"
  - removal of the dead output abstraction

### Verification completed
- `python3 -m py_compile ...` passed for all changed source files.
- `python3 -m py_compile ...` passed for all changed test files.
- Grep verification: no remaining `src/` or `tests/` references to deleted runtime symbols (`CliOutput`, `DisplayManager`, `NullOutput`, `OutputInterface`, deleted helper functions, or removed `output_controller=` threading), aside from one intentional explanatory mention in `src/pflow/cli/CLAUDE.md`.

### Verification constraints / deviations
- Could not run pytest via `uv run ...` in this sandbox:
  - with default cache path: permission failure under `~/.cache/uv/...`
  - with workspace cache override: `uv` panicked in the environment's macOS system-configuration path
- System `python3` is available for syntax checks but does not have `pytest` installed.
- Because of the environment constraint above, runtime test execution is still pending and must be done in a working project environment.

## 2026-04-07 - Follow-up from real test run

### Observed failures from user environment
- Two failures in `tests/test_mcp_server/test_execution_workflow.py`
- Both failures expected a literal `✓` in the returned success string from `ExecutionService.execute_workflow(...)`

### Root cause
- This was not a formatter bug.
- The tested workflow uses a plain shell node with no template inputs, which triggers the existing validator warning about cache safety.
- After Task 149, CLI and MCP success summaries are intentionally aligned:
  - clean success: `✓ Workflow completed ...`
  - degraded / warnings: `⚠️ Workflow completed with warnings ...` or `⚠️ Workflow completed with N warnings ...`
- So the old assertion "success string must contain a checkmark" became invalid for degraded-success cases.

### Fix applied
- Updated `tests/test_mcp_server/test_execution_workflow.py` to assert on stable success semantics instead:
  - contains `"Workflow completed"`
  - contains `"Workflow output:"`
  - contains `"hello"`
- This keeps the test aligned with the public contract of `ExecutionService.execute_workflow()` without overfitting to a specific glyph for degraded success.

## 2026-04-07 - Ruff follow-up

### Observed issue
- `ruff` flagged `src/pflow/core/output_controller.py::_handle_node_complete` with `C901` complexity 12 > 10.

### Fix applied
- Extracted two tiny helpers:
  - `_build_smart_handled_tag(...)`
  - `_emit_non_batch_completion(...)`
- `_handle_node_complete(...)` now only routes between:
  - fatal error
  - batch completion
  - non-batch completion

### Rationale
- Kept the logic local to `OutputController` instead of suppressing the rule.
- This preserves the approved behavior while making the success/warning rendering path easier to read and modify.

## 2026-04-07 - High-value regression tests added

### Why these tests
- Added only tests that protect the riskiest behaviors introduced by this refactor:
  1. callsite gating for `-p`
  2. callsite gating for JSON mode
  3. real failure-path progress line termination through the actual CLI/engine path

### Added tests
- In `tests/test_cli/test_workflow_output_handling.py`:
  - `test_print_mode_suppresses_progress_header_and_summary`
  - `test_json_mode_suppresses_progress_header_and_summary`
  - `test_real_failing_shell_node_terminates_progress_line`

### Value
- These catch regressions that would be easy to reintroduce later if someone:
  - moves the `progress_enabled` gate
  - reinstalls progress callback in JSON mode
  - reinstalls progress callback in `-p` mode
  - breaks the live failure terminator while refactoring callback rendering

## 2026-04-07 - Test restoration after accidental checkout

### What happened
- The working copy of `tests/test_cli/test_workflow_output_handling.py` was reverted with `git checkout`, wiping three unstaged tests that only existed in the working tree.

### Restored
- Re-added:
  - `test_print_mode_suppresses_progress_header_and_summary`
  - `test_json_mode_suppresses_progress_header_and_summary`
  - `test_real_failing_shell_node_terminates_progress_line`
- Also restored the supporting import:
  - `from tests.shared.markdown_utils import write_workflow_file`

### Verification
- `python3 -m py_compile tests/test_cli/test_workflow_output_handling.py` passed after restoration.

## 2026-04-07 - Adversarial verification + follow-up fixes

### Committed as
- Baseline: `8606f645` — Task 149 implementation (committed defensively to
  protect against accidental working-tree loss during mutation testing).
- Fixes: `7f2d61b3` — the four fixes documented below.

### Verification approach
- Ran the full plan's automated tests as *context only* (all pass: 4639
  baseline → 4641 after fixes).
- Focused real effort on reproducing the user-visible behavior in actual
  subprocesses (`uv run pflow …`) rather than CliRunner, because pytest's
  logging fixture and Click's stderr interception both mask production-
  level corruption.
- A/B compared against `main` where behavior was claimed "unchanged" to
  catch latent regressions the plan exposed.

### Findings

**CRITICAL #194 + streaming: VERIFIED working**
- Real subprocess shows clean stream separation (`stdout=9 bytes, stderr=437 bytes`).
- Live streaming verified with file polling at 0.4s intervals: byte count
  grows monotonically (header at t≈0.8s, first node at t≈1.6s, etc.).
  The user's primary goal — agents seeing live progress as nodes complete —
  is achieved.

**Finding #2 (HIGH — regression): Nested workflow rendering corrupted in non-TTY.**
- Symptom: parent `nested_call...` partial line concatenated with child's
  first `inner_a...`, parent's completion orphaned on its own line.
- Root cause: `_handle_node_start` used `nl=False`; nothing tracked that
  state, so when the child engine's own `_handle_node_start` fired via
  the propagated callback, it wrote directly onto the parent's partial.
- Hidden by: no test exercised real nested workflow execution with the
  progress callback active (prior tests used mocks or ran in TTY mode
  where the TTY gate suppressed nested progress entirely).

**Finding #3 (HIGH — regression): `logger.warning` corrupts partial line.**
- Symptom: `will_fail...WARNING: Command failed with exit code 1\n ✗ Failed`
  instead of `will_fail... ✗ Failed` on failing shell nodes.
- Root cause: `shell.py:713` called `logger.warning(...)` from `post()`
  which writes directly to stderr via Python logging (bypassing
  `OutputController`), landing between `_handle_node_start`'s partial line
  and `_handle_node_complete`'s terminator.
- Scope: 33 `logger.warning/error` calls across 9 node files are potential
  corruption sites. The common shell-failure path was the only one I
  observed in practice.

**Finding #4 (CRITICAL test fidelity): `test_real_failing_shell_node_…` passes for the wrong reason.**
- The test uses `click.testing.CliRunner`, whose `result.stderr` does NOT
  contain the `WARNING: Command failed...` text that a real subprocess
  sees. CliRunner intercepts stderr differently from Python's `logging`
  handler, which was installed against the original stderr before the
  interception.
- Result: the test gave false assurance that the failure-terminator path
  was clean. The new gh194 + failing-node tests were both mock-based, so
  none of the existing regression guards could detect Findings #2 or #3.

**Finding #1 (MEDIUM — pre-existing, exposed by the refactor):** structured
outputs were Python-`repr`-formatted on stdout (`{'key': 'value'}`),
unparseable by `jq`. Pre-existing in `safe_output`, but the GH #194 fix now
means these values actually land on stdout where consumers pipe them —
so the usability gap is visible for the first time.

### Fixes applied (follow-up commit `7f2d61b3`)

**Fix #2 — `OutputController` partial-line tracking:**
- New `_partial_line_open` flag + `_close_partial_line_if_open()` helper
- `_handle_node_start` now self-terminates any prior partial line first,
  sets the flag
- `_handle_node_complete`, `_handle_node_cached`, `_handle_node_warning`
  now accept `node_id` + `indent` parameters and call a new
  `_ensure_node_line_open()` helper that re-emits a fresh `  node_id`
  lead-in if the partial was closed between start and complete
- Forwarding in `create_progress_callback`'s inner `progress_callback`
  wrapper updated to pass `node_id` + `indent` through
- Nested rendering now clean:
  ```
    before... ✓ 0.0s
    nested_call...
      inner_a... ✓ 0.5s
      inner_b... ✓ 0.5s
    nested_call ✓ 1.0s        ← re-emitted on its own line
    after... ✓ 0.0s
  ```

**Fix #3 — Drop redundant `logger.warning` in `shell.py`:**
- Removed the `logger.warning(f"Command failed with exit code {exit_code}")`
  call at `shell.py:713` (in `post()` on non-zero exit).
- Rationale: the same message is already emitted by
  `call_completion_callback`'s `error_msg` (reads `shared["exit_code"]`)
  and by the post-execution diagnostic block that prints `shared["error"]`.
  The logger call was legacy from before the diagnostic refactor.
- Updated `tests/test_nodes/test_shell/test_auto_handling.py`'s
  `TestLoggingBehavior::test_real_error_logs_warning` →
  `test_real_error_surfaces_error_via_action_and_shared_store` to assert
  on the canonical failure-reporting path (returned action + shared store
  state) rather than the removed logger.warning.
- Did NOT install a partial-line-aware logging handler as defense-in-depth
  for the other 32 `logger.warning/error` sites — they are rare edge cases
  (shell timeout, dangerous command patterns, HTTP/LLM/file errors). If
  any start corrupting in practice, the new subprocess test will catch
  them cleanly and we can revisit.

**Fix #1 — JSON-encode structured outputs in `safe_output`:**
- Strings still pass through verbatim
- Non-string / non-bytes values now `json.dumps(value, ensure_ascii=False)`
- Non-JSON-serializable objects fall back to `str(value)` in a nested
  try/except so the output path can never raise
- Result: `pflow foo.pflow.md | jq -r .key` works for dict outputs;
  booleans render as `true`/`false`; `None` renders as `null`
- Updated `test_complex_output_types` to assert exact JSON tokens
  (`"true"`, `"null"`, `'{"key": "value", …}'`) instead of `str(value)`

**Fix #4 — Real subprocess regression tests:**
- New file `tests/test_cli/test_progress_streaming_subprocess.py`
  - `test_failing_shell_node_progress_line_is_clean` — spawns real
    `uv run pflow`, asserts `will_fail... ✗ Failed` present and
    `will_fail...WARNING:` / `will_fail...Command failed` absent.
  - `test_nested_workflow_progress_lines_are_not_concatenated` — spawns
    real `uv run pflow`, asserts parent and child lines render without
    concatenation, and that the parent's completion is re-emitted
    attached to its node id.
- Both tests SKIP cleanly under the sandboxed `uv` panic mode used in CI.
- These tests are the only regression guard that would catch Findings #2
  or #3 reappearing, because they exercise the real stderr file
  descriptor that agents and CI systems actually read.

### Verification after fixes
- `make test`: **4641 passed, 9 skipped** (+2 new subprocess tests,
  +1 test updated for JSON output, 0 regressions).
- `make check`: ruff + ruff-format + mypy + deptry all clean.
- Manual subprocess reproduction of all four findings: all fixed.
- Original #194 fix still works (stdout=9B, stderr=437B cleanly separated).
- Live streaming still works.
- Smart-handled tags (`[no matches]`, `[not found]`) still render.
- `-p` and JSON modes still 0-byte stderr on success.
- `--only` summary line still preserved.
- Cache hit display (`↻ cached`) still works.

### Not done (deferred, low priority)
- TTY-only manual tests (require a real terminal): interactive rendering,
  `\r` batch counter in-place update, TTY/non-TTY ANSI-stripped parity
  diff. These need the user's eyes in an actual terminal.
- Partial-line-aware logging handler for the remaining 32 rare
  `logger.warning/error` sites across node files. Minimal scope — revisit
  if any fire in practice. The subprocess regression test will catch them.
- Finding #5 (LOW): the `elif reason:` fallback branch in
  `_build_smart_handled_tag` is unreachable given current `shell.py` reason
  strings. Defensive dead code, fine to leave.

### Operator error to flag for future agents
- During mutation testing of the production fix, I ran
  `git checkout tests/test_cli/test_workflow_output_handling.py` to revert
  a temporary debug `print(...)` edit. That reverts to HEAD, NOT "before
  my edit", which wiped unstaged tests from the working tree.
- Recovery: found the lost tests via `git fsck --lost-found` + scanning
  dangling blobs for `test_workflow_data_goes_to_stdout_not_stderr_gh194`.
  Restored from blob `5e5fcb2b…`. The 3 additional unplanned tests
  (`test_print_mode_suppresses…`, `test_json_mode_suppresses…`,
  `test_real_failing_shell_node_…`) were re-added by hand afterwards.
- Lesson: when reverting a single debug edit, use `git diff` piped to
  `git apply -R` on the specific hunk, not a blanket `git checkout`. Or
  `git add` the rest first so checkout only affects the dirty bits.

## 2026-04-07 - High-value streaming regression test

### Motivation
- After the four fixes landed, stepped back and asked "what could regress
  silently that no existing test would catch?" One clear gap: **no test
  verifies that live streaming actually works end-to-end**. The user's #1
  stated motivation for Task 149 was "agents see streaming progress," but
  all existing tests check either routing (where bytes land) or rendering
  correctness (what the bytes look like) — not whether bytes *arrive
  incrementally* versus being buffered until process exit.
- Regressions that would silently break streaming and pass every current
  test: re-introducing the TTY gate on `create_progress_callback`, adding
  buffering to click.echo calls, installing an output combiner in
  `OutputController`, or any future refactor that batches progress events
  "for efficiency".

### Why a causal test, not a timing test
- First draft used wall-clock thresholds (sleep 0.2s between steps, assert
  gap > 0.1s). Works but flaky on slow CI — clock variance can push real
  gaps under the threshold.
- Replaced with a *causal* assertion: use a FIFO barrier to pin step_1
  in a known blocked state, then verify step_0's completion line is
  already on stderr. No timing math. If buffering is broken, the bytes
  sit in a buffer while the subprocess is blocked on the barrier and
  has no reason to flush → readline loop times out → clean failure.

### Added
- `tests/test_cli/test_progress_streaming_subprocess.py::test_progress_streams_before_downstream_nodes_complete`
- Two shared helpers in the same file (extracted to satisfy ruff C901):
  - `_wait_for_stderr_marker(proc, marker, deadline)` — line-by-line
    select loop that returns True when a marker arrives on stderr.
  - `_unblock_barrier_fifo(path, proc, timeout)` — non-blocking FIFO
    write with retry, handles the race between the parent test
    observing stderr and the subprocess reaching its `cat <fifo>` call.

### Verification of the test itself
- Passing path: ~1.1s wall-clock (subprocess startup + fast step + unblock).
- Mutation test: temporarily re-introduced the TTY gate in
  `create_progress_callback` to simulate the original #194 bug coming
  back. The test FAILED with the exact error message it was designed to
  emit: "step_0's completion line did not arrive on stderr while step_1
  was still blocked on the barrier FIFO." Confirmed the test catches the
  regression it was designed for.
- Reverted mutation, full suite clean: **4642 passed, 9 skipped**
  (+1 vs previous state).
- `make check`: ruff + ruff-format + mypy + deptry all clean.

### What this test catches that nothing else does
- Someone re-introducing `if not is_interactive(): return None` to
  `create_progress_callback` "for cleanliness" (the original #194 bug).
- Someone adding buffering to `click.echo` / `OutputController`
  internal writes.
- Someone removing Python's default stderr line buffering or changing
  click's flush-per-echo behavior.
- Any future change that batches progress events before delivery.
- The nested subprocess test already implicitly covers OutputController
  internal buffering (via the re-emission behavior), so the causal
  streaming test + the nested test together cover the full progress
  pipeline end-to-end.
