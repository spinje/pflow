# Task 137 Review: Unified CLI Output Pipeline

## Metadata
- Implementation Date: 2026-03-28 to 2026-03-29
- Supersedes: Task 117 (JSON error output)
- Enables: Task 134 (output detection), Issue 6 (entry point unification)

## Executive Summary

Restructured the CLI output layer from 7 divergent JSON shapes across 4 separate pipelines into one unified pipeline producing one shape. All pre-execution errors that previously output plain text even with `--output-format json` now produce valid JSON. Structured exception fields (`ValidationError.path`, `MaxNodeVisitsError.node_id`, `MarkdownParseError.line`) that were destroyed in catch chains now survive to output. ExecutionResult was cleaned of 5 orphaned fields. 9 dead functions deleted.

## Implementation Overview

### What Was Built

New `src/pflow/cli/error_output.py` — single entry point `output_error()` that handles JSON and text output for both exceptions and `ExecutionResult` failures. All early-exit handlers (`click.echo + ctx.exit(1)` pattern) converted to exception raises that propagate to a single catch block in `workflow_command`.

### Key Deviations from Plan

1. **Phase ordering**: The plan called for the outer `except Exception` catch in `workflow_command` to be added in Phase 6. Had to add it in Phase 5 because `resolve_workflow()` started raising exceptions. Tests must pass after every phase — can't defer the catch block.

2. **Function deletion strategy**: The plan called for deleting 7 functions into a new `_execute_workflow_pipeline`. Instead, I refactored them in-place first (lower risk), then inlined after the test suite was green (user challenged this — "if we have tests, what's the risk?" — and was right).

3. **Error category enum**: The plan listed only pre-execution categories. Post-execution categories from `executor_service._determine_error_category()` (`execution_failure`, `api_validation`, `resource_error`, `template_error`) also appear in the unified output and needed inclusion in tests.

4. **`OutputResolutionError.diagnostics`**: The plan assumed this was a string. It's `list[str]`. The code review caught this — would have produced `{"message": ["string1", "string2"]}` violating the `message: str` contract.

## Files Modified/Created

### Core Changes

- `src/pflow/cli/error_output.py` (NEW) — Unified error output. `output_error()` is the single entry point. `_exception_to_errors()` dispatches 10 exception types to focused helpers. `display_exception_text()` uses `format_for_cli()` protocol.
- `src/pflow/cli/main.py` — Largest change. 9 early-exit handlers converted to exception raises, 6 wrapper functions inlined, outer catch block added to `workflow_command`, inner pipeline in `execute_json_workflow` handles success/error inline.
- `src/pflow/cli/workflow_errors.py` — Deleted `_create_json_error_output()` and `_build_json_error_response()`. Only text-mode display functions remain.
- `src/pflow/cli/workflow_resolution.py` — `resolve_workflow()` raises exceptions instead of returning `(None, "parse_error")` tuples. `_try_load_workflow_from_file` returns `dict | None` instead of `tuple[dict | None, str | None]`.
- `src/pflow/core/exceptions.py` — `WorkflowNotFoundError`, `WorkflowValidationError`, `MaxNodeVisitsError` enriched with structured fields and `format_for_cli()` methods.
- `src/pflow/execution/executor_service.py` — `ExecutionResult` reduced from 10 to 5 fields. 4 dead functions deleted.
- `src/pflow/execution/workflow_execution.py` — Added `MaxNodeVisitsError` catch alongside `CompilationError`.
- `src/pflow/runtime/workflow_executor.py` — Removed `MarkdownParseError -> ValueError` wrapping. `parse_markdown()` exceptions propagate with structured fields intact.

### Test Files

- `tests/test_cli/test_unified_error_output.py` (NEW, 11 tests) — **Critical**: `_assert_unified_shape` validates the JSON contract, `test_missing_required_input_preserves_path_and_suggestion` is the end-to-end guard for structured field preservation.
- 13 existing test files updated for new error messages, JSON field names, and deleted function imports.

## Integration Points & Dependencies

### Incoming Dependencies

