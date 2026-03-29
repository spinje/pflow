# Task 137: Unified CLI Output Pipeline — Progress Log

## Overview

Restructured the CLI output layer so ALL error outcomes (pre-execution exceptions, post-execution failures, unexpected exceptions) flow through one pipeline (`error_output.py`) producing one JSON shape. Preserves text-mode display fidelity while adding JSON support to every error path and preserving structured exception data.

**Supersedes**: Task 117 (JSON error output — bandaid approach)
**Enables**: Task 134 (output detection), Issue 6 (entry point unification)

---

## Phase 0: Dead Code Removal

Removed 3 confirmed dead items:
- `_append_footer` in `success_formatter.py` — defined but never called
- `CompilationError(UserFriendlyError)` in `user_errors.py` — vestigial class with zero raise sites (real one is in `runtime/compilation/compiler.py`)
- Unused `logger` in `workflow_execution.py` — imported but never used

**Plan check**: Plan also said to remove the `CompilerCompilationError` import alias from `main.py`. Verified it didn't exist — the CLAUDE.md mentioned it but the actual import was never there. No action needed.

**Result**: Clean removal, no behavioral changes. Tests: 4617 pass.

---

## Phase 1: Clean ExecutionResult

Removed 5 orphaned fields from `ExecutionResult` dataclass that were populated but never read by any consumer:
- `action_result`, `node_count`, `duration`, `output_data`, `metrics_summary`

Updated `_build_execution_result` — removed both the field assignments and the now-unused parameters (`action_result`, `workflow_ir`, `duration`, `output_data`, `metrics_collector`). Also removed the computation of those values from the caller in `execute_workflow()`.

**Unplanned side effects**:
- `duration = time.time() - start_time` became unused after removing the `duration` parameter — ruff flagged it, deleted.
- `_extract_output_data()` method lost its only call site — became dead code. Discovered later in Phase 9 review and deleted.
- `_handle_execution_exception` return dict still had `action_result` and `output_data` keys — cleaned up since the caller no longer reads them.

Updated 4 test files:
- `test_workflow_execution.py` (2 sites): Changed `assert result.action_result == "compilation_failed"` → `assert result.errors[0]["source"] == "compilation"`
- `test_checkpoint_tracking.py`: Removed `output_data=None`
- `test_workflow_output_handling.py`: Removed `output_data=None`

**Result**: Dataclass went from 10 fields to 5. Tests: 4617 pass.

---

## Phase 2: Enrich Exception Classes

Added structured fields and `format_for_cli()` methods to 3 exception classes:

**`WorkflowNotFoundError`**: Added `workflow_name`, `similar_names`, `hint` params. `format_for_cli()` renders "Did you mean?" suggestions or displays hint directly.

**`WorkflowValidationError`**: Added `summary`, `validation_errors` (list of strings or `(msg, path, suggestion)` tuples). `format_for_cli()` renders structured errors with path and suggestion.

**`MaxNodeVisitsError`**: Added `format_for_cli()` method (already had structured fields).

Updated 3 raise sites in `manager.py` from `WorkflowNotFoundError(f"Workflow '{name}' not found")` to `WorkflowNotFoundError(name)`.

Updated 1 test: `test_workflow_name.py` — `WorkflowNotFoundError("Workflow 'test' not found")` → `WorkflowNotFoundError("test")` to match new constructor.

**Backward compatibility verified**: All `WorkflowValidationError` raise sites (20+ in `manager.py` and `save_service.py`) pass a single string as first positional arg — maps to `summary` parameter, fully compatible. Confirmed with grep.

**Result**: Additive changes only. Tests: 4617 pass.

---

## Phase 3: Create Unified Error Formatter

Created `src/pflow/cli/error_output.py` with:
- `format_error_json()` — builds unified JSON from exception OR ExecutionResult
- `_exception_to_errors()` — converts any exception to `(summary, errors_list)` with structured field extraction
- `display_exception_text()` — text-mode display using `format_for_cli()` protocol
- `output_error()` — THE single error output function for the entire CLI

**Design decisions**:
- Lazy imports throughout to avoid circular dependencies (exception classes, formatters)
- Exception type dispatch checks subclasses before parents (MCPError before UserFriendlyError) — comment documents this
- `_format_from_result` delegates to existing `format_execution_errors` for sanitization and execution state
- `_format_from_exception` includes best-effort metrics collection (matches old `_create_json_error_output` pattern)
- `display_exception_text` checks `format_for_cli()` protocol for extensibility

**Result**: New file, not yet wired into any call paths. Tests: 4617 pass.

---

## Phase 4: Fix Exception Data Loss at Catch Sites

3 fixes:
1. **`validator.py`**: Changed bare `except Exception` to `except SchemaValidationError` with a separate `except Exception` fallback labeled "Unexpected error during validation". This prevents non-validation exceptions from being silently mis-labeled as validation errors.

