# Task 137: Unified CLI Output Pipeline

## Description

Restructure the CLI output layer so ALL outcomes (success, execution failure, pre-execution error, exception) flow through one result type and one formatter. Eliminates 7 divergent JSON shapes, 9 ad-hoc early-exit error handlers, and systematic exception data loss.

## Status

not started

## Priority

high

## Problem

The CLI output layer has four separate pipelines that produce incompatible output:

1. **Success**: `ExecutionResult` -> `format_execution_success()` -> dict -> JSON. Works well.
2. **Execution failure** (ExecutionResult.success=False): `_build_json_error_response()` -> different dict shape -> JSON. `error` is a string.
3. **Unhandled exception**: `_create_json_error_output()` -> yet another dict shape -> JSON. `error` is a dict.
4. **Pre-execution error** (9 different handlers): `click.echo(text)` + `ctx.exit(1)`. No JSON at all.

This produces **7 different JSON shapes** with incompatible field types:
- `error` field: dict in one path, string in all others
- `metadata` vs `workflow`: same data, different key names
- `validation_errors` (strings) vs `errors` (dicts): different keys, different inner types
- `is_error: true` exists only in one path, redundant with `success: false`
- `status` field missing from most error paths

Additionally, structured exception data is systematically lost:
- `ValidationError` has `path` and `suggestion` fields — lost when caught as generic `Exception`
- `MaxNodeVisitsError` has `node_id`, `visit_count`, `max_visits` — all lost in catch chain
- `MarkdownParseError` has `line` and `suggestion` — lost when wrapped in `ValueError(str(e))`

### Root cause

The success path works because it has a clean data pipeline: one data type (`ExecutionResult`), one formatter, one serializer. Error paths have no equivalent — each handler constructs its own ad-hoc output.

### Prior work

