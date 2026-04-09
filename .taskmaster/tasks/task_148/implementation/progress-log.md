# Task 148 Implementation Progress Log

## Initial Context

- Scope: implement Task 148 exactly in plan order unless verified code reality requires a deviation.
- Pre-implementation addenda from user:
  - Phase 3 Action 3 in the plan uses a placeholder docstring for `extract_node_ids_from_template`; implementation must patch against the real multi-line docstring in `src/pflow/runtime/engine/error_context.py`.
  - Template-error title consistency is now part of scope: use the canonical title `Template Resolution Failed` everywhere for this error class.
- Verified before editing:
  - `resolve_coalesce()` still uses root membership in context and should stay unchanged.
  - Failed-node data is still read directly from `shared[node_id]` in multiple post-engine consumers.
  - `OutputResolutionError` still uses invalid category `runtime`.
  - `error_context.py` contains the real multi-line docstring, not the plan placeholder.
  - The repro workflow exists at `scratchpads/issue-208/repro.pflow.md`.
- Constraint discovered during verification:
  - `uv run ...` needs a writable cache override in this sandbox because the default uv cache path is not accessible.

## Phase 1

- Status: completed
- Goal: add `runtime/node_state.py`, add `TemplateResolver.extract_root_node_id()`, and establish the new invariant helpers before touching engine flow.
- Implemented:
  - Added `src/pflow/runtime/node_state.py` exactly as planned.
  - Added `TemplateResolver.extract_root_node_id()` in `src/pflow/runtime/template_resolver.py`.
- Verification:
  - Narrow helper/import check passed with `PYTHONPATH=src .venv/bin/python ...`.
- Important note:
  - In this sandbox, repo-local `.venv/bin/python` works reliably for targeted verification, while `uv run` is failing for environmental reasons unrelated to the code.

## Phase 2

- Status: completed
- Goal: funnel engine failure paths through `mark_node_failed()` as the last failure-step and clear stale failures on loop re-entry.
- Implemented:
  - `enforce_loop_guard()` now clears stale failure records on revisit.
  - `handle_api_warning()` now archives failed-node data after trace/callback work.
  - `_execute_node()` now archives returned-error actions on the happy path and exceptions on the exception path.
  - `_handle_no_successor()` now rolls back success bookkeeping and archives routing failures via `mark_node_failed()`.
- Critical insight:
  - The plan’s “move happens last” constraint is important because trace, metrics, and completion callbacks still read `shared[node_id]` directly.

## Phase 3

- Status: completed
- Goal: migrate post-engine consumers to `get_node_output()` / `get_node_failure()` and make the shared-store invariant observable everywhere.
- Implemented:
  - Migrated error extraction, stderr enrichment, child workflow error extraction, optional-input absent detection, output resolution diagnosis, and execution step building.
  - Replaced direct failed-node reads in `executor_service.py`, `error_context.py`, `workflow_executor.py`, `output_resolver.py`, and `execution_state.py`.
- User-requested plan correction applied:
  - `error_context.extract_node_ids_from_template()` was patched against the real multi-line docstring, not the placeholder shown in the plan.

## Phase 4

- Status: completed
- Goal: eliminate remaining external reaches into `TemplateResolver._ROOT_SPLIT_PATTERN`.
- Implemented:
  - Swapped `core/workflow/data_flow.py` to the new public `TemplateResolver.extract_root_node_id()` helper.

## Phase 5

- Status: completed
- Goal: replace raw-string template errors with structured Diagnostics and unify rendering.
- Implemented:
  - Rewrote `runtime/engine/template_errors.py` around `classify_unresolved_references()` and `build_template_error_diagnostic()`.
  - Reworked `core/diagnostic.py` to render per-reference failed/absent/path-error blocks and coalesce-wide failure summaries.
  - Routed template-resolution `ValueError`s through attached structured Diagnostics.
  - Reworked `OutputResolutionError.to_diagnostics()` to use `category="template_error"` and the same renderer.
  - Normalized template-error titles to the canonical `Template Resolution Failed`.
- Intentional deviation from plan:
  - Failure display fields are exposed both at `failure.data` and directly on the `failure` object. This preserves the planned renderer shape while making the structured payload easier for tests/consumers to use.

## Phase 6

- Status: completed
- Goal: track output `source:` line numbers from markdown parsing into runtime diagnostics.
- Implemented:
  - Added per-item YAML line tracking and parsed-key tracking in `markdown_parser.py`.
  - `_build_output_dict()` now records `_source_line` for inline and code-block `source` declarations.
  - Output resolution already propagates `source_line` / `source_file` into diagnostics.
- Plan gap discovered and resolved:
  - Adding `_source_line` to output definitions broke validation because output schema disallowed extra fields.
  - Fixed by extending `src/pflow/core/ir_schema.py` to allow internal output `_source_line` metadata, matching the existing internal `_source_lines` pattern used for nodes.

## Phase 7

- Status: completed
- Goal: document the new invariant and the unified failure write path.
- Implemented:
  - Updated `src/pflow/runtime/CLAUDE.md` with the `__failures__` key and the node execution state invariant.
  - Updated `src/pflow/runtime/engine/CLAUDE.md` to document loop re-entry cleanup and `mark_node_failed()`.

## Phase 8

- Status: completed
- Goal: add regression coverage, migrate existing tests that encoded the old invariant, and run verification.
- Implemented:
  - Added new regression suites:
    - `tests/test_runtime/test_node_state.py`
    - `tests/test_integration/test_failed_node_invariant.py`
    - `tests/test_runtime/test_template_error_messages.py`
    - new failed-node coalesce coverage in `tests/test_runtime/test_template_coalesce.py`
  - Updated existing tests that assumed failed nodes remain in `shared[node_id]`.
  - Updated older message assertions to the new structured template-error rendering.
- Verification completed:
  - `PYTHONPATH=src .venv/bin/pre-commit run -a` passed.
  - `PYTHONPATH=src .venv/bin/mypy` passed.
  - `PYTHONPATH=src .venv/bin/deptry src` passed.
  - `HOME=$PWD/.home TMPDIR=$PWD/.tmp PYTHONPATH=src .venv/bin/python -m pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py` passed: `4697 passed, 5 skipped`.
  - `HOME=$PWD/.home TMPDIR=$PWD/.tmp PYTHONPATH=src .venv/bin/pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace` produced `fallback-content`.
  - Manual no-coalesce output check showed the new structured template error with source line and paste-able coalesce fix.
  - `--report` run succeeded and wrote a trace + report under the repo-local test home.
- Environment note:
  - `make check` / `uv` remain unusable in this sandbox because the `uv` binary panics on this host. Equivalent repo-local tool commands were run instead.

## Phase 9

- Status: completed externally
- Goal: file the three follow-up GitHub issues from the plan.
- Existing issues:
  - `spinje/pflow#233` — Sub-workflow Diagnostic propagation flattens to plain string at parent boundary
  - `spinje/pflow#234` — Distinguish "node not declared in workflow" from "branch not taken" in absent-node errors
  - `spinje/pflow#235` — Replace `runner._extract_runtime_warnings` canned suggestions with actionable signal
- Note:
  - These follow-up issues were already filed outside this implementation session, so no GitHub action was required here.

## Post-Completion UX Tweak

- Status: completed
- Change:
  - Adjusted output-resolution template error rendering so singular output failures read `In output 'content':` instead of the awkward `In parameter 'output 'content''`.
- Files:
  - `src/pflow/core/diagnostic.py`

## Post-Completion Regression Tests

- Status: completed
- Rationale:
  - Added only high-value tests that exercise real invariant risks, not coverage padding.
- Added:
  - Real engine loop re-entry recovery test: failed first visit, successful second visit, final state must be succeeded with no stale `__failures__` record.
  - Routing-failure invariant test for `_handle_no_successor`: unmatched action must roll back completion bookkeeping, archive to `__failures__`, and preserve the warning.
- Files:
  - `tests/test_runtime/test_engine_behavior.py`
- Verification:
  - `HOME=$PWD/.home TMPDIR=$PWD/.tmp PYTHONPATH=src .venv/bin/pytest tests/test_runtime/test_engine_behavior.py -q`
  - Result: `8 passed`

## Post-Completion Ruff Cleanup

- Status: completed
- Rationale:
  - Addressed Ruff findings raised after the final review pass instead of leaving style debt in place.
- Changes:
  - Reduced complexity in `src/pflow/core/diagnostic.py` by extracting the all-failed-coalesce summary block into a helper.
  - Replaced the small output-header `if/else` with the requested ternary expression.
  - Converted remaining `Optional[...]` annotations in `src/pflow/runtime/node_state.py` to `| None`.
- Verification:
  - `HOME=$PWD/.home TMPDIR=$PWD/.tmp PYTHONPATH=src .venv/bin/ruff check src/pflow/core/diagnostic.py src/pflow/runtime/node_state.py`
  - Result: `All checks passed!`

## Post-Completion Verification Pass (2026-04-07)

Fresh verification session run against the "completed" implementation. Goal: try to break the work, not confirm it. Built 24 test workflows in `scratchpads/task148-verification/` plus a shared-store inspector harness (`inspect_shared.py`) that reports the `__failures__` / `completed_nodes` / top-level invariant state after every run.

### What held up

- #208 repro still produces `fallback-content`.
- Invariant holds across all 5 failure paths (shell exit, raised exception, api warning, routing error, `_handle_no_successor`). Failed nodes live only in `__failures__` with full data preserved. Categories are set correctly (`shell_failure`, `node_action_error`, etc.).
- `ignore_errors: true` with empty stdout correctly stays as succeeded-with-empty instead of falling through coalesce.
- Three-way coalesce, sub-field coalesce, sub-workflow boundary isolation, cache+failure interaction, batch partial-failure metadata display, loop re-entry at the runtime level — all correct.
- Source line tracking is exact even with heavy line offsets (verified lines 39, 40, 50).
- Typo-on-succeeded surfaces "Did you mean". Typo-on-failed surfaces BOTH failure (primary) AND typo (secondary hint). Template error UX for node-param path is high quality with command / exit_code / stderr / real peer names.
- JSON output has rich structured `unresolved_references` with per-ref category, error, peer suggestions.

### Bugs found — three real issues

Before proposing fixes, 4 `pflow-codebase-searcher` agents were launched in parallel to verify fix-strategy assumptions (blast radius, existing test encoding, consumer completeness, test coverage gaps). Fix work proceeded only after green-lights from all four.

**BUG #1 (CRITICAL — spec violation)**: `src/pflow/runtime/output_resolver.py:168-172` silently skipped ALL unresolved coalesce expressions in output declarations, including when operands were FAILED. The comment said "all-absent coalesce" but the code skipped regardless of ref status.

- **Spec requirement violated**: `task-148.md` explicitly requires `${primary.stdout ?? fallback.stdout}` with both failed to produce a structured error and emit an "All coalesce operands failed" summary block. The node-param path correctly does this; the output path silently swallowed it. This is the exact bug class the task set out to prevent — "silently resolves to empty string. Single worst UX outcome — workflow looks fine but produces garbage".
- **Also affected**: mixed absent+failed coalesce in output — same silent swallow.
- **Root cause**: the gate checked `is_coalesce_expression` but never consulted ref statuses. The required helper `classify_unresolved_references` was already imported by `_diagnose_unresolved_output` in the same file.
- **Fix**: extracted `_is_all_absent_coalesce(normalized, shared_storage)` helper that calls `classify_unresolved_references` and returns True only when every ref is `status == "absent"`. The main function now skips silently only for true all-absent cases and falls through to `_record_output_failure` (new helper) for any FAILED or PATH_ERROR operand. Also factored `_record_output_failure` to keep `populate_declared_outputs` under the C901 complexity threshold.
- **Files**: `src/pflow/runtime/output_resolver.py`

**BUG #2 (HIGH — AI agent output correctness)**: `src/pflow/execution/execution_state.py:110-133` used the singular `exec_state["failed_node"]` to determine per-node display status. In multi-failure workflows, only the LAST failed node matched the singular check; earlier failed nodes (present in `__failures__` but not in `completed_nodes` and not equal to the singular) fell through to `"not_executed"`. Visible in both CLI text output (`○` icon) and JSON output (`"status": "not_executed"`) — an AI agent consuming the JSON would receive an outright lie about execution state.

- **Missed Phase 3 migration**: Phase 3 of the original implementation only updated `execution_state.py:143` (the `get_node_output` call for batch metadata). The status-determination logic at lines 128-133 was left on the pre-Task-148 singular-field model.
- **Only site affected**: verified by agent sweep — all downstream formatters (success_formatter, error_formatter, CLI workflow_output, MCP server) consume the status string rather than recomputing it. `trace_report.py` uses a separate parallel source of truth (trace events) and is unaffected.
- **Fix**: replaced the three-arm conditional with a single call to `node_state.get_node_status(shared, node_id)` mapped through a `_STATUS_MAP` dict to the existing status strings.
- **Files**: `src/pflow/execution/execution_state.py`

**BUG #3 (MEDIUM — Task 148 acceptance criterion not met)**: The #208 repro's `--report` summary.md listed the failed node's error as `"Unknown error"` instead of the actual failure text. Task 148 spec explicitly lists as acceptance: *"--report for the #208 repro shows `primary` as failed with full context"*.

