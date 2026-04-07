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