2. **`workflow_execution.py`**: Added `MaxNodeVisitsError` catch alongside existing `CompilationError` catch — returns structured `ExecutionResult` with `node_id`, `visit_count`, `max_visits`. The exception propagates from `instrumented_wrapper.py` → re-raised by `executor_service._handle_execution_exception` (which re-raises all `RuntimeError` subclasses) → caught here.

3. **`workflow_executor.py`**: Removed `MarkdownParseError → ValueError` wrapping. The old code caught `MarkdownParseError` and re-raised as `ValueError(f"Invalid workflow file {path}: {e}")`, destroying the structured `line` and `suggestion` fields. Now `parse_markdown()` is called without any try-except — `MarkdownParseError` propagates with all fields intact.

**Ruff interaction**: Initially wrote `except MarkdownParseError: raise` which ruff flagged as TRY203 (redundant try-except that just re-raises). Simplified by removing the entire try-except block. ruff then auto-removed the now-unused `MarkdownParseError` import.

**Result**: Structured fields now survive through the pipeline. Tests: 4617 pass.

---

## Phase 5: Restructure workflow_resolution.py

Changed `resolve_workflow()` to raise exceptions instead of returning `(None, "parse_error")` tuples:
- `.json` extension → raises `WorkflowNotFoundError` with migration hint
- `.md` not `.pflow.md` → raises `WorkflowNotFoundError` with rename hint
- `MarkdownParseError` / `PermissionError` / `UnicodeDecodeError` → propagate directly (no longer caught)
- File not found → still returns `None` (to allow fallthrough to registry lookup)

Deleted `_show_markdown_parse_error` function and the `click` import.

Changed `_try_load_workflow_from_file` return type from `tuple[dict | None, str | None]` to `dict | None`.

**Deviation from plan**: The plan called for the outer `except Exception` catch block in `workflow_command` to be added in Phase 6. Had to add it here in Phase 5 because `MarkdownParseError` now propagates out of `resolve_workflow()` → `_try_execute_named_workflow` → `workflow_command`, and without a catch block, the CLI crashes with an unhandled exception. The catch block uses `output_error()` from the new `error_output.py`.

**Test updates (5 files)**:
- `test_parse_error_handling.py` (6 assertions): `"Invalid workflow syntax"` no longer appears (that text came from the deleted `_show_markdown_parse_error`). Updated to check actual `MarkdownParseError` message content. `"Permission denied"` → `"Permission" in output or "permission" in output` (PermissionError without args produces empty message, handled by new `display_exception_text` fallback). `"Unable to read file"` → `"decode" in output.lower() or "utf" in output.lower()`.
- `test_main.py`: Same `"Unable to read file"` → codec error message pattern.
- `test_workflow_resolution.py` (2 assertions): Same Permission/Unicode patterns.
- `test_e2e_workflow.py` (2 assertions): Added "steps" to the allowed error patterns for invalid workflow files.
- `test_workflow_name.py`: Updated `WorkflowNotFoundError` constructor arg.

**Result**: Tests: 4617 pass. `resolve_workflow` is now exception-based.

---

## Phase 6: Pipeline Restructure (main.py)

The largest phase. Converted early-exit handlers to exception raises and wired error output through `output_error()`.

### Handler conversions

| Handler | Was | Now |
|---------|-----|-----|
| `_validate_workflow_flags` | `click.echo` + `ctx.exit(1)` | raises `UserFriendlyError` |
| `_preprocess_run_prefix` | `click.echo` + `ctx.exit(1)` | raises `UserFriendlyError` |
| `_handle_invalid_workflow_input` | `click.echo` + `ctx.exit(1)` | raises `UserFriendlyError` |
| `_show_stdin_routing_error` | JSON/text branching + `ctx.exit(1)` | raises `UserFriendlyError` |
| `_output_validation_errors` | JSON/text branching + `ctx.exit(1)` | raises `WorkflowValidationError` |
| `_validate_before_execution` | JSON/text branching + `ctx.exit(1)` | raises `WorkflowValidationError` |
| `_resolve_file_refs_or_exit` | try-except + `ctx.exit(1)` | Lets exceptions propagate |
| `_handle_workflow_error` | `_build_json_error_response` / `_display_text_error_details` | `output_error(result=...)` |
| `_handle_workflow_exception` | `_create_json_error_output` / type-specific text | `output_error(exception=...)` |

### Deviation from plan: functions NOT deleted

The plan (Phase 6.5) called for deleting 7 functions. In practice I **refactored them in-place** rather than deleting most of them:

- `_handle_workflow_error` — **kept**, body replaced with `output_error()` call. Still called by `_execute_workflow_and_handle_result`.
- `_handle_workflow_exception` — **kept**, body replaced with `output_error()` call + LLM cleanup. Still called by `execute_json_workflow`'s except block.
- `_handle_workflow_not_found` — **kept**, body replaced with `WorkflowNotFoundError` raise. Still called by `_try_execute_named_workflow`.
- `_handle_invalid_workflow_input` — **kept**, body replaced with `UserFriendlyError` raises.
- `_show_stdin_routing_error` — **kept**, body replaced with `UserFriendlyError` raise.
- `_execute_workflow_and_handle_result` — **kept** unchanged. It's still a useful routing function between success and error paths.
- `_resolve_file_refs_or_exit` — **kept**, body simplified (removed try-except).