- **Root cause**: `engine.py` step 16 called `record_trace(..., success=not str(action).startswith("error"))` with no `error=` kwarg in the happy-path action="error" branch. The `error` parameter was only passed on the exception path. So action="error" failures (shell `exit N` routed via `on-error`) produced trace events with `success: False` but no `error` field, and `trace_report.py:552` fell back to `event.get("error", "Unknown error")`.
- **Fix**: pre-computed `trace_error = shared[node_id].get("error")` when action is error and passed it as `error=trace_error` to `record_trace`. Loosened the type of `record_trace`'s `error` parameter from `Optional[Exception]` to `Optional[Exception | str]` with a docstring explaining why.
- **Files**: `src/pflow/runtime/engine/engine.py`, `src/pflow/runtime/engine/instrumentation.py`

### Bugs considered and deliberately not fixed

- **Stale `exec_state["failed_node"]` singular after loop recovery**. Initially flagged as BUG #2b. Verification agent C proved it is purely latent — all 4 consumers of the singular `failed_node` are either guarded by failure checks (`if not success`, `except:`) or shadowed by priority ordering (`completed_nodes` check wins first). Task 148 spec explicitly defers `failed_node → failed_nodes list` as orthogonal (task-148.md:261). Withdrawn from the bug list.
- **`--report` "Status: failed" after loop recovery**. Initially conflated with BUG #2b in the verification report. Agent C proved this has a completely independent root cause: `workflow_trace.py:281` uses `any(not e.get("success", True) for e in self.events)`, which is monotonic over the full event list. Visit 1's failure event persists forever in the trace, so the workflow reports "failed" even though visit 2 succeeded. Has nothing to do with `failed_node` singular. Pre-existing trace aggregation semantic gap not covered anywhere in Task 148's spec. Filed as **spinje/pflow#240** with reproducer, root-cause trace, design options, and acceptance criteria.

### Test updates — fixtures that encoded the old API

BUG #2 fix broke 4 tests whose fixtures set `exec_state["failed_node"]` singular without populating the `__failures__` dict. These tests predate the Task 148 invariant and treated the singular pointer as ground truth. Updated to match the new runtime invariant:

- `tests/test_execution/test_execution_state.py::test_basic_step_building` — populate `shared_storage["node1"]` and `["node2"]` at top level (succeeded nodes live there).
- `tests/test_execution/test_execution_state.py::test_failed_node_status` — populate `__failures__["node2"]` with `data`/`category`/`error` fields.
- `tests/test_execution/test_execution_state.py::test_not_executed_status` — same pattern.
- `tests/test_execution/test_execution_state.py::test_no_stderr_flag_when_exit_code_nonzero` — move failed node data from top-level `shared["shell-node"]` to `__failures__["shell-node"].data`.
- `tests/test_execution/formatters/test_error_formatter.py::test_completed_nodes_must_show_correct_status` — populate `__failures__["send"]` and top-level entries for the succeeded nodes.

None of these fixtures asserted the buggy behavior — they asserted the old API shape, which was semantically equivalent for single-failure scenarios. The fixture changes match what real runtime state looks like after `mark_node_failed` runs.

### New regression tests

Targeted tests for each fix, built to exercise the exact code path that would have caught the bug. Designed per the project's "tests that catch real bugs, not coverage metrics" standard.

- `tests/test_execution/test_execution_state.py::test_multi_failure_all_show_failed_status` — constructs a realistic `shared_storage` with TWO entries in `__failures__` (primary, fallback) plus one succeeded (soak), with `failed_node` singular pointing only at the last. Asserts `build_execution_steps` returns `status == "failed"` for BOTH failed nodes, not just the one that matches the singular. Would have caught BUG #2.
- `tests/test_integration/test_failed_node_invariant.py::test_all_failed_coalesce_in_output_raises_structured_error` — end-to-end workflow where `${primary.stdout ?? fallback.stdout}` has both operands in `__failures__`. Asserts workflow does NOT silently succeed, asserts `category == "template_error"`, asserts the structured `unresolved_references` list has both refs classified as `failed` with preserved `exit_code` and `category == "shell_failure"`. Would have caught BUG #1.
- `tests/test_integration/test_failed_node_invariant.py::test_mixed_absent_and_failed_coalesce_in_output_raises_error` — same pattern for `${absent.x ?? failed.y}`. Covers the mixed case which shared the same broken gate.
- `tests/test_integration/test_failed_node_invariant.py::test_all_absent_coalesce_in_output_is_silently_skipped` — positive regression: Task 128 branch-convergence semantic (all operands absent → silent skip) must remain. Ensures the BUG #1 fix doesn't over-reach.

### Verification

