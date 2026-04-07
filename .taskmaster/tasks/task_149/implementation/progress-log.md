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

## 2026-04-07 - Task 149 closeout

### Branch state
- Branch: `fix/non-interactive-output-stderr`
- Commits (newest first):
  - `945ac6b3` test: add causal streaming regression test (FIFO barrier)
  - `7f2d61b3` fix: partial-line corruption + JSON-encode structured outputs
  - `8606f645` feat: fix #194 + consolidate output pipeline (Task 149)
- All three commits pass pre-commit hooks (ruff, ruff-format, mypy, deptry).

### Final test state
- `make test`: **4642 passed, 9 skipped** (0 failures, 0 errors).
- `make check`: clean.
- +3 new tests vs `main`:
  - `test_failing_shell_node_progress_line_is_clean` (subprocess)
  - `test_nested_workflow_progress_lines_are_not_concatenated` (subprocess)
  - `test_progress_streams_before_downstream_nodes_complete` (subprocess, causal)

### What actually ships
The committed state delivers everything in the original Task 149 plan
plus four follow-up fixes from adversarial verification:

1. **#194 fix** — data → stdout, diagnostics → stderr, always. Real
   subprocess verified.
2. **Live progress streaming** — TTY gate removed; gated at callsite for
   `-p` and JSON modes only. Causal streaming test verifies bytes arrive
   incrementally.
3. **Dead scaffolding deleted** — `OutputInterface`, `CliOutput`,
   `NullOutput`, `DisplayManager`, `test_cli_mcp_parity.py`.
4. **CLI/MCP summary parity** — both paths lost the `Nodes executed (N):`
   per-node block; each emits one-line completion tag + supplementary
   diagnostics.
5. **Smart-handled tags** — `[no matches]` / `[not found]` ported to the
   live progress callback via `NamespacedSharedStore` access pattern.
6. **Failure terminator** — `✗ Failed` closes the partial line on
   non-batch errors.
7. **Partial-line tracking** — `OutputController` self-terminates open
   partial lines on interleaved writes, re-emits `  node_id` lead-in on
   completion if the partial was closed. Fixes nested workflow rendering.
8. **`logger.warning` removal** — redundant warning in `shell.py:713`
   deleted (diagnostic pipeline already surfaces the same info).
9. **JSON-encoded structured outputs** — `safe_output` now emits valid
   JSON for dict/list/bool/number/null values so `pflow foo | jq` works.

### Deferred (intentional, low value)
- Defense-in-depth logging handler for the 32 other `logger.warning/error`
  sites across node files. Rare edge cases; the subprocess failing-shell
  test is the canary. If any start corrupting in practice, we'll see it
  there and can revisit.
- Finding #5: unreachable `elif reason:` fallback branch in
  `_build_smart_handled_tag`. Defensive dead code, fine to leave.

### Requires human verification before merge
- TTY-only behavior (colors, `\r` batch counter in-place updates,
  interactive save prompts, visual spacing/layout). Cannot be exercised
  from the Bash sandbox — see `scratchpads/streaming-baseline/manual-tests.md`
  for the checklist.

### Status
**Ready to merge pending manual TTY verification.**

## 2026-04-07 - Code review (4 reviewers, in parallel)

Manual TTY verification was completed by the user. Then ran a focused code
review with 4 specialist agents in parallel — selected for highest signal on
this refactor's blast radius rather than the full 8-agent sweep.

### Reviewers selected
1. **review-agent-ux** — task is fundamentally about agent UX (streaming,
   stdout/stderr routing, structured-output JSON encoding, smart-handled
   tags). Highest expected signal.
2. **review-feature-interactions** — refactor touches output × progress ×
   batch × nested workflows × MCP × `-p` × JSON × `--only` × caching ×
   error handling. Follow-up commit `7f2d61b3` already proved this lens
   catches real bugs (nested workflow rendering, `logger.warning` corruption).
3. **review-impact-completeness** — deleted shared abstraction
   (`OutputInterface`) + changed `WorkflowRunner.run()` signature. Need to
   verify all consumers were updated, including ad-hoc reimplementations
   (the Task 85 / Decision 1 "Update BOTH Call Sites" pattern).
4. **review-test-fidelity** — CliRunner already burned us once on Finding #4
   (test passed for the wrong reason because CliRunner stderr interception
   masked real corruption). Worth verifying current tests test what they
   claim.

### Reviewers NOT run (and why)
- `review-silent-failures` — overlap with agent-ux on JSON-encode fallback
- `review-concurrency-safety` — progress callback is single-threaded
  (verified in plan); see follow-up below
- `review-validation-consistency` — no validation logic changed
- `review-plan` — plan is already implemented

### Findings — consolidated and de-duped across reviewers

**Critical / must-fix before merge:**

1. **MCP `_append_outputs` still emits Python repr** *(impact-completeness C1,
   feature-interactions C4)* — `success_formatter.py:265-280` still does
   `lines.append(str(first_value))`. The Fix #1 JSON-encoding update was
   applied to CLI `safe_output` but missed the MCP twin. **Exact Task 85
   "Update BOTH Call Sites" pattern Decision 1 was supposed to enforce.**
   Workflows returning dict outputs via MCP get unparseable Python repr
   while CLI gets valid JSON.

2. **`safe_output` produces invalid JSON for NaN/Infinity** *(agent-ux H1)* —
   `json.dumps` defaults to `allow_nan=True`, emits literal `NaN`/`Infinity`
   tokens which jq rejects. Pass `allow_nan=False` + `default=str` fallback.

3. **`safe_output` fallback degrades silently to unparseable output**
   *(agent-ux H2)* — when value is `datetime`/`Path`/`set`/dataclass,
   fallback to `str(value)` produces unparseable output with no warning.
   Use `default=str` inside `json.dumps` AND emit a stderr warning on
   true serialization failure.

