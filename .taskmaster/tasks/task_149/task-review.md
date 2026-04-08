# Task 149 Review: Fix GH #194 + Output Pipeline Consolidation

## Metadata

- **Implementation Date**: 2026-04-07
- **Branch**: `fix/non-interactive-output-stderr`
- **GH Issue**: #194 — "Non-interactive mode routes all output to stderr — agents capturing stdout get nothing"
- **Commits** (newest first):
  - `8cf9d0d0` fix: address Task 149 code review findings (16 issues, mutation-verified)
  - `945ac6b3` test: add causal streaming regression test (FIFO barrier)
  - `7f2d61b3` fix: partial-line corruption + JSON-encode structured outputs (Task 149 follow-up)
  - `8606f645` feat: fix #194 + consolidate output pipeline (Task 149)
- **Final test count**: 4664 passed, 9 skipped (+17 net vs main), `make check` clean
- **Net production LOC**: ~-470 (scaffolding deletion) minus ~+370 (three architectural fixes) = still net deletion
- **Status at review time**: Merge-ready pending TTY manual verification

## Executive Summary

Fixed GH #194 (non-interactive output routed to stderr) by collapsing a three-mode routing system in `_output_with_header` to one Unix-convention rule, unlocking live progress streaming for agents as a direct consequence. The work exposed several latent bugs hidden by the old TTY gate and led to three architectural fixes (`_ProgressPartialLineFilter` for stderr coherence, per-worker event buffer + main-thread atomic drain for parallel batch, dual-emission for `--only` mode confirmation) that now own load-bearing responsibilities across `OutputController`, `batch_executor`, and the CLI summary path.

## Implementation Overview

### What Was Built

**Everything in the original plan**:
- `_output_with_header` collapsed from 3 modes to 14 lines (data→stdout, diagnostics→stderr, `-p` suppresses header)
- Deleted 4 files (~260 LOC): `OutputInterface`, `CliOutput`, `NullOutput`, `DisplayManager`
- `WorkflowRunner.run()` signature: `output: Optional[OutputInterface]` → `progress_callback: Optional[Callable]`
- `OutputController.create_progress_callback()` TTY gate removed; always returns a callable
- `_handle_batch_progress` got internal `sys.stderr.isatty()` guard (only for `\r` overwrite)
- CLI summary collapsed: dropped duplicate `Nodes executed (N):` block from CLI and MCP (parity enforced via `_append_execution_steps`)
- Smart-handled tags (`[no matches]`, `[not found]`) ported from deleted `_format_node_status_line` to live callback via `NamespacedSharedStore` access
- `--print`/`-p` flag kept (Claude Code convention); gated progress off at callsite
- `--output-format json` also gates progress off at callsite

**Additions discovered during adversarial verification (NOT in plan)**:

1. **`_partial_line_open` state machine** on `OutputController`: `_close_partial_line_if_open()` + `_ensure_node_line_open()` + `_partial_line_open: bool`. Required because nested sub-workflow child callbacks and `logger.warning` writes both landed in the middle of parent `node_id...` partial lines.
2. **`logger.warning("Command failed with exit code N")` deleted** from `shell.py:713` — it was bypassing `OutputController` and corrupting partial lines on failure.
3. **JSON encoding in `safe_output`** — `dict`/`list`/`bool`/`number`/`None` outputs were Python-`repr`'d on stdout, unparseable by jq. The #194 fix made this visible for the first time because the data actually landed on stdout. Uses `json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)` with stderr diagnostic on true serialization failure.
4. **Real subprocess regression tests** — 9 tests in `tests/test_cli/test_progress_streaming_subprocess.py` (853 LOC new file). CliRunner intercepts `sys.stderr` via Click's capture machinery, but Python's `logging` module holds a reference to the ORIGINAL stderr from startup. Three of the bugs above are **invisible to CliRunner**. Two CliRunner tests were deleted as test theater.
5. **`_ProgressPartialLineFilter`** (`logging.Filter` with weakref back to OutputController) — installed inside `create_progress_callback`, attaches to root logger `StreamHandler`s whose stream is `sys.stderr`. Closes any open partial line as a side effect of every `filter()` call. Covers all 29 `logger.warning`/`logger.error` sites across node files, plus any future sites added. Top-10% pattern (tqdm/rich).
6. **Per-worker event buffer + main-thread atomic drain** (Pattern 5b) in `batch_executor.py::_execute_parallel.process_item`. The original plan claim "parallel batch invokes callbacks from main thread only" was correct for leaf items but **wrong for parallel batch + sub-workflow**: `WorkflowExecutor` runs in the worker thread and its child engine fires callbacks from the worker thread. A mutation test reproduced literal label-swap corruption in production. The fix: each worker replaces its inherited `__progress_callback__` with a buffering wrapper that captures `(args, kwargs)` tuples; main thread drains via `as_completed` before `_report_batch_progress`. Same model as `pytest-xdist` and `make --output-sync=line`. Recursively correct for nested parallel batches (inner buffer drains into outer buffer).
7. **Dual-emission `--only` mode confirmation** via shared `format_only_indicator` helper. The spec guarded `--only` summary line on `nodes_skipped > 0` (hid it when target was last node) AND `-p` mode suppressed the whole summary (hid it entirely). Both now fixed: long form when skipping, short form when not; always emitted even in `-p` mode via a dedicated `_emit_only_indicator` dispatcher. Rationale: mode flags survive verbosity flags (make/pytest/rsync/apt/kubectl/terraform convention).
8. **Batch count rendering on live line**: `3/5 ⚠️` for partial-failure batches, `5/5` for full success. Agents can now distinguish partial-failure from full-success without waiting for the diagnostic block.
9. **Canonical `node_id...` re-emission shape**: `_ensure_node_line_open` re-emits with the same trailing `...` as `_handle_node_start` so structured stderr parsers see ONE format for completion lines.
10. **`_handle_node_warning` parameter rename**: `duration_ms` slot was being abused to smuggle warning text as a string. Renamed to `warning_message` and `instrumentation.py::handle_api_warning` now passes via `error_message=` kwarg.
11. **6 `cli:` verbose echoes gained `err=True`**: `main.py` lines 119, 139, 301, 774, 776, 778. Pre-existing bug — the #194 fix surfaced it because verbose diagnostics now polluted stdout that jq was reading.