- `cli/main.py` -> `error_output.output_error()` — ALL error paths in the CLI now route here
- `cli/main.py` -> `exceptions.WorkflowNotFoundError` — raised by `resolve_workflow()` and `_try_execute_named_workflow`
- `cli/main.py` -> `exceptions.WorkflowValidationError` — raised by `_validate_before_execution` and `_validate_and_prepare_workflow_params`

### Outgoing Dependencies

- `error_output.py` -> `workflow_output._serialize_json_result` — JSON serialization with custom type handling
- `error_output.py` -> `workflow_errors._display_text_error_details` — text-mode display for `ExecutionResult` failures
- `error_output.py` -> `execution.formatters.error_formatter.format_execution_errors` — sanitization and execution state extraction

### Load-Bearing Interfaces

- **`prepare_inputs()` return format**: Returns `list[tuple[str, str, str]]` where each tuple is `(message, path, suggestion)`. This flows through `WorkflowValidationError.validation_errors` to `_workflow_validation_to_errors`. Breaking the tuple format silently drops `path`/`suggestion` from JSON output.
- **`format_for_cli()` protocol**: Exceptions with this method get their text display from it. New exceptions should implement this.
- **Unified JSON shape**: `{success: false, status: "failed", error: str, errors: [{message, category, ...}], workflow: {action}}`. The `error` field MUST be a string, never a dict.

## Key Architectural Insights

These are the deeper findings from the research phase that drove the design. Future agents working on Task 134 (output detection) or Issue 6 (entry point unification) need to understand these.

### Why Task 117's approach was wrong

Task 117 proposed adding a central `_output_cli_error()` function that all error paths would call. This is **additive** — it adds a new layer on top of the existing divergent code. The 2 old JSON builders and 6 inline JSON constructions would still exist, just wrapped. The root cause (no shared data layer for errors) wouldn't be addressed.

The right approach was **substitutive** — delete the divergent code and replace it with one pipeline. This is why Task 137 supersedes rather than implements Task 117.

### The success pipeline is the reference architecture

The success path works well because it has a clean data pipeline:
```
ExecutionResult → format_execution_success() → dict → _serialize_json_result()
```
One data type, one formatter, one serializer. The error paths had no equivalent — each of the 4 pipelines built its own ad-hoc dict with different field names, types, and structures.

The fix was giving errors the same architecture: structured exception → `_exception_to_errors()` → unified dict → `_serialize_json_result()`. Same pattern, same serializer, one shape.

### ExecutionResult divergence revealed a deeper problem

5 of 10 `ExecutionResult` fields were orphaned — populated but never read. This wasn't just dead code. It revealed that the dataclass and its consumers had **evolved independently**: `ExecutionResult` was designed as a comprehensive carrier, but consumers evolved to pull the same data from other sources (shared store, metrics collector). The data model and its usage had drifted apart.

Cleaning it to 5 fields (success, status, shared_after, errors, warnings) makes the contract honest — these are the fields consumers actually depend on.

### Exception data loss was structural, not individual bugs

Three separate exception types (`ValidationError`, `MaxNodeVisitsError`, `MarkdownParseError`) had structured fields that were destroyed by catch chains. This wasn't three bugs — it was a **structural pattern**: generic `except Exception` or `except ValueError` catches calling `str(e)` on exceptions that carry richer data than their string representation.

The fix addresses the pattern, not just the instances: `workflow_execution.py` now catches specific types and extracts structured fields, while `_exception_to_errors()` uses `isinstance` to dispatch to type-specific handlers that preserve fields.

### The 5-layer model

The research identified 5 layers of the output refactor:
1. Clean ExecutionResult (data model)
2. Unified result type + single formatter (output layer)
3. Pipeline pattern in main.py (control flow)
4. Fix exception data loss at catch sites (catch chain)
5. Deduplicate formatters — `_find_auto_output()`, step formatting (Task 134)

**Layers 1-4 had to be done together** because they're interconnected: restructuring the catch chain (3) requires the unified formatter (2) which benefits from the clean dataclass (1), and fixing data loss (4) at catch sites feeds into the pipeline (3).

**Layer 5 was deliberately deferred** because deduplicating formatters BEFORE restructuring the pipeline means carefully merging code that's about to be replaced. Layer 5 is easier after Layers 1-4 because there's now one clear pipeline with clean boundaries.