This emerged from a thorough architectural debt audit (PRs #167, #170, #173, #175) that resolved Issues 1, 3, 9 and partially resolved Issues 4, 7, 10 from `scratchpads/architectural-debt/compounding-issues.md`. This task addresses the remaining structural debt in the output layer, superseding Task 117 (JSON error output) which proposed adding a central function on top of the existing mess — a bandaid rather than a fix.

## Solution

Four interconnected layers, implemented together:

### Layer 1: Clean ExecutionResult

Remove 5 orphaned fields that are populated but never read by any consumer:
- `action_result` (only surviving use: 2 integration tests assert `"compilation_failed"`, but same info is in `errors[0]["source"] == "compilation"`)
- `node_count` (consumers get this from IR)
- `duration` (consumers get this from MetricsCollector)
- `output_data` (consumers re-extract from `shared_after`)
- `metrics_summary` (consumers call `MetricsCollector.get_summary()` directly)

Remaining fields: `success`, `status`, `shared_after`, `errors`, `warnings`.

### Layer 2: Unified result type + single formatter

One result type that covers ALL outcomes. Either extend `ExecutionResult` or create a `WorkflowResult` wrapper. Delete `_create_json_error_output()` and `_build_json_error_response()` — replace with one formatter that produces a single JSON shape for all error types.

The unified JSON shape should mirror the success output as closely as possible:
```json
{
  "success": false,
  "status": "failed",
  "error": "Human summary",
  "errors": [{"message": "...", "category": "...", "suggestion": "...", "node_id": "..."}],
  "workflow": {"action": "...", "name": "..."},
  "execution": {...},
  "metrics": {...},
  "duration_ms": ...
}
```

Key decisions:
- `error` is always a string (human-readable summary), never a dict
- `errors` is always an array of objects (detailed structured errors)
- `workflow` is always present (may have null values for early CLI errors)
- `status` is always present (success/degraded/failed)
- Execution/metrics fields are omitted (not null) when not applicable
- Remove `is_error` (redundant with `success: false`)
- Remove `validation_errors` and `metadata` keys (use `errors` and `workflow` consistently)

### Layer 3: Pipeline pattern in main.py

Convert 9 early-exit error handlers from `click.echo() + ctx.exit(1)` to exception raises. One top-level try/catch converts exceptions to the unified result type, one output function formats and writes.

Today:
```python
# 9 functions like this, each with its own formatting
def _handle_workflow_not_found(ctx, ...):
    click.echo("Workflow not found...", err=True)
    ctx.exit(1)
```

After:
```python
try:
    ir, source = resolve_workflow(name_or_path)
    params = prepare_inputs(ir, raw_params, stdin)
    validate(ir, params)
    result = execute(ir, params)
except PflowError as e:
    result = WorkflowResult.from_error(e)

output(ctx, result, format=output_format)
```

Verified safe: none of the 14 early-exit functions do cleanup before exiting — all cleanup is in `finally` blocks. Each is called from exactly one place (except `_resolve_file_refs_or_exit` which is called from 2).

### Layer 4: Fix exception data loss

Preserve structured fields that are currently destroyed in the catch chain:

- **ValidationError**: Catch specifically in `validator.py` (currently caught as generic `Exception` at line 131). Preserve `path` and `suggestion` fields.
- **MaxNodeVisitsError**: Catch in `workflow_execution.py` alongside `CompilationError`. Extract `node_id`, `visit_count`, `max_visits` into error dict.
- **MarkdownParseError**: Stop wrapping in `ValueError(str(e))` in `workflow_executor.py:376`. Catch specifically and preserve `line` and `suggestion`.

## Design Decisions

- **Layers 1-4 together, not incrementally**: They're interconnected — restructuring the catch chain (Layer 3) is the natural time to fix data loss (Layer 4), and both need the unified result type (Layer 2) which benefits from the clean dataclass (Layer 1).
- **Layer 5 (formatter deduplication) AFTER, not before**: Deduplicating `_find_auto_output()`, step formatting, etc. (Task 134 territory) is easier after the pipeline is restructured. Doing it first would mean carefully merging code that's about to be replaced.
- **Extend or wrap ExecutionResult, don't replace**: The name and import paths are used across CLI, MCP, formatters, and ~15 test files. Wrapping preserves compatibility.
- **Text display functions stay**: `_display_single_error()`, `_display_shell_error_details()`, `_display_api_error_response()`, `_display_mcp_error_details()` work well. They become the text-mode branch of the unified formatter.
- **MCP server not in scope**: MCP always returns text (not JSON) and has its own error handling. Unifying MCP is Issue 6 (entry point unification), which this task enables but doesn't attempt.
- **Registry run not in scope**: Doesn't use `ExecutionResult` at all — separate execution path.
- **No functionality loss**: All existing error messages, suggestions, shell details, API responses continue to display. Text mode output is unchanged or improved.
- **Enhanced error fidelity**: `ValidationError`, `MaxNodeVisitsError`, and `MarkdownParseError` gain structured fields in JSON output. 9 pre-execution error paths gain JSON support.

## Dependencies

None. This is the next priority after the architectural debt sweeps (PRs #167, #170, #173, #175).

## Requirements

### Unified JSON shape

- All error JSON output uses ONE structure (no more 7 shapes)
- `error` field is always a string, never a dict
- `errors` field is always an array of objects with at minimum `message` and `category`
- `workflow` field replaces `metadata` everywhere
- `status` field present on all outputs (success, degraded, failed)
- `is_error` field removed
- `validation_errors` key removed (use `errors` array)
- Optional fields (`execution`, `metrics`, `duration_ms`) omitted when not applicable

### Pipeline pattern

- All pre-execution errors in main.py produce proper JSON when `--output-format json` is set
- The 9 early-exit handlers are replaced by exceptions + one catch block
- Exit codes preserved: 0=success, 1=error, 2=degraded
- `finally` blocks (trace saving, resource cleanup) continue to run
- `handle_sigint` (signal handler) unchanged — not part of the pipeline
- **Pre-initialization safety**: `_inject_settings_env_vars()` runs BEFORE `_initialize_context()`, so errors can occur before `ctx.obj["output_format"]` exists. The unified error handler must safely handle `ctx.obj` being empty/None (use `ctx.obj.get("output_format", "text")` or override parameter).
- **`sys.exit()` normalization**: `_perform_validation()` and `_display_validation_results()` use `sys.exit()` instead of `ctx.exit()`, skipping `ctx.close()` callbacks. Normalize to exception raises (or `ctx.exit()`) during restructuring.
- **`click.exceptions.Exit` handling**: Current `except Exception` block at main.py:835 has `if isinstance(e, click.exceptions.Exit): raise` because `ctx.exit(1)` raises Click's Exit which would otherwise be caught. After restructuring, the pipeline catch should only catch pflow exceptions (e.g., `except PflowError`), making this re-raise pattern unnecessary.

### Exception data preservation

- `ValidationError.path` and `ValidationError.suggestion` available in JSON error output
- `MaxNodeVisitsError.node_id`, `visit_count`, `max_visits` available in JSON error output
- `MarkdownParseError.line` and `MarkdownParseError.suggestion` available in JSON error output
- `CompilationError` structured fields continue to be preserved (already working)
- `UserFriendlyError` structured fields continue to be preserved (already working)

### ExecutionResult cleanup

- Remove `action_result`, `node_count`, `duration`, `output_data`, `metrics_summary` fields
- All existing tests pass after field removal (mechanical updates only)

### No regressions

- Text mode output unchanged or improved (never degraded)
- All existing error messages, suggestions, and contextual details preserved
- CLI exit codes unchanged
- `make test` and `make check` pass
- MCP server unaffected
- Registry run unaffected

### New tests required

- JSON output for each error category: validation, compilation, runtime, CLI (file not found, parse error, bad params)
- Pre-initialization error handling (error before `ctx.obj["output_format"]` is set)
- Structured field preservation: `ValidationError.path`/`.suggestion`, `MaxNodeVisitsError.node_id`, `MarkdownParseError.line`/`.suggestion` in JSON output
- Text output regression: existing error display unchanged for key error types
- Unified JSON shape: all error paths produce output parseable by `jq '.success, .status, .error, .errors[0].message, .workflow'`

### Bug fixes (from Task 117 audit)

- `registry.py:_handle_nonexistent_path()` — fix stdout→stderr for both JSON and text branches
- `registry.py:_handle_scan_error()` — fix stdout→stderr for JSON branch
- `workflow.py` lines 48-55 — fix stdout→stderr for filter-no-match message

## Implementation Notes

### Files to modify

| File | Changes |
|------|---------|
| `src/pflow/execution/executor_service.py` | Remove 5 orphaned fields from `ExecutionResult` dataclass and `_build_execution_result()` |
| `src/pflow/execution/workflow_execution.py` | Catch `MaxNodeVisitsError` alongside `CompilationError`. Remove `action_result="compilation_failed"` from CompilationError wrapping |
| `src/pflow/cli/main.py` | Replace 9 early-exit handlers with exception raises. Add top-level try/catch. Unify output routing. |
| `src/pflow/cli/workflow_errors.py` | Delete `_create_json_error_output()` and `_build_json_error_response()`. Replace with one unified error formatter. |
| `src/pflow/cli/workflow_output.py` | Minor — route both success and error through shared output function |
| `src/pflow/core/workflow/validator.py` | Catch `ValidationError` specifically at line ~131 instead of bare `Exception` |
| `src/pflow/runtime/workflow_executor.py` | Stop wrapping `MarkdownParseError` in `ValueError(str(e))` at line ~376 |
| `src/pflow/cli/commands/registry.py` | Fix 3 stdout→stderr bugs |
| `src/pflow/cli/commands/workflow.py` | Fix 1 stdout→stderr bug |

### Dead code to remove during refactor

- `success_formatter.py:478` — `_append_footer()` (defined, never called)
- `core/user_errors.py:112` — vestigial `CompilationError(UserFriendlyError)` (0 raise sites). Once removed, also clean up the `CompilerCompilationError` alias in main.py (exists only to disambiguate from the vestigial one)
- `workflow_errors.py` — `verbose` parameter threading (accepted but never used for gating)
- `workflow_execution.py:10` — unused `logger`
- Triple `cleanup_llm_interception()` calls (normal path, exception path, finally) — collapses to just the `finally` block during pipeline restructuring

### Exception types for CLI-level errors (design decision — must resolve before implementation)

The 9 early-exit handlers need exception types to raise. Current mapping:

| Handler | Suggested exception type | Rationale |
|---------|-------------------------|-----------|
| `_handle_workflow_not_found` | `WorkflowNotFoundError` (exists, needs structured fields added: `workflow_name`, `similar_names`) | Direct semantic match |
| `_handle_invalid_workflow_input` | `UserFriendlyError` | Guidance-heavy output fits what/why/how pattern |
| `_validate_before_execution` | `WorkflowValidationError` (exists, needs `errors: list` field) | Direct semantic match |
| `_show_stdin_routing_error` | `WorkflowValidationError` | Stdin routing is a validation concern |
| `_output_validation_errors` | `WorkflowValidationError` | Direct match |
| `_resolve_file_refs_or_exit` | Re-raise `FileNotFoundError`/`YAMLError` (already exceptions — stop catching them here) | These are already exceptions; the handler catches and converts to text unnecessarily |
| `_validate_workflow_flags` | `click.UsageError` | Click's built-in type for CLI flag errors |
| `_preprocess_run_prefix` | `click.UsageError` | Click's built-in type for usage guidance |
| `_perform_validation` / `_display_validation_results` | Return result or raise `WorkflowValidationError` | Validate-only mode — may need special handling for exit code 0 (valid) |

Key principle: reuse existing exceptions where possible, add structured fields to `WorkflowNotFoundError` and `WorkflowValidationError`, use `UserFriendlyError` for guidance-heavy messages. Avoid creating new exception classes unless no existing type fits.

### Silent data holes to fix opportunistically

- `workflow_output.py:321` — bare `except Exception: pass` swallows output population errors silently. At minimum log a warning.
- `validator.py:131` — catches `Exception` instead of `ValidationError`. Any crash during validation becomes a misleading "validation error" string.

### What NOT to touch

- Node implementations
- Compilation pipeline
- Execution pipeline (executor_service internals)
- MCP server error handling (Issue 6 scope)
- Registry run path (doesn't use ExecutionResult)
- Formatter deduplication — `_find_auto_output()` divergence, step formatting duplication (Task 134 / Layer 5)

## Verification

```bash
# All error paths produce valid JSON with unified structure:
uv run pflow --output-format json nonexistent.pflow.md        # CLI error: file not found
uv run pflow --output-format json malformed.pflow.md          # CLI error: parse error
echo "data" | uv run pflow --output-format json no-stdin.pflow.md  # Validation: stdin routing
uv run pflow --output-format json bad-node.pflow.md           # Compilation error
uv run pflow --output-format json failing-workflow.pflow.md   # Runtime error

# All should parse with same structure:
# jq '.success, .status, .error, .errors[0].message, .workflow'

# Text mode unchanged:
uv run pflow failing-workflow.pflow.md  # Same error display as before

# Tests pass:
make test && make check

# Structured fields preserved:
# ValidationError JSON output includes "path" and "suggestion" fields
# MaxNodeVisitsError JSON output includes "node_id" field
# MarkdownParseError JSON output includes "line" and "suggestion" fields
```

## References

### Research documents
- `scratchpads/architectural-debt/compounding-issues.md` — Issue 7 (error hierarchy + UX), Issue 4 (validation/runtime split)
- `scratchpads/handoffs/architectural-debt-fixes.md` — 5 completed sweeps, remaining items

### Supersedes
- Task 117 (JSON error output) — this task addresses the same problem but with a structural fix instead of a central function bandaid

### Related tasks
- Task 134 (output detection unification) — Layer 5, easier AFTER this task
- Task 135 (batch compile-once) — independent, no interaction

### Key code files (current state)
- `src/pflow/execution/executor_service.py:18-31` — `ExecutionResult` dataclass
- `src/pflow/execution/workflow_execution.py:13-92` — `execute_workflow()` bridge function
- `src/pflow/cli/main.py:1508-1651` — `workflow_command()` entry point
- `src/pflow/cli/workflow_errors.py` — two divergent JSON error builders (to be unified)
- `src/pflow/cli/workflow_output.py:736-761` — `_serialize_json_result()` (shared serializer, keep)
- `src/pflow/execution/formatters/success_formatter.py:12-112` — `format_execution_success()` (gold standard)
- `src/pflow/execution/formatters/error_formatter.py:16-113` — `format_execution_errors()` (shared error formatter)
- `src/pflow/core/exceptions.py` — PflowError hierarchy
- `src/pflow/core/user_errors.py` — UserFriendlyError (what/why/how pattern)
- `src/pflow/runtime/compilation/compiler.py:33-84` — CompilationError (the real one, rich fields)

### Research findings (from parallel agent searches)
- Exception topology: `scratchpads/architectural-debt/compounding-issues.md` and this conversation's agent outputs
- ExecutionResult consumers: CLI (5 fields read), MCP (4 fields read), formatters (3 fields read)
- Test blast radius: 18 `ExecutionResult` constructions across 4 test files, ~12 lines to change for orphaned field removal