4. **MCP tool docstring still describes deleted "Nodes executed (3)..." block**
   *(impact-completeness W1, feature-interactions C3)* — visible to LLMs at
   MCP discovery time, misleads agents about response shape.

5. **`test_failing_node_emits_terminator_in_live_progress` is test theater**
   *(test-fidelity C-1)* — mocks `WorkflowRunner.run` so the engine path
   never runs. The negative assertion `"failing_node...❌" not in
   result.stderr` is trivially true; the test would pass even if
   `_handle_node_complete`'s entire error path was deleted. Subprocess test
   `test_failing_shell_node_progress_line_is_clean` is the real guard.

**Should fix — needs user decision:**

6. **Concurrency: `_partial_line_open` has no thread safety**
   *(feature-interactions C1)* — parallel batch (`parallel: true`) where
   each item runs a sub-workflow fires interleaved callbacks from worker
   threads onto the same `OutputController` instance. The new flag is
   non-atomic. No existing test exercises it. **Importance 4.**

7. **High-frequency `logger.warning` corruption sites**
   *(feature-interactions C2, impact-completeness W2)* — plan deferred 32
   sites with the subprocess test as canary. Reviewers enumerated and
   flagged 4 as likely to fire in real agent usage:
   - `shell.py:456` — dangerous-pattern detection (rm/dd/chmod)
   - `mcp/node.py:580` — fires on every non-compliant MCP server call
   - `llm.py:334` — LLM call timeout
   - `shell.py:648` — shell command timeout
   **Importance 3.**

8. **`--only` context lost in `-p` mode AND when target is last node**
   *(agent-ux H3, feature-interactions W1)* — `nodes_skipped > 0` guard
   hides the line when `--only` targets a leaf node, AND `-p` mode
   suppresses `_display_execution_summary` entirely. Iterative debugging
   footgun. **Importance 2.**

**Should fix — straightforward:**

9. **Live batch line drops success/failure counts** *(agent-ux M1)* —
   `batch_total` and `batch_success_count` passed through but never
   rendered. 8/10 success batch shows as full success on the live line.
10. **Re-emitted partial line uses no trailing dots** *(agent-ux M4)* —
    parser-unfriendly inconsistency. Original `node_id...` vs re-emit
    `node_id`. Agents grep'ing structured stderr miss re-emissions.
11. **`test_real_failing_shell_node_terminates_progress_line` redundant**
    *(test-fidelity C-2)* — CliRunner version cannot catch the
    `logger.warning` bypass that was the root of Finding #3; subprocess
    counterpart does both that and the click.echo terminator. Delete.
12. **No unit-level test for `_partial_line_open` re-emission**
    *(test-fidelity W-1)* — only the slow subprocess test catches Fix #2
    regressions. Add a fast unit test.

**Lower priority (deferred for follow-up):**

- Smart-handled tag with empty/None reason silently produces nothing
  *(agent-ux M3)* — defensive only, no current path triggers it
- `_handle_node_warning` overloads `duration_ms` to carry the warning
  string *(agent-ux M5)* — pre-existing footgun
- `test_complex_output_types` uses substring match instead of round-trip
  parse *(test-fidelity W-3)* — strengthen assertion
- `-v` mode writes 5 `cli: ...` echoes to stdout *(feature-interactions
  W4)* — pre-existing, surfaced by #194 fix
- Cache hit + nested workflow non-TTY untested *(feature-interactions W2)*
- node_warning + partial-line tracking untested *(feature-interactions W3)*

### Reviewers' callouts on what's working

All four reviewers explicitly praised:
- The **FIFO causal streaming test** as gold-standard regression coverage
- The **3 subprocess regression tests** in `test_progress_streaming_subprocess.py`
- The `_partial_line_open` state-machine design (small, local, well-documented)
- The `shell.py:713` `logger.warning` removal with explanatory comment
- The `test_real_error_surfaces_error_via_action_and_shared_store` rename
  (model example of preserving behavioral contract while removing
  implementation detail)
- The negative assertions in `test_success_formatter.py`
  (`"Nodes executed" not in text`)
- The unified routing in `_output_with_header`
  ("architectural fix distilled into 14 lines")

## 2026-04-07 - Code review fixes #1-#5 + #9-#12