### Implementation Approach

Followed the **7-step research→plan→review→implement→code-review→fix→manual-test** pattern:
1. Research: read braindump, task spec, plan in full before editing
2. Plan: approved with 4 review agents finding 7+ critical issues pre-implementation
3. Implement: started with smallest fix (`_output_with_header`) and worked outward
4. Adversarial verification: ran real subprocess tests AGAINST the "working" implementation, found 4 new critical bugs
5. Fix: partial-line tracking + logger.warning removal + JSON encoding + subprocess tests
6. Code review (8 agents): 18 findings, 3 architectural
7. Batch fix all findings; mutation-test every architectural fix before shipping

**Key architectural principles applied**:
- "Routing is unified, rendering can vary by TTY" — the separation that resolves the #194 root cause
- "OutputController owns stderr coherence" — every path that writes to stderr during progress must coordinate with it (directly or via the logging filter)
- "Workers produce transcripts, single writer drains atomically" — the parallel batch insight
- "Mode flags survive verbosity flags" — the `--only` insight (verbosity hides details, not modes)

## Files Modified/Created

### Production — Modified

| File | What changed |
|---|---|
| `src/pflow/cli/workflow_output.py` | `_output_with_header` collapsed; `safe_output` strict JSON + `default=str` + diagnostic fallback; `_display_execution_summary` dropped per-node loop + always emits `--only`; new `_emit_summary_or_only_indicator` dispatcher + `_emit_only_indicator` helper; `_format_node_status_line` / `_get_status_indicator` / `_format_node_timing` deleted |
| `src/pflow/core/output_controller.py` | `_ProgressPartialLineFilter` class; `_partial_line_open` state + `_close_partial_line_if_open` + `_ensure_node_line_open` helpers; `_install_log_partial_line_guard` idempotent install (weakref); TTY gate removed from `create_progress_callback`; `_handle_batch_progress` internal isatty guard; `_handle_node_complete` split into `_build_smart_handled_tag` + `_emit_non_batch_completion` (ruff C901); `_handle_node_warning` parameter renamed; dead methods deleted (`echo_progress`, `echo_result`, `should_show_prompts`, `_handle_workflow_start`) |
| `src/pflow/execution/runner.py` | Signature: `output: OutputInterface` → `progress_callback: Callable`; simplified `_initialize_shared_store` |
| `src/pflow/execution/formatters/success_formatter.py` | `_append_execution_steps` collapsed; new `format_only_indicator` shared formatter (single source of truth); `_append_outputs` JSON-encodes for MCP/CLI parity |
| `src/pflow/runtime/engine/batch_executor.py` | Per-worker buffering wrapper in `process_item`; new `_drain_worker_buffer` helper; `_collect_parallel_results` drains before `_report_batch_progress` |
| `src/pflow/runtime/engine/instrumentation.py` | `call_completion_callback` passes `smart_handled`/`smart_handled_reason` through via namespaced shared store access; `handle_api_warning` passes warning text via `error_message` kwarg (not `duration_ms` abuse) |
| `src/pflow/cli/main.py` | Removed `CliOutput`/`DisplayManager` usage; unified `progress_enabled = not print_flag and output_format != "json"` gate; 6 `cli:` echoes gained `err=True`; `--print` help text updated |
| `src/pflow/nodes/shell/shell.py` | `logger.warning` on non-zero exit **deleted** (was bypassing OutputController); line 200 comment points at `_handle_node_complete` |
| `src/pflow/mcp_server/tools/execution_tools.py` | Docstring no longer claims "Nodes executed (N)..." block |
| `src/pflow/runtime/workflow_executor.py` | Stale `NullOutput` comment updated |

### Production — Deleted

- `src/pflow/cli/cli_output.py`
- `src/pflow/execution/display_manager.py`
- `src/pflow/execution/null_output.py`
- `src/pflow/execution/output_interface.py`
- `tests/test_integration/test_cli_mcp_parity.py` (vacuous after refactor)

### Tests — Created

- **`tests/test_cli/test_progress_streaming_subprocess.py`** (853 LOC, NEW) — 9 real-subprocess tests. **This is the single most important file in the whole task.** Nothing else catches the corruption modes the fixes address.

### Tests — Modified

| File | Change |
|---|---|
| `tests/test_core/test_output_controller.py` | +555 LOC; deleted tests for removed dead methods; new coverage for `_partial_line_open`, `_ProgressPartialLineFilter`, smart-handled tags, failure terminator, batch count rendering (full-success + partial-failure split), `_handle_node_warning` via `error_message` kwarg, partial-line re-emission after interleaved close; batch-progress tests patch `sys.stderr.isatty=True` (pytest capture breaks the new guard) |
| `tests/test_execution/formatters/test_success_formatter.py` | +447 LOC; deleted `_format_execution_step`/`_format_batch_node_line` tests (helpers deleted); new `TestFormatOnlyIndicator` + `TestAppendOutputsCliMcpParity` (6 tests locking output value parity); updated for `--only` short form |
| `tests/test_cli/test_workflow_output_handling.py` | +160 LOC net; added GH #194 canary, print/JSON mode suppression tests, round-trip JSON parse in `test_complex_output_types`; DELETED two mock-based tests that were test theater |
| `tests/test_cli/test_shell_stderr_warnings.py` | Removed `_format_node_status_line` import and its orphaned tests |
| `tests/test_mcp_server/test_execution_workflow.py` | Relaxed assertion from literal `✓` to `"Workflow completed"`/`"Workflow output:"` substrings |
| `tests/test_nodes/test_shell/test_auto_handling.py` | `test_real_error_logs_warning` → `test_real_error_surfaces_error_via_action_and_shared_store` (asserts canonical failure-reporting path via action + shared store, not removed `logger.warning`) |