### Sentinels vs exceptions

`resolve_workflow()` returned `(None, "parse_error")` — a sentinel value that callers had to check. This was an entire bug class: the `"parse_error"` sentinel was checked in `_handle_workflow_not_found` to silently exit (because the error was "already displayed" by the resolution layer). Mixing display logic into the resolution layer and using sentinel values for control flow created fragile coupling.

Converting to exceptions separates detection (raise) from display (catch + format) from exit (single point). The resolution layer never calls `click.echo`. The catch block in `workflow_command` handles all display. This is a pattern that should be followed for any new pre-execution error path.

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **Exception-based error propagation over return-value sentinels**. See "Sentinels vs exceptions" above. Eliminated an entire class of "forgot to check the sentinel" bugs.

2. **Single `output_error()` over format-specific functions**. The old system had `_create_json_error_output` (exceptions -> JSON), `_build_json_error_response` (ExecutionResult -> JSON), `_display_text_error_details` (ExecutionResult -> text), and ad-hoc `click.echo` (exceptions -> text). Now one function handles all 4 combinations.

3. **`noqa: C901` on `execute_json_workflow` and `_exception_to_errors`**. After inlining, `execute_json_workflow` has inherent structural complexity (try/except/finally with success/error branching). The `_exception_to_errors` dispatcher checks 10 types. Both are irreducible — suppressing C901 is the right call.

4. **`sys.exit()` kept in `_display_validation_results`**. Four review agents flagged this. Converting to `ctx.exit()` would raise `click.exceptions.Exit` which hits the outer catch and calls `output_error()` again — duplicating output. The validate-only JSON error path already conforms to the unified shape.

### Technical Debt Incurred

- **Parse errors lose file path context**: Old code showed `"Invalid workflow syntax in {path}"`. New code shows just the `MarkdownParseError` message. Fixing requires storing path on the exception or wrapping without losing structured fields.
- **`_display_validation_results` bypasses unified pipeline**: Uses `sys.exit()` and inline `json.dumps()` instead of `output_error()`. Works correctly but is a structural inconsistency.

## Testing Implementation

### Critical Test Cases

- `test_missing_required_input_preserves_path_and_suggestion` — End-to-end guard for THE core bug: `prepare_inputs()` tuple fields surviving through `WorkflowValidationError` → `_exception_to_errors` → JSON. The only test that catches broken tuple unpacking.
- `_assert_unified_shape` helper (used by 5 tests) — Validates the unified JSON contract including forbidden old fields (`is_error`, `validation_errors`, `metadata`, `failed_node`, `checkpoint`).
- `test_workflow_not_found_produces_json` and `test_error_field_is_string_not_dict` — Direct regression guards for the two core bugs this task fixes.

### Tests That Caught Real Issues During Development

- ruff C901 on `_exception_to_errors` (complexity 26) forced extraction into helper functions — better code.
- ruff TRY203 on redundant `except MarkdownParseError: raise` forced removing the entire try-except — cleaner code.
- The `test_missing_required_input` test initially asserted `suggestion` would be present — running it revealed `prepare_inputs()` returns empty suggestion for required-but-missing inputs. Not a bug, but validated the assumption.

## Unexpected Discoveries

### Gotchas Encountered

- **`OutputResolutionError.diagnostics` is `list[str]`, not `str`**. The plan and initial implementation both assumed string. Code review caught this — would have produced `{"message": ["a", "b"]}` in production.
- **Pre-initialization error handling**: If `_inject_settings_env_vars()` throws before `ctx.obj` is set, the outer catch must use the local `output_format` parameter (from Click decorator), not `ctx.obj.get("output_format")`. One-line fix but easy to miss.
- **`MarkdownParseError` extends `ValueError`**: This means `UnicodeDecodeError` (also extends `ValueError`) could be accidentally caught by a `ValueError` handler. The duck-type check `isinstance(e, ValueError) and hasattr(e, "line")` was fragile — replaced with proper isinstance via helper function.

## Patterns Established

### Reusable Patterns