User opted to ship findings #1-#5 (must-fix) and #9-#12 (small/clear) in one
batch, then discuss the three architectural decisions (#6 concurrency, #7
logger.warning sites, #8 --only context) separately.

### Production fixes

**Fix #1 — MCP `_append_outputs` JSON parity**
- File: `src/pflow/execution/formatters/success_formatter.py`
- Added `import json`. `_append_outputs` now mirrors CLI `safe_output`:
  strings pass through verbatim, structured values use
  `json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)`,
  with `str(value)` fallback on serialization failure.
- Closes the Decision 1 / Task 85 twin-update gap that the post-merge Fix
  #1 missed.

**Fix #2 + #3 — `safe_output` strict JSON + diagnostic fallback**
- File: `src/pflow/cli/workflow_output.py`
- `json.dumps(...)` now uses `allow_nan=False` (rejects literal
  `NaN`/`Infinity` tokens that jq can't parse) and `default=str` (datetime,
  Path, set, dataclass, etc. coerce inside the JSON document so the value
  lands as a JSON string and the pipeline keeps working).
- On true serialization failure, emits a stderr `cli: ...` warning naming
  the value type and exception, then falls back to `repr(value)` on stdout
  so something is still visible. Agents can now diagnose the failure
  instead of getting silent unparseable output.

**Fix #4 — MCP `workflow_execute` docstring**
- File: `src/pflow/mcp_server/tools/execution_tools.py`
- The `Returns:` block no longer claims a `Nodes executed (3)...` segment.
  Updated to describe the actual post-Decision-1 format (one-line
  completion tag + JSON-encoded outputs).

**Fix #9 — Live batch line shows success/failure counts**
- File: `src/pflow/core/output_controller.py::_handle_node_complete`
- The `is_batch` branch now reads the already-passed-through `batch_total`
  and `batch_success_count` and emits a count tag:
  - Full success: `process... 8/8 0.5s` (green)
  - Partial failure: `process... 8/10 ⚠️ 0.5s` (yellow)
- The supplementary `Batch 'X' errors:` block continues to carry per-item
  details after execution. Agents watching live stderr can now distinguish
  partial-failure batches from full successes without reading the
  post-execution diagnostic.

**Fix #10 — Re-emitted partial line keeps canonical `node_id...` shape**
- File: `src/pflow/core/output_controller.py::_ensure_node_line_open`
- Re-emit was `f"{indent}  {node_id}"` (no dots); changed to
  `f"{indent}  {node_id}..."` to match `_handle_node_start`. Structured
  stderr parsers now see one canonical format for completed lines
  regardless of whether interleaving forced a re-emit.

### Test fixes

**Fix #5 — Deleted `test_failing_node_emits_terminator_in_live_progress`**
- File: `tests/test_cli/test_workflow_output_handling.py`
- Test theater: mocked `WorkflowRunner.run` to return a pre-built
  `ExecutionResult`, so the engine never ran, so no `failing_node...`
  partial line was ever written, so the negative assertion was trivially
  true. Subprocess test in `test_progress_streaming_subprocess.py` is the
  real guard.

**Fix #11 — Deleted `test_real_failing_shell_node_terminates_progress_line`**
- File: `tests/test_cli/test_workflow_output_handling.py`
- Redundant with the subprocess test. The CliRunner version cannot catch
  the `logger.warning` bypass corruption that was the root of Finding #3
  (CliRunner's stderr interception masks `logger.*` writes), so its name
  was misleading. The subprocess test asserts both the click.echo
  terminator AND the `logger.warning` bypass cleanliness, so it covers
  everything the CliRunner version did and more.
- Also removed the now-unused `write_workflow_file` import.

**Fix #12 — New unit test for partial-line re-emission**
- File: `tests/test_core/test_output_controller.py`
- Added `test_partial_line_reemits_after_interleaved_close`. Drives the
  callback through `parent.node_start` → `child.node_start` →
  `child.node_complete` → `parent.node_complete` and asserts that the
  parent's completion path emits two echo calls: a re-emit of the
  `parent...` lead-in followed by the ` ✓ 1.0s` text. Fast unit-level
  guard for the partial-line tracking logic that doesn't require
  spawning a subprocess.

**Test updates from production changes**
- `test_node_complete_for_batch_only_shows_timing` →
  `test_node_complete_for_full_success_batch_shows_count_and_timing` and
  added `test_node_complete_for_partial_failure_batch_shows_warning_count`.
  Old test name became inaccurate after Fix #9 added count rendering;
  split into one test per branch.
- `test_nested_workflow_progress_lines_are_not_concatenated` updated:
  the dot-canonical-format change in Fix #10 changed the re-emit shape
  from `nested_call ✓` to `nested_call... ✓`. Updated the assertion and
  the docstring.

**New parity guard test class — `TestAppendOutputsCliMcpParity`**
- File: `tests/test_execution/formatters/test_success_formatter.py`
- 6 tests guarding the MCP/CLI value-formatting parity:
  - `test_string_output_passes_through_verbatim` (no JSON quoting)
  - `test_dict_output_emits_valid_json` (round-trip through json.loads)
  - `test_list_output_emits_valid_json`
  - `test_bool_output_emits_lowercase_json_token` (true not True)
  - `test_none_output_emits_json_null` (null not None)
  - `test_unserializable_output_falls_back_without_raising` (datetime
    via `default=str`)
- Designed to permanently lock the CLI/MCP parity contract for output
  value rendering so the next post-merge fix can't drift again.

### Verification
- `make test`: **4648 passed** (+6 vs 4642 baseline: +1 from Fix #12, +1
  from Fix #9 split, +6 from new parity class, -2 from deleted test
  theater = +6 net).
- `make check`: ruff + ruff-format + mypy + deptry all clean (one
  ruff-format auto-fix on the new batch count rendering line).
- 0 regressions across 4648 tests including all 3 subprocess tests
  (verified they actually ran, not just got skipped — the FIFO causal
  test took ~1.1s wall-clock).

### Not committed yet
- All fixes are in the working tree, not yet committed. Awaiting decisions
  on findings #6, #7, #8 before final commit.

### Open for discussion
The three architectural decisions remaining from the review:
- **#6 — `_partial_line_open` thread safety**: lock vs document vs
  suppress nested events under parallel batch
- **#7 — `logger.warning` corruption defense**: delete the 4 high-frequency
  sites individually vs install a partial-line-aware logging handler vs
  defer entirely (current plan)
- **#8 — `--only` always-emit even in `-p` mode**: move the summary line
  out of `_display_execution_summary` vs keep current behavior with
  explicit doc

## 2026-04-07 - Architectural fix #7: partial-line-aware logging filter

### The right answer wasn't the one I originally proposed
First framing of #7 had three options: delete 4 high-frequency sites,
install a logging handler, or defer. After enumerating the actual call
sites I had to revise the recommendation:

- 29 ``logger.warning``/``logger.error`` calls in node files
  (``shell``, ``llm``, ``mcp``, ``file``, ``claude_code``)
- ~10 are **genuine warnings** carrying unique diagnostic info (LLM
  timeout per retry, dangerous-pattern detection, MCP server returning
  Python repr, schema key missing, JSON extraction failed, file size
  lookup failures). Deleting these loses real value for agents.
- ~18 are ``logger.error + raise`` pairs where the diagnostic pipeline
  already surfaces the same info via the exception (the ``shell.py:713``
  pattern that Fix #3 deleted).

Both groups corrupt partial lines today. Deleting the 4 high-frequency
sites individually:
1. Loses unique diagnostic value from 3 of the 4 sites
2. Doesn't fix the 25 other corruption sites
3. Doesn't fix any future ``logger.warning`` added to a node
4. Adds whack-a-mole engineering tax for years

### What top-10% codebases do
- **`tqdm.contrib.logging.logging_redirect_tqdm`** — provides a logging
  handler that knows about the active progress bar; logger calls flow
  through it and the bar redraws cleanly.
- **`rich.Console` + `RichHandler`** — Console owns stderr/stdout; logging
  routes through the Console via a custom handler.

Both share the architectural answer: **the controller actually owns
stderr coherence, and logging routes through the controller**. The flag
stops being leaky because there's only one writer.

### The fix shipped
A ``logging.Filter`` installed inside ``create_progress_callback()`` —
~50 lines, one production file, zero node-file changes:

- ``_ProgressPartialLineFilter(logging.Filter)``: holds a ``weakref``
  to the OutputController; on each ``filter()`` call, calls
  ``_close_partial_line_if_open()`` and returns True (never blocks
  records). The side effect IS the point.
- ``OutputController._install_log_partial_line_guard()``: idempotent;
  attaches the filter to every ``StreamHandler`` on the root logger
  whose stream IS ``sys.stderr`` (which is the single handler that
  ``cli/logging_config.py::configure_logging`` installs at startup).
- ``OutputController._log_filter_installed`` instance var: tracks
  install state for idempotency.
- ``create_progress_callback()`` calls ``_install_log_partial_line_guard()``
  before returning the closure. Non-progress modes (``-p``, ``--output-format
  json``, MCP server) never call ``create_progress_callback()`` so the
  filter is never installed and logging behavior is unchanged.

### Why each design choice
- **`logging.Filter` not `logging.Handler`** — filters run as side
  effects before each handler emits. We don't have to replace pflow's
  existing ``StreamHandler``, can't accidentally swallow records, can't
  accidentally duplicate output.
- **`weakref.ref(controller)`** — installed filters survive controller
  GC cleanly. In tests that create/destroy many controllers, this
  prevents the filter from pinning destroyed instances alive.
- **`handler.stream is sys.stderr` check** — only attach to handlers
  that write to the actual stderr file descriptor. Future file-based
  log handlers won't be affected.
- **Idempotent** — nested workflow propagation reuses one
  OutputController across the parent and all children, but
  ``create_progress_callback()`` may be called multiple times in
  edge cases. Re-install is a no-op.
- **Installed inside `create_progress_callback`** — the one method
  whose contract is "I'm enabling progress display". Tied to progress
  lifecycle, not OutputController lifecycle.

### Tests added
1. **`test_log_filter_closes_partial_line_on_emit`** — unit test of the
   filter class in isolation. Constructs a fake ``LogRecord``, calls
   ``filter.filter(record)`` directly, asserts the side effect ran AND
   the return value is True. Independent of pytest's logging fixture.
2. **`test_install_log_partial_line_guard_is_idempotent`** — calls
   ``create_progress_callback`` three times in a row, asserts exactly
   one filter is attached to the temp StreamHandler. Guards against
   filter stacking from re-entry.
3. **`test_logger_warning_through_real_logging_closes_partial_line`** —
   end-to-end integration test. Installs a real stderr ``StreamHandler``,
   creates an OutputController (which installs the filter), opens a
   partial line via the callback, fires a real ``logger.warning(...)``
   through Python's logging machinery, asserts the partial line was
   closed by the filter side effect. This is the test that pairs with
   the unit test to cover BOTH the filter behavior AND the install path
   — without it, a regression that breaks the install (e.g., someone
   removes ``self._install_log_partial_line_guard()`` from
   ``create_progress_callback``) would not be caught by the unit test
   alone.

### What this protects
| Concern | Status |
|---|---|
| 29 current ``logger.warning``/``logger.error`` sites in node files | All protected |
| Future ``logger.*`` calls added to any node | Just work |
| Mental model | "OutputController owns stderr coherence" |
| Diagnostic value | 0 of 29 lost |
| Files touched | 1 production file (``output_controller.py``) |
| Test changes | +3 tests, 0 deletions |
| Lines added | +50 prod, +90 test |
| Architectural debt | Resolved — flag now means what it says |

### Verification
- `make test`: **4651 passed** (+3 from filter tests)
- `make check`: ruff + ruff-format + mypy + deptry all clean
  (ruff auto-fixed the weakref type annotation to drop string quotes)
- 0 regressions

### Still open
- **#6 — `_partial_line_open` thread safety**
- **#8 — `--only` context lost**

## 2026-04-07 - Architectural fix #6: per-worker buffer + main-thread atomic drain

### The reviewer was right but the original framing was wrong
First framing of #6 had three options: thread lock, document & defer, or
suppress nested events. After verifying against the actual code in
``batch_executor.py`` and ``workflow_executor.py``:

- The original Task 149 plan claim ("parallel batch invokes progress
  callbacks from the main thread only") is **correct for plain parallel
  batch (leaf items)** but **wrong for parallel batch + sub-workflow per
  item**. The plan didn't think about sub-workflows.
- For plain parallel batch: ``_execute_single_node`` does NOT fire
  progress callbacks (verified ``engine.py:343-363``); only the main
  thread fires events via ``_collect_parallel_results``. Race-free.
- For parallel batch + sub-workflow: ``WorkflowExecutor.exec()`` runs in
  the worker thread and creates a child ``WorkflowEngine`` whose
  ``_execute_node`` fires ``call_start_callback``/``call_completion_callback``
  for every child node — all from the worker thread, all targeting the
  same shared OutputController via the propagated ``__progress_callback__``.

### The bug is semantic, not just byte-level
A naive ``threading.Lock`` does NOT fix this. The flag tracks *whether* a
partial is open, not *which node's*. Even with perfect mutex serialization,
T1's ``inner_a`` completion can find itself attached to T2's still-open
``inner_b`` partial, producing valid bytes with semantically wrong labels.

### Mutation test proved the race is REAL in production today
Stashed the buffering fix, ran the new regression test against the
pre-fix code, captured this raw stderr from a real subprocess
(parallel batch over 4 items running an inner sub-workflow with 2
child nodes each):

```
  process_items...
    child_a...
    child_a...
    child_a...
    child_a... ✓ 0.0s
    child_b... ✓ 0.0s
    child_b... ✓ 0.0s
 ✓ 0.0s                                  ← orphan completion
    child_b...    child_b... ✓ 0.0s      ← TWO partials concatenated
    child_b... ✓ 0.0s
    child_b... ✓ 0.0s
    child_b... ✓ 0.0s
  process_items... 4/4 0.0s
```

Three corruption modes visible at once: stacked partial lines, an orphan
completion floating with no node id, and a literal concatenation of two
partial lines on one line. **Not theoretical** — this is the rendering
of a 2-line workflow snippet with the existing pflow build (without my
fix). With buffering installed, the same workflow renders 8 clean
``child_a... ✓`` / ``child_b... ✓`` lines in 4 coherent pairs.

### What ships
**Pattern 5b: per-worker event buffer + main-thread atomic drain.**
This is the same model ``pytest-xdist`` and ``GNU make --output-sync=line``
use for parallel work. The architectural insight: workers don't share
output state. They produce *transcripts* (sequences of events) which a
single-writer drains atomically.

Implementation, all in ``batch_executor.py``:

1. **``process_item`` (worker side)**: replaces the inherited
   ``__progress_callback__`` in ``item_shared`` with a per-worker
   buffering wrapper that captures ``(args, kwargs)`` tuples into a
   thread-local list. The list is returned as the 5th element of the
   future result.

2. **``_drain_worker_buffer`` (new helper)**: takes the buffered events
   and the real callback, plays the events back through the callback.
   Suppression matches the existing patterns in ``instrumentation.py``
   (``call_start_callback`` / ``call_completion_callback`` etc.) so a
   rendering exception cannot crash workflow execution. Extracted as a
   helper to keep ``_collect_parallel_results`` under ruff's C901
   complexity limit.

3. **``_collect_parallel_results``**: unpacks the 5th tuple element,
   calls ``_drain_worker_buffer(callback, buffered_events)`` BEFORE
   ``_report_batch_progress``. Single-threaded by construction —
   ``as_completed`` yields one future at a time in the calling thread,
   which is the main thread.

### What this preserves vs Pattern 3 (suppress all worker callbacks)
| Concern | Pattern 3 (suppress) | **Pattern 5b (buffer + drain)** |
|---|---|---|
| Per-child node visibility | Lost | **Preserved** (atomic per item) |
| Live ``⚠️`` warnings from sub-workflow nodes | Lost | **Preserved** |
| Live ``↻ cached`` indicators from sub-workflow nodes | Lost | **Preserved** |
| Failure terminators (``✗ Failed``) | Lost | **Preserved** |
| Smart-handled tags (``[no matches]``) | Lost | **Preserved** |
| Race-free | Yes (no callbacks) | **Yes** (single-threaded drain) |
| Locks | None | **None** |

The "loss" of "real-time interleaving across workers" turned out to be a
non-loss — that interleaving was never actually working correctly (it
was racy) and couldn't be done correctly without per-line item-id
tagging anyway (which would hurt agent parseability more than waiting
one item duration helps). Pattern 5b is **strictly the correct trade**.

### Recursive correctness
Tested mentally for nested parallel batches: an inner parallel batch
inside a worker thread also installs its own buffering wrapper; events
accumulate in the inner buffer; the inner drain (also main-thread-of-its-
context) flushes them into the outer buffer; eventually the outermost
main thread drains everything to the real OutputController. No
special-casing for nesting depth.

### Tests added
1. **``test_parallel_batch_sub_workflow_renders_coherent_per_item_blocks``**
   in ``test_progress_streaming_subprocess.py``. Real subprocess. Runs a
   parallel batch over 4 items, each executing a sub-workflow with two
   children (``child_a``, ``child_b``). Asserts:
   - Exactly 8 child completion lines on stderr (4 items * 2 children)
   - Lines form 4 consecutive ``(child_a, child_b)`` pairs (no
     interleaving from other items)
   - No line contains both ``child_a`` and ``child_b`` (no concatenation)

2. **Mutation test verification**: stashed the buffering fix, confirmed
   the test fails with a clear assertion message showing the actual
   corruption (only 7 valid lines instead of 8, with ``child_b... ✓``
   appearing 6 times — concatenated). Restored the fix, test passes.

### Visual verification (real subprocess, post-fix)
```
Executing workflow (1 nodes):
  process_items...
    child_a... ✓ 0.0s
    child_b... ✓ 0.0s
    child_a... ✓ 0.0s
    child_b... ✓ 0.0s
    child_a... ✓ 0.0s
    child_b... ✓ 0.0s
    child_a... ✓ 0.0s
    child_b... ✓ 0.0s
  process_items... 4/4 0.0s
```

Each item's transcript is a clean coherent pair. No orphans, no
concatenation, no swapped labels.

### Verification
- ``make test``: **4652 passed** (+1 from new subprocess test)
- ``make check``: ruff + ruff-format + mypy + deptry all clean
  (one C901 fix via ``_drain_worker_buffer`` extraction)
- 0 regressions
- Mutation test verified: test fails on pre-fix code, passes on post-fix

### Still open
- **#8 — `--only` context lost**

## 2026-04-07 - Architectural fix #8: --only mode confirmation always announced

### The two sub-issues, verified empirically before recommending
Stepped back and ran three real subprocess tests against the working tree
(with all prior fixes in place but #8 not yet applied):

```
TEST 1: pflow foo --only target_b (middle node)
  ✓ Workflow completed in 0.031s
    ⤷ Stopped after 'target_b' (--only), 1 remaining node skipped    ← shown ✓

TEST 2: pflow foo --only target_c (LAST node)
  ✓ Workflow completed in 0.029s                                      ← INDISTINGUISHABLE FROM FULL RUN

TEST 3: pflow -p foo --only target_b
  stderr bytes: 0                                                     ← agent gets ZERO signal
```

Both sub-issues confirmed in production:
- **Sub-issue 8a**: ``nodes_skipped > 0`` gate hides ``--only`` confirmation when
  the target is the last node (or downstream branches were conditional and
  didn't run anyway). Output is byte-identical to a full run.
- **Sub-issue 8b**: ``-p`` mode suppresses the entire summary including the
  ``--only`` line. Agent piping ``pflow -p foo --only target | jq`` sees
  the data but has no rendered signal that the run was constrained.

### Top-10% prior art for "mode flags vs verbosity flags"

| Tool | Mode flag | Verbosity flag | Mode signal silenced by verbosity? |
|---|---|---|---|
| ``make`` | ``-k`` | ``-s`` | **No** — partial-completion warnings always shown |
| ``pytest`` | ``--maxfail=N`` | ``-q`` | **No** — ``!!! stopping after N failures !!!`` always shown |
| ``rsync`` | ``--dry-run`` | ``-q`` | **No** — every output line prefixed ``(DRY RUN)`` |
| ``apt-get`` | ``--simulate`` | ``-q`` | **No** — "Simulating" prefix always shown |
| ``git checkout`` | ``-p`` (interactive partial) | ``--quiet`` | **No** — interactive prompts honored |
| ``kubectl`` | ``--dry-run=client`` | ``-q`` | **No** — "(dry run)" suffix always shown |
| ``terraform`` | ``plan`` | ``-quiet`` | **No** — plan output mandatory |

**Unanimous**: mode flags (which change what the tool does) are
announced regardless of verbosity flags (which hide details). The
principle: **verbosity hides details, not modes**. ``--only`` is a mode
flag. ``-p`` is a verbosity flag.

### What ships
**Pattern: dual-emission with shared formatter.** Three changes in three
files, plus one extracted helper for ruff C901 compliance.

1. **``execution/formatters/success_formatter.py``**:
   - New ``format_only_indicator(only_node, nodes_skipped) -> str``
     helper. Single source of truth for the indicator text. Two forms:
     long form (``Stopped after 'X' (--only), N remaining nodes skipped``)
     when ``nodes_skipped > 0``, short form (``Stopped after 'X' (--only)``)
     when zero nodes were skipped.
   - ``_append_execution_steps``: drops the ``> 0`` gate, calls
     ``format_only_indicator`` directly. Fix for sub-issue 8a in MCP path.

2. **``cli/workflow_output.py``**:
   - ``_display_execution_summary``: drops the ``> 0`` gate, calls the
     shared ``format_only_indicator`` helper. Fix for sub-issue 8a in
     CLI default-mode path.
   - New ``_emit_only_indicator(formatted_result)`` helper that emits
     just the ``--only`` line via the shared formatter.
   - New ``_emit_summary_or_only_indicator(...)`` dispatcher that
     decides between full summary (default mode) and ``--only``-only
     emission (``-p`` mode + ``--only``). Fix for sub-issue 8b.
   - ``_handle_text_output``: simplified to delegate dispatch to the
     new helper, restoring complexity below ruff C901 limit.

### Why dual-emission and not "move the line up to _handle_text_output"

The cleaner-looking refactor would be to move the ``--only`` line out
of ``_display_execution_summary`` entirely and emit it from
``_handle_text_output`` in a single place. Rejected because it changes
the rendered ordering in default mode (``--only`` would print BEFORE
the completion status, vs after it today). That's a visible regression
for users relying on the current ordering AND breaks existing test
assertions. The dual-emission design preserves default mode byte-identical
to today and adds the new ``-p`` mode emission as a focused exception.

The shared ``format_only_indicator`` helper prevents drift between the
three call sites (CLI default summary, CLI ``-p`` emission, MCP summary).

### Tests added

**Unit tests** in ``test_success_formatter.py``:
1. ``TestFormatOnlyIndicator::test_long_form_when_nodes_skipped`` — verifies the
   long form text shape with skipped nodes count
2. ``TestFormatOnlyIndicator::test_short_form_when_no_nodes_skipped`` — sub-issue
   8a fix: short form when ``nodes_skipped == 0``, no "0 remaining" noise
3. ``TestFormatOnlyIndicator::test_singular_grammar_for_one_skipped_node`` —
   "1 remaining node" not "1 remaining nodes"
4. ``TestFormatOnlyIndicator::test_node_id_with_special_characters_quoted_correctly``
5. ``TestAppendExecutionStepsOnlyNode::test_only_with_zero_skipped_emits_short_form`` —
   sub-issue 8a fix at the MCP-formatter boundary
6. **Updated** ``test_only_node_zero_skipped_emits_short_form``
   (formerly ``test_only_node_zero_skipped_no_summary_line``): the
   pre-existing test explicitly encoded the OLD (buggy) behavior. Updated
   to assert the new behavior — short form is emitted, but "0 remaining"
   noise is preserved as forbidden text. The original test author's
   concern (no "0 remaining nodes skipped" noise) is satisfied by the
   short form, while the new requirement (announce ``--only`` mode) is
   also met.

**Subprocess tests** in ``test_progress_streaming_subprocess.py``:
1. ``test_only_with_last_node_emits_indicator`` — sub-issue 8a end-to-end:
   real ``pflow ... --only last_step`` shows ``⤷ Stopped after 'last_step' (--only)``
   on stderr with no "remaining" suffix.
2. ``test_print_mode_with_only_emits_indicator`` — sub-issue 8b end-to-end:
   real ``pflow -p ... --only step_b`` shows the mode confirmation on
   stderr while keeping ``-p``'s minimal-stdout-data contract.
3. ``test_print_mode_without_only_stays_silent`` — regression guard:
   ``-p`` without ``--only`` still produces 0 bytes on stderr.

### Mutation test verification
Stashed both ``cli/workflow_output.py`` and
``execution/formatters/success_formatter.py``, ran the new tests against
pre-fix code:

- ``TestFormatOnlyIndicator`` tests: ImportError (the helper doesn't exist
  in pre-fix code) — clean signal that the architecture is gone.
- ``test_only_with_last_node_emits_indicator``: FAILED with empty stderr
  — confirms sub-issue 8a is real in production today.
- ``test_print_mode_with_only_emits_indicator``: FAILED with stderr=''
  — confirms sub-issue 8b is real in production today.
- ``test_print_mode_without_only_stays_silent``: PASSED on pre-fix code
  (the regression guard correctly doesn't fire on the unrelated case).

Restored fixes, all tests pass.

### Visual verification (real subprocess, post-fix)
```
TEST 1: --only on LAST node (sub-issue 8a fix)
  ✓ Workflow completed in 0.029s
    ⤷ Stopped after 'target_c' (--only)         ← short form, no "0 remaining"

TEST 2: -p + --only on middle node (sub-issue 8b fix)
  stdout: b_done
  stderr:
    ⤷ Stopped after 'target_b' (--only), 1 remaining node skipped     ← present ✓

TEST 3: -p without --only (regression guard)
  stderr bytes: 0                                ← still silent ✓
```

All three cases verified. Sub-issues 8a and 8b both fixed.

### Verification
- ``make test``: **4660 passed** (+8 from #8 tests: 4 unit + 3 subprocess + 1 updated)
- ``make check``: ruff + ruff-format + mypy + deptry all clean (one C901
  fix via ``_emit_summary_or_only_indicator`` extraction)
- 0 regressions
- Mutation test verified: tests fail on pre-fix code, pass on post-fix

### All review findings shipped
With #8 done, the working tree contains all 12 fixes from the code review:
- Critical (must-fix before merge): #1, #2, #3, #4, #5
- Architectural decisions: #6 (per-worker buffer), #7 (logging filter), #8 (dual emission)
- Straightforward improvements: #9, #10, #11, #12

Branch ready for final commit and merge.

## 2026-04-07 - Deferred-list cleanup batch (#14, #15, #16, #18, +#6 nested)

After completing the 12 must/should items, ran a triage of the
"deferred for follow-up" list from the original review. Three of the
six items were small enough and high-enough value to ship in this
batch; one was a strengthening of an existing test; one item I
originally rated lower-priority (#6 nested-batch test) was added as
strengthening for the most complex of the architectural fixes.

### Triage decisions
| # | Item | Decision | Reason |
|---|---|---|---|
| #14 | Rename ``duration_ms`` slot for warning text | **SHIP** | Real type-confused parameter, footgun for future change |
| #15 | Round-trip-parse JSON in ``test_complex_output_types`` | **SHIP** | Strict improvement, ~5 lines, catches subtle regressions |
| #16 | Add ``err=True`` to verbose ``cli:`` echoes | **SHIP** | Pre-existing bug surfaced by #194 fix, real impact on ``pflow -v foo \| jq`` |
| #18 | Test ``node_warning`` + partial-line interaction | **SHIP** | Natural regression test for #14 |
| #13 | Smart-handled empty-reason fallback | SKIP | YAGNI — no current shell.py path triggers it |
| #17 | Cache hit + nested workflow test | SKIP | General case already covered by ``test_partial_line_reemits_after_interleaved_close`` |
| Trace ``smart_handled`` field | SKIP | Reviewer was wrong — ``test_shell_smart_handling.py:336`` reads it |
| #6 nested-parallel-batch test | **SHIP (optional)** | Strengthens recursive correctness coverage for the most complex of the architectural fixes |

### Verification before recommending
- For #16, grepped main.py for ``cli:`` echoes missing ``err=True``: found 5
  expected (lines 119, 301, 774, 776, 778) PLUS one I missed in the
  initial review (line 139). All 6 fixed.
- For the trace ``smart_handled`` field deletion: verified
  ``tests/test_nodes/test_shell_smart_handling.py:336`` reads
  ``steps[0]["smart_handled"]``. **Reviewer was wrong** — the field is
  consumed by tests. Skipped the deletion. Saved by verification.

### Production fixes

**Fix #14 — Stop overloading ``duration_ms`` for warning text**
- ``runtime/engine/instrumentation.py:491``: changed
  ``callback(node_id, "node_warning", warning, depth)`` to
  ``callback(node_id, "node_warning", depth=depth, error_message=warning)``.
  Warning text now arrives via the properly-named ``error_message``
  kwarg instead of being smuggled through the ``duration_ms`` positional
  slot.
- ``core/output_controller.py::_handle_node_warning``: parameter renamed
  from ``duration_ms`` to ``warning_message``. ``isinstance`` type check
  removed (no longer needed because the parameter actually holds what
  its name says it holds). Generic "API warning" fallback preserved
  via ``warning_message or 'API warning'``.
- ``core/output_controller.py`` callback closure dispatch: updated
  ``_handle_node_warning(node_id, indent, duration_ms)`` to
  ``_handle_node_warning(node_id, indent, error_message)``.

**Fix #16 — All ``cli:`` diagnostics go to stderr (verbose mode bug)**
- 6 ``click.echo`` calls in ``cli/main.py`` were missing ``err=True``:
  - Line 119: ``cli: Cleaned up temp file: ...`` (verbose finally block)
  - Line 139: ``cli: Workflow execution completed`` (verbose success path)
  - Line 301: ``cli: Starting workflow execution with N node(s)``
  - Line 774, 776, 778: workflow loading verbose diagnostics
- All 6 added ``err=True``. Now ``pflow -v foo.pflow.md | jq`` works
  cleanly — only the workflow data lands on stdout.

### Test fixes

**Fix #15 — Round-trip-parse JSON in ``test_complex_output_types``**
- File: ``tests/test_cli/test_workflow_output_handling.py``
- Replaced substring matching (``assert expected_token in result.stdout``)
  with ``json.loads(result.stdout.strip())`` round-trip + structural
  equality check. Catches subtle regressions like trailing whitespace,
  prefix/suffix corruption, partial JSON, that the substring check
  would silently accept.

**Fix #18 — Two new unit tests for ``node_warning`` + partial-line interaction**
- ``test_node_warning_emits_via_error_message_kwarg`` — direct unit
  test that verifies the warning text reaches ``_handle_node_warning``
  via the properly-named ``error_message`` kwarg, with the ⚠️ marker
  rendered. Asserts the generic "API warning" fallback does NOT fire
  when a real warning text is provided.
- ``test_node_warning_after_node_start_terminates_partial_line`` —
  exercises the full warning path: ``node_start`` opens partial line,
  ``node_warning`` renders the warning, partial gets closed.
  Regression guard for both #14 (parameter naming) and the
  partial-line tracking interaction.

**New regression test for #16 (``cli:`` stdout pollution)**
- ``test_verbose_mode_keeps_cli_diagnostics_off_stdout`` in
  ``test_progress_streaming_subprocess.py`` — real subprocess test
  that runs ``pflow -v foo.pflow.md`` and asserts:
  - The data canary is on stdout (GH #194 invariant)
  - Zero ``cli:`` lines on stdout
  - At least one ``cli:`` line IS on stderr (proves the test isn't
    passing because verbose mode is silently broken)

**New strengthening test for #6 (nested parallel batch buffering)**
- ``test_nested_parallel_batch_recursive_buffering`` in
  ``test_progress_streaming_subprocess.py`` — three nesting levels:
  outer parallel batch → middle parallel batch → innermost workflow
  with 2 leaf nodes. Total: 2 outer items × 2 inner items × 2 leaves
  = 8 leaf events, in 4 coherent (leaf_x, leaf_y) pairs.
- Verifies the recursive correctness claim from #6's analysis: an inner
  parallel batch inside a worker thread installs ITS OWN buffering
  wrapper; the inner drain (running in the worker thread of its
  context) flushes events into the outer worker's buffer; the outermost
  main thread eventually drains everything to the real OutputController.
- The test asserts every leaf line is either pure ``leaf_x`` or pure
  ``leaf_y`` (no concatenation) AND that they form 4 consecutive
  pairs (no inter-item interleaving at any nesting level).

### Mutation test verification
Stashed ``instrumentation.py``, ``output_controller.py``, and
``cli/main.py``, then ran the new tests against pre-fix code:

- ``test_node_warning_emits_via_error_message_kwarg``: **FAILED** ✓
  (warning text arrives via ``duration_ms`` slot, not ``error_message``)
- ``test_node_warning_after_node_start_terminates_partial_line``:
  **FAILED** ✓ (same reason)
- ``test_verbose_mode_keeps_cli_diagnostics_off_stdout``: **FAILED** ✓
  (3 ``cli:`` lines polluting stdout, exactly the bug)
- ``test_nested_parallel_batch_recursive_buffering``: PASSED (Fix #6
  in ``batch_executor.py`` was NOT stashed, so the buffering still
  works; this test would catch any regression in the buffering logic
  at any nesting level — already mutation-tested by the simpler #6
  test from earlier)

Restored fixes, all tests pass.

### Visual end-to-end verification

**Three nesting levels (post-fix):**
```
  outer_batch...
    inner_batch...
      leaf_x... ✓ 0.0s        ← innermost #1, item 1's transcript (atomic block)
      leaf_y... ✓ 0.0s
      leaf_x... ✓ 0.0s        ← innermost #2, item 2's transcript (atomic block)
      leaf_y... ✓ 0.0s
    inner_batch... 2/2 0.0s
    inner_batch...
      leaf_x... ✓ 0.0s        ← innermost #3
      leaf_y... ✓ 0.0s
      leaf_x... ✓ 0.0s        ← innermost #4
      leaf_y... ✓ 0.0s
    inner_batch... 2/2 0.0s
  outer_batch... 2/2 0.0s
```

Recursive buffering works at every nesting level. 8 leaf events
form 4 coherent (leaf_x, leaf_y) pairs as expected.

**``-v`` mode after fix:**
```
$ pflow -v workflow.pflow.md > out.txt 2> err.txt
$ grep -c "^cli:" out.txt    # 0  (was 4)
$ grep -c "^cli:" err.txt    # 4  (all on stderr now)
```

### Verification
- ``make test``: **4664 passed** (+4 from this batch: 2 unit + 1 verbose + 1 nested)
- ``make check``: ruff + ruff-format + mypy + deptry all clean
- 0 regressions
- Mutation test verified: 3 of 4 new tests fail on pre-fix code
  (the 4th, nested batch test, is a strengthening test that depends
  on a fix that wasn't reverted)

### Final state of all review items
- **Shipped**: #1, #2, #3, #4, #5, #6, #7, #8, #9, #10, #11, #12, #14, #15, #16, #18
- **Plus**: #6 nested-batch strengthening test
- **Skipped**: #13 (YAGNI), #17 (redundant coverage), trace
  ``smart_handled`` field deletion (reviewer was wrong, field IS read)

**16 of 18 review findings addressed.** Branch ready for final commit.