## Integration Points & Dependencies

### Load-Bearing Coupling (fragile — touch with care)

| Integration | Where | Fragility |
|---|---|---|
| `shared["__progress_callback__"]` | `instrumentation.py` reads it; `batch_executor.py::process_item` REPLACES it per-worker with a buffering wrapper; `workflow_executor.py::_PROPAGATED_KEYS` propagates it to nested workflows | Any new code reading this key directly bypasses the per-worker buffer and re-introduces the parallel race |
| `_PROPAGATED_KEYS` tuple | `runtime/workflow_executor.py:99-107` — declares which shared-store keys cross from parent to nested child workflows; consumed in `_build_child_storage` around line 521-523 | Contains `__progress_callback__`. Removing it from this tuple silently breaks nested workflow progress (no child events ever reach the parent's OutputController). Nested rendering tests catch the symptom but misdiagnose the root cause as an OutputController bug. This is the single point-of-declaration for the propagation contract |
| `_ProgressPartialLineFilter` → root logger `StreamHandler`s | `cli/logging_config.py::configure_logging` installs one `StreamHandler` whose `stream is sys.stderr`; the filter iterates `logging.getLogger().handlers` and attaches to matches | If logging config changes to use a wrapper stream or multiple handlers, the filter silently attaches to wrong/none |
| `NamespacedSharedStore` rewriting of `shell.py:688-689` writes | `shell.py` writes `shared["smart_handled"] = True`; store redirects to `parent[node_id]["smart_handled"]`; `call_completion_callback` reads from `shared[node_id]["smart_handled"]` | Documented only in code comments. Reading `instrumentation.py` in isolation suggests the value is at root |
| `_partial_line_open` flag | Single bool on `OutputController`. Per-worker buffering eliminated the race, but any future code path that calls `_handle_node_start` directly (not through the callback) bypasses coordination | No test catches direct-call bypass |
| `format_only_indicator` | THREE call sites: `cli/workflow_output.py::_display_execution_summary` (default mode), `cli/workflow_output.py::_emit_only_indicator` (`-p` mode), `success_formatter.py::_append_execution_steps` (MCP) | Drift between sites = CLI/MCP divergence or `-p`/default divergence. Tests lock the parity but only for current call sites |
| `_install_log_partial_line_guard` install timing | Called from `create_progress_callback`. Non-progress modes (`-p`, JSON, MCP) never call it, never install the filter | Correct as designed — but if someone adds progress to those modes without going through `create_progress_callback`, the filter is missing |

### Shared Store Keys

| Key | Set by | Read by | Purpose |
|---|---|---|---|
| `__progress_callback__` | Runner (from `_initialize_shared_store`) | `instrumentation.py` (`call_start_callback`, `call_completion_callback`, `handle_api_warning`, `handle_cached_execution`); `batch_executor.py` (`_report_batch_progress`, and REPLACED per-worker in `process_item`) | Live per-node progress dispatch |
| `shared[node_id]["smart_handled"]` + `smart_handled_reason` | `shell.py:688-689` (via NamespacedSharedStore rewrite) | `call_completion_callback` then progress callback kwargs | Shell classification tag (`[no matches]`, `[not found]`) |
| `__execution__.only_node` | `WorkflowEngine` | `_display_execution_summary`, `_emit_only_indicator`, `success_formatter._append_execution_steps` | `--only` mode confirmation rendering |
| `__execution__.nodes_skipped` | `success_formatter.format_execution_success` | `format_only_indicator` | Long/short form selection |

## Architectural Decisions & Tradeoffs

### Decision 1: `_ProgressPartialLineFilter` via `logging.Filter` (not `logging.Handler`)

**Context**: 29 `logger.warning`/`logger.error` sites across node files corrupt partial progress lines. Options: delete the high-frequency sites individually, install a handler, install a filter, defer.

**Chosen**: `logging.Filter` that calls `_close_partial_line_if_open()` as a side effect before returning `True`.

**Why filter not handler**:
- Filters run as side effects before each handler emits — don't replace existing handlers, can't accidentally swallow records, can't accidentally duplicate output
- Handlers would require replacing pflow's existing `StreamHandler`, which owns its own formatting

**Why weakref back to controller**:
- Tests create and destroy many controllers — a strong ref would pin them alive
- Silent no-op if controller is GC'd (acceptable trade — means "progress is gone, don't coordinate anything")

**Alternative rejected**: delete the 4 high-frequency sites. Rejected because: (1) loses unique diagnostic value from 3 of the 4 sites, (2) doesn't fix the 25 other corruption sites, (3) doesn't fix any future `logger.warning` added to a node, (4) whack-a-mole engineering tax.

**Prior art**: `tqdm.contrib.logging.logging_redirect_tqdm`, `rich.console.Console` + `RichHandler`. Both route logging through the display controller.

### Decision 2: Per-worker event buffer + main-thread atomic drain (Pattern 5b)

**Context**: Parallel batch + sub-workflow per item → worker threads fire `node_start`/`node_complete` events from a child engine on the shared `OutputController`. The original plan claim "parallel batch is main-thread-only" missed this case. Mutation test reproduced literal label-swap corruption.

**Options evaluated**:
- **Pattern 1: `threading.Lock`** — rejected. Produces valid bytes with semantically wrong labels. The flag tracks *whether* a partial is open, not *which node's*. Under concurrent workers executing identical sub-workflows, T1's `inner_a` completion can attach to T2's still-open `inner_a` partial. Valid rendering, wrong semantics.
- **Pattern 3: Suppress all worker callbacks** — rejected. Loses per-child visibility, smart-handled tags, warnings, cached indicators from sub-workflow nodes.
- **Pattern 5b: per-worker buffer + main-thread drain** — chosen. Each worker accumulates `(args, kwargs)` into a thread-local list; main thread drains via `as_completed` before `_report_batch_progress`. Single-threaded by construction. Recursively correct.

**Prior art**: `pytest-xdist` worker transcripts, `make --output-sync=line`.

**Recursive correctness**: inner parallel batches inside worker threads install THEIR OWN buffering wrapper on sub-items' shared store. Events accumulate in the inner buffer; the inner drain (running in the worker thread that's single-threaded for that nesting level) flushes into the outer worker's buffer; the outermost main thread drains everything to the real `OutputController`. Verified by `test_nested_parallel_batch_recursive_buffering`.