**Exception → unified JSON conversion**: Add a handler in `_exception_to_errors()` for any new exception type. Follow the subclass-before-parent ordering. Extract a `_foo_to_errors()` helper if the conversion has any branching. The generic fallback produces `category: "unknown"`.

**`format_for_cli()` protocol**: Exceptions that implement `format_for_cli() -> str` get their text display from it automatically. `display_exception_text()` checks for this method via `hasattr`. New enriched exceptions should implement it.

**Error handler conversion pattern**: Replace `click.echo(..., err=True) + ctx.exit(1)` with `raise SomeException(...)`. The outer catch in `workflow_command` handles display and exit. This applies to any new pre-execution error path added to main.py.

### Anti-Patterns to Avoid

- **Don't add `click.echo + ctx.exit(1)` for new error paths in main.py**. All errors should be exceptions that propagate to the outer catch. Adding inline error display bypasses the unified pipeline and breaks `--output-format json`.
- **Don't catch exceptions just to re-wrap them as strings**. The old `except MarkdownParseError as e: raise ValueError(str(e))` pattern destroyed structured fields. Let exceptions propagate or catch them specifically.
- **Don't use `"validation_errors"`, `"is_error"`, `"metadata"`, `"failed_node"` keys in JSON output**. These are the old shape. Use `"errors"` (list of dicts), `"success"`, `"workflow"`.

## Breaking Changes

### JSON Output Shape Changes

Old exception-path JSON: `{"success": false, "error": {"type": "...", "message": "..."}, "workflow": {...}}`
New: `{"success": false, "status": "failed", "error": "string summary", "errors": [{"message": "...", "category": "..."}], "workflow": {...}}`

Old ExecutionResult-path JSON: `{"success": false, "is_error": true, "error": "...", "errors": [...], "failed_node": "..."}`
New: `{"success": false, "status": "failed", "error": "string summary", "errors": [...], "workflow": {...}}`

Key difference: `error` is always a **string** now (was sometimes a dict). `is_error`, `failed_node`, `validation_errors`, `metadata` keys are gone.

### ExecutionResult Field Removal

Removed: `action_result`, `node_count`, `duration`, `output_data`, `metrics_summary`. All had zero read sites. Any code accessing these will get `AttributeError`.

### WorkflowNotFoundError Constructor Change

Old: `WorkflowNotFoundError("Workflow 'name' not found")` (single string message)
New: `WorkflowNotFoundError(workflow_name, similar_names=[], hint=None)` (structured)

All 3 raise sites in `manager.py` updated. `str(exception)` still produces `"Workflow 'name' not found"` for backward compatibility.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/cli/error_output.py` first — it's the hub
2. Read `src/pflow/core/exceptions.py` for the `format_for_cli()` protocol
3. Run `uv run pflow --output-format json nonexistent.pflow.md` to see the unified shape
4. The test `tests/test_cli/test_unified_error_output.py::_assert_unified_shape` IS the JSON contract

### Common Pitfalls

- **Adding new exception types**: Must add a handler in `_exception_to_errors()` or they fall to `category: "unknown"`. Check subclass ordering.
- **Modifying `prepare_inputs()` return format**: The `(msg, path, suggestion)` tuple format is load-bearing. Changing it silently breaks JSON field preservation. The `test_missing_required_input_preserves_path_and_suggestion` test guards this.
- **Testing JSON error output**: Use `CliRunner` with `--output-format json`. The `_assert_unified_shape` helper validates the full contract. Import it or copy the checks.
- **validate-only mode**: Bypasses the unified pipeline via `sys.exit()`. Changes to error output there must be made in `_display_validation_results`, not `output_error()`.

### Test-First Recommendations

When modifying error output:
1. Run `pytest tests/test_cli/test_unified_error_output.py` — validates JSON shape contract
2. Run `pytest tests/test_cli/test_parse_error_handling.py` — validates text-mode error display
3. Run `pytest tests/test_cli/test_dual_mode_stdin.py -k json` — validates JSON mode for stdin errors
4. Manual: `uv run pflow --output-format json <your-error-case>` and pipe through `jq '.success, .error, .errors[0].category'`

---

*Generated from implementation context of Task 137*