- `uv run pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py` → **4708 passed** (was 4704; net +4 new tests).
- `make check` → clean (pre-commit, ruff, mypy, deptry all green).
- `uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace` → `fallback-content`.
- `uv run pflow scratchpads/task148-verification/03_both_fail.pflow.md --no-cache --no-trace` → structured error with "All coalesce operands failed" summary, exit 1.
- `uv run pflow scratchpads/task148-verification/23_mixed_absent_failed.pflow.md --no-cache --no-trace` → structured error, exit 1.
- `uv run pflow scratchpads/task148-verification/09_loop_recovery.pflow.md --no-cache --no-trace` → `succeeded-on-retry`, exit 0 (invariant correct, only `--report` cosmetic remains — filed as #240).
- `uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --report` summary.md now shows `Errors: primary (ShellNode): Command failed with exit code 1` instead of "Unknown error".
- Direct `build_execution_steps` probe with a realistic multi-failure shared state confirms both failed nodes are labeled `"failed"`, not `"not_executed"`.

### Files changed in this pass

Production (4 files):
- `src/pflow/runtime/output_resolver.py` — BUG #1 fix (new `_is_all_absent_coalesce` + `_record_output_failure` helpers)
- `src/pflow/execution/execution_state.py` — BUG #2 fix (`get_node_status` migration)
- `src/pflow/runtime/engine/engine.py` — BUG #3 fix (pass `trace_error` to `record_trace`)
- `src/pflow/runtime/engine/instrumentation.py` — BUG #3 fix (loosen `error` param type)

Tests (3 files):
- `tests/test_execution/test_execution_state.py` — 4 fixture updates + 1 new regression test
- `tests/test_execution/formatters/test_error_formatter.py` — 1 fixture update
- `tests/test_integration/test_failed_node_invariant.py` — 3 new regression tests

### Follow-ups filed

- **spinje/pflow#240** — Trace aggregation reports workflow as 'failed' after loop recovery (cosmetic, pre-existing trace semantic gap).
- **spinje/pflow#241** — Invariant does not hold for `enable_namespacing=false`. Raised by external code review, verified real via live reproduction (failure data leaks to root, `__failures__` record is empty with wrong category). Not reachable via `.pflow.md`/CLI/MCP; reachable via programmatic IR construction. Issue includes three options (deprecate / adapt / document) with full analysis; recommendation is deprecation at compile time.

## Second Code Review Pass (2026-04-07)

4-agent code review (review-silent-failures, review-impact-completeness, review-feature-interactions, review-agent-ux) against the branch. Inventory across all four: 11 confirmed critical/warning + 2 needs-investigation + 8 suggestions. Many findings overlapped — e.g., silent-failures W3/W4 + impact-completeness #6 + agent-ux C1/C7 all described the same `OutputResolutionError` triple-render bug from different angles. Each Critical finding was verified against the cited code before fixing.

### Implemented Fixes (critical + high-priority review findings)

**Fix #2 — Routing double-archive preserves shell failure data**
- **Regression found**: A shell node returning `"error"` action with no matching error successor edge was double-archived by step 17.5 *and then again* by `_handle_no_successor`. Inside the second call, `shared.pop(node_id, None)` returned `None` (already popped), so the rich failure record (`exit_code`, `stderr`, `command`, `category=shell_failure`) was overwritten with `{data: {}, category: routing_error}`. Any pflow workflow with a shell node failing without an explicit `on-error` handler was affected — the most impactful regression finding.
- **Fix**: `_handle_no_successor` now checks `get_node_failure(shared, node_id)` first. If the node is already archived (step 17.5 ran), preserve the existing record and surface the routing hint only via `__warnings__[node_id]`. For non-error actions (custom unmatched routes), fall through to the original `invalidate_cache` + `mark_node_failed` flow.
- **Files**: `src/pflow/runtime/engine/engine.py:111-152`
- **Decision**: Option A "silent preservation" — the routing warning goes to `__warnings__` only; the failure record's category/data stay authoritative. Rationale: cleanest separation, matches the existing `__warnings__` / `__failures__` split.

**Fix #5 — Typo-on-failed node produces paste-able fix**
- **Issue**: For `${primary.stddout}` (typo) where `primary` failed, `_find_peer_nodes_with_field` was called with the raw typo'd `var`, so the peer search found no nodes with field `stddout` → fell back to `<peer>` placeholder. Rendered fix: `${primary.stddout ?? <peer>.stddout}` — double typo, non-paste-able. Direct violation of task-148.md spec: *"Fix suggestions are paste-able: substitute actual peer node names, not placeholders"*.
- **Fix**: In `_classify_one_reference` FAILED branch, compute `corrected_var` from `secondary_hint` and use it for both peer search and the fix template. Primary reference line still shows the original typo so the agent sees what they wrote.
- **Files**: `src/pflow/runtime/engine/template_errors.py:184-213`, `src/pflow/core/diagnostic.py:369-390` (`_format_failed_reference_fixes`)
- **Result**: `${primary.stddout}` (typo on failed node with `fallback` peer) now renders `Use coalesce: ${primary.stdout ?? fallback.stdout}` — paste-able, field-corrected, real peer name.

**Fix #4 — Mixed absent+failed coalesce emits a fix suggestion**
- **Issue**: `_format_all_failed_coalesce_summary` gate required all refs to have `status == "failed"`. A mixed `${never_run.x ?? fails.y}` (one absent, one failed) hit neither the summary block nor the per-ref fixes (per-ref fixes suppress themselves when `in_coalesce=True`). Agent got zero actionable fix.
- **Fix**: Renamed to `_format_all_unavailable_coalesce_summary`. Widened gate to `status in ("failed", "absent")`. Header conditional: `"All coalesce operands failed"` when all failed, `"All coalesce operands are unavailable (failed or did not execute)"` otherwise. "Investigate the underlying failures" line only renders when any ref is actually failed (skipped for pure all-absent).
- **Files**: `src/pflow/core/diagnostic.py:280-322`

**Fix #1 — OutputResolutionError refactor (drops legacy triple-render)**
- **Issue (biggest quality gap)**: `OutputResolutionError.__init__` built `explanation` from legacy per-variable prose strings, `to_diagnostics()` set `message=self.explanation`, ALSO populated `context.unresolved_references`, AND set legacy canned `suggestions=["Check that source expressions reference..."]`. The renderer emitted all three — same information rendered 2-3 times with the actionable fix buried in the middle. JSON output duplicated everything under inconsistently-named fields (`raw_diagnostics` with key `"variable"` vs `unresolved_references` with key `"var"`, plus `to_display_dict` flattening).
- **Fix**:
  1. Stripped `_diagnose_unresolved_output` to `{source_expr, template, unresolved_references, available_context_keys}`. Dropped legacy `diagnostics` and `raw_diagnostics` lists entirely.
  2. Rewrote `OutputResolutionError.__init__` to build a one-line `explanation` summary (matching `build_template_error_diagnostic` format) and drop legacy canned suggestions.
  3. Rewrote `to_diagnostics()` to produce a single Diagnostic with structured `output_failures` list (one block per failing output, each with its own `source_line`/`source_file`), `suggestions=None`, and `node_id=None` explicitly.
  4. Added `_format_output_block` helper in `diagnostic.py` to render per-output blocks for multi-output errors. Single-output case uses the existing `In output 'X':` header; multi-output iterates each block.
- **Files**: `src/pflow/core/user_errors.py:96-199`, `src/pflow/runtime/output_resolver.py:56-80`, `src/pflow/core/diagnostic.py:250-330` (`_format_template_error_lines` + `_format_output_block`)
- **Decision**: Option A "single grouped Diagnostic with per-output blocks" — simpler than splitting into multiple Diagnostics, preserves the existing dedup contract.

**Fix #3 — Stale failed_node annotation on OutputResolutionError**
- **Issue**: `__execution__["failed_node"]` was never cleared when a workflow recovered from a failure via `on-error` routing. When `populate_declared_outputs` later raised `OutputResolutionError`, `runner._compile_and_execute` unconditionally copied the stale pointer onto the exception. The Diagnostic's `At:` line then claimed "node 'path-a'" for an error that was actually about an entirely different output declaration. An agent following `At:` would open the wrong file and investigate the wrong node.
- **Fix**: `_compile_and_execute` exception handler now explicitly excludes `OutputResolutionError` from `_pflow_node_id` annotation. Also set `node_id=None` explicitly in `OutputResolutionError.to_diagnostics()` (belt-and-suspenders).
- **Files**: `src/pflow/execution/runner.py:204-218`, `src/pflow/core/user_errors.py:190-198`

**Fix #6 — `_extract_runtime_warnings` preserves structured Diagnostic**
- **Issue**: `runtime/engine/template_resolution.py:406-411` already built a full structured `Diagnostic` with per-ref classification, peer suggestions, and typo hints, then attached it to `error_data["diagnostic"]`. But `runner._extract_runtime_warnings` ignored that field and emitted a canned `"Fix unresolved template references in '{node_id}' or use the ?? fallback..."` hint with zero structured info. Permissive-mode workflows got strictly worse UX than strict-mode.
- **Fix**: Read `error_data["diagnostic"]`; if it's a `Diagnostic`, copy with `severity=WARNING` via `dataclasses.replace`, preserving all structured context. Fallback path retained for legacy entries without an attached diagnostic.
- **Files**: `src/pflow/execution/runner.py:490-527`

### Test Migration (post-review fixes)

Existing assertions against the legacy "did not execute" / "executed but failed" / "executed but path not found" wordings were migrated to the structured `unresolved_references` form:

- `tests/test_runtime/test_output_resolver.py` — rewrote `test_error_diagnosis_absent_root`, `test_error_diagnosis_path_not_found`, `test_error_suggests_coalesce_when_root_absent`, `test_error_formats_via_diagnostic` to assert on `refs[0]["status"]` / `did_you_mean` and paste-able rendered output
- `tests/test_integration/test_branch_convergence.py` — updated `test_non_coalesce_output_errors_on_unexecuted_branch` and `test_nested_workflow_output_error_propagates_to_parent` to match the new one-line summary format
- `tests/test_runtime/test_template_error_messages.py` — cleaned up `TestWarning10OutputResolutionStructured` fixture to drop legacy fields, added `test_fix_template_uses_corrected_field_and_real_peer` (Fix #5), `test_mixed_absent_and_failed_coalesce_emits_summary_fix` + `test_all_absent_coalesce_summary_omits_investigate_line` (Fix #4)
- `tests/test_core/test_diagnostic.py` — updated `OutputResolutionError` test fixture to use structured references and `None` for `suggestions` (Fix #1)
- `tests/test_integration/test_failed_node_invariant.py` — added 3 new regression tests: `test_shell_error_without_on_error_preserves_shell_data_in_failure_record` (Fix #2), `test_output_resolution_error_does_not_inherit_stale_failed_node` (Fix #3), `test_output_resolution_error_does_not_triple_render` (Fix #1)
- `tests/test_execution/test_runner.py` — added `test_extract_runtime_warnings_preserves_structured_diagnostic` (Fix #6)

### Verification

- `uv run pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py` → **4714 passed** (was 4708 after the first review pass; +6 new regression tests)
- `make check` → clean (pre-commit, ruff, mypy, deptry all green)
- `uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace` → `fallback-content`
- Manual verification of `scratchpads/task148-verification/`:
  - `04_no_coalesce_failed_ref.pflow.md` — no more triple-render, clean structured block with paste-able fix
  - `08_typo_on_failed.pflow.md` — fix suggestion now uses `${primary.stdout ?? fallback.stdout}` (corrected field + real peer)
  - `23_mixed_absent_failed.pflow.md` — new "All coalesce operands are unavailable" summary with paste-able fix
- Synthetic Fix #2 verification: `/tmp/task148-review/shell_no_onerror.pflow.md` — shell exit 1 without `on-error` now shows full `Shell details: Command / Stderr` in error output (was empty pre-fix)

### Files Changed (second review pass)

Production (6 files):
- `src/pflow/runtime/engine/engine.py` — Fix #2 (`_handle_no_successor` preserves existing failure record)
- `src/pflow/runtime/engine/template_errors.py` — Fix #5 (`corrected_var` field + peer search uses corrected path)
- `src/pflow/core/diagnostic.py` — Fix #4 (`_format_all_unavailable_coalesce_summary`) + Fix #5 (fix template uses corrected var) + Fix #1 (`_format_output_block` helper for multi-output)
- `src/pflow/runtime/output_resolver.py` — Fix #1 (strip legacy fields from `_diagnose_unresolved_output`)
- `src/pflow/core/user_errors.py` — Fix #1 (rewrite `OutputResolutionError.to_diagnostics`) + Fix #3 (`node_id=None` explicit)
- `src/pflow/execution/runner.py` — Fix #3 (skip `_pflow_node_id` for `OutputResolutionError`) + Fix #6 (pass-through structured Diagnostic)

Tests (6 files): see "Test Migration" above.

### Small Follow-Ups Implemented (same pass)

A "think hard" audit surfaced 9 additional small findings that were in scope to fix now (not the critical 6, but cheap cleanups that compound the value of the main refactor). Implemented in the same pass:

**B5 — Delete redundant writes in `cache_result` + `handle_api_warning`**
- `instrumentation.py:106-115` — `cache_result` for action="error" was a no-op wrapper that set `failed_node` via a stale pre-task-148 code path, then step 17.5 re-set it via `mark_node_failed`. Removed the else branch entirely.
- `instrumentation.py:476-490` — `handle_api_warning` was directly writing `__warnings__[node_id]` and `__execution__["failed_node"]` before calling `mark_node_failed` (which writes both of those via the `warning=` kwarg). Removed the duplicate pre-writes.
- Net: 7 lines deleted. Contract compliance with "single write path" goal.
- Updated `test_checkpoint_tracking.py::test_failed_node_tracking` which encoded the old stale `cache_result` contract.

**B4 — Migrate 2 remaining ad-hoc root extractions**
- `node_output_formatter.py:57` — `path.split(".")[0].split("[")[0]` → `TemplateResolver.extract_root_node_id(path)`. Functionally equivalent, cosmetic cleanup.
- `validator.py:384-385` — `operand.split(".", 1)[0]` had a latent correctness bug: for `${data[0].x}`, it yielded `node_id="data[0]"` (with bracket), producing a misleading "node 'data[0]' not found" error. Now uses `TemplateResolver.extract_root_node_id(operand)` which correctly yields `"data"`. The `output_key` derivation was updated to slice from the remainder: `operand[len(node_id):].lstrip(".[")`.
- Also added an `or "[" in operand` check to the "skip non-node reference" guard so bracket-only forms like `${arr[0]}` aren't skipped.

**D4 — `handle_cached_execution` defensive `clear_node_failure`**
- `instrumentation.py:428-451` — Added a single `clear_node_failure(shared, node_id)` call at the start of `handle_cached_execution`. Zero-cost defense against the invariant breaking if a future checkpoint-resume or externally-seeded shared store puts a node in both `shared[id]` AND `__failures__[id]` simultaneously.

**A2 — Preserve batch metadata in failure record for all-failed + fail_fast**
- `batch_executor.py:598-663` — `_aggregate_batch_results` now writes `shared[node_id] = {...}` BEFORE raising the "all items failed" abort. Step 17.5's `mark_node_failed` then archives the full batch_metadata / errors list into `__failures__[node_id].data`, so `build_execution_steps` can surface `batch_error_details` for the failing batch node.
- `batch_executor.py:359-378` — `_execute_sequential` no longer raises on fail_fast from inside the loop. Instead it `break`s out; the raise happens in `execute_batch` after `_aggregate_batch_results` writes the shared store.
- `batch_executor.py:457-523` — `_execute_parallel` no longer raises on fail_fast. Same pattern: return partial state, let `execute_batch` raise after aggregation.
- `batch_executor.py:214-228` — `execute_batch` now owns the fail_fast raise, executing it AFTER `_aggregate_batch_results` so the partial state survives.
- Closes the task-148.md spec acceptance criterion *"Failed batch nodes show `batch_error_details` in execution summary"* for the previously-unsatisfied all-failed and fail_fast cases.

**B1 — Fix generic failure block multi-line truncation**
- `diagnostic.py:460-502` — `_render_generic_failure_block` now skips the `error` key (already shown on the primary `Error:` line), skips empty strings, truncates multi-line values to first line + `(more — run with --verbose)`, truncates single-line values to 200 chars + `...`. Caps output at 6 shown fields.
- `diagnostic.py:344` — `_format_failed_reference` now passes `error` through `_truncate_error_text` before rendering, applying the same truncation rules to the primary `Error:` line. Multi-line Python tracebacks no longer break the diagnostic layout.

**B2 — Zero-line fallback for failure block renderers**
- `diagnostic.py:418-502` — `_render_shell_failure_block`, `_render_http_failure_block`, `_render_mcp_failure_block`, `_render_generic_failure_block` now append `"(no <type> details captured)"` when no fields were extracted. Combined with Fix #2 this is mostly defensive, but prevents any future code path that archives `data={}` from producing an empty-block rendered error.

**B3 — Always show available context keys, including failed peers**
- `template_errors.py:335-347` — `build_template_error_diagnostic` now populates `failed_context_keys` from `shared["__failures__"].keys()` alongside `available_context_keys`.
- `diagnostic.py:281-317` — New `_format_context_keys_block` helper renders the "Available nodes in context:" block unconditionally when there are unresolved refs. Succeeded peers render as `- name`, failed peers render as `- name (failed — see error detail above or check __failures__)`. If both lists are empty, renders `(none — no other nodes have executed)` so the agent never sees a phantom-suppressed block.

**C3 — Unify `file:line` format in `_format_location`**
- `diagnostic.py:182-210` — Changed `At: file, line N` to `At: file:N` (universal editor-click convention). File without line still renders as bare `file`; line without file still renders as `line N`.

**C1 — Add multi-output OutputResolutionError regression test**
- `tests/test_integration/test_failed_node_invariant.py` — New `test_multi_output_resolution_error_renders_per_output_blocks` constructs a 2-output failure with different source lines and asserts both render in their own `In output 'X':` block with their own `file:line` source hint. Protects the Fix #1 refactor's multi-output path from regression.

**A2 regression test**
- `tests/test_integration/test_failed_node_invariant.py` — New `test_all_failed_batch_preserves_batch_metadata_in_failures` uses the engine directly (not the runner, because `_exception_to_result` doesn't thread `shared_store` into `ExecutionResult.shared_after`) to verify that `__failures__["batch_node"].data` retains `batch_metadata`, `count`, `error_count`, `errors`, etc. after an all-failed batch raise.

### Follow-up items NOT implemented (deferred / out-of-scope)

- **A1 runner reads `__failures__` for DEGRADED status** — semantic design call (should a recovered-via-on-error workflow report SUCCESS or DEGRADED?). Not in this pass.
- **A3 routing trace-event success inconsistency** — custom non-error action landing in `_handle_no_successor` writes `success=True` to the trace before `mark_node_failed` archives. Edge case, needs trace collector API change.
- **C2 `exception_to_diagnostics` sentinel for `node_id`** — latent fragility, not a current bug.
- **D2 `__failures__` unbounded growth in long loops** — document in CLAUDE.md, don't implement cleanup until reported.
- **E #233 sub-workflow diagnostic propagation** — significant rework, deserves its own task.
- **`_exception_to_result` should thread `shared_store` into `ExecutionResult.shared_after`** — architectural change, discovered while adding the A2 regression test but out of scope for this pass.

### Verification (post-follow-ups)

- `uv run pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py` → **4716 passed** (+2 new regression tests)
- `make check` → clean
- `uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace` → `fallback-content`
- Manual verification of scratchpads: 04/08/23 all render cleanly with the new `file:line` format, no truncation issues, no empty blocks

### Files Changed (small follow-ups)

Production (5 files):
- `src/pflow/runtime/engine/instrumentation.py` — B5 (cache_result + handle_api_warning dedup), D4 (handle_cached_execution defensive clear)
- `src/pflow/runtime/engine/batch_executor.py` — A2 (3 sites: _aggregate_batch_results write-before-raise, _execute_sequential break-not-raise, _execute_parallel no-raise, execute_batch owns fail_fast raise)
- `src/pflow/runtime/engine/template_errors.py` — B3 (failed_context_keys population)
- `src/pflow/core/diagnostic.py` — B1 (generic truncation + _truncate_error_text), B2 (zero-line fallbacks), B3 (_format_context_keys_block), C3 (file:line format)
- `src/pflow/execution/formatters/node_output_formatter.py` — B4 (root extraction migration)
- `src/pflow/core/workflow/validator.py` — B4 (root extraction migration + latent correctness fix for `${data[0].x}`)

Tests (3 files):
- `tests/test_runtime/test_checkpoint_tracking.py` — updated to match new `cache_result` contract
- `tests/test_integration/test_failed_node_invariant.py` — +2 new regression tests (A2 batch metadata, C1 multi-output OutputResolutionError)

### Third Pass — Observability and Coverage Gaps (2026-04-07)

A second "think hard" audit after the B1-B5/A2/C1/C3/D4 polish pass surfaced five remaining items worth fixing. All implemented.

**#5 — `_exception_to_result` threads `shared_store` through the exception path**
- **Regression**: When ``engine.run`` raised (exception path, not action="error"), the runner's ``_exception_to_result`` built an ``ExecutionResult(shared_after={})``. All partial state — ``__failures__``, per-node outputs, batch metadata, warnings — was invisible to CLI formatters, MCP consumers, and ``build_execution_steps``. This silently undermined the task-148 spec acceptance criterion *"Failed batch nodes show batch_error_details in execution summary"* for any batch that raised (vs returned action="error"), and the same for any shell node that raised from an actual subprocess error instead of an exit code.
- **Fix**: ``_compile_and_execute`` attaches ``shared_store`` to the exception via a new ``_pflow_shared_store`` annotation (matching the existing ``_pflow_node_id`` / ``_pflow_parser_diagnostics`` pattern). ``_exception_to_result`` reads the annotation and populates ``ExecutionResult.shared_after``.
- **Files**: ``src/pflow/execution/runner.py:204-224, 575-615``
- **Impact**: Spec acceptance for failure display now actually works end-to-end. An agent seeing an exception-path failure gets the rich ``__failures__`` record (category, error, data, source_line) instead of an empty shared store. Enabled simpler regression tests (A2 now uses the runner API instead of direct-engine).

**#4 — Verify C3 `file:line` format change didn't break existing assertions**
- Searched for `", line ", `', line `, `"At:`, `_format_location` across tests. Only 5 matches, none asserting on the main `_format_location` output format (they're in parser tests, Python code node tests, and one "At: nodes[0]..." path assertion). C3 change verified safe.

**#1 — B4 `output_key` lstrip cleanup**
- ``validator.py:387`` — changed ``.lstrip(".[")`` to ``.lstrip(".")``. For ``${data[0].x}`` the rendered `output_key` is now `[0].x` (intact bracket syntax) instead of `0].x` (ugly). Only affects the error message shown when a non-existent node is referenced.

**#2 — Fail_fast batch metadata regression test**
- New ``test_fail_fast_batch_preserves_batch_metadata_in_failures`` in ``test_failed_node_invariant.py``. Exercises the different control flow for A2's fail_fast path (break-not-raise in ``_execute_sequential``, ``execute_batch`` owns the raise after aggregation). Uses the runner API — enabled by #5.

**#3 — B3 mixed-context regression test**
- New ``test_template_error_shows_both_succeeded_and_failed_peers_in_context``. Verifies the new "Available nodes in context:" block renders BOTH succeeded peers (clean name) and failed peers (with ``(failed — see error detail...)`` marker). Protects against regression in ``_format_context_keys_block``.

Also refactored ``test_all_failed_batch_preserves_batch_metadata_in_failures`` to use the runner API instead of the direct-engine approach (simpler, exercises more code paths, possible thanks to #5).

### Verification (third pass)

- ``uv run pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py`` → **4718 passed** (+2 new tests beyond the second pass)
- ``make check`` → clean
- ``uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace`` → ``fallback-content``
- Manual verify of #5: ``WorkflowRunner().run(batch_ir).shared_after["__failures__"]["all_fail"]["data"]`` contains full ``batch_metadata`` with ``count=3, error_count=3``. Pre-fix this was ``{}``.

### Files Changed (third pass)

Production (2 files):
- ``src/pflow/execution/runner.py`` — #5 (``_pflow_shared_store`` annotation + read)
- ``src/pflow/core/workflow/validator.py`` — #1 (output_key lstrip cleanup)

Tests (1 file):
- ``tests/test_integration/test_failed_node_invariant.py`` — +2 new tests (#2 fail_fast, #3 mixed context), refactored #A2 all-failed test to use the runner API

### Complete Follow-Up Status (all three passes)

**Implemented (15 findings total)**:
- Critical: Fix #1 OutputResolutionError refactor, Fix #2 routing double-archive, Fix #3 stale failed_node, Fix #4 mixed coalesce, Fix #5 typo-on-failed paste-able fix, Fix #6 structured warning pass-through
- High: B5 redundant writes cleanup, B4 ad-hoc root extractions (with latent correctness fix), A2 batch metadata preservation, D4 handle_cached_execution defensive clear
- Medium: B1 multi-line error truncation, B2 zero-line fallbacks, B3 always show context keys, C3 file:line format, C1 multi-output regression test, #5 shared_store threading through exception path

**Deferred (filed for future work)**:
- A1 — Runner reads ``__failures__`` for DEGRADED status (semantic design call)
- A3 — Routing trace-event ``success=True`` for custom non-error actions (needs trace collector API change)
- C2 — ``exception_to_diagnostics`` sentinel for ``node_id`` (latent fragility)
- D2 — ``__failures__`` unbounded growth in long loops (document in CLAUDE.md when reported)
- E / #233 — Sub-workflow diagnostic propagation (significant rework, deserves own task)
- Multi-output grouping by root node (moderate renderer change, not critical)

### Fourth Pass — High-Value Tests + One Discovered Bug (2026-04-07)

After confirming the earlier fixes, a "what would break if I touched the wrong thing?" audit focused on bug classes where no single test exercised the full pipeline. Identified three high-value test targets; one of them turned out to be an actual half-finished bug.

**Test B (investigated first) — exposed a real bug in Fix #6**
- **Hypothesis**: Fix #6 passes the structured template-error Diagnostic through ``_extract_runtime_warnings`` with severity downgraded to WARNING. But ``_format_warning_or_info_diagnostic`` always rendered warnings as one-liners regardless of category — never calling ``_format_template_error_lines``. So the rich structured data (per-ref details, peer suggestions, paste-able fixes, "did not execute" explanations) was preserved in the Diagnostic object but **silently dropped** at text rendering time. Permissive-mode workflows had objectively worse CLI UX than strict-mode, just for a different reason than before Fix #6.
- **Reproduction**: Same ``build_template_error_diagnostic`` call, two severities → ERROR path rendered a 12-line structured block, WARNING path rendered a single ``⚠ [node] Unresolved variables...`` line with nothing else.
- **Fix**: Added ``_format_warning_template_error`` helper in ``diagnostic.py`` that renders the structured block for template_error warnings, keeping the warning icon + node_id header so it stays visually distinct from a hard error. Dispatched via a new category check in ``_format_warning_or_info_diagnostic``. Non-template_error warnings (cache_lint, api_warning, etc.) still render as compact one-liners — the convention holds for warnings that don't carry rich context.
- **Files**: ``src/pflow/core/diagnostic.py:117-167``
- **Severity**: MEDIUM. Affected every permissive-mode template error display. Previously invisible because Fix #6's unit test only checked that ``_extract_runtime_warnings`` returned a Diagnostic with the right context — never that the Diagnostic's rendered text showed the context.
- **Regression test**: ``tests/test_runtime/test_template_error_messages.py::TestPermissiveModeWarningRendering`` — two cases, one asserting template_error warnings render the full structured block, one asserting non-template_error warnings stay compact.

**Test A — End-to-end batch display pipeline guard**
- **Purpose**: The task-148 spec acceptance criterion *"Failed batch nodes show batch_error_details in execution summary"* depends on a 4-layer pipeline cooperating. Each layer broke during this work:
  1. ``_aggregate_batch_results`` writes ``shared[node_id]`` BEFORE raising (Fix A2)
  2. Step 17.5 archives to ``__failures__[id].data`` via ``mark_node_failed`` (Task 148 core)
  3. ``_exception_to_result`` threads ``shared_store`` into ``ExecutionResult.shared_after`` (Fix #5)
  4. ``build_execution_steps`` reads via ``get_node_output`` and emits ``batch_error_details`` (BUG #2 post-completion fix)
- **Gap in coverage**: No single test exercised all 4 in sequence via the public ``WorkflowRunner`` API. Each had its own unit test, but a regression in any one layer would break the spec acceptance silently.
- **Test**: ``tests/test_integration/test_failed_node_invariant.py::test_failed_batch_surfaces_error_details_in_execution_steps`` — runs an all-failed batch through ``WorkflowRunner().run()``, calls ``build_execution_steps(ir, result.shared_after, result.metrics.get_summary())``, asserts the returned step has ``is_batch=True``, ``batch_errors=3``, ``batch_error_details`` populated with all 3 item errors.

**Test C — Sub-workflow `__failures__` isolation invariant**
- **Purpose**: ``__failures__`` must NOT be in ``WorkflowExecutor._PROPAGATED_KEYS`` (it's per-workflow-scoped). A careless refactor that adds it there, or that copies the dict reference across workflow boundaries, would silently leak a child's failed-node IDs into the parent's ``__failures__`` dict. Downstream consumers (``get_node_status``, ``_extract_node_level_error``, error enrichment) would then report wrong state for identically-named nodes.
- **Gap in coverage**: ``test_nested_workflow_output_error_propagates_to_parent`` checks the parent sees the child error as a string, but doesn't check that the parent's ``__failures__`` dict is clean of the child's internal failed-node IDs.
- **Test**: ``tests/test_integration/test_branch_convergence.py::TestOutputResolutionErrors::test_child_failures_do_not_leak_into_parent_failures_dict`` — parent→child where the child's inner ``inner_failing`` node fails with exit 1. Asserts that parent's ``__failures__`` contains the boundary-level ``run_child`` key (the WorkflowExecutor node itself, correctly archived) but does NOT contain ``inner_failing`` (the child's internal failed node).

### Verification (fourth pass)

- ``uv run pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py`` → **4722 passed** (+4 new tests: 2 from Test B, 1 from Test A, 1 from Test C)
- ``make check`` → clean
- ``uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace`` → ``fallback-content``
- Reproduced the Test B bug before fixing: same Diagnostic at ERROR severity produced 12 lines of rich content, at WARNING severity produced 1 line with no detail. Post-fix: WARNING renders the full structured block with icon header.

### Files Changed (fourth pass)

Production (1 file):
- ``src/pflow/core/diagnostic.py`` — Test B fix: new ``_format_warning_template_error`` helper + category check in ``_format_warning_or_info_diagnostic`` dispatcher.

Tests (3 files):
- ``tests/test_runtime/test_template_error_messages.py`` — new ``TestPermissiveModeWarningRendering`` class with 2 tests (Test B regression)
- ``tests/test_integration/test_failed_node_invariant.py`` — new ``test_failed_batch_surfaces_error_details_in_execution_steps`` (Test A)
- ``tests/test_integration/test_branch_convergence.py`` — new ``test_child_failures_do_not_leak_into_parent_failures_dict`` (Test C)

### Complete Tally (all four passes)

- **21 bugs fixed** (6 critical from first review + 10 polish from second review + 5 observability from third review + 1 discovered during fourth review)
- **18 new regression tests** (6 + 4 + 4 + 4)
- **4722 tests passing**
- **0 warnings, 0 type errors, 0 dependency issues**

## Fifth Pass — Follow-up GH Issue Filing (2026-04-07)

After confirming the code work was complete, an audit of all deferred items across the four review passes identified which deserved GH issues. Applied a strict bar: real bug OR real UX improvement OR design decision worth preserving, AND not already filed.

### Verification before filing

**Reproduced issue #2 (`${input.field}` validator rejection)** before filing — ran a minimal script constructing an IR with declared input `data` and output source `${data.field}`, confirmed `WorkflowValidator.validate()` returns the error `"Output 'x' source references non-existent node 'data'"`. Bug is real, not speculative.

**Re-examined #235** — discovered my earlier "fully addressed" claim was wrong. Fix #6 (second pass) + Test B renderer fix (fourth pass) only addressed the `__template_errors__` loop in `runner._extract_runtime_warnings`. The parallel `__warnings__` loop (API warnings) was untouched — still has canned `"Inspect '{node_id}' upstream inputs and output..."` suggestions. Updated plan: add a partial-resolution comment on #235 instead of closing it.

**Deduplication search** — searched the 100+ existing issues across keywords (`DEGRADED`, `on-error recovery`, `input.field validator`, `workflow input validator`, `multi-output template error`, `call_completion_callback api_warning`, `progress callback node_complete`, `routing failure trace`, `trace success false routing`). None of the 5 planned issues duplicate existing open or closed issues:

- #159 (batch results include failed items) — different scope
- #223 (UserFriendlyError.to_diagnostics duplication) — different kind of dup (internal data vs rendered output)
- #234 (absent-node error wording) — different scope
- #240 (trace aggregation after loop recovery) — related but distinct from #250
- #241 (invariant with namespacing=false) — different scope
- #116 (closed, batch ${item.field}) — different scope

### Issues filed (5 new)

**spinje/pflow#246 (HIGH) — Workflow reports SUCCESS when a node failed and was recovered via on-error**
- Promoted from "deferred A1" in the post-completion review.
- Body includes concrete reproducer, the semantic design question (is opting into `on-error` the same as wanting silent recovery?), and 4 design options (A: promote to DEGRADED, B: INFO diagnostics, C: CLI flag, D: report-only).
- Recommended Option A as the single-flag change with least added noise.
- Scope: `_determine_status` returns DEGRADED when `__failures__` is non-empty after successful recovery. Tests update to match.

**spinje/pflow#247 (HIGH) — Validator rejects valid `${input.field}` references in output sources**
- Discovered during B4 root-extraction migration in the second pass, but kept out of scope.
- Reproducer verified before filing.
- Root cause: `validator.py:_validate_template_in_source` only has a "skip if no dot or bracket" check for bare `${input_name}` references. Any `${input_name.field}` form falls through to the "not in nodes_map" check and errors.
- Fix direction: thread `workflow_ir["inputs"]` into `_validate_template_in_source` and check inputs alongside nodes_map before erroring.
- Blocks `pflow workflow save` for any workflow accessing fields on declared inputs in output sources.

**spinje/pflow#248 (HIGH) — Template error renders failure details N times when multiple outputs reference the same failed node**
- Identified as agent-ux W2 during the first review pass, deferred then as "moderate renderer change, not critical".
- Real UX regression: scales linearly with number of outputs referencing one failed node. A workflow with 5 outputs referencing one failed shell node shows the command/exit_code/stderr block 5 times.
- Body includes before/after rendering examples showing the grouping by root node.
- Fix direction: group refs by root in `_format_template_error_lines`, render failure-data block once per root with a per-reference fix list.
- ~40-60 lines renderer change.

**spinje/pflow#249 (MEDIUM) — `handle_api_warning` skips `call_completion_callback`**
- Pre-existing UX inconsistency flagged by review-feature-interactions C4 in the first review.
- Not a regression — same behavior as before Task 148. But discovered during the second pass's B5 redundant-writes cleanup in the same function.
- Body documents the symmetry with the happy path (which calls `call_completion_callback` at step 17) and the exception path (which calls it from the except block).
- Progress displays may show API-warning-failing nodes as "still running" until the workflow terminates.
- Fix: add the callback call before `mark_node_failed`.

**spinje/pflow#250 (MEDIUM) — Trace event records `success=True` for routing failure with custom non-error action**
- Silent-failures W5 from the first review, deferred as "edge case, needs trace collector API change".
- Scenario: node returns `"custom_route"` (non-error), no edge matches, `_handle_no_successor` archives the failure via `mark_node_failed` — but the trace event at step 16 was already written with `success=True` because `is_error_action` is False.
- Body includes 3 fix options (Option A: trace collector mark_last_event_failed API, Option B: earlier routing detection, Option C: re-emit event).
- Recommended Option A.
- Affects `--report` accuracy and trace-based post-analysis.
- Related to #240 (loop recovery trace aggregation) but distinct.

### Issue updated (1)

**spinje/pflow#235** — Added a partial-resolution comment documenting the split:

- **Addressed**: `__template_errors__` loop in `_extract_runtime_warnings` now passes structured Diagnostic through; `_format_warning_or_info_diagnostic` dispatches template_error warnings to the structured renderer. Per-ref details, peer suggestions, typo hints all visible in CLI text output.
- **Not addressed**: `__warnings__` loop (API warnings) still has canned `"Inspect upstream inputs..."` suggestions. The detector signal exists in `api_warning_detector.py` but isn't plumbed through to `__warnings__`.
- Left #235 open for the API warning half.

### Documentation updated (1)

**`src/pflow/runtime/CLAUDE.md`** — Added `__failures__` lifetime note (D2 deferral handled as documentation instead of an issue). Documents that entries persist for the full workflow lifetime, with cleanup only on loop re-entry and memo cache hits. Notes that long-running workflows with heavy retry loops accumulate entries proportional to total failures — not a bug, but a characteristic worth knowing.

### What WASN'T filed (and why)

- **`_exception_to_result` threading for non-engine exceptions** — no shared_store exists at pre-engine stages, not a real gap
- **Parallel batch + shared-mode sub-workflow `__failures__` aliasing (feature-interactions C3)** — speculative, edge case within edge case, no user reachable
- **`exception_to_diagnostics` sentinel for `node_id`** — latent fragility, no concrete scenario
- **`_describe_failure_category` returns raw category for unknowns** — defensive fallback, fine as-is
- **Falsy checks dropping empty stderr** — cosmetic
- **`node_action_error` category label is "unfriendly"** — cosmetic
- **Multi-output `"; "` separator** — already fixed via per-output blocks in Fix #1
- **`_extract_child_error` uses singular `failed_node`** — orthogonal to the task spec's `failed_node → failed_nodes` refactor
- **`_enrich_error_from_node_output` stale category** — latent, 5-line fix, no current user impact
- **#233 sub-workflow diagnostic propagation** — already filed, significant rework
- **#240 loop recovery trace aggregation** — already filed
- **#241 invariant with namespacing=false** — already filed

### Verification (fifth pass)

- `make check` → clean (ruff, ruff-format, mypy, deptry all green)
- `uv run pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py` → **4722 passed**

### Files Changed (fifth pass)

Docs (1 file):
- `src/pflow/runtime/CLAUDE.md` — added `__failures__` lifetime note

External (via `gh` CLI):
- spinje/pflow#246, #247, #248, #249, #250 — new issues
- spinje/pflow#235 — partial-resolution comment added

## Final Status (all five passes)

- **21 bugs fixed** in source code
- **18 new regression tests**
- **5 new GH issues filed** (all verified not-duplicate, all with concrete reproductions or fix directions)
- **1 GH issue updated** (#235 partial resolution)
- **2 docs updates** (runtime/CLAUDE.md + this progress log)
- **4722 tests passing, 0 warnings, 0 type errors, 0 dependency issues**
- **All changes local to `fix/resolve-coalesce-empty-string` branch — not committed**

## Sixth Pass — Simplicity Audit and Cleanup Refactor (2026-04-08)

Pre-PR audit triggered by the user's framing: "simplicity of the final code, not how easy it is to get there — what would the top 10% of codebases implement?" Targeted at the +941 net production LOC the task had added, looking for genuine consolidation wins, dead code, and unnecessary abstraction.

### Audit method

Read the five largest new/touched files (`node_state.py`, `template_errors.py`, `diagnostic.py`, `user_errors.py`, `output_resolver.py`) in full and proposed 5 simplification findings:

1. `_extract_failure_display_data` double-filter + dead `**display_data` spread (~25–40 LOC)
2. Field-name extraction duplication in `_find_peer_nodes_with_field` + `_suggest_field_correction` (~10 LOC)
3. `_format_legacy_template_error_lines` dead code (~20 LOC)
4. Single/multi-output template error rendering normalization (~15–20 LOC)
5. Defensive checks in `node_state.py` read helpers (~15 LOC)

Total rough estimate: ~80–100 LOC reducible.

### Adversarial verification — 5 parallel pflow-codebase-searcher agents

Each agent was given ONE claim and explicitly told to try to disprove it (not confirm). Results reshaped the plan substantially:

- **Finding #1 — BROKEN**. The `**display_data` spread is NOT dead weight: two tests (`test_template_error_messages.py:48`, `test_failed_node_invariant.py:170-173`) read flattened fields like `failure["exit_code"]` directly. Per the Task 148 plan, the flattening was an intentional test/JSON consumer contract. Also the filter itself is load-bearing for the generic path — it drops 500+ char scalars before JSON serialization, and prevents cross-category dispatch misrouting. My "clean double-filter" framing was wrong. Dropped from the cleanup.
- **Finding #2 — CONFIRMED**. Byte-for-byte identical `parts[1].split(".", 1)[0].split("[", 1)[0]` chain in two places, no third site, `TemplateResolver` had no existing helper.
- **Finding #3 — CONFIRMED DEAD**. Both `category="template_error"` producers always populate `unresolved_references`. No tests exercise the legacy branch. The function's own docstring was incorrect ("non-template-error categories"). Agent also uncovered a latent silent-render bug: if `OutputResolutionError` is built with empty refs + non-empty `output_failures`, deleting the legacy branch would silently return `[]` from the renderer — needed a guarded fallthrough fix.
- **Finding #4 — VALID but needs discriminator field**. Normalization is equivalent only if each block carries a `kind: "param"|"output"` field so `_format_output_block` can render the right header. Agent also flagged that the top-level `At:` line for output errors would move to inline `(at ...)` inside the block — a visible-but-equivalent UX change acceptable for output errors, preserved unchanged for node-param errors.
- **Finding #5 — SPLIT**. Claim A (defensive `__execution__` init dead) was broken by `test_node_state.py::test_creates_execution_state_if_missing` which explicitly asserts the defensive behavior as API contract. Production paths are clean but the test pins the contract. Deferred as optional. Claim B (`isinstance` guards redundant in `get_node_failure`) was confirmed, and the agent found the same redundancy in `get_node_output` that wasn't in the original claim — bonus finding.

The verification was the second-most-valuable step of the session. Catching the #1 mistake alone prevented breaking two tests and rolling back production code.

### Implementation — 4 steps, all with baseline capture and focused-suite verification

Pre-work: captured `stderr` of 10 key scratchpad workflows under `/tmp/task148-before/` as a visible-output baseline for diffing after each refactor. Established 218 focused-test green baseline (`test_node_state`, `test_template_error_messages`, `test_output_resolver`, `test_template_coalesce`, `test_failed_node_invariant`, `test_branch_convergence`, `test_runner`, `test_execution_state`, `test_diagnostic`).

**Step 1 — `TemplateResolver.extract_first_field_segment` helper** (commit `7086c34b`)
- New static method next to `extract_root_node_id` with 7 doctests covering the cases the verification agent walked through (simple/nested/indexed/bracket-root/bare-root/none).
- Migrated both `_find_peer_nodes_with_field` and `_suggest_field_correction`.
- 7 new unit tests in `TestExtractFirstFieldSegment` class.
- Net: +12/-12 in production, +46 test. Zero behavior change.

**Step 2 — simplify `node_state.py` read helpers** (commit `cd05519c`)
- `get_node_failure`: 19 → 7 lines. Uses `shared.get("__failures__", {}).get(node_id)` with a local annotation to satisfy mypy's return-type inference.
- `get_node_output`: removed the dead `return record` fallback branch + the `isinstance/"data" in record` guard.
- Docstrings now document the "trusts the single-writer invariant" reason.
- Net: -3 production LOC. Zero behavior change.

**Step 3 — delete legacy renderer + TDD-fix silent-render gap** (commit `500c7bd1`)
- TDD: wrote `test_output_resolution_error_with_empty_refs_still_renders_output_block` FIRST. Verified RED (current code produces only the one-line `Diagnostic.message`, missing the structured block entirely).
- Fix: `_format_template_error_lines` now guards on `not refs and not output_failures` rather than `not refs`, falls through to the structured block iteration when `output_failures` is present even with empty refs. `_format_context_keys_block` now renders unconditionally for any template error — agents need it regardless of ref classification.
- Deleted `_format_legacy_template_error_lines` (20 lines of dead code with an incorrect docstring).
- Verified GREEN. Diffed all 10 scratchpad baselines — zero rendered-output change (only timing jitter on `repro.stderr`).
- Net: -3 production LOC + regression test. One real latent silent-failure bug fixed along the way.

**Step 4 — unify template error rendering via `kind` discriminator** (commit `5effdb84`)
- Pre-flight grep audit confirmed only ONE test pinned `"In parameter '"` (needs `kind="param"`), four pinned `"In output '"` (survive unchanged), zero pinned the top-level `At:` line for template errors, zero MCP consumers read `output_failures`.
- `build_template_error_diagnostic` now synthesizes a single-entry `output_failures` list with `kind="param"` for node-param errors. Top-level `source_file`/`source_line` stay in context for `_format_location` so node-param errors keep the universal `At:` line.
- `OutputResolutionError.to_diagnostics` dropped the single-output source_file/source_line hoist. Every block carries its own source. Tagged blocks with `kind="output"`.
- `_format_template_error_lines` collapsed to a single `for block in output_failures` loop. Deleted the dual-branch single-case intro-line synthesis.
- `_format_output_block` now branches on `block.get("kind")` for the header (`"In parameter 'X':"` vs `"In output 'X':"`).
- Diffed all 10 scratchpad baselines. Uniform expected pattern across 8 error-output workflows: top-level `At: ...` line moved to inline `(at ...)` inside the block. All other content byte-identical.
- Net: -14 production LOC. 219 focused tests green first try.

### Final verification

- `.venv/bin/pre-commit run -a` → clean (ruff, ruff-format, all hooks pass)
- `.venv/bin/mypy src/` → `Success: no issues found in 172 source files`
- `.venv/bin/pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py` → **4730 passed** (baseline was 4722 at end of fifth pass; net +8 from regression tests)
- Manual execution of #208 repro → still `fallback-content`
- Manual execution of `04_no_coalesce_failed_ref`, `05_node_param_both_fail`, `08_typo_on_failed`, `23_mixed_absent_failed`, `issue-208/repro.pflow.md --report`: all produce expected structured output. `--report` summary.md still shows real error text ("Command failed with exit code 1"), not "Unknown error" — BUG #3 regression guard holds.

### Scoreboard

| Commit | Step | Production ΔLOC | Tests Δ |
|---|---|---|---|
| `7086c34b` | Finding #2 helper | +12 / -12 | +7 new |
| `cd05519c` | Finding #5B guards | -3 | 0 |
| `500c7bd1` | Finding #3 + silent-render fix | -3 | +1 regression |
| `5effdb84` | Finding #4 normalize | -14 | 0 |
| **Total** | **4 commits** | **~−20 net production LOC** | **+8** |

Bundled with Step 1: 1 real latent bug fixed (the silent-render gap in `OutputResolutionError` with empty refs + present `output_failures`). That alone justifies the cleanup pass — it's exactly the bug class task-148 was designed to prevent ("silently resolves to empty string — single worst UX outcome").

### Visible UX change (one only, deliberate)

Output-resolution template errors now render source location as **inline `(at file:line)`** inside the block instead of as a **top-level `At:` line** above the message. Information preserved, now context-scoped to its block. Rationale: uniform with the existing multi-output rendering, eliminates dual-branch code, makes single-vs-multi indistinguishable to the renderer.

**Node-param errors unchanged** — they keep the top-level `At:` line via `_format_location` (the node-param case is the only remaining consumer of top-level `source_file`/`source_line` for template errors).

### What was NOT done (deferred / rejected)

- **Finding #1 (double-filter + dead spread)** — verified NOT dead. Tests and load-bearing behavior keep it. Not touched.
- **Finding #5A (defensive `__execution__` init)** — marginal win (~8 LOC); breaks one test that pins the defensive behavior as API contract. Deferred.
- **TypedDict for `unresolved_references`** — considered but rejected for this pass: zero LOC saved, would need a separate type-safety sweep to be coherent.
- **Collapsing `_render_*_failure_block` into dispatch table** — modest win (~35 LOC) but HTTP has `response OR response_body` fallback logic and each category has different truncation rules, so the table gets messy. Left for later.

### Files changed in sixth pass

Production (5 files):
- `src/pflow/runtime/template_resolver.py` — Finding #2 (new helper)
- `src/pflow/runtime/engine/template_errors.py` — Finding #2 (migration) + Finding #4 (synthesize node-param `output_failures`)
- `src/pflow/runtime/node_state.py` — Finding #5B (simplify read helpers)
- `src/pflow/core/diagnostic.py` — Finding #3 (delete legacy + fix silent-render) + Finding #4 (unify renderer)
- `src/pflow/core/user_errors.py` — Finding #4 (delete hoist, tag blocks with `kind`)

Tests (3 files):
- `tests/test_runtime/test_template_resolver.py` — `TestExtractFirstFieldSegment` class (+7 tests)
- `tests/test_integration/test_failed_node_invariant.py` — `test_output_resolution_error_with_empty_refs_still_renders_output_block` (regression for the silent-render fix)

## Seventh Pass — Rebase onto main + Committed Fixture Pattern (2026-04-08)

Triggered by the PR #251 review needing to catch up to main. Task 147 (validator-produces-Diagnostics-natively, 9500-line rewrite) and Task 149 (output pipeline consolidation, 7500-line refactor) had landed on main since Task 148 branched. Heavy file-level overlap expected: `runner.py` (3-way: 147 `_validate`, 149 signature, 148 annotations), `instrumentation.py` (both 149 and 148 touched `handle_api_warning`), `batch_executor.py` (both touched `_execute_parallel`), `validator.py` / `data_flow.py` / `diagnostic.py`.

### Squash-then-rebase strategy

The branch had 10 commits spread across 6 review passes. Rebasing each individually against the new main would have cascaded conflict resolution across the commit series (every cleanup commit depended on state left by earlier commits that themselves conflicted). Decision: squash to a single commit before rebasing, so conflict resolution happens exactly once against the final intended state rather than 10 times against synthetic intermediate states.

**Safety steps before rebase:**
1. Created `backup/task-148-pre-rebase` branch at old HEAD for rollback
2. Read Task 147's and Task 149's task-review.md files in full before touching conflicts — the 3-way overlap needed architectural context on both sides, not just line-by-line resolution
3. Soft reset to merge-base, staged everything, committed as one squashed commit with a detailed message preserving the task history

### Conflicts resolved (9 files)

**8 doc conflicts (CLAUDE.md files)** — mostly Task 147 explaining the new validator-returns-Diagnostic model where my branch still described the old tuple return. Resolution pattern: take HEAD (correct post-147) for anything describing validator return types, error handling philosophy, or `Diagnostic.__hash__` identity. Merge both sides where they described different aspects of the same file (`runtime/engine/CLAUDE.md` — HEAD described subclass override requirements, mine described eager `parent[namespace] = {}` creation). Dropped the `OutputInterface Protocol` section from `execution/CLAUDE.md` entirely because Task 149 deleted those classes.

**1 code conflict (`core/diagnostic.py`)** — the critical one. HEAD renamed `_format_template_error_lines` → `_format_available_fields_block` and broadened the gate to unconditional. My branch had `_format_template_error_lines` as a fundamentally different function (template error rendering with per-ref classification, output_failures blocks, coalesce summaries). **These were different functions that happened to collide on name**. Resolution: keep BOTH function definitions side by side — Task 147's `_format_available_fields_block` (generic "available X (showing N of M)" block for any validator error) and my Task 148 `_format_template_error_lines` (template error renderer for `category=="template_error"`).

### Silent auto-merge drop caught

The 9 explicit conflict markers were not the only damage. Git's line-based auto-merge silently dropped a load-bearing call in `_format_all_context_blocks`:

```python
# Pre-rebase state (task 148):
if context.get("category") == "template_error":
    lines.extend(_format_template_error_lines(context))

# Auto-merged state (silently corrupted):
lines.extend(_format_available_fields_block(context))  # Task 147's call
# ← my _format_template_error_lines dispatch gone entirely
```

Caught by reading the surrounding lines of the conflict region, not by any automated check. The fix restored the conditional dispatch alongside Task 147's unconditional call. Without catching this, ALL Task 148 template error rendering would have silently degraded to the one-line `Diagnostic.message` summary — every structured block (per-ref classification, failure details, paste-able fixes) would have been invisible.

**Lesson**: auto-merge is line-based, not semantic. When a 3-way merge touches an overlapping dispatcher or helper, do not trust it — read the surrounding lines of every conflict region, even the ones git says are "auto-resolved".

### Adversarial audit (after initial "rebase done" claim)

After the first rebase declaration, a pushback ("are you FULLY happy with this rebase?") prompted a second audit:

1. **Task 149 subprocess tests run explicitly** — not just included in the full suite. `test_progress_streaming_subprocess.py`: 12 tests, all passed (stderr coherence, FIFO causal, parallel batch buffering). Proves Task 149's invariants survived the rebase.

2. **Functional-equivalence diff vs `backup/task-148-pre-rebase`** for every Task 148-owned file:
   - 9 of 10 pure Task 148 files byte-identical (`node_state.py`, `template_errors.py`, `output_resolver.py`, `user_errors.py`, `template_resolver.py`, `markdown_parser.py`, 3 test files)
   - `ir_schema.py` had 13 lines of diff — all Task 147's `_format_path` fix for `[0, "batch"]` rendering (pflow#214), preserved correctly alongside my `_source_line` schema extension
   - `engine.py` had ZERO diff — byte-identical
   - `instrumentation.py` had 47 lines of pure Task 149 additions (smart_handled passthrough + handle_api_warning kwarg rename); all my B5/D4/mark_node_failed changes byte-identical
   - `batch_executor.py` had 127 lines of pure Task 149 per-worker buffering additions; all my A2 fail_fast/all-failed restructure byte-identical
   - `workflow_executor.py` had only Task 149 doc tweak + Task 147 dedup symmetry fix; my `_extract_child_error` + `__failures__` exclusion from `_PROPAGATED_KEYS` byte-identical
   - `validator.py` my B4 migration intact inside Task 147's rewritten `_validate_template_in_source` helper, flowing into new `_build_template_node_diagnostic`
   - `runner.py` my Fix #3/#5/#6 annotations (`_pflow_shared_store`, OutputResolutionError skip, structured diagnostic pass-through) all preserved; Task 147's severity filter + `WorkflowValidationError(validation_warnings=...)` kwarg rename applied correctly; Task 149's `progress_callback` signature applied correctly

3. **`capture_baselines.py` rendering-regression tool** run against backup branch vs HEAD:
   - Copied the script to `/tmp/task148-rebase-baselines/` so it wouldn't touch the committed baselines in `.taskmaster/tasks/task_144/research/`
   - Ran `before` on backup branch, `after` on rebased HEAD, then `compare`
   - Result: every diff is an IMPROVEMENT from Task 147/149 landing. Validation errors render in titled format with `At:` line + suggestion arrow (was raw `Diagnostic(severity=...)` repr). `Available fields` block now renders with label + count. Multi-error list uses `Error N: Validation Error` format. `Nodes executed (N):` per-node block removed (lives in progress stream now). Context-key rendering: 60/123 (49%) → 64/129 (50%)
   - **Zero rendering regressions from my rebase itself**. All diffs are pre-existing Task 147/149 improvements the rebase correctly pulled in

4. **MaxNodeVisitsError factoid restored** — during the initial CLAUDE.md merge I dropped a minor note that `MaxNodeVisitsError` also implements `to_diagnostics()` despite not inheriting from `PflowError`. Restored as a follow-up amend.

### Committed Fixture Pattern (Option B)

The audit surfaced a broader question: `scratchpads/task148-verification/` held 24 `.pflow.md` workflows that caught BUG #1/#2/#3 during the post-completion verification passes, but they were local-only scratchpads per the "scratchpads are temporary" rule. The existing `test_failed_node_invariant.py` uses inline IR dicts exclusively — zero tests exercised the markdown parser → source_line → diagnostic chain end-to-end.

Discovered `examples/invalid/` had already established the pattern: committed `.pflow.md` files that double as regression fixtures (`test_example_validation.py` rglobs them, validates they fail parse/schema). Extended the pattern with a new `examples/error-handling/` subdirectory for RUNTIME error scenarios.

**6 scratchpad fixtures promoted with descriptive names:**

| Scratchpad | Committed as | Gap it closes |
|---|---|---|
| `04_no_coalesce_failed_ref.pflow.md` | `failed-node-direct-reference.pflow.md` | Rendered text with real failure details (exit_code, command, stderr) + paste-able coalesce fix using real peer name |
| `08_typo_on_failed.pflow.md` | `typo-on-failed-node.pflow.md` | `corrected_var` plumbing: fix suggestion must render `${primary.stdout ?? fallback.stdout}`, not `${primary.stddout ??...}` (double typo). Fix #5 regression guard |
| `09_loop_recovery.pflow.md` | `loop-recovery.pflow.md` | Final data flow after loop re-entry — `maybe-fail.stdout == "succeeded-on-retry"`, node in `shared_after` top-level, NOT in `__failures__` |
| `16_source_line_multi.pflow.md` | `source-line-multi-output.pflow.md` | Multi-output source line tracking: diagnostic points at first failing output's line, not the last |
| `18_source_line_offsets.pflow.md` | `source-line-heavy-offsets.pflow.md` | Parser `yaml_current_item_start_line` against real blank-line offsets (fixture has output at line 50) |
| `23_mixed_absent_failed.pflow.md` | `coalesce-mixed-absent-failed.pflow.md` | Fix #4 regression guard: `_format_all_unavailable_coalesce_summary` gate must be `status in ("failed", "absent")`, not only `"failed"` |

**6 new tests** in `tests/test_integration/test_failed_node_invariant.py` under the heading "End-to-end fixtures under examples/error-handling/":
- `test_example_failed_node_direct_reference_renders_pasteable_fix`
- `test_example_typo_on_failed_node_surfaces_failure_and_corrected_fix`
- `test_example_loop_recovery_final_state_is_succeeded`
- `test_example_source_line_multi_output_tracks_first_output_line`
- `test_example_source_line_heavy_offsets_tracks_correct_line`
- `test_example_coalesce_mixed_absent_failed_emits_summary_fix`

Helper: `_run_fixture(filename)` loads `examples/error-handling/<filename>` and runs it through `WorkflowRunner().run(str(path), ...)`. `_only_template_error(result)` filters out cache-lint warnings and returns the rendered text of the single template_error diagnostic.

**Mutation test on Fix #5 plumbing**: temporarily replaced `"corrected_var": secondary_hint` with `"corrected_var": None` in `template_errors.py`, verified `test_example_typo_on_failed_node_surfaces_failure_and_corrected_fix` fails with the exact assertion it was designed to catch (`${primary.stdout ?? fallback.stdout}` not in rendered — instead shows `${primary.stddout ?? fallback.stddout}` double-typo). Restored original, verified test passes. Proves the test is load-bearing, not accidentally passing.

**Performance**: 0.43s wall time for all 6 new tests (0.27s one-time pytest setup + 10-20ms per test call). Roughly 2-3x slower than inline-IR tests because they parse markdown; 20-30x FASTER than Task 149's subprocess tests because they don't spawn a process. Net impact on full suite: +6 tests / +~30-120ms out of ~10s — negligible.

### Decision rule documented in `tests/CLAUDE.md`

Added a "Choosing a Workflow Test Pattern" section codifying the four test patterns and when to use each:

| Pattern | Layer exercised | Cost | When |
|---|---|---|---|
| 1. Inline IR dict | Compiler+engine+runner | 5-10ms | Default — IR shapes, internal invariants, parameterized edges |
| 2. `tmp_path` fixture | Parser + full in-process | 20-30ms | Test-specific content, not reusable |
| 3. Committed fixture | Parser + full in-process + renderer text surface | 10-20ms | **See decision rule** |
| 4. Real subprocess | CLI surface (stderr, exit codes, logger) | 300-500ms | CliRunner-unreachable behavior |

**Pattern 3 decision rule (all 4 conditions must hold)**:
1. Scenario demonstrates user-facing behavior
2. Parser layer OR rendered output text is part of the assertion
3. You'd re-run it manually during debugging
4. Has a natural descriptive name

**Explicitly NOT a sweep**: the rule applies to NEW tests only. Existing inline-IR tests stay put. Dual-writing (same scenario as both inline IR and fixture) is banned — delete one. Fixture drift risk documented with three mitigations (README-documented contract, load-bearing substring markers, mutation testing).

Updated `examples/CLAUDE.md` to reference the new `examples/error-handling/` directory + its bound test file. Added `examples/error-handling/README.md` explaining each fixture's purpose and the dual-use pattern.

### Verification corpus disposition

The original `scratchpads/task148-verification/` held 24 `.pflow.md` workflows and an `inspect_shared.py` harness from the Post-Completion Verification Pass. Final disposition:

- **6 fixtures** promoted to `examples/error-handling/` with descriptive filenames and committed end-to-end tests (see Option B above). Those are the source of truth — the scratchpad duplicates were deleted to prevent drift.
- **18 fixtures + `inspect_shared.py`** moved to `.taskmaster/tasks/task_148/verification/` with a README that documents each fixture's scenario, the 3 bugs this corpus originally found, the harness usage, and a cross-reference to the 6 promoted fixtures. Task 147 established the same `verification/` subdirectory pattern for its manual testing plan, so this matches existing structure. The corpus is preserved as a ready-made adversarial probe for any future pass on Task 148's invariants.
- `scratchpads/task148-verification/` directory removed entirely after the move.

The 18 non-promoted fixtures intentionally do NOT have committed test bindings. They cover scenarios (batch + sub-workflow combinations, 3-way coalesce, cache + failure races, typo on succeeded, custom routing errors) that are edge cases relative to the main invariant. If a future bug surfaces in any of them, the appropriate move is: reproduce using the fixture, add a targeted inline-IR test OR promote the fixture to `examples/error-handling/` per the decision rule in `tests/CLAUDE.md`.

**`inspect_shared.py` retained** because the task-148 invariant verification workflow (dump `shared_after` → inspect `__failures__` vs top-level keys) is still the fastest way to sanity-check invariant changes, and the harness takes a workflow path as argument so it has no dependencies on fixture location.

Also removed `scratchpads/issue-208/` — the `#208` reproducer was already embedded verbatim in the GH #208 issue body, in `task-148.md` spec, and covered by the committed `test_coalesce_falls_through_to_fallback_on_primary_failure` inline-IR test. The scratchpad copy was a fourth redundant local-only version with drift risk.

### Fixture drift investigation — initial misdiagnosis

After the move, a parse+validate audit of the 18 verification fixtures under current code found 2 failures:

1. **`17_source_line_block.pflow.md`** — `SchemaValidationError: Additional properties are not allowed ('yaml' was unexpected). Output definitions can only have: description, type, source. Unknown field: 'yaml'`
2. **`22_routing_error.pflow.md`** — `MarkdownParseError: Node 'router' uses dynamic routing (next = <expression>) but has no '- next:' declaration. Fix: Add '- next:' listing all possible routing targets`

Initial conclusion (wrong): both fixtures were "stale" due to Task 147's parser hardening, the scenarios they tested were "unreachable under current schema", and they should be deleted. Proposed `rm` command.

**User pushback**: "since you misunderstood this, was the error message not good enough to make you understand?"

This was the correct call-out. Both error messages were fully actionable:

- **Fixture 22's error contained a literal `Fix:` line** with the exact edit (`- next: path_a, path_b`) and a concrete example. Applying it verbatim (plus keeping the dynamic assignment form, since a literal-string assignment would be caught by `_extract_next_targets_from_code` and treated as a declared target) would have worked in one shot.
- **Fixture 17's error explicitly listed allowed fields** (`description`, `type`, `source`) and called out `'yaml'` as the unknown field. Mapping this to the parser's code-block handling at `markdown_parser.py::_build_output_dict` (where `block.param_name == "source"` triggers source extraction while any other `param_name` stores content under that key) would have yielded the fix: rename the code fence from ````yaml` to ````source`.

What I actually did: ignored the `Fix:` line on 22, rewrote the code block in a way that produced a different error (literal string target not found), generalised that to "scenario unreachable", and was about to delete the fixture. For 17, concluded "code-block source form isn't supported" without trying the `source` fence name the error had effectively pointed at.

**Meta-lesson**: these error messages are the direct product of Task 148's and Task 147's agent-actionability work. They ARE good enough to give an AI agent the right answer in one shot — but only if the agent reads them carefully and applies the `Fix:` guidance literally before investigating around the error. Saved as `feedback_trust_error_messages.md` in memory so future sessions apply the same discipline.

### Fixture fixes applied

**`17_source_line_block.pflow.md`** — renamed output code fence from ````yaml` to ````source`. The fixture now correctly exercises the code-block path in `_build_output_dict` (`block.param_name == "source"` branch), which assigns `_source_line = block.start_line + 1`. Verified end-to-end: output resolves to `_source_line: 44`, the rendered diagnostic's `(at ...)` line shows `17_source_line_block.pflow.md:44`.

**`22_routing_error.pflow.md`** — added `- next: path_a, path_b` declaration to the router node, added `- next: end` to both branch targets to satisfy `_validate_branch_targets_have_next` (Task 147 hardening), and rewrote the code block to use a non-literal assignment (`_action: str = "not_a_real_action"; next: str = _action`) so the parser's AST analysis sees `has_dynamic=True` and skips the "literal target validation" branch. Verified end-to-end: `router.category == "routing_error"`, the failure record contains `"Node 'router' returned action 'not_a_real_action' but no successor edge matches. Available: ['path_a', 'path_b', 'default']"`.

Both fixtures now test exactly what their descriptions claim. Updated the README.md in the verification folder to document the fix rationale so a future agent reading these fixtures understands the parser contract (code-block fence name → output field name; dynamic vs literal `next:` detection via AST).

### Full corpus audit (post-fix)

All 18 fixtures under `.taskmaster/tasks/task_148/verification/` parse, validate, AND run end-to-end:

| Status | Count | Fixtures |
|---|---|---|
| `SUCCESS` | 8 | 01, 02, 06, 07, 11, 12, 14, 15 |
| `FAILED` (by design — testing failure paths) | 9 | 03, 05, 13, 17, 19, 20, 21, 22, 24 |
| `DEGRADED` | 1 | 10 (batch_partial_fail) |

Zero fixtures are "stale". The corpus is a fully functional adversarial probe set.

### Verification (seventh pass)

- `pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py` → **4783 passed** (was 4777 before Option B; +6 from the new fixture-based tests. The full delta from pre-rebase 4730 is +53 = +47 from Task 147/149 landing + +6 from Option B)
- `pre-commit run -a` → all hooks clean (ruff, ruff-format, mypy, deptry, trailing-whitespace, end-of-file, merge-conflict check)
- `mypy src/` → `Success: no issues found in 168 source files`
- `pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace` → `fallback-content`
- Task 149 subprocess tests (`test_progress_streaming_subprocess.py`) → 12/12 passing
- Task 148 regression tests (`test_node_state`, `test_failed_node_invariant`, `test_template_error_messages`, `test_output_resolver`, `test_template_resolver`) → 142 + 6 new = 148 passing
- Mutation test on Fix #5 `corrected_var` → test fails under mutation, passes after restore

### Files changed in seventh pass

Production (from rebase + Option B):
- All Task 148 production files preserved (byte-identical or with minor integrations into Task 147/149 changes)
- 1 code conflict resolved in `src/pflow/core/diagnostic.py` (preserved both `_format_available_fields_block` + `_format_template_error_lines`; restored dropped `_format_all_context_blocks` dispatch)

Docs (11 files):
- 8 CLAUDE.md conflict resolutions (`cli/`, `core/`, `core/workflow/`, `execution/`, `execution/formatters/`, `mcp_server/services/`, `runtime/compilation/`, `runtime/engine/`)
- `src/pflow/core/CLAUDE.md` — restored `MaxNodeVisitsError` `to_diagnostics()` factoid
- `tests/CLAUDE.md` — new "Choosing a Workflow Test Pattern" section with decision rule (~60 lines)
- `examples/CLAUDE.md` — added `error-handling/` subdirectory reference

New committed fixtures (7 files under `examples/error-handling/`):
- 6 `.pflow.md` workflows (promoted from scratchpads with descriptive names)
- `README.md` explaining the dual-use pattern

New tests (1 file, 6 tests):
- `tests/test_integration/test_failed_node_invariant.py` — new "End-to-end fixtures" section with 6 tests + 2 helpers (`_run_fixture`, `_only_template_error`)

Verification corpus moved + fixed (20 files under `.taskmaster/tasks/task_148/verification/`):
- 18 `.pflow.md` fixtures moved from `scratchpads/task148-verification/` (minus the 6 promoted ones)
- `inspect_shared.py` harness
- `README.md` — documents each fixture's scenario, the 3 bugs this corpus originally found, `inspect_shared.py` usage, cross-reference to the 6 promoted fixtures, and the files-to-watch-when-editing list
- 2 fixtures edited to match Task 147 parser hardening (17 code fence rename; 22 declared routing + dynamic `next:` form) — see "Fixture drift investigation" above

### Final commit state

Single squashed commit on `fix/resolve-coalesce-empty-string` rebased on top of Task 147 (`1bfac790`) and Task 149 (`ce920870`). Branch is rebased, tested, quality-gated, and ready for force-push to PR #251.

**Backup branch `backup/task-148-pre-rebase`** preserved at the pre-rebase HEAD for rollback if any post-push issue surfaces. Delete after PR merges.

## Eighth Pass — Code Review Response (2026-04-09)

Three independent code reviews arrived against PR #251: the bot review on the PR itself (`#issuecomment-4209874016`), `scratchpads/code-review-task148-20260408-160500.md` (a 3-warning focused review), and `scratchpads/code-review-task148-20260408-235050.md` (a detailed merge-readiness review with 5 warnings + 7 polish suggestions). After consolidating and verifying every finding against the actual code (4 parallel verification agents + direct file reads), 22 findings were confirmed, 1 was disputed (the double-flatten `display_data` spread — already investigated in the sixth pass and kept intentionally), and 3 critical findings were identified as pre-existing architectural gaps worth filing as follow-ups.

### Phase A — Critical correctness bugs (3 items)

**A1 — Priority inversion in `_extract_error_info` masked shell failures.** Pre-fix, when a shell node failed with `exit 1` and had no matching `on-error:` edge, the routing hint from `_handle_no_successor` (written to `__warnings__` as Task 148 Fix #2) was surfaced as the primary error message: `"Node 'broken' returned action 'error' but no successor edge matches..."`. The real `"Command failed with exit code 1"` was buried in context. Post-fix, `_extract_error_info` reorders its priority: the authoritative `get_node_failure(...).error` wins, the warning mirror is the last-resort fallback.

- **Sub-finding during verification**: reordering exposed a legitimate pre-existing contract for api_warnings. The detector extracts a canonical actionable message (`"API error (429): Rate limited"`) that was historically preferred over the node's raw `error` field (`"HTTP request failed"`). `handle_api_warning` was storing the raw node error as `failure.error` and the post-detector text only as `failure.warning`, so the A1 reorder would have surfaced the less-actionable raw error. **Fixed at the source**: `handle_api_warning` now passes `error=warning` (post-detector text is authoritative — it's what the detector extracted specifically to be user-facing). The raw node data is still preserved in `failure.data` for anyone who needs it.
- **Files**: `src/pflow/execution/executor_service.py` (`_extract_error_info`), `src/pflow/runtime/engine/instrumentation.py` (`handle_api_warning`)
- **Tests**: new end-to-end assertion in `test_shell_error_without_on_error_preserves_shell_data_in_failure_record` verifying the top-line error message contains "exit code 1" / "command failed" and NOT "no successor edge matches"; `test_api_warning_surfaces_detector_message_not_raw_node_error` updated to the post-Task-148 realistic fixture shape
- **Disputed-finding context**: 160500 W1 was correct about the inversion but didn't consider the api_warning case. The fix had to handle both paths.

**A2 — Stale `__warnings__` after loop recovery reported DEGRADED.** `mark_node_failed(..., warning=...)` writes `__warnings__[node_id]`, but `enforce_loop_guard` only called `clear_node_failure` which only popped `__failures__`. A node that failed via api_warning on visit 1 and succeeded on visit 2 left its warning mirror stale, and `_determine_status` reported DEGRADED even for a clean recovery. Fix: extended `clear_node_failure` to pop both dicts — keeps it the single place that handles "clean slate for a node".

- **Files**: `src/pflow/runtime/node_state.py` (`clear_node_failure`)
- **Tests**: `TestClearNodeFailure::test_clears_warning_mirror` (unit) + `test_loop_reentry_after_api_warning_reports_success_not_degraded` (E2E through `_determine_status`)

**A3 — Validator `var.split(".")[0]` misclassified indexed inputs as unused.** `_validate_unused_inputs` at `template_validation/validator.py:184` still used `var.split(".")[0]`. For `${items[0].name}` the split yielded `"items[0]"` (with bracket) which never matched the declared `items` → blocking false-positive `"Declared input(s) never used"`. B4 migration miss from the sixth pass. Fix: one-line migration to `TemplateResolver.extract_root_node_id`.

- **Files**: `src/pflow/runtime/template_validation/validator.py`
- **Tests**: new `test_input_used_with_indexed_access` — declare input `items`, template `${items[0].name}`, assert zero diagnostics
- **Bonus verification**: agent sweep confirmed no other sites still use the ad-hoc split for node-id extraction. The last B4 miss is now closed.

### Phase B — Test fidelity + doc drift (3 items)

**B1 — Loop-recovery test docstring mismatch.** Docstring at `test_example_loop_recovery_final_state_is_succeeded` said `/tmp/pflow-loop-recovery-marker`; fixture uses `/tmp/pflow-task148-marker`. Pure doc fix — the assertions never touched the marker path, but the drift proves the docstring wasn't re-verified after the fixture rename. Fix applied; hermeticity deferred because the engine-level `test_failed_then_succeeded_reentry_clears_failure_record` already provides a hermetic alternative and the fixture test's value is parser+runner coverage.

**B2 — Weak test redundancy.** `test_rendered_suggests_coalesce_fix` asserted only `"??" in rendered`. `test_rendered_substitutes_actual_peer_in_fix` (same fixture, same template, same render) asserts the exact paste-able string `${primary.stdout ?? fallback.stdout}` — strict superset. Deleted the weak test; inline comment documents why.

**B3 — Internal `__failures__` key leaked into user-facing text.** `diagnostic.py:393` rendered `"- {key} (failed — see error detail above or check __failures__)"`. The task spec explicitly treats `__failures__` as internal. Reworded to `(failed — see failure detail above)`. Added a regression assertion `"__failures__" not in rendered` to `test_template_error_shows_both_succeeded_and_failed_peers_in_context`.

### Phase C — Code quality polish (5 items)

**C1 — Deleted `determine_error_category` template_error regex fallback.** The `"${" in error_message or "template" in error_lower` branch was a pre-Task-148 heuristic that could misfire on shell commands echoing `${PATH}`. Since `mark_node_failed(category=FAILURE_CATEGORY_TEMPLATE)` is the authoritative source and `build_error_list` overwrites the regex result with `__failures__[id].category`, the regex path was only reachable for root-level errors with no failed_node — a scenario that in practice doesn't carry template errors. Deleted the branch; updated `test_determine_error_category_template_error` to assert `execution_failure` fallthrough.

**C2 — Type-validation permissive entries now carry a structured Diagnostic.** `template_resolution.py:366-370` appended type_validation entries as `{"message", "type", "param"}` — no `diagnostic` key. `runner._extract_runtime_warnings` had a legacy canned-hint fallback branch that fired for these entries, contradicting the `engine/CLAUDE.md` claim that every permissive entry carries a structured Diagnostic. Fix: build a minimal Diagnostic at the source site, attach it via `diagnostic` key. **Deleted the legacy fallback branch entirely** from `runner._extract_runtime_warnings` — entries without a Diagnostic are now contract violations, logged and skipped. Single code path in the runner, no dead branches.

- **Files**: `src/pflow/runtime/engine/template_resolution.py`, `src/pflow/execution/runner.py` (legacy branch deleted), `src/pflow/runtime/engine/CLAUDE.md` (doc updated to state all entries carry Diagnostic)
- **Tests**: new `test_extract_runtime_warnings_handles_type_validation_diagnostic` + `test_extract_runtime_warnings_skips_entries_without_diagnostic`

**C3 — Category-based dispatch for failure rendering (biggest C item).** `_extract_failure_display_data` and `_render_failure_data_block` both branched on data-key presence for HTTP (`"status_code" in data`) and MCP (`"server" in data and "tool" in data`), only dispatching on category for the shell path. A success output that happened to contain `status_code` could be misclassified as an HTTP failure. The underlying missing piece was `FAILURE_CATEGORY_HTTP` / `FAILURE_CATEGORY_MCP` constants — Task 148's original set only included shell/node_error/api_warning/routing/exception/template.

Fix (structural):
1. Added `FAILURE_CATEGORY_HTTP` and `FAILURE_CATEGORY_MCP` constants in `node_state.py`.
2. Added `infer_failure_category_from_data(data)` in `node_state.py` — a single explicit detection function that branches on `exit_code`+`command` → SHELL, `status_code` → HTTP, `error_details` with `server`+`tool` → MCP, else NODE_ERROR. This is the only site that sniffs data shape; every reader dispatches on the category string.
3. Refactored engine step 17.5 in `engine.py` to call `infer_failure_category_from_data()` instead of an inline if-else. Single line.
4. `_extract_failure_display_data` in `template_errors.py` now branches purely on category. Extracted the per-category field tuples as module constants (`_SHELL_DISPLAY_FIELDS`, `_HTTP_DISPLAY_FIELDS`, `_MCP_DISPLAY_FIELDS`).
5. `_render_failure_data_block` in `diagnostic.py` now branches purely on category.
6. `_FAILURE_CATEGORY_MAP` in `executor_service.py` maps `http_failure` and `mcp_failure` to `execution_failure` (same top-level title category).
7. `_describe_failure_category` in `diagnostic.py` includes HTTP/MCP descriptions.

- **Files**: `src/pflow/runtime/node_state.py`, `src/pflow/runtime/engine/engine.py`, `src/pflow/runtime/engine/template_errors.py`, `src/pflow/core/diagnostic.py`, `src/pflow/execution/executor_service.py`
- **Tests**: new `TestInferFailureCategoryFromData` class with 10 focused tests (including parameterized shapes) + 3 end-to-end integration tests (`test_step_17_5_assigns_http_category_from_data_shape`, `test_step_17_5_assigns_mcp_category_from_data_shape`, `test_render_failure_data_block_ignores_data_shape_when_category_is_generic`)

**C4 — Deleted unreachable defensive `clear_node_failure` in `handle_cached_execution`.** The call was documented as "currently unreachable" in `runtime/engine/CLAUDE.md` (memo cache skipped on revisits, loop guard already cleared, error results never cached). Deleted the 3 lines and updated CLAUDE.md. If future checkpoint-resume work makes it reachable, it should come back with a test exercising the reaching path — not as speculative defense.

**C5 — `mark_node_failed` raises on reserved internal keys.** Pre-fix, calling `mark_node_failed("__execution__", ...)` would silently skip the `shared.pop` but still write `__failures__["__execution__"]` AND `__execution__["failed_node"] = "__execution__"` — corrupting both dicts. Replaced the silent guard with an explicit `ValueError("reserved internal key")`. All current callers pass `config.node_id` (IR-validated), so this is pure defense-in-depth. New unit test `test_rejects_reserved_internal_keys`.

### Disputed finding

**Double-flatten of `display_data` (235050 W2)** — verified NOT dead per the sixth-pass adversarial verification. Tests read `failure["exit_code"]` directly (not `failure["data"]["exit_code"]`) at multiple sites, and the `**display_data` spread is load-bearing for that contract. Progress log already documents the decision. No action.

### Follow-up issues filed (4 new)

Pre-existing architectural gaps worth tracking but out of scope for this PR:

- **spinje/pflow#252** — Batch × sub-workflow × failed child loses structured `__failures__` records (related to but distinct from #233 sub-workflow Diagnostic propagation — this is the batch combination specifically)
- **spinje/pflow#253** — MCP protocol errors bypass step 17.5 via the `return "default"` workaround. Task 148 C3 adds MCP category handling for tool errors (which correctly return `"error"`), but protocol errors remain unarchived. Design options included in issue body.
- **spinje/pflow#254** — `storage_mode: shared` sub-workflows leak child `__failures__` into parent. Pre-existing aliasing bug exposed by Task 148's single-write-site discipline. Recommendation: deprecate `storage_mode: shared` (already causes #231 + now this).
- **spinje/pflow#255** — Pre-engine exception annotation gap + `registry_run.py` engine bypass (bundled — both low-priority brittleness observations).

### Verification

- `pre-commit run -a` → clean (ruff, ruff-format, all hooks pass)
- `mypy src/` → `Success: no issues found in 168 source files`
- `deptry src` → `Success! No dependency issues found.`
- `pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py` → **4802 passed** (was 4783 at end of pass 7; net +19 new regression tests across A/B/C)
- GH #208 reproducer → still produces `fallback-content`

### Files changed (eighth pass)

Production (7 files):
- `src/pflow/execution/executor_service.py` — A1 `_extract_error_info` reorder + `_FAILURE_CATEGORY_MAP` entries for HTTP/MCP + C1 regex deletion
- `src/pflow/runtime/engine/instrumentation.py` — A1 `handle_api_warning` uses post-detector warning as authoritative error + C4 deleted defensive `clear_node_failure`
- `src/pflow/runtime/node_state.py` — A2 `clear_node_failure` extended to `__warnings__` + C3 new constants + `infer_failure_category_from_data()` + C5 raise on reserved keys
- `src/pflow/runtime/template_validation/validator.py` — A3 migrate to `extract_root_node_id`
- `src/pflow/runtime/engine/engine.py` — C3 step 17.5 uses `infer_failure_category_from_data()`
- `src/pflow/runtime/engine/template_resolution.py` — C2 build structured Diagnostic for type_validation entries
- `src/pflow/runtime/engine/template_errors.py` — C3 `_extract_failure_display_data` category dispatch + module constants
- `src/pflow/core/diagnostic.py` — B3 reword + C3 `_render_failure_data_block` category dispatch + C3 `_describe_failure_category` entries
- `src/pflow/execution/runner.py` — C2 delete legacy fallback branch in `_extract_runtime_warnings`

Docs (1 file):
- `src/pflow/runtime/engine/CLAUDE.md` — C2 doc update for type_validation path + C4 doc update for `handle_cached_execution`

Tests (6 files):
- `tests/test_integration/test_failed_node_invariant.py` — A1 assertion + A2 E2E + B3 no-leak + C3 three integration tests + B1 docstring fix
- `tests/test_runtime/test_node_state.py` — A2 unit + C3 `TestInferFailureCategoryFromData` + C5 rejection test
- `tests/test_runtime/test_template_validation/test_unused_inputs.py` — A3 indexed-input regression
- `tests/test_runtime/test_template_error_messages.py` — B2 delete weak test + tighten "Exit code: 1" assertion
- `tests/test_execution/test_runner.py` — C2 two new tests (type_validation diagnostic + skip without diagnostic)
- `tests/test_execution/test_api_warning_system.py` — A1 update fixture to post-Task-148 realistic shape + rename test

## Ninth Pass — Final Polish (2026-04-09)

Post-eighth-pass review of the staged diff identified one clear improvement missed by the code-review response and two borderline items worth fixing. An independent agent review was also evaluated — its finding about `infer_failure_category_from_data` led to a structural simplification.

### Structural simplification: node-type mapping replaces data-shape inference

**Deleted `infer_failure_category_from_data`** (28-line function in `node_state.py`). The function inferred failure category by sniffing data-key shapes (`exit_code`+`command` → shell, `status_code` → HTTP, `error_details` with `server`+`tool` → MCP). This was a heuristic — and `config.node_type_name` was already in scope at step 17.5, providing the authoritative node type from compile time.

**Replaced with**: a 3-entry dict `_NODE_TYPE_FAILURE_CATEGORY` in `engine.py` mapping class names (`ShellNode`/`HttpNode`/`MCPNode`) to category constants. One dict lookup at step 17.5, no data-shape heuristic.

This is more aligned with C3's stated goal — C3 moved data-key sniffing out of renderers, but `infer_failure_category_from_data` reintroduced it at the write site. The mapping eliminates the last data-shape sniffer in the codebase.

- **Files**: `src/pflow/runtime/node_state.py` (function deleted), `src/pflow/runtime/engine/engine.py` (mapping dict + call site), `src/pflow/runtime/engine/template_errors.py` (docstring updated), `src/pflow/core/diagnostic.py` (docstring updated)
- **Tests**: deleted `TestInferFailureCategoryFromData` (11 tests); updated 2 integration tests to verify the mapping dict + downstream render chain instead of the deleted helper

### Three polish fixes

**P1 — Inline imports → top-level in `engine.py`.** Three inline `from pflow.runtime.node_state import ...` blocks (at `_handle_no_successor`, step 17.5, and exception path) moved to the top-level import block. `node_state.py` imports only from `enum` and `typing` — zero circular import risk (verified). Follows codebase convention, eliminates per-call lookup overhead.

**P2 — `_extract_field_name` → `_extract_field_path` in `diagnostic.py`.** The function returns the post-root path (`primary.data.inner` → `data.inner`), not the leaf field name as the docstring claimed. Renamed with corrected docstring: `"primary.stdout" → "stdout"`, `"primary.data.inner" → "data.inner"`.

**P3 — Intentional transient state comment in `test_node_state.py`.** `test_failed_takes_priority_over_succeeded` deliberately sets up a node in BOTH `shared` and `__failures__` (the XOR violation). Added a comment explaining this is intentional and can't persist in production, to prevent a future reader from "fixing" it.

### Verification

- `ruff check src/` → All checks passed
- `mypy src/` → Success: no issues found in 168 source files
- `pytest -n 4 --doctest-modules` → **4791 passed** (was 4802; net −11 from deleted `TestInferFailureCategoryFromData`)
- GH #208 reproducer → still produces `fallback-content`

### Files changed (ninth pass)

Production (4 files):
- `src/pflow/runtime/engine/engine.py` — P1 top-level imports + `_NODE_TYPE_FAILURE_CATEGORY` mapping dict + step 17.5 uses dict lookup
- `src/pflow/runtime/node_state.py` — deleted `infer_failure_category_from_data`
- `src/pflow/core/diagnostic.py` — P2 rename + docstring update for mapping approach
- `src/pflow/runtime/engine/template_errors.py` — docstring update for mapping approach

Tests (2 files):
- `tests/test_runtime/test_node_state.py` — deleted `TestInferFailureCategoryFromData` (11 tests) + P3 comment
- `tests/test_integration/test_failed_node_invariant.py` — updated 2 integration tests to verify mapping dict

## Final Status (all nine passes)

- **22 bugs fixed in original implementation** + **1 latent bug** (silent-render gap, sixth pass) + **1 silent auto-merge drop** (`_format_all_context_blocks`, seventh pass rebase) + **3 correctness bugs + 5 polish fixes** (eighth pass code-review response) + **1 structural simplification + 3 polish fixes** (ninth pass) = **36 fixes total**
- **33 new regression tests** (18 from passes 1-5 + 1 from pass 6 + 6 from pass 7 committed fixtures + 19 from pass 8 − 11 deleted in pass 9)
- **+7 unit tests** for the `extract_first_field_segment` helper (pass 6)
- **9 new GH issues filed**, **1 updated** (5 from passes 1-5 + 4 from pass 8)
- **6 committed fixture files** + 1 README in `examples/error-handling/` (pass 7)
- **1 new test-pattern decision rule** in `tests/CLAUDE.md` (pass 7)
- **4791 tests passing**, **0 warnings**, **0 type errors**, **0 dependency issues**, **0 pre-commit failures**
- Branch rebased onto current main (Task 147 + Task 149 integrated cleanly)
- **Local commits on `fix/resolve-coalesce-empty-string`** — ready for review and commit to PR #251