**Trade**: real-time interleaving across workers is lost. This was a non-loss — the interleaving was never working correctly (it was racy) and couldn't be done correctly without per-line item-id tagging. Pattern 5b is strictly the correct trade.

### Decision 3: Dual-emission `--only` with shared `format_only_indicator`

**Context**: Two sub-issues — `nodes_skipped > 0` gate hid the line when target was the last node (8a); `-p` mode suppressed the whole summary including `--only` line (8b).

**Options evaluated**:
- **Move `--only` line out of `_display_execution_summary` to `_handle_text_output`** — rejected. Changes default-mode rendering ordering (`--only` would print BEFORE completion tag), visible regression, breaks existing assertions.
- **Keep current gating, document** — rejected. Agent-UX regression.
- **Dual-emission with shared formatter** — chosen. Default mode still emits inside summary; `-p` mode emits just the indicator via `_emit_only_indicator`; both use the shared `format_only_indicator` helper.

**Why `format_only_indicator` is a separate function**:
- Three call sites (CLI default, CLI `-p`, MCP text)
- Without it, each site's drift produces CLI/MCP divergence
- Short-form vs long-form logic lives in one place

**Prior art surveyed before implementing**: `make -k`, `pytest --maxfail`, `rsync --dry-run`, `apt-get --simulate`, `kubectl --dry-run`, `terraform plan`. **Unanimous**: mode flags are announced regardless of verbosity flags. Verbosity hides details; mode flags survive verbosity.

### Decision 4: CLI/MCP parity via `_append_outputs` JSON encoding

**Context**: Fix #1 originally JSON-encoded structured outputs only in CLI `safe_output`. Code review caught that MCP `_append_outputs` still did `str(first_value)` — exactly the Task 85 "update BOTH call sites" regression the plan was supposed to enforce.

**Chosen**: mirror CLI behavior in MCP formatter. New `TestAppendOutputsCliMcpParity` class (6 tests) locks the contract permanently.

**Trade**: adds `import json` to `success_formatter.py` but this is unavoidable for parity.

### Technical Debt Incurred