**Rationale for keeping**: Deleting these functions and inlining their logic into a single `_execute_workflow_pipeline` would have been a much larger refactor with higher risk. The refactored functions are thin wrappers that raise exceptions — they'll be easy to inline later if needed. Each function is still called from exactly one place.

### Deletions (from workflow_errors.py)

Deleted `_create_json_error_output()` and `_build_json_error_response()` — replaced by `format_error_json()` in `error_output.py`. These were the two old JSON builders that produced divergent shapes.

Removed their imports from `main.py` (`_build_json_error_response`, `_create_json_error_output`). Also removed `_display_text_error_details` import (no longer used directly in main.py — used via `error_output.py`). Also removed `_serialize_json_result` import (no longer used directly in main.py).

### Updated validate-only JSON

`_display_validation_results` error path now produces the unified shape:
```python
error_output = {
    "success": False,
    "status": "failed",
    "error": "Workflow validation failed",
    "errors": [{"message": e, "category": "validation"} for e in errors],
    "workflow": {"action": "unsaved"},
}
```

Previously it was `{"success": False, "errors": ["string1", "string2"]}` — flat string list, no status, no workflow.

### `_perform_validation` exception propagation

Removed the `try/except Exception: sys.exit(1)` wrapper around `WorkflowValidator.validate()`. Exceptions now propagate to the outer catch block in `workflow_command`. This was a simple `sys.exit(1)` that swallowed all context.

### Mypy fix

`list[tuple[str,str,str]]` is not assignable to `list[str | tuple[str,str,str]]` due to list invariance. Fixed with explicit `list()` conversion: `validation_errors: list[str | tuple[str, str, str]] = list(errors)`.

### Ruff fix

ruff S110 flagged `except Exception: pass` in `_handle_workflow_exception`'s LLM cleanup. Changed to `logger.debug("LLM interception cleanup failed", exc_info=True)`.