None significant. The three architectural fixes are solutions, not shortcuts. Deferred items:
- `_build_smart_handled_tag`'s `elif reason:` fallback branch is unreachable given current `shell.py` reason strings (defensive dead code, LOW priority)
- Manual TTY verification of interactive `\r` batch counter rendering (can't be done from Bash sandbox)
- No standalone test for the `--only` + cache-hit + nested workflow + non-TTY four-way interaction (general case is covered)

## Testing Implementation

### Critical Wisdom: Subprocess Over CliRunner

**The single most important lesson from this task**: CliRunner is unsafe for any test that validates stderr coherence under real-world conditions.

**Why**: Click's `CliRunner` intercepts `sys.stderr` via its own capture machinery. But Python's `logging` module holds a reference to the **original stderr** from when `logging.basicConfig` ran at CLI startup. `logger.warning` writes land on the original stderr, not the CliRunner-captured one. **The corruption is invisible to CliRunner but visible to real agents.**

**Concrete bugs missed by CliRunner tests but caught by subprocess tests**:
1. `logger.warning("Command failed with exit code 1")` concatenating onto `will_fail...` partial line (Finding #3)
2. Nested child `node_start` concatenating onto parent `nested_call...` partial line (Finding #2)
3. Parallel batch sub-workflow label-swap races (Finding #6)
4. `cli:` verbose diagnostics polluting stdout (Fix #16)
5. `--only` mode confirmation missing when target was last node (#8a)
6. `--only` mode confirmation missing in `-p` mode (#8b)
7. Live streaming vs buffered delivery (FIFO causal test)

**Test theater deleted**:
- `test_failing_node_emits_terminator_in_live_progress` — mocked `WorkflowRunner.run` so engine never ran, negative assertion trivially true
- `test_real_failing_shell_node_terminates_progress_line` — CliRunner version, couldn't catch `logger.warning` bypass

### Critical Test Cases (the ones that catch real bugs)

**Four tests form the critical core** — each uniquely guards a regression class nothing else catches. Removing or breaking any one leaves a silent gap in coverage:

1. `test_workflow_data_goes_to_stdout_not_stderr_gh194` (CliRunner, in `test_workflow_output_handling.py`) — THE #194 fix. CliRunner is adequate here because routing doesn't involve `logger.*`, only `click.echo` stream selection, which CliRunner captures correctly. Guards against any future TTY-detection-in-routing regression.
2. `test_progress_streams_before_downstream_nodes_complete` (subprocess + FIFO barrier) — the user's #1 stated motivation (live streaming). The only test in the suite that distinguishes "bytes arrive incrementally" from "bytes arrive at process exit". Guards against any future buffering regression, TTY-gate restoration, or progress event batching.
3. `test_failing_shell_node_progress_line_is_clean` (subprocess) — `_ProgressPartialLineFilter` coordination. Any new `logger.*` site in a node or filter install-path refactor can silently reintroduce `node_id...WARNING: ...` corruption. This is the canary for all 29+ existing `logger.warning`/`logger.error` sites and any future ones.
4. `test_parallel_batch_sub_workflow_renders_coherent_per_item_blocks` (subprocess) — per-worker buffer in `batch_executor.py`. Label swaps under parallel batch produce valid bytes with wrong semantics — silent corruption that nothing else in the suite catches.

The remaining tests below are regression guards for specific fixes, not core coverage.

**Subprocess tests** (`tests/test_cli/test_progress_streaming_subprocess.py`):

| Test | Catches |
|---|---|
| `test_failing_shell_node_progress_line_is_clean` | `logger.warning` bypass corruption (Finding #3 regression) |
| `test_nested_workflow_progress_lines_are_not_concatenated` | Nested child interleaving parent partial line (Finding #2 regression) |
| `test_parallel_batch_sub_workflow_renders_coherent_per_item_blocks` | Per-worker buffering regression (#6) — 4 items × 2 children = 8 events must form 4 pairs |
| `test_nested_parallel_batch_recursive_buffering` | 3-level nesting: 2 outer × 2 inner × 2 leaves = 8 events must form 4 pairs at deepest level |
| `test_progress_streams_before_downstream_nodes_complete` | Causal streaming test via FIFO barrier. Blocks step_1 in `cat <fifo>`, asserts step_0's completion arrives on stderr while step_1 is still blocked. Non-flaky (no wall-clock math). Listed as #2 in the critical-core list above |
| `test_verbose_mode_keeps_cli_diagnostics_off_stdout` | Any future `cli:` echo missing `err=True` |
| `test_only_with_last_node_emits_indicator` | Sub-issue 8a regression |
| `test_print_mode_with_only_emits_indicator` | Sub-issue 8b regression |
| `test_print_mode_without_only_stays_silent` | Guards the above from over-correcting |

**Unit tests**:
- `test_partial_line_reemits_after_interleaved_close` — fast regression guard for nested re-emission
- `test_log_filter_closes_partial_line_on_emit` — unit of filter in isolation
- `test_install_log_partial_line_guard_is_idempotent` — filter stacking guard
- `test_logger_warning_through_real_logging_closes_partial_line` — end-to-end that catches install-path breakage
- `test_node_warning_emits_via_error_message_kwarg` — guards against kwarg regression (#14)
- `TestAppendOutputsCliMcpParity` (6 tests) — locks CLI/MCP output value parity

**Mutation-tested fixes** (each architectural fix was stashed and the test re-run against pre-fix code to verify the test actually catches the regression):
- FIFO causal streaming test: stashed TTY gate restoration → test FAILED with exact message it was designed for
- Nested partial-line rendering: stashed partial-line tracking → test FAILED with visible corruption
- Per-worker buffer: stashed buffering → test FAILED with 7 valid lines instead of 8 + label swaps
- `--only` fixes: stashed production changes → 8a test FAILED with empty stderr, 8b test FAILED with stderr=''
- `node_warning` kwarg: stashed production changes → tests FAILED

## Unexpected Discoveries

### Gotchas Encountered

1. **CliRunner is a liar for stderr coherence tests.** Stated above — this is the #1 takeaway. Any test touching `logger.*` behavior during progress must be a subprocess test.

2. **`pytest` replaces `sys.stderr` with a non-TTY capture stream by default.** After adding the internal `sys.stderr.isatty()` guard inside `_handle_batch_progress`, 5 batch-progress tests started silently short-circuiting. Fix: `patch.object(sys.stderr, "isatty", return_value=True)` in those tests.

3. **`git checkout <single-file>` reverts to HEAD, not "before my last edit".** Wiped unstaged tests during mutation testing. Recovery required `git fsck --lost-found` + scanning dangling blobs. Lesson: when reverting a single debug edit, use `git diff | git apply -R` on the specific hunk, not a blanket checkout.

4. **`_format_execution_step` and `_format_batch_node_line` were imported directly by tests.** The plan claimed they'd become dead after the per-node loop deletion. They did — but test updates had to happen first or deletion broke imports.

5. **`tests/test_mcp_server/test_execution_workflow.py` asserted on literal `✓`.** After the summary unified across CLI/MCP, degraded-success runs emit `⚠️` instead. Updated to assert on stable semantics (`"Workflow completed"`, `"Workflow output:"`, actual data) rather than a specific glyph.

6. **The spec claim "parallel batch is main-thread-only" was wrong for `WorkflowExecutor` batches.** `_execute_single_node` doesn't fire callbacks (correct), but `WorkflowExecutor.exec()` creates a child `WorkflowEngine` whose `_execute_node` fires `call_start_callback` / `call_completion_callback` from the worker thread. Verified empirically with mutation test that reproduced corruption in production.

7. **32 `logger.warning`/`logger.error` sites across 9 node files were latent corruption sites.** Only fired once the TTY gate was removed. Deleting 4 individually would have been whack-a-mole; the `_ProgressPartialLineFilter` handles all 29 + any future ones.

8. **`safe_output` emitting structured values as Python `repr` was a pre-existing bug invisible until #194 was fixed.** Agents using `pflow foo | jq .key` got nothing until the data actually reached stdout. The #194 fix surfaced it, making the JSON encoding NOT a feature creep — it was completing the contract.

9. **`--only` summary line was gated on `nodes_skipped > 0` which hid it when the target was the last node.** `-p` mode then suppressed the whole summary including the `--only` line. Agent running `pflow -p foo --only target | jq` got 0 bytes of mode signal on stderr, indistinguishable from a full run.

10. **`_handle_node_warning` was smuggling warning text through the `duration_ms` parameter** as a string. `isinstance` type check on the receiving end kept it working but the parameter name lied about its content. Renamed to `warning_message` and call site updated to `error_message=` kwarg.

### Edge Cases Found

- **Nested sub-workflow progress in non-TTY**: the plan assumed it would "just work" via `__progress_callback__` propagation. It kind of did — lines arrived, but the parent's partial line was corrupted by the child's first `node_start`. Fixed by partial-line tracking + re-emission.
- **Parallel batch with identical sub-workflow child node names**: label swaps were SILENT. Same `child_a` name across workers made the corruption valid bytes with wrong labels.
- **`default=str` inside `json.dumps`**: coerces datetime/Path/set/dataclass INSIDE the JSON document (value becomes a JSON string). Without this, those types crash. With this, output stays parseable.
- **`allow_nan=False` in `json.dumps`**: jq rejects `NaN`/`Infinity` tokens. Default `allow_nan=True` would silently produce invalid JSON.
- **Batch success count rendering edge case**: `batch_total is None` or `batch_success_count is None` → omit the count tag entirely (not `None/None`).

## Patterns Established

### Pattern A: OutputController Owns Stderr Coherence

**Rule**: Any code that writes to stderr during progress rendering must coordinate with `OutputController._partial_line_open` or flow through the `_ProgressPartialLineFilter` (installed automatically for `logger.*` writes).

**How**: call `self._close_partial_line_if_open()` before starting a new line. Use `self._ensure_node_line_open(node_id, indent)` when emitting a completion that expects a preceding `node_id...` lead-in.

**Reusable insight**: a `logging.Filter` with a weakref back to a coordination object is a clean way to get "run before every emit" semantics without replacing handlers. The side effect IS the point; `filter()` always returns True.

```python
class _ProgressPartialLineFilter(logging.Filter):
    def __init__(self, controller):
        super().__init__()
        self._controller_ref = weakref.ref(controller)
    def filter(self, record):
        ctrl = self._controller_ref()
        if ctrl is not None:
            ctrl._close_partial_line_if_open()
        return True  # Never filter; side effect is the point
```

### Pattern B: Per-Worker Event Buffer + Main-Thread Atomic Drain (Pattern 5b)

**Rule**: For parallel work that needs to render progress atomically per-unit-of-work, workers don't share output state — they produce transcripts (sequences of events) which a single-writer drains atomically.

**How**: in `process_item`, replace the inherited callback with a per-thread buffering wrapper; return the buffer as part of the future result; in `_collect_parallel_results`, call `_drain_worker_buffer(real_callback, buffered_events)` before any shared-state writes.

**Recursive correctness**: works at arbitrary nesting depth because each nesting level installs its own buffer on its sub-items' shared store. Inner drains run in whatever thread is single-threaded for their nesting context.

**Prior art**: `pytest-xdist`, `make --output-sync=line`. Use this pattern for any future parallel rendering (not just progress — any shared mutable display state).

### Pattern C: Mode Flags Survive Verbosity Flags

**Rule**: Mode flags (what the tool does: `--only`, `--dry-run`, `--force`) are always announced. Verbosity flags (how much output: `-p`, `-q`, `-v`) hide details, never modes.

**How**: use a shared formatter (`format_only_indicator`) as single source of truth. Dispatch to full summary OR just-mode-signal based on verbosity. Never gate the mode signal on a count being > 0 or similar.

**Prior art**: make `-k`, pytest `--maxfail`, rsync `--dry-run`, apt-get `--simulate`, kubectl `--dry-run`, terraform `plan`.

### Pattern D: Routing vs Rendering Separation

**Rule**: Routing (which stream bytes go to) is unified with zero TTY checks. Rendering (how bytes look — cursor tricks, colors) can vary by TTY but ONLY inside the specific branches that need it.

**Anti-example**: the original `_output_with_header` used TTY detection for routing, which is the #194 bug root cause.
**Example done right**: `_handle_batch_progress` gates only its `\r` overwrite on `sys.stderr.isatty()`. The rest of the rendering pipeline is TTY-agnostic.

### Pattern E: Subprocess Tests for Agent-UX Validation

**Rule**: When a test validates behavior an agent would observe (stderr stream separation, live streaming, `logger.*` coherence, pipe routing), use a real subprocess. CliRunner cannot represent the real `sys.stderr` file descriptor.

**How**: `subprocess.run([uv_exe, "run", "pflow", ...], capture_output=True, text=True, env=isolated_env)`. Use `Popen` + `_wait_for_stderr_marker` when you need to observe streaming behavior during execution.

**FIFO barrier pattern for causal tests**: when testing "this must arrive before that", pin "that" in a known-blocked state via `os.mkfifo` + `cat <fifo>`, verify "this" is visible, then unblock the FIFO. No wall-clock math — non-flaky by construction.

### Pattern F: Self-Describing Values Through Passthrough Kwargs

**Rule**: When a value needs to flow from a producer (e.g., `shell.py`) through multiple layers (instrumentation, callback, handler) to a renderer, pass it as a properly-named kwarg through every layer. Never abuse unrelated parameter slots.

**Example fixed**: `_handle_node_warning` was abusing `duration_ms: Optional[float]` to carry a string warning message. Fixed by renaming to `warning_message` and updating `handle_api_warning` to pass `error_message=warning`.

**Example done right**: `smart_handled` and `smart_handled_reason` flow from `shell.py` → `NamespacedSharedStore` → `call_completion_callback` → progress callback → `_handle_node_complete` → `_build_smart_handled_tag`. Every layer has properly-named parameters.

## Anti-Patterns to Avoid

1. **Don't gate ROUTING on TTY state.** Ever. Routing is unified; TTY gates belong inside specific rendering branches.
2. **Don't add `click.echo("...", err=True)` from inside a node's `prep`/`exec`/`post`.** Bypasses `OutputController` + the logging filter. Use `logger.warning(...)` instead — the filter handles it.
3. **Don't add `click.echo("...")` without `err=True` for a diagnostic.** Pollutes stdout that consumers pipe to jq.
4. **Don't use CliRunner for stderr coherence tests.** Add a subprocess test alongside.
5. **Don't gate mode signals on verbosity flags or on "did anything interesting happen" counts.** Mode signals are always shown; verbosity hides details.
6. **Don't assume parallel batch is main-thread-only for callbacks.** It IS for leaf items, it is NOT for sub-workflows. The per-worker buffer is load-bearing.
7. **Don't mock `WorkflowRunner.run` to test display behavior.** The test becomes theater — the code path under test never runs.
8. **Don't delete a formatter helper without `rg`-ing `src/ tests/` for callers first.** Plan claimed `_format_execution_step` was dead; tests imported it directly.
9. **Don't smuggle strings through numeric parameter slots.** Rename the parameter if its meaning changes.
10. **Don't use `str(value)` for structured outputs on stdout.** Agents pipe to jq; `{'key': 'value'}` is not JSON.

## Breaking Changes

### API/Interface Changes

- **`WorkflowRunner.run()` signature**: `output: Optional[OutputInterface] = None` → `progress_callback: Optional[Callable] = None`. MCP server already passed nothing, unaffected. Any external caller using the old kwarg is broken. MVP policy: no compat shim.
- **`OutputController._handle_node_complete` signature**: added `node_id`, `indent`, `smart_handled`, `smart_handled_reason` parameters. Internal — only called from the progress callback closure.
- **`OutputController._handle_node_cached` / `_handle_node_warning` signatures**: added `node_id`, `indent` parameters.
- **`_output_with_header`, `_handle_text_output`, `_try_declared_outputs`, `_emit_declared_output`, `_handle_workflow_output`**: removed `output_controller` parameter.
- **Deleted public symbols**: `OutputInterface`, `CliOutput`, `NullOutput`, `DisplayManager`, `_format_node_status_line`, `_get_status_indicator`, `_format_node_timing`, `_format_execution_step`, `_format_batch_node_line`, `OutputController.echo_progress`, `OutputController.echo_result`, `OutputController.should_show_prompts`, `OutputController._handle_workflow_start`.

### Behavioral Changes

- **`pflow workflow.pflow.md` in non-TTY writes data to stdout** (was: stderr). This is the #194 fix. Breaks any consumer relying on the old stderr-routed behavior.
- **Progress is streamed live in non-TTY mode** (was: silent then static summary). Agents now see per-node progress as nodes complete.
- **`--only` mode confirmation is ALWAYS emitted when active** (was: hidden when `nodes_skipped == 0` or in `-p` mode). Short form (`⤷ Stopped after 'X' (--only)`) when 0 skipped, long form otherwise.
- **Structured outputs on stdout are JSON-encoded** (was: Python `repr`). `pflow foo | jq` now works for dict/list/bool/number/null outputs. NaN/Infinity rejected (jq-compatible).
- **Batch success/failure counts on live line**: `3/5 ⚠️` for partial, `5/5` for full success. Previously no count on live line.
- **`shell.py` no longer emits `logger.warning("Command failed with exit code N")`** on non-zero exit. The same info is still in `shared["error"]` and rendered via the diagnostic block + live failure terminator.
- **`⚠️ Workflow completed` (not `✓`) for degraded success** — shell nodes that write stderr but exit 0 → summary now uses ⚠️. Fixed test_execution_workflow.py assertions accordingly.

## Future Considerations

### Extension Points

- **New stderr-writing code paths during progress**: must either use `OutputController._handle_*` methods OR flow through `logger.*` (filter handles it). Do NOT use raw `click.echo(..., err=True)` from inside nodes.
- **New node types**: `smart_handled` tag pattern is extensible — write `shared["smart_handled"] = True, smart_handled_reason = "..."` in node `post()`. For the tag to render, the reason string should contain "no matches" or "not found", or the raw reason will be used as fallback (yellow `[reason]`).
- **New parallel execution patterns**: follow Pattern 5b (per-worker buffer + main-thread drain). Don't add locks around shared display state.
- **New `--only`-like mode flags**: add a `format_<flag>_indicator` helper in `success_formatter.py`, emit via dual-emission pattern (full summary in default mode, just the indicator in `-p`).

### Scalability Concerns

- **Per-worker buffer memory**: each worker accumulates all events until drained. For long-running sub-workflows with many events, this is O(events_per_item × max_concurrent). Not currently a problem; monitor if sub-workflow depth or event density grows significantly.
- **`_ProgressPartialLineFilter` attach loop**: iterates `logging.getLogger().handlers` every time `_install_log_partial_line_guard` is called. Idempotent (tracked by `_log_filter_installed`), so called once in practice. No concern.
- **`format_only_indicator` call count**: three sites, each called once per workflow run. No concern.

### Open Questions / Fragile Areas

- **What if someone future-refactors logging to use a wrapper stream?** The filter's `handler.stream is sys.stderr` check would fail silently. Add a test that verifies the filter is attached after `configure_logging` runs.
- **What if `cli/logging_config.py` installs multiple handlers?** Filter attaches to all matches. Harmless but means multiple side effects per emit. Not broken, just suboptimal.
- **`configure_logging` is a no-op under `PYTEST_CURRENT_TEST`** (`cli/logging_config.py:27-28`) and only installs a handler if none exists yet (`not logging.getLogger().handlers`, line 31). Two consequences: (1) tests that construct an `OutputController` and expect the filter to "just work" need to manually install a `StreamHandler` against `sys.stderr` — `test_logger_warning_through_real_logging_closes_partial_line` does this explicitly; (2) a library consumer that imports pflow after touching logging elsewhere could end up with no pflow handler at all, making `_install_log_partial_line_guard` a no-op filter-attach loop. Production CLI path is fine (startup runs early enough), but both paths are silent bear traps for new test/library authors.
- **What if a node adds `print("...", file=sys.stderr)` directly?** The filter doesn't intercept `print` — only `logger.*`. A raw `print` would corrupt partial lines. Add a pre-commit hook to ban raw `print` in node files? (YAGNI for now.)
- **`is_interactive()` has one caller left** (`cli/mcp_sync.py`). Deleting it is out of scope but would be a nice followup when refactoring mcp_sync.

## AI Agent Guidance

### Quick Start for Related Tasks

**If you're fixing an agent-UX or stderr-related bug**:
1. **Read this file first.** Then `src/pflow/core/output_controller.py` in full — it's the mental model.
2. **Write a subprocess test FIRST** in `tests/test_cli/test_progress_streaming_subprocess.py`. Use the existing fixtures (`subprocess_env`, `_run_pflow`, `_skip_if_uv_sandbox_panics`).
3. **Never add a CliRunner test for stderr coherence.** It will give false assurance.
4. **If touching parallel batch rendering**: read `batch_executor.py::process_item` + `_drain_worker_buffer` + `_collect_parallel_results` — understand the buffer-drain-atomic model before editing.

**If you're adding a new node type and want live tags**:
1. Write values to `shared[key]` from `post()` (which the `NamespacedSharedStore` rewrites to `parent[node_id][key]`).
2. Read them in `instrumentation.py::call_completion_callback` via `node_output.get("key")`.
3. Pass through to the callback via kwargs.
4. Render in `_handle_node_complete` via a helper similar to `_build_smart_handled_tag`.
5. Add a subprocess test that exercises the real path.

**If you're adding a new mode flag** (like `--only`):
1. Add a `format_<mode>_indicator` helper in `execution/formatters/success_formatter.py`.
2. Emit via dual-emission: default mode inside `_display_execution_summary`, `-p` mode via a dedicated `_emit_<mode>_indicator` helper.
3. Update `_emit_summary_or_only_indicator` dispatcher.
4. Add subprocess tests for: default mode, `-p` mode, `-p` mode + other verbosity flags, edge cases (mode flag with target being last node, etc.).

**If you're touching `OutputController`**:
1. Understand the `_partial_line_open` state machine first. Every non-batch completion handler must call `_ensure_node_line_open` before appending.
2. Any new `click.echo(..., nl=False)` → set `self._partial_line_open = True`.
3. Any new writer that is NOT a completion (e.g., a mid-execution notice) → call `_close_partial_line_if_open()` first.
4. If it writes via `logger.*`, the filter handles it. If it writes via `click.echo` directly, coordinate manually.

**If you're changing the runner signature or shared store keys**:
1. Check `workflow_executor.py::_PROPAGATED_KEYS` — any key that should cross workflow boundaries must be in that tuple.
2. Check `batch_executor.py::process_item` — any key the per-worker buffer needs to replace must be handled there.
3. Check `mcp_server/services/execution_service.py` — MCP passes no progress callback; signature changes there are safe only if they default to None.

### Key Files to Read First (in order)

1. **`.taskmaster/tasks/task_149/task-review.md`** (this file) — the context bridge
2. **`src/pflow/core/output_controller.py`** — the mental model
3. **`tests/test_cli/test_progress_streaming_subprocess.py`** — the regression guards (and the wisdom of the FIFO causal test)
4. **`src/pflow/runtime/engine/batch_executor.py::_execute_parallel`** — the per-worker buffering pattern
5. **`src/pflow/runtime/engine/instrumentation.py::call_completion_callback`** — the callback dispatch
6. **`src/pflow/cli/workflow_output.py::_output_with_header`** — the actual #194 fix (14 lines)
7. **`src/pflow/execution/formatters/success_formatter.py::format_only_indicator`** — the mode-signal pattern
8. **`.taskmaster/tasks/task_149/starting-context/braindump-20260407-planning.md`** — the tacit context from the planning phase

### Common Pitfalls

- **"I'll add a CliRunner test for this"** → STOP. Use subprocess. See Pattern E.
- **"I'll add `click.echo(..., err=True)` in this node to debug"** → STOP. Use `logger.warning`. The filter handles coordination.
- **"I'll add a `threading.Lock` around `OutputController`"** → STOP. Bytes become valid but semantically wrong (label swaps). Use Pattern 5b.
- **"I'll gate the mode signal on `nodes_skipped > 0`"** → STOP. Mode signals survive verbosity/counts.
- **"I'll mock `WorkflowRunner.run` to avoid the engine overhead"** → STOP. Check if the code path under test even runs. See "test theater" above.
- **"I'll delete this helper — `rg` only finds internal callers"** → STOP. Also check `tests/` for direct imports.
- **"I'll add `warnings.warn(...)` or `sys.stderr.write(...)` from a node"** → STOP. Both bypass the logging filter.
- **"I'll change `_format_execution_step` formatting"** → That function was deleted. If you see it in git history, you're looking at pre-Task-149 code.

### Test-First Recommendations

When modifying progress/output behavior:
1. **Write the subprocess test first** — it will fail, and the failure message tells you what's broken.
2. **Mutation-test your fix** — stash it, verify the test FAILS with a clear message; unstash, verify it PASSES. If the test passes both ways, it's theater.
3. **Run the 4 critical-core tests as a group** when touching `OutputController`, `create_progress_callback`, `batch_executor.py::process_item`, or `_output_with_header`. They're fast (~1-2s each) and each catches a different regression class. See "Critical Test Cases" above for the tier.
4. **Check `make test` for `test_progress_streaming_subprocess` — if any skip, check `_skip_if_uv_sandbox_panics`** — they skip cleanly in sandboxed uv environments but should run in real test environments.

---

*Generated from implementation context of Task 149 by the agent that shipped the implementation.*