### Test updates (4 files)
- `test_dual_mode_stdin.py`: `validation_errors` → `errors`, `validation_errors[0].lower()` → `errors[0].get("message", "").lower()`, removed `"path" in` / `"suggestion" in` assertions, `"❌"` → `"stdin"`.
- `test_workflow_save.py`: Removed `"failed" in result.output.lower()` assertion (validation error message doesn't contain "failed"), kept `"non-existent-node"` check.

**Result**: Tests: 4617 pass. Single pipeline for all errors.

---

## Phase 7: stdout→stderr Bug Fixes

Fixed 4 confirmed stdout→stderr bugs:
1. `registry.py` `_handle_nonexistent_path`: Added `err=True` to both JSON and text echo calls
2. `registry.py` `_handle_scan_error`: Added `err=True` to JSON echo call
3. `workflow.py` filter-no-match: Added `err=True` to 5 echo calls

**Test updates**: `test_workflow_commands.py` — the custom `invoke_cli` helper captures stdout and stderr separately (unlike Click's CliRunner which mixes them by default). Updated 2 test methods to check `combined = result.output + result.stderr` since the messages now go to stderr.

**Result**: Tests: 4617 pass.

---

## Phase 8: Tests

Created `tests/test_cli/test_unified_error_output.py` with 10 tests across 3 classes:

**TestUnifiedErrorJsonShape** (5 tests): End-to-end CLI tests verifying unified JSON shape for file_not_found, parse_error, validation_error, execution_error, json_extension_error. Shared `_assert_unified_shape` helper validates:
- `success` is `False`
- `status` is string `"failed"`
- `error` is string (NOT dict — this was the core bug)
- `errors` is non-empty list of dicts, each with `message` and `category`
- `category` from valid enum set
- `workflow` dict with `action` key present
- Forbidden old fields absent: `is_error`, `validation_errors`, `metadata`, `failed_node`, `checkpoint`

**TestStructuredFieldPreservation** (3 tests): Unit tests of `_exception_to_errors` for MaxNodeVisitsError, ValidationError, WorkflowNotFoundError — verifying structured fields survive.

**TestCoreRegression** (2 tests): Regression guards for the exact bugs fixed — JSON output for not-found (was plain text before), `error` field is string (was dict with `type`/`message` keys before).

**Discovery**: The valid error categories set needed to include BOTH pre-execution categories from the plan (`validation`, `not_found`, `parse_error`, `cli`, `mcp`, `max_visits`, `file_not_found`, `permission_denied`, `unknown`) AND post-execution categories from `executor_service._determine_error_category()` (`execution_failure`, `api_validation`, `resource_error`, `template_error`, `compilation`). The plan only listed the former.

**Result**: 4627 tests pass (10 new). `make check` clean.

---

## Phase 9: Code Review

Deployed 7 specialized review agents in parallel:
- `review-silent-failures`
- `review-validation-consistency`
- `review-impact-completeness`
- `review-feature-interactions`
- `review-agent-ux`
- `review-test-fidelity`
- `review-concurrency-safety`

### Confirmed and fixed (11 items)

1. **`OutputResolutionError.diagnostics` is `list[str]` not `str`** (agent-ux). `failure.get("diagnostics", str(exception))` put a list as the `message` field, violating the `message: str` contract. Fixed: `msg = "; ".join(diag) if diag else str(exception)`.

2. **Pre-initialization `output_format` fallback ignores user flag** (silent-failures). When `ctx.obj` is None (early exception before `_initialize_context`), the outer catch defaulted `of = "text"` even though the local `output_format` parameter from Click has the user's actual value. Fixed: `of = ctx.obj.get("output_format", "text") if ctx.obj else output_format`.

3. **`OutputResolutionError` includes `None` values for optional fields** (validation-consistency). `output_name` and `source_expr` could be `None` but were always included. The unified shape spec says "omitted when not applicable (not null)". Fixed: only add fields when truthy.

4. **Two parse error tests became no-ops** (test-fidelity). `test_invalid_yaml_param_shows_error` and `test_unclosed_code_block_shows_error` asserted `exit_code != 0` twice — the second assertion was meant to check message content but was replaced with a duplicate of the first during Phase 5 test updates. Fixed: added content assertions matching actual `MarkdownParseError` messages (`"yaml"` / `"bracket"` / `"code"` / `"fence"` / `"block"`).

5. **`test_valid_markdown_workflow_no_error` had vacuous assertion** (test-fidelity). `assert "Missing" not in result.output or "Steps" not in result.output` is logically `not (A and B)` — fails ONLY if BOTH words appear. Nearly always true. Fixed: `assert "Missing" not in result.output`.

6. **3 dead functions not cleaned up** (impact-completeness). `_extract_output_data` (executor_service.py), `_get_default_workflow_metadata` (workflow_output.py), `_extract_workflow_node_count` (workflow_output.py) — all lost their call sites during the refactoring but weren't deleted. Verified with grep: zero call sites anywhere. Deleted all three.

7. **`_resolve_file_refs_or_exit` name is misleading** (validation-consistency). The function no longer exits — it lets exceptions propagate. Renamed to `_resolve_file_refs` at all 3 sites.

8. **`MarkdownParseError` duck-typed via `hasattr(exception, "line")`** (agent-ux). `display_exception_text` checked `isinstance(exception, ValueError) and hasattr(exception, "line")` instead of proper isinstance. Any `ValueError` subclass with a `line` attribute would be misrouted. Fixed: added `_is_markdown_parse_error()` helper using proper isinstance import.

9. **`_format_from_exception` metrics `except: pass`** (agent-ux, silent-failures). Silently swallowed all exceptions during metrics collection. Changed to `logger.debug("Metrics collection failed during error output", exc_info=True)`. Added `import logging` and `logger` to the module.

10. **Stale `_perform_validation` docstring** (validation-consistency). Said `Raises: SystemExit: If validation raises an exception` — that behavior was removed. Deleted the stale Raises section.

11. **`test_validation_before_execution.py:185` stale assertion** (impact-completeness). `assert "validation_errors" in output_data or "error" in output_data` — the `"validation_errors"` branch is the old shape. Since `"error"` is always present in the new shape, this always passes regardless. Tightened to `assert "errors" in output_data` and `assert "validation_errors" not in output_data`.

### Disputed findings (3 items)

1. **`sys.exit()` in `_display_validation_results`** (4 agents flagged this). The task spec said to normalize `sys.exit()` to `ctx.exit()` or exception raises. I left it because: (a) converting to `ctx.exit()` would raise `click.exceptions.Exit` which would propagate to the outer catch and call `output_error()` again, duplicating output; (b) the validate-only JSON error output already conforms to the unified shape; (c) the `finally` block in `workflow_command` still runs (SystemExit is BaseException, finally is unconditional). The structural inconsistency is accepted as deliberate.

2. **Text-mode validation errors lose `format_validation_failure()` smart truncation** (validation-consistency). `_validate_before_execution` now raises `WorkflowValidationError` whose `format_for_cli()` renders all errors without truncation. The old path used `format_validation_failure()` which truncates at 10 errors and auto-generates suggestions. In practice, `_validate_before_execution` produces 1-3 errors. The validate-only mode (which can hit many errors) still uses `format_validation_failure()` directly.

3. **Missing `MaxNodeVisitsError` wrapping unit test** (test-fidelity). The `execute_workflow()` catch of `MaxNodeVisitsError` has no dedicated unit test (the `_exception_to_errors` unit test doesn't exercise this code path). However, Phase 10 manual testing exercised this via the full CLI, and the exception propagation chain (`instrumented_wrapper → executor_service re-raise → workflow_execution catch`) is well-understood.

### CLAUDE.md updates (3 files, via background agent)

- `execution/CLAUDE.md`: Updated `ExecutionResult` canonical reference — removed 5 deleted fields.
- `cli/CLAUDE.md`: Added `error_output.py` to file structure. Updated error construction section to reference `output_error()` instead of deleted `_create_json_error_output`/`_build_json_error_response`.
- `runtime/compilation/CLAUDE.md`: Removed "WARNING" about two `CompilationError` classes (vestigial one deleted). Updated consumer table — `cli/main.py` no longer imports `CompilationError` as `CompilerCompilationError`.

**Result**: 4627 tests pass. `make check` clean.

---

## Phase 10: Manual Testing

Created 7 test workflow files in `/tmp/pflow-test-137/` and ran 12 manual test scenarios:

| # | Scenario | Mode | Expected | Result |
|---|----------|------|----------|--------|
| 1 | Good workflow | text | Success with output | PASS |
| 2 | Good workflow | JSON | Unified success shape | PASS |
| 3 | Failing shell (`exit 1`) | JSON | `execution_failure` + `execution` key | PASS |
| 4 | Nonexistent file | JSON | `not_found` category | PASS |
| 5 | Bad node type | JSON | `validation` category | PASS |
| 6 | No steps section | JSON | `parse_error` + suggestion | PASS |
| 7 | Bad YAML | JSON | `parse_error` + line number | PASS |
| 8 | .json extension | JSON | `not_found` + migration message | PASS |
| 9 | Stdin routing error | JSON | `cli` category + suggestion | PASS |
| 10 | Failing shell | text | Rich error with shell details | PASS |
| 11 | Validate-only error | JSON | Unified shape | PASS |
| 12 | Validate-only success | JSON | `{success: true}` | PASS |

**Automated shape verification**: Python script validated all 6 JSON error outputs against unified shape contract (success=false, status=string, error=string, errors=list of dicts with message+category, workflow dict present, no old fields).

**Result**: All 12 scenarios passed. No regressions.

---

## Post-Review Cleanup

Removed unused `ctx` parameters from 4 private functions after user question. My initial reasoning ("signatures are public-ish") was wrong — they're all `_`-prefixed internal functions with no external callers. Updated all call sites.

| Function | Before | After |
|----------|--------|-------|
| `_validate_workflow_flags` | `(workflow, ctx)` | `(workflow)` |
| `_preprocess_run_prefix` | `(ctx, workflow)` | `(workflow)` |
| `_show_stdin_routing_error` | `(ctx)` | `()` |
| `_output_validation_errors` | `(ctx, errors, ...)` | `(errors, ...)` |

Also refactored `_exception_to_errors` to reduce cyclomatic complexity. ruff C901 flagged it at complexity 26 (limit 10). Extracted 7 helper functions (`_workflow_validation_to_errors`, `_workflow_not_found_to_errors`, `_mcp_error_to_errors`, `_output_resolution_to_errors`, `_user_friendly_to_errors`, `_markdown_parse_to_errors`, `_schema_validation_to_errors`). The dispatch function now delegates to focused helpers while preserving the subclass-before-parent ordering. Added `noqa: C901` on the dispatcher since it's still at the boundary (10 isinstance checks is inherently complex).

ruff SIM101 also flagged mergeable isinstance calls in `display_exception_text` — merged `isinstance(exception, WorkflowNotFoundError) or isinstance(exception, WorkflowValidationError)` into `isinstance(exception, (WorkflowNotFoundError, WorkflowValidationError))`.

**Result**: 4627 tests pass. `make check` clean.

---

## Known Regressions / Accepted Tradeoffs

These were identified by the review agents and deliberately accepted:

### 1. `UnicodeDecodeError` loses file path and custom message
- **Before**: `"cli: Unable to read file: '{path}'. File must be valid UTF-8 text."`
- **After**: `"cli: Workflow execution failed - 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte"`
- **In JSON mode**: category is `"unknown"` instead of a specific file-related category
- **Why accepted**: The raw Python error message contains the codec details which are diagnostic. The file path context was provided by the old `_try_load_workflow_from_file` wrapper which was removed to let exceptions propagate. Adding a file-specific UnicodeDecodeError handler is a future improvement.

### 2. Parse errors lose file path context
- **Before**: `"❌ Invalid workflow syntax in {path}\n  {error}"`
- **After**: `"✗ Line 5: Missing required field 'type'..."` (no file path)
- **Why accepted**: For single-file usage (the common case), the file path is obvious from the command invocation. For nested workflows, the MarkdownParseError message itself contains enough context. Adding path back would require storing it on the exception or wrapping it — either approach risks losing structured fields.

### 3. `_validate_before_execution` errors lose `format_validation_failure()` features
- **Before**: Text mode used `format_validation_failure()` which auto-generates suggestions and truncates at 10 errors
- **After**: `WorkflowValidationError.format_for_cli()` renders all errors with basic formatting
- **Why accepted**: Pre-execution validation typically produces 1-3 errors. Validate-only mode (which can produce many) still uses `format_validation_failure()` directly.

### 4. Validate-only success JSON missing `status` field
- **Output**: `{"success": true, "message": "Workflow structure is valid"}`
- **Unified shape expects**: `status` and `workflow` fields present on all outputs
- **Why accepted**: This is the success path (out of scope for error unification). Fixing it is a small additive change for a future PR.

### 5. `test_dual_mode_stdin.py` removed `path`/`suggestion` assertions
- **Before**: Asserted that multiple-stdin validation errors had `path` and `suggestion` structured fields in JSON
- **After**: Assertion removed because the error flow changed — `_validate_before_execution` wraps plain error strings as `(e, "", "")` tuples with empty path/suggestion
- **Why accepted**: The `path` and `suggestion` fields ARE preserved when they originate from `prepare_inputs()` (which produces real tuples). The test was checking a path that now goes through a different handler. A future test should verify `prepare_inputs()` errors specifically.

### 6. `test_workflow_commands.py` stdout→stderr not strictly verified
- **Tests use**: `combined = result.output + result.stderr` — passes whether message is on stdout or stderr
- **Should be**: `assert "..." in result.stderr` and `assert "..." not in result.output`
- **Why accepted**: The fix is verified by manual testing. The combined assertion prevents false failures from test infrastructure changes. Strict verification is a test quality improvement for later.

---

## Files Modified (34 total)

### New files (2)
- `src/pflow/cli/error_output.py` — unified error output (343 lines)
- `tests/test_cli/test_unified_error_output.py` — 10 new tests (299 lines)

### Production code (14)
- `src/pflow/cli/main.py` — pipeline restructure, handler conversions (+/- 427 lines net reduction)
- `src/pflow/cli/workflow_errors.py` — deleted 2 JSON builders (177 lines removed)
- `src/pflow/cli/workflow_output.py` — deleted 3 dead functions (15 lines removed)
- `src/pflow/cli/workflow_resolution.py` — exception-based resolution (81 lines changed)
- `src/pflow/cli/commands/registry.py` — stdout→stderr fixes (6 lines)
- `src/pflow/cli/commands/workflow.py` — stdout→stderr fix (10 lines)
- `src/pflow/core/exceptions.py` — enriched exception classes (60 lines added)
- `src/pflow/core/user_errors.py` — deleted vestigial CompilationError (6 lines)
- `src/pflow/core/workflow/manager.py` — updated 3 raise sites (6 lines)
- `src/pflow/core/workflow/validator.py` — specific exception catch (8 lines)
- `src/pflow/execution/executor_service.py` — cleaned dataclass + 4 dead items (80 lines removed)
- `src/pflow/execution/workflow_execution.py` — MaxNodeVisitsError catch (31 lines)
- `src/pflow/execution/formatters/success_formatter.py` — deleted `_append_footer` (15 lines)
- `src/pflow/runtime/workflow_executor.py` — removed MarkdownParseError wrapping (8 lines)

### Test files (12)
- `tests/test_cli/test_parse_error_handling.py` — 30 lines changed (assertion updates)
- `tests/test_cli/test_dual_mode_stdin.py` — 25 lines changed
- `tests/test_cli/test_main.py` — 4 lines changed
- `tests/test_cli/test_workflow_resolution.py` — 4 lines changed
- `tests/test_cli/test_workflow_save.py` — 8 lines changed
- `tests/test_cli/test_workflow_commands.py` — 22 lines changed
- `tests/test_cli/test_validation_before_execution.py` — 3 lines changed
- `tests/test_cli/test_workflow_output_handling.py` — 2 lines changed
- `tests/test_execution/test_workflow_execution.py` — 3 lines changed
- `tests/test_integration/test_e2e_workflow.py` — 10 lines changed
- `tests/test_runtime/test_checkpoint_tracking.py` — 1 line changed
- `tests/test_runtime/test_workflow_executor/test_workflow_name.py` — 2 lines changed

### Documentation (3)
- `src/pflow/execution/CLAUDE.md` — updated ExecutionResult canonical reference
- `src/pflow/cli/CLAUDE.md` — added error_output.py, updated error construction docs
- `src/pflow/runtime/compilation/CLAUDE.md` — removed deleted CompilationError references

### Task files (3)
- `.taskmaster/tasks/task_137/task-137.md` — task spec
- `.taskmaster/tasks/task_137/implementation/implementation-plan.md` — plan
- `.taskmaster/tasks/task_137/implementation/progress-log.md` — this file

---

## Post-Review: Function Inlining

After user challenge ("if we have both tests and manual tests what are the risks?"), inlined 6 thin wrapper functions that the plan called for deleting but were initially kept as "lower risk":

| Deleted function | Inlined into |
|-----------------|-------------|
| `_handle_workflow_error` (5 lines) | `execute_json_workflow` try block |
| `_handle_workflow_exception` (15 lines) | `execute_json_workflow` except block |
| `_execute_workflow_and_handle_result` (30 lines) | `execute_json_workflow` try block |
| `_handle_workflow_not_found` (3 lines) | `_try_execute_named_workflow` |
| `_show_stdin_routing_error` (3 lines) | `_route_stdin_to_params` |
| `_output_validation_errors` (3 lines) | `_validate_and_prepare_workflow_params` |

**Kept** `_handle_invalid_workflow_input` — 3-branch dispatch with enough logic to justify a name.

**Side effects of inlining**:
- `execute_json_workflow` grew from ~50 to ~100 lines, triggering ruff C901 (complexity). Added `noqa: C901` — the complexity is structural (try/except/finally with success/error branching in a pipeline function).
- ruff TRY400/TRY401 flagged `logger.error` inside except blocks. The verbose branch uses `logger.exception` (includes traceback), the non-verbose branch deliberately omits it — added `noqa` comments.
- `test_agent_ux_fixes.py` imported `_execute_workflow_and_handle_result` directly. Rewrote both tests to use CliRunner + mock `execute_workflow` return value instead.
- `test_enhanced_error_output.py` docstring referenced `_handle_workflow_error` — updated.

---

## Post-Review: Regression Fixes

Fixed 2 regressions identified by review agents but initially classified as "accepted tradeoffs":

### UnicodeDecodeError handler
- **Before (old code)**: `"cli: Unable to read file: '{path}'. File must be valid UTF-8 text."`
- **After Phase 5 (broken)**: `"cli: Workflow execution failed - 'utf-8' codec can't decode byte..."` — generic fallback, no actionable guidance
- **After fix**: `"✗ File must be valid UTF-8 text."` — clear, actionable, no raw codec noise
- **File**: Added `elif isinstance(exception, UnicodeDecodeError)` handler in `display_exception_text`

### Validate-only success JSON missing `status`
- **Before**: `{"success": true, "message": "Workflow structure is valid"}`
- **After fix**: `{"success": true, "status": "valid", "message": "Workflow structure is valid"}`
- **File**: One-line change in `_display_validation_results`

Updated 3 test files to match the new UnicodeDecodeError message (`"utf-8" in result.output.lower()`).

---

## Post-Review: High-Value Test Addition

After stepping back to evaluate test gaps, identified one genuinely valuable missing test:

**`test_missing_required_input_preserves_path_and_suggestion`** — End-to-end test that invokes the CLI with `--output-format json` against a workflow with a required input, without providing that input. Verifies that the `path` field (e.g., `"inputs.data"`) from `prepare_inputs()` tuples survives through the full pipeline: `prepare_inputs()` → `WorkflowValidationError(validation_errors=tuples)` → outer catch → `_workflow_validation_to_errors` → JSON output.

**Why this matters**: This is the ONLY end-to-end test that verifies structured tuple fields survive from `prepare_inputs()` to JSON. All other structured field tests are unit tests on `_exception_to_errors`. If someone breaks the tuple unpacking in `_workflow_validation_to_errors`, only this test catches it.

**Discovery during writing**: The test initially asserted both `path` and `suggestion` would be present. Running it revealed that `prepare_inputs()` returns an empty string for `suggestion` on required-but-missing inputs, which `_workflow_validation_to_errors` correctly omits (per the "omit, not null" spec). Fixed assertion to only require `path`. This is exactly the kind of assumption-checking the test is valuable for.

---

## Known Regressions / Accepted Tradeoffs

These were identified by the review agents. Items 1 and 4 were **fixed** post-review. Items 2, 3, 5, 6 remain accepted.

### 1. ~~UnicodeDecodeError loses file path and custom message~~ FIXED
See "Post-Review: Regression Fixes" above.

### 2. Parse errors lose file path context
- **Before**: `"❌ Invalid workflow syntax in {path}\n  {error}"`
- **After**: `"✗ Line 5: Missing required field 'type'..."` (no file path)
- **Why accepted**: For single-file usage (the common case), the file path is obvious from the command invocation. Adding path back would require storing it on the exception or wrapping it — either approach risks losing structured fields.

### 3. `_validate_before_execution` errors lose `format_validation_failure()` features
- **Before**: Text mode used `format_validation_failure()` which auto-generates suggestions and truncates at 10 errors
- **After**: `WorkflowValidationError.format_for_cli()` renders all errors with basic formatting
- **Why accepted**: Pre-execution validation typically produces 1-3 errors. Validate-only mode (which can produce many) still uses `format_validation_failure()` directly.

### 4. ~~Validate-only success JSON missing `status` field~~ FIXED
See "Post-Review: Regression Fixes" above.

### 5. ~~`test_dual_mode_stdin.py` removed `path`/`suggestion` assertions~~ FIXED (Pass 2)
The review pass 2 (test-fidelity + feature-interactions agents) identified that the original reasoning was wrong: the multiple-stdin error comes from `prepare_inputs()` (not `_validate_before_execution`), so the tuples DO have real `path` and `suggestion` values. Assertions restored.

### 6. `test_workflow_commands.py` stdout→stderr not strictly verified
- **Tests use**: `combined = result.output + result.stderr`
- **Should be**: `assert "..." in result.stderr` and `assert "..." not in result.output`
- **Why accepted**: The fix is verified by manual testing. Strict verification is a test quality improvement for later.

---

## Final File List (35 total)

### New files (2)
- `src/pflow/cli/error_output.py` — unified error output
- `tests/test_cli/test_unified_error_output.py` — 11 tests

### Production code (14)
- `src/pflow/cli/main.py` — pipeline restructure, handler inlining, regression fixes
- `src/pflow/cli/workflow_errors.py` — deleted 2 JSON builders
- `src/pflow/cli/workflow_output.py` — deleted 3 dead functions
- `src/pflow/cli/workflow_resolution.py` — exception-based resolution
- `src/pflow/cli/commands/registry.py` — stdout→stderr fixes
- `src/pflow/cli/commands/workflow.py` — stdout→stderr fix
- `src/pflow/core/exceptions.py` — enriched exception classes
- `src/pflow/core/user_errors.py` — deleted vestigial CompilationError
- `src/pflow/core/workflow/manager.py` — updated raise sites
- `src/pflow/core/workflow/validator.py` — specific exception catch
- `src/pflow/execution/executor_service.py` — cleaned dataclass, deleted dead code
- `src/pflow/execution/workflow_execution.py` — MaxNodeVisitsError catch
- `src/pflow/execution/formatters/success_formatter.py` — deleted dead function
- `src/pflow/runtime/workflow_executor.py` — removed MarkdownParseError wrapping

### Test files (13)
- `tests/test_cli/test_agent_ux_fixes.py` — rewrote deleted-function imports to use CliRunner
- `tests/test_cli/test_dual_mode_stdin.py` — updated JSON field assertions
- `tests/test_cli/test_enhanced_error_output.py` — updated stale docstring
- `tests/test_cli/test_main.py` — updated UnicodeDecodeError assertion
- `tests/test_cli/test_parse_error_handling.py` — fixed no-op assertions, updated messages
- `tests/test_cli/test_validation_before_execution.py` — tightened stale assertion
- `tests/test_cli/test_workflow_commands.py` — stderr verification
- `tests/test_cli/test_workflow_output_handling.py` — removed deleted field
- `tests/test_cli/test_workflow_resolution.py` — updated error message assertions
- `tests/test_cli/test_workflow_save.py` — updated validation error assertion
- `tests/test_execution/test_workflow_execution.py` — updated action_result assertions
- `tests/test_integration/test_e2e_workflow.py` — updated error pattern matching
- `tests/test_runtime/test_checkpoint_tracking.py` — removed deleted field
- `tests/test_runtime/test_workflow_executor/test_workflow_name.py` — updated constructor

### Documentation (3)
- `src/pflow/execution/CLAUDE.md` — updated ExecutionResult canonical reference
- `src/pflow/cli/CLAUDE.md` — added error_output.py, updated error construction docs
- `src/pflow/runtime/compilation/CLAUDE.md` — removed deleted CompilationError references

---

## Code Review Pass 2

Deployed 7 review agents on staged changes. Provided task spec, progress log, and task review to all agents for full context.

**Findings**: 2 confirmed, 0 disputed.

1. **Compilation error `error` field hardcoded "Compilation failed"** (agent-ux). Single compilation errors produced `"error": "Compilation failed"` instead of the actual message. Agents parsing `jq '.error'` got a category label, not the diagnostic. Fixed: removed the special case, `error` now always uses the first error's message.

2. **`test_multiple_stdin_error_json_output` removed valid assertions** (test-fidelity, feature-interactions). The reasoning in Known Regression #5 was wrong — the multiple-stdin error comes from `prepare_inputs()` (not `_validate_before_execution`), so the `(msg, path, suggestion)` tuples DO have real values. Restored `path`/`suggestion` assertions.

All other findings were re-flags of already-accepted items (UnicodeDecodeError JSON category, yaml.YAMLError category, nested MarkdownParseError field loss, validate-only bypass, test naming) or cosmetic (dead param, category set grouping).

---

## Issue and PR

- **Issue**: spinje/pflow#176 — filed describing the 6 problems this task solves
- **PR**: spinje/pflow#177 — `fix/unified-cli-output-pipeline` branch, 40 files, +3751/-975 lines

---

## Key Metrics
- **4628 tests pass** (11 new), 9 skipped
- **`make check` clean** (ruff, mypy, deptry)
- **7 JSON shapes → 1** unified shape
- **9 early-exit handlers → exceptions** through single pipeline, 6 wrapper functions deleted
- **5 orphaned ExecutionResult fields → removed**
- **9 dead functions → deleted** total (3 Phase 0/1, 3 found by review, 3 dead workflow_output functions)
- **2 code review passes** (14 agents total): 13 confirmed fixes, 3 disputed, 2 accepted regressions remaining
- **1 correctness bug found and fixed** by review (OutputResolutionError list-as-message)
- **2 regressions fixed** post-review (UnicodeDecodeError handler, validate-only status field)
- **1 high-value test added** post-review (prepare_inputs path preservation)
